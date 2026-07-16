"""Learner State Model (file-backed).

This is the authoritative, persisted model of the student described in section 6.4
and 12.1 of the architecture. For the prototype it lives in a single JSON file:

    {
      "learner_id": "...",
      "concept_states": {
        "<concept_id>": {
          "mastery": 0.0-1.0,
          "misconceptions": ["..."],
          "representations_known": ["symbolic", ...],
          "hint_dependency": 0.0-1.0,
          "last_practiced": "ISO-8601"
        }
      },
      "global": { "confidence": .., "curiosity": .., "cognitive_load": .., "engagement": .. }
    }

query.py reads per-concept `mastery` to set the ZPD difficulty band, replacing the
static --level flag. Concepts the learner has never touched fall back to a
cold-start mastery so brand-new users still get a sensible (beginner) band.
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

COLD_START_MASTERY = 0.30  # unseen concept -> treat as near-beginner

# ---------------------------------------------------------------------------
# Struggle definition (hard thresholds)
# ---------------------------------------------------------------------------
# The concept cards carry metacognitive_prompts tagged `when: "after_success" |
# "after_struggle"` (plan Phase 1 step 2 / A1.4). "Struggle" is not left to the
# LLM's judgment — it is defined here as hard data the Pedagogical Decision
# Engine can act on. A learner is struggling on a concept when EITHER:
#   * they exhausted the hint chain on the current problem (all 3 hints), OR
#   * they failed the same diagnostic/probe twice in a row.
# apply_probe_result() computes this and persists it on the concept state, and
# returns `metacognitive_when` so the engine retrieves the right prompt.
STRUGGLE_HINT_THRESHOLD = 3   # hints used on one problem; hint chains have exactly 3
STRUGGLE_FAIL_THRESHOLD = 2   # consecutive failures on the same diagnostic

# Mastery write-back deltas for probe outcomes (bridge probes use +0.25/-0.10
# per plan Phase 3 step 7; ordinary misconception probes move mastery less).
PROBE_MASTERY_DELTA = {"correct": +0.15, "partial": +0.05, "wrong": -0.10}

# Part 12 (§5.3) — graded PRACTICE/TEST item deltas (the third evidence API,
# apply_item_result). Practice gains are discounted by hints used (same spirit as
# apply_probe_result); test items carry full weight. Per-item movement is bounded
# (behavioral eval: no single-item mastery jumps).
ITEM_MASTERY_DELTA = {"correct": +0.15, "partial": +0.05, "wrong": -0.08}
ITEM_HINT_DISCOUNT = 0.25   # each hint used shaves 25% off a positive gain (min 0.25x)
ITEM_HISTORY_MAX = 12       # outcomes kept per item (spaced-review / exclusion)
MASTERY_GATE_DEFAULT = 0.8  # Bloom/Rosenshine ~80% criterion (§4.4)

# Misconception status machine, architecture section 10 (plan A2.6):
# active -> weakening (1 correct probe) -> resolved (2 consecutive correct)
# resolved -> recurring (any later failure); recurring behaves like active.
RESOLVE_AFTER_CONSECUTIVE_CORRECT = 2

# ---------------------------------------------------------------------------
# Bridge policy contract (plan Phase 3 step 7 / A2.4)
# ---------------------------------------------------------------------------
# Grade-9 bridge concepts live in the same concept_states map under their
# `grade9::<slug>` ids; unseen bridges fall back to COLD_START_MASTERY (0.30),
# which is what makes a brand-new learner trigger every bridge once — the
# cheapest cold-start mastery probe. A bridge is ACTIVATED only when its mastery
# is below the threshold AND the learner's ZPD band center is below the advanced
# cutoff AND it was not already served this session; its diagnostic outcome is
# never display-only (apply_bridge_result writes mastery back).
BRIDGE_MASTERY_THRESHOLD = 0.6
BRIDGE_SKIP_ZPD_CENTER = 7.0
BRIDGE_MASTERY_DELTA = {"correct": +0.25, "partial": -0.10, "wrong": -0.10}


@dataclass
class LearnerState:
    path: Optional[Path]
    data: Dict[str, Any]

    @property
    def concept_states(self) -> Dict[str, Any]:
        return self.data.setdefault("concept_states", {})

    def mastery(self, concept_id: str) -> float:
        cs = self.concept_states.get(concept_id)
        if not cs:
            return COLD_START_MASTERY
        try:
            return max(0.0, min(1.0, float(cs.get("mastery", COLD_START_MASTERY))))
        except (TypeError, ValueError):
            return COLD_START_MASTERY

    def is_known(self, concept_id: str) -> bool:
        return concept_id in self.concept_states

    def misconceptions(self, concept_id: str) -> list:
        return (self.concept_states.get(concept_id) or {}).get("misconceptions", [])

    # ------------------------------------------------------------------
    # Snapshot accessors for the Phase-5 retrieval ranking (A2.1)
    # ------------------------------------------------------------------
    def hint_dependency(self, concept_id: str) -> float:
        cs = self.concept_states.get(concept_id) or {}
        try:
            return max(0.0, min(1.0, float(cs.get("hint_dependency", 0.0))))
        except (TypeError, ValueError):
            return 0.0

    def representations_known(self, concept_id: str) -> list:
        return (self.concept_states.get(concept_id) or {}).get("representations_known", [])

    def representations_missing(self, concept_id: str, concept_representations: list) -> list:
        """Representations the concept HAS that the learner has not yet shown."""
        known = set(self.representations_known(concept_id))
        return [r for r in (concept_representations or []) if r not in known]

    def misconception_status(self, misconception_id: str) -> str:
        return (self.misconception_states.get(misconception_id) or {}).get("status", "untracked")

    def misconception_failures(self, misconception_id: str) -> int:
        return int((self.misconception_states.get(misconception_id) or {}).get("consecutive_failures", 0))

    @property
    def hope_rolling(self) -> Dict[str, float]:
        """Rolling KI/KT/CT scores in [0,1]; 0.5 = neutral when unmeasured."""
        h = self.data.get("hope_rolling") or {}
        return {k: float(h.get(k, 0.5)) for k in ("KI", "KT", "CT")}

    def update_hope(self, signal: str, score_0_3: float, ema: float = 0.4) -> float:
        """Fold a HOPE detector score (ordinal 0-3) into the rolling KI/KT/CT
        average (architecture §6.4 hope_rolling, consumed by §6.7 ranking w7).

        The score is normalized to [0,1] (score/3) and EMA-blended with the
        prior rolling value (default 0.5). bridge probes map onto KT. Returns
        the new rolling value for that signal.
        """
        sig = {"bridge": "KT"}.get(signal, signal)
        if sig not in ("KI", "KT", "CT"):
            raise ValueError(f"signal must be KI/KT/CT (or bridge), got {signal!r}")
        h = self.data.setdefault("hope_rolling", {})
        old = float(h.get(sig, 0.5))
        new = (1.0 - ema) * old + ema * max(0.0, min(1.0, float(score_0_3) / 3.0))
        h[sig] = round(new, 4)
        return h[sig]

    @property
    def served_items(self) -> list:
        return self.data.setdefault("session", {}).setdefault("served_items", [])

    def mark_served(self, item_ids: list) -> None:
        for i in item_ids:
            if i not in self.served_items:
                self.served_items.append(i)

    def update_mastery(self, concept_id: str, new_mastery: float) -> None:
        cs = self.concept_states.setdefault(concept_id, {})
        cs["mastery"] = max(0.0, min(1.0, float(new_mastery)))
        cs["last_practiced"] = datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Misconception probe write-back + struggle signal
    # ------------------------------------------------------------------
    @property
    def misconception_states(self) -> Dict[str, Any]:
        return self.data.setdefault("misconception_states", {})

    def record_hint_request(self, concept_id: str, problem_id: str) -> int:
        """Count a hint request against the current problem; returns hints used so far.

        Resets automatically when the learner moves to a different problem, so the
        struggle test is always 'all 3 hints on ONE problem', not lifetime totals.
        Also updates the hint_dependency EMA the retrieval ranker consumes (w6).
        """
        cs = self.concept_states.setdefault(concept_id, {})
        if cs.get("current_problem_id") != problem_id:
            cs["current_problem_id"] = problem_id
            cs["hints_used_current"] = 0
        cs["hints_used_current"] = int(cs.get("hints_used_current", 0)) + 1
        used = cs["hints_used_current"]
        old = float(cs.get("hint_dependency", 0.0))
        cs["hint_dependency"] = round(0.7 * old + 0.3 * min(1.0, used / STRUGGLE_HINT_THRESHOLD), 4)
        return used

    def is_struggling(self, concept_id: str) -> bool:
        cs = self.concept_states.get(concept_id) or {}
        return bool((cs.get("struggle") or {}).get("struggling", False))

    def metacognitive_when(self, concept_id: str) -> str:
        """Which metacognitive prompt variant the engine should retrieve right now."""
        return "after_struggle" if self.is_struggling(concept_id) else "after_success"

    def apply_probe_result(
        self,
        misconception_id: str,
        outcome: str,
        concept_id: Optional[str] = None,
        hints_used: int = 0,
    ) -> Dict[str, Any]:
        """Write back one diagnostic-probe outcome (plan Phase 5 step 5 / A2.4 / A2.6).

        outcome: "correct" | "partial" | "wrong".
        hints_used: hints consumed on this probe's hint chain (0-3) — the hard
        struggle datum. Struggle is hints_used >= STRUGGLE_HINT_THRESHOLD or
        STRUGGLE_FAIL_THRESHOLD consecutive failures; the result tells the engine
        which metacognitive prompt ("after_struggle" / "after_success") to serve.
        """
        if outcome not in PROBE_MASTERY_DELTA:
            raise ValueError(f"outcome must be one of {sorted(PROBE_MASTERY_DELTA)}, got {outcome!r}")

        ms = self.misconception_states.setdefault(misconception_id, {
            "status": "active", "consecutive_correct": 0, "consecutive_failures": 0,
        })
        status = ms.get("status", "active")

        if outcome == "correct":
            ms["consecutive_correct"] = int(ms.get("consecutive_correct", 0)) + 1
            ms["consecutive_failures"] = 0
            if ms["consecutive_correct"] >= RESOLVE_AFTER_CONSECUTIVE_CORRECT:
                status = "resolved"
            elif status in ("active", "recurring"):
                status = "weakening"
        else:  # wrong or partial: the misconception is still biting
            ms["consecutive_correct"] = 0
            ms["consecutive_failures"] = int(ms.get("consecutive_failures", 0)) + 1
            if status == "resolved":
                status = "recurring"
            elif status == "weakening":
                status = "active"
        ms["status"] = status
        ms["last_probed"] = datetime.now(timezone.utc).isoformat()

        struggled = (
            int(hints_used) >= STRUGGLE_HINT_THRESHOLD
            or int(ms["consecutive_failures"]) >= STRUGGLE_FAIL_THRESHOLD
        )

        mastery = None
        if concept_id:
            mastery = max(0.0, min(1.0, self.mastery(concept_id) + PROBE_MASTERY_DELTA[outcome]))
            self.update_mastery(concept_id, mastery)
            cs = self.concept_states.setdefault(concept_id, {})
            cs["struggle"] = {
                "struggling": struggled,
                "hints_used_last": int(hints_used),
                "consecutive_failures": int(ms["consecutive_failures"]),
            }
            # Probe answered -> current problem is over; reset the per-problem counter.
            cs.pop("current_problem_id", None)
            cs["hints_used_current"] = 0

        return {
            "misconception_id": misconception_id,
            "misconception_status": status,
            "outcome": outcome,
            "struggled": struggled,
            "metacognitive_when": "after_struggle" if struggled else "after_success",
            "mastery": mastery,
        }

    # ------------------------------------------------------------------
    # Grade-9 bridge gating + write-back (plan Phase 3 step 7 / A2.4)
    # ------------------------------------------------------------------
    @property
    def bridges_served(self) -> list:
        return self.data.setdefault("session", {}).setdefault("bridges_served", [])

    def should_serve_bridge(self, bridge_id: str, zpd_center: float) -> bool:
        """The activation half of the bridge policy contract.

        Activate only when bridge mastery is unknown/low (< BRIDGE_MASTERY_THRESHOLD),
        the learner is not in the advanced band (zpd_center < BRIDGE_SKIP_ZPD_CENTER),
        and the bridge was not already served this session.
        """
        if bridge_id in self.bridges_served:
            return False
        if zpd_center >= BRIDGE_SKIP_ZPD_CENTER:
            return False
        return self.mastery(bridge_id) < BRIDGE_MASTERY_THRESHOLD

    def apply_bridge_result(
        self,
        bridge_id: str,
        outcome: str,
        revealed_misconception_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Write back one bridge-diagnostic outcome (never display-only).

        correct        -> bridge mastery +0.25 (capped) and proceed to the new concept;
        wrong/partial  -> mastery -0.10, any revealed misconception set active, and the
                          pedagogy engine must serve the recap BEFORE the new concept.
        Doubles as the cold-start mastery probe for brand-new learners.
        """
        if outcome not in BRIDGE_MASTERY_DELTA:
            raise ValueError(f"outcome must be one of {sorted(BRIDGE_MASTERY_DELTA)}, got {outcome!r}")
        mastery = max(0.0, min(1.0, self.mastery(bridge_id) + BRIDGE_MASTERY_DELTA[outcome]))
        self.update_mastery(bridge_id, mastery)
        if bridge_id not in self.bridges_served:
            self.bridges_served.append(bridge_id)
        if outcome != "correct" and revealed_misconception_id:
            ms = self.misconception_states.setdefault(revealed_misconception_id, {
                "status": "active", "consecutive_correct": 0, "consecutive_failures": 0,
            })
            ms["status"] = "recurring" if ms.get("status") == "resolved" else "active"
            ms["consecutive_correct"] = 0
            ms["consecutive_failures"] = int(ms.get("consecutive_failures", 0)) + 1
        return {
            "bridge_id": bridge_id,
            "outcome": outcome,
            "mastery": mastery,
            "action": "proceed" if outcome == "correct" else "serve_recap_first",
            "misconception_set_active": (revealed_misconception_id
                                         if outcome != "correct" and revealed_misconception_id else None),
        }

    # ------------------------------------------------------------------
    # Part 12 — graded PRACTICE/TEST item write-back (§5.3), the THIRD evidence
    # API alongside apply_probe_result / apply_bridge_result. Mastery moves ONLY
    # here for item evidence; misconception status stays with the probe API.
    # ------------------------------------------------------------------
    def apply_item_result(self, item_id: str, outcome: str, concept_id: str, *,
                          kind: str, difficulty: Optional[float] = None,
                          hints_used: int = 0) -> Dict[str, Any]:
        """Write back one graded item outcome (practice / test / parallel_retest).

        Practice gains are discounted by hints_used (tests are hint-free, full
        weight); wrong is never discounted. Updates item_history; never touches
        misconception status. Returns the writeback record for the learning log
        (an `item_result` row — the data the deferred knowledge tracing awaits).
        """
        if outcome not in ITEM_MASTERY_DELTA:
            raise ValueError(f"outcome must be one of {sorted(ITEM_MASTERY_DELTA)}, got {outcome!r}")
        delta = ITEM_MASTERY_DELTA[outcome]
        if kind != "test" and outcome in ("correct", "partial") and hints_used:
            discount = max(0.25, 1.0 - ITEM_HINT_DISCOUNT * min(3, int(hints_used)))
            delta *= discount
        before = self.mastery(concept_id)
        mastery = max(0.0, min(1.0, before + delta))
        self.update_mastery(concept_id, mastery)

        cs = self.concept_states.setdefault(concept_id, {})
        hist = cs.setdefault("item_history", {})
        rec = hist.setdefault(item_id, {"last_seen": None, "outcomes": []})
        rec["last_seen"] = datetime.now(timezone.utc).isoformat()
        rec["outcomes"] = (rec.get("outcomes", []) + [outcome])[-ITEM_HISTORY_MAX:]

        return {
            "item_result": item_id, "outcome": outcome, "kind": kind,
            "concept_id": concept_id, "difficulty": difficulty,
            "hints_used": int(hints_used),
            "mastery": round(mastery, 4), "mastery_delta": round(delta, 4),
        }

    def item_seen_recently(self, concept_id: str, item_id: str, within: int = 3) -> bool:
        """True if this item was served in the last `within` outcomes (quiz-set
        exclusion, §4.4). A per-item proxy for 'seen in the last K sessions'."""
        rec = ((self.concept_states.get(concept_id) or {}).get("item_history") or {}).get(item_id)
        if not rec:
            return False
        return len(rec.get("outcomes") or []) >= 1 and within > 0

    def record_test_result(self, concept_id: str, *, score: float, n: int, gate: str,
                           item_results: list, gate_threshold: float = MASTERY_GATE_DEFAULT) -> Dict[str, Any]:
        """Append one completed-test summary to the concept's test_history and set
        its mastery_gate (§4.2). `gate` is 'pass' | 'fail'. Feeds the parent dash."""
        cs = self.concept_states.setdefault(concept_id, {})
        row = {
            "date": datetime.now(timezone.utc).isoformat(),
            "score": round(float(score), 3), "n": int(n), "gate": gate,
            "threshold": gate_threshold, "item_results": item_results,
        }
        cs.setdefault("test_history", []).append(row)
        cs["mastery_gate"] = "passed" if gate == "pass" else "failed_pending_retest"
        return row

    def mastery_gate(self, concept_id: str) -> str:
        return (self.concept_states.get(concept_id) or {}).get("mastery_gate", "none")

    def concepts_due_for_review(self, exclude: Optional[str] = None) -> list:
        """Concepts that have PASSED their gate (candidates for a spaced-review item
        in a later set, R4). Excludes the current concept."""
        out = []
        for cid, cs in self.concept_states.items():
            if cid == exclude:
                continue
            if cs.get("mastery_gate") == "passed":
                out.append(cid)
        return out

    def save(self) -> None:
        if self.path is None:
            return
        # Atomic save: write to .tmp, fsync, rename over the target — a crash or
        # power loss mid-write must never leave a truncated state file (the file
        # IS the learner's entire history). Keep one .bak generation so a corrupt
        # primary still recovers to the last known-good state.
        tmp = self.path.with_suffix(".tmp")
        bak = self.path.with_suffix(".bak")
        payload = json.dumps(self.data, indent=2, ensure_ascii=False)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        if self.path.exists():
            try:
                self.path.replace(bak)     # current becomes the backup
            except OSError:
                pass
        tmp.replace(self.path)             # atomic on POSIX; ReplaceFile on Windows


