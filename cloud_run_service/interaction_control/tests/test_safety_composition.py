"""Legacy-20 safety regression, written against the composition helper from day one.

The test calls the shared union entry point (`compose_safety_alert`) — whose body
is the LEXICON reading union perception's bit today, and gains the model verdict
at the `child_safety` cutover. **This file is never edited at cutover; the thing
under it changes.** It also exercises the composition seam months before it
matters, which is where composition bugs are cheap.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from interaction_control import compose_safety_alert
from utterance_intake.intake import _lexicon_safety, normalize_text

# eval/perception_eval_safety.jsonl at the repo root — the adopted permanent
# regression suite (never the recall measurement).
_CORPUS = Path(__file__).resolve().parents[3] / "eval" / "perception_eval_safety.jsonl"


def _rows() -> list[dict]:
    rows = []
    with _CORPUS.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


class LegacyTwentyRegression(unittest.TestCase):
    def test_corpus_is_the_expected_twenty(self) -> None:
        self.assertEqual(len(_rows()), 20)

    def test_every_legacy_row_composes_to_an_alert(self) -> None:
        for row in _rows():
            text = row["utterance"]
            with self.subTest(text=text):
                lexicon = _lexicon_safety(normalize_text(text))
                alert = compose_safety_alert(
                    lexicon=lexicon, perception_safety_alert=False
                )
                self.assertTrue(alert, f"legacy safety row no longer trips: {text!r}")

    def test_composition_is_union_only_perception_bit_alone_suffices(self) -> None:
        # No lexicon match, but perception's bit is set -> still an alert.
        self.assertTrue(
            compose_safety_alert(lexicon=None, perception_safety_alert=True)
        )

    def test_composition_never_subtracts_a_lexicon_finding(self) -> None:
        lexicon = _lexicon_safety("i want to kill myself")
        self.assertTrue(lexicon.tripped)
        # perception says nothing; the lexicon finding survives composition.
        self.assertTrue(
            compose_safety_alert(lexicon=lexicon, perception_safety_alert=False)
        )


if __name__ == "__main__":
    unittest.main()
