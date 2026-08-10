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

#: Minimum gap before an outcome counts as COLD recall rather than immediate
#: recall (audit D-3). Answering right straight after being taught measures
#: attention; answering right a day later measures retention.
COLD_RECALL_MIN_GAP_DAYS = 1.0
#: How many recent graded outcomes the confidence trend looks back over.
CONFIDENCE_TREND_WINDOW = 6

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

# Misconception evidence lifecycle. A single result can create at most a
# candidate; supported requires converging consistent evidence.
RESOLVE_AFTER_CONSECUTIVE_CORRECT = 2
SUPPORT_AFTER_CONSISTENT_FAILURES = 2

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
BRIDGE_MASTERY_DELTA = {"correct": +0.25, "partial": +0.05, "wrong": -0.10}


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

    def has_measured_mastery(self, concept_id: str) -> bool:
        """Has this concept's mastery ever been MEASURED, or is `mastery()` just
        handing back COLD_START_MASTERY?

        `mastery()` silently substitutes the cold-start constant for an absent
        value, so every caller — the ZPD band above all — reads a real number and
        cannot tell an unmeasured concept from a genuinely mid-mastery one. On the
        live device 30 of 40 touched concepts had no `mastery` value at all, i.e.
        the band was cold-start for 75% of them while the ranking layer treated it
        as evidence (audit D-4). This is the distinction that was missing; the
        fallback behaviour of `mastery()` is deliberately unchanged.
        """
        return "mastery" in (self.concept_states.get(concept_id) or {})

    # ------------------------------------------------------------------
    # §6.4 per-concept fields that the architecture specified and nothing
    # implemented (audit D-3). Each is written from EVIDENCE only — never
    # inferred from the text of an utterance (§10/§13 rule 8).
    # ------------------------------------------------------------------
    def cold_recall_strength(self, concept_id: str) -> Optional[float]:
        """Retention after a gap: how well the learner did on the first item of a
        session on a concept last practised some days earlier. None = never
        measured, which callers must treat as "unknown", not as zero."""
        v = (self.concept_states.get(concept_id) or {}).get("cold_recall_strength")
        try:
            return None if v is None else max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return None

    def record_cold_recall(self, concept_id: str, correct: bool,
                           gap_days: float, ema: float = 0.4) -> Optional[float]:
        """Fold one cold-recall observation in. Only counts when the gap since
        `last_practiced` clears COLD_RECALL_MIN_GAP_DAYS — answering correctly ten
        seconds after being told the answer says nothing about retention."""
        if gap_days < COLD_RECALL_MIN_GAP_DAYS:
            return self.cold_recall_strength(concept_id)
        cs = self.concept_states.setdefault(concept_id, {})
        old = self.cold_recall_strength(concept_id)
        obs = 1.0 if correct else 0.0
        new = obs if old is None else (1.0 - ema) * old + ema * obs
        cs["cold_recall_strength"] = round(new, 4)
        cs["cold_recall_last"] = datetime.now(timezone.utc).isoformat()
        return cs["cold_recall_strength"]

    def confidence_trend(self, concept_id: str) -> str:
        """"rising" / "falling" / "flat" / "unknown" over the recent outcome
        history for this concept — the direction, which a single mastery number
        cannot express (a child at 0.5 on the way up needs the opposite of a
        child at 0.5 on the way down)."""
        # item_history is keyed BY ITEM ({item_id: {last_seen, outcomes[]}}), not a
        # flat log, so recover a chronological sequence by ordering items on
        # last_seen and taking each one's outcomes in the order they were appended.
        hist = (self.concept_states.get(concept_id) or {}).get("item_history") or {}
        seq: list = []
        for _iid, rec in sorted(hist.items(), key=lambda kv: (kv[1] or {}).get("last_seen") or ""):
            seq.extend((rec or {}).get("outcomes") or [])
        vals = [1.0 if o == "correct" else 0.5 if o == "partial" else 0.0
                for o in seq[-CONFIDENCE_TREND_WINDOW:]]
        if len(vals) < 3:
            return "unknown"
        half = len(vals) // 2
        first, second = vals[:half], vals[len(vals) - half:]
        delta = (sum(second) / len(second)) - (sum(first) / len(first))
        return "rising" if delta > 0.15 else "falling" if delta < -0.15 else "flat"

    def transfer_readiness(self, concept_id: str) -> float:
        """0-1: how ready this concept is to be carried to a NEW situation.

        Mastery is necessary but not sufficient — a learner who only ever
        succeeds WITH hints is not transfer-ready, and one who cannot recall the
        idea cold certainly is not. Combines the three accordingly, so §6.6's
        transfer rule can consult a measured quantity instead of a one-turn
        perception signal (which is what routed a student's own word problem to
        TRANSFER_PROBLEM in the first place, audit A-2).
        """
        m = self.mastery(concept_id)
        if not self.has_measured_mastery(concept_id):
            return 0.0
        cold = self.cold_recall_strength(concept_id)
        hint_free = 1.0 - self.hint_dependency(concept_id)
        score = 0.6 * m + 0.4 * hint_free
        if cold is not None:
            score = 0.7 * score + 0.3 * cold
        return round(max(0.0, min(1.0, score)), 4)

    def _days_since_practice(self, concept_id: str) -> Optional[float]:
        """Days since this concept was last practised; None if never."""
        lp = (self.concept_states.get(concept_id) or {}).get("last_practiced")
        if not lp:
            return None
        try:
            ts = datetime.fromisoformat(lp)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None
        return (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0

    def hint_chain_position(self, concept_id: str, problem_id: Optional[str] = None) -> int:
        """How far INTO the hint chain the learner currently is (0 = untouched).

        §6.4 lists "hint dependency AND hint-chain position" as separate fields;
        only the first existed. The position is what tells the tutor whether to
        fade the next hint or switch action — `hints_used_current` already tracks
        it per problem, this exposes it as the documented field.
        """
        cs = self.concept_states.get(concept_id) or {}
        if problem_id is not None and cs.get("current_problem_id") != problem_id:
            return 0
        try:
            return max(0, int(cs.get("hints_used_current", 0)))
        except (TypeError, ValueError):
            return 0

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

    def begin_session(self) -> dict:
        """Clear the SESSION-scoped no-repeat sets. Call once per brain start.

        §6.4 scopes `served_items` to "items already served **this session**", but
        it lives in the persisted learner state and only `/api/reset-session` (a
        different entry point) ever cleared it — so on the device it had grown to
        593 permanently blacklisted chunks, monotonically starving retrieval: the
        best chunk for a concept was excluded from every turn after the first,
        forever, and rule 1b ("re-explain the same idea more simply") was denied
        the very evidence that explains it (audit A-7/D-5).

        Mastery, misconceptions, flags and history are per-LEARNER and are NOT
        touched here — only the two per-session no-repeat sets.
        """
        session = self.data.setdefault("session", {})
        cleared = {"served_items": len(session.get("served_items") or []),
                   "bridges_served": len(session.get("bridges_served") or [])}
        session["served_items"] = []
        session["bridges_served"] = []
        session["session_started_at"] = datetime.now(timezone.utc).isoformat()
        return cleared

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
        evidence_consistent: bool = False,
        evidence_ref: Optional[str] = None,
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

        ms = self.misconception_states.get(misconception_id)
        # A first correct response is evidence against the named misconception;
        # do not create an "active" record merely because a probe was answered.
        if ms is None and (outcome == "correct" or not evidence_consistent):
            status = "untracked"
            consecutive_failures = 0 if outcome == "correct" else 1
        else:
            ms = self.misconception_states.setdefault(misconception_id, {
                "status": "candidate", "consecutive_correct": 0,
                "consecutive_failures": 0, "consistent_failures": 0,
                "evidence_refs": [],
            })
            status = ms.get("status", "candidate")
            if evidence_ref and evidence_ref not in ms.setdefault("evidence_refs", []):
                ms["evidence_refs"].append(evidence_ref)

            if outcome == "correct":
                ms["consecutive_correct"] = int(ms.get("consecutive_correct", 0)) + 1
                ms["consecutive_failures"] = 0
                if status in ("supported", "recurring", "weakening"):
                    status = ("resolved" if ms["consecutive_correct"] >=
                              RESOLVE_AFTER_CONSECUTIVE_CORRECT else "weakening")
                elif ms["consecutive_correct"] >= RESOLVE_AFTER_CONSECUTIVE_CORRECT:
                    status = "resolved"
            else:
                ms["consecutive_correct"] = 0
                ms["consecutive_failures"] = int(ms.get("consecutive_failures", 0)) + 1
                if evidence_consistent:
                    ms["consistent_failures"] = int(ms.get("consistent_failures", 0)) + 1
                    if status == "resolved":
                        status = "recurring"
                    elif int(ms["consistent_failures"]) >= SUPPORT_AFTER_CONSISTENT_FAILURES:
                        status = "supported"
                    else:
                        status = "candidate"
                # An ordinary wrong answer does not prove this particular
                # misconception. Preserve the current status without strengthening.
            ms["status"] = status
            ms["last_probed"] = datetime.now(timezone.utc).isoformat()
            consecutive_failures = int(ms.get("consecutive_failures", 0))

        struggled = (
            int(hints_used) >= STRUGGLE_HINT_THRESHOLD
            or consecutive_failures >= STRUGGLE_FAIL_THRESHOLD
        )

        mastery = None
        if concept_id:
            mastery = max(0.0, min(1.0, self.mastery(concept_id) + PROBE_MASTERY_DELTA[outcome]))
            self.update_mastery(concept_id, mastery)
            cs = self.concept_states.setdefault(concept_id, {})
            cs["struggle"] = {
                "struggling": struggled,
                "hints_used_last": int(hints_used),
                "consecutive_failures": consecutive_failures,
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
                "status": "candidate", "consecutive_correct": 0,
                "consecutive_failures": 0, "consistent_failures": 0,
                "evidence_refs": [],
            })
            ms["consecutive_correct"] = 0
            ms["consecutive_failures"] = int(ms.get("consecutive_failures", 0)) + 1
            ms["consistent_failures"] = int(ms.get("consistent_failures", 0)) + 1
            if ms.get("status") == "resolved":
                ms["status"] = "recurring"
            elif int(ms["consistent_failures"]) >= SUPPORT_AFTER_CONSISTENT_FAILURES:
                ms["status"] = "supported"
            else:
                ms["status"] = "candidate"
        return {
            "bridge_id": bridge_id,
            "outcome": outcome,
            "mastery": mastery,
            "action": "proceed" if outcome == "correct" else "serve_recap_first",
            "misconception_candidate": (revealed_misconception_id
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
        # COLD RECALL (§6.4, audit D-3): measured BEFORE update_mastery rewrites
        # last_practiced — the gap since the previous session is exactly what
        # makes this outcome evidence about retention rather than about attention.
        cold_gap = self._days_since_practice(concept_id)
        mastery = max(0.0, min(1.0, before + delta))
        self.update_mastery(concept_id, mastery)
        if cold_gap is not None:
            self.record_cold_recall(concept_id, outcome == "correct", cold_gap)

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

    # ------------------------------------------------------------------
    # P0 single evidence-ledger funnel. The legacy apply_* methods remain above
    # as the rollback path; the live P0 path enters learner state only here.
    # ------------------------------------------------------------------
    @property
    def evidence_ledger(self) -> list:
        return self.data.setdefault("evidence_ledger", [])

    def apply_outcome_event(self, event) -> Dict[str, Any]:
        """Idempotently apply one verified ``OutcomeEvent`` and append it once.

        The event and its application result are persisted in the same in-memory
        state object and therefore in the same atomic LearnerState.save(). A retry
        with the same key returns the recorded result without mutating state.
        """
        from response_layer.contracts import OutcomeEvent
        from runtime_flags import GRADER_WRITE_CONFIDENCE_MIN, STT_WRITE_CONFIDENCE_MIN

        if isinstance(event, dict):
            event = OutcomeEvent.from_dict(event)
        if not isinstance(event, OutcomeEvent):
            raise TypeError("event must be an OutcomeEvent or dict")
        key = event.idempotency_key
        if not event.script_id or not event.beat_id or event.attempt < 1:
            raise ValueError("OutcomeEvent requires script_id, beat_id, and attempt >= 1")
        for row in self.evidence_ledger:
            if row.get("idempotency_key") == key:
                result = dict(row.get("application") or {})
                result.update({"status": "duplicate", "idempotency_key": key})
                return result

        outcome = str(event.outcome or "").lower()
        if outcome not in ("correct", "partial", "wrong"):
            return {"status": "rejected", "reason": "unscorable_outcome",
                    "idempotency_key": key}
        if event.stt_confidence is not None and \
                float(event.stt_confidence) < STT_WRITE_CONFIDENCE_MIN:
            return {"status": "suppressed", "reason": "low_stt_confidence",
                    "idempotency_key": key}
        if event.grader_confidence is not None and \
                float(event.grader_confidence) < GRADER_WRITE_CONFIDENCE_MIN:
            return {"status": "suppressed", "reason": "low_grader_confidence",
                    "idempotency_key": key}

        payload = dict(event.payload or {})
        concept = event.concept_id or payload.get("target_concept")
        item_id = event.item_id or event.assessment_hook_id or event.beat_id
        mutation_kind = payload.get("mutation_kind") or payload.get("kind") or "practice"
        target = item_id if mutation_kind == "bridge" else concept
        before = self.mastery(target) if target else None

        if mutation_kind == "bridge":
            result = self.apply_bridge_result(
                item_id, outcome, payload.get("revealed_misconception_id"))
        elif mutation_kind == "misconception":
            result = self.apply_probe_result(
                item_id, outcome, concept_id=concept,
                hints_used=int(payload.get("hints_used") or 0),
                evidence_consistent=bool(payload.get("misconception_consistent", False)),
                evidence_ref=key)
        else:
            if not concept:
                return {"status": "rejected", "reason": "missing_target_concept",
                        "idempotency_key": key}
            result = self.apply_item_result(
                item_id, outcome, concept, kind=mutation_kind,
                difficulty=payload.get("difficulty"),
                hints_used=int(payload.get("hints_used") or 0))

        after = self.mastery(target) if target else before
        application = dict(result)
        application.update({
            "status": "applied", "idempotency_key": key,
            "mastery_before": before, "mastery_after": after,
            "mastery_delta_applied": (None if before is None or after is None
                                      else round(after - before, 4)),
        })
        row = event.to_dict()
        row["application"] = application
        self.evidence_ledger.append(row)
        return dict(application)

    def replay_mastery(self, concept_id: str) -> Optional[float]:
        """Replay the recorded mastery chain for one concept.

        Returns None when P0 has not recorded evidence for the concept. A broken
        before/after chain raises instead of silently hiding ledger corruption.
        """
        value: Optional[float] = None
        for row in self.evidence_ledger:
            app = row.get("application") or {}
            payload = row.get("payload") or {}
            target = row.get("concept_id") or payload.get("target_concept")
            if payload.get("mutation_kind") == "bridge":
                target = row.get("item_id") or row.get("assessment_hook_id")
            if target != concept_id or app.get("status") != "applied":
                continue
            before, after = app.get("mastery_before"), app.get("mastery_after")
            if value is not None and before is not None and abs(float(before) - value) > 1e-9:
                raise ValueError(f"ledger mastery chain broken for {concept_id}")
            value = None if after is None else float(after)
        return value

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
