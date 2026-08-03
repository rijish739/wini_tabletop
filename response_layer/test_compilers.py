"""Phase 3 compiler tests."""
from __future__ import annotations

from .compilers import compile_response
from .contracts import (
    AssessmentHook, AssessmentHookType, Beat, ExecutionMode, ResponseKind,
    RobotPrimitive, TeachingScript, VisualIntent, VisualType,
)
from .scene_author import layout_scene


def _script(profile: dict) -> TeachingScript:
    beat = Beat(
        beat_id="b0", pedagogical_step="explain",
        atomic_learning_claim="The roots are where the graph crosses the x-axis.",
        evidence_refs=["ev1"],
        visual_intent=VisualIntent(VisualType.GENERATED_DECLARATIVE_SCENE_SPEC, True, "earned"),
        text_intent="The roots are where the graph crosses the x-axis.",
        robot_intent=[RobotPrimitive.LOOK_AT_SCREEN],
        assessment_hook=AssessmentHook(
            hook_id="hook1", hook_type=AssessmentHookType.MICRO_CHECK,
            execution_mode=ExecutionMode.LOCAL, evidence_refs=["ev1"]),
    )
    return TeachingScript(
        script_id="s1", turn_id="t1", response_kind=ResponseKind.INSTRUCTIONAL,
        pedagogical_action="EXPLAIN", concept_id="jemh104__quadratic_formula",
        device_profile=profile, beats=[beat], entry_beat_id="b0",
        validation={"ok": True},
    )


def test_compiler_binds_existing_answer_without_rewriting() -> None:
    profile = {"display_present": True, "touch_present": True,
               "robot_primitives": [], "max_text_len_per_beat": 18}
    answer = "Look where the curve crosses the horizontal axis."
    bundle = compile_response(
        _script(profile), answer=answer,
        scene=layout_scene("jemh104__quadratic_formula", "Roots", ["x = -1", "x = 3"]))
    beat = bundle["beats"][0]
    assert beat["speech"]["text"] == answer
    assert beat["visual"]["kind"] == "scene_spec"
    assert beat["visual"]["narration_mode"] == "script_override"
    assert all(not item["narration"] for item in beat["visual"]["scene"]["beats"])
    assert beat["interaction"]["kind"] == "touch_prompt"
    assert beat["robot"] == []
    assert bundle["compiler_telemetry"]["robot_primitives_dropped"] == 1
    assert len(beat["lvgl_text"]["pages"]) > 1
    assert " ".join(beat["lvgl_text"]["pages"]) == beat["claim"]


def test_spoken_checkpoint_is_not_faked_as_touch() -> None:
    profile = {"display_present": False, "touch_present": True, "robot_primitives": []}
    script = _script(profile)
    script.beats[0].assessment_hook.execution_mode = ExecutionMode.SPOKEN
    bundle = compile_response(script, answer="Can you name one root?")
    beat = bundle["beats"][0]
    assert beat["visual"] is None
    assert beat["interaction"]["kind"] == "spoken_checkpoint"


def _run() -> int:
    tests = [test_compiler_binds_existing_answer_without_rewriting,
             test_spoken_checkpoint_is_not_faked_as_touch]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed} passed, {failed} failed ({len(tests)} total)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())

