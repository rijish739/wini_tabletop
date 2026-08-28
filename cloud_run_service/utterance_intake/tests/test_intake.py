"""observe() behaviour: normalization, authorization policy, totality, purity."""

from __future__ import annotations

import unittest

from runtime.contracts import Utterance, UtteranceProvenance, UtteranceSource, WordConfidence
from utterance_intake import (
    Authorization,
    ConfidenceFloorPolicy,
    UtteranceIntake,
    UtteranceIntakeRequest,
    normalize_text,
)
from utterance_intake.observation import DoubtCause
from utterance_intake.tests.harness import build_utterance, run_observe


class NormalizationTests(unittest.TestCase):
    def test_nfkc_is_absent_superscript_survives(self) -> None:
        self.assertEqual(normalize_text("x²"), "x²")

    def test_vulgar_fraction_survives(self) -> None:
        self.assertEqual(normalize_text("½"), "½")

    def test_minus_sign_survives(self) -> None:
        self.assertEqual(normalize_text("−5"), "−5")

    def test_zero_width_stripped(self) -> None:
        self.assertEqual(normalize_text("a​b"), "ab")

    def test_whitespace_collapsed(self) -> None:
        self.assertEqual(normalize_text("  a   b\tc  "), "a b c")

    def test_nfc_composition(self) -> None:
        # e + combining acute -> composed é
        self.assertEqual(normalize_text("é"), "é")


class NormalizationMathsTypographyTests(unittest.TestCase):
    """Slice-02: explicit proof that NFKC is absent from normalize_text.

    The old InputProcessor.normalize_input() used NFKC which silently destroyed
    maths typography (U+00B2 → '2', U+00BD → '1⁄2').  These tests make
    that regression impossible to sneak back in — they assert the *forbidden* NFKC
    output is NOT what we produce.  The matching expected_diffs rows document
    the intentional divergence from the old path.
    """

    def test_superscript_two_not_reduced_to_ascii_digit(self) -> None:
        # NFKC("x²") == "x2" — that must never happen in normalize_text.
        # NFKC("x²") == "x2" — NFC must never produce that.
        result = normalize_text("x²")
        self.assertEqual(result, "x²")

    def test_vulgar_fraction_not_expanded_by_nfkc(self) -> None:
        # NFKC("½") == "1⁄2" — that must never happen in normalize_text.
        result = normalize_text("½")
        self.assertEqual(result, "½")
        self.assertNotIn("⁄", result,
                         "NFKC expansion of ½ to 1⁄2 must not occur")

    def test_nbsp_collapses_to_regular_space(self) -> None:
        # U+00A0 (non-breaking space) is Unicode whitespace; \s matches it.
        # Both NFKC and NFC paths collapse it via the whitespace regex.
        self.assertEqual(normalize_text("the answer"), "the answer")

    def test_zwj_stripped(self) -> None:
        # U+200D (zero-width joiner) is stripped by the _ZERO_WIDTH translate.
        # NFKC does NOT change U+200D, so both paths strip it the same way.
        self.assertEqual(normalize_text("a‍b"), "ab")

    def test_zwnj_stripped(self) -> None:
        # U+200C (zero-width non-joiner) — same stripping rule as ZWJ.
        self.assertEqual(normalize_text("a‌b"), "ab")
    def test_minus_sign_u2212_survives(self) -> None:
        # U+2212 MINUS SIGN has no NFKC compatibility mapping, so it is unchanged
        # by both paths. This is the proof required by the spec alongside x² and ½.
        result = normalize_text("−5")
        self.assertEqual(result, "−5")


class AuthorizationTests(unittest.TestCase):
    def _voice(self, confidence):
        return Utterance(
            text="the answer is seven", source=UtteranceSource.VOICE,
            provenance=UtteranceProvenance(
                utterance_id="u1", captured_at="t", recognizer="chirp/en-US"),
            confidence=confidence,
        )

    def test_typed_is_authorized(self) -> None:
        obs = run_observe(build_utterance({"text": "5", "source": "TYPED"}))
        self.assertEqual(obs.authorization, Authorization.AUTHORIZED)

    def test_voice_below_floor_is_unauthorized(self) -> None:
        obs = run_observe(self._voice(0.30))
        self.assertEqual(obs.authorization, Authorization.UNAUTHORIZED)

    def test_voice_at_floor_is_authorized(self) -> None:
        obs = run_observe(self._voice(0.60))
        self.assertEqual(obs.authorization, Authorization.AUTHORIZED)

    def test_voice_none_confidence_is_no_gate_authorized(self) -> None:
        obs = run_observe(self._voice(None))
        self.assertEqual(obs.authorization, Authorization.AUTHORIZED)

    def test_discard_is_discarded(self) -> None:
        u = Utterance(text="", source=UtteranceSource.REPAIR_DISCARD,
                      provenance=UtteranceProvenance(
                          utterance_id="u1", captured_at="t", repairs="t0"))
        obs = run_observe(u)
        self.assertEqual(obs.authorization, Authorization.DISCARDED)

    def test_floor_is_injected_not_baked_in(self) -> None:
        strict = UtteranceIntake(transcript_policy=ConfidenceFloorPolicy(floor=0.95))
        obs = strict.observe(UtteranceIntakeRequest(
            turn_input=type("T", (), {"utterance": self._voice(0.90)})())).value
        self.assertEqual(obs.authorization, Authorization.UNAUTHORIZED)


