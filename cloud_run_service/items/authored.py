"""Adapter for pre-authored store diagnostics (not generated answer keys)."""
from __future__ import annotations

import hashlib
import json

from .contracts import VerifiedItem
from .normalization import is_binary_answer, normalize_answer, normalize_text, validation_error


def from_authored(value: dict) -> VerifiedItem | None:
    source = str(value.get("item_source") or "authored")
    if source.startswith("generated"):
        return None  # generated keys must cross items.verify(), never this adapter
    question = normalize_text(value.get("question") or value.get("diagnostic_question"))
    answer = normalize_answer(value.get("expected_answer"))
    rubric = normalize_text(value.get("rubric") or value.get("why_wrong"))
    response_type = str(value.get("response_type") or "short_text")
    purpose = str(value.get("assessment_purpose") or "diagnose_barrier")
    reveal = str(value.get("reveal_policy") or "after_attempt")
    if validation_error(question, answer or None, rubric or None, response_type, purpose, reveal):
        return None
    item_id = str(value.get("item_id") or value.get("id") or "")
    concept = str(value.get("concept_id") or "")
    if not item_id or not concept:
        return None
    material = json.dumps({"id": item_id, "q": question, "a": answer, "r": rubric},
                          sort_keys=True, ensure_ascii=True)
    token = hashlib.sha256(("authored-store-v1:" + material).encode("utf-8")).hexdigest()
    return VerifiedItem(
        item_id=item_id, concept_id=concept, kc_id=str(value.get("kc_id") or concept),
        question=question, expected_answer=answer or None, rubric=rubric or None,
        response_type=response_type, assessment_purpose=purpose, reveal_policy=reveal,
        verification_status="authored_verified",
        verifier_provenance=str(value.get("verification_provenance") or "authored_store"),
        verifier_version=str(value.get("verification_version") or "store-v1"),
        verification_token=token, item_source=source,
        binary_item=is_binary_answer(answer), hint_chain=tuple(value.get("hint_chain") or ()),
        metadata=dict(value.get("metadata") or {}),
    )
