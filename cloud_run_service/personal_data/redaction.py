"""The redaction primitive and the types the sinks accept (§6, §8, §15).

Read §6.2 first, because it is the whole design:

    Sinks accept ``RedactedText`` and **have no ``str`` overload**. ``RedactedText``
    is constructible only by the redactor, from ``normalized_text`` plus a landed
    verdict.

The evidence that discipline alone fails is already in this tree: ``_log_nonlearning``
redacted the utterance on the safety branch and not on the ordinary one, and
``debug_logger._fan_out`` serialized whatever it was handed to an SSE stream *and* to
disk. Each is a five-line log statement written by someone not thinking about §11, and
the next one will be too. So the obligation is carried by a type, and the constructor
is guarded by a module-private token — ``RedactedText(text="anything")`` raises.

Three factories, and the difference between them is §8:

* ``redact``          — §15's exact signature. Returns ``None`` when a persisting
                        sink must write **no transcript at all**. Fail CLOSED.
* ``turn_redaction``  — the one call the Turn Coordinator makes. Returns an
                        identifier-FREE ``TurnRedaction`` that is safe to thread
                        through the whole turn.
* ``for_generation``  — total. Generation cannot run without the text, so it fails
                        OPEN (§8) and the anti-echo obligation falls back to a prompt
                        instruction for that turn. The fallback is *named* here rather
                        than happening silently at a call site.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import IdentifierClass, PersonalDataVerdict, VerdictStatus

#: The module-private construction token. Nothing outside this file holds it, so
#: `RedactedText` cannot be built from a bare string anywhere else in the tree — the
#: type reduced back to discipline is exactly what §13 refuses.
_TOKEN = object()

#: §16's stamps. `""` is the ordinary case: a verdict landed and redaction verified.
STAMP_NONE = ""
STAMP_UNAVAILABLE = "privacy_unavailable"       # §9.2's convention, shared with 07
STAMP_INCOMPLETE = "redaction_incomplete"       # §4: a named substring was not found


def placeholder(identifier_class: IdentifierClass) -> str:
    """§6.1: a typed, uppercase, **un-indexed, digit-free** placeholder.

    Presidio's ``replace`` operator (``<ENTITY_TYPE>``) is the prior art, and a typed
    token is skippable by a maths parser where a blank or ``****`` re-introduces an
    ambiguous token into the arithmetic.

    * **Un-indexed.** Two names in one utterance both become ``<NAME>``. The unit is
      one short spoken turn, distinguishing them has no consumer, and an index is
      exactly the field someone later makes *stable across turns* — at which point it
      is a persistent pseudo-identifier, COPPA class 7, reintroduced by a helpful
      refactor.
    * **No digits, ever.** ``math_grade.normalize`` must never be able to parse a
      placeholder as a number. Asserted in the test suite over the whole enum, not
      just the classes that happen to exist today.
    """
    return f"<{IdentifierClass(identifier_class).value}>"


@dataclass(frozen=True)
class RedactedText:
    """Learner text with every named identifier replaced, plus the class labels.

    The **only** thing a persisting sink may write. Its existence is the proof that a
    verdict landed and that every substring the model named was found and removed —
    which is why it cannot be constructed without one.
    """

    #: Structural marker for ``debug_logger``, which is stdlib-only by its own module
    #: rule and must not import this package (``config`` pulls ``dotenv``, and a debug
    #: sink that can fail to import is a debug sink that breaks a turn). Duck-typing on
    #: this attribute is what lets ``_fan_out`` recognise a redacted string without a
    #: dependency edge. Do not put it on ``GenerationText``: that type may legitimately
    #: hold unredacted text, and debug is a persisting sink.
    redacted_text_marker = True

    text: str
    classes: tuple[IdentifierClass, ...] = ()
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _TOKEN:
            raise TypeError(
                "RedactedText is constructed only by personal_data.redact() from a "
                "landed verdict. A sink that needs one and has none must write no "
                "transcript (PERSONAL_DATA_CONTRACT.md §6.2, §8)."
            )
        object.__setattr__(
            self, "classes", tuple(IdentifierClass(c) for c in self.classes)
        )

    def __repr__(self) -> str:
        return (
            f"RedactedText(len={len(self.text)}, "
            f"classes={[c.value for c in self.classes]})"
        )

    def __str__(self) -> str:
        """The redacted text itself. Safe by construction — every named identifier is
        already a placeholder — and this is what a sink writes."""
        return self.text

    @property
    def class_values(self) -> list[str]:
        """The sink payload (§9): class labels only, never a value."""
        return [c.value for c in self.classes]


@dataclass(frozen=True)
class GenerationText:
    """What the B5 generation prompt is built from (§6.3, §8).

    Generation is the only sink that can **echo the identifier back to the child**,
    and it is also the only sink that cannot fail closed — it cannot run without the
    text. So this type carries both possibilities and says which it is:

    * ``redaction_confirmed=True``  — built from a ``RedactedText``; the generator
      never sees the identifier, and §11's obligation 2 is structural.
    * ``redaction_confirmed=False`` — §8's deliberate concession. The verdict was
      late or absent, generation proceeds on unredacted text, and
      ``anti_echo_required`` is True so the prompt carries the instruction instead.

    The boolean exists so the concession is visible at the prompt-building site
    instead of being a silent `or raw_text`.
    """

    text: str
    classes: tuple[IdentifierClass, ...] = ()
    redaction_confirmed: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _TOKEN:
            raise TypeError(
                "GenerationText is constructed only by personal_data.for_generation()"
            )
        object.__setattr__(
            self, "classes", tuple(IdentifierClass(c) for c in self.classes)
        )

    def __repr__(self) -> str:
        return (
            f"GenerationText(len={len(self.text)}, "
            f"redaction_confirmed={self.redaction_confirmed})"
        )

    def __str__(self) -> str:
        return self.text

    @property
    def anti_echo_required(self) -> bool:
        """True exactly when the generator may see an identifier, so the prompt must
        be told not to repeat it. False on the ordinary path, where the instruction
        would be noise."""
        return not self.redaction_confirmed


@dataclass(frozen=True)
class TurnRedaction:
    """The turn-scoped, **identifier-free** product of the personal-data path.

    This is what crosses the seams — Interaction Control, the legacy adapter, the
    sinks. It carries a placeholder-substituted string and class labels and nothing
    else; the ``PersonalDataVerdict`` that produced it is dropped at the redactor and
    never travels (§4).

    ``redacted is None`` is the fail-closed state and means exactly one thing to every
    persisting sink: **write the structured fields and no transcript.**
    """

    status: VerdictStatus
    classes: tuple[IdentifierClass, ...] = ()
    redacted: RedactedText | None = None
    stamp: str = STAMP_NONE
    missed: tuple[IdentifierClass, ...] = ()   # classes whose substring was not found

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", VerdictStatus(self.status))
        object.__setattr__(
            self, "classes", tuple(IdentifierClass(c) for c in self.classes)
        )
        object.__setattr__(
            self, "missed", tuple(IdentifierClass(c) for c in self.missed)
        )
        if self.redacted is not None and self.status is not VerdictStatus.LANDED:
            raise ValueError("a RedactedText requires a landed verdict")

    @property
    def class_values(self) -> list[str]:
        return [c.value for c in self.classes]

    @property
    def found(self) -> bool:
        """True when the model named at least one identifier. §11's scripted line
        fires on this — there is no high-precision second source to gate on (§2)."""
        return bool(self.classes)

    def analytics(self) -> dict:
        """§9: the turn's ordinary analytics row carries ``privacy_classes`` — class
        labels only — and nothing else. No identifier value, no count of characters,
        no span, and (§9) **no separate privacy-event store** behind it."""
        row: dict = {"privacy_classes": self.class_values}
        if self.stamp:
            row["privacy"] = self.stamp
        return row

    @classmethod
    def unavailable(cls, stamp: str = STAMP_UNAVAILABLE) -> "TurnRedaction":
        """No verdict. Every persisting sink writes no transcript; generation falls
        open. This is also the honest state when **no detector is wired at all**,
        which is why the stamp is a parameter."""
        return cls(status=VerdictStatus.UNAVAILABLE, stamp=stamp)


# ---------------------------------------------------------------------------
# The factories
# ---------------------------------------------------------------------------
def redact(
    normalized_text: str, verdict: PersonalDataVerdict
) -> RedactedText | None:
    """The ONLY constructor of ``RedactedText`` (§15).

    Returns ``None`` when the sink must write no transcript at all:

    * ``verdict.status`` is ``UNAVAILABLE`` (§8 fail-closed), or
    * a finding's value is not found in ``normalized_text`` (§4 fail-closed) — the
      redaction cannot be verified, and we never persist a transcript we could not
      confirm we cleaned.

    Substitution is plain ``str.replace`` on the verbatim substring the model named,
    longest first so a shorter finding nested inside a longer one cannot corrupt it.
    There is no threshold and no shape rule: a bare digit run is redacted if and only
    if the model, having read the whole utterance, asserted that specific run is a
    phone number. **The maths is protected by construction** (§5).
    """
    if verdict.status is not VerdictStatus.LANDED:
        return None
    # Check EVERY finding against the original ``normalized_text`` before substituting
    # any of them. §4's rule is "not found in normalized_text", and checking against a
    # partially-substituted string would fail the turn closed over a miss this function
    # created itself: "9876543210" and "543210" can both be named, and once the long one
    # is a placeholder the short one is genuinely absent. Validate first, then replace.
    if any(finding.value not in normalized_text for finding in verdict.findings):
        # Fail closed. Not a warning, not a best-effort partial redaction: a
        # partially-cleaned transcript is one we cannot claim to have cleaned.
        return None
    text = normalized_text
    # Longest first, so a shorter finding nested inside a longer one cannot corrupt it
    # — and so a nested finding is removed by the enclosing substitution rather than
    # leaving "<PHONE>" fragments behind.
    for finding in sorted(
        verdict.findings, key=lambda f: len(f.value), reverse=True
    ):
        text = text.replace(finding.value, placeholder(finding.identifier_class))
    return RedactedText(text=text, classes=verdict.classes, _token=_TOKEN)


def turn_redaction(
    normalized_text: str, verdict: PersonalDataVerdict | None
) -> TurnRedaction:
    """The Turn Coordinator's one call. Total, and identifier-free on the way out.

    ``verdict is None`` means no detector was wired for this turn. That is stamped
    ``privacy_unavailable`` like an outage, because from every sink's point of view it
    is one — but see ``personal_data/__init__``: a system with no detector wired logs
    no transcripts at all, which is correct per §8 and is a deployment fact worth
    knowing rather than a silent degradation.
    """
    if verdict is None or verdict.status is not VerdictStatus.LANDED:
        return TurnRedaction.unavailable()
    redacted = redact(normalized_text, verdict)
    if redacted is None:
        # A landed verdict whose substrings could not be matched. The finding's
        # CLASS is still recorded (§4) — that is a real observation about the turn —
        # but no transcript reaches any sink.
        return TurnRedaction(
            status=VerdictStatus.LANDED,
            classes=verdict.classes,
            redacted=None,
            stamp=STAMP_INCOMPLETE,
            missed=tuple(
                f.identifier_class
                for f in sorted(verdict.findings, key=lambda f: f.identifier_class.value)
                if f.value not in normalized_text
            ),
        )
    return TurnRedaction(
        status=VerdictStatus.LANDED,
        classes=verdict.classes,
        redacted=redacted,
        stamp=STAMP_NONE,
    )


def for_generation(
    normalized_text: str, redaction: TurnRedaction | None
) -> GenerationText:
    """Build the generation prompt's text. **Total — generation fails OPEN** (§8).

    A late or absent verdict means generation proceeds on unredacted text and the
    anti-echo obligation falls back to a prompt instruction for that turn. §8 accepts
    this deliberately: echoing a number back to the child who just said it aloud is a
    breach with near-zero marginal harm, while *persistence* is the harm §11 is
    actually about — and the persisting sinks fail closed in the same moment.
    """
    if redaction is not None and redaction.redacted is not None:
        return GenerationText(
            text=redaction.redacted.text,
            classes=redaction.redacted.classes,
            redaction_confirmed=True,
            _token=_TOKEN,
        )
    return GenerationText(
        text=normalized_text,
        classes=(),
        redaction_confirmed=False,
        _token=_TOKEN,
    )
