"""Public interface for transactional State and Persistence."""

from .projection import (
    CapabilityStateAccess,
    LearnerStateView,
    PreparedStateCommit,
    SessionStateView,
    StateChangeConflict,
    StateChangeRejected,
    StateView,
    WorkingStateProjection,
)
from .persistence import (
    DeterministicPersistenceAdapter,
    LearnerStatePersistenceAdapter,
    PersistenceAdapter,
    StateAndPersistence,
    StateCommitFailed,
    StaleState,
    state_version,
)

__all__ = [
    "CapabilityStateAccess",
    "DeterministicPersistenceAdapter",
    "LearnerStatePersistenceAdapter",
    "LearnerStateView",
    "PersistenceAdapter",
    "PreparedStateCommit",
    "StateAndPersistence",
    "StateChangeConflict",
    "StateChangeRejected",
    "StateCommitFailed",
    "StateView",
    "SessionStateView",
    "StaleState",
    "WorkingStateProjection",
    "state_version",
]
