"""Utterance Intake — the one public door onto the raw-text -> observation step.

``UtteranceIntake.observe`` turns one raw ``Utterance`` into a screened,
normalized, model-free ``UtteranceObservation``. It is **total** (every
``Utterance`` yields a valid observation), **write-free** (``state_changes`` is
always empty), and **pure of session** (the observation is a deterministic
function of one ``Utterance`` and an injected transcript policy that is itself a
pure function of one ``Utterance``).

This is the walking-skeleton body (ticket 01). Its behaviour is deliberately
trivial: NFC + zero-width strip + whitespace collapse; authorization from the
injected policy; the real LEXICON safety reading and the real illegibility
decision (both must be honest for ``gate()`` to stay byte-identical); and honest
defaults for the problem, reference, and maths-parse readings that later slices
fill in. There is **no** public ``normalize(text: str) -> str``.
"""

from __future__ import annotations

import unicodedata
import re
from dataclasses import dataclass
from typing import Protocol

from runtime.contracts import ModuleOutcome, Utterance, UtteranceSource, WordConfidence

from .observation import (
    AnaphorSpan,
    Authorization,
    DoubtCause,
    LegibilityCue,
    LegibilityReading,
    MathParse,
    PASSTHROUGH_PARSE,
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

# The demoted safety lexicon and the illegibility test still live in
# perception/gates.py; Intake reads them, gates.py reads nothing of Intake's
# (dependency direction is one-way).
from perception.gates import classify_safety, is_nonsense, is_safety
from runtime_flags import (
    DISAGREEMENT_CEILING,
    UTTERANCE_CONFIDENCE_FLOOR,
    WORD_CONFIDENCE_FLOOR,
)

_ZERO_WIDTH = dict.fromkeys(
    (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF), None
)
_WS_RE = re.compile(r"\s+")

# Stable id for the demoted lexicon net. NEVER the matched span.
_LEXICON_EVIDENCE_ID = "perception.gates._SAFETY_RE"
# Mirror perception.gates' character classes so the cue matches the is_nonsense
# decision exactly. The illegibility *decision* stays owned by is_nonsense; this
# only names which branch fired.
_ALNUM_RE = re.compile(r"[a-z0-9]", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z]{2,}", re.IGNORECASE)
_VOWEL_RE = re.compile(r"[aeiouy]", re.IGNORECASE)
_DIGIT_RE = re.compile(r"\d")
_RUN_RE = re.compile(r"^(.)\1{4,}$")


# ---------------------------------------------------------------------------
# Problem-detection regexes (migrated from InputProcessor.detect_student_problem,
# ticket 03).  The logic is UNCHANGED; the input is now the NFC-normalized text
# from normalize_text() instead of the raw utterance.
# ---------------------------------------------------------------------------
#: an '=' with a term on each side, at least one carrying a digit or lone variable.
_PROB_EQUATION_RE = re.compile(
    r"[0-9a-z\)\]]\s*(?:=|equals)\s*[-+]?\s*[0-9a-z\(\[]", re.IGNORECASE)

#: arithmetic operator between two operands; at least one side is a digit.
_PROB_EXPRESSION_RE = re.compile(
    r"(?:\d\s*[\^/*×÷]\s*[0-9a-z\(\[]|[0-9a-z\)\]]\s*[\^/*×÷]\s*\d)", re.IGNORECASE)

#: imperative "work this out" verbs, including "what is" / "how much".
_PROB_SOLVE_VERB_RE = re.compile(
    r"\b(solve|calculate|compute|evaluate|simplify|factorise|factorize|"
    r"expand|prove|derive|work out|figure out|what is|what's|how much|how many|"
    r"find (?:the |out )?)\b", re.IGNORECASE)

_PROB_DIGIT_RE = re.compile(r"\d")


# ---------------------------------------------------------------------------
# Reference / anaphora detection (ticket 04).
# Finds every anaphor token in the text and records its character span.
# The 12-word cutoff from the old is_anaphoric_followup is deliberately absent
# — it was unmeasured, had no owner, and is recorded in the concept-resolver
# handover as an artefact, not an inherited requirement.
# UNAUTHORIZED utterances get an empty ReferenceReading (compute-and-mark
# deferral): the learner may re-authorize via a repair selection, so running
# detection on an untrusted transcript is wasteful and misleading.
# ---------------------------------------------------------------------------
_ANAPHOR_RE = re.compile(
    r"\b(this|that|it|these|those|the\s+same|here)\b", re.IGNORECASE
)


def _reference(normalized: str, authorization: Authorization) -> ReferenceReading:
    """Detect anaphor spans in *normalized* text.

    Returns an empty ``ReferenceReading`` for UNAUTHORIZED utterances (deferred
    until the learner re-authorizes). For AUTHORIZED (and DISCARDED, which the
    gate already blocked), scans the normalized text with ``_ANAPHOR_RE`` and
    records each match as an ``AnaphorSpan`` with character-offset ``Span``.
    """
    if authorization is not Authorization.AUTHORIZED:
        return ReferenceReading()
    spans: list[AnaphorSpan] = []
    for match in _ANAPHOR_RE.finditer(normalized):
        spans.append(AnaphorSpan(
            text=match.group(0),
            span=Span(start=match.start(), end=match.end()),
        ))
    return ReferenceReading(anaphors=tuple(spans))


def detect_problem(normalized: str) -> ProblemReading:
    """Detect whether the normalized utterance presents a student problem instance.

    Runs on the NFC-normalized text from normalize_text().  Logic is unchanged
    from InputProcessor.detect_student_problem (ticket 03 migrates the call site
    from raw to normalized text and the return type from dict to ProblemReading).

    Two ways to qualify:

    * **equation/expression** — the utterance carries maths of its own.
      Sufficient on its own.
    * **solve verb + numerals** — an imperative plus concrete numbers.

    ``directive`` says the student addressed the tutor (an imperative verb or
    "what is …"), separating a student answer attempt from a fresh problem command.
    """
    s = (normalized or "").strip()
    if not s:
        return ProblemReading.absent()
    directive = bool(_PROB_SOLVE_VERB_RE.search(s))
    if _PROB_EQUATION_RE.search(s):
        return ProblemReading(is_problem=True, directive=directive, cue=ProblemCue.EQUATION)
    if _PROB_EXPRESSION_RE.search(s):
        return ProblemReading(is_problem=True, directive=directive, cue=ProblemCue.EXPRESSION)
    if directive and _PROB_DIGIT_RE.search(s):
        return ProblemReading(is_problem=True, directive=True, cue=ProblemCue.SOLVE_VERB_NUMERALS)
    return ProblemReading.absent()


def normalize_text(text: str) -> str:
    """The one published normalized form: NFC + zero-width strip + whitespace
    collapse. NFKC is deliberately absent — it destroyed ``x2``/vulgar fractions
    /U+2212. Any lossy folding a matcher needs stays private to that matcher."""
    folded = unicodedata.normalize("NFC", text or "")
    folded = folded.translate(_ZERO_WIDTH)
    folded = _WS_RE.sub(" ", folded).strip()
    return folded


class TranscriptPolicy(Protocol):
    """The injected authorization seam. A pure function of one Utterance, so
    tests reach every authorization branch with no cloud call and no audio."""

    def authorize(self, utterance: Utterance) -> Authorization: ...


@dataclass(frozen=True)
class ConfidenceFloorPolicy:
    """Default transcript policy: TYPED / REPAIR_SELECTION are authorized; a
    VOICE transcript is authorized iff its confidence is at or above the floor;
    ``confidence is None`` means *no gate* — it is authorized, not distrusted;
    a REPAIR_DISCARD is DISCARDED."""

    floor: float = 0.60

    def authorize(self, utterance: Utterance) -> Authorization:
        if utterance.source is UtteranceSource.REPAIR_DISCARD:
            return Authorization.DISCARDED
        if utterance.source in (
            UtteranceSource.TYPED,
            UtteranceSource.REPAIR_SELECTION,
        ):
            return Authorization.AUTHORIZED
        # VOICE
        if utterance.confidence is None:
            return Authorization.AUTHORIZED
        if utterance.confidence < self.floor:
            return Authorization.UNAUTHORIZED
        return Authorization.AUTHORIZED


@dataclass(frozen=True)
class UtteranceIntakeRequest:
    """Carries ``turn_input`` only — no session, no learner state."""

    turn_input: object


def _lexicon_safety(normalized: str) -> SafetySignals:
    """The demoted LEXICON reading, axis-only: ``{UNSPECIFIED_CONCERN}`` and
    never a caregiver/imminence flag, so the net can never fire a CRITICAL
    emergency script off a regex (SAFETY_ROUTE_TAXONOMY.md §8)."""
    if not is_safety(normalized):
        return SafetySignals(
            tripped=False,
            findings=frozenset(),
            caregiver_implicated=False,
            imminence_cue=False,
        )
    finding = SafetyFinding(
        safety_class=SafetyClass.UNSPECIFIED_CONCERN,
        source=SafetySource.LEXICON,
        evidence_id=_LEXICON_EVIDENCE_ID,
    )
    return SafetySignals(
        tripped=True,
        findings=frozenset({finding}),
        caregiver_implicated=False,
        imminence_cue=False,
    )


def _legibility(normalized: str) -> LegibilityReading:
    """The illegibility *decision* (slice 02): the five ``is_nonsense`` branches
    collapse into one boolean + a 6-way ``LegibilityCue``.  Thresholds are
    unchanged from the demoted ``is_nonsense``; the cue names which branch fired.

    Cue assignment:
        LEGIBLE            — is_nonsense returned False (passes through)
        EMPTY              — stripped text is empty
        NO_ALPHANUMERIC    — no [a-z0-9] character at all
        CHARACTER_RUN      — ≥5 repetitions of the same character
        KEYBOARD_MASH      — ≥4-char word(s), none contain a vowel, no digits
        NO_LEXICAL_CONTENT — none of the above; e.g. a bare single alpha letter
    """
    if not is_nonsense(normalized):
        return LegibilityReading(illegible=False, cue=LegibilityCue.LEGIBLE)
    stripped = (normalized or "").strip()
    if not stripped:
        cue = LegibilityCue.EMPTY
    elif not _ALNUM_RE.search(stripped):
        cue = LegibilityCue.NO_ALPHANUMERIC
    elif _RUN_RE.match(stripped):
        cue = LegibilityCue.CHARACTER_RUN
    else:
        words = _WORD_RE.findall(stripped)
        has_digit = bool(_DIGIT_RE.search(stripped))
        long_words = [w for w in words if len(w) >= 4]
        if not has_digit and long_words and all(
            not _VOWEL_RE.search(w) for w in long_words
        ):
            cue = LegibilityCue.KEYBOARD_MASH
        else:
            cue = LegibilityCue.NO_LEXICAL_CONTENT
    return LegibilityReading(illegible=True, cue=cue)


# ---------------------------------------------------------------------------
# Transcript doubt (ticket 05).
# Three signals, OR-ed: utterance confidence, min word confidence, and
# alternate disagreement.  The disagreement measure is computed over
# normalized_text, BEFORE authorization — it is a property of the acoustic
# evidence, not the trust decision.  Intake never compares confidence to a
# threshold; the three PROVISIONAL env-backed floors live in runtime_flags.
# ---------------------------------------------------------------------------

def _alternate_disagreement(alternates: tuple[str, ...]) -> float | None:
    """Position-wise character disagreement over normalized alternates.

    Returns None when fewer than 2 hypotheses are supplied.  The measure
    is the fraction of character positions where at least one alternate
    disagrees with the primary.  Normalization is applied so whitespace
    and case differences do not inflate the score.
    """
    if len(alternates) < 2:
        return None
    normed = [normalize_text(alt).casefold() for alt in alternates]
    primary = normed[0]
    if not primary:
        return 1.0
    max_len = max(len(n) for n in normed)
    disagreements = 0
    for pos in range(max_len):
        p_char = primary[pos] if pos < len(primary) else ""
        for alt in normed[1:]:
            a_char = alt[pos] if pos < len(alt) else ""
            if a_char != p_char:
                disagreements += 1
                break
    return round(disagreements / max_len, 4)


def _min_word_conf(word_confidences: tuple[WordConfidence, ...]) -> float | None:
    """Minimum word-level confidence; None when the producer reports nothing."""
    vals = [wc.confidence for wc in word_confidences if wc.confidence is not None]
    if not vals:
        return None
    return min(vals)


def _transcript_doubt(utterance: Utterance, normalized: str) -> TranscriptReading:
    """Compute the doubt verdict and maths parse for one utterance (tickets 05, 06).

    Signals:
        1. Utterance confidence < UTTERANCE_CONFIDENCE_FLOOR
        2. Min word confidence   < WORD_CONFIDENCE_FLOOR
        3. Alternate disagreement > DISAGREEMENT_CEILING
        4. Grammar refusal (AMBIGUOUS_PARSE or OUT_OF_GRAMMAR)

    ``doubtful`` is the OR of the available signals for VOICE utterances.
    ``repair_choices`` carries the top-3 distinct choices when doubtful.
    """
    from .grammar import parse_maths

    parse = parse_maths(normalized)

    # Non-VOICE sources: no acoustic doubt; record parse.
    if utterance.source is not UtteranceSource.VOICE:
        return TranscriptReading(doubtful=False, parse=parse)

    causes: list[DoubtCause] = []

    # Signal 1: utterance-level confidence.
    if (utterance.confidence is not None
            and utterance.confidence < UTTERANCE_CONFIDENCE_FLOOR):
        causes.append(DoubtCause.UTTERANCE_CONFIDENCE)

    # Signal 2: min word confidence.
    min_wc = _min_word_conf(utterance.word_confidences)
    if min_wc is not None and min_wc < WORD_CONFIDENCE_FLOOR:
        causes.append(DoubtCause.WORD_CONFIDENCE)

    # Signal 3: alternate disagreement (computed over normalized_text).
    disagreement = _alternate_disagreement(utterance.alternates)
    if disagreement is not None and disagreement > DISAGREEMENT_CEILING:
        causes.append(DoubtCause.ALTERNATE_DISAGREEMENT)

    # Signal 4: grammar parse refusals.
    if parse.outcome is ParseOutcome.REFUSE_AMBIGUOUS:
        causes.append(DoubtCause.AMBIGUOUS_PARSE)
    elif parse.outcome is ParseOutcome.REFUSE_OUT_OF_GRAMMAR:
        causes.append(DoubtCause.OUT_OF_GRAMMAR)

    doubtful = bool(causes)

    # repair_choices: top-3 distinct choices when doubtful.
    repair_choices: tuple[str, ...] = ()
    if doubtful:
        choices_list: list[str] = []
        if utterance.alternates:
            for alt in utterance.alternates:
                na = normalize_text(alt)
                if na and na not in choices_list:
                    choices_list.append(na)
        if parse.outcome is ParseOutcome.REFUSE_AMBIGUOUS and parse.competing:
            for c in parse.competing:
                if c and c not in choices_list:
                    choices_list.append(c)
        repair_choices = tuple(choices_list)[:3]

    return TranscriptReading(
        doubtful=doubtful,
        parse=parse,
        causes=tuple(causes),
        disagreement=disagreement,
        min_word_confidence=min_wc,
        repair_choices=repair_choices,
    )


class UtteranceIntake:
    """The one public door. ``observe`` is total, write-free, and pure of
    session; the transcript policy is a hard construction dependency."""

    def __init__(self, *, transcript_policy: TranscriptPolicy | None = None) -> None:
        self._transcript_policy = transcript_policy or ConfidenceFloorPolicy()

    def observe(
        self, request: UtteranceIntakeRequest
    ) -> ModuleOutcome[UtteranceObservation]:
        utterance: Utterance = request.turn_input.utterance
        if not isinstance(utterance, Utterance):
            raise TypeError("Utterance Intake requires a typed Utterance")
        normalized = normalize_text(utterance.text)
        authorization = self._transcript_policy.authorize(utterance)
        # Compute-and-mark deferral (ticket 03): problem detection runs only on
        # an authorized transcript.  An unauthorized turn carries the zero reading
        # (is_problem=False, directive=False) — not skipped, marked.
        if authorization is Authorization.AUTHORIZED:
            problem = detect_problem(normalized)
        else:
            problem = ProblemReading.absent()
        observation = UtteranceObservation(
            utterance=utterance,
            normalized_text=normalized,
            authorization=authorization,
            safety=_lexicon_safety(normalized),
            legibility=_legibility(normalized),
            transcript=_transcript_doubt(utterance, normalized),
            problem=problem,
            reference=_reference(normalized, authorization),
        )
        return ModuleOutcome(value=observation)
