# Phase 1 — Developer Query Responses (T1–T7)

> Answers to `implementation_task_query_from_developer.txt`, covering the data / label /
> HOPE tasks (T1–T7) — "Phase 1" (through the pedagogy & pacing models). **Every answer was
> verified against the actual code/data, not the markdown reports.** Source locations are cited
> as `file:line` so each claim is checkable.
>
> Ground-truth scan performed on the live tree: `tutor_loop.py`, `learner_state.py`,
> `wini_ui_server.py`, `cognitive_classifier/{cues,curate_dataset,label_space}.py`,
> `policy_shadow/shadow.py`, `hope_detector/{features,clean_bank}.py`,
> `build_local_datasets.py`, and the data files `rag_store/learning_log.jsonl`,
> `rag_store/hope_prompt_bank.jsonl`, `rag_store/hope_gold_set.jsonl`,
> `dataset/{grounding_guard,misconception_clue_bank,representation_tagger}.jsonl`.

---

## T1 — Capture real learner-conversation logs

### Q1. Does the UI already have `student_id_hash` / `session_id`, or must they be built?
**Must be built — neither exists today.**
- `TutorLoop.__init__` takes a single `state_path` (`tutor_loop.py:353`) and the log writer
  `_log()` emits only: `ts, loop, question, action, action_reason, need, shadow_suggestion,
  signals, cognitive_update, concept, writeback, hope_update, manifest`
  (`tutor_loop.py:642-650`). **No `student_id_hash`, no `session_id`.**
- `wini_ui_server.py` uses one global `STATE_PATH = learner_state.json`
  (`wini_ui_server.py:29`, `:39`) shared by all callers. There is no login, roster, or
  per-browser session identity anywhere.
- **What to do:** the UI/server must mint a `session_id` per conversation (e.g. a UUID at
  session start) and a `student_id_hash` (hash of a login/roster id, or a device id while
  single-user). Until multi-student exists, stamp a constant `student_id_hash` + a
  per-process `session_id` so the schema is correct from day one.

### Q2. How are the `short_term_outcome` fields (next-answer-correct / confusion-reduced / hint-used) provided?
**They are derived next-turn from signals the loop already computes — not a new model.**
- *next_answer_correct*: already produced when a pending check closes — `judge_answer` →
  `apply_probe_result`/`apply_bridge_result` returns correct/partial/wrong, surfaced as
  `writeback` (`tutor_loop.py:632, 648`).
- *confusion_reduced*: `cognitive_update.confusion` is computed every turn
  (`tutor_loop.py:646`); compare turn *N+1* vs *N*.
- *hint_used*: a `HINT_LEVEL_k` action / `record_hint_request` is already tracked
  (`tutor_loop.py:419-427`).
- **What to do:** add a small **deferred-attribution** step. Give each turn a `turn_id`; when
  turn *N+1* resolves, write `short_term_outcome = {next_answer_correct (from writeback),
  confusion_reduced (Δconfusion<0), hint_used (bool)}` back onto turn *N*'s log row. This is
  bookkeeping over existing signals; the only missing primitive is a `turn_id` to point back at.

### Q3. Is the listed work (tutor_loop fields / `collect_delayed.py` / learner_state per-student / device_config) done or pending?
**All four are pending. Verified:**
| Item | State (ground truth) |
|---|---|
| `tutor_loop.py` log fields | **Pending** — `_log()` lacks turn_id / ids / outcomes (`tutor_loop.py:642-650`). |
| `collect_delayed.py` | **Does not exist** (file listing confirmed). Must be created. |
| `learner_state.py` per-student / delayed timing | **Pending** — single `learner_state.json`, no per-student files, no delayed-test timing (`learner_state.py:312-323`). |
| `device_config.py` | **Not present in this repo** — it was created on the *Jetson* copy (build plan Part 9 / voice doc §12.3). For Windows you must add it or port the Jetson one. |

### Q4. Is `learning_log.jsonl`'s schema correct? What should change?
**Good for runtime audit, insufficient for training, and currently heterogeneous.**
- 83 rows today; the **first rows are an older `query.py` format** (have `need`/`manifest` but
  no `loop`/`action`), later rows are `tutor_loop_v4`. So the file mixes two schemas — a join
  hazard.
- Per report §2.1 the training turn schema needs, and the log is **missing**: `turn_id`,
  `student_id_hash`, `session_id`, `learner_state_before` / `learner_state_after` snapshots,
  `short_term_outcome`, `delayed_outcome`, and the `teacher_action` vs `model_action` split.
