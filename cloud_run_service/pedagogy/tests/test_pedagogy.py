from __future__ import annotations

import unittest

from runtime.contracts import DeviceCapabilities, TurnBudgets, TurnInput

from pedagogy import (
    Pedagogy, PedagogyDependencies, PedagogyObservation, PedagogyRequest,
    PedagogyStateView,
)
from cognitive_classifier.cues import (
    is_clarification_request, is_learning_request, is_pure_ack,
    is_purpose_question, is_question, is_visualization_request,
    # Slice 07 (2026-08-28): session-mode cue functions — kept in cues.py for
    # offline tooling/tests. session_modes.mode_cues() is retired (always None);
    # in production, RouteResult.session_control_mode replaces it.
    is_stop_test_request, is_test_request, is_practice_request, is_explain_request,
)
from utterance_intake.observation import ProblemCue, ProblemReading


def _mode_cue_from_text(text: str):
    """Test-only helper: simulate Perception's session_control_mode from text.

    Replicates the logic of the retired session_modes.mode_cues() using the
    underlying cue functions from cognitive_classifier.cues (kept for offline
    tooling). Production code reads RouteResult.session_control_mode instead.
    """
    if is_stop_test_request(text):
        return "STOP"
    if is_test_request(text):
        return "TEST"
    if is_practice_request(text):
        return "PRACTICE"
    if is_explain_request(text):
        return "EXPLAIN"
    return None


def observation(
    *,
    text: str,
    signals=(),
    flags=(),
    cognitive=None,
    problem: ProblemReading | None = None,
) -> PedagogyObservation:
    update = {
        "confusion": 0.0,
        "curiosity": 0.0,
        "cognitive_load": 0.0,
        "frustration_risk": 0.0,
    }
    update.update(cognitive or {})
    return PedagogyObservation(
        normalized_text=text.lower(),
        concept_id="fractions",
        signals=tuple(signals),
        concept_flags=tuple(flags),
        cognitive_update=update,
        answer_attempt=False,
        perception_degraded=False,
        acknowledged=is_pure_ack(text),
        clarification_requested=is_clarification_request(text),
        visualization_requested=is_visualization_request(text),
        purpose_requested=is_purpose_question(text),
        learning_requested=is_learning_request(text),
        question=is_question(text),
        learner_problem=bool(problem and problem.is_directive_problem),
        requested_mode=_mode_cue_from_text(text),
    )


def request(text: str, observed: PedagogyObservation, **state) -> PedagogyRequest:
    return PedagogyRequest(
        turn_input=TurnInput(
            turn_id="turn-2",
            learner_id="learner-1",
            interaction={"text": text},
            device=DeviceCapabilities(),
            budgets=TurnBudgets(total_ms=10_000),
        ),
        observation=observed,
        state=PedagogyStateView(
            session=state.pop("session", {}),
            mastery=state.pop("mastery", 0.2),
            transfer_readiness=state.pop("transfer_readiness", 0.0),
            **state,
        ),
    )


