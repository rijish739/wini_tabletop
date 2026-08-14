from __future__ import annotations

import unittest

from baseline_oracle.reference import REQUIRED_OBSERVATION_FIELDS, verify_frozen_reference


class FrozenReferenceTests(unittest.TestCase):
    def test_frozen_reference_is_complete_and_self_equivalent(self) -> None:
        report = verify_frozen_reference()

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["cases"], 27)
        self.assertEqual(report["differences"], 0)
        self.assertEqual(set(report["observation_fields"]), REQUIRED_OBSERVATION_FIELDS)
        self.assertEqual(report["capture_limitations"], [
            "canonical_runtime_missing_policy_logreg.npz",
            "canonical_runtime_missing_signal_heads.npz",
            "canonical_runtime_missing_local_chunk_index",
        ])


if __name__ == "__main__":
    unittest.main()
