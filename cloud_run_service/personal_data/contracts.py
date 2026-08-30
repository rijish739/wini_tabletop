"""What the personal-data model is allowed to say, as a type.

``PersonalDataVerdict`` is the only thing the detector produces, and §4 makes it an
unusual object in this tree: **it is identifier-bearing**. The verbatim substring the
model named IS the child's phone number. So the rules below are not stylistic —

    The verdict object is consumed by the redactor and dropped. It is never
    serialized, never logged, never a sink payload, and never reaches
    ``debug_logger``. Only class labels survive it.

``IdentifierFinding.__repr__`` masks ``value``; there is no ``asdict`` path and no
``__str__`` that reveals it. ``PersonalDataVerdict.as_record()`` deliberately does not
exist — compare ``child_safety.ModelSafetyVerdict.as_record``, which is safe there
because a safety verdict carries only class labels. Copying that method here would be
the single most likely way this contract gets broken.

Notice also what this module cannot reach: nothing here imports ``SafetyClass``,
``SafetySeverity`` or anything from ``child_safety``. Personal data is **off the
safety axis entirely** (§1) — it never produces a ``SafetyClass``, never sets
``safety_alert``, and never pauses the lesson. A module that cannot name those types
cannot drift onto that axis.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class IdentifierClass(str, Enum):
    """§3. Nine members; ``OTHER_IDENTIFIER`` is the honest residual and is always
    available. A class never enters this enum until it clears both §12 floors — a
    known-but-unmet class is recorded in the eval report and the backlog, never as a
    silent member that reports zero."""

    NAME = "NAME"
    SCHOOL = "SCHOOL"
    ADDRESS = "ADDRESS"
    LIVE_LOCATION = "LIVE_LOCATION"
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    CREDENTIAL = "CREDENTIAL"
    GOVERNMENT_ID = "GOVERNMENT_ID"
    OTHER_IDENTIFIER = "OTHER_IDENTIFIER"


class VerdictStatus(str, Enum):
    """§15. Two states, and the distinction is the whole of §8.

    ``UNAVAILABLE`` is emphatically NOT "no identifiers found". Today's code cannot
    tell those apart at all (§16); this enum is what makes the difference
    representable, and the fail-closed sinks are what make it matter.
    """

    LANDED = "LANDED"            # the model answered within its envelope
    UNAVAILABLE = "UNAVAILABLE"  # timeout, retry exhausted, or outage


@dataclass(frozen=True)
class IdentifierFinding:
    """One identifier the model named, as a verbatim substring of ``normalized_text``.

    **IDENTIFIER-BEARING.** ``value`` is the child's actual phone number / address /
    name. §4 permits it to exist only in memory, only for the turn, only to be handed
    to ``redact``.

    Why a verbatim substring rather than a character span or a rewrite (§4): spans
    leak no value, but LLMs are unreliable at exact offset arithmetic and a wrong
    offset redacts the wrong half of a sentence; a model-returned *rewrite* hands the
    model a licence to alter the arithmetic, which is precisely the utility failure
    MathEd-PII measures. A verbatim substring gives deterministic, auditable
    ``str.replace`` redaction — and means there is **no threshold and no shape rule
    anywhere in this system** (§5).
    """

    identifier_class: IdentifierClass
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "identifier_class", IdentifierClass(self.identifier_class)
        )
        if not self.value:
            raise ValueError("an IdentifierFinding names a non-empty substring")

    def __repr__(self) -> str:
        """Masked. A traceback, a `print`, a debugger frame dump and an f-string are
        all sinks, and none of them consulted this contract first."""
        return (
            f"IdentifierFinding(identifier_class={self.identifier_class.value}, "
            f"value=<redacted len={len(self.value)}>)"
        )

    __str__ = __repr__


@dataclass(frozen=True)
class PersonalDataVerdict:
    """One personal-data answer for one utterance.

    Total: the detector always returns one, and a failure is a verdict object that
    says it is a failure. ``findings`` is **always empty when UNAVAILABLE** — that
    invariant is what stops "we never looked" from reading as "nothing was there".
    """

    utterance_id: str
    status: VerdictStatus
    findings: frozenset[IdentifierFinding] = frozenset()
    model_id: str = ""
    model_pinned: bool = False
    prompt_version: str = ""
    schema_version: str = ""
    latency_ms: int | None = None
    attempts: int = 0
    failure_reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", VerdictStatus(self.status))
        object.__setattr__(self, "findings", frozenset(self.findings))
        if not self.utterance_id:
            raise ValueError("PersonalDataVerdict requires an utterance_id")
        if self.status is VerdictStatus.UNAVAILABLE and self.findings:
            raise ValueError(
                "an unavailable personal-data call carries no findings — "
                "it carries no verdict at all"
            )

    def __repr__(self) -> str:
        """Masked, for the same reason ``IdentifierFinding.__repr__`` is: the default
        dataclass repr would print every finding's ``value`` verbatim."""
        return (
            f"PersonalDataVerdict(utterance_id={self.utterance_id!r}, "
            f"status={self.status.value}, n_findings={len(self.findings)}, "
            f"classes={sorted(c.value for c in self.classes)})"
        )

    __str__ = __repr__

    @property
    def landed(self) -> bool:
        return self.status is VerdictStatus.LANDED

    @property
    def classes(self) -> tuple[IdentifierClass, ...]:
        """The labels — the ONLY part of this verdict that may be written anywhere
        (§9). Sorted and de-duplicated; un-indexed, like the placeholders (§6.1)."""
        return tuple(sorted({f.identifier_class for f in self.findings},
                            key=lambda c: c.value))

    @classmethod
    def unavailable(
        cls,
        *,
        utterance_id: str,
        model_id: str = "",
        model_pinned: bool = False,
        prompt_version: str = "",
        schema_version: str = "",
        attempts: int = 0,
        failure_reason: str = "",
        latency_ms: int | None = None,
    ) -> "PersonalDataVerdict":
        """The model did not answer. The only way to build a non-answer, and the
        reason "no findings" can never be mistaken for "nothing was disclosed"."""
        return cls(
            utterance_id=utterance_id,
            status=VerdictStatus.UNAVAILABLE,
            findings=frozenset(),
            model_id=model_id,
            model_pinned=model_pinned,
            prompt_version=prompt_version,
            schema_version=schema_version,
            attempts=attempts,
            failure_reason=failure_reason,
            latency_ms=latency_ms,
        )


@dataclass(frozen=True)
class PersonalDataContext:
    """Exactly what the session is allowed to hand the prompt (§14).

    ``session["context"][-2:]`` — one preceding exchange, the same window the safety
    call sees. It is the only thing that catches the split disclosure: the tutor asks
    something and the child answers *"it's 98765"*, which without context is
    indistinguishable from an answer and **must** be left alone.

    The type exists so §14's second rule is enforced at the call site rather than
    remembered at review time:

        Findings may only name substrings of the CURRENT utterance. Context is
        evidence, never a redaction target.
    """

    recent_context: tuple = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "recent_context", tuple(self.recent_context))
        if len(self.recent_context) > 2:
            raise ValueError(
                "the personal-data prompt sees session['context'][-2:] only"
            )
