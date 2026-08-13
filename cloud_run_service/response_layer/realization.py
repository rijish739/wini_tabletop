"""Deterministic post-stream checks that protect evidence, not already-played audio."""
from __future__ import annotations

import re
from dataclasses import dataclass

_NUMBER_RE = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?(?:/\d+)?")


def _norm(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


@dataclass(frozen=True)
class RealizationResult:
    flags: tuple[str, ...]
    elapsed_ms: float

    @property
    def assessment_corrupted(self) -> bool:
        return any(flag in {
            "verified_question_not_delivered", "answer_key_leak",
            "unsupported_number", "response_budget_exceeded",
            "unsupported_misconception_correction",
        } for flag in self.flags)


def check_realization(answer: str, *, hook=None, grounding: str = "manifest_only",
                      grounded_text: str = "", learner_text: str = "",
                      max_words: int | None = None, max_sentences: int | None = None,
                      correcting_misconception: bool = False,
                      misconception_supported: bool = False,
                      allowed_numbers: tuple[str, ...] = ()) -> RealizationResult:
    import time
    start = time.perf_counter()
    flags: list[str] = []
    answer = str(answer or "").strip()
    if hook is not None:
        question = str(getattr(hook, "question", "") or "").strip()
        qnorm, anorm = _norm(question), _norm(answer)
        if not question or question not in answer:
            flags.append("verified_question_not_delivered")
        expected = str(getattr(hook, "expected_answer", "") or "").strip()
        body = anorm.replace(qnorm, " ") if qnorm else anorm
        key = _norm(expected)
        if key:
            if key in {"yes", "no"}:
                leaked = re.search(
                    rf"\b(?:answer|correct answer|it)\s+(?:is|would be)\s+{key}\b", body)
            else:
                leaked = re.search(rf"(?<!\w){re.escape(key)}(?!\w)", body)
            if leaked:
                flags.append("answer_key_leak")
    words = len(answer.split())
    sentences = len([s for s in re.split(r"(?<=[.!?])\s+", answer) if s.strip()])
    if max_words is not None and words > max_words:
        flags.append("response_budget_exceeded")
    if max_sentences is not None and sentences > max_sentences:
        flags.append("response_budget_exceeded")
    if correcting_misconception and not misconception_supported:
        flags.append("unsupported_misconception_correction")
    if grounding == "manifest_only":
        allowed = set(_NUMBER_RE.findall(f"{grounded_text} {learner_text}"))
        allowed.update(str(number) for number in allowed_numbers)
        question_numbers = set(_NUMBER_RE.findall(
            str(getattr(hook, "question", "") or ""))) if hook else set()
        produced = set(_NUMBER_RE.findall(answer)) - question_numbers
        if any(number not in allowed for number in produced):
            flags.append("unsupported_number")
    elapsed = (time.perf_counter() - start) * 1000.0
    return RealizationResult(tuple(dict.fromkeys(flags)), elapsed)
