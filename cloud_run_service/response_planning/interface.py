"""Approved teaching and modality plans behind one Response Planning Interface."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping, Protocol

from response_layer.adapter import build_response_context
from response_layer.contracts import AssessmentHook, TeachingScript
from response_layer.contracts import AssessmentHookType, ExecutionMode
from response_layer.planner import TeachingScriptPlanner
from response_layer.validator import ScriptValidator
from runtime.contracts import (
    FailureSeverity,
    FailureSignal,
    ModuleOutcome,
    TurnInput,
    deep_freeze,
)


CAPABILITY = "response_planning"

if TYPE_CHECKING:
    from pedagogy import PedagogicalDecision
    from retrieval import RetrievalResult


@dataclass(frozen=True)
class ResponsePlanningStateView:
    """Immutable turn-local facts Response Planning may observe."""

    concept_type: str | None = None
    misconception_targets: tuple[str, ...] = ()
    representation_targets: tuple[str, ...] = ()
    cognitive_load: float = 0.0
    frustration_risk: float = 0.0
    mastery: float | None = None
    misconception_confirmed: bool = False
    wants_visual: bool = False
    wants_animation: bool = False
    wants_real_life: bool = False
    clarification: bool = False
    available_scene_concept_id: str | None = None
    available_crop: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "misconception_targets", tuple(self.misconception_targets))
        object.__setattr__(self, "representation_targets", tuple(self.representation_targets))
        if self.available_crop is not None:
            object.__setattr__(self, "available_crop", deep_freeze(self.available_crop))


@dataclass(frozen=True)
class ResponsePlanningRequest:
    turn_input: TurnInput
    pedagogical: "PedagogicalDecision"
    retrieval: "RetrievalResult"
    concept_id: str | None
    state: ResponsePlanningStateView = ResponsePlanningStateView()
    response_kind: str = "instructional"


@dataclass(frozen=True)
class AssessmentProposal:
    """A verified candidate carried forward for Presentation; never armed here."""

    item_id: str
    hook: AssessmentHook
    armed: bool = False


@dataclass(frozen=True)
class ResponsePlan:
    script: TeachingScript
    intended_modalities: tuple[str, ...]
    approved_modalities: tuple[str, ...]
    assessment_proposal: AssessmentProposal | None = None


class ResponsePlanningInterface(Protocol):
    def plan(self, request: ResponsePlanningRequest) -> ModuleOutcome[ResponsePlan]: ...


class ResponsePlanning:
    """Convert pedagogy and grounded evidence into a validated, unrealized plan."""

    def __init__(self) -> None:
        self._planner = TeachingScriptPlanner()
        self._validator = ScriptValidator()

    def plan(self, request: ResponsePlanningRequest) -> ModuleOutcome[ResponsePlan]:
        if not request.turn_input.device.speech:
            return self._invalid("unsupported_capability", "capability", valid=False)
        evidence = request.retrieval.manifest.evidence
        if request.response_kind == "instructional" and not evidence:
            return self._invalid("grounding_violation", "grounding", valid=False)
        try:
            profile = self._profile(request)
            rows = [item.to_dict() for item in evidence]
            state = request.state
            ctx = build_response_context(
                turn_id=request.turn_input.turn_id,
                pedagogical_action=request.pedagogical.action,
                need=request.pedagogical.need,
                teaching_goal=request.pedagogical.need,
                concept_id=request.concept_id,
                concept_type=state.concept_type,
                evidence=rows,
                response_kind=request.response_kind,
                mode=request.pedagogical.mode,
                wants_visual=(state.wants_visual or request.pedagogical.action in {
                    "REPRESENTATION_TRANSLATION", "VISUAL_ANALOGY"}),
                wants_animation=state.wants_animation,
                wants_real_life=state.wants_real_life,
                clarification=state.clarification,
                is_intro=request.pedagogical.introduction,
                grounding=request.retrieval.manifest.grounding,
                misconception_targets=list(state.misconception_targets),
                representation_targets=list(state.representation_targets),
                misconception_confirmed=state.misconception_confirmed,
                cognitive_load=state.cognitive_load,
                frustration_risk=state.frustration_risk,
                mastery=state.mastery,
                available_scene_concept_id=state.available_scene_concept_id,
                available_crop=(dict(state.available_crop) if state.available_crop else None),
                device_profile=profile,
            )
            script = self._planner.plan(ctx)
            proposal = self._attach_proposal(script, request)
            evidence_text = {
                item.id: str(item.content.get("text") or item.content.get("question")
                             or item.content.get("why_wrong") or "")
                for item in evidence
            }
            self._validator.validate(script, evidence_text=evidence_text, profile=profile)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            return self._invalid("invalid_plan", "validation", valid=False, detail=str(exc))

        if not script.validation.get("allowed_steps_ok", True):
            return self._invalid("illegal_teaching_step", "validation", valid=False)
        if not script.validation.get("grounding_ok", True):
            return self._invalid("grounding_violation", "grounding", valid=False)
        if not script.validation.get("ok", False):
            return self._invalid("invalid_plan", "validation", valid=False)

        visual = bool((script.validation.get("visual") or {}).get("allowed"))
        visual_intended = request.response_kind == "instructional" and bool(
            state.wants_visual or state.representation_targets
            or request.pedagogical.action in {
                "REPRESENTATION_TRANSLATION", "VISUAL_ANALOGY"}
        )
        intended = ("speech", "display") if visual_intended else ("speech",)
        approved = ("speech", "display") if visual else ("speech",)
        failures = ()
        visual_was_intended = any(
            beat.visual_intent is not None and "device" in beat.visual_intent.reason
            for beat in script.beats
        )
        if visual_was_intended or (not request.turn_input.device.display and
                                   (state.wants_visual or state.representation_targets)):
            failures = (self._signal("unsupported_capability", "capability", True),)
        return ModuleOutcome(value=ResponsePlan(
            script=copy.deepcopy(script), intended_modalities=intended,
            approved_modalities=approved,
            assessment_proposal=proposal,
        ), failures=failures)

    @staticmethod
    def _profile(request: ResponsePlanningRequest) -> dict[str, Any]:
        device = request.turn_input.device
        return {
            "display_present": device.display,
            "renderer": "pillow_lvgl" if device.display else "none",
            "supports_authored_scene": device.display and device.authored_visuals,
            "supports_animation": bool(device.attributes.get("animation", False)),
            "supports_interactive_visual": device.display and device.touch,
            "robot_primitives": tuple(device.attributes.get("robot_primitives", ())),
        }

    @staticmethod
    def _attach_proposal(script: TeachingScript, request: ResponsePlanningRequest):
        candidate = request.retrieval.assessment_candidate
        for beat in script.beats:
            beat.assessment_hook = None
        if not candidate or not request.retrieval.assessment_allowed or not script.beats:
            return None
        data = dict(candidate)
        item_id = str(data.get("item_id") or data.get("id") or "")
        kind = str(data.get("kind") or "practice")
        hook_type = {
            "bridge": AssessmentHookType.DIAGNOSTIC_PROBE,
            "misconception": AssessmentHookType.MISCONCEPTION_PROBE,
        }.get(kind, AssessmentHookType.MICRO_CHECK)
        hook = AssessmentHook(
            hook_id=f"{script.script_id}:{script.beats[-1].beat_id}:{item_id}",
            hook_type=hook_type, execution_mode=ExecutionMode.SPOKEN,
            target_concept=data.get("concept_id"),
            target_misconception=item_id if kind == "misconception" else None,
            expected_response_type=data.get("response_type") or "short_text",
            correctness_rule=data.get("rubric") or data.get("expected_answer"),
            state_update_intent=data.get("state_update_intent") or kind,
            evidence_refs=[item_id] if item_id else [], item_id=item_id,
            question=data.get("question"), expected_answer=data.get("expected_answer"),
            rubric=data.get("rubric") or "",
            assessment_purpose=data.get("assessment_purpose") or kind,
            reveal_policy=data.get("reveal_policy") or "after_attempt",
            item_verified=bool(data.get("item_verified")),
            verification_provenance=data.get("verification_provenance"),
            verification_version=data.get("verification_version"),
            verification_status=data.get("verification_status") or "unverified",
            verification_token=data.get("verification_token"),
            item_source=data.get("item_source"),
            binary_item=bool(data.get("binary_item", False)),
            difficulty=data.get("difficulty"), metadata=dict(data.get("metadata") or {}),
            hint_chain=list(data.get("hint_chain") or []),
        )
        script.beats[-1].assessment_hook = hook
        script.beats[-1].completion_condition = "await_spoken_answer"
        return AssessmentProposal(item_id=hook.item_id or "", hook=copy.deepcopy(hook))

    @classmethod
    def _invalid(cls, cause, phase, *, valid, detail=""):
        return ModuleOutcome(value=None, failures=(cls._signal(cause, phase, valid, detail),))

    @staticmethod
    def _signal(cause, phase, valid_outcome, detail=""):
        return FailureSignal(
            capability=CAPABILITY, phase=phase,
            severity=(FailureSeverity.DEGRADED if valid_outcome else FailureSeverity.ERROR),
            recoverable=valid_outcome, cause=cause, valid_outcome=valid_outcome,
            context={"detail": detail} if detail else {},
        )
