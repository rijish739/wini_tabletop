"""Board Buddy integration seam tests (BOARD_BUDDY_INTEGRATION_PLAN.md §6.10).

We do NOT retest Board Buddy itself (frozen v1.0, already unit-tested on the Pi). These
cover OUR new code: the grounding/capability belt, the scene->payload translator, the
segment orchestration loop, and the compiler/runner Board-Buddy branches. All headless
(no Vertex, no pygame) — the belt/translator/loop are pure functions with injected seams.

Run: ``python -m response_layer.test_board_buddy``
"""
from __future__ import annotations

import contextlib

from . import board_buddy_caps as caps
from .board_buddy_author import (
    MAX_ELEMENTS, payload_has_animation, stickers_from_answer, validate_board_call,
)
from .board_buddy_compile import compile_scene_to_board, scene_to_payload
from .board_buddy_orchestrator import BoardSegmentOrchestrator, _tmax_hint
from .compilers import compile_response
from .contracts import (
    Beat, ResponseKind, TeachingScript, VisualIntent, VisualType,
)
from .device_profile import ESP32_P4_PROFILE, WINIPI5_PROFILE
from .device_runner import DeviceScriptRunner
from .scene_author import parabola_scene

PI = WINIPI5_PROFILE.to_dict()


@contextlib.contextmanager
def _deterministic_board():
    """Force the compiler's DETERMINISTIC scene->payload path.

    `_compile_board_buddy` prefers `author_board_from_answer`, which is a LIVE Gemini
    call — billed, ~1-10 s, and nondeterministic. Measured 2026-08-02 on the same input:
    two calls returned ['text', 'stickers', 'graph'] and the third returned ['text'],
    which silently flipped `test_compiler_emits_board_payload_on_bb_device` between pass
    and fail depending on what the model felt like drawing. That broke this module's
    stated "no Vertex" contract and made the suite's result a coin toss.

    These tests assert the COMPILER/RUNNER branch, not the author's taste, so stub the
    author out and let the deterministic scene translator run. The live author path has
    its own dedicated suite (test_board_buddy_author_live.py).
    """
    from . import board_buddy_author as author
    original = author.author_board_from_answer
    author.author_board_from_answer = lambda *a, **k: None
    try:
        yield
    finally:
        author.author_board_from_answer = original


# ---------------------------------------------------------------------------
# Belt: grounding
# ---------------------------------------------------------------------------
def test_ungrounded_count_is_dropped() -> None:
    ans = "Let's count seven apples on the board."
    kept, dropped = validate_board_call(
        [{"type": "stickers", "item": "apple", "count": 7, "pos": [100, 200]},
         {"type": "stickers", "item": "apple", "count": 9, "pos": [100, 400]}],
        ans, profile=PI)
    assert [e["type"] for e in kept] == ["stickers"]
    assert kept[0]["count"] == 7
    assert kept[0]["item"] == "apple"          # real key is `item`
    assert kept[0]["id"]                        # every element carries an id
    assert any("ungrounded-quantity" in d and "count=9" in d for d in dropped)


def test_number_words_ground_counts() -> None:
    # "seven" (word) grounds the digit 7 (scene_author._answer_number_set).
    kept, _ = validate_board_call(
        [{"type": "stickers", "item": "star", "count": 7, "pos": [10, 10]}],
        "There are seven stars.", profile=PI)
    assert kept and kept[0]["count"] == 7


def test_numberline_ungrounded_hop_dropped_but_window_kept() -> None:
    ans = "Start at seven and hop three to make ten."
    kept, _ = validate_board_call(
        [{"type": "numberline", "min": 0, "max": 12,
          "hops": [{"start": 7, "end": 10, "label": "+3"},
                   {"start": 1, "end": 99, "label": "bad"}]}],
        ans, profile=PI)
    assert len(kept) == 1
    assert kept[0]["min"] == 0 and kept[0]["max"] == 12   # window is structural, kept
    assert len(kept[0]["hops"]) == 1 and kept[0]["hops"][0]["end"] == 10   # 99-hop dropped


def test_numberline_accepts_start_end_aliases() -> None:
    # The model may emit start/end; the belt maps them to the real min/max + hop start/end.
    kept, _ = validate_board_call(
        [{"type": "numberline", "start": 0, "end": 10,
          "hops": [{"from": 7, "to": 10}]}],
        "start at seven hop to ten", profile=PI)
    assert kept and kept[0]["min"] == 0 and kept[0]["max"] == 10
    assert kept[0]["hops"][0] == {"start": 7.0, "end": 10.0}