- **What to do:** add those fields; stamp a `schema_version`; do a one-time pass to tag/segregate
  the legacy `query.py` rows. Keep it append-only. The `manifest` + `cognitive_update` already
  present mean most of report §2.1 is *free* once the identity + outcome fields are added.

---

## T2 — Add the `acknowledgment` label and re-curate

### Q1. The markers in `cues.py` (`because`, `but`, `since`) are regex — isn't that brittle? How to generalize?
**The regex is not the classifier — generalization comes from MiniLM, and the regex stays only as a guardrail.**
- `cues.py` regexes serve two narrow roles (`cues.py:1-13`): (a) deterministic **gold rules**
  for *only three* labels — `question`, `request_hint`, `simplification_request`; (b) **9 binary
  auxiliary features** appended to the embedding (`CUE_NAMES`, `cues.py:87-90`). The bulk of
  classification is **semantic** (frozen MiniLM knn + logistic head). `is_pure_ack`
  (`cues.py:109-120`) is a separate *runtime* safety cue for the pedagogy rule, not a training
  label.
- **What to do:** add `acknowledgment` as a normal **semantic** label learned from examples — it
  then generalizes to unseen phrasings (MiniLM embeds meaning). Keep `ACK_RE`/`is_pure_ack` only
  as (i) an optional auxiliary cue and (ii) the runtime override that prevents re-explanation
  even if the model misses a novel ack. *Gotcha (CLAUDE.md):* adding a new **cue feature** changes
  `CUE_NAMES` width and forces a rebuild of **both** the classifier and the policy shadow; adding
  only a **label** keeps the cue width but still needs a bank rebuild.

### Q2. Separate confusion from acknowledgment? Remove "multiple confusion labels"?
**There is only one `confusion` label — nothing to de-duplicate.**
- Curation report shows a single `confusion` (3,807 rows); there are no duplicate confusion
  labels. The real problem is acks being *mislabelled into* `confusion`/`low_confidence` (the
  documented MiniLM polarity issue, `cues.py:109-117`).
- **What to do:** add a curation rule in the existing `curate_dataset.py`: *if `is_pure_ack(utt)`
  → ensure `acknowledgment` is present and remove `confusion`/`low_confidence`*. This mirrors the
  existing deterministic gold rules for `question`/`request_hint` (`curate_dataset.py:49-90`).
  Do **not** remove the `confusion` label globally.

### Q3. Do we need to create a `curate_dataset.py`?
**No — it already exists:** `cognitive_classifier/curate_dataset.py`, with the gold-rule
framework and a `curate_row()` already exported for reuse by augmented rows
(`curate_dataset.py:44-90`). Extend it (the ack rule above) + `label_space.py` (register
`acknowledgment`) + author ~300–500 ack examples, then `python -m cognitive_classifier.build_bank`
and rebuild the policy shadow.

### Q4. For "I understood but why x=2?" — does it learn `x=2` literally, or generalize?
**It generalizes; `x=2` is never special-cased.**
- The classifier embeds the sentence with MiniLM (meaning, not tokens); no rule keys on `x=2`.
- `is_pure_ack("i understood but why x=2")` → **False** because it contains `but` and the WH-word
  `why` (`cues.py:106, 119-120`), so it is correctly treated as *ack + follow-up question*, which
  routes to answering the "why", not re-explaining.
- **What to do for safety:** when authoring/generating ack examples, vary the surface tokens
  (different variables, numbers, contexts) — the same isomorphic principle the problem-schemas
  use — so the bank can never overfit a literal like `x=2`.

---

## T4 — Normalize off-action-space policy tags

### Q1. Is it wrong to drop multi-actions / rename / drop RESUME_STATE & REQUEST_HINT?
**Mostly defensible for the *current* single-label shadow, with one merge to re-examine.** Ground truth in `policy_shadow/shadow.py:33-41`:
- **Multi-action → first only** (`re.split("[,+]")[0]`): a simplification because the shadow is a
  single-label softmax. Acceptable for v1 imitation (first-listed = documented primary), but it
  *discards* the secondary action. Better long-term: keep secondaries in a separate column for a
  future multi-label/next-action policy.
- **`VERBAL_ANALOGY → VISUAL_ANALOGY`**: ⚠️ **re-examine.** These are arguably *different* moves —
  `VISUAL_ANALOGY` serves a figure crop, a verbal analogy is spoken. Once the display channel
  (task T9) exists, the distinction is real and the merge would erase a separable action.
