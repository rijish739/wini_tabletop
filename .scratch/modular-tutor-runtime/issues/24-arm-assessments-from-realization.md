# 24 — Arm assessments from realized output

**What to build:** The completed outbound Assessment and Evidence path, which arms a verified assessment only when the approved response plan and Presentation's Realization Receipt prove the learner received an assessable item.

**Blocked by:** 17 — Extract prior-attempt assessment and evidence; 20 — Extract Response Planning; 23 — Realize authored visual presentation.

**Status:** ready-for-agent

- [ ] Finalize the Assessment and Evidence public façade for both prior-attempt evaluation and new-assessment arming.
- [ ] Accept only verified items and approved assessment proposals.
- [ ] Require a matching successful Realization Receipt before arming pending assessment state.
- [ ] Void or decline assessment when realization is missing, partial, altered, unverified, interrupted, or failed.
- [ ] Preserve single-writer enforcement for pending assessment state and durable evidence.
- [ ] Produce typed State Changes and Failure Signals without direct state mutation.
- [ ] Verify spoken, displayed, generated, unrealized, mismatched, duplicate, interrupted, and degraded assessment scenarios end to end.
- [ ] Remove all remaining assessment-arming policy from response and legacy implementations while keeping the equivalence oracle green.