def test_numberline_with_no_grounded_hop_is_dropped() -> None:
    kept, dropped = validate_board_call(
        [{"type": "numberline", "min": 0, "max": 10,
          "hops": [{"start": 1, "end": 99}]}],
        "add three and four", profile=PI)
    assert kept == []
    assert any("numberline-hops" in d for d in dropped)


def test_fraction_numerator_grounded() -> None:
    kept, _ = validate_board_call(
        [{"type": "fraction", "numerator": 3, "denominator": 10, "pos": [50, 50]}],
        "the fraction three over ten of the bar is shaded", profile=PI)
    assert kept and kept[0]["numerator"] == 3 and kept[0]["denominator"] == 10
    assert kept[0]["visual_type"] == "bar"      # default fraction style
    # and an ungrounded denominator drops it
    bad, dropped = validate_board_call(
        [{"type": "fraction", "numerator": 3, "denominator": 8, "pos": [50, 50]}],
        "the fraction three over ten", profile=PI)
    assert bad == [] and any("denominator=8" in d for d in dropped)


def test_graph_multidigit_coeff_ungrounded_is_dropped() -> None:
    # A structural single digit survives; a multi-digit coefficient the answer never
    # stated drops the element (scene_author._ground_lines rule for maths strings).
    ok, _ = validate_board_call(
        [{"type": "graph", "equation": "y = x^2 - 5*x + 6"}],
        "the parabola y equals x squared minus five x plus six", profile=PI)
    assert ok and ok[0]["type"] == "graph"
    bad, dropped = validate_board_call(
        [{"type": "graph", "equation": "y = 42*x^2"}],
        "the parabola opens upward", profile=PI)
    assert bad == [] and any("ungrounded-text" in d for d in dropped)


def test_text_keeps_structural_single_digits() -> None:
    # The quadratic formula's 2 and 4 must survive (they are structural, not stated).
    kept, _ = validate_board_call(
        [{"type": "text", "text": "x = (-b ± √(b²-4ac)) / 2a", "pos": [20, 20]}],
        "we use the quadratic formula to find the roots", profile=PI)
    assert kept and kept[0]["type"] == "text"


# ---------------------------------------------------------------------------
# Belt: capability
# ---------------------------------------------------------------------------
def test_unknown_tool_and_sticker_and_shape_dropped() -> None:
    _, dropped = validate_board_call(
        [{"type": "bogus"},
         {"type": "stickers", "item": "dragon", "count": 3, "pos": [0, 0]},
         {"type": "geometry", "shape": "hypercube", "pos": [0, 0]}],
        "three", profile=PI)
    assert any("unknown-tool" in d for d in dropped)
    assert any("unknown-sticker" in d for d in dropped)
    assert any("unknown-shape" in d for d in dropped)


def test_device_tool_subset_is_honoured() -> None:
    prof = dict(ESP32_P4_PROFILE.to_dict())
    prof["board_buddy_tools"] = ["text"]        # a device that ships only text
    kept, dropped = validate_board_call(
        [{"type": "text", "text": "hi", "pos": [10, 10]},
         {"type": "stickers", "item": "apple", "count": 3, "pos": [0, 0]}],
        "three apples say hi", profile=prof)
    assert [e["type"] for e in kept] == ["text"]
    assert any("tool-not-on-device:stickers" in d for d in dropped)


def test_position_is_clamped_or_laid_out() -> None:
    kept, _ = validate_board_call(
        [{"type": "text", "text": "a", "pos": [9999, -50]},   # out of bounds -> clamp
         {"type": "text", "text": "b"}],                       # missing pos -> laid out
        "hello world this is a board", profile=PI)
    for el in kept:
        x, y = el["pos"]
        assert caps.POS_X_MIN <= x <= caps.POS_X_MAX
        assert caps.POS_Y_MIN <= y <= caps.POS_Y_MAX


def test_element_budget_enforced() -> None:
    payload = [{"type": "text", "text": "hi", "pos": [10, 10 * i]}
               for i in range(MAX_ELEMENTS + 5)]
    kept, dropped = validate_board_call(payload, "hi", profile=PI)
    assert len(kept) <= MAX_ELEMENTS
    assert any("over-element-budget" in d for d in dropped)


def test_animation_flag() -> None:
    assert payload_has_animation(
        [{"type": "animate_param", "var": "n", "from": 1, "to": 5, "duration": 2}])
    assert not payload_has_animation([{"type": "text", "text": "x", "pos": [0, 0]}])


