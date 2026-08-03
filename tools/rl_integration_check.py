"""Response Layer integration check — real store/graph/scene data, NO cloud calls.

The unit tests (response_layer/test_response_layer.py) prove the gate/planner/validator
logic on synthetic contexts. This proves the SEAM: a real TutorLoop (real concept graph,
real rag_store/concept_figures.json, real WINIPI5 device profile) driven through
``TutorLoop._response_layer`` returns the right EARNED-visual decision + display for
representative turns — without needing Vertex (which the Pi's SA key cannot call; the live
brain runs on Cloud Run for exactly that reason).

Run on the Pi:
    .venv/bin/python -m tools.rl_integration_check
"""

from __future__ import annotations

import time
import types

import tutor_loop
from tutor_loop import TutorLoop


def _run():
    print("building TutorLoop (loads real store/graph/scene index; no cloud)...")
    loop = TutorLoop(want_answer=True)
    print("ready.\n")

    # _scene_for reads the REAL rag_store/concept_figures.json
    print("== _scene_for (real concept_figures.json) ==")
    for cid in ("jemh104__quadratic_formula", "jemh104__roots_of_quadratic_equation",
                "jemh101__fundamental_theorem_of_arithmetic"):
        print(f"  {cid} -> {loop._scene_for(cid)}")
    print()

    snap = types.SimpleNamespace(active_misconceptions=[])
    crop = {"image_path": "figure_crops/jemh106/fig_area.png", "alt_text": "triangle area"}

    # (label, action, concept_id, wants_visual, clarification, load, crop_items, expect)
    cases = [
        ("plain EXPLAIN of a derivation concept (scene exists)",
         "EXPLAIN", "jemh104__quadratic_formula", False, False, 0.1, [],
         "authored_scene / arm"),
        ("EXPLAIN of a definitional concept, no scene, no crop",
         "EXPLAIN", "jemh101__fundamental_theorem_of_arithmetic", False, False, 0.1, [],
         "none / suppress (speech-only)"),
        ("representation gap ('I can't picture it')",
         "REPRESENTATION_TRANSLATION", "jemh104__roots_of_quadratic_equation", True, True,
         0.2, [], "authored_scene / arm"),
        ("EXPLAIN with a retrieved crop present, no scene",
         "EXPLAIN", "jemh101__fundamental_theorem_of_arithmetic", False, False, 0.1, [crop],
         "retrieved_crop / show crop"),
        ("high cognitive load, decorative visual (scene exists)",
         "EXPLAIN", "jemh104__quadratic_formula", False, False, 0.85, [],
         "none / suppress (load)"),
        ("MISCONCEPTION_PROBE (probe beat, no answer-revealing visual)",
         "MISCONCEPTION_PROBE", "jemh104__quadratic_formula", False, False, 0.2, [],
         "none / suppress (probe)"),
    ]

    print("== _response_layer decisions (real data) ==")
    total_ms = 0.0
    for label, action, cid, wv, clar, load, crops, expect in cases:
        concept = {"concept_id": cid}
        evidence = [{"id": "chunk::demo", "type": "chunk",
                     "supports_representation": (["graph"] if "roots" in cid else [])}]
        analysis = {"cognitive_update": {"cognitive_load": load, "frustration_risk": 0.0}}
        t0 = time.perf_counter()
        display, figure_on_screen, directive = loop._response_layer(
            text="(probe)", action=action, need="explain", primary=cid, concept=concept,
            evidence=evidence, analysis=analysis, snapshot=snap, mode="EXPLAIN",
            wants_visual=wv, clarification=clar, intro=False, grounding="manifest_only",
            mode_cards=[], crop_items=crops)
        ms = (time.perf_counter() - t0) * 1000
        total_ms += ms
        print(f"\n[{label}]")
        print(f"  expect     : {expect}")
        print(f"  visual     : type={directive['type']} allowed={directive['allowed']} "
              f"arm_scene={directive['arm_scene']} asset={directive['asset']}")
        print(f"  reason     : {directive['reason']}")
        print(f"  display    : {len(display)} item(s); figure_on_screen={figure_on_screen}")
        print(f"  overhead   : {ms:.2f} ms  (deterministic — no model call)")

    print(f"\n== response-layer overhead: {total_ms / len(cases):.2f} ms/turn avg "
          f"(added BEFORE the unchanged streamed generation → TTFA preserved) ==")


if __name__ == "__main__":
    tutor_loop.RESPONSE_LAYER = True
    _run()
