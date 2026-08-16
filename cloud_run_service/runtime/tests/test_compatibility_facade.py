from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from interaction_control import (
    CapabilityTransition,
    InteractionControl,
    InteractionControlDependencies,
    InteractionDecision,
    InteractionDisposition,
)
from runtime.contracts import ModuleOutcome
from runtime.compatibility import TutorLoopCompatibilityFacade
from runtime.supervisor import RuntimeHealth
from perception import Perception, PerceptionTransportError
from perception.route import RouteResult


class CompatibilityFacadeTests(unittest.TestCase):
    def test_perception_scenarios_cross_the_compatibility_facade(self) -> None:
        class Engine:
            def observe(self, text, session, current_concept):
                if text == "backend down":
                    raise PerceptionTransportError("backend_unavailable")
                return RouteResult(primary="LEARNING"), {
                    "normalized_text": text, "signals": [], "signal_scores": {},
                    "concept": {
                        "concept_id": current_concept, "concept_confidence": 0.0,
                        "secondary_concepts": [], "abstained": True,
                    },
                    "cognitive_update": {},
                    "state_deltas": {"global": {}, "concept_id": current_concept,
                                     "concept_flags": [], "signals": []},
                }

        class Control:
            def control(self, request):
                observation = request.perception
                if observation.intent != "LEARNING":
                    return ModuleOutcome(value=InteractionDecision(
                        disposition=InteractionDisposition.COMPLETE,
                        text=request.turn_input.interaction["text"],
                        compatibility={"action": observation.intent, "answer": "safe",
                                       "display": [], "session_ended": False},
                    ))
                return ModuleOutcome(value=InteractionDecision(
                    disposition=InteractionDisposition.CONTINUE_LEARNING,
                    text=request.turn_input.interaction["text"],
                    analysis=observation.analysis,
                    perception_uncertain=observation.uncertain,
                ))

        received = []
        state = SimpleNamespace(
            data={"learner_id": "learner-1", "session": {"current_concept": "fractions"}}
        )
        facade = TutorLoopCompatibilityFacade(
            legacy_turn=lambda text, **kwargs: received.append(kwargs) or {
                "action": "EXPLAIN", "answer": "learning", "display": []
            },
            commit_state=lambda: None,
            state=state,
            interaction_control=Control(),
            perception=Perception(Engine()),
        )

        self.assertEqual(facade.turn("I want to kill myself")["action"], "SAFETY")
        self.assertEqual(facade.turn("!!!!!!")["action"], "NONSENSE")
        self.assertEqual(facade.turn("explain that")["action"], "EXPLAIN")
        self.assertEqual(received[-1]["precomputed_analysis"]["concept"]["concept_id"], "fractions")
        self.assertEqual(facade.turn("backend down")["action"], "EXPLAIN")
        self.assertTrue(received[-1]["_perception_uncertain"])
        self.assertEqual(received[-1]["precomputed_analysis"]["signals"], [])

    def test_learning_and_nonlearning_routes_cross_the_same_compatibility_facade(self) -> None:
        def route(text, session):
            return SimpleNamespace(
                primary="SOCIAL" if text == "hello" else "LEARNING",
                reason="fixture route",
                source="fixture",
                concept_id=None,
                concept_confidence=0.0,
                safety_alert=False,
                uncertain=False,
                answer_attempt=False,
            )

        no_transition = lambda *args: CapabilityTransition()
        control = InteractionControl(InteractionControlDependencies(
            deterministic_route=lambda text: None,
            perception_route=route,
            analyze=lambda text, current: {
                "normalized_text": text,
                "concept": {
                    "concept_id": "fractions",
                    "concept_confidence": 1.0,
                    "abstained": False,
                },
                "signals": [],
                "state_deltas": {},
            },
            persona={
                "identity": "Wini",
                "style": "Warm",
                "intents": {"SOCIAL": {"canned": ["Hello!"]}},
            },
            want_answer=False,
            generation_backend="fixture",
            generate_persona=lambda prompt: "",
            concept_name=lambda concept_id: "Fractions",
            topic_candidates=lambda text, limit: [],
            chapter_for_concept=lambda concept_id: None,
            extract_topic_request=lambda text: None,
            is_bare_topic=lambda text: False,
            wants_different_topic=lambda text: False,
            concept_relates_to_topic=lambda new, old: False,
            mode_cue=lambda text: None,
            current_mode=lambda session: "EXPLAIN",
            set_mode=no_transition,
            consume_mode_offer=no_transition,
            consume_test_resume=no_transition,
            check_frozen_test=no_transition,
            clear_pending_assessment=no_transition,
            log_event=lambda event: None,
            notify_safety=lambda record: None,
            now=lambda: "2026-08-14T12:00:00",
        ))

        learning_calls = []

        def legacy_learning(text, **kwargs):
            learning_calls.append((text, kwargs))
            return {
                "action": "EXPLAIN",
                "answer": "One half.",
                "display": [],
                "session_ended": False,
            }

        state = SimpleNamespace(data={"learner_id": "learner-1", "session": {}})
        facade = TutorLoopCompatibilityFacade(
            legacy_turn=legacy_learning,
            commit_state=lambda: None,
            state=state,
            interaction_control=control,
        )

        social = facade.turn("hello", turn_id="turn-social", learner_id="learner-1")
        learning = facade.turn(
            "teach me fractions", turn_id="turn-learning", learner_id="learner-1"
        )

        self.assertEqual(social["action"], "SOCIAL")
        self.assertEqual(learning["action"], "EXPLAIN")
        self.assertEqual(len(learning_calls), 1)
        self.assertEqual(learning_calls[0][0], "teach me fractions")
        self.assertTrue(learning_calls[0][1]["_interaction_controlled"])
        self.assertEqual(
            state.data["session"]["context"],
            [
                {"role": "student", "text": "hello"},
                {"role": "wini", "text": "Hello!"},
                {"role": "student", "text": "teach me fractions"},
                {"role": "wini", "text": "One half."},
            ],
        )

    def test_tutor_loop_turn_routes_through_coordinator_and_preserves_dictionary(self) -> None:
        state = SimpleNamespace(
            data={"learner_id": "learner-1", "session": {"mode": "EXPLAIN"}}
        )
        expected = {
            "answer": "One half.",
            "display": [{"kind": "text", "lines": ["1/2"]}],
            "signals": ["steady"],
        }
        received = {}

        def legacy_turn(text, **kwargs):
            received["text"] = text
            received.update(kwargs)
            return expected

        commits = []
        class LearningControl:
            def control(self, request):
                return ModuleOutcome(value=InteractionDecision(
                    disposition=InteractionDisposition.CONTINUE_LEARNING,
                    text=request.turn_input.interaction["text"],
                    analysis=request.turn_input.trusted_observations[
                        "precomputed_analysis"
                    ],
                ))

        facade = TutorLoopCompatibilityFacade(
            legacy_turn=legacy_turn,
            commit_state=lambda: commits.append("committed"),
            state=state,
            interaction_control=LearningControl(),
        )

        actual = facade.turn(
            "What is one half?",
            answer_budget={"max_words": 20},
            precomputed_analysis={"signals": ["steady"]},
            precomputed_grade="correct",
            stt_confidence=0.98,
            turn_id="turn-1",
            learner_id="learner-1",
        )

        self.assertEqual(actual, expected)
        self.assertIsInstance(actual["display"], list)
        self.assertIsInstance(actual["display"][0]["lines"], list)
        self.assertEqual(received["text"], "What is one half?")
        self.assertEqual(received["answer_budget"], {"max_words": 20})
        self.assertEqual(received["precomputed_analysis"], {"signals": ["steady"]})
        self.assertEqual(received["precomputed_grade"], "correct")
        self.assertEqual(commits, ["committed"])
        self.assertEqual(facade.runtime_health.health, RuntimeHealth.READY)

    def test_canonical_tutor_loop_entrypoint_is_only_a_compatibility_facade(self) -> None:
        source = (Path(__file__).parents[2] / "tutor_loop.py").read_text(encoding="utf-8")
        facade_start = source.index("    def turn(")
        legacy_start = source.index("    def _legacy_turn(")
        facade_body = source[facade_start:legacy_start]
        legacy_body = source[legacy_start:source.index("    @staticmethod\n    def _test_echo")]
        adapter_source = (
            Path(__file__).parents[1] / "legacy_adapter.py"
        ).read_text(encoding="utf-8")

        self.assertIn("_turn_compatibility_facade().turn(", facade_body)
        self.assertNotIn("_front_gate(text)", facade_body)
        self.assertIn("_interaction_controlled", legacy_body)
        self.assertNotIn("_handle_nonlearning", adapter_source)
        self.assertNotIn("_maybe_topic_shift", adapter_source)
        self.assertNotIn("_maybe_stop_mode", adapter_source)


if __name__ == "__main__":
    unittest.main()