# ---------------------------------------------------------------------------
# Scene -> payload translator
# ---------------------------------------------------------------------------
def test_parabola_scene_translates_to_graph() -> None:
    scene = parabola_scene("quad", 1, -5, 6, "Roots")
    payload = scene_to_payload(scene)
    assert any(e["type"] == "graph" for e in payload)
    # tracer/point/axes are NOT translated on the fallback path (§4)
    graph = next(e for e in payload if e["type"] == "graph")
    assert "x^2" in graph["equation"] and "x_range" in graph


def test_text_scene_translates_to_text_stack() -> None:
    from .scene_author import layout_scene
    scene = layout_scene("c", "Formula", ["a + b", "= c"])
    payload = compile_scene_to_board(scene, answer="a plus b equals c", profile=PI)
    assert payload and all(e["type"] == "text" for e in payload)
    for el in payload:
        assert caps.POS_X_MIN <= el["pos"][0] <= caps.POS_X_MAX


# ---------------------------------------------------------------------------
# Orchestration loop
# ---------------------------------------------------------------------------
def test_loop_opens_once_closes_once() -> None:
    segs = [{"speech": "seven apples",
             "board_call": [{"type": "stickers", "item": "apple",
                             "count": 7, "pos": [100, 200]}]},
            {"speech": "add three", "board_call": [
                {"type": "stickers", "item": "apple", "count": 3, "pos": [100, 400]}]},
            {"done": True}]
    it = iter(segs)
    res = BoardSegmentOrchestrator("brief", profile=PI, decide=lambda s: next(it)).run()
    verbs = [v["cmd"] for v in res.verbs]
    assert verbs == ["board_open", "board", "speak", "board", "speak", "board_close"]
    assert res.stop_reason == "done"
    assert res.spoken_text == "seven apples add three"


def test_loop_grounds_each_board_call_against_spoken_text() -> None:
    # The board says 9 but the segment's speech says seven -> the element is dropped and
    # (nothing grounded) the board is never opened.
    segs = [{"speech": "we have seven apples",
             "board_call": [{"type": "stickers", "item": "apple",
                             "count": 9, "pos": [10, 10]}]},
            {"done": True}]
    it = iter(segs)
    res = BoardSegmentOrchestrator("brief", profile=PI, decide=lambda s: next(it)).run()
    assert not res.board_opened
    assert [v["cmd"] for v in res.verbs] == ["speak"]
    assert any("ungrounded-quantity" in d for s in res.segments for d in s.dropped)


def test_loop_respects_budgets() -> None:
    res = BoardSegmentOrchestrator(
        "brief", profile=PI, max_segments=3, board_budget=2,
        decide=lambda s: {"speech": "more",
                          "board_call": [{"type": "text", "text": "hi there",
                                          "pos": [10, 10]}]}).run()
    assert res.stop_reason == "budget"
    assert sum(1 for v in res.verbs if v["cmd"] == "board") == 2   # board budget capped
    assert len(res.segments) == 3                                   # segment budget capped


def test_loop_interrupt_tears_down() -> None:
    res = BoardSegmentOrchestrator(
        "brief", profile=PI, wait_ack=lambda e: {"interrupt": True},
        decide=lambda s: {"speech": "hi", "board_call": [
            {"type": "text", "text": "hello there", "pos": [10, 10]}]}).run()
    assert res.interrupted and res.stop_reason == "interrupt"
    assert res.verbs[-1]["cmd"] == "board_close"   # child torn down on interrupt


def test_tmax_hint_from_animation() -> None:
    assert _tmax_hint([{"type": "animate_param", "var": "n", "from": 1,
                        "to": 5, "duration": 3.5}]) == 3.5
    assert _tmax_hint([{"type": "text", "text": "x", "pos": [0, 0]}]) == 0.0


# ---------------------------------------------------------------------------
# Compiler + runner branches
# ---------------------------------------------------------------------------
def _board_script(profile: dict) -> TeachingScript:
    beat = Beat(
        beat_id="b0", pedagogical_step="explain",
        atomic_learning_claim="Roots are where the graph crosses the x-axis.",
        visual_intent=VisualIntent(VisualType.GENERATED_DECLARATIVE_SCENE_SPEC, True, "earned"))
    return TeachingScript(script_id="s1", turn_id="t1",
                          response_kind=ResponseKind.INSTRUCTIONAL,
                          device_profile=profile, beats=[beat], entry_beat_id="b0",
                          validation={"ok": True})


