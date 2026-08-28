"""What the safety model is allowed to say, as a type.

``ModelSafetyVerdict`` is the ONLY thing ``child_safety`` produces. Read its
``__post_init__``: severity is absent by construction, ``caregiver_implicated`` is
absent by construction, and a failed call is unconstructable as a negative verdict.

Notice what this module does not import: ``SafetySeverity`` lives in
``interaction_control.safety_composition`` and nothing here can reach it. That is
not tidiness — it is SAFETY_ROUTE_TAXONOMY.md §5's "severity is derived at exactly
one site" made structural. A detector that cannot name the type cannot write it.

Classes and sources are reused from ``utterance_intake.observation`` so there is
exactly one ``SafetyClass`` enum in the tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from utterance_intake.observation import SafetyClass, SafetyFinding, SafetySource


class SafetyModelStatus(str, Enum):
    """Why the verdict looks the way it does.

    ``OK`` is the only status that carries a real judgement. Everything else means
    *the model did not answer*, which is emphatically NOT the same as "no concern"
    (§7.3: empty text is classified as a failure, never as a negative verdict).
    """

    OK = "ok"
    TIMEOUT = "timeout"       # the 5s envelope expired
    ERROR = "error"           # transport, malformed, or empty response
    LATE = "late"             # arrived after the envelope; unions in, still escalates

    @property
    def answered(self) -> bool:
        return self in (SafetyModelStatus.OK, SafetyModelStatus.LATE)


@dataclass(frozen=True)
class ModelSafetyVerdict:
    """One safety-model answer for one utterance.

    The four evidence flags are EVIDENCE the model observed, not severity. §5 reads
    them at the single derivation site; the model supplies them and never sees what
    they are used for. This is what "a model can raise severity through evidence it
    supplies, but can never set severity directly" (§6.5) looks like in a type.
    """

    tripped: bool
    classes: frozenset[SafetyClass]
    imminence_cue: bool
    status: SafetyModelStatus
    model_id: str                       # as sent to Vertex, pinned when configured
    model_pinned: bool
    prompt_version: str
    schema_version: str
    named_means: bool = False           # SELF_HARM: a method/means was named
    weapon: bool = False                # THREAT_BY_CHILD: a weapon was named
    arranged_meeting: bool = False      # UNSAFE_CONTACT: a meeting was arranged
    latency_ms: int | None = None
    attempts: int = 0
    failure_reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", SafetyModelStatus(self.status))
        object.__setattr__(
            self, "classes", frozenset(SafetyClass(c) for c in self.classes)
        )
        if self.tripped != bool(self.classes):
            raise ValueError("ModelSafetyVerdict.tripped must equal bool(classes)")
        if not self.status.answered and self.tripped:
            raise ValueError(
                "a failed safety call cannot carry a positive verdict — "
                "it carries no verdict at all"
            )
        if not self.tripped and (
            self.imminence_cue
            or self.named_means
            or self.weapon
            or self.arranged_meeting
        ):
            raise ValueError("evidence flags require a tripped axis")
        if not self.model_id:
            raise ValueError("ModelSafetyVerdict requires the model id it came from")

    @property
    def available(self) -> bool:
        """True when the model actually answered. The composition step reads this to
        decide whether the degraded net contributes (§6.3)."""
        return self.status.answered

    def findings(self) -> frozenset[SafetyFinding]:
        """The verdict as add-only findings. ``evidence_id`` is the prompt/schema
        version (§15) — never the utterance, never a matched span."""
        evidence_id = f"{self.prompt_version}/{self.schema_version}"
        return frozenset(
            SafetyFinding(
                safety_class=safety_class,
                source=SafetySource.MODEL,
                evidence_id=evidence_id,
            )
            for safety_class in self.classes
        )

    def as_record(self) -> dict:
        """The raw structured verdict for the case record (§14.1): structured, so it
        stays redaction-safe; never free text, never the utterance."""
        return {
            "tripped": self.tripped,
            "classes": sorted(c.value for c in self.classes),
            "imminence_cue": self.imminence_cue,
            "named_means": self.named_means,
            "weapon": self.weapon,
            "arranged_meeting": self.arranged_meeting,
            "status": self.status.value,
            "model_id": self.model_id,
            "model_pinned": self.model_pinned,
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
            "latency_ms": self.latency_ms,
            "attempts": self.attempts,
            "failure_reason": self.failure_reason,
        }

    @classmethod
    def unavailable(
        cls,
        *,
        status: SafetyModelStatus,
        model_id: str,
        model_pinned: bool,
        prompt_version: str,
        schema_version: str,
        attempts: int = 0,
        failure_reason: str = "",
        latency_ms: int | None = None,
    ) -> "ModelSafetyVerdict":
        """The model did not answer. This is the ONLY way to build a non-answer, and
        it is why "no classes" can never be mistaken for "no concern"."""
        if SafetyModelStatus(status).answered:
            raise ValueError("unavailable() builds failures only")
        return cls(
            tripped=False,
            classes=frozenset(),
            imminence_cue=False,
            status=status,
            model_id=model_id,
            model_pinned=model_pinned,
            prompt_version=prompt_version,
            schema_version=schema_version,
            attempts=attempts,
            failure_reason=failure_reason,
            latency_ms=latency_ms,
        )


@dataclass(frozen=True)
class SafetySessionSummary:
    """Exactly what the session is allowed to hand the prompt (§7.5).

    A count and a max severity. Never classes, never text. The type exists so the
    rule is enforced at the call site instead of remembered at review time.
    """

    prior_safety_findings: int = 0
    prior_max_severity: str | None = None
    recent_context: tuple = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "prior_safety_findings", int(self.prior_safety_findings)
        )
        object.__setattr__(self, "recent_context", tuple(self.recent_context))
        if self.prior_max_severity not in (None, "ELEVATED", "CRITICAL"):
            raise ValueError("prior_max_severity is ELEVATED, CRITICAL, or None")
        if len(self.recent_context) > 2:
            raise ValueError("the safety prompt sees session['context'][-2:] only")
