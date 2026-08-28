# 03 — Problem-detection slice

**What to build:** A complete path for "is the learner stating a problem": `observe()` fills
`ProblemReading` on normalized text, and the two consumers that used `analysis["problem_cue"]` now read
`observation.problem`. Two suppliers of one fact — the pattern that produced four disagreeing copies —
becomes one.

**Blocked by:** 01.

**Status:** done (e3a3b00)

- [x] `detect_student_problem` migrated from raw to **normalized** input, unchanged in logic, as
  `ProblemReading` (`is_problem`, `directive`, `cue: ProblemCue` ∈ {equation, expression,
  solve_verb+numerals}).
- [x] Compute-and-mark deferral: `ProblemReading` is marked (not skipped) on an unauthorized transcript.
- [x] `analysis["problem_cue"]` **deleted, not mirrored**; its two consumers read `observation.problem`;
  the inline `student_problem` line reads `observation.problem` (its fusion is the future layer's).
- [x] `retrieval/interface.py` reads the observation instead of `interaction["text"]`.
- [x] Expected-diff rows for `detect_student_problem` (raw→normalized), symmetric; fixtures for each
  `ProblemCue` (equation / expression / solve-verb+numerals) in the conformance suite; green in CI.

## Code-review findings (e3a3b00, 2026-08-28)

**Standards — addressed:**
- `_pr` renamed to `problem` at both consumer sites
- `ProblemReading.is_directive_problem` property centralises the null-guard `is_problem and directive`
  test that appeared in 3+ call sites
- `ProblemReading.absent()` factory names the zero-reading sentinel (was constructed raw in 4 places)

**Spec — addressed:**
- Reverted ticket-04 scope creep: `_reference()` / `_ANAPHOR_RE` / 5 anaphora fixture rows / 3
  concept-fallback removals in `legacy_adapter.py` — all deferred to their owning tickets
- `retrieval/interface.py` fallback comment updated: `interaction["text"]` is the migration
  glide-path; deleted once all call sites supply `normalized_text`

**Non-findings:**
- "marked (not skipped)" — `ProblemReading.absent()` in the unauthorized branch is the mark;
  "not skipped" means the slot is always filled (no None/KeyError). Correct as implemented.
- Fixture symmetry — 3 expected_diff rows present and correct; reviewer lacked fixture content.
