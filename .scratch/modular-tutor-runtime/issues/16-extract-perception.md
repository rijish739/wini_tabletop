# 16 — Extract Perception

**What to build:** A deep Perception Module that turns an admitted Turn into validated intent, cognitive-signal, concept, and safety observations without owning state persistence or runtime recovery policy.

**Blocked by:** 14 — Route the legacy runtime through the typed coordinator.

**Status:** ready-for-agent

- [ ] Expose one Perception Interface used by the coordinator and Interface-level tests.
- [ ] Preserve deterministic gates, structured model observation, concept cross-checking, confidence thresholds, and validation.
- [ ] Return observations and permitted soft State Changes instead of writing Learner State or Session State directly.
- [ ] Emit typed Failure Signals for timeout, unavailable backend, invalid schema, and degraded fallback.
- [ ] Preserve the established deterministic-gate, inherited-concept, and neutral-signal degraded outcome when valid.
- [ ] Use the shared Model Gateway port only for transport concerns while retaining perception prompts and schemas inside Perception.
- [ ] Verify safety, nonsense, learning, concept inheritance, and degraded scenarios through both the Module Interface and compatibility façade.
- [ ] Remove migrated perception policy from the legacy adapter while keeping the equivalence oracle green.

