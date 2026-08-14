"""Turn lifecycle contracts and coordination foundations."""

from .contracts import (
    DeviceCapabilities,
    FailureSignal,
    FailureSeverity,
    ModuleOutcome,
    ProvisionalOutput,
    RealizationReceipt,
    RealizationStatus,
    StateChange,
    StateOperation,
    StateScope,
    TurnBudgets,
    TurnCommit,
    TurnContext,
    TurnInput,
    TurnResult,
)
from .coordinator import (
    LOGICAL_TURN_PHASES,
    CoordinatedTurn,
    LegacyExecution,
    RecoveryAction,
    RecoveryPolicy,
    TurnCoordinator,
    TurnPhase,
)
from .supervisor import RuntimeHealth, RuntimeHealthSnapshot, RuntimeSupervisor
from .compatibility import TutorLoopCompatibilityFacade

__all__ = [
    "DeviceCapabilities",
    "FailureSignal",
    "FailureSeverity",
    "ModuleOutcome",
    "ProvisionalOutput",
    "RealizationReceipt",
    "RealizationStatus",
    "StateChange",
    "StateOperation",
    "StateScope",
    "TurnBudgets",
    "TurnCommit",
    "TurnContext",
    "TurnInput",
    "TurnResult",
    "LOGICAL_TURN_PHASES",
    "CoordinatedTurn",
    "LegacyExecution",
    "RecoveryAction",
    "RecoveryPolicy",
    "TurnCoordinator",
    "TurnPhase",
    "RuntimeHealth",
    "RuntimeHealthSnapshot",
    "RuntimeSupervisor",
    "TutorLoopCompatibilityFacade",
]
