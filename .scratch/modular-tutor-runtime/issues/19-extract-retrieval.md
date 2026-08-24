# 19 — Extract Retrieval

**What to build:** The `Retrieval` Feature Module owning grounded evidence selection, vector similarity, prerequisite bridge lookups, misconception extraction, served history filtering, and cohesion validation.

**Blocked by:** 18 — Extract Pedagogy.

**Status:** resolved

- [x] Extract `retrieval/interface.py`.
- [x] Implement `RetrievalInterface` returning typed `RetrievalOutcome` and `EvidenceManifest`.
- [x] Preserve vector embedding, ranking, and cohesion judge integration.
- [x] Pass retrieval unit tests in `retrieval/tests/test_retrieval.py`.

## Resolution

- Implemented `cloud_run_service/retrieval/` package with full test suite passing in `retrieval/tests/test_retrieval.py`.