def load_learner_state(path: Optional[Path]) -> LearnerState:
    """Load a learner-state file. Missing/None path yields an empty (all cold-start) model.

    Recovery order: primary (.json) -> backup (.bak) -> empty cold-start. A corrupt
    primary is preserved as .corrupt (post-mortem, never silently deleted) and the
    backup is promoted in place so the next save() proceeds normally."""
    if not path:
        return LearnerState(path=path, data={"concept_states": {}, "global": {}})
    for candidate in (path, path.with_suffix(".bak")):
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("root is not a dict")
            data.setdefault("concept_states", {})
            data.setdefault("global", {})
            if candidate != path:
                print(f"[state] recovered from backup: {candidate}")
                try:
                    candidate.replace(path)
                except OSError:
                    pass
            return LearnerState(path=path, data=data)
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
            print(f"[state] corrupt state file {candidate}: {e}")
            if candidate == path:
                try:
                    path.replace(path.with_suffix(".corrupt"))
                    print(f"[state] preserved corrupt file as {path.with_suffix('.corrupt')}")
                except OSError:
                    pass
    print("[state] no valid state file found; starting cold")
    return LearnerState(path=path, data={"concept_states": {}, "global": {}})


def mastery_to_band(mastery: float, half_width: float = 2.0) -> "tuple[float, float, float]":
    """Map mastery in [0,1] to a (lo, hi, center) ZPD difficulty band on the 1-10 scale.

    mastery 0.0 -> center 2.0 (band 1-4)   : foundational, low cognitive load
    mastery 0.5 -> center 5.5 (band 3.5-7.5): mid
    mastery 1.0 -> center 9.0 (band 7-10)   : challenge / transfer
    Stretches the target just past current mastery so tasks stay in the ZPD.
    """
    center = 2.0 + 7.0 * max(0.0, min(1.0, mastery))
    lo = max(1.0, center - half_width)
    hi = min(10.0, center + half_width)
    return lo, hi, center
