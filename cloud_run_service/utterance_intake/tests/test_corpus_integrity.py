"""Corpus-integrity validator — a gate, not a document.

Runs in the free lane. It fails on a malformed fixture row so the coverage
corpora cannot silently rot. The expected-diff manifest mechanism is exercised
here as empty-but-live: the file must parse and every row (currently none) must
carry the closed manifest shape.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

FIXTURES = Path(__file__).with_name("fixtures")

_INTAKE_REQUIRED = {
    "normalized_text", "authorization", "safety_tripped", "illegible",
    "problem_is_problem", "parse_outcome", "has_anaphora",
}
_DIFF_REQUIRED = {"id", "function", "input_id", "before", "after", "reason", "ticket"}


def _rows(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for n, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:  # pragma: no cover - failure path
                raise AssertionError(f"{path.name}:{n} is not valid JSON: {exc}")
    return rows


class IntakeCorpusIntegrity(unittest.TestCase):
    def test_intake_observations_rows_are_well_formed(self) -> None:
        rows = _rows(FIXTURES / "intake_observations.jsonl")
        self.assertGreater(len(rows), 0)
        seen_ids: set[str] = set()
        for row in rows:
            self.assertIn("id", row)
            self.assertNotIn(row["id"], seen_ids, f"duplicate id {row['id']}")
            seen_ids.add(row["id"])
            self.assertIn("utterance", row)
            self.assertIn("text", row["utterance"])
            expected = row.get("expected") or {}
            missing = _INTAKE_REQUIRED - expected.keys()
            self.assertEqual(missing, set(), f"{row['id']} missing {missing}")


class ExpectedDiffManifestIsLive(unittest.TestCase):
    def test_manifest_parses_and_rows_are_closed_shape(self) -> None:
        path = FIXTURES / "expected_diffs.jsonl"
        self.assertTrue(path.exists(), "the expected-diff manifest file must exist")
        for row in _rows(path):
            missing = _DIFF_REQUIRED - row.keys()
            self.assertEqual(missing, set(), f"diff row missing {missing}")


if __name__ == "__main__":
    unittest.main()
