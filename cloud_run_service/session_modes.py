"""Part 12 — session pedagogy modes: the OUTER loop (EXPLAIN / PRACTICE / TEST).

VanLehn's two-loop model: tutor_loop's per-turn `rules_decide` + grading is a strong
INNER loop; this module is the missing OUTER loop that gives a session *intentionality*
("we are practicing toward mastery" / "this is a check"). See PART12_PEDAGOGY_MODES_PLAN.md.

ModeController owns:
  * the current mode (`session["mode"]`, default EXPLAIN),
  * mode transitions (§4.1): explicit student requests (deterministic cues), mode
    offers (yes/no, consumed like `pending_shift`), and evidence transitions,
  * item selection for PRACTICE (adaptive ladder, §4.3) and TEST (quiz set, §4.4).

Protection invariants (plan §6), enforced by construction here:
  * This module NEVER moves mastery / misconception / HOPE state — that stays with
    learner_state's evidence APIs (`apply_probe_result` / `apply_bridge_result` /
    the new `apply_item_result`). ModeController only reads state and picks tasks.
  * EXPLAIN is byte-identical to pre-Part-12: when mode == EXPLAIN the controller
    yields no item and tutor_loop runs `rules_decide` unchanged.
  * SAFETY / NONSENSE / SESSION_CONTROL are handled by the front door BEFORE the
    controller runs; inner-loop confusion/visual/purpose overrides still win and
    pause the plan (§5.2 precedence table).

Staging: Stage 1 ships the substrate (mode field, cues, offers, consume); Stage 2
the PRACTICE ladder (`next_practice_item`); Stage 3 the TEST quiz set
(`build_quiz_set` / `advance_test` / `score_quiz`). When a mode yields no item the
controller returns None and tutor_loop falls back to `rules_decide`.
"""

from __future__ import annotations

import re

MODES = ("EXPLAIN", "PRACTICE", "TEST")

# Actions that count as "we actually taught something" — a precondition for
# offering PRACTICE (§4.1: offer only after the concept intro is done).
TEACHING_ACTIONS = {
    "EXPLAIN", "WORKED_EXAMPLE", "ANALOGOUS_EXAMPLE",
    "REPRESENTATION_TRANSLATION", "WHY_IT_MATTERS", "ENCOURAGE",
}

_YES_RE = re.compile(
    r"^(yes|yeah|ya|yep|yup|ok(ay)?|sure|haan|ha|please|go on|let'?s go|lets go|"
    r"why not|alright|sounds good)\b", re.IGNORECASE)
_NO_RE = re.compile(
    r"^(no|nope|nah|not now|not really|later|maybe later|not yet)\b", re.IGNORECASE)


def normalize_mode(mode) -> str:
    m = str(mode or "EXPLAIN").strip().upper()
    return m if m in MODES else "EXPLAIN"


def mode_cues(text: str):
    """RETIRED (slice 07, 2026-08-28) — reads text via cue regexes.

    The mode sub-type is now provided by the Gemini perception layer as
    ``RouteResult.session_control_mode`` (STOP/TEST/PRACTICE/EXPLAIN or None).
    The ModeController caller is retired; the interaction-control layer reads
    from the observation instead of calling this function.

    This stub returns None unconditionally so any lingering call-site is
    a silent no-op rather than an import error during the transition.
    """
    return None


