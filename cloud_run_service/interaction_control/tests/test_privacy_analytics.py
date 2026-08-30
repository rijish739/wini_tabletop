"""The analytics row is a converted sink (PERSONAL_DATA_CONTRACT.md §6.2, §6.3, §8).

These drive the **real** ``InteractionControl``, not a stub, because the thing under test
is what the five ``log_event`` call sites actually put in the row — and those five are
where the live rows come from, not ``tutor_loop``'s two older helpers that §6.3's table
names by their pre-extraction line numbers.

A NEW FILE. ``test_interaction_control.py`` is not edited: it predates this axis and its
rows are about routing, not about what a row contains.
"""

from __future__ import annotations

import json
import unittest

from interaction_control import (
    InteractionControl,
    InteractionControlRequest,
)
from personal_data import (
    IdentifierClass,
    IdentifierFinding,
    PersonalDataVerdict,
    VerdictStatus,
    turn_redaction,
)

from .test_interaction_control import _Route, _dependencies, _turn


SECRET = "9876543210"
UTTERANCE = f"my number is {SECRET} and 9 x 25 x 17 = 3825"


def _redaction(*pairs, text: str = UTTERANCE):
    verdict = PersonalDataVerdict(
        utterance_id="u1", status=VerdictStatus.LANDED,
        findings=frozenset(
            IdentifierFinding(identifier_class=cls, value=value)
            for cls, value in pairs
        ),
    )
    return turn_redaction(text, verdict)


def _safety_case_record(redaction):
    """Run a real safety turn and return the case record it wrote.

    Captured through ``notify_safety`` rather than off the session dict: ``_control``
    works on a deep-thawed copy and publishes changes as ``StateChange``s, so the
    caller's dict never sees the write.
    """
    records: list[dict] = []
    route = _Route(primary="SAFETY", reason="safety gate", safety_alert=True)
    dependencies = _dependencies(
        deterministic_route=lambda text: route,
        persona={"identity": "Wini", "style": "Warm",
                 "intents": {"SAFETY": {"scripted": "Find a trusted adult."}}},
        log_event=lambda event: None,
        notify_safety=records.append,
    )
    InteractionControl(dependencies).control(InteractionControlRequest(
        turn_input=_turn(UTTERANCE),
        session={"current_concept": "quadratics", "context": []},
        personal_data=redaction,
    ))
    assert records, "a tripped safety turn writes exactly one case record"
    return records[-1]


def _nonlearning_row(redaction, *, safety_alert: bool = False):
    """Run a real non-learning turn and return the analytics row it logged."""
    logs: list[dict] = []
    route = _Route(
        primary="SOCIAL", reason="social route",
        safety_alert=safety_alert,
    )
    dependencies = _dependencies(
        deterministic_route=lambda text: route,
        persona={
            "identity": "Wini", "style": "Warm",
            "intents": {
                "SOCIAL": {"scripted": "Hello!"},
                "SAFETY": {"scripted": "Please get a trusted adult now."},
            },
        },
        log_event=logs.append,
        notify_safety=lambda record: None,
    )
    InteractionControl(dependencies).control(InteractionControlRequest(
        turn_input=_turn(UTTERANCE),
        session={"current_concept": "quadratics", "context": []},
        personal_data=redaction,
    ))
    assert logs, "a non-learning turn logs exactly one analytics row"
    return logs[-1]


