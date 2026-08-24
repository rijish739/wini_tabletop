# 18 — Extract Pedagogy

**What to build:** The `Pedagogy` Feature Module owning teaching action selection (`rules_decide`), learning mode state machine (`ModeController`), practice/test planning (`drive_test`), and pedagogical pacing.

**Blocked by:** 17 — Extract Prior Assessment and Evidence.

**Status:** resolved

- [x] Extract `pedagogy/interface.py` and `pedagogy/session_modes.py`.
- [x] Implement `PedagogyInterface` emitting `PedagogicalDecision` and state changes.
- [x] Ensure rules-based teaching decisions, mode transitions, and pacing calculations are self-contained.
- [x] Pass pedagogy unit tests in `pedagogy/tests/test_pedagogy.py`.

## Resolution

- Implemented `cloud_run_service/pedagogy/` with complete test coverage in `pedagogy/tests/test_pedagogy.py`.
