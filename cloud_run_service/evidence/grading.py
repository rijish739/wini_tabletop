"""Deterministic-first, rubric-aware grading."""
from __future__ import annotations

import json
import re
from typing import Callable

from .contracts import GradeResult

_NON_ATTEMPT_RE = re.compile(
    r"^\s*(?:ok(?:ay)?|thanks?|thank you|i (?:cannot|can'?t|do not|don'?t) (?:know|understand)|"
    r"can you (?:explain|repeat)|what do you mean|why\??|huh\??|next topic)\s*[.!?]*\s*$",
    re.IGNORECASE,
)


def obvious_non_attempt(reply: str) -> bool:
    text = str(reply or "").strip()
    if not text or _NON_ATTEMPT_RE.match(text):
        return True
    return text.endswith("?") and not re.search(r"(?:=|\d|yes\b|no\b)", text, re.I)


def grade_answer(question: str, expected: str, student_answer: str, rubric: str = "", *,
                 model_call: Callable[..., str] | None = None,
                 stt_confidence: float | None = None,
                 idempotency_key: str | None = None,
                 misconception_probe: bool = False) -> GradeResult:
    """Return one GradeResult. Model failure is insufficient evidence, never wrong."""
    if obvious_non_attempt(student_answer):
        return GradeResult("not_an_answer", "non_attempt_gate", 1.0, None,
                           stt_confidence, idempotency_key)
    deterministic = None
    try:
        import math_grade
        deterministic = math_grade.grade(expected, student_answer)
    except Exception:
        deterministic = None
    if deterministic == "correct":
        return GradeResult("correct", "deterministic", 1.0,
                           False if misconception_probe else None,
                           stt_confidence, idempotency_key)
    if deterministic == "wrong" and not (rubric and misconception_probe):
        return GradeResult("wrong", "deterministic", 1.0, None,
                           stt_confidence, idempotency_key)
    if model_call is None:
        return GradeResult("not_an_answer", "grader_unavailable", 0.0, None,
                           stt_confidence, idempotency_key)

    consistency_instruction = (
        ' Also return "misconception_consistent": true, false, or null; use null when '
        "the reply does not support an inference about the named misconception."
        if misconception_probe else "")
    prompt = (
        "Grade this Class 10 maths response.\n"
        f"QUESTION: {question}\nEXPECTED ANSWER: {expected}\n"
        + (f"RUBRIC / AUTHORED TRAP INFORMATION: {rubric}\n" if rubric else "")
        + f"LEARNER RESPONSE: {student_answer}\n"
          "Return only JSON with outcome (correct|partial|wrong|not_an_answer) and "
          f"confidence (0..1).{consistency_instruction}")
    try:
        raw = model_call(prompt, temperature=0.0, max_tokens=100, small=True)
        match = re.search(r"\{.*\}", raw or "", re.S)
        data = json.loads(match.group(0)) if match else {}
        outcome = str(data.get("outcome") or "not_an_answer")
        if outcome not in {"correct", "partial", "wrong", "not_an_answer"}:
            outcome = "not_an_answer"
        confidence = max(0.0, min(1.0, float(data.get("confidence") or 0.0)))
        consistency = data.get("misconception_consistent") if misconception_probe else None
        if consistency not in {True, False}:
            consistency = None
        # math_grade is the correctness floor. The model may characterize a trap,
        # but it may not overrule a deterministic wrong result.
        if deterministic == "wrong":
            outcome = "wrong"
            consistency = consistency if confidence >= 0.80 else None
            confidence = 1.0
        path = "deterministic+rubric" if deterministic == "wrong" else "rubric_model"
        return GradeResult(outcome, path, confidence, consistency,
                           stt_confidence, idempotency_key)
    except Exception:
        if deterministic == "wrong":
            return GradeResult("wrong", "deterministic+rubric_unavailable", 1.0,
                               None, stt_confidence, idempotency_key)
        return GradeResult("not_an_answer", "grader_unavailable", 0.0, None,
                           stt_confidence, idempotency_key)
