# 19 — Extract Retrieval

**What to build:** A deep Retrieval Module that produces a grounded provenance manifest appropriate to the pedagogical decision and learner-state view.

**Blocked by:** 18 — Extract Pedagogy.

**Status:** ready-for-agent

- [ ] Expose one Retrieval Interface used by the coordinator and Interface-level tests.
- [ ] Preserve prerequisite bridge precedence, probe-before-correction evidence, need modes, ranking, served-history filtering, cohesion, and provenance.
- [ ] Consume immutable concept, mastery, misconception, representation, and served-history views.
- [ ] Return a typed grounded manifest and proposed served-evidence State Changes without writing state directly.
- [ ] Emit typed Failure Signals for missing stores, unavailable embeddings, invalid evidence, and cohesion failure.
- [ ] Ensure retrieval failure cannot create assessed or ungrounded generated output.
- [ ] Verify bridge, misconception, explanation, example, practice, transfer, representation, empty-result, and degraded scenarios through the Module Interface and compatibility façade.
- [ ] Remove migrated retrieval policy from the legacy adapter while keeping the equivalence oracle green.

