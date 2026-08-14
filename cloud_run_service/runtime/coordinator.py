"""Feature-neutral sequencing and current-Turn recovery for the tutor runtime."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol

from .contracts import FailureSeverity, FailureSignal, TurnInput, TurnResult
from .legacy_adapter import LegacyAdapterFailure
from .supervisor import RuntimeSupervisor


class TurnPhase(str, Enum):
    ADMISSION_AND_ROUTING = "admission_and_routing"
    PERCEPTION_AND_PRIOR_GRADING = "perception_and_prior_grading"
    STATE_PROJECTION_AND_PEDAGOGY = "state_projection_and_pedagogy"
    GROUNDED_RETRIEVAL = "grounded_retrieval"
    RESPONSE_PLANNING = "response_planning"
    RESPONSE_GENERATION = "response_generation"
    PRESENTATION_AND_REALIZATION = "presentation_and_realization"
    ASSESSMENT_ARMING_AND_COMMIT = "assessment_arming_and_commit"
    FINAL_RESULT = "final_result"


LOGICAL_TURN_PHASES = tuple(TurnPhase)


class RecoveryAction(str, Enum):
    CONTINUE = "continue"
    DEGRADE = "degrade"
    SAFE_NON_ASSESSING_FALLBACK = "safe_non_assessing_fallback"
    RETRY = "retry"
    FAIL_CLOSED = "fail_closed"


class RecoveryPolicy:
    """Feature-neutral current-Turn decisions over reported failure facts."""

    _FAIL_CLOSED_CAPABILITIES = frozenset({
        "identity",
        "safety_integrity",
        "state_and_persistence",
        "assessment_evidence",
    })
    _SAFE_FALLBACK_CAPABILITIES = frozenset({
        "retrieval",
        "response_generation",
    })

    def decide(self, failure: FailureSignal) -> RecoveryAction:
        if (
            failure.severity is FailureSeverity.FATAL
            or failure.capability in self._FAIL_CLOSED_CAPABILITIES
        ):
            return RecoveryAction.FAIL_CLOSED
        if failure.valid_outcome:
            return RecoveryAction.DEGRADE
        if failure.capability in self._SAFE_FALLBACK_CAPABILITIES and failure.recoverable:
            return RecoveryAction.SAFE_NON_ASSESSING_FALLBACK
        if (
            failure.recoverable
            and failure.context.get("idempotent") is True
            and int(failure.context.get("retry_attempt", 0)) < 1
        ):
            return RecoveryAction.RETRY
        return RecoveryAction.FAIL_CLOSED


@dataclass(frozen=True)
class LegacyExecution:
    """Measurable result from the temporary, explicitly removable legacy seam."""

    result: TurnResult
    completed_phases: tuple[TurnPhase, ...]
    measurements: Mapping[str, int | float] = field(default_factory=dict)


class TemporaryLegacyAdapter(Protocol):
    name: str

    def execute(self, turn_input: TurnInput) -> LegacyExecution: ...


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return {_thaw(item) for item in value}
    return copy.deepcopy(value)


@dataclass(frozen=True)
class CoordinatedTurn:
    result: TurnResult
    phases: tuple[TurnPhase, ...]
    measurements: Mapping[str, int | float]

    def serialize_compatibility(self) -> dict[str, Any]:
        return _thaw(self.result.compatibility)


class TurnCoordinator:
    """Sequence a Turn while leaving all tutoring policy behind adapter interfaces."""

    def __init__(
        self,
        *,
        adapter: TemporaryLegacyAdapter,
        supervisor: RuntimeSupervisor,
        recovery_policy: RecoveryPolicy | None = None,
    ) -> None:
        self._adapter = adapter
        self._supervisor = supervisor
        self._recovery_policy = recovery_policy or RecoveryPolicy()

    def run(self, turn_input: TurnInput) -> CoordinatedTurn:
        try:
            execution = self._adapter.execute(turn_input)
        except LegacyAdapterFailure as failure:
            self._supervisor.observe_turn((failure.signal,))
            action = self._recovery_policy.decide(failure.signal)
            if action is not RecoveryAction.FAIL_CLOSED:
                raise RuntimeError(
                    "temporary legacy failures may only use fail-closed recovery"
                ) from failure
            raise failure.original.with_traceback(failure.original.__traceback__)
        if execution.completed_phases != LOGICAL_TURN_PHASES:
            raise RuntimeError("Turn adapter did not complete the logical phase sequence")
        self._supervisor.observe_turn(execution.result.failures)
        return CoordinatedTurn(
            result=execution.result,
            phases=execution.completed_phases,
            measurements=dict(execution.measurements),
        )
