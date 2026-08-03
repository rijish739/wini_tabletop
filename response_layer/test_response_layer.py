"""Response Layer unit tests — pure Python, no pytest, no Vertex/torch.

Runs on the Pi venv directly:

    .venv/bin/python -m response_layer.test_response_layer

Covers the Phase-1+2 surface: contracts round-trip, a spine for every action, the Visual
Benefit Gate's accept/reject cases, and every validator rule (allowed-step, probe-before-
correct, visual/step + device compatibility, claim<->evidence numeric grounding, robot
drop, speech-only fallback).
"""

from __future__ import annotations

import sys
import traceback

from . import templates, visual_gate
from .adapter import build_response_context
from .contracts import (
    AssessmentHook,
    AssessmentHookType,
    Beat,
    ExecutionMode,
    ResponseKind,
    RobotPrimitive,
    TeachingScript,
    VisualIntent,
    VisualType,
)
from .device_profile import WINIPI5_PROFILE, DeviceCapabilityProfile
from .planner import TeachingScriptPlanner
from .validator import ScriptValidator

_PLANNER = TeachingScriptPlanner()
_VALIDATOR = ScriptValidator()
_PROFILE = WINIPI5_PROFILE.to_dict()


# ---------------------------------------------------------------------------
def _ctx(**kw):
    base = dict(pedagogical_action="EXPLAIN", concept_id="jemh104__quadratic_formula",
                concept_type="derivation", evidence=[{"id": "c1", "type": "chunk"}],
                device_profile=_PROFILE)
    base.update(kw)
    return build_response_context(**base)


# ---- contracts ------------------------------------------------------------
def test_contracts_round_trip():
    hook = AssessmentHook(hook_id="h1", hook_type=AssessmentHookType.MISCONCEPTION_PROBE,
                          execution_mode=ExecutionMode.SPOKEN, target_concept="c",
                          branch_targets={"incorrect": "b2"})
    beat = Beat(beat_id="b0", pedagogical_step="explain", atomic_learning_claim="x",
                evidence_refs=["c1"], robot_intent=[RobotPrimitive.LOOK_AT_SCREEN],
                assessment_hook=hook,
                visual_intent=VisualIntent(VisualType.AUTHORED_SCENE, True, "why", "scene::c"))
    script = TeachingScript(script_id="s1", turn_id="t1",
                            response_kind=ResponseKind.INSTRUCTIONAL,
                            pedagogical_action="EXPLAIN", concept_id="c", beats=[beat],
                            entry_beat_id="b0")
    d = script.to_dict()
    # JSON-safe: enums became their string values
    assert d["response_kind"] == "instructional"
    assert d["beats"][0]["visual_intent"]["visual_type"] == "authored_scene"
    assert d["beats"][0]["robot_intent"] == ["look_at_screen"]
    assert d["beats"][0]["assessment_hook"]["execution_mode"] == "spoken"
    round_tripped = TeachingScript.from_dict(d)
    assert round_tripped.beats[0].shows_visual()
    assert round_tripped.beats[0].assessment_hook.hook_type == AssessmentHookType.MISCONCEPTION_PROBE
    assert round_tripped.entry_beat().beat_id == "b0"


# ---- templates / planner --------------------------------------------------
def test_spine_for_every_action():
    for action in templates.SPINES:
        ctx = _ctx(pedagogical_action=action)
        script = _PLANNER.plan(ctx)
        assert script.beats, f"{action}: empty spine"
        for b in script.beats:
            assert templates.is_step_allowed(action, b.pedagogical_step), \
                f"{action}: step {b.pedagogical_step} not allowed by its own table"


def test_unknown_action_uses_default_spine():
    ctx = _ctx(pedagogical_action="TOTALLY_MADE_UP")
    script = _PLANNER.plan(ctx)
    assert len(script.beats) == 1 and script.beats[0].pedagogical_step == templates.STEP_EXPLAIN