def test_compiler_emits_board_payload_on_bb_device() -> None:
    scene = parabola_scene("quad", 1, -5, 6, "Roots")
    with _deterministic_board():
        bundle = compile_response(
            _board_script(PI),
            answer="the parabola y equals x squared minus five x plus six",
            scene=scene, profile=PI)
    vis = bundle["beats"][0]["visual"]
    assert vis["kind"] == "board_buddy_payload"
    assert any(e["type"] == "graph" for e in vis["payload"])


def test_compiler_keeps_scene_spec_on_non_bb_device() -> None:
    prof = {"display_present": True, "renderer": "pillow_lvgl"}
    scene = parabola_scene("quad", 1, -5, 6, "Roots")
    bundle = compile_response(_board_script(prof), answer="y equals x squared",
                              scene=scene, profile=prof)
    assert bundle["beats"][0]["visual"]["kind"] == "scene_spec"


def test_runner_emits_board_lifecycle_verbs() -> None:
    scene = parabola_scene("quad", 1, -5, 6, "Roots")
    with _deterministic_board():
        bundle = compile_response(
            _board_script(PI),
            answer="the parabola y equals x squared minus five x plus six",
            scene=scene, profile=PI)
    runner = DeviceScriptRunner()
    armed = runner.arm(bundle)
    cmds = [c["cmd"] for c in armed]
    assert "board_open" in cmds and "board" in cmds
    runner.start()
    closing = runner.speech_completed()      # single beat -> completes -> closes board
    close_cmds = [c["cmd"] for c in closing]
    assert "board_close" in close_cmds
    assert close_cmds.index("board_close") < close_cmds.index("complete_script")


def test_numberline_animated_placeholder_hop_kept() -> None:
    # A "{hop:int}" placeholder hop is kept when an animate_param drives that var; the
    # numberline then rides an animation (Board Buddy grows the arc each frame).
    kept, dropped = validate_board_call(
        [{"type": "numberline", "min": 0, "max": 8, "hops": ["{hop:int}"]},
         {"type": "animate_param", "var": "hop", "from": 1, "to": 4, "duration": 3}],
        "The hop grows from 1 to 4 landing on 8.")
    types = [e["type"] for e in kept]
    assert "numberline" in types and "animate_param" in types
    nl = next(e for e in kept if e["type"] == "numberline")
    assert nl["hops"] == ["{hop:int}"]          # placeholder preserved for the device
    assert payload_has_animation(kept)


def test_numberline_placeholder_hop_without_animation_dropped() -> None:
    # A placeholder hop with no matching animate_param is meaningless -> numberline dropped.
    kept, dropped = validate_board_call(
        [{"type": "numberline", "min": 0, "max": 8, "hops": ["{hop:int}"]}],
        "The hop grows from 1 to 4.")
    assert kept == []
    assert any("numberline-hops" in d for d in dropped)


def test_bare_var_hop_is_normalized_to_placeholder() -> None:
    # Phase B: the model wrote the bare var "hop" (not "{hop:int}"); with a driving
    # animate_param the belt normalizes it so the arc still animates instead of dropping.
    kept, _ = validate_board_call(
        [{"type": "numberline", "min": 0, "max": 8, "hops": ["hop"]},
         {"type": "animate_param", "var": "hop", "from": 1, "to": 4, "duration": 3}],
        "The hop grows from 1 to 4 landing on 8.")
    nl = next(e for e in kept if e["type"] == "numberline")
    assert nl["hops"] == ["{hop:int}"]
    assert payload_has_animation(kept)


# ---------------------------------------------------------------------------
# Phase B: orchestrated multi-segment authoring (scripted decider, no Vertex)
# ---------------------------------------------------------------------------
def test_author_board_orchestrated_merges_grounded_segments() -> None:
    from .board_buddy_orchestrator import author_board_orchestrated
    answer = ("First we count seven apples, then three more, and on the graph the value a "
              "grows from 1 to 3 as the parabola opens.")
    segs = iter([
        {"speech": "count the apples",
         "board_call": [{"type": "stickers", "item": "apple", "count": 7, "pos": [40, 80]}]},
        {"speech": "now the parabola grows",
         "board_call": [{"type": "graph", "equation": "{a}*x^2", "title": "y={a}x^2"},
                        {"type": "animate_param", "var": "a", "from": 1, "to": 3,
                         "duration": 2.5}]},
        {"done": True},
    ])
    out = author_board_orchestrated(answer, profile=PI, decide=lambda s: next(segs))
    assert out is not None
    assert len(out["segments"]) == 2                       # two board-bearing segments
    assert out["animated"] is True and out["tmax"] == 2.5
    # merged carries the flattened board with fresh sequential ids for load_json
    ids = [e["id"] for e in out["merged"]]
    assert ids == [f"el{i}" for i in range(len(ids))]
    assert any(e["type"] == "graph" for e in out["merged"])
    assert any(e.get("item") == "apple" for e in out["merged"])


