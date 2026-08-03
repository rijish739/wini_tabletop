"""Teaching Script Planner (§5.2) — template-first, near-zero latency.

``TeachingScriptPlanner.plan(ctx)`` turns a ResponseContext into a TeachingScript by:

    1. selecting a template spine for the upstream ``pedagogical_action`` (templates.py),
    2. instantiating each spine slot into a concrete Beat with an ``atomic_learning_claim``
       and ``evidence_refs`` from the manifest,
    3. running the Visual Benefit Gate on the first visual-candidate beat to set that
       beat's visual_intent (visuals earned, not default),
    4. attaching assessment hooks where the template places them, and
    5. linking beats into a linear on_complete chain (the bounded-DAG branch edges are
       populated only when an assessment hook needs them — Phase 4/5 runtime).

It generates NO words. The spoken content is filled by the existing streamed generator
(tutor_loop.qwen_answer) so the Part-13 single-call streaming and TTFA <= 4 s are
untouched — the script decides WHAT and WHETHER-A-VISUAL; the generator fills the words.
This is the fast path (§18.1); the full-LLM medium path (§5.2) is deferred.
"""

from __future__ import annotations

import uuid

from . import templates, visual_gate
from .contracts import (
    AssessmentHook,
    Beat,
    ResponseContext,
    ResponseKind,
    TeachingScript,
    VisualType,
)


class TeachingScriptPlanner:
    def plan(self, ctx: ResponseContext) -> TeachingScript:
        script_id = f"script_{uuid.uuid4().hex[:10]}"

        if ctx.response_kind != ResponseKind.INSTRUCTIONAL:
            return self._social_script(ctx, script_id)

        spine = templates.spine_for(ctx.pedagogical_action)
        evidence_ids = [e.get("id") for e in ctx.evidence if e.get("id")]

        # The gate runs ONCE, on the first visual-candidate slot — that beat owns the
        # turn's display decision. Later visual-candidate slots inherit NONE (one visual
        # per teaching move keeps the panel coherent, §3.1).
        gate_intent = None
        gated = False

        beats: list[Beat] = []
        for i, bt in enumerate(spine):
            beat = Beat(
                beat_id=f"b{i}",
                pedagogical_step=bt.step,
                atomic_learning_claim=self._claim(ctx, bt),
                evidence_refs=self._beat_evidence(ctx, bt, evidence_ids),
                robot_intent=list(bt.robot),
            )
            if bt.visual_candidate and not gated:
                gate_intent = visual_gate.decide(ctx)
                beat.visual_intent = gate_intent
                gated = True
                if gate_intent.allowed and gate_intent.asset_ref:
                    # the chosen asset id is itself evidence the beat cites
                    if gate_intent.asset_ref not in beat.evidence_refs:
                        beat.evidence_refs.append(gate_intent.asset_ref)
            if bt.assessment is not None:
                beat.assessment_hook = AssessmentHook(
                    hook_id=f"{script_id}_hook{i}",
                    hook_type=bt.assessment,
                    execution_mode=bt.assessment_mode,
                    target_concept=ctx.concept_id,
                    target_misconception=(ctx.misconception_targets[0]
                                          if ctx.misconception_targets else None),
                    evidence_refs=list(beat.evidence_refs),
                    telemetry_tags=[ctx.pedagogical_action or "unknown", bt.step],
                )
                beat.completion_condition = (
                    "await_spoken_answer" if bt.assessment_mode.value == "spoken"
                    else "await_local_response")
            beats.append(beat)

        # linear on_complete chain
        for i in range(len(beats) - 1):
            beats[i].on_complete = beats[i + 1].beat_id

        return TeachingScript(
            script_id=script_id,
            turn_id=ctx.turn_id,
            response_kind=ctx.response_kind,
            pedagogical_action=ctx.pedagogical_action,
            teaching_goal=ctx.teaching_goal,
            concept_id=ctx.concept_id,
            misconception_targets=list(ctx.misconception_targets),
            representation_targets=list(ctx.representation_targets),
            evidence_manifest_ref=ctx.evidence_manifest_ref,
            device_profile=dict(ctx.device_profile),
            beats=beats,
            entry_beat_id=beats[0].beat_id if beats else None,
        )

    # ------------------------------------------------------------------
    def _social_script(self, ctx: ResponseContext, script_id: str) -> TeachingScript:
        """A minimal speech-only script for social/administrative/off_domain turns
        (§4.1). No concept/evidence/visual required — the validator relaxes grounding
        for these kinds."""
        beat = Beat(
            beat_id="b0",
            pedagogical_step="explain",
            atomic_learning_claim="",
            evidence_refs=[],
        )
        return TeachingScript(
            script_id=script_id,
            turn_id=ctx.turn_id,
            response_kind=ctx.response_kind,
            pedagogical_action=ctx.pedagogical_action,
            device_profile=dict(ctx.device_profile),
            beats=[beat],
            entry_beat_id="b0",
        )

    @staticmethod
    def _claim(ctx: ResponseContext, bt: "templates.BeatTemplate") -> str:
        """A short grounded claim string for the beat.

        Deterministic and number-free by construction (the words come from the streamed
        generator, not here) so the validator's numeric/formula cross-check has nothing
        unsupported to catch on the fast path — a future LLM planner authoring claims with
        numbers is exactly what that check guards."""
        concept = (ctx.concept_id or "this idea").split("__")[-1].replace("_", " ")
        return f"{bt.claim_hint} (concept: {concept})".strip()

    @staticmethod
    def _beat_evidence(ctx: ResponseContext, bt: "templates.BeatTemplate",
                       evidence_ids: list[str]) -> list[str]:
        """Which evidence a beat cites. Content beats cite the manifest; framing beats
        (orient/close/encourage) may cite nothing. Every instructional CONTENT beat must
        cite >=1 (validator rule 1)."""
        framing = {templates.STEP_ORIENT, templates.STEP_CLOSE, templates.STEP_ENCOURAGE}
        if bt.step in framing:
            return []
        return list(evidence_ids)
