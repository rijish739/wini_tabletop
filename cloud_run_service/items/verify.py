"""The authoritative generated-answer-key verification boundary."""
from __future__ import annotations

import hashlib
import json
from typing import Callable

from .bank import VerifiedItemBank, default_bank
from .contracts import CandidateItem, VerifiedItem
from .normalization import is_binary_answer, normalize_answer, normalize_text, validation_error

VERIFIER_VERSION = "wini-item-verifier-v1"


def _answers_agree(proposed: str, independent: str) -> bool:
    try:
        import math_grade
        verdict = math_grade.grade(proposed, independent)
        if verdict in {"correct", "wrong"}:
            return verdict == "correct"
    except Exception:
        pass
    return normalize_answer(proposed).casefold() == normalize_answer(independent).casefold()


def verify(candidate: CandidateItem | dict, *, independent_answer: str | None = None,
           independent_rubric: str | None = None, verifier_confidence: float = 1.0,
           verifier_provenance: str = "independent_deterministic",
           bank: VerifiedItemBank | None = None, cache: bool = True) -> VerifiedItem | None:
    """Verify one generated candidate and optionally append it to the shared bank.

    This is the ONLY boundary through which a generated answer key becomes
    servable. Callers must obtain the independent answer without exposing the
    proposed key; ordinary learner-facing turns only read this function's cache.
    """
    candidate = candidate if isinstance(candidate, CandidateItem) else CandidateItem.from_dict(candidate)
    question = normalize_text(candidate.question)
    proposed = normalize_answer(candidate.expected_answer)
    rubric = normalize_text(candidate.rubric)
    error = validation_error(
        question, proposed or None, rubric or None, candidate.response_type,
        candidate.assessment_purpose, candidate.reveal_policy)
    if error or candidate.item_source != "generated" or verifier_confidence < 0.90:
        return None
    if proposed:
        if not independent_answer or not _answers_agree(proposed, independent_answer):
            return None
    else:
        if not independent_rubric or normalize_text(independent_rubric).casefold() != rubric.casefold():
            return None

    canonical = {
        "concept_id": candidate.concept_id,
        "kc_id": candidate.kc_id or candidate.concept_id,
        "question": question,
        "expected_answer": proposed or None,
        "rubric": rubric or None,
        "response_type": candidate.response_type,
        "assessment_purpose": candidate.assessment_purpose,
        "reveal_policy": candidate.reveal_policy,
        "generator_model": candidate.generator_model,
        "generator_version": candidate.generator_version,
        "schema_id": candidate.schema_id,
        "verifier_version": VERIFIER_VERSION,
    }
    digest = hashlib.sha256(json.dumps(
        canonical, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()
    item = VerifiedItem(
        item_id=f"verified_item::{digest[:24]}",
        concept_id=candidate.concept_id,
        kc_id=candidate.kc_id or candidate.concept_id,
        question=question,
        expected_answer=proposed or None,
        rubric=rubric or None,
        response_type=candidate.response_type,
        assessment_purpose=candidate.assessment_purpose,
        reveal_policy=candidate.reveal_policy,
        verification_status="verified",
        verifier_provenance=verifier_provenance,
        verifier_version=VERIFIER_VERSION,
        verification_token=digest,
        binary_item=is_binary_answer(proposed),
        metadata={**candidate.metadata,
                  "generator_model": candidate.generator_model,
                  "generator_version": candidate.generator_version,
                  "schema_id": candidate.schema_id,
                  "verifier_confidence": verifier_confidence},
    )
    if cache:
        (bank or default_bank())._append_verified(item)
    return item


def solve_independently(candidate: CandidateItem, solver: Callable[..., dict]) -> tuple[str | None, float]:
    """Off-path helper: the independent solver sees the question, never the key."""
    result = solver(question=candidate.question, temperature=0.0)
    if not isinstance(result, dict):
        return None, 0.0
    return result.get("derived_answer"), float(result.get("confidence") or 0.0)
