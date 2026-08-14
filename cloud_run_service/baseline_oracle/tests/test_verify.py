from __future__ import annotations

import copy
import unittest

from baseline_oracle.reference import load_frozen_reference
from baseline_oracle.verify import diagnose_candidate_differences, verify_candidate


class CandidateVerificationTests(unittest.TestCase):
    def test_reports_case_and_path_for_candidate_drift(self) -> None:
        candidate = copy.deepcopy(list(load_frozen_reference()))
        candidate[0]["assessment_lifecycle"]["armed"] = "unexpected-item"

        report = diagnose_candidate_differences(candidate)

        self.assertEqual(report["failed_cases"], 1)
        self.assertEqual(
            report["findings"][0]["path"], "assessment_lifecycle.armed"
        )

    def test_refuses_equivalence_verdict_against_incomplete_reference(self) -> None:
        candidate = copy.deepcopy(list(load_frozen_reference()))

        report = verify_candidate(candidate, candidate_startup={"startup_ms": 10.0})

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["reason"], "canonical_reference_incomplete")
        self.assertEqual(report["performance"]["status"], "not_compared")


if __name__ == "__main__":
    unittest.main()