class PedagogyInterfaceTests(unittest.TestCase):
    def test_teaching_priority_is_selected_from_validated_observation(self) -> None:
        cases = (
            ("explain fractions", observation(text="explain fractions"), {}, "EXPLAIN"),
            ("hint please", observation(text="hint please", flags=("hint_requested",)), {}, "ANALOGOUS_EXAMPLE"),
            ("I think denominators add", observation(text="I think denominators add", flags=("misconception_suspected",)), {}, "MISCONCEPTION_PROBE"),
            ("give me a harder one", observation(text="give me a harder one", signals=("ready_for_next",)), {"transfer_readiness": 0.9}, "TRANSFER_PROBLEM"),
            ("I don't understand", observation(text="I don't understand", cognitive={"confusion": 0.8}), {}, "EXPLAIN"),
            ("okay", observation(text="okay"), {}, "METACOGNITIVE_REFLECT"),
            ("solve 2x + 3 = 7", observation(text="solve 2x + 3 = 7", problem=ProblemReading(is_problem=True, directive=True, cue=ProblemCue.EQUATION)), {}, "SOLVE_STUDENT_PROBLEM"),
        )
        module = Pedagogy()

        for text, observed, state, expected in cases:
            with self.subTest(text=text):
                outcome = module.decide(request(text, observed, **state))
                self.assertTrue(outcome.valid)
                self.assertEqual(outcome.value.action, expected)

    def test_explicit_modes_and_stop_return_owned_state_changes(self) -> None:
        module = Pedagogy()
        for text, initial, expected in (
            ("let's practice", "EXPLAIN", "PRACTICE"),
            ("test me", "EXPLAIN", "TEST"),
            ("go back to explaining", "PRACTICE", "EXPLAIN"),
            ("stop the test", "TEST", "EXPLAIN"),
        ):
            with self.subTest(text=text):
                outcome = module.decide(request(
                    text, observation(text=text), session={"mode": initial}
                ))
                self.assertEqual(outcome.value.mode, expected)
                self.assertTrue(outcome.state_changes)
                self.assertTrue(all(c.owner == "pedagogy" for c in outcome.state_changes))

    def test_uncertain_perception_never_selects_an_assessment(self) -> None:
        observed = observation(text="test me")
        object.__setattr__(observed, "perception_degraded", True)

        outcome = Pedagogy().decide(request("test me", observed))

        self.assertFalse(outcome.value.assessment_appropriate)
        self.assertNotIn(outcome.value.action, {"TEST_QUESTION", "MISCONCEPTION_PROBE"})

    def test_pacing_is_part_of_the_typed_decision(self) -> None:
        outcome = Pedagogy().decide(request(
            "this is too much",
            observation(
                text="this is too much", cognitive={"cognitive_load": 0.9}
            ),
        ))

        self.assertEqual(outcome.value.pacing.max_words, 35)
        self.assertEqual(outcome.value.pacing.max_sentences, 2)

    def test_active_test_keeps_its_locked_concept_in_the_typed_plan(self) -> None:
        session = {
            "mode": "TEST",
            "test_state": {
                "concept_id": "algebra", "n": 5, "idx": 0,
                "schema_cycle": ["schema-a"] * 5,
                "items": [{"id": "old-item"}], "results": [],
                "phase": "serving",
            },
        }
        outcome = Pedagogy(dependencies=PedagogyDependencies(
            schema_ids=lambda concept_id: ["schema-a"]
        )).decide(request("6", observation(text="6"), session=session))

        self.assertEqual(outcome.value.plan["concept_id"], "algebra")
        self.assertEqual(outcome.value.plan["item_history"], ({"id": "old-item"},))

    def test_acknowledgement_creates_and_acceptance_consumes_practice_offer(self) -> None:
        module = Pedagogy(offers_enabled=True)
        offered = module.decide(request(
            "okay",
            observation(text="okay"),
            session={"mode": "EXPLAIN", "current_concept": "fractions",
                     "last_action": "EXPLAIN"},
        ))
        projected = {"mode": "EXPLAIN", "current_concept": "fractions",
                     "last_action": "EXPLAIN"}
        for change in offered.state_changes:
            if change.operation.value == "set":
                projected[change.path[0]] = change.value

        self.assertEqual(offered.value.plan["offer"], "Want to try a few problems together?")
        self.assertEqual(projected["pending_mode_offer"]["mode"], "PRACTICE")

        accepted = module.decide(request(
            "yes", observation(text="yes"), session=projected
        ))

        self.assertEqual(accepted.value.mode, "PRACTICE")
        self.assertNotIn("pending_mode_offer", {
            change.path[0]: change.value for change in accepted.state_changes
            if change.operation.value == "set"
        })


if __name__ == "__main__":
    unittest.main()
