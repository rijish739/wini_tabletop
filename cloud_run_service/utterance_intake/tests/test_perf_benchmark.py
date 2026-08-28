"""Microbenchmark for Earley maths parser to guard against algorithmic blowup (Slice 06)."""

from __future__ import annotations

import json
import os
import time
import unittest

from utterance_intake.grammar import parse_maths

CORPUS = [
    "42",
    "three squared",
    "three cube",
    "one over x plus two",
    "x = 2 and x = 3",
    "−4",
    "½",
    "root two",
    "2y = 10",
    "one third",
    "two thirds",
    "2 to the power 5",
    "plus or minus 5",
    "I do not know",
    "what is 63 / 9",
    "solve x^2 - 5x + 6 = 0",
    "twenty five",
    "3.14",
    "x is equal to 12",
    "a / (b + c)",
]


@unittest.skipUnless(os.getenv("CI"), "perf microbenchmark runs in CI only (baseline reflects CI Linux latencies)")
class MathsParserPerfMicrobenchmark(unittest.TestCase):
    """Guards that Earley parsing latency stays well within baseline bounds."""

    def test_p95_within_three_times_baseline(self):
        # Warmup
        for text in CORPUS:
            parse_maths(text)

        durations_ms = []
        # Run 5 repetitions across corpus (100 runs total)
        for _ in range(5):
            for text in CORPUS:
                t0 = time.perf_counter()
                parse_maths(text)
                durations_ms.append((time.perf_counter() - t0) * 1000.0)

        durations_ms.sort()
        n = len(durations_ms)
        p50 = durations_ms[int(n * 0.50)]
        p95 = durations_ms[int(n * 0.95)]

        # Load committed baseline
        baseline_file = os.path.join(os.path.dirname(__file__), "fixtures", "intake_perf_baseline.json")
        with open(baseline_file, "r", encoding="utf-8") as f:
            baseline = json.load(f)

        max_allowed_p95 = baseline.get("p95_ms", 5.0) * 3.0
        print(f"\nMaths Parser Perf Benchmark: p50={p50:.2f}ms, p95={p95:.2f}ms (Baseline p95: {baseline.get('p95_ms')}ms, Threshold: {max_allowed_p95:.2f}ms)")
        self.assertLess(p95, max_allowed_p95, f"p95 latency {p95:.2f}ms exceeded 3x baseline threshold {max_allowed_p95:.2f}ms")


if __name__ == "__main__":
    unittest.main()
