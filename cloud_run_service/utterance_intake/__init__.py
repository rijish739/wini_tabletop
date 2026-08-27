"""Utterance Intake — turns one raw Utterance into a model-free observation.

It observes; it decides nothing. One public interface (``UtteranceIntake.observe``),
one frozen output contract (``UtteranceObservation``). See ``README.md`` and
``.scratch/deterministic-input-layer/spec.md``.
"""

from .intake import (
    ConfidenceFloorPolicy,
    TranscriptPolicy,
    UtteranceIntake,
    UtteranceIntakeRequest,
    normalize_text,
)
from .observation import (
    AnaphorSpan,
    Authorization,
    DoubtCause,
    LegibilityCue,
    LegibilityReading,
    MathParse,
    ParseOutcome,
    ProblemCue,
    ProblemReading,
    ReferenceReading,
    SafetyClass,
    SafetyFinding,
    SafetySignals,
    SafetySource,
    Span,
    TranscriptReading,
    UtteranceObservation,
)

__all__ = [
    "ConfidenceFloorPolicy",
    "TranscriptPolicy",
    "UtteranceIntake",
    "UtteranceIntakeRequest",
    "normalize_text",
    "AnaphorSpan",
    "Authorization",
    "DoubtCause",
    "LegibilityCue",
    "LegibilityReading",
    "MathParse",
    "ParseOutcome",
    "ProblemCue",
    "ProblemReading",
    "ReferenceReading",
    "SafetyClass",
    "SafetyFinding",
    "SafetySignals",
    "SafetySource",
    "Span",
    "TranscriptReading",
    "UtteranceObservation",
]
