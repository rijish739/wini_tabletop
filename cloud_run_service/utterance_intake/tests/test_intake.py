"""observe() behaviour: normalization, authorization policy, totality, purity."""

from __future__ import annotations

import unittest

from runtime.contracts import Utterance, UtteranceProvenance, UtteranceSource
from utterance_intake import (
    Authorization,
    ConfidenceFloorPolicy,
    UtteranceIntake,
    UtteranceIntakeRequest,
    normalize_text,
)
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


if __name__ == "__main__":
    unittest.main()
