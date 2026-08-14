from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from runtime.compatibility import TutorLoopCompatibilityFacade
from runtime.supervisor import RuntimeHealth


class CompatibilityFacadeTests(unittest.TestCase):
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

        self.assertIn("_turn_compatibility_facade().turn(", facade_body)
        self.assertNotIn("_front_gate(text)", facade_body)
        self.assertIn("_front_gate(text)", legacy_body)


if __name__ == "__main__":
    unittest.main()
