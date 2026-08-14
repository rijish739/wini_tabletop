from __future__ import annotations

import unittest

from baseline_oracle.metrics import compare_performance, summarize_performance


class PerformanceTests(unittest.TestCase):
    def test_summarizes_each_required_latency_and_usage_measure(self) -> None:
        observations = [
            {"metrics": {"non_model_ms": value, "time_to_first_audio_ms": value + 10,
                         "total_ms": value + 20, "presentation_selection_ms": value / 10},
             "model_usage": {"model_calls": 2, "client_constructions": 0}}
            for value in range(1, 101)
        ]

        summary = summarize_performance(
            {"startup_ms": 250.0, "model_client_constructions": 2}, observations
        )

        self.assertEqual(summary["startup_ms"], 250.0)
        self.assertEqual(summary["non_model_p95_ms"], 95.0)
        self.assertEqual(summary["time_to_first_audio_p95_ms"], 105.0)
        self.assertEqual(summary["total_latency_p95_ms"], 115.0)
        self.assertEqual(summary["steady_state_model_calls_max"], 2)
        self.assertEqual(summary["model_client_constructions"], 2)
        self.assertEqual(summary["presentation_selection_p95_ms"], 9.5)

    def test_new_model_call_is_a_performance_failure(self) -> None:
        reference = {"non_model_p95_ms": 10.0, "steady_state_model_calls_max": 2,
                     "model_client_constructions": 2}
        candidate = {"non_model_p95_ms": 10.5, "steady_state_model_calls_max": 3,
                     "model_client_constructions": 2}

        failures = compare_performance(reference, candidate, non_model_tolerance=0.10)

        self.assertEqual(failures, ("steady_state_model_calls_max increased from 2 to 3",))


if __name__ == "__main__":
    unittest.main()