- **Drop `RESUME_STATE` / `REQUEST_HINT`**: correct. `RESUME_STATE` is session mechanics, and
  `REQUEST_HINT` is a *student* action, not a *tutor* action — neither belongs in a tutor policy.
- **Audit/diff + new file**: correct and should stay (originals are read-only by mandate).

### Q2. Shouldn't a genuinely new action be *added* rather than force-fit/dropped?
**Yes.** Normalizing spelling/variants and *adding genuinely new moves* are not in conflict:
- Normalize true duplicates/variants (T4), but if a row encodes a real tutor move absent from the
  action set, **extend the action space** — add it to the vocabulary, give it enough examples
  (report §6.3), wire it into `rules_decide` if reachable, and propagate to the lockstep docs.
- **Heads-up (found while checking):** report §6.1 lists **17** actions, but the shadow trains on
  **15** clean dataset actions (`shadow.py` header). `VERBAL_ANALOGY` is exactly the kind of move
  better *added* than merged. Reconcile the 15-vs-17 action space when you revisit this.

---

## T5 — Scale the seed-level derived datasets

### Q1. During live learning, how/where do you label "leak" and grounding?
**Automatically, by validators over data the loop already emits — no per-turn human labeling.** Ground truth: `grounding_guard.jsonl` labels are `safe_hint 2724 / answer_leak 338 / grounded 261 / unsupported 261`, all built deterministically (`build_local_datasets.py`).
- **Grounding:** every response is composed *only* from its manifest (`tutor_loop.py:649`,
  architecture Rule 12). Log the `(response, manifest)` pair and run an automatic claim-coverage
  check → `grounded` vs `unsupported`.
- **Leak:** hints are served from precomputed `hint_chain`s; the same **answer-leak regex +
  expected-answer-containment** check used at build time flags a leak. Log that boolean per hint.
- So both labels are *derived*, appended to each turn; humans only spot-audit. These auto-labels
  then train the grounding-guard classifier (task T16).

### Q2. One tag or two for hard-negative vs near-miss? How many samples?
**Today it's ONE label field with three values — and `near_miss` is not one of them.** Ground truth: `misconception_clue_bank.jsonl` `label ∈ {positive 676, hard_negative 552, error_explanation 276}`.
- `hard_negative` = correct reasoning using the *same vocabulary* (the model must **not** flag it).
- `near_miss` (a *partial/almost*-misconception) is a **different** thing and is **not** present.
  They should be **separate** classes — add a 4th value `near_miss`, generated by perturbing the
  `diagnostic_question` + `expected_answer`. Don't conflate them.
- **Volume:** report §4.4 targets **≥100 examples per misconception family**; with 276 families
  that's ~27,600 for a strong prototype. Current seed averages ~2–2.5 per family (seed-level only,
  store exhausted). Keep roughly **positive : hard_negative ≈ 1:1**, plus a smaller `near_miss`
  set (~half). Real scaling needs generation (local Qwen) or real logs (T1).

---

## T6 — Replace HOPE rater B with human-teacher labels

**Developer's hunch is correct on the dropping — here is exactly what's done vs pending (verified in the data):**
- ✅ **Done:** the `rewrite_or_drop` prompts are **already removed**. `hope_prompt_bank.jsonl`
  is now **997 rows** (was 1034) with **0** rows carrying `status: rewrite_or_drop`; the gold set
  is **888 answers** (was 1036, 148 dropped). This was `clean_bank.py` (backups `*.prehope.bak`).
- ❌ **Pending #1 — teacher labels:** the gold answers carry `rater_a`, `rater_b`, `final_label`
  only, where `final_label = round((rater_a + rater_b)/2)` and **both raters are LLMs**
  (rater B = gemini-2.5-pro). **There is no teacher column.** The κ ≥ 0.6 gate that passed is
  therefore LLM–LLM agreement, not teacher agreement.
- ❌ **Pending #2 — expert-review answers:** **12** answers still flagged `needs_expert_review`
  (|A−B| ≥ 2) remain unresolved. (The reports say 18; after the 148-answer cleanup, **12**
  remain — corrected against the data.)
- ❌ **Pending #3 — scope of the human round:** only **28** bank rows carry a `human_hope_rating`,
  and that round was a 30-prompt **quality audit**, *not* a full answer re-label.
- **What to do:** a teacher re-labels the 888 gold **answers** (or at least a stratified
  calibration subset), resolves the 12 flagged answers, then re-derive `final_label` from the
  teacher labels and recompute κ(teacher, ·) ≥ 0.6 before any scaling → feeds T7.

