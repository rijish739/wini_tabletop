# 15 — Extract Interaction Control

**What to build:** The `InteractionControl` Feature Module owning session admission, deterministic routing (`_front_gate`), persona generation, topic continuity, and session termination.

**Blocked by:** 14 — Route legacy Turn through the Turn Coordinator.

**Status:** resolved

- [x] Extract `interaction_control/control.py` and its typed dependencies.
- [x] Implement deterministic front-door gates (safety, nonsense, topic routing).
- [x] Integrate with `TurnCoordinator` turn-admission phase.
- [x] Ensure persona generation and non-learning paths are encapsulated.
- [x] Pass all interaction control unit tests.

## Resolution

- Implemented `cloud_run_service/interaction_control/` module with full test suite passing in `interaction_control/tests/test_interaction_control.py`.
