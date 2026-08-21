# 28 — Verify and complete Ownership Handoff

**What to build:** A reviewed handoff proving the Baseline Split is behavior-equivalent, modular, performant, documented, and safe for independent Feature Module ownership.

**Blocked by:** 27 — Consolidate the canonical runtime.

**Status:** ready-for-agent

- [ ] Pass the frozen equivalence oracle and publish the before/after comparison.
- [ ] Pass every Feature Module Interface test and cross-Module Turn scenario.
- [ ] Pass architecture enforcement with no forbidden imports, raw state writes, duplicate policy, or coordinator feature logic.
- [ ] Pass bounded live-cloud smoke verification for identity, schemas, deadlines, streaming, call counts, and representative end-to-end behavior.
- [ ] Demonstrate no new network boundary, steady-state model call, or model-client construction.
- [ ] Keep non-model p95 Turn overhead within ten percent of the measured baseline and report startup and time-to-first-audio separately.
- [ ] Verify duplicate-runtime deletion and all retained compatibility entrypoints.
- [ ] Update the architecture overview, mandatory lockstep documents, measured build status, and work log with remeasured results.
- [ ] Document every Module's Interface, invariants, semantic state ownership, Failure Signals, approved dependencies, adapters, and verification commands.
- [ ] Record a primary and backup owner for every Feature Module and the runtime integration owner.
- [ ] Record producer, consumer, and integration review rules for future Interface and lifecycle-contract changes.
- [ ] Obtain final review confirming that Ownership Handoff may begin and parallel feature development is now permitted.
