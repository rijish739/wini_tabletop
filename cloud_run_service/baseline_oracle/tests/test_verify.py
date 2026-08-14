from __future__ import annotations

import copy
import unittest

from baseline_oracle.reference import load_frozen_reference
from baseline_oracle.verify import verify_candidate


class CandidateVerificationTests(unittest.TestCase):
    def test_reports_case_and_path_for_candidate_drift(self) -> None:
        candidate = copy.deepcopy(list(load_frozen_reference()))
        candidate[0]["assessment_lifecycle"]["armed"] = "unexpected-item"

        report = verify_candidate(candidate)

        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failed_cases"], 1)
        self.assertEqual(
            report["findings"][0]["path"], "assessment_lifecycle.armed"
        )


if __name__ == "__main__":
    unittest.main()
