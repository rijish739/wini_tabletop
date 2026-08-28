# Retire the 9-cue vector and the policy shadow

Status: open
Type: implementation
Blocked by: 04
Owner: TBD — deliberately outside this map's spec (user decision, 2026-08-26)

## Question

Ticket 04 deleted every runtime *call site* of `cognitive_classifier/cues.py` but left the
file byte-identical, because two runtime modules still import it. This ticket retires them.

**Scope is the 9-cue vector + the policy shadow, NOT `cognitive_classifier/`.**
`classifier.py` survives: `concept_resolver/resolver.py:29` imports `score_labels_knn`,
`hope_detector/detector.py:21` imports `MODEL_NAME`, and CLAUDE.md keeps retrieval
embeddings and the HOPE detectors on MiniLM deliberately.

## What is actually entangled

- `cue_matrix` runs every turn: `classifier.py:185` inside `classify()`, reached from
  `cognitive_analyzer/analyzer.py:229`.
- `policy_shadow/shadow.py:79` calls it again from `suggest()`, unconditionally at
  `tutor_loop.py:2463` — and the result is **only logged** (`shadow_suggestion`). A whole
  MiniLM embed + score pass per turn for a log line.
- `analysis["scores"]` from `classify()` feeds `derive_cognitive_update` /
  `derive_state_deltas`. Removing the classifier is a **state-math** decision, not a cleanup.
- The logreg head's weights were fit **with** the 9 cue dims (recovered `build_bank.py:210-219`
  hstacks them). Dropping the dims requires a re-fit or a zero-fill — and
  `build_bank.py` / `curate_dataset.py` / `build_policy.py` were lost in `5b847a1`
  (recoverable at `5b847a1^`), so there is no rebuild path in the tree today.

## Decisions to close

- Does `PolicyShadow` survive at all, given its only consumer is a log line?
- Does the exemplar classifier keep producing `scores` for the state math, or does
  Perception's Gemini call become the sole source?
- If the cue dims go: re-fit (restore `build_bank.py` first) or zero-fill?
- What replaces the `cues.py` header comment's warning once the file is gone?

## Inherited debt

- **Accepted billing regression (ticket 04, 2026-08-26):** the Part 15 Phase B speculative
  pre-gate (`wini_server.py:574`) lost its `is_pure_ack` / `is_question` skips, so every
  armed `pending_check` now bills a `judge_answer` call on pure acks and bare questions.
  This layer decides whether to restore a cheaper skip.
- **Accepted silent-failure risk (ticket 04):** `cues.py` has a header warning and no test.
  An edit to a cue regex shifts the feature vector with no crash and no failing test.
- **Root `run_wini_package.sh`** was left in place by ticket 04's delete-only commit
  (`Wini.desktop` points at a device checkout, `/home/winipi5/cloud_tutor/cloud-CLI/`,
  whose layout was not verifiable). Confirm and delete, or keep deliberately.
- **CLAUDE.md:67-69, 124-126** document `curate_dataset.py`, `build_bank.py` and
  `build_policy.py` as live commands. They do not exist.
