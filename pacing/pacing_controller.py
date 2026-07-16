"""Runtime pacing controller for short spoken tutoring turns."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .ledger import PaceLedger, get_session
from .triage import TriageResult, triage_turn


# Spoken-turn budgets. Teaching actions (EXPLAIN / WORKED_EXAMPLE / ANALOGOUS /
# REPRESENTATION / ENCOURAGE / TRANSFER) carry enough room to actually DELIVER a
# clear multi-sentence idea (owner decision 2026-07-01: the earlier 25-35 word caps
# produced content-free one-liners once a greeting/apology was stripped). Checking
# actions (PROBE / SOCRATIC / QUIZ / REFLECT) stay tighter — a probe or a check
# should be short by design, not a lecture.
ACTION_BUDGETS: dict[str, dict[str, Any]] = {
    "EXPLAIN": {"max_words": 65, "max_sentences": 4, "micro_check_type": "yes_no"},
    "WORKED_EXAMPLE": {"max_words": 85, "max_sentences": 5, "micro_check_type": "try_step"},
    "MISCONCEPTION_PROBE": {"max_words": 35, "max_sentences": 2, "micro_check_type": "none"},
    "ANALOGOUS_EXAMPLE": {"max_words": 60, "max_sentences": 4, "micro_check_type": "try_step"},
    "ENCOURAGE": {"max_words": 45, "max_sentences": 3, "micro_check_type": "next_step"},
    "METACOGNITIVE_REFLECT": {"max_words": 30, "max_sentences": 2, "micro_check_type": "own_words"},
    "TRANSFER_PROBLEM": {"max_words": 45, "max_sentences": 3, "micro_check_type": "answer"},
    "REPRESENTATION_TRANSLATION": {"max_words": 60, "max_sentences": 4, "micro_check_type": "yes_no"},
    "WHY_IT_MATTERS": {"max_words": 60, "max_sentences": 4, "micro_check_type": "yes_no"},
    "SOCRATIC_Q": {"max_words": 30, "max_sentences": 2, "micro_check_type": "question"},
    "QUIZ": {"max_words": 30, "max_sentences": 2, "micro_check_type": "answer"},
    # Part 12 (§5.5) — PRACTICE/TEST actions. Checking actions stay tight by design;
    # COMPLETION_STEP gets room to work all-but-the-last step (backward fading).
    "COMPLETION_STEP": {"max_words": 75, "max_sentences": 5, "micro_check_type": "try_step"},
    "ISOMORPHIC_PRACTICE": {"max_words": 40, "max_sentences": 2, "micro_check_type": "answer"},
    "TEST_QUESTION": {"max_words": 30, "max_sentences": 2, "micro_check_type": "answer"},
    "TEST_FEEDBACK": {"max_words": 20, "max_sentences": 2, "micro_check_type": "none"},
    "TEST_SUMMARY": {"max_words": 60, "max_sentences": 4, "micro_check_type": "yes_no"},
    "MODE_OFFER": {"max_words": 25, "max_sentences": 2, "micro_check_type": "yes_no"},
}


@dataclass
class AnswerBudget:
    max_words: int = 60
    max_sentences: int = 4
    must_end_with: str = "micro_check"
    micro_check_type: str = "yes_no"
    expected_response_type: str = "yes_no"
    style: str = "warm, concrete, no lecture"

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_words": self.max_words,
            "max_sentences": self.max_sentences,
            "must_end_with": self.must_end_with,
            "micro_check_type": self.micro_check_type,
            "expected_response_type": self.expected_response_type,
            "style": self.style,
        }


@dataclass
class PacingDecision:
    triage: TriageResult
    answer_budget: AnswerBudget
    direct_answer: str | None = None
    tts_pace: str = "slow-clear"
    analysis: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "triage": self.triage.as_dict(),
            "answer_budget": self.answer_budget.as_dict(),
            "direct_answer": self.direct_answer,
            "tts_pace": self.tts_pace,
        }


def _expected_from_micro_check(kind: str) -> str:
    return {
        "yes_no": "yes_no",
        "own_words": "own_words",
        "answer": "answer_probe",
        "question": "reason",
        "try_step": "reason",
        "next_step": "reason",
        "none": "free",
    }.get(kind, "free")


def budget_for_action(action: str | None, *, pending_check: bool = False, route: str = "tutor_loop") -> AnswerBudget:
    raw = dict(ACTION_BUDGETS.get(action or "EXPLAIN", ACTION_BUDGETS["EXPLAIN"]))
    if pending_check:
        raw["micro_check_type"] = "none"
    if route == "confirm_shift":
        raw.update({"max_words": 22, "max_sentences": 1, "micro_check_type": "yes_no"})
    micro = raw["micro_check_type"]
    return AnswerBudget(
        max_words=int(raw["max_words"]),
        max_sentences=int(raw["max_sentences"]),
        must_end_with="none" if micro == "none" else "micro_check",
        micro_check_type=micro,
        expected_response_type=_expected_from_micro_check(micro),
    )


class PacingController:
    def before_turn(self, transcript: str, loop, stt_uncertain: bool = False) -> PacingDecision:
        session = get_session(loop.state)
        ledger = PaceLedger.from_state(loop.state)
        analysis = loop.analyze_only(transcript)
        triage = triage_turn(transcript, analysis, session, ledger.data, stt_uncertain=stt_uncertain)

        if triage.route == "clarify":
            budget = AnswerBudget(max_words=16, max_sentences=1, must_end_with="none", micro_check_type="none")
            return PacingDecision(
                triage=triage,
                answer_budget=budget,
                direct_answer="I could not hear that clearly. Please say it once more.",
                analysis=analysis,
            )

        if triage.route == "confirm_shift":
            concept = analysis.get("concept") or {}
            cid = concept.get("concept_id")
            # speak the human name, never a raw catalog id; arm pending_shift so a
            # bare "yes" next turn actually EXECUTES the switch (tutor_loop consumes
            # it — previously the offer was made and then forgotten)
            name = loop.concept_name(cid) if (cid and hasattr(loop, "concept_name")) else "that topic"
            if cid:
                session["pending_shift"] = {"concept_id": cid, "name": name}
            direct = f"We can switch to {name}. Should I pause the current topic here?"
            budget = budget_for_action(None, route="confirm_shift")
            return PacingDecision(triage=triage, answer_budget=budget, direct_answer=direct, analysis=analysis)

        budget = budget_for_action(None, pending_check=bool(session.get("pending_check")), route=triage.route)
        return PacingDecision(triage=triage, answer_budget=budget, analysis=analysis)

    def budget_after_action(self, action: str, decision: PacingDecision, loop) -> AnswerBudget:
        session = get_session(loop.state)
        return budget_for_action(action, pending_check=bool(session.get("pending_check")), route=decision.triage.route)

    def after_turn(
        self,
        transcript: str,
        answer: str | None,
        loop_result: dict[str, Any] | None,
        loop,
        decision: PacingDecision,
        latency: dict[str, int] | None = None,
    ) -> None:
        ledger = PaceLedger.from_state(loop.state)
        triage = decision.triage
        if triage.state_policy in {"soft_only", "no_write"}:
            ledger.clear_micro_check()

        action = (loop_result or {}).get("action")
        budget = decision.answer_budget
        if action:
            budget = self.budget_after_action(action, decision, loop)

        answer_text = answer or decision.direct_answer or ""
        ledger.data["mode"] = _mode_for_action(action, triage.primary_intent)
        ledger.data["expected_response_type"] = budget.expected_response_type
        ledger.data["max_words"] = budget.max_words
        ledger.data["last_spoken_answer"] = answer_text[:500]
        ledger.data["last_explanation_summary"] = _summarize_answer(answer_text)
        ledger.data["last_voice_latency_ms"] = latency or {}
        ledger.data["explanation_step"] = int(ledger.data.get("explanation_step") or 0) + 1

        if budget.must_end_with == "micro_check" and answer_text:
            ledger.set_micro_check(_last_sentence(answer_text), kind=budget.micro_check_type)
        else:
            ledger.clear_micro_check()

        ledger.save_to_state(loop.state)
        if loop.state.path:
            loop.state.save()


def _mode_for_action(action: str | None, intent: str) -> str:
    if intent == "hint_request":
        return "hint"
    if intent == "topic_shift":
        return "shift"
    if action in {"MISCONCEPTION_PROBE", "TRANSFER_PROBLEM", "QUIZ"}:
        return "probe"
    # Part 12 (§5.5): the TEST_* family are checks; COMPLETION_STEP teaches.
    if action in {"TEST_QUESTION", "TEST_FEEDBACK", "TEST_SUMMARY", "ISOMORPHIC_PRACTICE"}:
        return "probe"
    if action == "COMPLETION_STEP":
        return "explain"
    if action == "METACOGNITIVE_REFLECT":
        return "reflect"
    if action and action.startswith("HINT_LEVEL"):
        return "hint"
    return "explain"


def _last_sentence(text: str) -> str:
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
    return parts[-1][:220] if parts else text[:220]


def _summarize_answer(text: str) -> str:
    first = _last_sentence(text) if len(text.split()) <= 14 else " ".join(text.split()[:18])
    return first[:220]
