"""Typed, immutable contracts at the oracle's public runtime seam."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class TurnCase:
    case_id: str
    state_fixture: str
    turn_input: Mapping[str, Any]
    tags: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TurnCase":
        return cls(
            case_id=str(value["id"]),
            state_fixture=str(value["state"]),
            turn_input=_deep_freeze(copy.deepcopy(value["turn_input"])),
            tags=tuple(str(tag) for tag in value.get("tags", ())),
        )


@dataclass(frozen=True)
class FailureSignal:
    capability: str
    phase: str
    severity: str
    recoverable: bool
    cause: str
    context: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProvisionalEvent:
    kind: str
    sequence: int
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if "kind" in self.payload or "sequence" in self.payload:
            raise ValueError("provisional event payload cannot replace kind or sequence")

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "sequence": self.sequence, **copy.deepcopy(dict(self.payload))}


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_deep_freeze(item) for item in value)
    return value