class ModeController:
    """Stateless over its own attributes; all mode state lives in the `session` dict
    so it persists/resumes with learner state (§4.1 freeze-on-SESSION_CONTROL)."""

    def __init__(self, offers_enabled: bool = False):
        # Offers stay OFF until PRACTICE exists (Stage 2). Explicit requests always
        # work. Kept as a flag so the Stage-2 flip is one line + a test.
        self.offers_enabled = offers_enabled

    # ── mode accessors ────────────────────────────────────────────────────────
    @staticmethod
    def current_mode(session: dict) -> str:
        return normalize_mode(session.get("mode"))

    @staticmethod
    def set_mode(session: dict, mode: str) -> str:
        mode = normalize_mode(mode)
        session["mode"] = mode
        # Leaving a mode drops its transient plan struct (kept compact, §9 risk).
        if mode != "PRACTICE":
            session.pop("practice_plan", None)
        if mode != "TEST":
            # A TEST in progress FREEZES rather than being discarded (§4.4.4): only
            # clear it when the student is going back to plain learning, not on a
            # SESSION_CONTROL pause (that path never calls set_mode).
            session.pop("test_state", None)
        return mode

    # ── offer consume (bare yes/no, like pending_shift) ───────────────────────
    def consume_offer(self, session: dict, text: str):
        """Resolve a pending_mode_offer from last turn.

        Returns ("accepted", new_mode) | ("declined", current_mode) | None.
        None means there was no offer, or the reply was neither a bare yes nor a
        bare no — in which case the offer is cancelled and the caller lets the
        utterance take the normal pipeline (same semantics as _consume_pending_shift).
        """
        offer = session.get("pending_mode_offer")
        if not offer:
            return None
        low = (text or "").strip().lower()
        words = low.split()
        session.pop("pending_mode_offer", None)  # one-shot, either way
        if _YES_RE.match(low) and len(words) <= 4:
            return ("accepted", self.set_mode(session, offer.get("mode", "PRACTICE")))
        if _NO_RE.match(low) and len(words) <= 4:
            return ("declined", self.current_mode(session))
        return None

    # ── frozen-test resume (§4.4.4) ───────────────────────────────────────────
    def check_frozen_test(self, session: dict):
        """Detect a test frozen by a mid-set session end ('bye' preserves
        test_state; see set_mode docstring). Returns a resume-offer dict (also
        stored as session['pending_test_resume']) or None. Called once when a
        LEARNING turn resumes a paused/ended session."""
        ts = session.get("test_state")
        if not ts or ts.get("phase") == "done":
            return None
        if session.get("pending_test_resume"):
            return None  # already offered
        offer = {
            "concept_id": ts.get("concept_id", ""),
            "graded": len(ts.get("results", [])),
            "n": int(ts.get("n", 5)),
        }
        session["pending_test_resume"] = offer
        return offer

    def consume_test_resume(self, session: dict, text: str):
        """Resolve last turn's frozen-test resume offer (one-shot, like
        consume_offer). Returns:
          ("resume", "TEST")     bare yes  -> continue the frozen set
          ("abandon", "EXPLAIN") bare no   -> drop the set, back to learning
          None                   ambiguous -> offer cancelled, set dropped, and
                                 the utterance takes the normal pipeline.
        The set is dropped (not kept) on non-yes replies: leaving mode/test_state
        frozen would rebuild a quiz on the student's next unrelated question."""
        offer = session.get("pending_test_resume")
        if not offer:
            return None
        low = (text or "").strip().lower()
        words = low.split()
        session.pop("pending_test_resume", None)  # one-shot, either way
        if _YES_RE.match(low) and len(words) <= 4:
            session["mode"] = "TEST"              # test_state is intact — continue
            return ("resume", "TEST")
        if _NO_RE.match(low) and len(words) <= 4:
            return ("abandon", self.set_mode(session, "EXPLAIN"))  # drops test_state
        self.set_mode(session, "EXPLAIN")
        return None

    # ── explicit request resolution ───────────────────────────────────────────
    def resolve_mode(self, session: dict, text: str, *, cue=None):
        """Apply an explicit mode-request cue to the session. Returns (mode, reason).

        reason is None when nothing changed (so the caller can skip logging a
        no-op transition). Evidence transitions (offer PRACTICE, PRACTICE->TEST,
        Bloom corrective, mastery gate) are added in Stages 2/3.
        """
        if cue is None:
            cue = mode_cues(text)
        prev = self.current_mode(session)
        if cue == "STOP":
            if prev != "EXPLAIN":
                return self.set_mode(session, "EXPLAIN"), f"stop-request: {prev} -> EXPLAIN"
            return prev, None
        # An active test blocks every mode change EXCEPT the explicit STOP above:
        # a spoken "let's practice" mid-quiz must not abandon the set unscored
        # (§4.4). The "blocked" reason lets the caller acknowledge to the student.
        ts = session.get("test_state")
        test_active = ts is not None and ts.get("phase") != "done"
        if test_active and cue in MODES and cue != "TEST":
            return prev, f"mode change to {cue} blocked: test in progress"
        if cue in MODES:
            if cue != prev:
                return self.set_mode(session, cue), f"explicit request: {prev} -> {cue}"
            return prev, None
        return prev, None

    # ── mode offers (end-of-turn) ─────────────────────────────────────────────
    def maybe_offer_practice(self, session: dict, *, acknowledged: bool, analysis: dict,
                             has_active_misconception: bool):
        """At the end of an EXPLAIN turn where the student just confirmed understanding
        (§4.1 row 2), optionally offer PRACTICE. Sets pending_mode_offer and returns
        the offer line, else None. Gated by offers_enabled (OFF until Stage 2).
        """
        if not self.offers_enabled:
            return None
        if self.current_mode(session) != "EXPLAIN":
            return None
        if not acknowledged or not session.get("current_concept"):
            return None
        if has_active_misconception:
            return None
        cu = (analysis or {}).get("cognitive_update", {}) or {}
        if float(cu.get("frustration_risk", 0.0)) >= 0.6 or float(cu.get("cognitive_load", 0.0)) >= 0.7:
            return None
        if session.get("last_action") not in TEACHING_ACTIONS:
            return None
        session["pending_mode_offer"] = {
            "mode": "PRACTICE", "concept_id": session.get("current_concept")}
        return "Want to try a few problems together?"

    # ── PRACTICE ladder (§4.3) ────────────────────────────────────────────────
    # level -> (action, query.py need). Adaptive fading (R2 / expertise reversal).
    LADDER = [
        ("WORKED_EXAMPLE", "example"),      # 0: full worked example (novice)
        ("COMPLETION_STEP", "schema"),      # 1: Wini does all but the last step
        ("ISOMORPHIC_PRACTICE", "schema"),  # 2: independent problem, graded
        ("TRANSFER_PROBLEM", "transfer"),   # 3: near transfer (far only at high mastery)
    ]

    @staticmethod
    def _entry_level(mastery: float) -> int:
        """Entry ladder level keyed on mastery (§4.3): <0.45→0, <0.6→1, <0.75→2, else 3."""
        if mastery < 0.45:
            return 0
        if mastery < 0.60:
            return 1
        if mastery < 0.75:
            return 2
        return 3

    def next_practice_item(self, session: dict, *, mastery: float,
                           last_outcome=None, last_hints: int = 0):
        """Pick the next PRACTICE ladder item, moving the ladder on last turn's graded
        outcome (adaptive fading, both directions — expertise reversal). Returns a dict
        {action, need, why, level} or {exit_to_explain: True, why} to hand back to a
        corrective EXPLAIN. Pure w.r.t. the session dict (no state/mastery writes here).
        """
        plan = session.get("practice_plan")
        if not plan or plan.get("concept_id") != session.get("current_concept"):
            plan = {
                "concept_id": session.get("current_concept"),
                "ladder_level": self._entry_level(mastery),
                "items_served": [], "consecutive_wrong": 0, "reps_rotated": [],
            }
            session["practice_plan"] = plan
        elif last_outcome in ("correct", "partial", "wrong"):
            lvl = int(plan.get("ladder_level", 0))
            if last_outcome == "wrong":
                plan["consecutive_wrong"] = int(plan.get("consecutive_wrong", 0)) + 1
            else:
                plan["consecutive_wrong"] = 0
            if last_outcome == "correct" and int(last_hints) == 0:
                plan["ladder_level"] = min(len(self.LADDER) - 1, lvl + 1)   # up
            elif last_outcome == "wrong" or int(last_hints) >= 3:
                if lvl == 0 and plan["consecutive_wrong"] >= 2:
                    return {"exit_to_explain": True,
                            "why": "practice: two consecutive wrong at ladder bottom "
                                   "-> corrective EXPLAIN (§4.1)"}
                plan["ladder_level"] = max(0, lvl - 1)                       # down
            # partial holds the level

        level = int(plan.get("ladder_level", 0))
        action, need = self.LADDER[level]
        return {
            "action": action, "need": need, "level": level, "exit_to_explain": False,
            "why": f"practice ladder L{level} ({action}); mastery {mastery:.2f}",
        }

    # ── TEST quiz set (§4.4) ──────────────────────────────────────────────────
    # A TEST is a fixed set of N items (default 5), drawn across the concept's
    # problem_schemas and GENERATED at serve time (the store carries no stored
    # `expected_answer` — audit 2026-07-15). ct_probes never enter: only
    # problem_schema ids are passed in. This module only PLANS the set (which
    # schema, which phase, the score/gate); tutor_loop owns item generation +
    # grading (the model/state seam stays out of here, plan §6 invariant).
    TEST_SET_N = 5

    def build_quiz_set(self, session: dict, concept_id: str, schema_ids: list, n: int = TEST_SET_N):
        """Initialise a TEST set for `concept_id`. Returns the test_state struct, or
        None if the concept has no problem_schema to draw from (caller degrades to
        rules_decide). Interleaves/cycles the available schemas up to N items so a
        concept with <5 schemas still yields a full-length set (parallel forms come
        from generation-time variation, not from distinct stored items)."""
        if not schema_ids:
            return None
        cycle = [schema_ids[i % len(schema_ids)] for i in range(int(n))]
        ts = {
            "concept_id": concept_id, "n": int(n), "idx": 0,
            "schema_cycle": cycle, "items": [], "results": [], "phase": "serving",
        }
        session["test_state"] = ts
        session["mode"] = "TEST"
        return ts

    @staticmethod
    def score_quiz(results: list, n: int, threshold: float) -> dict:
        """Score a completed (or force-ended) set. partial counts as half a mark.
        Returns a summary intent dict with the pass/fail gate (§4.4 80% criterion)."""
        n = max(1, int(n))
        correct = sum(1 for r in results if r == "correct")
        partial = sum(1 for r in results if r == "partial")
        score = (correct + 0.5 * partial) / n
        gate = "pass" if score >= threshold else "fail"
        return {
            "phase": "summary", "action": "TEST_SUMMARY", "need": "none",
            "score": score, "gate": gate, "n": n, "correct": correct,
            "partial": partial, "results": list(results), "threshold": threshold,
            "why": f"test complete: {correct}/{n} correct (score {score:.2f}) "
                   f"-> gate {gate} (§4.4)",
        }

    def advance_test(self, session: dict, *, last_outcome=None,
                     gate_threshold: float = 0.8):
        """Advance the TEST set one step. Folds last turn's graded outcome into the
        running results, then returns the next intent:
          * {'phase':'serving', action:'TEST_QUESTION', schema_id, i, n, ...} — serve
            item i (1-based); the caller generates it and arms the pending check.
          * {'phase':'summary', action:'TEST_SUMMARY', score, gate, ...} — set done.
          * None — no active set.
        A non-attempt (last_outcome None) does NOT consume a slot: the same item
        index is re-served with a freshly generated (parallel) question."""
        ts = session.get("test_state")
        if not ts:
            return None
        if last_outcome in ("correct", "partial", "wrong") and ts.get("phase") == "serving":
            ts["results"].append(last_outcome)
        graded = len(ts["results"])
        ts["idx"] = graded
        if graded >= ts["n"]:
            ts["phase"] = "done"
            return self.score_quiz(ts["results"], ts["n"], gate_threshold)
        return {
            "phase": "serving", "action": "TEST_QUESTION", "need": "schema",
            "schema_id": ts["schema_cycle"][graded], "i": graded + 1, "n": ts["n"],
            "why": f"test item {graded + 1}/{ts['n']} (§4.4)",
        }
