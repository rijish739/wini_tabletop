"""Script Validator and Safety Gate (§5.3) — generation is not trusted; this is.

``ScriptValidator.validate(script, evidence_text, profile)`` runs the required rules and
returns the SAME script object with its ``.validation`` filled and any unsupportable
modality DOWNGRADED in place (visual dropped to NONE, robot primitives filtered). It never
aborts the turn: a hard content violation degrades to a grounded speech-only path
(§3.5 "fallback reduces modality count"), it does not stop Wini from speaking.

Rules implemented (§5.3 "Required Validator Rules"):
    1. ``instructional`` requires concept + evidence grounding; social/admin/off_domain
       stay speech/text only (all visuals forced off).
    2. Every ``pedagogical_step`` must be legal under the turn's ``pedagogical_action``
       (allowed-step table, §B8) — else the script is rejected (visual dropped).
    3. Probe-before-correct (§A3): a ``correct`` beat is unreachable until the
       misconception is confirmed — reject the visual + flag.
    4. ``visual_type`` must be compatible with the beat's step AND renderable on the
       reported device profile (enum-consistency + capability, §B6/§5.3).
    5. Claim<->evidence consistency (§A2), tiered: numbers/formulas in a beat's claim
       must be grounded in the cited evidence OR the concept's linked formulas
       (rag_store/formula_links.json) — an unsupported number drops that beat's visual
       rather than shipping a wrong picture.
    6. Robot primitives absent from ``profile.robot_primitives`` are dropped before
       packaging (on winipi5 that is ALL of them) and counted.

The final display decision the integration reads is ``validation["visual"]``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import templates
from .contracts import RobotPrimitive, TeachingScript, VisualType

_ROOT = Path(__file__).resolve().parent.parent
_FORMULA_LINKS = _ROOT / "rag_store" / "formula_links.json"

_NUM_RE = re.compile(r"(?<![A-Za-z_])\d+(?:\.\d+)?")

# framing steps carry no substantive claim -> no grounding required (§planner._beat_evidence)
_FRAMING = {templates.STEP_ORIENT, templates.STEP_CLOSE, templates.STEP_ENCOURAGE}

# steps whose beat must NEVER show an answer-revealing visual (test integrity / probe)
_NO_VISUAL_STEPS = {
    templates.STEP_TEST_QUESTION, templates.STEP_TEST_SUMMARY,
    templates.STEP_PROBE, templates.STEP_CHALLENGE, templates.STEP_POSE_PROBLEM,
}

# visual_type -> the device profile flag that must be true to render it. A generated
# declarative scene renders through the SAME beat player as an authored scene.
_TYPE_CAPABILITY = {
    VisualType.AUTHORED_SCENE: "supports_authored_scene",
    VisualType.GENERATED_DECLARATIVE_SCENE_SPEC: "supports_authored_scene",
    VisualType.ANIMATION: "supports_animation",
    VisualType.INTERACTIVE_VISUAL: "supports_interactive_visual",
}


class ScriptValidator:
    def __init__(self):
        self._formula_by_concept: dict[str, str] | None = None

    # ------------------------------------------------------------------
    def _formula_text(self, concept_id: str | None) -> str:
        """Concatenated formula text for a concept from formula_links.json (§A2 reuse).
        Loaded once, best-effort — a missing file just means no formula-grounded numbers."""
        if self._formula_by_concept is None:
            idx: dict[str, str] = {}
            try:
                data = json.loads(_FORMULA_LINKS.read_text(encoding="utf-8"))
                for link in data.get("links", []):
                    cid = link.get("concept_id")
                    if cid:
                        idx[cid] = idx.get(cid, "") + " " + (link.get("formula") or "")
            except Exception:  # noqa: BLE001 — no formula index is fine
                idx = {}
            self._formula_by_concept = idx
        return self._formula_by_concept.get(concept_id or "", "") if concept_id else ""

    # ------------------------------------------------------------------
    def validate(self, script: TeachingScript, evidence_text: dict[str, str] | None = None,
                 profile: dict | None = None) -> TeachingScript:
        evidence_text = evidence_text or {}
        profile = profile or script.device_profile or {}
        issues: list[str] = []
        instructional = script.response_kind.value == "instructional"

        grounding_ok = True
        allowed_steps_ok = True
        probe_ok = True
        assessment_hooks_ok = True
        robot_dropped = 0

        for beat in script.beats:
            # P0 evidence integrity: planner placeholders describe interaction
            # shape only; they are not assessing contracts. Fail closed.
            hook = beat.assessment_hook
            if hook is not None and not (
                    hook.verification_status in {"verified", "authored_verified"}
                    and hook.verification_token and hook.item_id and hook.question
                    and (hook.expected_answer or hook.rubric)
                    and hook.assessment_purpose and hook.state_update_intent):
                assessment_hooks_ok = False
                issues.append(
                    f"beat {beat.beat_id}: unverified assessment hook downgraded to non-assessing")
                beat.assessment_hook = None
                if beat.completion_condition in ("await_spoken_answer", "await_local_response"):
                    beat.completion_condition = "speech_complete"

            # rule 2 — allowed-step compliance (§B8)
            if not templates.is_step_allowed(script.pedagogical_action, beat.pedagogical_step):
                allowed_steps_ok = False
                issues.append(
                    f"beat {beat.beat_id}: step '{beat.pedagogical_step}' is not legal "
                    f"under action '{script.pedagogical_action}'")

            # rule 3 — probe-before-correct (§A3)
            correcting = beat.pedagogical_step == templates.STEP_CORRECT
            confirmed = bool(script.validation.get("misconception_confirmed")) or \
                _confirmed_from_script(script)
            if correcting and not confirmed:
                probe_ok = False
                issues.append(
                    f"beat {beat.beat_id}: corrects an unconfirmed misconception "
                    f"(probe-before-correct)")

            # rule 1 — instructional content beats must cite evidence
            if instructional and beat.pedagogical_step not in _FRAMING and \
                    not beat.evidence_refs and beat.atomic_learning_claim:
                grounding_ok = False
                issues.append(f"beat {beat.beat_id}: instructional content beat cites no evidence")

            # rule 6 — drop robot primitives the device can't do (§5.3 rule 6)
            allowed_prims = _profile_primitives(profile)
            kept = [p for p in beat.robot_intent if p in allowed_prims]
            robot_dropped += len(beat.robot_intent) - len(kept)
            beat.robot_intent = kept

            # rule 4 + rule 5 — visual consistency & claim<->evidence
            if beat.shows_visual():
                drop = self._visual_reject_reason(script, beat, evidence_text, profile)
                if drop is not None:
                    issues.append(f"beat {beat.beat_id}: visual dropped — {drop}")
                    from .contracts import VisualIntent
                    beat.visual_intent = VisualIntent(
                        VisualType.NONE, False, f"validator dropped: {drop}")

        # non-instructional turns are speech/text only (§5.3 rule for social/admin/off)
        if not instructional:
            for beat in script.beats:
                if beat.shows_visual():
                    from .contracts import VisualIntent
                    beat.visual_intent = VisualIntent(
                        VisualType.NONE, False,
                        f"{script.response_kind.value} turn is speech/text only")

        # a HARD reject (illegal step / probe-before-correct / ungroundable) forces the
        # speech-only fallback: strip every remaining visual, keep the answer (§3.5).
        hard_reject = (not allowed_steps_ok) or (not probe_ok) or \
            (instructional and not grounding_ok and not _has_any_evidence(script))
        if hard_reject:
            for beat in script.beats:
                if beat.shows_visual():
                    from .contracts import VisualIntent
                    beat.visual_intent = VisualIntent(
                        VisualType.NONE, False, "fallback: script failed validation → speech only")

        final_visual = self._final_visual(script)
        script.validation = {
            "ok": not hard_reject,
            "response_kind": script.response_kind.value,
            "grounding_ok": grounding_ok,
            "allowed_steps_ok": allowed_steps_ok,
            "probe_before_correct_ok": probe_ok,
            "assessment_hooks_ok": assessment_hooks_ok,
            "robot_dropped": robot_dropped,
            "issues": issues,
            "visual": final_visual,
        }
        return script

    # ------------------------------------------------------------------
    def _visual_reject_reason(self, script: TeachingScript, beat, evidence_text: dict,
                              profile: dict) -> str | None:
        """Return a reason to DROP the beat's visual, or None to keep it."""
        vi = beat.visual_intent
        vtype = vi.visual_type

        # rule 4a — step compatibility (no answer-revealing visual on probe/test)
        if beat.pedagogical_step in _NO_VISUAL_STEPS:
            return f"visual not allowed on a '{beat.pedagogical_step}' beat"

        # rule 4b — device capability for this visual type
        cap_flag = _TYPE_CAPABILITY.get(vtype)
        if cap_flag is not None and not profile.get(cap_flag, True):
            return f"device cannot render {vtype.value}"
        if not profile.get("display_present", True):
            return "device has no display"

        # rule 5 — claim<->evidence numeric grounding (§A2)
        claim_nums = set(_NUM_RE.findall(beat.atomic_learning_claim or ""))
        if claim_nums:
            grounded = set()
            for ref in beat.evidence_refs:
                grounded |= set(_NUM_RE.findall(evidence_text.get(ref, "")))
            grounded |= set(_NUM_RE.findall(self._formula_text(script.concept_id)))
            ungrounded = claim_nums - grounded
            if ungrounded:
                return (f"claim cites number(s) {sorted(ungrounded)} not in the cited "
                        f"evidence or the concept's formulas")
        return None

    @staticmethod
    def _final_visual(script: TeachingScript) -> dict:
        b = script.first_visual_beat()
        if b is not None and b.visual_intent is not None:
            vi = b.visual_intent
            return {"allowed": vi.allowed, "type": vi.visual_type.value,
                    "reason": vi.reason, "asset": vi.asset_ref,
                    "beat_id": b.beat_id,
                    "representation_target": vi.representation_target}
        # No beat SHOWS a visual. Surface the gate/drop reason from the first beat that
        # carries a (rejecting) visual_intent, so telemetry keeps the actual cause
        # ("high cognitive load…", "claim cites number 42…") instead of a generic string.
        for beat in script.beats:
            if beat.visual_intent is not None:
                return {"allowed": False, "type": VisualType.NONE.value,
                        "reason": beat.visual_intent.reason, "asset": None}
        return {"allowed": False, "type": VisualType.NONE.value,
                "reason": "no visual earned this turn", "asset": None}


def _profile_primitives(profile: dict) -> set[RobotPrimitive]:
    prims = set()
    for p in (profile.get("robot_primitives") or []):
        try:
            prims.add(p if isinstance(p, RobotPrimitive) else RobotPrimitive(p))
        except ValueError:
            continue
    return prims


def _has_any_evidence(script: TeachingScript) -> bool:
    return any(b.evidence_refs for b in script.beats)


def _confirmed_from_script(script: TeachingScript) -> bool:
    # A correction is only reachable if a prior probe beat confirmed the misconception.
    # In the deterministic slice no spine emits a correct beat, so this stays False and
    # the rule is a guard for a future LLM planner. Wired to the script's own flag.
    return bool(script.validation.get("misconception_confirmed", False))
