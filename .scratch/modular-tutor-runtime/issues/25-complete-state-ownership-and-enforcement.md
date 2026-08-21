# 25 — Complete state ownership and architecture enforcement

**What to build:** Exclusive semantic ownership for every Learner State and Session State field, with automated enforcement that Feature Modules use typed views and State Changes rather than raw mutation or implementation imports.

**Blocked by:** 15 — Extract Interaction Control; 16 — Extract Perception; 17 — Extract prior-attempt assessment and evidence; 18 — Extract Pedagogy; 19 — Extract Retrieval; 20 — Extract Response Planning; 21 — Extract Response Generation and the Model Gateway; 22 — Realize speech and retrieved presentation; 23 — Realize authored visual presentation; 24 — Arm assessments from realized output.

**Status:** ready-for-agent

- [ ] Publish a state-ownership matrix covering every durable and session-continuity field.
- [ ] Give each Module only the immutable typed view required by its Interface.
- [ ] Validate every State Change against semantic ownership and cross-state invariants.
- [ ] Remove raw shared-state mutation from Feature Modules, the coordinator, and compatibility adapters.
- [ ] Preserve working-projection visibility and one atomic Turn Commit.
- [ ] Add automated checks for forbidden Feature Module implementation imports, direct state writes, duplicate policy, and feature policy inside the coordinator.
- [ ] Add failure tests for ownership violations, conflicting changes, stale projections, invalid transitions, and commit failure.
- [ ] Pass the frozen oracle and all Module-interface tests with enforcement enabled.

