"""Phase 3 modality compilers.

Compilers consume a validated TeachingScript and produce deterministic device artifacts.
They never add instructional claims: speech is supplied by the script or the already
generated answer, text is a canonical claim, and visuals only reference validated assets.
"""
from __future__ import annotations
import uuid
from typing import Any

from .contracts import ExecutionMode, RobotPrimitive, TeachingScript, VisualType
from .scene_adaptation import NARRATION_SCRIPT_OVERRIDE, review_scene, scene_for_narration_mode


def _allowed_primitives(profile: dict) -> set[RobotPrimitive]:
    allowed: set[RobotPrimitive] = set()
    for value in profile.get("robot_primitives") or []:
        try:
            allowed.add(value if isinstance(value, RobotPrimitive) else RobotPrimitive(value))
        except ValueError:
            pass
    return allowed


def _text_pages(text: str, limit: int) -> list[str]:
    """Respect transport/UI limits by splitting, never truncating instructional text."""
    text = str(text or "").strip()
    if not text:
        return []
    if limit <= 0 or len(text) <= limit:
        return [text]
    pages: list[str] = []
    rest = text
    while rest:
        if len(rest) <= limit:
            pages.append(rest)
            break
        cut = rest.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
        pages.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    return pages


def _compile_visual(beat, scene: dict | None, profile: dict) -> dict | None:
    intent = beat.visual_intent
    if intent is None or not intent.allowed or intent.visual_type == VisualType.NONE:
        return None
    if not profile.get("display_present", True):
        return None
    if intent.visual_type == VisualType.RETRIEVED_CROP:
        return {"kind": "retrieved_crop", "asset_ref": intent.asset_ref,
                "representation_target": intent.representation_target}
    if intent.visual_type in (VisualType.AUTHORED_SCENE,
                               VisualType.GENERATED_DECLARATIVE_SCENE_SPEC):
        if scene is not None:
            review = review_scene(scene)
            if not review.ok:
                return None
            return {"kind": "scene_spec",
                    "scene": scene_for_narration_mode(scene, NARRATION_SCRIPT_OVERRIDE),
                    "narration_mode": NARRATION_SCRIPT_OVERRIDE}
        if intent.visual_type == VisualType.AUTHORED_SCENE and intent.asset_ref:
            return {"kind": "authored_scene_ref", "asset_ref": intent.asset_ref,
                    "narration_mode": NARRATION_SCRIPT_OVERRIDE}
        # A valid generated visual can be delivered in a later package; do not invent one.
        return {"kind": "pending_scene"} if intent.visual_type == VisualType.GENERATED_DECLARATIVE_SCENE_SPEC else None
    if intent.visual_type == VisualType.STATIC_TEXT_FORMULA:
        return {"kind": "formula_text", "text": beat.text_intent or beat.atomic_learning_claim}
    return None


def _compile_interaction(beat, profile: dict) -> dict | None:
    hook = beat.assessment_hook
    if hook is None:
        return None
    common = {"hook_id": hook.hook_id, "hook_type": hook.hook_type.value,
              "expected_response_type": hook.expected_response_type,
              "target_concept": hook.target_concept,
              "target_misconception": hook.target_misconception,
              "state_update_intent": hook.state_update_intent,
              "evidence_refs": list(hook.evidence_refs),
              "idempotency_seed": f"{hook.hook_id}:{beat.beat_id}"}
    if hook.execution_mode == ExecutionMode.SPOKEN:
        return {"kind": "spoken_checkpoint", **common}
    if not profile.get("touch_present", False):
        return None
    return {"kind": "touch_prompt", **common}


def compile_response(script: TeachingScript, *, answer: str | None = None,
                     scene: dict | None = None, profile: dict | None = None) -> dict[str, Any]:
    """Compile a validated script into Pi-safe modality records.

    The generated answer is bound once, to the first executable beat lacking authored
    spoken content. It is copied verbatim; compilers do not paraphrase or synthesize.
    """
    profile = dict(profile or script.device_profile or {})
    allowed_primitives = _allowed_primitives(profile)
    max_text = int(profile.get("max_text_len_per_beat") or 0)
    compiled: list[dict[str, Any]] = []
    answer_bound = False
    robot_dropped = 0

    for beat in script.beats:
        spoken = str(beat.spoken_content or "")
        if not spoken and answer and not answer_bound:
            spoken = str(answer)
            answer_bound = True
        robot = [primitive.value for primitive in beat.robot_intent
                 if primitive in allowed_primitives]
        robot_dropped += len(beat.robot_intent) - len(robot)
        caption = beat.text_intent or beat.atomic_learning_claim
        compiled.append({
            "beat_id": beat.beat_id,
            "pedagogical_step": beat.pedagogical_step,
            "claim": beat.atomic_learning_claim,
            "evidence_refs": list(beat.evidence_refs),
            "speech": {"text": spoken} if spoken else None,
            "visual": _compile_visual(beat, scene if beat.shows_visual() else None, profile),
            "lvgl_text": {"pages": _text_pages(caption, max_text)} if caption else None,
            "interaction": _compile_interaction(beat, profile),
            "robot": robot,
            "timing_policy": beat.timing_policy,
            "completion_condition": beat.completion_condition,
            "fallback_behavior": beat.fallback_behavior,
            "resumable": beat.resumable,
            "on_complete": beat.on_complete,
            "on_correct": beat.on_correct,
            "on_incorrect": beat.on_incorrect,
            "on_nonresponse": beat.on_nonresponse,
        })
    return {
        "bundle_schema_version": 1,
        "bundle_id": f"bundle_{uuid.uuid4().hex[:12]}",
        "script_id": script.script_id,
        "turn_id": script.turn_id,
        "response_kind": script.response_kind.value,
        "entry_beat_id": script.entry_beat_id,
        "device_profile": profile,
        "beats": compiled,
        "compiler_telemetry": {"robot_primitives_dropped": robot_dropped},
    }

