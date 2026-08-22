# 13 — Expand lifecycle contracts and working state

**What to build:** The foundational lifecycle contracts, capability-scoped state projections, and atomic commit boundary needed by the Turn Coordinator and Feature Modules.

**Blocked by:** 11 — Freeze the Baseline Split equivalence oracle.

**Status:** resolved

- [x] Define immutable `TurnInput`, `TurnContext`, `TurnResult`, `ModuleOutcome`, `StateChange`, `FailureSignal`, `ProvisionalOutput`, and `RealizationReceipt` contracts.
- [x] Implement capability-scoped immutable state projections in `state_and_persistence`.
- [x] Implement transactional `StateChange` validation, invariant checks, and atomic `TurnCommit`.
- [x] Implement deterministic recovery mapping for `FailureSignal` and the 4-state `RuntimeSupervisor`.
- [x] Verify state immutability, single-writer invariants, and failure handling via unit tests.

## Resolution

- Implemented `runtime/contracts.py` with typed contracts (`TurnInput`, `TurnContext`, `TurnResult`, `ModuleOutcome`, `StateChange`, `FailureSignal`).
- Implemented `state_and_persistence/` with `WorkingStateProjection` and `TurnCommitManager`.