class TotalityAndPurityTests(unittest.TestCase):
    def test_observe_is_total_and_write_free(self) -> None:
        outcome = UtteranceIntake().observe(UtteranceIntakeRequest(
            turn_input=type("T", (), {
                "utterance": Utterance(text="", source=UtteranceSource.TYPED,
                                       provenance=UtteranceProvenance(
                                           utterance_id="u1", captured_at="t"))})()))
        self.assertIsNotNone(outcome.value)
        self.assertEqual(outcome.state_changes, ())
        self.assertEqual(outcome.failures, ())
        self.assertTrue(outcome.valid)

    def test_embeds_utterance_whole(self) -> None:
        u = build_utterance({"text": "5", "source": "TYPED"})
        obs = run_observe(u)
        self.assertIs(obs.utterance, u)


class TranscriptDoubtTests(unittest.TestCase):
    """Ticket 05: three-signal OR logic for acoustic doubt.

    Covers: non-VOICE never doubtful; utterance-confidence signal; min-word-
    confidence signal; alternate-disagreement signal; OR combination; repair_choices
    populated only when doubtful.
    """

    # ------------------------------------------------------------------ helpers

    def _voice(
        self,
        confidence: float | None = 0.92,
        alternates: tuple[str, ...] = (),
        word_confidences: tuple[WordConfidence, ...] = (),
    ) -> Utterance:
        return Utterance(
            text="test utterance",
            source=UtteranceSource.VOICE,
            provenance=UtteranceProvenance(
                utterance_id="u_doubt", captured_at="2026-08-28T00:00:00+00:00",
                recognizer="chirp/en-US",
            ),
            confidence=confidence,
            alternates=alternates,
            word_confidences=word_confidences,
        )

    def _obs(self, utterance: Utterance):
        return run_observe(utterance)

    # ------------------------------------------------------------------ non-VOICE

    def test_typed_is_never_doubtful(self) -> None:
        obs = run_observe(build_utterance({"text": "five", "source": "TYPED"}))
        self.assertFalse(obs.transcript.doubtful)
        self.assertEqual(obs.transcript.causes, ())
        self.assertEqual(obs.transcript.repair_choices, ())

    def test_repair_selection_is_never_doubtful(self) -> None:
        obs = run_observe(build_utterance({
            "text": "five", "source": "REPAIR_SELECTION",
            "repairs": "u_prev", "selected_alternate_index": 0,
        }))
        self.assertFalse(obs.transcript.doubtful)

    def test_repair_discard_is_never_doubtful(self) -> None:
        obs = run_observe(build_utterance({
            "text": "", "source": "REPAIR_DISCARD", "repairs": "u_prev",
        }))
        self.assertFalse(obs.transcript.doubtful)

    # ------------------------------------------------------------------ signal 1: utterance confidence

    def test_voice_above_floor_not_doubtful(self) -> None:
        """Confidence 0.60 is at the floor — authorized and not doubtful."""
        obs = self._obs(self._voice(confidence=0.60))
        self.assertFalse(obs.transcript.doubtful)
        self.assertEqual(obs.transcript.causes, ())

    def test_voice_below_floor_is_doubtful(self) -> None:
        """Confidence 0.30 < 0.60 → UTTERANCE_CONFIDENCE cause."""
        obs = self._obs(self._voice(confidence=0.30))
        self.assertTrue(obs.transcript.doubtful)
        self.assertIn(DoubtCause.UTTERANCE_CONFIDENCE, obs.transcript.causes)

    def test_voice_none_confidence_not_doubtful(self) -> None:
        """None confidence means the producer did not report it — no gate, no doubt."""
        obs = self._obs(self._voice(confidence=None))
        self.assertFalse(obs.transcript.doubtful)

    # ------------------------------------------------------------------ signal 2: word confidence

    def test_word_confidence_below_floor_is_doubtful(self) -> None:
        """Min word confidence 0.25 < WORD_CONFIDENCE_FLOOR (0.40) → WORD_CONFIDENCE cause."""
        wc = (WordConfidence(word="maybe", confidence=0.90),
              WordConfidence(word="three", confidence=0.25))
        # Utterance confidence is above floor so only the word signal fires.
        obs = self._obs(self._voice(confidence=0.80, word_confidences=wc))
        self.assertTrue(obs.transcript.doubtful)
        self.assertIn(DoubtCause.WORD_CONFIDENCE, obs.transcript.causes)
        self.assertNotIn(DoubtCause.UTTERANCE_CONFIDENCE, obs.transcript.causes)
        # min_word_confidence carries the measured value
        self.assertAlmostEqual(obs.transcript.min_word_confidence, 0.25)

    def test_word_confidence_above_floor_not_doubtful_on_word_signal(self) -> None:
        """Min word confidence 0.45 >= WORD_CONFIDENCE_FLOOR → no WORD_CONFIDENCE cause."""
        wc = (WordConfidence(word="six", confidence=0.80),
              WordConfidence(word="seven", confidence=0.45))
        obs = self._obs(self._voice(confidence=0.80, word_confidences=wc))
        self.assertNotIn(DoubtCause.WORD_CONFIDENCE, obs.transcript.causes)

    def test_word_confidence_none_skipped(self) -> None:
        """A WordConfidence with confidence=None is excluded from the min calculation."""
        wc = (WordConfidence(word="hello", confidence=None),)
        obs = self._obs(self._voice(confidence=0.80, word_confidences=wc))
        self.assertIsNone(obs.transcript.min_word_confidence)
        self.assertFalse(obs.transcript.doubtful)

    # ------------------------------------------------------------------ signal 3: alternate disagreement

    def test_alternate_disagreement_above_ceiling_is_doubtful(self) -> None:
        """Alternates that disagree above DISAGREEMENT_CEILING (0.30) → ALTERNATE_DISAGREEMENT."""
        # "five times six" vs "fire times ix" vs "five times seventh" → ~0.44 disagreement
        alts = ("five times six", "fire times ix", "five times seventh")
        obs = self._obs(self._voice(confidence=0.90, alternates=alts))
        self.assertTrue(obs.transcript.doubtful)
        self.assertIn(DoubtCause.ALTERNATE_DISAGREEMENT, obs.transcript.causes)
        self.assertIsNotNone(obs.transcript.disagreement)
        self.assertGreater(obs.transcript.disagreement, 0.30)

    def test_single_alternate_no_disagreement_computed(self) -> None:
        """Fewer than 2 alternates → disagreement=None → no ALTERNATE_DISAGREEMENT signal."""
        obs = self._obs(self._voice(confidence=0.90, alternates=("five",)))
        self.assertIsNone(obs.transcript.disagreement)
        self.assertNotIn(DoubtCause.ALTERNATE_DISAGREEMENT, obs.transcript.causes)

    def test_identical_alternates_no_doubt(self) -> None:
        """Identical alternates → disagreement=0.0 → not doubtful from that signal."""
        alts = ("the answer is five", "the answer is five")
        obs = self._obs(self._voice(confidence=0.90, alternates=alts))
        self.assertIsNotNone(obs.transcript.disagreement)
        self.assertAlmostEqual(obs.transcript.disagreement, 0.0)
        self.assertNotIn(DoubtCause.ALTERNATE_DISAGREEMENT, obs.transcript.causes)

    # ------------------------------------------------------------------ OR logic and repair_choices

    def test_or_logic_any_signal_triggers_doubt(self) -> None:
        """Both utterance-confidence and word-confidence signals fire → both causes listed."""
        wc = (WordConfidence(word="maybe", confidence=0.20),)
        obs = self._obs(self._voice(confidence=0.30, word_confidences=wc))
        self.assertTrue(obs.transcript.doubtful)
        causes = obs.transcript.causes
        self.assertIn(DoubtCause.UTTERANCE_CONFIDENCE, causes)
        self.assertIn(DoubtCause.WORD_CONFIDENCE, causes)

    def test_repair_choices_empty_when_not_doubtful(self) -> None:
        obs = self._obs(self._voice(confidence=0.92))
        self.assertEqual(obs.transcript.repair_choices, ())

    def test_repair_choices_populated_when_doubtful_with_alternates(self) -> None:
        """When doubtful and alternates present, repair_choices carries top-3 distinct normalized."""
        alts = ("five times six", "fire times ix", "five times seventh")
        obs = self._obs(self._voice(confidence=0.90, alternates=alts))
        self.assertTrue(obs.transcript.doubtful)
        self.assertEqual(obs.transcript.repair_choices, (
            "five times six", "fire times ix", "five times seventh"
        ))

    def test_repair_choices_empty_when_doubtful_but_no_alternates(self) -> None:
        """Low confidence with no alternates → doubtful, repair_choices empty."""
        obs = self._obs(self._voice(confidence=0.30))
        self.assertTrue(obs.transcript.doubtful)
        self.assertEqual(obs.transcript.repair_choices, ())

    def test_repair_choices_deduped_and_capped_at_three(self) -> None:
        """Duplicate alternates are deduplicated; at most 3 are returned."""
        alts = ("five", "five", "six", "seven", "eight")
        # Low confidence to trigger doubt
        obs = self._obs(self._voice(confidence=0.30, alternates=alts))
        self.assertTrue(obs.transcript.doubtful)
        # deduplicated + capped at 3
        choices = obs.transcript.repair_choices
        self.assertLessEqual(len(choices), 3)
        # no duplicates
        self.assertEqual(len(set(choices)), len(choices))


if __name__ == "__main__":
    unittest.main()
