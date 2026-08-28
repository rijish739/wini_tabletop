"""The frozen Utterance Intake observation contract.

This is the one thing every later slice of the deterministic-input-layer effort
builds against. It is a closed vocabulary of booleans, enums, and spans — no
scores, no cue matrix, no ``RouteResult``. The only floats reachable from an
``UtteranceObservation`` arrive from outside on the embedded ``Utterance``.

Invariants raise, never clamp: an invalid reading is unconstructable. The five
readings on ``UtteranceObservation`` are all required and non-defaulted (there is
no ``privacy`` slot — personal-data detection is model-only and Intake is
model-free). See ``.scratch/deterministic-input-layer/spec.md`` and, for the
safety types, ``docs/architecture/SAFETY_ROUTE_TAXONOMY.md`` §15 (normative).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from runtime.contracts import Utterance


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
class Authorization(str, Enum):
    AUTHORIZED = "AUTHORIZED"       # TYPED, REPAIR_SELECTION, or VOICE at/above the floor
    UNAUTHORIZED = "UNAUTHORIZED"   # VOICE below the floor; a repair screen is pending
    DISCARDED = "DISCARDED"         # the learner rejected every hypothesis


# ---------------------------------------------------------------------------
# Safety — LEXICON-only reading (SAFETY_ROUTE_TAXONOMY.md §15 is normative)
# ---------------------------------------------------------------------------
class SafetyClass(str, Enum):
    SELF_HARM = "SELF_HARM"
    HARM_BY_OTHER = "HARM_BY_OTHER"
    THREAT_TO_CHILD = "THREAT_TO_CHILD"
    THREAT_BY_CHILD = "THREAT_BY_CHILD"
    PEER_AT_RISK = "PEER_AT_RISK"
    UNSAFE_CONTACT = "UNSAFE_CONTACT"
    UNSPECIFIED_CONCERN = "UNSPECIFIED_CONCERN"


class SafetySource(str, Enum):
    MODEL = "MODEL"                 # the child_safety call
    PERCEPTION_BIT = "PERCEPTION_BIT"  # perception's existing `safety` boolean
    LEXICON = "LEXICON"            # the degraded-mode net


@dataclass(frozen=True)
class SafetyFinding:
    safety_class: SafetyClass
    source: SafetySource
    evidence_id: str               # stable pattern id (LEXICON). NEVER the matched span.

    def __post_init__(self) -> None:
        object.__setattr__(self, "safety_class", SafetyClass(self.safety_class))
        object.__setattr__(self, "source", SafetySource(self.source))
        if not self.evidence_id:
            raise ValueError("SafetyFinding requires an evidence_id")


@dataclass(frozen=True)
class SafetySignals:
    """Produced by Utterance Intake — LEXICON only, no severity.

    On a healthy turn this is *not* the verdict; it is consumed only in degraded
    mode and by the divergence monitor. Severity lives on the downstream verdict,
    not on the reading.
    """

    tripped: bool
    findings: frozenset[SafetyFinding]
    caregiver_implicated: bool
    imminence_cue: bool
    source: SafetySource = SafetySource.LEXICON

    def __post_init__(self) -> None:
        object.__setattr__(self, "findings", frozenset(self.findings))
        object.__setattr__(self, "source", SafetySource(self.source))
        if self.tripped != bool(self.findings):
            raise ValueError("SafetySignals.tripped must equal bool(findings)")
        if self.source is not SafetySource.LEXICON:
            raise ValueError("SafetySignals is LEXICON-only inside Utterance Intake")
        if any(f.source is not SafetySource.LEXICON for f in self.findings):
            raise ValueError("every SafetySignals finding carries source=LEXICON")
        if not self.tripped and (self.caregiver_implicated or self.imminence_cue):
            raise ValueError("flags must be False when the axis has not tripped")


# ---------------------------------------------------------------------------
# Legibility
# ---------------------------------------------------------------------------
class LegibilityCue(str, Enum):
    LEGIBLE = "LEGIBLE"
    EMPTY = "EMPTY"
    NO_ALPHANUMERIC = "NO_ALPHANUMERIC"
    CHARACTER_RUN = "CHARACTER_RUN"
    NO_LEXICAL_CONTENT = "NO_LEXICAL_CONTENT"
    KEYBOARD_MASH = "KEYBOARD_MASH"


@dataclass(frozen=True)
class LegibilityReading:
    illegible: bool
    cue: LegibilityCue

    def __post_init__(self) -> None:
        object.__setattr__(self, "cue", LegibilityCue(self.cue))
        if self.illegible == (self.cue is LegibilityCue.LEGIBLE):
            raise ValueError("illegible iff cue is not LEGIBLE")


# ---------------------------------------------------------------------------
# Transcript axis + maths parse (the STT uncertainty contract)
# ---------------------------------------------------------------------------
class ParseOutcome(str, Enum):
    ACCEPT = "ACCEPT"
    PASSTHROUGH = "PASSTHROUGH"
    REFUSE_AMBIGUOUS = "REFUSE_AMBIGUOUS"
    REFUSE_OUT_OF_GRAMMAR = "REFUSE_OUT_OF_GRAMMAR"


class DoubtCause(str, Enum):
    UTTERANCE_CONFIDENCE = "UTTERANCE_CONFIDENCE"
    WORD_CONFIDENCE = "WORD_CONFIDENCE"
    ALTERNATE_DISAGREEMENT = "ALTERNATE_DISAGREEMENT"
    AMBIGUOUS_PARSE = "AMBIGUOUS_PARSE"
    OUT_OF_GRAMMAR = "OUT_OF_GRAMMAR"


@dataclass(frozen=True)
class Span:
    start: int                     # token index into normalized_text
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError("Span requires 0 <= start <= end")


@dataclass(frozen=True)
class MathParse:
    outcome: ParseOutcome
    span: Span | None = None       # the span CLAIMED as mathematical; None on PASSTHROUGH
    interpretation: str | None = None   # ACCEPT only — e.g. "3^2"
    derivation: str | None = None       # the audit artifact
    competing: tuple[str, ...] = ()     # REFUSE_AMBIGUOUS only — the rival readings
    grammar_version: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", ParseOutcome(self.outcome))
        object.__setattr__(self, "competing", tuple(self.competing))
        if (self.span is None) != (self.outcome is ParseOutcome.PASSTHROUGH):
            raise ValueError("span is None iff outcome is PASSTHROUGH")
        if (self.interpretation is not None) != (self.outcome is ParseOutcome.ACCEPT):
            raise ValueError("interpretation is set iff outcome is ACCEPT")
        if self.competing and self.outcome is not ParseOutcome.REFUSE_AMBIGUOUS:
            raise ValueError("competing readings only on REFUSE_AMBIGUOUS")


@dataclass(frozen=True)
class TranscriptReading:
    doubtful: bool
    parse: MathParse
    causes: tuple[DoubtCause, ...] = ()      # empty iff not doubtful
    contested_spans: tuple[Span, ...] = ()
    disagreement: float | None = None        # None = fewer than 2 hypotheses supplied
    min_word_confidence: float | None = None  # None = not reported
    repair_choices: tuple[str, ...] = ()     # top-3 distinct, index 0 == primary; () unless doubtful

    def __post_init__(self) -> None:
        object.__setattr__(self, "causes", tuple(self.causes))
        object.__setattr__(self, "contested_spans", tuple(self.contested_spans))
        object.__setattr__(self, "repair_choices", tuple(self.repair_choices))
        if self.doubtful != bool(self.causes):
            raise ValueError("causes is empty iff not doubtful")
        if not self.doubtful and self.repair_choices:
            raise ValueError("repair_choices only when doubtful")


# ---------------------------------------------------------------------------
# Problem detection
# ---------------------------------------------------------------------------
class ProblemCue(str, Enum):
    EQUATION = "equation"
    EXPRESSION = "expression"
    SOLVE_VERB_NUMERALS = "solve_verb+numerals"


@dataclass(frozen=True)
class ProblemReading:
    is_problem: bool
    directive: bool
    cue: ProblemCue | None = None

    def __post_init__(self) -> None:
        if self.cue is not None:
            object.__setattr__(self, "cue", ProblemCue(self.cue))
        if self.is_problem and self.cue is None:
            raise ValueError("a problem reading carries a cue")
        if not self.is_problem and self.cue is not None:
            raise ValueError("a non-problem reading carries no cue")

    @property
    def is_directive_problem(self) -> bool:
        """True iff the student both presented a problem *and* addressed the tutor.

        Centralises the three-way guard ``is_problem and directive`` that would
        otherwise be re-implemented at every consumer site.
        """
        return self.is_problem and self.directive

    @classmethod
    def absent(cls) -> "ProblemReading":
        """The canonical zero/deferred reading — no problem detected or deferred.

        Use in place of ``ProblemReading(is_problem=False, directive=False)``
        so the four construction sites share a name and a meaning.
        """
        return cls(is_problem=False, directive=False)


# ---------------------------------------------------------------------------
# Reference / anaphora — evidence only, spans not a boolean
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AnaphorSpan:
    text: str
    span: Span


@dataclass(frozen=True)
class ReferenceReading:
    anaphors: tuple[AnaphorSpan, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "anaphors", tuple(self.anaphors))

    @property
    def has_anaphora(self) -> bool:
        return bool(self.anaphors)


# ---------------------------------------------------------------------------
# The observation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class UtteranceObservation:
    """One frozen, model-free observation of what was said. It observes; it
    decides nothing. The embedded ``Utterance`` is carried whole, never
    flattened — consumers read ``obs.utterance.confidence``."""

    utterance: Utterance            # embedded whole, never flattened
    normalized_text: str            # exactly one published form
    authorization: Authorization
    safety: SafetySignals           # lexicon-only; see SAFETY_ROUTE_TAXONOMY.md §15
    legibility: LegibilityReading
    transcript: TranscriptReading
    problem: ProblemReading
    reference: ReferenceReading

    def __post_init__(self) -> None:
        object.__setattr__(self, "authorization", Authorization(self.authorization))
        if not isinstance(self.utterance, Utterance):
            raise ValueError("UtteranceObservation embeds an Utterance whole")


PASSTHROUGH_PARSE = MathParse(outcome=ParseOutcome.PASSTHROUGH)
"""The honest default maths parse — no span was claimed as mathematical."""
