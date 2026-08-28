"""The shared golden-fixture conformance suite. Any observe() must pass it."""

from __future__ import annotations

import unittest

from utterance_intake.tests.harness import (
    build_utterance,
    check_expected,
    load_rows,
    run_observe,
    stub_observation,
)


class ConformanceTests(unittest.TestCase):
    def test_every_fixture_row_conforms(self) -> None:
        rows = load_rows("intake_observations.jsonl")
        self.assertGreater(len(rows), 0)
        for row in rows:
            with self.subTest(id=row["id"]):
                observation = run_observe(build_utterance(row["utterance"]))
                fails = check_expected(observation, row["expected"])
                self.assertEqual(fails, [], f"{row['id']}: {fails}")

    def test_observe_is_deterministic(self) -> None:
        utterance = build_utterance({"text": "x² = 3", "source": "TYPED"})
        first = run_observe(utterance)
        second = run_observe(utterance)
        self.assertEqual(first.normalized_text, second.normalized_text)
        self.assertEqual(first.authorization, second.authorization)

    def test_stub_observation_builds_a_valid_shape(self) -> None:
        obs = stub_observation(text="5")
        self.assertEqual(obs.normalized_text, "5")
        self.assertFalse(obs.safety.tripped)
        self.assertFalse(obs.legibility.illegible)


if __name__ == "__main__":
    unittest.main()
