# 17 — Extract prior-attempt assessment and evidence

**What to build:** An Assessment and Evidence path that recognizes and grades a learner's response to a previously realized assessment, preserves non-attempts, and applies idempotent evidence to the working state projection.

**Blocked by:** 14 — Route the legacy runtime through the typed coordinator.

**Status:** ready-for-agent

- [ ] Expose the prior-attempt operation through one Assessment and Evidence public façade.
- [ ] Read pending assessment state through an immutable assessment-scoped view.
- [ ] Preserve obvious non-attempt handling and keep the pending assessment armed when no gradeable attempt occurred.
- [ ] Preserve deterministic grading before model-assisted grading and enforce confidence thresholds.
- [ ] Produce idempotent evidence events and validated State Changes through the authoritative evidence writer.
- [ ] Preserve append-only evidence, replay, migration, misconception projection, and mastery projection guarantees.
- [ ] Emit typed Failure Signals and fail closed on assessment-integrity violations.
- [ ] Verify correct, incorrect, partial, low-confidence, duplicate, stale, legacy-unverified, and non-attempt scenarios through the façade and Module Interface.
- [ ] Remove migrated prior-assessment and evidence policy from the legacy adapter while keeping the equivalence oracle green.