def test_author_board_orchestrated_none_when_ungrounded() -> None:
    from .board_buddy_orchestrator import author_board_orchestrated
    # The board says 9 apples but the answer says seven -> dropped -> no segments -> None.
    segs = iter([
        {"speech": "look",
         "board_call": [{"type": "stickers", "item": "apple", "count": 9, "pos": [10, 10]}]},
        {"done": True},
    ])
    out = author_board_orchestrated("We have seven apples on the table to count together.",
                                    profile=PI, decide=lambda s: next(segs))
    assert out is None


def test_text_sanitizer_cleans_display_strings() -> None:
    # Phase D live-render fixes: strip $$ delimiters, unwrap \text{}, map unicode minus,
    # drop literal '*'. Grounding runs BEFORE this, so it never changes what is grounded.
    kept, _ = validate_board_call(
        [{"type": "text", "text": "$$x = 2 \\text{ or } x = 3$$", "pos": [40, 40]}],
        "the roots are x = 2 or x = 3", profile=PI)
    assert kept and kept[0]["text"] == "x = 2 or x = 3"


def test_graph_gets_clean_default_title() -> None:
    # A graph with no title must NOT fall back to Board Buddy's mathmode "Graph of <equation>"
    # auto-title (fuses prose, shows literal '*'); the belt sets a clean equation title.
    kept, _ = validate_board_call(
        [{"type": "graph", "equation": "x^2 - 5*x + 6"}],
        "the parabola y equals x squared minus five x plus six", profile=PI)
    g = next(e for e in kept if e["type"] == "graph")
    assert g["equation"] == "x^2 - 5*x + 6"          # equation KEEPS '*' (BB parses it)
    assert g["title"].startswith("y =") and "*" not in g["title"]   # title is clean


def test_stickers_from_answer_grounds_object_and_count() -> None:
    # Real-life safety net (Phase E): the first "<n> <object>" becomes n grounded stickers.
    els = stickers_from_answer("You have 5 pencils and buy 3 more pencils.", PI)
    stk = next(e for e in els if e["type"] == "stickers")
    assert stk["item"] == "pencil" and stk["count"] == 5
    assert any(e["type"] == "text" and "5 pencils" in e["text"] for e in els)


def test_stickers_from_answer_maps_synonym_and_skips_non_objects() -> None:
    els = stickers_from_answer("arrange 4 marbles into a square", PI)   # marble -> ball
    assert els and els[1]["item"] == "ball" and els[1]["count"] == 4
    assert stickers_from_answer("the value a grows from 1 to 3", PI) == []   # no object
    assert stickers_from_answer("you have 40 tiles", PI) == []               # count out of range


def test_tree_element_validation() -> None:
    from .board_buddy_author import validate_board_call
    kept, dropped = validate_board_call(
        [{"type": "tree", "root": "6", "branches": [{"parent": "6", "children": ["2", "3"]}]}],
        "prime factorization of 6 is 2 times 3", profile=PI)
    assert kept and kept[0]["type"] == "tree"
    assert kept[0]["root"] == "6"
    assert kept[0]["branches"] == [{"parent": "6", "children": ["2", "3"]}]
    assert dropped == []


def test_sync_speech_with_visuals_strips_look_at_figure_when_text_only() -> None:
    from .board_buddy_author import sync_speech_with_visuals
    ans = "Look at the figure on the screen. To solve 6, we factorize it."
    # Text-only payload -> visual reference phrase stripped
    text_payload = [{"type": "text", "text": "Factorization"}]
    clean = sync_speech_with_visuals(ans, text_payload)
    assert "Look at the figure" not in clean
    assert "To solve 6, we factorize it." in clean

    # Payload with tree visual -> phrase preserved
    tree_payload = [{"type": "tree", "root": "6"}]
    synced = sync_speech_with_visuals(ans, tree_payload)
    assert "Look at the figure" in synced


def _run() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed} passed, {failed} failed ({len(tests)} total)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())
