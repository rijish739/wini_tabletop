"""Deterministic turn triage before voice-paced generation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Slice 07 (2026-08-28): cue-regex imports from cognitive_classifier.cues retired.
# Triage now reads Perception labels from analysis["signals"] instead of running
# HINT_RE / NEXT_RE / SELF_CORRECTION_RE / is_pure_ack / is_question on text.
# stt_uncertain stays legacy (unwired to a label; signals are empty on uncertain turns).

YES_NO_RE = re.compile(r"^\s*(yes|yeah|ya|yep|no|nope|nah|ok|okay)\b", re.IGNORECASE)


@dataclass
class TriageResult:
    primary_intent: str
    secondary_intents: list[str] = field(default_factory=list)
    state_policy: str = "normal"
    route: str = "tutor_loop"
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "primary_intent": self.primary_intent,
            "secondary_intents": self.secondary_intents,
            "state_policy": self.state_policy,
            "route": self.route,
            "reason": self.reason,
        }


def triage_turn(text: str, analysis: dict, session: dict, pace: dict, stt_uncertain: bool = False) -> TriageResult:
    normalized = (analysis.get("normalized_text") or text or "").strip()
    signals = set(analysis.get("signals") or [])
    flags = set((analysis.get("state_deltas") or {}).get("concept_flags") or [])
    concept = analysis.get("concept") or {}
    pending_check = session.get("pending_check")
    pending_micro = pace.get("pending_micro_check")

    if stt_uncertain or not normalized or len(normalized.split()) <= 1:
        return TriageResult(
            "unclear",
            state_policy="no_write",
            route="clarify",
            reason="empty, very short, or uncertain STT transcript",
        )

    # Slice 07 (2026-08-28): label-fed — read Perception signals instead of cue regexes.
    secondary: list[str] = []
    if "curiosity" in signals or "question" in signals:
        secondary.append("curiosity")
    if "self_correction" in signals:
        secondary.append("self_correction")
    if "transfer_attempt" in signals:
        secondary.append("transfer_attempt")

    wants_hint = bool("request_hint" in signals or "hint_requested" in flags)
    if pending_check:
        if wants_hint:
            return TriageResult(
                "hint_request",
                secondary,
                state_policy="normal",
                route="tutor_loop",
                reason="real graded pending_check exists; route to existing hint-chain escalation",
            )
        return TriageResult(
            "answer_current_prompt",
            secondary,
            state_policy="normal",
            route="tutor_loop",
            reason="real graded pending_check exists; TutorLoop may close it with evidence write-back",
        )

    if wants_hint:
        return TriageResult(
            "hint_request",
            secondary,
            state_policy="soft_only",
            route="tutor_loop",
            reason="hint request without graded pending_check; use tutor rules but no deep write-back",
        )

    if "acknowledgment" in signals:
        return TriageResult(
            "ack",
            secondary,
            state_policy="soft_only",
            route="tutor_loop",
            reason="pure acknowledgment should reflect/advance, not re-explain",
        )

    if "ready_for_next" in signals or "topic_shift" in signals:
        return TriageResult(
            "topic_shift",
            secondary,
            state_policy="confirm_before_shift",
            route="confirm_shift",
            reason="explicit move-next/topic-shift cue",
        )

    if concept.get("concept_id") and not concept.get("abstained") and float(concept.get("concept_confidence") or 0.0) >= 0.72:
        current = session.get("current_concept")
        # Slice 07: "question" label replaces is_question(normalized) regex.
        if current and current != concept.get("concept_id") and "question" in signals:
            return TriageResult(
                "topic_shift",
                secondary,
                state_policy="confirm_before_shift",
                route="confirm_shift",
                reason="high-confidence concept different from current concept",
            )

    if pending_micro and YES_NO_RE.search(normalized):
        return TriageResult(
            "answer_current_prompt",
            secondary,
            state_policy="soft_only",
            route="tutor_loop",
            reason="answered a pace-only micro-check; close micro-check but do not deep-grade",
        )

    if pending_micro:
        return TriageResult(
            "elaboration",
            secondary,
            state_policy="soft_only",
            route="tutor_loop",
            reason="student elaborated during a pace-only micro-check",
        )

    return TriageResult(
        "elaboration" if secondary else "unclear" if len(normalized.split()) < 3 else "answer_current_prompt",
        secondary,
        state_policy="normal",
        route="tutor_loop",
        reason="ordinary tutor turn",
    )
