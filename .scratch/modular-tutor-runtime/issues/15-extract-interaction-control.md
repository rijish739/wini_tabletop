# 15 — Extract Interaction Control

**What to build:** A deep Interaction Control Module that owns session admission, non-learning routing, topic continuity, redirection, conversation continuity, and termination while the remaining Turn behavior continues through the migration adapter.

**Blocked by:** 14 — Route the legacy runtime through the typed coordinator.

**Status:** ready-for-agent

- [ ] Expose one Interaction Control Interface used by the Turn Coordinator and its tests.
- [ ] Move admission, deterministic front routing, non-learning interactions, topic shifts, mode-stop interaction, and session termination behind that Interface.
- [ ] Assign Interaction Control semantic ownership of interaction-continuity state.
- [ ] Return typed Module Outcomes, State Changes, and Failure Signals without directly mutating shared state.
- [ ] Preserve safety notifications, scripted replies, context continuity, and session-ended behavior.
- [ ] Verify learning and non-learning routes end to end through the compatibility façade.
- [ ] Remove migrated interaction policy from the legacy adapter while keeping the equivalence oracle green.

