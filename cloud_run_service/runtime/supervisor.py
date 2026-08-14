"""Cross-Turn service health derived from typed runtime failures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .contracts import FailureSignal


class RuntimeHealth(str, Enum):
    STARTING = "STARTING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class RuntimeHealthSnapshot:
    health: RuntimeHealth
    consecutive_failed_turns: int
    last_failures: tuple[FailureSignal, ...]


class RuntimeSupervisor:
    """Aggregate initialization and repeated Turn failures into service health."""

    def __init__(self, *, unavailable_after: int = 3) -> None:
        if unavailable_after < 1:
            raise ValueError("unavailable_after must be positive")
        self._unavailable_after = unavailable_after
        self._health = RuntimeHealth.STARTING
        self._consecutive_failed_turns = 0
        self._last_failures: tuple[FailureSignal, ...] = ()

    def ready(self) -> None:
        self._health = RuntimeHealth.READY
        self._consecutive_failed_turns = 0
        self._last_failures = ()

    def observe_turn(self, failures: Iterable[FailureSignal]) -> None:
        observed = tuple(failures)
        self._last_failures = observed
        invalid = tuple(signal for signal in observed if not signal.valid_outcome)
        if invalid:
            self._consecutive_failed_turns += 1
            self._health = (
                RuntimeHealth.UNAVAILABLE
                if self._consecutive_failed_turns >= self._unavailable_after
                else RuntimeHealth.DEGRADED
            )
        elif observed:
            self._consecutive_failed_turns = 0
            self._health = RuntimeHealth.DEGRADED
        else:
            self._consecutive_failed_turns = 0
            self._health = RuntimeHealth.READY

    def initialization_failed(self, failure: FailureSignal) -> None:
        self._last_failures = (failure,)
        self._consecutive_failed_turns = self._unavailable_after
        self._health = RuntimeHealth.UNAVAILABLE

    def snapshot(self) -> RuntimeHealthSnapshot:
        return RuntimeHealthSnapshot(
            health=self._health,
            consecutive_failed_turns=self._consecutive_failed_turns,
            last_failures=self._last_failures,
        )