def test_linear_chain_links():
    ctx = _ctx(pedagogical_action="EXPLAIN")
    script = _PLANNER.plan(ctx)
    assert len(script.beats) >= 2
    assert script.beats[0].on_complete == script.beats[1].beat_id


# ---- visual gate ----------------------------------------------------------
def test_gate_representation_remedy_earns_scene():
    ctx = _ctx(pedagogical_action="REPRESENTATION_TRANSLATION", wants_visual=True)
    vi = visual_gate.decide(ctx)
    # draw-the-answer: earned -> generated scene, no pre-existing asset required
    assert vi.allowed and vi.visual_type == VisualType.GENERATED_DECLARATIVE_SCENE_SPEC


def test_gate_high_load_rejects_decorative_visual():
    ctx = _ctx(pedagogical_action="EXPLAIN", cognitive_load=0.85,
               available_scene_concept_id="jemh104__quadratic_formula")
    vi = visual_gate.decide(ctx)
    assert not vi.allowed and "high cognitive load" in vi.reason


def test_gate_high_load_but_remedy_still_allows():
    ctx = _ctx(pedagogical_action="REPRESENTATION_TRANSLATION", cognitive_load=0.85,
               wants_visual=True, available_scene_concept_id="jemh104__quadratic_formula")
    vi = visual_gate.decide(ctx)
    assert vi.allowed  # a representation remedy survives high load


def test_gate_test_mode_rejects():
    ctx = _ctx(mode="TEST", available_scene_concept_id="jemh104__quadratic_formula")
    vi = visual_gate.decide(ctx)
    assert not vi.allowed and "test turn" in vi.reason


def test_gate_definitional_concept_speech_only():
    # non-visual concept, no scene, no crop, no remedy -> suppress (the live fix)
    ctx = _ctx(pedagogical_action="EXPLAIN", concept_id="jemh104__meaning_of_solution",
               concept_type="definitional", available_scene_concept_id=None,
               available_crop=None)
    vi = visual_gate.decide(ctx)
    assert not vi.allowed and vi.visual_type == VisualType.NONE


def test_gate_visual_concept_earns_drawn_scene():
    ctx = _ctx(pedagogical_action="EXPLAIN", concept_id="jemh106__area_of_triangle",
               concept_type="geometry")
    vi = visual_gate.decide(ctx)
    assert vi.allowed and vi.visual_type == VisualType.GENERATED_DECLARATIVE_SCENE_SPEC
    assert vi.asset_ref is None  # drawn from the answer, not a stored asset


def test_gate_draws_without_preexisting_asset():
    # inherently visual concept, no stored scene/crop -> still earned (we draw it)
    ctx = _ctx(pedagogical_action="EXPLAIN", concept_id="jemh106__area_of_triangle",
               concept_type="geometry", available_scene_concept_id=None, available_crop=None)
    vi = visual_gate.decide(ctx)
    assert vi.allowed and vi.visual_type == VisualType.GENERATED_DECLARATIVE_SCENE_SPEC


def test_gate_social_kind_rejects():
    ctx = _ctx(response_kind="social", available_scene_concept_id="jemh104__quadratic_formula")
    vi = visual_gate.decide(ctx)
    assert not vi.allowed


# ---- validator ------------------------------------------------------------
def test_validator_clean_script_keeps_visual():
    ctx = _ctx(pedagogical_action="EXPLAIN",
               available_scene_concept_id="jemh104__quadratic_formula")
    script = _PLANNER.plan(ctx)
    _VALIDATOR.validate(script, evidence_text={"c1": "quadratic formula"}, profile=_PROFILE)
    assert script.validation["ok"]
    assert script.validation["visual"]["allowed"]
    assert script.validation["visual"]["type"] == "generated_declarative_scene_spec"


