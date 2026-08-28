"""Shared golden-fixture conformance harness.

Any ``observe()`` implementation must pass ``run_fixture``; any consumer imports
``stub_observation`` to build a stub observation from hand values rather than
hand-rolling an observation shape. Later slices add fixture rows here; nobody
hand-rolls a shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from runtime.contracts import Utterance, UtteranceProvenance, UtteranceSource

from utterance_intake import (
    Authorization,
    ConfidenceFloorPolicy,
    LegibilityCue,
    ParseOutcome,
    UtteranceIntake,
    UtteranceIntakeRequest,
)
from utterance_intake.observation import (
    LegibilityReading,
    PASSTHROUGH_PARSE,
    ProblemReading,
    ReferenceReading,
    SafetySignals,
    SafetySource,
    TranscriptReading,
    UtteranceObservation,
)

FIXTURES = Path(__file__).with_name("fixtures")


def load_rows(name: str) -> list[dict]:
    path = FIXTURES / name
    rows: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_utterance(spec: dict) -> Utterance:
    source = UtteranceSource(spec.get("source", "TYPED"))
    provenance = UtteranceProvenance(
        utterance_id=spec.get("utterance_id", "u_fixture"),
        captured_at=spec.get("captured_at", "2026-08-27T00:00:00+00:00"),
        recognizer=spec.get("recognizer"),
        repairs=spec.get("repairs"),
        selected_alternate_index=spec.get("selected_alternate_index"),
    )
    return Utterance(
        text=spec.get("text", ""),
        source=source,
        provenance=provenance,
        confidence=spec.get("confidence"),
        alternates=tuple(spec.get("alternates", ())),
    )


def run_observe(utterance: Utterance, intake: UtteranceIntake | None = None):
    intake = intake or UtteranceIntake(transcript_policy=ConfidenceFloorPolicy())
    turn_input = SimpleNamespace(utterance=utterance)
    return intake.observe(UtteranceIntakeRequest(turn_input=turn_input)).value


def stub_observation(
    *,
    text: str = "",
    normalized_text: str | None = None,
    authorization: Authorization = Authorization.AUTHORIZED,
    safety_tripped: bool = False,
    illegible: bool = False,
    legibility_cue: LegibilityCue | None = None,
    source: UtteranceSource = UtteranceSource.TYPED,
) -> UtteranceObservation:
    """Build a stub observation from hand values — the one place a consumer's
    tests get an observation shape from."""
    from utterance_intake.intake import _legibility, _lexicon_safety, normalize_text

    normalized = normalize_text(text) if normalized_text is None else normalized_text
    if safety_tripped:
        safety = _lexicon_safety("i want to kill myself")
    else:
        safety = SafetySignals(
            tripped=False,
            findings=frozenset(),
            caregiver_implicated=False,
            imminence_cue=False,
            source=SafetySource.LEXICON,
        )
    if legibility_cue is not None:
        legibility = LegibilityReading(
            illegible=legibility_cue is not LegibilityCue.LEGIBLE, cue=legibility_cue
        )
    elif illegible:
        computed = _legibility(normalized)
        legibility = computed if computed.illegible else (
            LegibilityReading(illegible=True, cue=LegibilityCue.NO_LEXICAL_CONTENT)
        )
    else:
        legibility = LegibilityReading(illegible=False, cue=LegibilityCue.LEGIBLE)
    provenance = UtteranceProvenance(
        utterance_id="u_stub", captured_at="2026-08-27T00:00:00+00:00"
    )
    utterance = Utterance(text=text, source=source, provenance=provenance)
    return UtteranceObservation(
        utterance=utterance,
        normalized_text=normalized,
        authorization=authorization,
        safety=safety,
        legibility=legibility,
        transcript=TranscriptReading(doubtful=False, parse=PASSTHROUGH_PARSE),
        problem=ProblemReading(is_problem=False, directive=False),
        reference=ReferenceReading(),
    )


def check_expected(observation, expected: dict) -> list[str]:
    """Return a list of mismatch descriptions ([] means the row conforms)."""
    fails: list[str] = []

    def eq(name, got, want):
        if got != want:
            fails.append(f"{name}: got {got!r}, want {want!r}")

    eq("normalized_text", observation.normalized_text, expected["normalized_text"])
    eq("authorization", observation.authorization.value, expected["authorization"])
    eq("safety_tripped", observation.safety.tripped, expected["safety_tripped"])
    eq("illegible", observation.legibility.illegible, expected["illegible"])
    if "legibility_cue" in expected:
        eq("legibility_cue", observation.legibility.cue.value, expected["legibility_cue"])
    eq("problem_is_problem", observation.problem.is_problem, expected["problem_is_problem"])
    if "problem_cue" in expected:
        got_cue = observation.problem.cue.value if observation.problem.cue is not None else None
        eq("problem_cue", got_cue, expected["problem_cue"])
    if "problem_directive" in expected:
        eq("problem_directive", observation.problem.directive, expected["problem_directive"])
    eq("parse_outcome", observation.transcript.parse.outcome.value, expected["parse_outcome"])
    eq("has_anaphora", observation.reference.has_anaphora, expected["has_anaphora"])
    return fails


__all__ = [
    "Authorization",
    "LegibilityCue",
    "ParseOutcome",
    "build_utterance",
    "check_expected",
    "load_rows",
    "run_observe",
    "stub_observation",
]
