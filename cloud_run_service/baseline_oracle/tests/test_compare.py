from __future__ import annotations

import unittest

from baseline_oracle.compare import compare_observations


class ObservationComparisonTests(unittest.TestCase):
    def test_wording_normalization_does_not_hide_numbers_or_state_changes(self) -> None:
        reference = {
            "result": {"answer": "  A quadratic has 2 roots.  ", "action": "EXPLAIN"},
            "state_after": {"concept_states": {"quadratics": {"mastery": 0.4}}},
        }
        candidate = {
            "result": {"answer": "A quadratic has 3 roots.", "action": "EXPLAIN"},
            "state_after": {"concept_states": {"quadratics": {"mastery": 0.5}}},
        }

        report = compare_observations(reference, candidate)

        self.assertFalse(report.equivalent)
        self.assertEqual(
            {difference.path for difference in report.differences},
            {"result.answer", "state_after.concept_states.quadratics.mastery"},
        )

    def test_path_scoped_wording_normalization_accepts_formatting_only(self) -> None:
        reference = {
            "result": {"answer": "Let’s   factor it.\n", "action": "EXPLAIN"},
            "compatibility": {"answer": "Let’s   factor it.\n"},
        }
        candidate = {
            "result": {"answer": "Let's factor it.", "action": "EXPLAIN"},
            "compatibility": {"answer": "Let's factor it."},
        }

        report = compare_observations(reference, candidate)

        self.assertTrue(report.equivalent, report.differences)


if __name__ == "__main__":
    unittest.main()
