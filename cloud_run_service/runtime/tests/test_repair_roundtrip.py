"""Ticket 05 — turn-level property: repair round-trip preserves provenance.repairs.

Free lane (no model calls). Uses a stub transcript policy that marks any VOICE
turn below the 0.50 stub floor as UNAUTHORIZED, producing repair_choices. The
subsequent REPAIR_SELECTION turn is AUTHORIZED and carries provenance.repairs
pointing back to the original utterance_id.

Property under test:
    For every VOICE turn that produces UNAUTHORIZED + repair_choices,
    a REPAIR_SELECTION turn repairing it is AUTHORIZED, not doubtful,
    and its embedded utterance's provenance.repairs equals the original utterance_id.

Startup-capability assertion (day-one supply):
    The current STT producer (Cloud STT) supplies only the utterance-confidence
    float. Word-confidence and alternate fields are not yet populated in
    production. The repair-path delta is therefore predicted ≈ zero — the only
    cause is UTTERANCE_CONFIDENCE — and this is written down here as a
    fixture-level note rather than a runtime assertion.
"""

from __future__ import annotations

import unittest

from runtime.contracts import (
    Utterance,
    UtteranceProvenance,
    UtteranceSource,
)
from utterance_intake import (
    Authorization,
    ConfidenceFloorPolicy,
    UtteranceIntake,
    UtteranceIntakeRequest,
)
from utterance_intake.observation import DoubtCause


def _make_intake(floor: float = 0.50) -> UtteranceIntake:
    """Stub: uses the standard ConfidenceFloorPolicy with a configurable floor."""
    return UtteranceIntake(transcript_policy=ConfidenceFloorPolicy(floor=floor))


def _observe(intake: UtteranceIntake, utterance: Utterance):
    from types import SimpleNamespace
    turn_input = SimpleNamespace(utterance=utterance)
    return intake.observe(UtteranceIntakeRequest(turn_input=turn_input)).value


