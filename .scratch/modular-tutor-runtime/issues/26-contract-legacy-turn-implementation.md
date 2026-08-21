# 26 — Contract the legacy Turn implementation

**What to build:** The typed Turn Coordinator as the authoritative implementation for every Turn, with the migration adapter removed and the compatibility façade reduced to input/output adaptation.

**Blocked by:** 25 — Complete state ownership and architecture enforcement.

**Status:** ready-for-agent

- [ ] Route every supported Turn scenario entirely through the nine Feature Module Interfaces.
- [ ] Remove the temporary legacy behavior adapter and all migrated feature-policy branches.
- [ ] Keep the Turn Coordinator limited to phase sequencing, concurrency, outcome joining, failure policy, state projection, and commit.
- [ ] Keep the compatibility façade limited to Turn Input construction and Turn Result serialization.
- [ ] Preserve external response fields, streaming behavior, state semantics, evidence integrity, and caller compatibility.
- [ ] Verify Runtime Supervisor health transitions and terminal-error behavior without legacy fallbacks.
- [ ] Pass the complete frozen equivalence oracle, Module tests, scenario tests, and architecture checks.
- [ ] Demonstrate that no active behavior depends on the contracted implementation.

