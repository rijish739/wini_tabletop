"""Typed contracts for the offline verified-item economy."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CandidateItem:
    """An untrusted generated item. It is never servable in this form."""

    concept_id: str
    question: str
    expected_answer: str | None = None
    rubric: str | None = None
    kc_id: str | None = None
    response_type: str = "short_exact"
    assessment_purpose: str = "check_independent"
    reveal_policy: str = "after_attempt"
    item_source: str = "generated"
    generator_model: str | None = None
    generator_version: str | None = None
    schema_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CandidateItem":
        data = dict(value or {})
        answer = data.get("expected_answer")
        return cls(
            concept_id=str(data.get("concept_id") or ""),
            kc_id=data.get("kc_id"),
            question=str(data.get("question") or ""),
            expected_answer=None if answer is None else str(answer),
            rubric=data.get("rubric"),
            response_type=str(data.get("response_type") or "short_exact"),
            assessment_purpose=str(data.get("assessment_purpose") or "check_independent"),
            reveal_policy=str(data.get("reveal_policy") or "after_attempt"),
            item_source=str(data.get("item_source") or "generated"),
            generator_model=data.get("generator_model"),
            generator_version=data.get("generator_version"),
            schema_id=data.get("schema_id"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class VerifiedItem:
    """A normalized item accepted by the independent verification boundary."""

    item_id: str
    concept_id: str
    kc_id: str
    question: str
    expected_answer: str | None
    rubric: str | None
    response_type: str
    assessment_purpose: str
    reveal_policy: str
    verification_status: str
    verifier_provenance: str
    verifier_version: str
    verification_token: str
    item_source: str = "generated_verified"
    binary_item: bool = False
    hint_chain: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1

    @property
    def item_verified(self) -> bool:
        return self.verification_status in {"verified", "authored_verified"}

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["hint_chain"] = list(self.hint_chain)
        value["item_verified"] = self.item_verified  # legacy compatibility
        value["verification_provenance"] = self.verifier_provenance
        value["verification_version"] = self.verifier_version
        value["id"] = self.item_id
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "VerifiedItem":
        data = dict(value or {})
        concept_id = str(data.get("concept_id") or "")
        return cls(
            item_id=str(data.get("item_id") or data.get("id") or ""),
            concept_id=concept_id,
            kc_id=str(data.get("kc_id") or concept_id),
            question=str(data.get("question") or ""),
            expected_answer=(None if data.get("expected_answer") is None
                             else str(data.get("expected_answer"))),
            rubric=data.get("rubric"),
            response_type=str(data.get("response_type") or "short_exact"),
            assessment_purpose=str(data.get("assessment_purpose") or "check_independent"),
            reveal_policy=str(data.get("reveal_policy") or "after_attempt"),
            verification_status=str(data.get("verification_status") or "unverified"),
            verifier_provenance=str(data.get("verifier_provenance")
                                    or data.get("verification_provenance") or ""),
            verifier_version=str(data.get("verifier_version")
                                 or data.get("verification_version") or ""),
            verification_token=str(data.get("verification_token") or ""),
            item_source=str(data.get("item_source") or "generated_verified"),
            binary_item=bool(data.get("binary_item", False)),
            hint_chain=tuple(data.get("hint_chain") or ()),
            metadata=dict(data.get("metadata") or {}),
            schema_version=int(data.get("schema_version") or 1),
        )