class RepairRoundtripTests(unittest.TestCase):
    """Property: repair round-trip preserves provenance.repairs."""

    def test_unauthorized_voice_produces_repair_choices_when_alternates_present(self) -> None:
        """VOICE below floor with alternates → UNAUTHORIZED, doubtful, repair_choices populated."""
        intake = _make_intake(floor=0.50)
        utterance = Utterance(
            text="maybe six",
            source=UtteranceSource.VOICE,
            provenance=UtteranceProvenance(
                utterance_id="u_voice_1",
                captured_at="2026-08-28T00:00:00+00:00",
                recognizer="chirp/en-US",
            ),
            confidence=0.35,
            alternates=("maybe six", "maybe sick", "baby six"),
        )

        obs = _observe(intake, utterance)

        self.assertEqual(obs.authorization, Authorization.UNAUTHORIZED)
        self.assertTrue(obs.transcript.doubtful)
        self.assertIn(DoubtCause.UTTERANCE_CONFIDENCE, obs.transcript.causes)
        # repair_choices must be non-empty (alternates were supplied)
        self.assertGreater(len(obs.transcript.repair_choices), 0)
        self.assertEqual(obs.transcript.repair_choices[0], "maybe six")

    def test_repair_selection_is_authorized_and_not_doubtful(self) -> None:
        """REPAIR_SELECTION sourced from the original VOICE turn → AUTHORIZED + not doubtful."""
        intake = _make_intake(floor=0.50)
        repair = Utterance(
            text="maybe sick",
            source=UtteranceSource.REPAIR_SELECTION,
            provenance=UtteranceProvenance(
                utterance_id="u_repair_1",
                captured_at="2026-08-28T00:00:00+00:00",
                repairs="u_voice_1",
                selected_alternate_index=1,
            ),
        )

        obs = _observe(intake, repair)

        self.assertEqual(obs.authorization, Authorization.AUTHORIZED)
        self.assertFalse(obs.transcript.doubtful)
        self.assertEqual(obs.transcript.causes, ())
        self.assertEqual(obs.transcript.repair_choices, ())

    def test_roundtrip_provenance_preserved(self) -> None:
        """End-to-end: the REPAIR_SELECTION observation carries provenance.repairs == original id."""
        intake = _make_intake(floor=0.50)
        original_id = "u_voice_roundtrip"

        # Step 1: VOICE turn below floor → unauthorized + choices.
        voice = Utterance(
            text="three times four",
            source=UtteranceSource.VOICE,
            provenance=UtteranceProvenance(
                utterance_id=original_id,
                captured_at="2026-08-28T10:00:00+00:00",
                recognizer="chirp/en-US",
            ),
            confidence=0.28,
            alternates=("three times four", "free times four"),
        )
        voice_obs = _observe(intake, voice)
        self.assertEqual(voice_obs.authorization, Authorization.UNAUTHORIZED)
        choices = voice_obs.transcript.repair_choices
        self.assertGreater(len(choices), 0)

        # Step 2: learner selects alternate index 1 ("free times four").
        repair = Utterance(
            text=choices[1] if len(choices) > 1 else choices[0],
            source=UtteranceSource.REPAIR_SELECTION,
            provenance=UtteranceProvenance(
                utterance_id="u_repair_roundtrip",
                captured_at="2026-08-28T10:00:05+00:00",
                repairs=original_id,
                selected_alternate_index=1,
            ),
        )
        repair_obs = _observe(intake, repair)

        # Property: AUTHORIZED, not doubtful.
        self.assertEqual(repair_obs.authorization, Authorization.AUTHORIZED)
        self.assertFalse(repair_obs.transcript.doubtful)

        # Property: provenance.repairs is preserved in the embedded utterance.
        self.assertEqual(
            repair_obs.utterance.provenance.repairs,
            original_id,
            "repair_obs.utterance.provenance.repairs must equal the original utterance_id",
        )

    def test_repair_discard_is_discarded_and_not_doubtful(self) -> None:
        """REPAIR_DISCARD: learner rejected all hypotheses → DISCARDED, not doubtful."""
        intake = _make_intake(floor=0.50)
        discard = Utterance(
            text="",
            source=UtteranceSource.REPAIR_DISCARD,
            provenance=UtteranceProvenance(
                utterance_id="u_discard_1",
                captured_at="2026-08-28T10:01:00+00:00",
                repairs="u_voice_1",
            ),
        )
        obs = _observe(intake, discard)

        self.assertEqual(obs.authorization, Authorization.DISCARDED)
        self.assertFalse(obs.transcript.doubtful)

    def test_day_one_stt_supply_note(self) -> None:
        """Document: day-one producer supplies utterance-confidence only.

        Cloud STT does not yet populate word_confidences or multiple alternates
        in production. Repair-path delta is predicted ≈ zero — only cause is
        UTTERANCE_CONFIDENCE. This test asserts the single-signal path works
        and serves as the living documentation of that supply fact.
        """
        intake = _make_intake(floor=0.60)
        # Day-one shape: confidence only, no alternates, no word confidences.
        voice = Utterance(
            text="four times nine",
            source=UtteranceSource.VOICE,
            provenance=UtteranceProvenance(
                utterance_id="u_dayone",
                captured_at="2026-08-28T00:00:00+00:00",
                recognizer="chirp/en-US",
            ),
            confidence=0.45,   # below floor 0.60
        )
        obs = _observe(intake, voice)

        self.assertTrue(obs.transcript.doubtful)
        self.assertEqual(obs.transcript.causes, (DoubtCause.UTTERANCE_CONFIDENCE,))
        self.assertIsNone(obs.transcript.disagreement)      # no alternates
        self.assertIsNone(obs.transcript.min_word_confidence)  # no word confidences
        self.assertEqual(obs.transcript.repair_choices, ())    # no alternates → no choices


if __name__ == "__main__":
    unittest.main()
