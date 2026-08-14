from __future__ import annotations

import unittest

from baseline_oracle.reference import (
    REQUIRED_OBSERVATION_FIELDS,
    load_frozen_reference,
    verify_frozen_reference,
)


class FrozenReferenceTests(unittest.TestCase):
    def test_frozen_reference_is_complete_and_self_equivalent(self) -> None:
        report = verify_frozen_reference()

        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["self_check_status"], "pass")
        self.assertEqual(report["cases"], 27)
        self.assertEqual(report["differences"], 0)
        self.assertEqual(set(report["observation_fields"]), REQUIRED_OBSERVATION_FIELDS)
        self.assertEqual(report["capture_limitations"], [
            "canonical_runtime_missing_policy_logreg.npz",
            "canonical_runtime_missing_signal_heads.npz",
            "canonical_runtime_missing_local_chunk_index",
            "model_boundary_replay_incomplete",
        ])
        first = load_frozen_reference()[0]
        self.assertTrue({"shadow", "hope_update", "layer_latency_ms", "answer_budget",
                         "pace", "mode_reason"}.issubset(first["result"]))
        self.assertTrue({"turn_id", "transcript", "test", "diagnostics",
                         "latency_ms"}.issubset(first["compatibility"]))
        self.assertEqual(report["model_replay_coverage"]["expected_calls"], 32)
        self.assertEqual(report["model_replay_coverage"]["recorded_calls"], 7)
        self.assertIn("commit-failure", report["model_replay_coverage"]["incomplete_cases"])


if __name__ == "__main__":
    unittest.main()