---

## T7 — Retrain HOPE detectors + fix calibration

### Q1. Do we retrain the HOPE metrics?
**Yes — after T6.** Rerun `hope_detector/build_detector.py` on the teacher-relabelled gold.
Detectors are per-signal ordinal logistic heads (KI/KT/CT; bridge folds into KT), split by
prompt 70/15/15, features = **answer-only** MiniLM embedding + 5 scalars (`features.py`).

### Q2. How to fix relative-vs-absolute scoring?
**Relative is already correct and is all w7 needs; absolute needs a calibration layer on real labels.**
- Detector scores are conservatively calibrated on *synthetic* gold (runtime memorized→0.06,
  strong→1.86); fine for `w7` ranking which only needs the **weakest** signal boosted (relative
  order), wrong for any absolute threshold.
- **What to do:** fit a **per-signal isotonic regression (or Platt scaling)** mapping raw score →
  calibrated 0–3, trained on the **teacher-labelled** answers (T6). Keep the raw score for `w7`;
  expose the calibrated score for any absolute decision. Report **calibration error (ECE)** as an
  acceptance metric, alongside the existing QWK and the strong−memorized gate.

### Q3. How to distinguish a genuinely "strong" answer from a "memorized" one?
**This is already engineered into the features and rubric — keep and strengthen it, don't rely on the raw embedding.** Ground truth in `features.py:1-40` + `hope_rubric.md`:
- The documented failure mode: embedding prompt+answer+rubric together makes a prompt's four
  answer levels embed almost identically (QWK 0.04–0.27, gate fails). The fix that works:
  - **`cos(answer, rubric_anchor)`** — the rubric anchor encodes the *target idea*; a memorized
    formula restatement aligns **low**, a real translation/transfer aligns **high**. This is the
    key separator.
  - **`cos(answer, prompt)`**, **log word count** (strong answers ~2× longer: 78 vs 36 words),
    **reasoning-marker count** (because/therefore/since…), **math-token count**.
  - The **rubric hard-caps** memorized recall at ≤1 on KI, surface analogy at ≤1 on KT,
    unjustified curiosity at ≤1 on CT.
  - The **discrimination gate** `strong − memorized ≥ 1.0` is enforced and passes (1.65/1.29/1.81).
- **What to do to keep it honest:** (a) keep the `rubric_anchor` feature; (b) ensure every prompt
  in the gold has a **memorized-level** answer so the model always sees the contrast; (c) keep the
  discrimination gate in the acceptance criteria; (d) teacher labels (T6) make the memorized=1 /
  strong=3 boundary authoritative instead of LLM-guessed.

---

## Summary table — what's actually done vs pending

| Query | Verified state |
|---|---|
| T1.Q1 student/session id | **Not built** (no fields in `_log`; UI has no identity) |
| T1.Q2 short_term_outcome | Derivable from existing signals; needs `turn_id` + deferred-attribution writer |
| T1.Q3 tutor_loop/collect_delayed/learner_state/device_config | **All pending**; `collect_delayed.py` & `device_config.py` don't exist here |
| T1.Q4 log schema | Works for audit; **heterogeneous + missing** training fields |
| T2.Q1 regex generalization | Classifier is semantic; ack should be a learned label, regex stays as guardrail |
| T2.Q2 confusion vs ack | Only one `confusion` label; add ack + curation rule to strip spurious confusion |
| T2.Q3 curate_dataset.py | **Already exists**; extend it |
| T2.Q4 `x=2` | Generalizes (semantic); never literal |
| T4.Q1 normalization | OK for v1; **re-examine VERBAL→VISUAL merge** |
| T4.Q2 add new action | Yes, extend the space for genuinely new moves; note 15-vs-17 mismatch |
| T5.Q1 leak/grounding labels | Auto-derived from manifest + hint-chain validators |
| T5.Q2 hard_negative vs near_miss | One field, 3 values today; `near_miss` absent → add as 4th; ~100/family target |
| T6 rewrite/drop | **Dropping DONE** (997 rows, 0 left); **teacher relabel + 12 expert answers PENDING** |
| T7.Q1 retrain | Yes, after T6 |
| T7.Q2 relative/absolute | Relative OK for w7; add isotonic/Platt calibration on teacher labels |
| T7.Q3 strong vs memorized | Handled by rubric_anchor alignment + length + reasoning markers + rubric caps + gate |