class AnalyticsRowTests(unittest.TestCase):
    def test_a_landed_verdict_puts_placeholders_and_labels_in_the_row(self) -> None:
        row = _nonlearning_row(_redaction((IdentifierClass.PHONE, SECRET)))
        # The row carries a RedactedText, never a str — the writer is what turns it
        # into text, and the writer is what refuses anything else.
        self.assertEqual(str(row["question"]), "my number is <PHONE> and 9 x 25 x 17 = 3825")
        self.assertEqual(row["privacy_classes"], ["PHONE"])
        self.assertEqual(row["log_tier"], "general")

    def test_the_maths_survives_the_row(self) -> None:
        # §5: the collision has no tie-break because there is no threshold. Only the
        # substring the model named is removed.
        row = _nonlearning_row(_redaction((IdentifierClass.PHONE, SECRET)))
        self.assertIn("9 x 25 x 17 = 3825", str(row["question"]))

    def test_no_verdict_withholds_the_transcript(self) -> None:
        row = _nonlearning_row(None)
        self.assertIsNone(row["question"])
        self.assertEqual(row["privacy"], "privacy_unavailable")
        self.assertEqual(row["log_tier"], "privacy_withheld")

    def test_an_unverifiable_redaction_withholds_the_transcript(self) -> None:
        # §4: a named substring that is not in the utterance means redaction cannot be
        # verified, so the sink receives no transcript — but the CLASS is still recorded.
        row = _nonlearning_row(_redaction((IdentifierClass.PHONE, "not-in-text")))
        self.assertIsNone(row["question"])
        self.assertEqual(row["privacy"], "redaction_incomplete")
        self.assertEqual(row["privacy_classes"], ["PHONE"])

    def test_a_safety_turn_withholds_even_with_a_clean_redaction(self) -> None:
        # SAFETY_ROUTE_TAXONOMY.md §14 keeps a safety utterance out of routine
        # analytics entirely. Stricter than redaction, and independent of it.
        row = _nonlearning_row(
            _redaction((IdentifierClass.PHONE, SECRET)), safety_alert=True
        )
        self.assertIsNone(row["question"])
        self.assertEqual(row["log_tier"], "safety_withheld")

    def test_the_row_never_contains_the_identifier(self) -> None:
        for redaction in (
            _redaction((IdentifierClass.PHONE, SECRET)),
            _redaction((IdentifierClass.PHONE, "not-in-text")),
            None,
        ):
            with self.subTest(redaction=redaction):
                row = _nonlearning_row(redaction)
                self.assertNotIn(SECRET, json.dumps(row, default=str))

    def test_the_writer_refuses_a_bare_string_under_question(self) -> None:
        # §6.2: no `str` overload. The row's `question` is a RedactedText or None; the
        # WRITER (`tutor_loop._analytics_row`) is what turns one into text and what
        # withholds anything else, so a future call site that passes raw text loses the
        # transcript rather than persisting it.
        import tutor_loop

        withheld = tutor_loop._analytics_row({"question": f"my number is {SECRET}"})
        self.assertEqual(withheld["question"], tutor_loop.WITHHELD_TRANSCRIPT)
        self.assertEqual(withheld["privacy"], "unredacted_str_rejected")
        self.assertNotIn(SECRET, json.dumps(withheld))

    def test_the_safety_case_record_carries_class_labels_never_values(self) -> None:
        # §9.2 / SAFETY_ROUTE_TAXONOMY.md §14: where personal data co-occurs with a
        # safety trip, the case record carries `<CLASS>_PRESENT`, never raw values.
        record = _safety_case_record(_redaction((IdentifierClass.ADDRESS, SECRET)))
        self.assertEqual(record["privacy"], ["ADDRESS_PRESENT"])
        self.assertNotIn(SECRET, json.dumps(record, default=str))

    def test_the_case_record_is_stamped_unavailable_and_never_waits(self) -> None:
        # §9.2: a safeguarding case must not be delayed by an annotation about a phone
        # number. With no verdict the record is written anyway, stamped honestly.
        self.assertEqual(
            _safety_case_record(None)["privacy"], "privacy_unavailable"
        )

    def test_a_clean_turn_records_an_empty_class_list_not_a_missing_one(self) -> None:
        # An empty list says "the detector ran and found nothing"; a missing field says
        # nothing at all. §8's whole point is that those must not collapse.
        row = _nonlearning_row(_redaction())
        self.assertEqual(row["privacy_classes"], [])
        self.assertNotIn("privacy", row)


if __name__ == "__main__":
    unittest.main()
