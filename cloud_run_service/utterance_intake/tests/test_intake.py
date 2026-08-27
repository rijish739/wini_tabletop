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
