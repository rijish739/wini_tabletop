"""The single schema constructor for captured and frozen Turn observations."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class TurnObservation:
    case_id: str
    tags: list[str]
    result: dict[str, Any]
    compatibility: dict[str, Any]
    state_before: dict[str, Any]
    state_after: dict[str, Any]
    state_changes: list[dict[str, Any]]
    evidence_events: list[dict[str, Any]]
    assessment_lifecycle: dict[str, Any]
    manifest: dict[str, Any]
    realization_receipt: dict[str, Any]
    stream_events: list[dict[str, Any]]
    failure_signals: list[dict[str, Any]]
    degradation_reasons: list[str]
    metrics: dict[str, Any]
    model_usage: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(asdict(self))
