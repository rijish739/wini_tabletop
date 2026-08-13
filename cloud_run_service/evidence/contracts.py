"""Typed grading result shared by serial and concurrent grading paths."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class GradeResult:
    outcome: str
    grader_path: str
    confidence: float
    misconception_consistency: bool | None = None
    stt_confidence: float | None = None
    idempotency_key: str | None = None

    @property
    def path(self) -> str:  # compatibility with the previous dict contract
        return self.grader_path

    @property
    def misconception_consistent(self) -> bool | None:
        return self.misconception_consistency

    def to_dict(self) -> dict:
        value = asdict(self)
        value["path"] = self.grader_path
        value["misconception_consistent"] = self.misconception_consistency
        return value

    @classmethod
    def from_value(cls, value) -> "GradeResult":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(value, "legacy_precomputed", 1.0)
        data = dict(value or {})
        consistency = data.get("misconception_consistency")
        if consistency is None and "misconception_consistent" in data:
            consistency = data.get("misconception_consistent")
        return cls(
            outcome=str(data.get("outcome") or "not_an_answer"),
            grader_path=str(data.get("grader_path") or data.get("path") or "unknown"),
            confidence=float(data.get("confidence") or data.get("grader_confidence") or 0.0),
            misconception_consistency=(None if consistency is None else bool(consistency)),
            stt_confidence=data.get("stt_confidence"),
            idempotency_key=data.get("idempotency_key"),
        )
