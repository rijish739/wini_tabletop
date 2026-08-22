# 17 — Extract Prior Assessment and Evidence

**What to build:** The `AssessmentEvidence` Feature Module owning item verification, prior attempt grading, grading contracts, and idempotent evidence generation.

**Blocked by:** 16 — Extract Perception.

**Status:** resolved

- [x] Extract `assessment_evidence/interface.py`.
- [x] Implement prior attempt evaluation with typed `AssessmentResult` and `GradeResult`.
- [x] Enforce single-writer idempotent event generation.
- [x] Connect assessment candidate preparation for grounded items.
- [x] Pass assessment evidence unit tests in `assessment_evidence/tests/`.

## Resolution

- Implemented `cloud_run_service/assessment_evidence/` with robust grading validity and idempotent outcome generation.
