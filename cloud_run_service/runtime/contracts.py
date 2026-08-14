"""Feature-neutral, immutable contracts shared across one Turn lifecycle."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Generic, Mapping, TypeVar


OutcomeValue = TypeVar("OutcomeValue")
ContextState = TypeVar("ContextState")
NextContextState = TypeVar("NextContextState")


def deep_freeze(value: Any) -> Any:
    """Detach and recursively freeze values crossing a lifecycle seam."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(deep_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(deep_freeze(item) for item in value)
    return copy.deepcopy(value)


def deep_thaw(value: Any) -> Any:
    """Detach immutable lifecycle values into caller-compatible mutable containers."""
    if isinstance(value, Mapping):
        return {str(key): deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [deep_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return {deep_thaw(item) for item in value}
    return copy.deepcopy(value)


@dataclass(frozen=True)
class DeviceCapabilities:
    speech: bool = True
    display: bool = False
    touch: bool = False
    authored_visuals: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", deep_freeze(self.attributes))


@dataclass(frozen=True)
class TurnBudgets:
    total_ms: int
    first_output_ms: int | None = None
    model_calls: int | None = None

    def __post_init__(self) -> None:
        for name in ("total_ms", "first_output_ms", "model_calls"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")


@dataclass(frozen=True)
class TurnInput:
    turn_id: str
    learner_id: str
    interaction: Mapping[str, Any]
    device: DeviceCapabilities
    budgets: TurnBudgets
    trusted_observations: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.turn_id or not self.learner_id:
            raise ValueError("Turn Input requires turn_id and learner_id")
        object.__setattr__(self, "interaction", deep_freeze(self.interaction))
        object.__setattr__(
            self, "trusted_observations", deep_freeze(self.trusted_observations)
        )


@dataclass(frozen=True)
class TurnContext(Generic[ContextState]):
    """Transient, feature-typed working state for one Turn; never persisted."""

    turn_input: TurnInput
    phase: str
    state: ContextState

    def __post_init__(self) -> None:
        if not self.phase:
            raise ValueError("Turn Context requires a phase")
        object.__setattr__(self, "state", copy.deepcopy(self.state))

    @classmethod
    def start(cls, turn_input: TurnInput) -> "TurnContext[None]":
        return TurnContext(turn_input=turn_input, phase="start", state=None)

    def advance(
        self, *, phase: str, state: NextContextState
    ) -> "TurnContext[NextContextState]":
        return TurnContext(turn_input=self.turn_input, phase=phase, state=state)


class FailureSeverity(str, Enum):
    DEGRADED = "degraded"
    ERROR = "error"
    FATAL = "fatal"


@dataclass(frozen=True)
class FailureSignal:
    capability: str
    phase: str
    severity: FailureSeverity
    recoverable: bool
    cause: str
    valid_outcome: bool
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "severity", FailureSeverity(self.severity))
        if not self.capability or not self.phase or not self.cause:
            raise ValueError("Failure Signal requires capability, phase, and cause")
        object.__setattr__(self, "context", deep_freeze(self.context))


@dataclass(frozen=True)
class ModuleOutcome(Generic[OutcomeValue]):
    """Common lifecycle envelope around a Feature Module's own typed value."""

    value: OutcomeValue | None
    state_changes: tuple["StateChange", ...] = ()
    failures: tuple[FailureSignal, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_changes", tuple(self.state_changes))
        object.__setattr__(self, "failures", tuple(self.failures))

    @property
    def valid(self) -> bool:
        return self.value is not None and all(signal.valid_outcome for signal in self.failures)


@dataclass(frozen=True)
class ProvisionalOutput:
    turn_id: str
    sequence: int
    kind: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.turn_id or not self.kind:
            raise ValueError("Provisional Output requires turn_id and kind")
        if self.sequence < 0:
            raise ValueError("Provisional Output sequence cannot be negative")
        object.__setattr__(self, "payload", deep_freeze(self.payload))


class RealizationStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    DEGRADED = "degraded"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass(frozen=True)
class RealizationReceipt:
    turn_id: str
    status: RealizationStatus
    intended: tuple[str, ...] = ()
    delivered: tuple[str, ...] = ()
    failures: tuple[FailureSignal, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", RealizationStatus(self.status))
        if not self.turn_id:
            raise ValueError("Realization Receipt requires turn_id")
        object.__setattr__(self, "intended", tuple(self.intended))
        object.__setattr__(self, "delivered", tuple(self.delivered))
        object.__setattr__(self, "failures", tuple(self.failures))
        object.__setattr__(self, "details", deep_freeze(self.details))


class StateScope(str, Enum):
    LEARNER = "learner"
    SESSION = "session"


class StateOperation(str, Enum):
    SET = "set"
    DELETE = "delete"
    APPEND = "append"


@dataclass(frozen=True)
class StateChange:
    """A feature-neutral request to alter one owned state path."""

    change_id: str
    owner: str
    scope: StateScope
    path: tuple[str, ...]
    operation: StateOperation
    value: Any = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope", StateScope(self.scope))
        object.__setattr__(self, "operation", StateOperation(self.operation))
        if not self.change_id or not self.owner:
            raise ValueError("State Change requires change_id and owner")
        path = tuple(str(part) for part in self.path)
        if not path or any(not part for part in path):
            raise ValueError("State Change requires a non-empty path")
        if self.operation is StateOperation.DELETE and self.value is not None:
            raise ValueError("a delete State Change cannot carry a value")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "value", deep_freeze(self.value))


@dataclass(frozen=True)
class TurnCommit:
    """Receipt proving that one Turn's accepted changes were durably committed."""

    commit_id: str
    turn_id: str
    learner_id: str
    applied_change_ids: tuple[str, ...]
    state_version: str

    def __post_init__(self) -> None:
        if not self.commit_id or not self.turn_id or not self.learner_id:
            raise ValueError("Turn Commit requires commit, turn, and learner identity")
        if not self.state_version:
            raise ValueError("Turn Commit requires a state version")
        object.__setattr__(self, "applied_change_ids", tuple(self.applied_change_ids))


@dataclass(frozen=True)
class TurnResult:
    """The authoritative result exposed only after a successful Turn Commit."""

    turn_id: str
    learner_id: str
    outcome: Mapping[str, Any]
    compatibility: Mapping[str, Any]
    realization: RealizationReceipt
    commit: TurnCommit
    failures: tuple[FailureSignal, ...] = ()
    degradation_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.commit.turn_id != self.turn_id or self.realization.turn_id != self.turn_id:
            raise ValueError("Turn Result lifecycle identities do not match")
        if self.commit.learner_id != self.learner_id:
            raise ValueError("Turn Result learner identity does not match its commit")
        object.__setattr__(self, "outcome", deep_freeze(self.outcome))
        object.__setattr__(self, "compatibility", deep_freeze(self.compatibility))
        object.__setattr__(self, "failures", tuple(self.failures))
        object.__setattr__(self, "degradation_reasons", tuple(self.degradation_reasons))
