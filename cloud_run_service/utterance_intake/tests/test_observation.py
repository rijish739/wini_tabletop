"""Construction invariants of the frozen observation contract — they raise, never clamp."""

from __future__ import annotations

import unittest

from runtime.contracts import (
    Utterance,
    UtteranceProvenance,
    UtteranceSource,
    WordConfidence,
)
from utterance_intake.observation import (
    Authorization,
    LegibilityCue,
    LegibilityReading,
    MathParse,
    ParseOutcome,
    ProblemCue,
    ProblemReading,
    SafetyClass,
    SafetyFinding,
    SafetySignals,
    SafetySource,
    Span,
    TranscriptReading,
)


def _prov(**kw) -> UtteranceProvenance:
    base = dict(utterance_id="u1", captured_at="2026-08-27T00:00:00+00:00")
    base.update(kw)
    return UtteranceProvenance(**base)


class UtteranceInvariants(unittest.TestCase):
    def test_confidence_out_of_range_raises(self) -> None:
        with self.assertRaises(ValueError):
            Utterance(text="hi", source=UtteranceSource.VOICE,
                      provenance=_prov(), confidence=1.5)

    def test_typed_carries_none_confidence_not_fabricated(self) -> None:
        u = Utterance(text="5", source=UtteranceSource.TYPED, provenance=_prov())
        self.assertIsNone(u.confidence)

    def test_empty_text_allowed(self) -> None:
        u = Utterance(text="", source=UtteranceSource.TYPED, provenance=_prov())
        self.assertEqual(u.text, "")

    def test_word_confidences_require_voice(self) -> None:
        with self.assertRaises(ValueError):
            Utterance(text="hi", source=UtteranceSource.TYPED, provenance=_prov(),
                      word_confidences=(WordConfidence(word="hi"),))

    def test_repair_selection_requires_repairs_and_index(self) -> None:
        with self.assertRaises(ValueError):
            Utterance(text="x", source=UtteranceSource.REPAIR_SELECTION,
                      provenance=_prov())
        ok = Utterance(text="x", source=UtteranceSource.REPAIR_SELECTION,
                       provenance=_prov(repairs="t0", selected_alternate_index=0))
        self.assertEqual(ok.provenance.selected_alternate_index, 0)

    def test_repair_discard_requires_empty_text_and_no_index(self) -> None:
        with self.assertRaises(ValueError):
            Utterance(text="something", source=UtteranceSource.REPAIR_DISCARD,
                      provenance=_prov(repairs="t0"))
        ok = Utterance(text="", source=UtteranceSource.REPAIR_DISCARD,
                       provenance=_prov(repairs="t0"))
        self.assertEqual(ok.text, "")


class SafetySignalsInvariants(unittest.TestCase):
    def _finding(self) -> SafetyFinding:
        return SafetyFinding(
            safety_class=SafetyClass.UNSPECIFIED_CONCERN,
            source=SafetySource.LEXICON, evidence_id="pat-1",
        )

    def test_tripped_must_equal_bool_findings(self) -> None:
        with self.assertRaises(ValueError):
            SafetySignals(tripped=True, findings=frozenset(),
                          caregiver_implicated=False, imminence_cue=False)

    def test_intake_reading_is_lexicon_only(self) -> None:
        model_finding = SafetyFinding(
            safety_class=SafetyClass.SELF_HARM, source=SafetySource.MODEL,
            evidence_id="prompt-v1",
        )
        with self.assertRaises(ValueError):
            SafetySignals(tripped=True, findings=frozenset({model_finding}),
                          caregiver_implicated=False, imminence_cue=False)
        with self.assertRaises(ValueError):
            SafetySignals(tripped=True, findings=frozenset({self._finding()}),
                          caregiver_implicated=False, imminence_cue=False,
                          source=SafetySource.MODEL)

    def test_flags_false_when_not_tripped(self) -> None:
        with self.assertRaises(ValueError):
            SafetySignals(tripped=False, findings=frozenset(),
                          caregiver_implicated=True, imminence_cue=False)


class ReadingInvariants(unittest.TestCase):
    def test_legibility_illegible_iff_not_legible_cue(self) -> None:
        with self.assertRaises(ValueError):
            LegibilityReading(illegible=True, cue=LegibilityCue.LEGIBLE)
        with self.assertRaises(ValueError):
            LegibilityReading(illegible=False, cue=LegibilityCue.EMPTY)

    def test_passthrough_span_is_none(self) -> None:
        with self.assertRaises(ValueError):
            MathParse(outcome=ParseOutcome.PASSTHROUGH, span=Span(0, 1))
        ok = MathParse(outcome=ParseOutcome.PASSTHROUGH)
        self.assertIsNone(ok.span)

    def test_interpretation_only_on_accept(self) -> None:
        with self.assertRaises(ValueError):
            MathParse(outcome=ParseOutcome.PASSTHROUGH, interpretation="3^2")
        ok = MathParse(outcome=ParseOutcome.ACCEPT, span=Span(0, 2),
                       interpretation="3^2")
        self.assertEqual(ok.interpretation, "3^2")

    def test_competing_only_on_refuse_ambiguous(self) -> None:
        with self.assertRaises(ValueError):
            MathParse(outcome=ParseOutcome.ACCEPT, span=Span(0, 1),
                      competing=("a", "b"))

    def test_transcript_causes_empty_iff_not_doubtful(self) -> None:
        with self.assertRaises(ValueError):
            TranscriptReading(doubtful=True,
                              parse=MathParse(outcome=ParseOutcome.PASSTHROUGH))

    def test_problem_cue_presence_matches_is_problem(self) -> None:
        with self.assertRaises(ValueError):
            ProblemReading(is_problem=True, directive=False)
        with self.assertRaises(ValueError):
            ProblemReading(is_problem=False, directive=False, cue=ProblemCue.EQUATION)


if __name__ == "__main__":
    unittest.main()
