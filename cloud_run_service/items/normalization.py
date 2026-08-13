"""Deterministic item normalization and structural validation."""
from __future__ import annotations

import re

_SPACE_RE = re.compile(r"\s+")
_LATEX_RE = re.compile(r"\\(?:frac|sqrt|begin|end)|\$|\\\[")
_QUESTION_END_RE = re.compile(r"[?.!]$")
_BINARY = {"yes", "no", "true", "false"}


def normalize_text(value: str | None) -> str:
    return _SPACE_RE.sub(" ", str(value or "").strip())


def normalize_answer(value: str | None) -> str:
    return normalize_text(value).replace("$", "").strip()


def is_binary_answer(value: str | None) -> bool:
    return normalize_answer(value).casefold() in _BINARY


def validation_error(question: str, expected_answer: str | None,
                     rubric: str | None, response_type: str,
                     assessment_purpose: str, reveal_policy: str) -> str | None:
    q = normalize_text(question)
    answer = normalize_answer(expected_answer)
    rubric = normalize_text(rubric)
    if not q or len(q) < 8 or len(q) > 500:
        return "malformed_question"
    if _LATEX_RE.search(q):
        return "unsupported_question_markup"
    if not _QUESTION_END_RE.search(q):
        return "question_not_explicit"
    if not answer and not rubric:
        return "missing_answer_or_rubric"
    if answer and len(answer) > 200:
        return "malformed_answer"
    if rubric and len(rubric) > 1200:
        return "malformed_rubric"
    if response_type not in {"number", "short_exact", "short_text", "expression", "explanation"}:
        return "unsupported_response_type"
    if not assessment_purpose:
        return "missing_assessment_purpose"
    if reveal_policy not in {"after_attempt", "after_assessment", "never_during_test"}:
        return "unsupported_reveal_policy"
    return None