def test_validator_probe_before_correct_rejects():
    # hand-craft a script that corrects an unconfirmed misconception
    beat = Beat(beat_id="b0", pedagogical_step=templates.STEP_CORRECT,
                atomic_learning_claim="the correction", evidence_refs=["c1"],
                visual_intent=VisualIntent(VisualType.AUTHORED_SCENE, True, "x", "scene::c"))
    script = TeachingScript(script_id="s", turn_id="t",
                            response_kind=ResponseKind.INSTRUCTIONAL,
                            pedagogical_action="MISCONCEPTION_PROBE", concept_id="c",
                            beats=[beat], entry_beat_id="b0", device_profile=_PROFILE)
    _VALIDATOR.validate(script, evidence_text={"c1": "text"}, profile=_PROFILE)
    assert not script.validation["ok"]
    assert not script.validation["probe_before_correct_ok"]
    assert not script.validation["visual"]["allowed"]  # speech-only fallback


def test_validator_illegal_step_rejects():
    beat = Beat(beat_id="b0", pedagogical_step=templates.STEP_TEST_SUMMARY,
                atomic_learning_claim="x", evidence_refs=["c1"])
    script = TeachingScript(script_id="s", turn_id="t",
                            response_kind=ResponseKind.INSTRUCTIONAL,
                            pedagogical_action="EXPLAIN", concept_id="c", beats=[beat],
                            entry_beat_id="b0", device_profile=_PROFILE)
    _VALIDATOR.validate(script, evidence_text={"c1": "t"}, profile=_PROFILE)
    assert not script.validation["allowed_steps_ok"]


def test_validator_numeric_mismatch_drops_visual():
    beat = Beat(beat_id="b0", pedagogical_step=templates.STEP_EXPLAIN,
                atomic_learning_claim="the answer is 42 apples", evidence_refs=["c1"],
                visual_intent=VisualIntent(VisualType.RETRIEVED_CROP, True, "x", "fig.png"))
    script = TeachingScript(script_id="s", turn_id="t",
                            response_kind=ResponseKind.INSTRUCTIONAL,
                            pedagogical_action="EXPLAIN", concept_id="c", beats=[beat],
                            entry_beat_id="b0", device_profile=_PROFILE)
    _VALIDATOR.validate(script, evidence_text={"c1": "there are seven apples"}, profile=_PROFILE)
    assert not script.validation["visual"]["allowed"]  # 42 is ungrounded
    assert any("42" in i for i in script.validation["issues"])


def test_validator_numeric_grounded_keeps_visual():
    beat = Beat(beat_id="b0", pedagogical_step=templates.STEP_EXPLAIN,
                atomic_learning_claim="the answer is 42 apples", evidence_refs=["c1"],
                visual_intent=VisualIntent(VisualType.RETRIEVED_CROP, True, "x", "fig.png"))
    script = TeachingScript(script_id="s", turn_id="t",
                            response_kind=ResponseKind.INSTRUCTIONAL,
                            pedagogical_action="EXPLAIN", concept_id="c", beats=[beat],
                            entry_beat_id="b0", device_profile=_PROFILE)
    _VALIDATOR.validate(script, evidence_text={"c1": "there are 42 apples"}, profile=_PROFILE)
    assert script.validation["visual"]["allowed"]


def test_validator_visual_on_probe_beat_dropped():
    beat = Beat(beat_id="b0", pedagogical_step=templates.STEP_PROBE,
                atomic_learning_claim="", evidence_refs=["c1"],
                visual_intent=VisualIntent(VisualType.AUTHORED_SCENE, True, "x", "scene::c"))
    script = TeachingScript(script_id="s", turn_id="t",
                            response_kind=ResponseKind.INSTRUCTIONAL,
                            pedagogical_action="MISCONCEPTION_PROBE", concept_id="c",
                            beats=[beat], entry_beat_id="b0", device_profile=_PROFILE)
    _VALIDATOR.validate(script, evidence_text={"c1": "t"}, profile=_PROFILE)
    assert not script.validation["visual"]["allowed"]


