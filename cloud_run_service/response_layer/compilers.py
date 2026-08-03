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


def _compile_board_buddy(scene: dict, answer: str | None, profile: dict,
                         want_animation: bool = False,
                         want_real_life: bool = False) -> dict | None:
    """A scene-bearing beat on a Board-Buddy device compiles to a Board Buddy payload
    instead of a scene_spec (§5).

    ``want_animation`` / ``want_real_life`` are the turn's explicit asks (the child said
    "animate it" / "real-life example"): they steer the author toward an ``animate_param`` /
    real-object ``stickers`` board — the answer already describes the motion / countable
    objects (tutor_loop cue -> prompt), so the belt still grounds every value.

    Prefer a DIRECT Board Buddy author from the answer (the rich path: stickers, fraction,
    numberline hops, geometry, graph + animate_param — the full v1.0 tool set), grounded by
    the belt. It runs off the time-to-first-audio path (after generation, with the answer
    audio already streaming), so its ~1s cost is hidden. Fall back to the conservative
    scene->payload translation (text/graph only) when the author declines or errs, so a
    Board-Buddy device always degrades to something drawable — and finally to the scene PNG
    (caller) if even that is empty."""
    import os
    from .board_buddy_author import (payload_has_animation, tmax_hint,
                                     author_board_from_answer)
    from .board_buddy_compile import compile_scene_to_board

    # RICH PATH (flag-gated, BOARD_BUDDY_FULL_FEATURE_PLAN.md Phase B): the LLM segment loop
    # plans a small SEQUENCE of board frames (varied tools + per-frame animation), each
    # grounded against the whole answer. `segments` drive the live device surface (board_open
    # -> board* -> board_close); `payload` is the merged flat board for the single-image
    # (static / animated APNG) web preview. Off by default -> the single author path below.
    if answer and os.getenv("WINI_BB_ORCHESTRATOR", "").strip() in ("1", "true", "on"):
        try:
            from .board_buddy_orchestrator import author_board_orchestrated
            orch = author_board_orchestrated(answer, profile=profile,
                                             want_animation=want_animation,
                                             want_real_life=want_real_life)
        except Exception:  # noqa: BLE001 — a drawing failure never costs a turn
            orch = None
        if orch and orch.get("merged"):
            return {"kind": "board_buddy_payload", "payload": orch["merged"],
                    "segments": orch["segments"], "tmax": orch.get("tmax", 0.0),
                    "animated": bool(orch.get("animated")),
                    "narration_mode": NARRATION_SCRIPT_OVERRIDE}

    payload = None
    if answer:
        try:
            payload = author_board_from_answer(answer, profile=profile,
                                               want_animation=want_animation,
                                               want_real_life=want_real_life)
        except Exception:  # noqa: BLE001 — a drawing failure never costs a turn
            payload = None
    # Deterministic real-life SAFETY NET: the child EXPLICITLY asked for a real-life example,
    # so a real-object sticker board must not silently miss when the author's 2nd Gemini call
    # returns nothing/only a badge. Synthesize stickers of the countable object the answer
    # names (number + object both grounded in the answer). BOARD_BUDDY_FULL_FEATURE_PLAN §E.
    if want_real_life:
        from .board_buddy_author import stickers_from_answer, _STICKER_BADGES
        real = [e for e in (payload or [])
                if e.get("type") == "stickers" and e.get("item") not in _STICKER_BADGES]
        if not real:
            extra = stickers_from_answer(answer, profile)
            if extra:
                payload = extra + [e for e in (payload or []) if e.get("type") == "text"][:3]
    if not payload:
        payload = compile_scene_to_board(scene, answer=answer, profile=profile)
    if not payload:
        return None
    return {"kind": "board_buddy_payload", "payload": payload,
            # A single authored board is one segment for the live surface.
            "segments": [{"payload": payload, "tmax": tmax_hint(payload),
                          "animated": payload_has_animation(payload), "speech": None}],
            "tmax": tmax_hint(payload), "animated": payload_has_animation(payload),
            "narration_mode": NARRATION_SCRIPT_OVERRIDE}


def _compile_visual(beat, scene: dict | None, profile: dict,
                    answer: str | None = None, want_animation: bool = False,
                    want_real_life: bool = False) -> dict | None:
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
        board_capable = bool(profile.get("renderer") == "board_buddy"
                             or profile.get("supports_board_buddy"))
        if scene is not None:
            review = review_scene(scene)
            if not review.ok:
                return None
            # Board-Buddy device: emit the richer payload when the scene translates;
            # otherwise fall through to the scene_spec PNG path (still valid on the Pi).
            if board_capable:
                board = _compile_board_buddy(scene, answer, profile,
                                             want_animation, want_real_life)
                if board is not None:
                    return board
            return {"kind": "scene_spec",
                    "scene": scene_for_narration_mode(scene, NARRATION_SCRIPT_OVERRIDE),
                    "narration_mode": NARRATION_SCRIPT_OVERRIDE}
        # No scene (scene_author declined — e.g. a qualitative GEOMETRY answer like "a right
        # triangle" from which text-extraction found no groundable lines). A Board-Buddy
        # device can STILL author the board schema DIRECTLY from the answer: the LLM emits
        # Board Buddy elements (a `geometry` shape, stickers, ...) whose grounding needs no
        # numeric lines, so the shape draws even when the scene path produced nothing. This
        # is the "LLM output follows Board Buddy's schema exactly" path (user directive
        # 2026-07-30); the belt still drops any ungrounded quantity.
        if board_capable and answer:
            board = _compile_board_buddy(None, answer, profile,
                                         want_animation, want_real_life)
            if board is not None:
                return board
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
                     scene: dict | None = None, profile: dict | None = None,
                     want_animation: bool = False,
                     want_real_life: bool = False) -> dict[str, Any]:
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
            "visual": _compile_visual(beat, scene if beat.shows_visual() else None,
                                      profile, answer=answer,
                                      want_animation=want_animation,
                                      want_real_life=want_real_life),
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

