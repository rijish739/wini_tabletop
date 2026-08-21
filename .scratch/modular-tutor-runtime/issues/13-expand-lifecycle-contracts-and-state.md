# 13 — Expand lifecycle contracts and transactional state

**What to build:** Typed Turn lifecycle contracts and a transactional state seam that coexist with the current runtime, preserve its behavior, and provide the foundation for incremental Feature Module extraction.

**Blocked by:** 11 — Freeze the Baseline Split equivalence oracle.

**Status:** ready-for-agent

- [ ] Define lifecycle-wide contracts for Turn Input, Turn Context, Turn Result, State Change, Failure Signal, Provisional Output, Realization Receipt, and Turn Commit.
- [ ] Keep feature-specific schemas out of lifecycle-wide contracts.
- [ ] Provide immutable, capability-scoped views of Learner State and Session State.
- [ ] Provide a working state projection that validates and applies typed State Changes in memory.
- [ ] Provide one atomic Turn Commit through the existing persistence adapters.
- [ ] Preserve identity binding, state migration, evidence idempotency, and append-only evidence behavior.
- [ ] Add production and deterministic test adapters at genuine persistence seams.
- [ ] Prove through the frozen oracle that adding the contracts and transaction seam changes no external Turn behavior.

