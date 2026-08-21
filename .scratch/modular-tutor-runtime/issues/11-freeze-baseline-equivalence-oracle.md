# 11 — Freeze the Baseline Split equivalence oracle

**What to build:** A frozen, offline behavioral oracle for the canonical tutor runtime that can compare the existing and modular implementations across learner-visible results, committed state, evidence, assessment lifecycle, grounding, presentation, streaming, failures, latency, and model usage.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Inventory every active Turn caller and the externally observable contract it consumes.
- [ ] Create sanitized starting-state fixtures covering cold start, active sessions, modes, pending assessments, misconceptions, mastery, migration, and termination.
- [ ] Create a representative Turn corpus covering learning, non-learning, safety, topic control, clarification, hints, practice, tests, assessment attempts and non-attempts, retrieval, visuals, and failures.
- [ ] Record and redact external model-boundary responses for deterministic offline replay.
- [ ] Compare Turn Results, compatibility serialization, State Changes, evidence events, assessment arming and voiding, manifests, Realization Receipts, streaming order, and degradation reasons.
- [ ] Document narrowly scoped normalization rules for nondeterministic wording without normalizing state-affecting meaning, numbers, evidence, assessment content, or presentation decisions.
- [ ] Measure startup, non-model p95 Turn overhead, time-to-first-audio, total latency, steady-state model calls, model-client construction, and presentation-selection overhead.
- [ ] Run the oracle successfully against the unchanged canonical runtime and preserve its report as the Baseline Split reference.

