from __future__ import annotations

import unittest

from baseline_oracle.corpus import (
    REQUIRED_BEHAVIOR_TAGS,
    REQUIRED_STATE_KINDS,
    CorpusValidationError,
    FrozenCorpus,
    load_default_corpus,
)


class FrozenCorpusTests(unittest.TestCase):
    def test_incomplete_behavior_coverage_is_rejected(self) -> None:
        corpus = FrozenCorpus.from_data(
            states={"cold_start": {"learner_id": "fixture-learner", "session": {}}},
            cases=[{
                "id": "only-learning",
                "state": "cold_start",
                "turn_input": {"text": "Explain quadratics"},
                "tags": ["learning"],
            }],
            recordings=[],
        )

        with self.assertRaisesRegex(CorpusValidationError, "missing behavior coverage"):
            corpus.validate()

    def test_default_corpus_has_sanitized_state_and_behavior_coverage(self) -> None:
        corpus = load_default_corpus()

        corpus.validate()

        self.assertTrue(REQUIRED_STATE_KINDS.issubset(corpus.state_kinds))
        self.assertGreaterEqual(len(corpus.cases), 20)
        serialized = str(corpus.states).lower()
        self.assertNotIn("@", serialized)
        self.assertNotIn("api_key", serialized)
        self.assertNotIn("access_token", serialized)

    def test_unredacted_or_incomplete_model_recording_is_rejected(self) -> None:
        corpus = FrozenCorpus.from_data(
            states={"cold_start": {"learner_id": "fixture-learner", "session": {}}},
            cases=[{
                "id": "all-coverage",
                "state": "cold_start",
                "turn_input": {"text": "fixture"},
                "tags": sorted(REQUIRED_BEHAVIOR_TAGS),
            }],
            recordings=[{
                "case_id": "all-coverage",
                "boundary": "generation",
                "call_index": 0,
                "request": {"authorization": "secret"},
                "response": "fixture",
            }],
        )

        with self.assertRaisesRegex(CorpusValidationError, "model recording"):
            corpus.validate()


if __name__ == "__main__":
    unittest.main()
