# 14 — Route legacy Turn through the Turn Coordinator

**What to build:** The `TutorLoopCompatibilityFacade` and `TurnCoordinator` skeleton that executes the canonical Turn pipeline while preserving existing caller contracts.

**Blocked by:** 13 — Expand lifecycle contracts and working state.

**Status:** resolved

- [x] Create `runtime/coordinator.py` sequencing turn phases through typed contracts.
- [x] Implement `runtime/compatibility.py` (`TutorLoopCompatibilityFacade`) bridging `TutorLoop.turn()` inputs and dictionary outputs.
- [x] Integrate single-writer state commits through `TurnCoordinator`.
- [x] Verify baseline behavior equivalence across all caller types.

## Resolution

- Implemented `TurnCoordinator` in `runtime/coordinator.py`.
- Implemented `TutorLoopCompatibilityFacade` in `runtime/compatibility.py`.
- Added unit tests in `runtime/tests/test_coordinator.py` and `runtime/tests/test_compatibility_facade.py`.
