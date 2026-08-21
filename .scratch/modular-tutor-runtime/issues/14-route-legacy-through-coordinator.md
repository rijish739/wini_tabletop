# 14 — Route the legacy runtime through the typed coordinator

**What to build:** A typed Turn Coordinator and Runtime Supervisor invoked by the existing compatibility façade while a temporary legacy adapter preserves the complete current Turn behavior.

**Blocked by:** 13 — Expand lifecycle contracts and transactional state.

**Status:** ready-for-agent

- [ ] Make the compatibility façade construct a Turn Input and serialize a committed Turn Result without changing caller-visible behavior.
- [ ] Route every existing Turn through the Turn Coordinator using a temporary adapter for behavior not yet extracted.
- [ ] Establish the logical Turn phase model without moving feature policy into the coordinator.
- [ ] Establish coordinator-owned current-Turn recovery policy and Runtime Supervisor health states.
- [ ] Translate unclassified legacy failures into observable Failure Signals at the adapter seam.
- [ ] Preserve provisional streaming order and terminal error behavior.
- [ ] Keep the temporary adapter explicit, measurable, and removable rather than presenting it as a final Feature Module.
- [ ] Pass the full frozen equivalence oracle through the new façade and coordinator path.

