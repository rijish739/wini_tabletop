from __future__ import annotations

import unittest

from perception import (
    Perception,
    PerceptionRequest,
    PerceptionTransportError,
)
from perception.route import RouteResult
from runtime.contracts import DeviceCapabilities, TurnBudgets, TurnInput


def turn(text: str, *, precomputed_analysis=None) -> TurnInput:
    return TurnInput(
        turn_id="turn-1",
        learner_id="learner-1",
        interaction={"text": text},
        device=DeviceCapabilities(),
        budgets=TurnBudgets(total_ms=10_000),
        trusted_observations={"precomputed_analysis": precomputed_analysis},
    )


class Gateway:
    def __init__(self, route=None, analysis=None, error=None):
        self.route = route
        self.analysis = analysis
        self.error = error
        self.calls = []

    def observe(self, text, session, current_concept):
        self.calls.append((text, session, current_concept))
        if self.error:
            raise self.error
        return self.route, self.analysis


def learning_analysis(concept_id="fractions"):
    return {
        "raw_text": "teach fractions",
        "normalized_text": "teach fractions",
        "problem_cue": {},
        "signals": ["curiosity"],
        "signal_scores": {"curiosity": 0.8},
        "concept": {
            "concept_id": concept_id,
            "concept_confidence": 0.9,
            "secondary_concepts": [],
            "abstained": False,
            "resolution_reason": "fixture",
        },
        "cognitive_update": {"curiosity": 0.8},
        "state_deltas": {
            "global": {"curiosity": 0.8},
            "concept_id": concept_id,
            "concept_flags": [],
            "signals": ["curiosity"],
        },
    }


class PerceptionInterfaceTests(unittest.TestCase):
    def test_safety_gate_precedes_the_model_gateway(self):
        gateway = Gateway()
        outcome = Perception(gateway).perceive(PerceptionRequest(
            turn_input=turn("I want to kill myself"), session={}
        ))

        self.assertEqual(outcome.value.intent, "SAFETY")
        self.assertTrue(outcome.value.safety_alert)
        self.assertEqual(outcome.value.source, "gate")
        self.assertEqual(gateway.calls, [])

    def test_nonsense_gate_precedes_the_model_gateway(self):
        gateway = Gateway()
        outcome = Perception(gateway).perceive(PerceptionRequest(
            turn_input=turn("!!!!!!"), session={}
        ))

        self.assertEqual(outcome.value.intent, "NONSENSE")
        self.assertEqual(gateway.calls, [])

    def test_validates_learning_observations_and_exposes_soft_changes(self):
        analysis = learning_analysis()
        gateway = Gateway(
            route=RouteResult(primary="LEARNING", answer_attempt=True),
            analysis=analysis,
        )
        outcome = Perception(gateway).perceive(PerceptionRequest(
            turn_input=turn("teach fractions"),
            session={"current_concept": "decimals"},
        ))

        self.assertEqual(outcome.value.intent, "LEARNING")
        self.assertEqual(outcome.value.concept_id, "fractions")
        self.assertEqual(outcome.value.signals, ("curiosity",))
        self.assertTrue(outcome.value.answer_attempt)
        self.assertEqual(outcome.value.analysis["state_deltas"]["global"], {"curiosity": 0.8})
        self.assertEqual(outcome.state_changes, ())

    def test_inherits_current_concept_when_the_model_abstains(self):
        analysis = learning_analysis(None)
        analysis["concept"]["abstained"] = True
        gateway = Gateway(
            route=RouteResult(primary="LEARNING", uncertain=False), analysis=analysis
        )
        outcome = Perception(gateway).perceive(PerceptionRequest(
            turn_input=turn("can you explain that"),
            session={"current_concept": "fractions"},
        ))

        self.assertEqual(outcome.value.concept_id, "fractions")
        self.assertTrue(outcome.value.analysis["concept"]["abstained"])

    def test_backend_timeout_returns_neutral_valid_degraded_observation(self):
        gateway = Gateway(error=PerceptionTransportError("timeout", "deadline"))
        outcome = Perception(gateway).perceive(PerceptionRequest(
            turn_input=turn("please explain that"),
            session={"current_concept": "fractions"},
        ))

        self.assertTrue(outcome.valid)
        self.assertEqual(outcome.value.intent, "LEARNING")
        self.assertEqual(outcome.value.concept_id, "fractions")
        self.assertEqual(outcome.value.signals, ())
        self.assertTrue(outcome.value.uncertain)
        self.assertEqual(outcome.value.analysis["normalized_text"], "please explain that")
        self.assertEqual(outcome.failures[0].cause, "timeout")
        self.assertTrue(outcome.failures[0].valid_outcome)

    def test_invalid_schema_is_a_typed_failure_with_the_same_degraded_outcome(self):
        gateway = Gateway(route=RouteResult(primary="NOT_AN_INTENT"), analysis={})
        outcome = Perception(gateway).perceive(PerceptionRequest(
            turn_input=turn("please explain that"), session={}
        ))

        self.assertTrue(outcome.valid)
        self.assertEqual(outcome.failures[0].cause, "invalid_schema")
        self.assertEqual(outcome.value.signals, ())


if __name__ == "__main__":
    unittest.main()
