# 24 — Arm assessments from realization

**What to build:** The authoritative assessment arming seam ensuring newly proposed items are armed only after a verified `RealizationReceipt` proves the question was delivered to the learner.

**Blocked by:** 23 — Realize authored visual presentation.

**Status:** resolved

- [x] Implement `arm_from_script` validation matching candidate items against realized speech beats.
- [x] Void assessment hooks if answers leak or delivery fails.
- [x] Pass P0 invariant tests for exact item delivery and anti-leak verification.

## Resolution

- Integrated authoritative arming logic in `response_layer/arming.py` and `assessment_evidence/interface.py`.
- Passed all arming tests in `test_p0_evidence.py`.
