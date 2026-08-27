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

from runtime.contracts import ModuleOutcome, Utterance, UtteranceSource

from .observation import (
    Authorization,
    LegibilityCue,
    LegibilityReading,
    PASSTHROUGH_PARSE,
    ProblemReading,
    ReferenceReading,
    SafetyClass,
    SafetyFinding,
    SafetySignals,
    SafetySource,
    TranscriptReading,
    UtteranceObservation,
)

# The demoted safety lexicon and the illegibility test still live in
# perception/gates.py; Intake reads them, gates.py reads nothing of Intake's
# (dependency direction is one-way).
from perception.gates import classify_safety, is_nonsense, is_safety

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
    """The illegibility *decision* (thresholds unchanged from the demoted
    ``is_nonsense``). The 6-way cue *report* split is ticket 02's; here the cue
    is a coarse LEGIBLE / not-LEGIBLE distinction, refined by later slices."""
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
        observation = UtteranceObservation(
            utterance=utterance,
            normalized_text=normalized,
            authorization=authorization,
            safety=_lexicon_safety(normalized),
            legibility=_legibility(normalized),
            transcript=TranscriptReading(doubtful=False, parse=PASSTHROUGH_PARSE),
            problem=ProblemReading(is_problem=False, directive=False),
            reference=ReferenceReading(),
        )
        return ModuleOutcome(value=observation)