def test_validator_robot_dropped_on_pi():
    ctx = _ctx(pedagogical_action="EXPLAIN")
    script = _PLANNER.plan(ctx)  # EXPLAIN spine carries LOOK_AT_SCREEN / LOOK_AT_LEARNER
    _VALIDATOR.validate(script, evidence_text={"c1": "t"}, profile=_PROFILE)
    assert script.validation["robot_dropped"] >= 1
    assert all(not b.robot_intent for b in script.beats)  # none survive on winipi5


def test_validator_device_cannot_render_scene_drops_it():
    no_scene = DeviceCapabilityProfile(supports_authored_scene=False).to_dict()
    beat = Beat(beat_id="b0", pedagogical_step=templates.STEP_EXPLAIN,
                atomic_learning_claim="x", evidence_refs=["c1"],
                visual_intent=VisualIntent(VisualType.AUTHORED_SCENE, True, "x", "scene::c"))
    script = TeachingScript(script_id="s", turn_id="t",
                            response_kind=ResponseKind.INSTRUCTIONAL,
                            pedagogical_action="EXPLAIN", concept_id="c", beats=[beat],
                            entry_beat_id="b0", device_profile=no_scene)
    _VALIDATOR.validate(script, evidence_text={"c1": "t"}, profile=no_scene)
    assert not script.validation["visual"]["allowed"]


def test_social_script_is_speech_only():
    ctx = _ctx(response_kind="social", pedagogical_action=None, concept_id=None, evidence=[])
    script = _PLANNER.plan(ctx)
    _VALIDATOR.validate(script, evidence_text={}, profile=_PROFILE)
    assert script.validation["ok"]
    assert not script.validation["visual"]["allowed"]


# ---- scene_author (draw the answer) — deterministic parts, no LLM ----------
def test_scene_author_layout_every_label_has_at():
    from .scene_author import layout_scene
    scene = layout_scene("jemh104__quadratic_formula", "Quadratic Formula",
                         ["x² + 2x − 3 = 0", "x = (−b ± √(b²−4ac)) / 2a", "x = 1 or x = −3"])
    assert scene["generated"] is True and len(scene["beats"]) == 3
    for b in scene["beats"]:
        el = b["in"][0]
        assert el["t"] == "label" and el.get("at") and el.get("text")  # never missing 'at'
        assert 0.0 <= el["at"][1] <= 1.0


def test_scene_author_renders_without_skips():
    # the generated spec must render through the real device path with no skipped labels
    from figures.scene_render import render_beat_frame
    from .scene_author import layout_scene
    scene = layout_scene("c", "T", ["a = 1", "b = 2", "c = 3"])
    img = render_beat_frame(scene, len(scene["beats"]) - 1, "light", scale=1.0)
    assert img.size == (scene["canvas"]["w"], scene["canvas"]["h"])


def test_scene_author_grounding_drops_invented_multidigit():
    from .scene_author import _ground_lines
    ans = "the answer is 42 apples and we started with 7"
    kept = _ground_lines(["total = 42", "start = 7", "bonus = 99"], ans)
    assert "total = 42" in kept and "start = 7" in kept
    assert "bonus = 99" not in kept          # 99 is multi-digit + not in the answer


def test_scene_author_grounding_keeps_formula_constants():
    from .scene_author import _ground_lines
    # the quadratic formula's 2 and 4 are single-digit structural constants -> keep
    kept = _ground_lines(["x = (−b ± √(b²−4ac)) / 2a"], "the quadratic formula gives x")
    assert len(kept) == 1


def test_scene_author_grounding_number_words():
    from .scene_author import _ground_lines
    # spoken words 'twenty ... one' ground a board '21'? no (compound) — but single are ok
    kept = _ground_lines(["2x + 5"], "two x plus five")  # single digits pass anyway
    assert kept == ["2x + 5"]


# ---------------------------------------------------------------------------
def main() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  PASS {t.__name__}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed ({len(tests)} total)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
