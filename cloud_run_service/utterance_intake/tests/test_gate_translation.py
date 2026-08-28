"""Tier A: gate() over the observation is byte-identical to gate() over text.

The tell that the Utterance Intake seam landed correctly is that gate()'s
SAFETY / NONSENSE decisions are unchanged when routed through the observation.
Covers the terse-real-answer set and the nine nonsense probes.
"""

from __future__ import annotations

import unittest

from perception.gates import gate
from utterance_intake.tests.harness import build_utterance, run_observe

# Clearly-real terse answers that pass the frozen lexicon straight through today.
_TERSE_REAL = ["5", "x=3", "no", "yes", "cos", "why", "x=2"]

# The nine conservative nonsense probes gate() fires NONSENSE on today.
_NONSENSE_PROBES = ["", "     ", "!!!!!", "?????", "aaaaaa", ".....", "µ", "sdfghjk",
                    "qwrtpln"]

# Byte-identical set: whatever gate(text) does, gate(observation) must match —
# including the ½ case the frozen lexicon currently mis-gates as nonsense.
_EQUIVALENCE = _TERSE_REAL + _NONSENSE_PROBES + ["½", "i want to kill myself"]


def _route(text: str):
    observation = run_observe(build_utterance({"text": text, "source": "TYPED"}))
    return gate(text), gate(observation)


class GateTranslationTierA(unittest.TestCase):
    def test_terse_real_answers_pass_through_both_paths(self) -> None:
        for text in _TERSE_REAL:
            with self.subTest(text=text):
                by_text, by_obs = _route(text)
                self.assertIsNone(by_text, f"{text!r} should pass gate(text)")
                self.assertIsNone(by_obs, f"{text!r} should pass gate(observation)")

    def test_observation_path_is_byte_identical_to_text_path(self) -> None:
        for text in _EQUIVALENCE:
            with self.subTest(text=text):
                by_text, by_obs = _route(text)
                text_primary = None if by_text is None else by_text.primary
                obs_primary = None if by_obs is None else by_obs.primary
                self.assertEqual(text_primary, obs_primary)

    def test_nonsense_probes_gate_identically(self) -> None:
        for text in _NONSENSE_PROBES:
            with self.subTest(text=text):
                by_text, by_obs = _route(text)
                text_primary = None if by_text is None else by_text.primary
                obs_primary = None if by_obs is None else by_obs.primary
                self.assertEqual(text_primary, obs_primary)
                self.assertEqual(text_primary, "NONSENSE")

    def test_safety_trip_routes_the_same_by_both_paths(self) -> None:
        text = "i want to kill myself"
        by_text, by_obs = _route(text)
        self.assertEqual(by_text.primary, "SAFETY")
        self.assertEqual(by_obs.primary, "SAFETY")
        self.assertTrue(by_obs.safety_alert)



class GateAcousticExclusion(unittest.TestCase):
    """Spec: "gate() NONSENSE arm consumes observation.legibility (textual axis only;
    nothing acoustic feeds NONSENSE)."

    A VOICE utterance with low confidence (UNAUTHORIZED) and legible text must NOT
    be gated as NONSENSE. The acoustic axis (authorization) is orthogonal to the
    textual axis (legibility); only the latter feeds NONSENSE.
    """

    def test_unauthorized_voice_with_legible_text_not_nonsense(self) -> None:
        # Confidence 0.30 -> UNAUTHORIZED; text "maybe twelve" is legible.
        obs = run_observe(build_utterance({
            "text": "maybe twelve",
            "source": "VOICE",
            "confidence": 0.30,
            "recognizer": "chirp/en-US",
        }))
        # Authorization is UNAUTHORIZED (acoustic), but legibility is LEGIBLE (textual).
        from utterance_intake import Authorization
        self.assertEqual(obs.authorization, Authorization.UNAUTHORIZED)
        self.assertFalse(obs.legibility.illegible)
        # gate() must not fire NONSENSE — the acoustic axis does not feed it.
        result = gate(obs)
        self.assertIsNone(result,
                          "UNAUTHORIZED voice with legible text must not be gated as NONSENSE")

    def test_safety_beats_nonsense_priority(self) -> None:
        # A safety trip on a text that is also nonsense: SAFETY wins.
        text = "kill myself"   # triggers SAFETY; also no real lexical structure
        obs = run_observe(build_utterance({"text": text, "source": "TYPED"}))
        result = gate(obs)
        self.assertIsNotNone(result)
        self.assertEqual(result.primary, "SAFETY",
                         "SAFETY must beat NONSENSE even if the text would also be gated for NONSENSE")

if __name__ == "__main__":
    unittest.main()
