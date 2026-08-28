"""The one shared safety-verdict composition entry point.

Both Interaction Control sites that branch on ``safety_alert`` compose the verdict
here, so two call sites can never compose it differently. The invariant, retargeted
and stated as one sentence: **nothing may ever remove a finding, whatever made it.**
Composition is union-only and monotone — it can only add.

``docs/architecture/SAFETY_ROUTE_TAXONOMY.md`` §5 and §6 are normative. This module
is also **the only place in the tree that may write a severity** (§5, §6.5). That is
enforced structurally as well as by convention: ``SafetySeverity`` is defined here
and ``child_safety/`` cannot import it without importing its own consumer.

The three sources, all add-only (§6):

1. On a healthy turn the **safety model's verdict is the verdict** — classes,
   imminence, axis.
2. Perception's ``safety`` boolean unions in as a free add-only net. Axis only,
   never a class.
3. The degraded net (the demoted lexicon) contributes **only** when the model call
   failed or timed out.

Frozen from day one (ticket 01): ``compose_safety_alert``'s signature has not
changed and **its legacy-20 regression test was not edited at the cutover** — the
thing under it changed. It now delegates to ``compose_safety_verdict``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from utterance_intake.observation import SafetyClass, SafetyFinding, SafetySource


class SafetySeverity(str, Enum):
    """Two values, and severity does NOT decide whether we pause (§5).

    Docx §12 pauses tutoring and runs the direct safety check for *all* of
    self-harm, violence, abuse, coercion and immediate danger. Severity selects only
    the hand-off queue and the resource shape: ``ELEVATED`` -> standard safeguarding
    queue and Tele-MANAS-shaped support; ``CRITICAL`` -> high-priority staffed queue
    and an emergency resource.
    """

    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return 2 if self is SafetySeverity.CRITICAL else 1


#: Evidence id for perception's free add-only bit. Never a span, never the text.
PERCEPTION_EVIDENCE_ID = "perception.route.safety_alert"

#: What the composition reports when no detector was wired into the turn at all.
#:
#: A DELIBERATE ADDITION to §15's enumeration, which lists
#: ``"ok" | "timeout" | "error" | "late"`` — four values that between them assume a
#: call was always made. "No detector was wired" is a genuinely different state
#: from "a call was made and failed", and it is real for as long as the legacy
#: `tutor_loop` path exists. Reusing ``"error"`` for it would assert a failure that
#: never happened, which §12 forbids more strongly than §15 forbids a fifth value.
#: `_stamps` reads this to decide between `safety_model_unavailable` (a real
#: outage) and `no_safety_detector` (nothing ran).
MODEL_STATUS_UNAVAILABLE = "unavailable"


def _max_severity(
    left: SafetySeverity | None, right: SafetySeverity | None
) -> SafetySeverity | None:
    if left is None:
        return right
    if right is None:
        return left
    return left if left.rank >= right.rank else right


def _coerce_severity(value: Any) -> SafetySeverity | None:
    if value is None or value == "" or value == "none":
        return None
    return SafetySeverity(value)


def derive_severity(
    *,
    classes: frozenset[SafetyClass],
    imminence_cue: bool = False,
    named_means: bool = False,
    weapon: bool = False,
    arranged_meeting: bool = False,
) -> SafetySeverity | None:
    """§5, and the only implementation of it.

        CRITICAL  iff  imminence_cue AND any class
                  or   SELF_HARM        AND a named means/method
                  or   THREAT_BY_CHILD  AND a weapon
                  or   UNSAFE_CONTACT   AND an arranged meeting
        ELEVATED  otherwise

    Two consequences, both deliberate and both enumerated in the taxonomy's §11
    exception list **before** implementation, so neither is discovered at test time:

    * **Bare ideation is ELEVATED, not CRITICAL.** ``i want to die`` with no means
      and no imminence reads an emergency number at a child who did not need one,
      which docx §15 names as a failure and which is clinically wrong. The §12
      direct question is the disambiguator and it runs at *both* severities.
    * **Ongoing abuse without an imminence cue is ELEVATED.** It needs a
      safeguarding queue, not an emergency dispatch.
    """
    if not classes:
        return None
    if imminence_cue:
        return SafetySeverity.CRITICAL
    if named_means and SafetyClass.SELF_HARM in classes:
        return SafetySeverity.CRITICAL
    if weapon and SafetyClass.THREAT_BY_CHILD in classes:
        return SafetySeverity.CRITICAL
    if arranged_meeting and SafetyClass.UNSAFE_CONTACT in classes:
        return SafetySeverity.CRITICAL
    return SafetySeverity.ELEVATED


@dataclass(frozen=True)
class SafetyVerdict:
    """The composed verdict — the only object in the tree that carries a severity.

    Severity lives here rather than on the reading because there is exactly one
    derivation site, and a field can only be derived where it lives.
    """

    tripped: bool
    findings: frozenset[SafetyFinding]
    severity: SafetySeverity | None
    caregiver_implicated: bool = False
    imminence_cue: bool = False
    degraded: bool = False
    model_status: str = MODEL_STATUS_UNAVAILABLE
    transcript_unconfirmed: bool = False
    transcript_discarded: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "findings", frozenset(self.findings))
        object.__setattr__(self, "severity", _coerce_severity(self.severity))
        if self.tripped != bool(self.findings):
            raise ValueError("SafetyVerdict.tripped must equal bool(findings)")
        if (self.severity is None) != (not self.tripped):
            raise ValueError("severity is None iff not tripped")
        if not self.tripped and (self.caregiver_implicated or self.imminence_cue):
            raise ValueError("flags must be False when the axis has not tripped")
        # §8: the outage net is axis-only and can NEVER fire an emergency-resource
        # script off a regex. A late model verdict (§6.4) unions into a record the
        # net opened and lifts that ceiling, which is why the check is scoped to a
        # verdict that has no model contribution.
        if self.degraded and self.model_status != "late" and self.tripped:
            if self.classes != frozenset({SafetyClass.UNSPECIFIED_CONCERN}):
                raise ValueError("the degraded net may only produce UNSPECIFIED_CONCERN")
            if self.severity is not SafetySeverity.ELEVATED:
                raise ValueError("the degraded net may never produce CRITICAL")

    @property
    def classes(self) -> frozenset[SafetyClass]:
        return frozenset(finding.safety_class for finding in self.findings)

    @property
    def sources(self) -> frozenset[SafetySource]:
        return frozenset(finding.source for finding in self.findings)

    @property
    def model_unavailable(self) -> bool:
        """The ``safety_model_unavailable`` stamp — visible, never silent (§7.3)."""
        return self.degraded

    def analytics(self) -> dict:
        """§14's write boundary: **routine analytics receive ``tripped`` +
        ``severity`` and nothing else.** The class set is redacted of phrases but is
        still a disclosure category, and the teacher-summary rule is about the
        category, not the words. Do not add a field to this method."""
        return {
            "safety_alert": self.tripped,
            "safety_severity": self.severity.value if self.severity else None,
        }

    @classmethod
    def clear(cls) -> "SafetyVerdict":
        return cls(tripped=False, findings=frozenset(), severity=None)


def compose_safety_verdict(
    *,
    lexicon: Any = None,
    perception_safety_alert: bool = False,
    model: Any = None,
    transcript_unconfirmed: bool = False,
    transcript_discarded: bool = False,
    prior_max_severity: Any = None,
) -> SafetyVerdict:
    """Union the sources into one verdict. Add-only, monotone, one severity site.

    * ``lexicon`` — the ``SafetySignals`` LEXICON reading from Utterance Intake.
      Contributes a finding **only** in degraded mode (§6.3); its
      ``caregiver_implicated`` flag contributes in both modes, because that flag is
      lexicon-only by design (§4.1) and only ever makes the language safer.
    * ``perception_safety_alert`` — perception's existing ``safety`` bit. Free, we
      already pay for that response. Axis only, never a class.
    * ``model`` — the ``ModelSafetyVerdict`` from ``child_safety``. ``None`` means no
      detector was wired for this turn; a verdict whose ``available`` is False means
      one ran and did not answer. Both put the turn in degraded mode.
    * ``prior_max_severity`` — §13: severity may be **raised** by history, never
      lowered. The class set is never revised by history.

    The uncertain/discarded stamps (§9) ride on the verdict and never gate it: a
    safety trip at any confidence always produces the safety response path, is still
    written and still notified, and **severity is not capped** on either. Withholding
    a real disclosure because the microphone was poor is precisely the failure this
    axis exists to prevent.
    """
    model_available = bool(model is not None and getattr(model, "available", False))
    degraded = not model_available

    findings: set[SafetyFinding] = set()
    imminence = named_means = weapon = arranged_meeting = False

    if model_available:
        findings |= set(model.findings())
        imminence = bool(model.imminence_cue)
        named_means = bool(getattr(model, "named_means", False))
        weapon = bool(getattr(model, "weapon", False))
        arranged_meeting = bool(getattr(model, "arranged_meeting", False))

    if perception_safety_alert:
        findings.add(SafetyFinding(
            safety_class=SafetyClass.UNSPECIFIED_CONCERN,
            source=SafetySource.PERCEPTION_BIT,
            evidence_id=PERCEPTION_EVIDENCE_ID,
        ))

    lexicon_tripped = bool(
        lexicon is not None and getattr(lexicon, "tripped", False)
    )
    if degraded and lexicon_tripped:
        findings |= set(getattr(lexicon, "findings", frozenset()))

    tripped = bool(findings)
    caregiver = bool(
        tripped
        and lexicon_tripped
        and getattr(lexicon, "caregiver_implicated", False)
    )
    imminence = imminence and tripped

    severity = derive_severity(
        classes=frozenset(f.safety_class for f in findings),
        imminence_cue=imminence,
        named_means=named_means,
        weapon=weapon,
        arranged_meeting=arranged_meeting,
    )
    if severity is not None:
        severity = _max_severity(severity, _coerce_severity(prior_max_severity))
    if degraded and severity is not None:
        # §8 is absolute: the net never fires an emergency-resource script off a
        # regex. History cannot lift that ceiling either — inheriting an earlier
        # turn's CRITICAL here would fire the emergency script on evidence the net
        # is not allowed to produce. The earlier record keeps its own CRITICAL; this
        # is not a downgrade of anything, it is a refusal to upgrade on no evidence.
        severity = SafetySeverity.ELEVATED

    status = MODEL_STATUS_UNAVAILABLE
    if model is not None:
        status = getattr(getattr(model, "status", None), "value", MODEL_STATUS_UNAVAILABLE)

    return SafetyVerdict(
        tripped=tripped,
        findings=frozenset(findings),
        severity=severity,
        caregiver_implicated=caregiver,
        imminence_cue=imminence,
        degraded=degraded,
        model_status=status,
        transcript_unconfirmed=bool(transcript_unconfirmed),
        transcript_discarded=bool(transcript_discarded),
    )


def union_late(verdict: SafetyVerdict, late: Any) -> SafetyVerdict:
    """§6.4: a late model verdict unions into a record the degraded net opened.

    It may add classes and raise severity; it may never clear or downgrade. The
    ``degraded`` stamp survives — the turn *was* released degraded, and rewriting
    that would make the record claim something the child did not experience.
    """
    if late is None or not getattr(late, "available", False):
        return verdict
    findings = set(verdict.findings) | set(late.findings())
    imminence = verdict.imminence_cue or bool(late.imminence_cue)
    severity = derive_severity(
        classes=frozenset(f.safety_class for f in findings),
        imminence_cue=imminence,
        named_means=bool(getattr(late, "named_means", False)),
        weapon=bool(getattr(late, "weapon", False)),
        arranged_meeting=bool(getattr(late, "arranged_meeting", False)),
    )
    severity = _max_severity(severity, verdict.severity)
    return SafetyVerdict(
        tripped=bool(findings),
        findings=frozenset(findings),
        severity=severity,
        caregiver_implicated=verdict.caregiver_implicated,
        imminence_cue=imminence,
        degraded=verdict.degraded,
        model_status="late",
        transcript_unconfirmed=verdict.transcript_unconfirmed,
        transcript_discarded=verdict.transcript_discarded,
    )


def compose_safety_alert(
    *,
    lexicon: Any = None,
    perception_safety_alert: bool = False,
    model: Any = None,
) -> bool:
    """Union the safety sources into one alert boolean. Add-only.

    The frozen entry point from ticket 01, unchanged in signature and now a thin
    projection of ``compose_safety_verdict``. Its legacy-20 regression test calls
    it with no ``model``, which is exactly the degraded case in which the lexicon
    contributes — so the legacy rows still trip, through the new composition, with
    that test file untouched.
    """
    return compose_safety_verdict(
        lexicon=lexicon,
        perception_safety_alert=perception_safety_alert,
        model=model,
    ).tripped
