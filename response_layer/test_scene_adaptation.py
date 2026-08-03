"""Phase 2.5 tests: authored scenes have one explicit narration authority."""
from __future__ import annotations
import json
from pathlib import Path
from .scene_author import layout_scene
from .scene_adaptation import (
    NARRATION_AS_AUTHORED,
    NARRATION_SCRIPT_OVERRIDE,
    NARRATION_VISUAL_ONLY,
    review_authored_scenes,
    review_scene,
    scene_for_narration_mode,
)

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "rag_store" / "figure_specs" / "jemh104__quadratic_formula.scene.json"

def test_all_authored_scenes_review_clean() -> None:
    reviews = review_authored_scenes()
    assert len(reviews) == 8
    assert all(review.ok for review in reviews.values())

def test_live_modes_never_reuse_authored_narration() -> None:
    scene = json.loads(SPEC.read_text(encoding="utf-8"))
    authored = [beat.get("narration", "") for beat in scene["beats"]]
    assert any(authored)
    as_authored = scene_for_narration_mode(scene, NARRATION_AS_AUTHORED)
    assert [beat["narration"] for beat in as_authored["beats"]] == authored
    visual_only = scene_for_narration_mode(scene, NARRATION_VISUAL_ONLY)
    assert all(not beat["narration"] for beat in visual_only["beats"])
    overridden = scene_for_narration_mode(
        scene, NARRATION_SCRIPT_OVERRIDE, {"0": "Script owns this first claim."})
    assert overridden["beats"][0]["narration"] == "Script owns this first claim."
    assert all(not beat["narration"] for beat in overridden["beats"][1:])

def test_missing_contract_fails_closed() -> None:
    review = review_scene({"beats": [{"narration": "unsafe old narration"}]})
    assert not review.ok
    assert "missing adaptation_contract" in review.issues

def test_generated_scene_is_adaptation_contract_compliant() -> None:
    scene = layout_scene("jemh104__quadratic_formula", "Formula", ["x = 1", "x = 3"])
    review = review_scene(scene)
    assert review.ok
    live = scene_for_narration_mode(scene, NARRATION_SCRIPT_OVERRIDE)
    assert all(not beat["narration"] for beat in live["beats"])

def _run() -> int:
    tests = [test_all_authored_scenes_review_clean,
             test_live_modes_never_reuse_authored_narration,
             test_missing_contract_fails_closed,
             test_generated_scene_is_adaptation_contract_compliant]
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

