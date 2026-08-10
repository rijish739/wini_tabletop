"""Response Layer contracts (Phase 1) — the frozen schemas every later module reads.

These are plain dataclasses + str-Enums, chosen so a script is trivially JSON-safe
(`to_dict` returns dicts/lists/str/num/bool/None only) for telemetry, transport, and
the device execution package. Field names follow the plan sections noted inline:

    ResponseContext          §5.1   (normalized input envelope)
    TeachingScript           §10.1  (canonical response object)
    Beat                     §10.2  (one atomic teaching idea; bounded-DAG node)
    AssessmentHook           §16.2  (explicit assessment object on a beat)
    OutcomeEvent             §21/§1.17 (idempotent event for the single-writer path)
    DeviceCapabilityProfile  §8.3   (lives in device_profile.py)

Design notes
------------
* Enums are ``(str, Enum)`` so ``VisualType.NONE.value == "none"`` and they serialise
  as their string directly. Unknown incoming strings coerce via ``_coerce_enum`` to a
  safe default rather than raising (belt-and-suspenders against a wrong-but-valid model
  pick — the store-side validation gate is where those are actually caught, §5.3).
* ``pedagogical_step`` is a free string (validated against the allowed-step table in
  ``templates.py``), not an enum — the step vocabulary is owned by the template layer.
* Beats form a shallow bounded branching DAG (§10.2): ``on_complete`` is the linear
  next; ``on_correct/on_incorrect/on_nonresponse`` are the at-most-one-level remediation
  branches gated by an assessment hook. Deeper adaptation returns to the PDE loop.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums (§1.16, §12.2, §13, §15.1, §16.1)
# ---------------------------------------------------------------------------
class ResponseKind(str, Enum):
    """§1.16 — only ``instructional`` requires concept/evidence grounding."""

    INSTRUCTIONAL = "instructional"
    SOCIAL = "social"
    ADMINISTRATIVE = "administrative"
    OFF_DOMAIN = "off_domain"


class VisualType(str, Enum):
    """§12.2 — what, if anything, the beat shows."""

    NONE = "none"
    STATIC_TEXT_FORMULA = "static_text_formula"
    STATIC_DIAGRAM = "static_diagram"
    RETRIEVED_CROP = "retrieved_crop"
    AUTHORED_SCENE = "authored_scene"
    GENERATED_DECLARATIVE_SCENE_SPEC = "generated_declarative_scene_spec"
    INTERACTIVE_VISUAL = "interactive_visual"
    ANIMATION = "animation"


class ExecutionMode(str, Enum):
    """§13.2/§16 — where an interaction/assessment is scored.

    ``local`` completes on-device; ``spoken`` suspends the runner and re-enters the
    cloud for STT+grading (the checkpoint mini-turn). Only ``local`` executes in this
    Phase 1+2 slice; ``spoken`` is carried in the schema, runtime deferred to Phase 4.
    """

    LOCAL = "local"
    SPOKEN = "spoken"


class AssessmentHookType(str, Enum):
    """§16.1 — the kind of learning transaction a hook represents."""

    MICRO_CHECK = "micro_check"
    DIAGNOSTIC_PROBE = "diagnostic_probe"
    MISCONCEPTION_PROBE = "misconception_probe"
    REPRESENTATION_TRANSLATION_CHECK = "representation_translation_check"
    WORKED_STEP_CHECK = "worked_step_check"
    CONFIDENCE_CHECK = "confidence_check"
    REFLECTION_PROMPT = "reflection_prompt"
    RETENTION_MARKER = "retention_marker"


class RobotPrimitive(str, Enum):
    """§15.1 — the only approved embodiment vocabulary (a closed set for safety §20.3).

    None of these execute on winipi5 (no motors): the validator drops every robot
    primitive absent from the device profile before packaging (§5.3 rule 6)."""

    LOOK_AT_SCREEN = "look_at_screen"
    LOOK_AT_LEARNER = "look_at_learner"
    POINT_TO_SCREEN_REGION = "point_to_screen_region"
    NOD = "nod"
    ENCOURAGE = "encourage"
    THINKING_PAUSE = "thinking_pause"
    CELEBRATE_SMALL_SUCCESS = "celebrate_small_success"
    SHOW_UNCERTAINTY = "show_uncertainty"
    IDLE_STILL = "idle_still"


def _coerce_enum(enum_cls, value, default):
    """Map an incoming string/enum to ``enum_cls``; unknown -> ``default`` (never raise).

    §5.3 belt: controlled generation stops *invented* enum values, but a wrong-but-valid
    one can still arrive from a cache/transport round-trip — coerce defensively here and
    let the validator reject on the semantic rules, not on a KeyError."""
    if isinstance(value, enum_cls):
        return value
    if value is None:
        return default
    try:
        return enum_cls(value)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# to_dict / from_dict helpers (JSON-safe, recursive)
# ---------------------------------------------------------------------------
def _to_jsonable(v: Any) -> Any:
    if isinstance(v, Enum):
        return v.value
    if is_dataclass(v) and not isinstance(v, type):
        return {f.name: _to_jsonable(getattr(v, f.name)) for f in fields(v)}
    if isinstance(v, dict):
        return {k: _to_jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_to_jsonable(x) for x in v]
    return v


# ---------------------------------------------------------------------------
# AssessmentHook (§16.2)
# ---------------------------------------------------------------------------
@dataclass
class AssessmentHook:
    hook_id: str
    hook_type: AssessmentHookType
    execution_mode: ExecutionMode = ExecutionMode.LOCAL
    target_concept: str | None = None
    target_misconception: str | None = None
    expected_response_type: str | None = None       # e.g. "number", "tap", "short_text"
    correctness_rule: str | None = None             # human/rule spec; grader owns detail
    hint_chain_ref: str | None = None
    state_update_intent: str | None = None          # what the single-writer path would apply
    evidence_refs: list[str] = field(default_factory=list)
    telemetry_tags: list[str] = field(default_factory=list)
    branch_targets: dict[str, str] = field(default_factory=dict)  # outcome -> beat_id
    # idempotency_key is filled at runtime (script_id+beat_id+attempt); left None at plan
    idempotency_key: str | None = None
    # P0 evidence contract. A hook is armable only when these fields identify a
    # verified, gradeable item. Legacy fields above remain for device packages.
    item_id: str | None = None
    question: str | None = None
    expected_answer: str | None = None
    rubric: str | None = None
    assessment_purpose: str | None = None
    reveal_policy: str = "after_attempt"
    item_verified: bool = False
    verification_provenance: str | None = None
    verification_version: str | None = None
    hint_chain: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return _to_jsonable(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AssessmentHook":
        d = dict(d or {})
        return cls(
            hook_id=d.get("hook_id") or f"hook_{uuid.uuid4().hex[:8]}",
            hook_type=_coerce_enum(AssessmentHookType, d.get("hook_type"),
                                   AssessmentHookType.MICRO_CHECK),
            execution_mode=_coerce_enum(ExecutionMode, d.get("execution_mode"),
                                        ExecutionMode.LOCAL),
            target_concept=d.get("target_concept"),
            target_misconception=d.get("target_misconception"),
            expected_response_type=d.get("expected_response_type"),
            correctness_rule=d.get("correctness_rule"),
            hint_chain_ref=d.get("hint_chain_ref"),
            state_update_intent=d.get("state_update_intent"),
            evidence_refs=list(d.get("evidence_refs") or []),
            telemetry_tags=list(d.get("telemetry_tags") or []),
            branch_targets=dict(d.get("branch_targets") or {}),
            idempotency_key=d.get("idempotency_key"),
            item_id=d.get("item_id"),
            question=d.get("question"),
            expected_answer=d.get("expected_answer"),
            rubric=d.get("rubric"),
            assessment_purpose=d.get("assessment_purpose"),
            reveal_policy=d.get("reveal_policy") or "after_attempt",
            item_verified=bool(d.get("item_verified", False)),
            verification_provenance=d.get("verification_provenance"),
            verification_version=d.get("verification_version"),
            hint_chain=list(d.get("hint_chain") or []),
        )


# ---------------------------------------------------------------------------
# Beat (§10.2)
# ---------------------------------------------------------------------------
@dataclass
class Beat:
    beat_id: str
    pedagogical_step: str                            # validated vs allowed-step table
    atomic_learning_claim: str = ""                  # the unit of cross-modal coherence
    evidence_refs: list[str] = field(default_factory=list)
    # Intents are DECLARATIVE — compilers (Phase 3) turn them into artifacts. Speech is
    # a hint/spec here, not the final words: the streamed generator fills the words in
    # this slice (see planner.py), keeping the Part-13 single-call streaming path.
    spoken_content: str = ""                         # authored hint OR filled at compile
    visual_intent: "VisualIntent | None" = None
    text_intent: str | None = None
    interaction_intent: str | None = None
    robot_intent: list[RobotPrimitive] = field(default_factory=list)
    assessment_hook: AssessmentHook | None = None
    timing_policy: str = "speak_then_advance"
    completion_condition: str = "speech_complete"
    fallback_behavior: str = "speech_only"           # §11 fallback for this beat
    resumable: bool = True                           # §5.6 barge-in resume flag
    # Bounded-DAG edges (§10.2). on_complete = linear next; the others are the
    # at-most-one-level remediation branches an assessment hook may take.
    on_complete: str | None = None
    on_correct: str | None = None
    on_incorrect: str | None = None
    on_nonresponse: str | None = None

    def to_dict(self) -> dict:
        return _to_jsonable(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Beat":
        d = dict(d or {})
        vi = d.get("visual_intent")
        hook = d.get("assessment_hook")
        return cls(
            beat_id=d.get("beat_id") or f"beat_{uuid.uuid4().hex[:8]}",
            pedagogical_step=d.get("pedagogical_step") or "explain",
            atomic_learning_claim=d.get("atomic_learning_claim") or "",
            evidence_refs=list(d.get("evidence_refs") or []),
            spoken_content=d.get("spoken_content") or "",
            visual_intent=VisualIntent.from_dict(vi) if vi else None,
            text_intent=d.get("text_intent"),
            interaction_intent=d.get("interaction_intent"),
            robot_intent=[_coerce_enum(RobotPrimitive, r, RobotPrimitive.IDLE_STILL)
                          for r in (d.get("robot_intent") or [])],
            assessment_hook=AssessmentHook.from_dict(hook) if hook else None,
            timing_policy=d.get("timing_policy") or "speak_then_advance",
            completion_condition=d.get("completion_condition") or "speech_complete",
            fallback_behavior=d.get("fallback_behavior") or "speech_only",
            resumable=bool(d.get("resumable", True)),
            on_complete=d.get("on_complete"),
            on_correct=d.get("on_correct"),
            on_incorrect=d.get("on_incorrect"),
            on_nonresponse=d.get("on_nonresponse"),
        )

    # A beat "shows a visual" only when it has a concrete, non-none visual intent.
    def shows_visual(self) -> bool:
        return (self.visual_intent is not None
                and self.visual_intent.visual_type != VisualType.NONE)


@dataclass
class VisualIntent:
    """The beat's visual decision (output of the Visual Benefit Gate, §12.1).

    ``allowed`` records the gate's yes/no; ``reason`` is the human-readable cause (logged
    as visual-usage or visual-suppression telemetry §21.2). ``asset_ref`` points at the
    concrete asset when one is chosen (a scene concept-id, a crop image_path, ...)."""

    visual_type: VisualType = VisualType.NONE
    allowed: bool = False
    reason: str = ""
    asset_ref: str | None = None                     # scene concept_id / crop image_path
    representation_target: str | None = None

    def to_dict(self) -> dict:
        return _to_jsonable(self)

    @classmethod
    def from_dict(cls, d: dict) -> "VisualIntent":
        d = dict(d or {})
        return cls(
            visual_type=_coerce_enum(VisualType, d.get("visual_type"), VisualType.NONE),
            allowed=bool(d.get("allowed", False)),
            reason=d.get("reason") or "",
            asset_ref=d.get("asset_ref"),
            representation_target=d.get("representation_target"),
        )


# ---------------------------------------------------------------------------
# ResponseContext (§5.1) — the one normalized input envelope
# ---------------------------------------------------------------------------
@dataclass
class ResponseContext:
    response_context_id: str
    turn_id: str
    response_kind: ResponseKind
    # upstream frozen outputs (already computed by tutor_loop.turn before generation)
    pedagogical_action: str | None = None            # the PDE macro action (owned upstream)
    need: str | None = None
    teaching_goal: str | None = None
    concept_id: str | None = None
    concept_type: str | None = None                  # from the graph node (shape/kind)
    misconception_targets: list[str] = field(default_factory=list)
    representation_targets: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)      # the manifest evidence list
    evidence_manifest_ref: str | None = None
    # learner signals that steer micro-choreography (NOT authority — planning inputs)
    cognitive_load: float = 0.0
    frustration_risk: float = 0.0
    mastery_tier: str = "medium"                     # low|medium|high (cache bucket §17.3)
    active_misconception: bool = False
    misconception_confirmed: bool = False            # gates probe-before-correct (§A3)
    grade_level: str | None = None
    mode: str = "EXPLAIN"                            # EXPLAIN|PRACTICE|TEST (session_modes)
    # turn-local signals the planner reads to shape the spine
    wants_visual: bool = False                       # a representation-gap plea this turn
    wants_animation: bool = False                    # wants to SEE MOTION -> force animate_param
    wants_real_life: bool = False                    # wants a real-life example -> stickers
    clarification: bool = False
    is_intro: bool = False
    grounding: str = "manifest_only"                 # manifest_only | method_only
    # available assets discovered upstream (so the gate can decide, not fetch)
    available_scene_concept_id: str | None = None    # a tier-0 authored scene exists
    available_crop: dict | None = None               # the crop _build_display would pick
    device_profile: dict = field(default_factory=dict)      # DeviceCapabilityProfile dict

    def to_dict(self) -> dict:
        return _to_jsonable(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ResponseContext":
        d = dict(d or {})
        return cls(
            response_context_id=d.get("response_context_id") or f"ctx_{uuid.uuid4().hex[:8]}",
            turn_id=d.get("turn_id") or f"turn_{uuid.uuid4().hex[:8]}",
            response_kind=_coerce_enum(ResponseKind, d.get("response_kind"),
                                       ResponseKind.INSTRUCTIONAL),
            pedagogical_action=d.get("pedagogical_action"),
            need=d.get("need"),
            teaching_goal=d.get("teaching_goal"),
            concept_id=d.get("concept_id"),
            concept_type=d.get("concept_type"),
            misconception_targets=list(d.get("misconception_targets") or []),
            representation_targets=list(d.get("representation_targets") or []),
            evidence=list(d.get("evidence") or []),
            evidence_manifest_ref=d.get("evidence_manifest_ref"),
            cognitive_load=float(d.get("cognitive_load") or 0.0),
            frustration_risk=float(d.get("frustration_risk") or 0.0),
            mastery_tier=d.get("mastery_tier") or "medium",
            active_misconception=bool(d.get("active_misconception", False)),
            misconception_confirmed=bool(d.get("misconception_confirmed", False)),
            grade_level=d.get("grade_level"),
            mode=d.get("mode") or "EXPLAIN",
            wants_visual=bool(d.get("wants_visual", False)),
            wants_animation=bool(d.get("wants_animation", False)),
            wants_real_life=bool(d.get("wants_real_life", False)),
            clarification=bool(d.get("clarification", False)),
            is_intro=bool(d.get("is_intro", False)),
            grounding=d.get("grounding") or "manifest_only",
            available_scene_concept_id=d.get("available_scene_concept_id"),
            available_crop=d.get("available_crop"),
            device_profile=dict(d.get("device_profile") or {}),
        )


# ---------------------------------------------------------------------------
# TeachingScript (§10.1) — the canonical response object
# ---------------------------------------------------------------------------
@dataclass
class TeachingScript:
    script_id: str
    turn_id: str
    response_kind: ResponseKind
    pedagogical_action: str | None = None
    teaching_goal: str | None = None
    concept_id: str | None = None
    misconception_targets: list[str] = field(default_factory=list)
    representation_targets: list[str] = field(default_factory=list)
    evidence_manifest_ref: str | None = None
    learner_snapshot_ref: str | None = None
    device_profile: dict = field(default_factory=dict)
    beats: list[Beat] = field(default_factory=list)
    entry_beat_id: str | None = None
    fallback_policy: str = "reduce_modalities"
    telemetry_policy: str = "observational"
    streaming_policy: str = "first_beat_commit"
    # validator output (filled by ScriptValidator; empty on a fresh draft)
    validation: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return _to_jsonable(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TeachingScript":
        d = dict(d or {})
        return cls(
            script_id=d.get("script_id") or f"script_{uuid.uuid4().hex[:8]}",
            turn_id=d.get("turn_id") or f"turn_{uuid.uuid4().hex[:8]}",
            response_kind=_coerce_enum(ResponseKind, d.get("response_kind"),
                                       ResponseKind.INSTRUCTIONAL),
            pedagogical_action=d.get("pedagogical_action"),
            teaching_goal=d.get("teaching_goal"),
            concept_id=d.get("concept_id"),
            misconception_targets=list(d.get("misconception_targets") or []),
            representation_targets=list(d.get("representation_targets") or []),
            evidence_manifest_ref=d.get("evidence_manifest_ref"),
            learner_snapshot_ref=d.get("learner_snapshot_ref"),
            device_profile=dict(d.get("device_profile") or {}),
            beats=[Beat.from_dict(b) for b in (d.get("beats") or [])],
            entry_beat_id=d.get("entry_beat_id"),
            fallback_policy=d.get("fallback_policy") or "reduce_modalities",
            telemetry_policy=d.get("telemetry_policy") or "observational",
            streaming_policy=d.get("streaming_policy") or "first_beat_commit",
            validation=dict(d.get("validation") or {}),
        )

    # --- convenience accessors used by the integration seam --------------------
    def entry_beat(self) -> Beat | None:
        if not self.beats:
            return None
        if self.entry_beat_id:
            for b in self.beats:
                if b.beat_id == self.entry_beat_id:
                    return b
        return self.beats[0]

    def first_visual_beat(self) -> Beat | None:
        """The first beat that actually shows a visual (drives the display decision)."""
        for b in self.beats:
            if b.shows_visual():
                return b
        return None

    def is_valid(self) -> bool:
        return bool(self.validation.get("ok", False))


# ---------------------------------------------------------------------------
# OutcomeEvent (§21.1 / §1.17) — idempotent event for the single-writer path
# ---------------------------------------------------------------------------
@dataclass
class OutcomeEvent:
    """Emitted by the (future) Telemetry/Outcome emitter; applied ONCE at turn close by
    the existing learner-state path (apply_probe_result / apply_bridge_result). The key
    is deterministic so a reconnect replay dedups (§B2)."""

    script_id: str
    beat_id: str
    attempt: int
    assessment_hook_id: str | None = None
    outcome: str | None = None                       # correct | incorrect | non_attempt ...
    learner_id: str | None = None
    concept_id: str | None = None
    kc_id: str | None = None
    item_id: str | None = None
    item_source: str | None = None
    assessment_purpose: str | None = None
    grader_path: str | None = None
    grader_confidence: float | None = None
    stt_confidence: float | None = None
    payload: dict = field(default_factory=dict)
    ts: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    @property
    def idempotency_key(self) -> str:
        return f"{self.script_id}:{self.beat_id}:{self.attempt}"

    def to_dict(self) -> dict:
        d = _to_jsonable(self)
        d["idempotency_key"] = self.idempotency_key
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "OutcomeEvent":
        d = dict(d or {})
        return cls(
            script_id=d.get("script_id") or "",
            beat_id=d.get("beat_id") or "",
            attempt=int(d.get("attempt") or 0),
            assessment_hook_id=d.get("assessment_hook_id"),
            outcome=d.get("outcome"),
            learner_id=d.get("learner_id"),
            concept_id=d.get("concept_id"),
            kc_id=d.get("kc_id"),
            item_id=d.get("item_id"),
            item_source=d.get("item_source"),
            assessment_purpose=d.get("assessment_purpose"),
            grader_path=d.get("grader_path"),
            grader_confidence=d.get("grader_confidence"),
            stt_confidence=d.get("stt_confidence"),
            payload=dict(d.get("payload") or {}),
            ts=d.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
