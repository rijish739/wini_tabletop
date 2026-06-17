"""Unit tests for the Cognitive Analyzer mapping + state application.

Stub-based (no model load):  python -m cognitive_analyzer.test_analyzer
With end-to-end model check: python -m cognitive_analyzer.test_analyzer --integration
"""

from __future__ import annotations

import sys

from learner_state import LearnerState

from .analyzer import (
    EMA,
    CognitiveAnalyzer,
    apply_deltas,
    derive_cognitive_update,
    derive_state_deltas,
)


class StubClassifier:
    def __init__(self, scores, signals):
        self._scores, self._signals = scores, signals

    def classify(self, text, top_evidence=0):
        return {"scores": self._scores, "signals": self._signals}


class StubResolver:
    def __init__(self, concept_id, abstained=False):
        self._cid, self._abst = concept_id, abstained

    def resolve(self, text, current_concept=None):
        return {
            "concept_id": current_concept if self._abst else self._cid,
            "concept_confidence": 0.9,
            "secondary_concepts": [],
            "abstained": self._abst,
            "resolution_reason": "stub",
        }


def test_mapping_formulas():
    up = derive_cognitive_update({"confusion": 0.8, "frustration": 0.6, "anxiety": 0.5})
    assert up["confusion"] == 0.8
    assert abs(up["cognitive_load"] - max(0.0, 0.5 * 0.8 + 0.3 * 0.6 + 0.2 * 0.5)) < 1e-9
    assert up["frustration_risk"] == 0.6
    assert up["confidence"] == 0.5 - 0.2 * 0.5  # anxiety drag only

    up = derive_cognitive_update({"cognitive_overload": 0.9, "confusion": 0.2})
    assert up["cognitive_load"] == 0.9  # stated overload dominates the blend

    up = derive_cognitive_update({"high_confidence": 0.8})
    assert up["confidence"] == 0.9
    up = derive_cognitive_update({"low_confidence": 1.0, "anxiety": 1.0})
    assert up["confidence"] == 0.0  # clamped

    up = derive_cognitive_update({"misconception_clue": 0.3, "recurring_error": 0.7})
    assert up["misconception_probability"] == 0.7

    up = derive_cognitive_update({"disengagement": 1.0})
    assert up["engagement"] == 0.0  # clamped from 0.5 - 0.6
    up = derive_cognitive_update({"curiosity": 1.0})
    assert up["engagement"] == 0.9


def test_flags():
    up = derive_cognitive_update({"misconception_clue": 0.8, "transfer_attempt": 0.6})
    deltas = derive_state_deltas(up, ["request_hint"], {"concept_id": "jemh102__x"})
    assert set(deltas["concept_flags"]) == {"misconception_suspected", "transfer_ready_evidence", "hint_requested"}
    # no concept resolved and nothing inherited -> no flags attached anywhere
    deltas = derive_state_deltas(up, [], {"concept_id": None, "abstained": True})
    assert deltas["concept_flags"] == []


def test_apply_deltas_ema_and_flags():
    state = LearnerState(path=None, data={})
    up = derive_cognitive_update({"confusion": 1.0, "curiosity": 1.0})
    deltas = derive_state_deltas(up, [], {"concept_id": "jemh102__x"})
    new = apply_deltas(state, deltas)
    # EMA from 0.5 default toward observed
    assert abs(new["curiosity"] - ((1 - EMA) * 0.5 + EMA * 1.0)) < 1e-6
    assert abs(new["cognitive_load"] - ((1 - EMA) * 0.5 + EMA * 0.5)) < 1e-6
    # repeated consistent evidence keeps moving the state
    for _ in range(5):
        apply_deltas(state, deltas)
    assert state.data["global"]["curiosity"] > 0.85
    # flags dedupe
    up2 = derive_cognitive_update({"misconception_clue": 0.9})
    d2 = derive_state_deltas(up2, [], {"concept_id": "jemh102__x"})
    apply_deltas(state, d2)
    apply_deltas(state, d2)
    assert state.concept_states["jemh102__x"]["flags"] == ["misconception_suspected"]


def test_analyzer_with_stubs():
    analyzer = CognitiveAnalyzer(
        classifier=StubClassifier({"confusion": 0.9, "graphical": 0.8}, ["confusion", "graphical"]),
        resolver=StubResolver("jemh102__quadratic_zero_geometry"),
    )
    out = analyzer.analyze("  this   graph   confuses me ??")
    assert out["normalized_text"] == "this graph confuses me??"
    assert out["cognitive_update"]["confusion"] == 0.9
    assert out["state_deltas"]["concept_id"] == "jemh102__quadratic_zero_geometry"

    # abstain path inherits the session concept
    analyzer = CognitiveAnalyzer(
        classifier=StubClassifier({"confusion": 0.9}, ["confusion"]),
        resolver=StubResolver(None, abstained=True),
    )
    out = analyzer.analyze("i dont get it", current_concept="jemh105__nth_term_formula")
    assert out["concept"]["concept_id"] == "jemh105__nth_term_formula"
    assert out["state_deltas"]["concept_id"] == "jemh105__nth_term_formula"


def integration():
    analyzer = CognitiveAnalyzer()
    state = LearnerState(path=None, data={})
    cases = [
        ("i dont understand why the parabola opens up, can you draw it", None),
        ("a quadratic always has two real roots na, that is the rule", None),
        ("this is too much for my head today", "jemh108__fundamental_trig_ratios"),
    ]
    for text, ctx in cases:
        out = analyzer.analyze_and_apply(text, state, current_concept=ctx)
        cu = out["cognitive_update"]
        print(f"\n> {text}")
        print(f"  concept: {out['concept']['concept_id']} (abstained={out['concept']['abstained']})")
        print(f"  signals: {out['signals'][:5]}")
        print("  update: " + ", ".join(f"{k}={v:.2f}" for k, v in cu.items() if v > 0.1))
        print(f"  flags: {out['state_deltas']['concept_flags']}  globals: {out['new_global_state']}")
    # sanity on the three turns
    assert state.data["global"]["cognitive_load"] > 0.5, "load should rise over these turns"


if __name__ == "__main__":
    failures = 0
    for fn in (test_mapping_formulas, test_flags, test_apply_deltas_ema_and_flags, test_analyzer_with_stubs):
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {fn.__name__}: {exc}")
    if "--integration" in sys.argv:
        integration()
        print("\nPASS integration")
    sys.exit(1 if failures else 0)
