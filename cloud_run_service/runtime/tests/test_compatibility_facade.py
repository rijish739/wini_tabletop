from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from interaction_control import InteractionDecision, InteractionDisposition
from runtime.contracts import ModuleOutcome
from runtime.compatibility import TutorLoopCompatibilityFacade
from runtime.supervisor import RuntimeHealth


class CompatibilityFacadeTests(unittest.TestCase):
    def test_learning_and_nonlearning_routes_cross_the_same_compatibility_facade(self) -> None:
        class RouteByText:
            def control(self, request):
                text = request.turn_input.interaction["text"]
                if text == "hello":
                    return ModuleOutcome(value=InteractionDecision(
                        disposition=InteractionDisposition.COMPLETE,
                        text=text,
                        compatibility={
                            "action": "SOCIAL",
                            "answer": "Hello!",
                            "display": [],
                            "session_ended": False,
                        },
                    ))
                return ModuleOutcome(value=InteractionDecision(
                    disposition=InteractionDisposition.CONTINUE_LEARNING,
                    text=text,
                    analysis={
                        "concept": {"concept_id": "fractions"},
                        "signals": [],
                        "state_deltas": {},
                    },
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
            interaction_control=RouteByText(),
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
        facade = TutorLoopCompatibilityFacade(
            legacy_turn=legacy_turn,
            commit_state=lambda: commits.append("committed"),
            state=state,
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
