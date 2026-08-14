# Complete Architecture — Build Plan

Execution plan for implementing `learner_cognitive_state_architecture.md` end-to-end.
Derived from the architecture doc, `model_dataset_architecture_report.md`, and the finished
RAG store work (`rag_memory.md`: 18/18 scorecard PASS, schema v2, 1,017 chunks, 3,562 nodes).

Date: 2026-06-11. Scope: Class 10 Maths only (NCERT, 108 concepts).

---

## 0. What already exists (do not rebuild)

| Layer (architecture §) | Artifact | Status |
|---|---|---|
| Curriculum Knowledge Graph (§6.5) | `rag_store/` concepts.json + graph.json, schema v2, enriched | DONE |
| Class-9 bridges (§6.8) | 62 `grade9_concept` nodes, gating in `learner_state.py` | DONE |
| Schemas / hint chains / metacog (§6.9) | 245 schemas, 908 hint chains, prompts on all 108 cards | DONE |
| Learner State Model v1 (§6.4) | `learner_state.py` (probe/bridge write-backs, struggle, snapshot) | DONE |
| Retrieval Layer (§6.7) | `query.py` 7-term ranking, provenance manifest, cohesion check | DONE |
| HOPE prompt bank + gold set | 1,034 prompts, κ ≥ 0.75 LLM–LLM calibration | DONE (rater B = LLM caveat) |
| Cognitive Input Processor (§6.1) | `cognitive_input_processor/input_processor.py` — normalization + heuristic signal scores + `SemanticClassifier` protocol | DONE (heuristic only) |
| Exemplar dataset | `dataset/exemplar_dataset_10000.json` / `.csv` — 10,000 labeled utterances | DONE |

The missing pieces are the **neural/semantic models** and the **runtime loop that wires
everything together**. That is what this plan builds.

---

## 1. Dataset ground truth (profiled 2026-06-11)

`dataset/exemplar_dataset_10000.json` — 10,000 rows, fields:
`student_utterance, concept_id, miniLM_labels, hope_signals, target_policy_action, category`.

- 9 scenario categories, ~1,111 rows each. No duplicate utterances. Mean 20 words/utterance.
- `concept_id`: 98 valid store IDs + `INHERIT_CURRENT_CONCEPT` (3,912 rows — context-dependent).
- `miniLM_labels`: multi-label, 48 raw labels. Head: confusion 3,807 · question 2,399 ·
  low_confidence 2,377 · procedural_focus 1,942 · curiosity 1,907. Tail: 12 labels < 20
  occurrences, several spelling/name variants → must be canonicalized (Part 1, §2.2).
- `target_policy_action`: 27 raw values; 15 clean actions ≥ 97 rows each; ~17 rows carry
  messy multi-action strings (`"ENCOURAGE + REVIEW"`) → canonicalize before policy training.
- `hope_signals`: free-ish text with casing variants (`Recurring Misconception` vs
  `Recurring misconception`) → canonicalize before use as weak supervision.

This one dataset supervises THREE models: the cognitive signal classifier (Part 1), the
concept resolver (Part 2 — `concept_id` column), and the pedagogy policy v1 (Part 5 —
`target_policy_action` column).

**Canonical source moved 2026-06-19.** `dataset/exemplar_dataset_10000_fixed.json` is now
THE dataset of record: 10,000 audit-corrected base rows (external Gemini audit + an 11-rule
text-evidence second pass) + 800 T2/T3 supplementary rows carrying `split:"train"`.
`curate_dataset.py` reads it (no longer the raw file) and writes `exemplar_dataset_10000_curated.json`,
the gold-rule projection that build_bank / build_policy / concept_resolver consume. The raw
`exemplar_dataset_10000.json` profiled above is archived under `dataset/archive/` (provenance only).

---

## 2. PART 1 — MiniLM exemplar cognitive classifier  ← BUILDING NOW

Report §3. The semantic replacement for the regex heuristics in `input_processor.py`.

### 2.1 Architecture (per report §3.2)

```text
student utterance
→ all-MiniLM-L6-v2 embedding (normalized)
→ cosine similarity vs exemplar bank (train split embeddings)
→ weighted k-NN evidence per label: p(L) = Σ sim(n) for neighbors with L / Σ sim(n)
→ per-label thresholds calibrated on validation split (max-F1)
→ thresholded multi-label signal set + top evidence exemplars
```

No fine-tuning. The "model" is: frozen MiniLM + exemplar bank + thresholds. k is tuned on
validation over {8, 16, 32, 64}. An optional logistic-regression second stage (report says
wait for 15k examples) is evaluated as a comparison baseline only, not shipped as primary.

### 2.2 Label canonicalization

48 raw labels → 38 canonical (was ~36; `acknowledgment` added 2026-06-19 as its own
canonical label for positive-confirmation utterances — see §2.5.2). Merge map
(variants/singletons folded into the nearest canonical label, documented in
`cognitive_classifier/label_space.py`):
`recurring_misconception→recurring_error`, `prerequisite_weakness_clue→prerequisite_weakness`,
`self_deprecation→low_confidence`, `visual_analogy→request_representation`,
`surface_engagement→disengagement`, `application_*→physical`, `logical→abstraction_attempt`,
`strategic_learning/productive_struggle→self_monitoring`, `active_engagement→curiosity`.
Labels still below MIN_SUPPORT=40 after merging are dropped from the label space.

### 2.3 Splits

80/10/10 train/val/test, seeded, stratified on the primary (first) label with rare labels
pooled, drawn over the 10,000 base rows only. Splits saved to
`models/exemplar_classifier/splits.json` so every later model trained on this dataset uses
the SAME test rows (no leakage across Parts 1/2/5). **Regenerated 2026-06-19** when the source
moved to `_fixed.json` (the prior frozen split was stratified on the old curated-from-raw
labels; 893/999 test rows changed). The 800 supplementary rows (`split:"train"`) and the 1,331
`augmented_rare_labels.json` rows are TRAIN-ONLY and never enter val/test.

### 2.4 Deliverables

```
cognitive_classifier/
  __init__.py
  label_space.py      # canonical label map + canonicalize()
  classifier.py       # ExemplarCognitiveClassifier (runtime) + SemanticClassifier adapter + CLI
  build_bank.py       # split → embed → tune k → calibrate thresholds → eval → save artifacts
models/exemplar_classifier/
  bank_embeddings.npy   bank_meta.jsonl   label_space.json
  thresholds.json       splits.json       eval_report.md
```

`MiniLMSemanticClassifier` in `classifier.py` implements the `SemanticClassifier` protocol so
`InputProcessor(classifier=...)` upgrades from regex to semantic with one constructor arg.
(Protocol label `explanation` has no dataset counterpart → returns 0.0; the processor's
max-merge keeps the heuristic for it. `answer_attempt` has only 62 examples — flagged thin.)

### 2.5 Acceptance criteria and RESULTS (built 2026-06-12)

Built. Shipped scorer = **knn+logreg ensemble** (weighted 8-NN posterior averaged with a
one-vs-rest logistic head on frozen embeddings; both candidates and the report-style
per-label evidence scorer were compared on validation — the evidence scorer lost badly,
0.39 val macro, because dense synthetic data gives every label a close positive).

| metric | target | actual (test, n=999) |
|---|---|---|
| micro-F1 | ≥ 0.75 | **0.69** |
| macro-F1 | ≥ 0.60 | **0.55** |
| head labels F1 | ≥ 0.75 | confusion 0.75 ✓ · curiosity 0.76 ✓ · request_representation 0.81 ✓ · physical 0.89 ✓ · question ~0.62 ✗ · request_hint ~0.33 ✗ |
| latency | < 50 ms | ~115 ms avg incl. warmup (acceptable) |

Verdict (first build): usable for the analyzer (head signals reliable), below target on
the long tail. Diagnosed as four stacked problems and fixed on 2026-06-12:

### 2.5.1 The four fixes (second build, all shipped)

1. **Label-ontology repair** (`curate_dataset.py` → `exemplar_dataset_10000_curated.json`,
   original untouched): `request_hint` redefined as a deterministic gold rule (explicit
   hint/steps/answer request, HINT_RE) — 266/279 old labels evicted and rerouted
   (example_request / request_representation / new `simplification_request`), 440 genuine
   requests pulled in from shortcut_seeking/hint_dependency rows.
2. **Rare-label masking**: (a) 9 binary surface-cue features (`cues.py`: wait/actually,
   answer-attempt phrasing, hint asks, …) appended to the logistic head's input — pooled
   sentence embeddings dilute 1–2-token signals; (b) 1,331 LLM-generated rows
   (`augment_rare_labels.py`, Vertex gemini-2.5-flash) where the rare label is PRIMARY,
   added to the train bank only; seeds from train rows only; all rows passed through the
   same curation rules (29 request_hint candidates auto-vetoed for missing hint phrasing).
3. **Threshold calibration** moved from the 999-row val split to 5-fold out-of-fold train
   predictions (~8× more positives per label), clamped to [0.10, 0.90].
4. **`question` made deterministic** (interrogative rule, `is_question`): 5,335 missing
   labels added, 16 spurious removed — the raw gold had omitted it on >half the questions.

| metric (test, n=999, curated gold) | target | build 1 | build 2 |
|---|---|---|---|
| micro-F1 | ≥ 0.75 | 0.64 | **0.77 ✓** |
| macro-F1 | ≥ 0.60 | 0.49 | **0.62 ✓** |
| question F1 | ≥ 0.75 | 0.62 | **1.00 ✓** (rule-governed) |
| request_hint F1 | — | 0.33 | **1.00** (rule-governed) |
| example_request F1 | — | 0.16 | **0.82** |
| confusion / curiosity F1 | ≥ 0.75 | 0.75 / 0.76 | 0.79 / 0.79 ✓ |

Still weak (test support too small to even measure reliably): answer_attempt (7 test
rows), self_correction (19), high_confidence (21, hurt by MiniLM's polarity blindness —
"so easy" embeds near "so hard"), hint_dependency (18), representation_shift (36).
These have augmented training support now; the honest blocker is **test-set support**,
which only more real (or held-out-quality) labeled data fixes. Note: build-1 vs build-2
numbers are not strictly comparable — build 2 is scored against the curated gold, which
is the point: the old gold was wrong.

### 2.5.2 Third build (2026-06-19): fixed-source re-point + T2/T3 (all shipped)

Two changes, rebuilt together:

1. **T2 — `acknowledgment` label.** Positive-confirmation utterances ("ok got it",
   "makes sense now") had almost no exemplars, so MiniLM's polarity blindness mislabeled
   them `confusion`. Registered `acknowledgment` in `label_space.py`; added a deterministic
   gold rule in `curate_dataset.py` (`is_pure_ack` ⇒ +acknowledgment, −confusion/−low_confidence);
   authored ~300 pure-ack rows. T3 — 100 each for the weak long tail (answer_attempt,
   self_correction, high_confidence, hint_dependency, representation_shift). All 800 are
   supplementary `split:"train"` rows in `_fixed.json`.
2. **Source re-point** — curate now derives from `_fixed.json` (audit-corrected labels)
   instead of raw; splits regenerated (§2.3).

Shipped scorer = **evidence+logreg** (selected by val macro-F1; the cleaner labels flipped
the winner from knn+logreg). 38 canonical labels; 12,131 rows used (10,000 base + 800 supp +
1,331 augmented in train).

| metric (test, n=999, fixed-derived gold) | build 2 | build 3 |
|---|---|---|
| micro-F1 | 0.77 | **0.83 ✓** |
| macro-F1 | 0.62 | **0.69 ✓** |
| representation_shift F1 | 0.44 | **0.82** (T3) |
| answer_attempt F1 | 0.30 | **0.71** (T3) |

Pure-ack smoke test on the shipped bank: "ok got it" → ack 0.95, "makes sense now" → 0.91,
confusion ≤ 0.25 (well under the 0.37 fire threshold); hard negatives ("yes but why x=2?")
correctly low. `acknowledgment` per-label test F1 stays noisy (6 natural test rows; the 300
authored acks are train-only) — same test-support blocker as the other rare labels.

---

## 3. PART 2 — MiniLM concept resolver (architecture §6.3, report §4.1) — BUILT 2026-06-12

Code: `concept_resolver/` (build_resolver.py, resolver.py). Artifacts:
`models/concept_resolver/` (anchor_embeddings, train_bank, logreg_resolver.npz, config,
eval_report.md). Frozen Part 1 splits reused; Part 1's augmented rows excluded (all INHERIT).

Two candidates calibrated on val, selected by combined = (top1_final + abstain_F1)/2:
blend (α·exemplar-kNN + (1−α)·card-anchor cosine; best α=0.3, k=16, τ=0.38 → 0.904) and
**multinomial logreg over 98 seen concepts + ABSTAIN class (shipped, 0.920)**.

| metric (test, n=999) | result |
|---|---|
| top-1 accuracy (explicit rows, n=619) | **0.895** |
| top-3 accuracy | **0.971** |
| abstain on INHERIT rows (n=380) | P 0.961 / R 0.984 / **F1 0.973** |
| error structure | 51/56 misses are same-chapter neighbors; 5 cross-chapter, all ambiguous |

Runtime: `ConceptResolver.load().resolve(text, current_concept=...)` → §6.3 schema
(primary + confidence + secondary + reason + `abstained`); abstain inherits the session
concept.

**Gap closure (2026-06-12):** the 10 store concepts with zero dataset utterances
(arithmetic_mean, trisection, angle_of_depression + the 7 jemh1a1/jemh1a2 appendix
concepts) were filled with 497 utterances generated by the **local Qwen2.5-3B via
llama.cpp on the GPU (Vulkan, port 8080)** — `concept_resolver/generate_gap_utterances.py`,
grounded in concept cards, keyword-validated, own 80/10/10 split field
(`dataset/concept_gap_utterances.json`; frozen Part 1 splits untouched). Rebuilt: bank
covers **108/108 concepts**; overall test top-1 0.894 / top-3 0.964 / abstain F1 0.968
(unchanged within noise); gap-concept slice top-1 **0.86** (50 held-out rows).
**Standing rule (superseded 2026-06-30 by the cloud pivot, see Part 11): generation was
local-Qwen-only; it is now `GEN_BACKEND`-selectable (qwen | gemini). The prompt is identical
either way; only the transport changes.**

## 4. PART 3 — Cognitive Analyzer assembly (architecture §6.2) — BUILT 2026-06-12

Code: `cognitive_analyzer/` (analyzer.py + test_analyzer.py). Pipeline per turn:
normalize (InputProcessor) → classify (Part 1) → resolve (Part 2) →
`derive_cognitive_update` (deterministic label→§6.2-aggregate formulas: confusion,
curiosity, confidence, misconception_probability, transfer/abstraction attempt,
self_correction, cognitive_load, engagement, frustration_risk) →
`derive_state_deltas` → `apply_deltas` (EMA 0.3 on the four persisted global fields +
per-concept flags: misconception_suspected / transfer_ready_evidence / hint_requested /
prerequisite_weakness_clue / frustration_risk / self_corrected).

Contract: the analyzer NEVER moves mastery or misconception status from text alone —
those stay with the evidence-driven learner_state.py APIs (apply_probe_result /
apply_bridge_result); the analyzer only flags suspicion for the pedagogy engine.

Verified: 4/4 unit tests (mapping formulas, flags, EMA application, stub assembly +
abstain-inheritance) and a 3-turn model integration run (misconception statement →
flag on resolved concept; overload utterance → load 0.85, global load EMA crossed 0.5).
CLI: `python -m cognitive_analyzer.analyzer "utterance" [--current-concept X]`.

Still open from the original Part 3 scope: `hope_signals` weak-supervision sanity sweep
of the mapping over the full dataset (nice-to-have validation, not blocking Part 7).

## 5. PART 4 — HOPE detectors (report §5) — BUILT 2026-06-12 (human review cleared)

Unblocked when the user supplied a human prompt-quality audit
(`rag_store/hope_bank_review_human.txt`, 30 prompts) and approved dropping the
non-discriminating prompts. Code: `hope_detector/` (clean_bank.py, features.py,
build_detector.py, detector.py); artifacts `models/hope_detector/`.

**Cleanup (`clean_bank.py`)**: dropped the 37 `status: rewrite_or_drop` prompts +
their 148 gold answers; attached the 28 joinable human ratings onto bank rows
(`human_hope_rating`, joined by position vs the ordered review sample with a
signal-consistency assertion). Backups `*.prehope.bak`. Bank 1034→997, gold 1036→888.
Per-signal still ≥300 (KI 318 / KT 313 / CT 315). verify_store.py updated: HOPE
total target 1000→950 + a new ≥300/signal gate; **scorecard still 100%**.

**Detector (`build_detector.py` + `features.py`)**: per-signal ordinal logistic head
(KI/KT/CT; bridge folds into KT). Key lesson — embedding prompt+answer+rubric together
fails (a prompt's 4 answer levels embed near-identically; QWK 0.04–0.27, gate FAILS).
Fix: embed the **answer alone** + standardized scalars (answer↔rubric cos, answer↔prompt
cos, log word count, reasoning markers, math tokens). Split by prompt 70/15/15, C tuned
on val by QWK. All local (MiniLM, GPU).

| signal | test QWK | adjacent acc | strong−memorized sep (gate ≥1.0) |
|---|---|---|---|
| KI | 0.527 | 0.679 | **1.65 PASS** |
| KT | 0.448 | 0.827 | **1.29 PASS** |
| CT | 0.651 | 0.865 | **1.81 PASS** |

The discrimination gate (a memorized answer must not score like a strong one — the
whole point of HOPE) passes on all three; QWK 0.45–0.65 (CT meets the 0.6 desideratum,
KI/KT below on small test sets). Runtime verified: memorized answer → 0.06, strong → 1.86.
`HopeDetector.load().score(signal, prompt, answer, rubric_anchor)` → {label, score, probs}.

**Label caveat (unchanged):** `final_label` = round((rater_a+rater_b)/2), both LLM
(raters agreed 84% exact / 98.6% within 1); the human round was a prompt audit + drop
decision, not a full answer re-label. Replace with teacher answer-labels before scaling.

**Wired live (2026-06-15, tutor_loop v4):** `learner_state.update_hope(signal, score_0_3)`
folds a detector score into the rolling KI/KT/CT average (EMA 0.4, normalized /3). The
loop arms `session.pending_hope` whenever it serves a CT/KT/KI probe (need ∈
challenge/transfer/integrate); the student's next attempt (not an ack, not a hint request,
≥4 words) is scored and folded in. Verified end-to-end: transfer probe → Qwen posed a
discriminant problem → student answer scored KT → rolling KT 0.50→0.44 → persisted →
feeds query.py ranking w7. **Calibration note:** the detectors discriminate well in
RELATIVE terms on free text (strong 1.4 > memorized 0.3 > weak 0.2) but are conservatively
calibrated in absolute terms (synthetic gold), so they shift all three signals similarly —
fine for w7, which boosts the weakest signal, not absolute thresholds.

## 6. PART 5 — Pedagogy policy (architecture §6.6, report §6) — SHADOW BUILT 2026-06-12, REBUILT 2026-06-19

Code: `policy_shadow/` (shadow.py, build_policy.py); artifacts `models/policy_shadow/`.
Actions canonicalized to the pedagogy set (`canonicalize_action`: multi-action → first
listed; VERBAL_ANALOGY → VISUAL_ANALOGY; RESUME_STATE/REQUEST_HINT dropped). Features =
exactly what runtime computes per turn: MiniLM emb (384) + Part-1 label scores + §6.2
update aggregates (10). Multinomial logreg.

**Rebuilt 2026-06-19** on the fixed-derived curated set (cleaner action labels: the audit
corrected ~6,900 actions) and now also trains on the 800 supplementary rows (632 enter
train after dropping non-pedagogy actions). 14 canonical actions, n_label_scores = 38.

| model | test top-1 (2026-06-12) | test top-1 (2026-06-19) | test top-2 |
|---|---|---|---|
| majority class | 0.196 | 0.405 | — |
| embedding only | 0.539 | 0.670 | 0.821 |
| full features (shipped) | 0.558 | **0.680** | **0.844** |

The jump (0.558 → 0.680 top-1; EXPLAIN F1 0.498 → 0.733) is the cleaner fixed action labels
plus the supplementary rows now reaching policy training. Still SHADOW MODE: `tutor_loop.py`
logs `shadow_suggestion` beside the rules' choice every turn; promotion only after it beats
rules on logged real turns.

## 7. PART 6 — Knowledge tracing (report §7.1)

- Per-concept mastery updates already rule-based in `learner_state.py` (probe/bridge deltas).
- Neural KT (e.g. SAINT-style on interaction sequences) waits for real learning-log data —
  the append-only `rag_store/learning_log.jsonl` is the training source. No synthetic KT.

## 8. PART 7 — Runtime loop wiring (architecture §7) — BUILT 2026-06-12 (v1, fully local)

`tutor_loop.py`: analyzer (Parts 1+2+3) → state update → `rules_decide` v1 (10 ordered
rules implementing §6.6/§13; bridge gate runs unconditionally in retrieval, not as a
rule) + shadow suggestion (logged) → evidence retrieval **reusing query.py's machinery
unchanged** (bridge_evidence, misconception_evidence probe-first, need_evidence, 7-term
snapshot_rerank, cohesion_filter) → response → learning_log append + state save.

Per the Qwen-only mandate, the three Gemini touchpoints of `query.py` are replaced
locally in the loop: concept resolution = Part 2 resolver; chunk ranking = a one-time
**local MiniLM chunk index** (`models/local_chunk_index/`, 1,017 chunks; the Gemini
FAISS index is untouched and still serves `query.py` standalone); response generation =
**Qwen2.5-3B via llama.cpp** *or* **Gemini 2.5 Flash** (`GEN_BACKEND`, see Part 11; composed
only from manifest items — the prompt is unchanged across backends; LLM cohesion judge off).

Verified on a fresh learner state: (1) AA-similarity question → bridge gate prepended
`grade9::congruence_of_triangles` (cold-start contract §6.8); (2) "quadratic always has
two real roots" → MISCONCEPTION_PROBE, Qwen asked the diagnostic WITHOUT revealing the
correction (probe-before-correct held); (3) overload message → ENCOURAGE + session-concept
inheritance. Log rows carry action + reason + shadow + full provenance manifest; global
EMA state, concept flags, and served-items dedupe all persisted. Shadow agreed with rules
3/3 turns. Known polish item: Qwen sometimes echoes evidence ids — tighten the prompt.

CLI: `python tutor_loop.py` (chat) / `--once "msg" [--no-answer]` (scripted).

**v2 (2026-06-12, same day): the loop is CLOSED.** Added to `tutor_loop.py`:
- **Pending-check grading**: serving any diagnostic (bridge or misconception) arms
  `session.pending_check`; the student's next reply is graded by local Qwen
  (`judge_answer`: correct/partial/wrong/not_an_answer, fail-safe to not_an_answer so a
  broken grader can never move state) and written back via `apply_probe_result` /
  `apply_bridge_result`. Verified: wrong answer → status `active`, failures 1, mastery
  0.30 → 0.20, all persisted; next-turn retrieval then serves corrective evidence.
- **Candidate probes**: when the analyzer flags `misconception_suspected` but none is
  active, the concept's first untracked `has_misconception` graph neighbor's diagnostic
  is served probe-first. (Gotcha found: concept-card `misconceptions` are free TEXT;
  the real nodes hang off `has_misconception` edges.)
- **Hint-chain escalation**: a hint request while a check is pending serves hint level
  k+1 via `record_hint_request` (rule 10 — one level at a time, never the answer;
  chain exhausted → falls through to grading/action switch). Verified HINT_LEVEL_1.
- **Prompt tightening**: evidence ids stripped from the Qwen prompt + explicit
  no-internal-ids instruction; write-back outcome fed to the response prompt.

**v3 (2026-06-12): conversation quality + remaining polish.** Triggered by a real student
test (`debug_text.txt`) where "yes it explained the difference" caused a full re-explanation:
- **Pure-acknowledgment rule (2b)**: `is_pure_ack` in cues.py (ack phrase + no '?', no
  WH-word, no 'but') routes to METACOGNITIVE_REFLECT — consolidate + advance, never
  re-explain. Deterministic cue OUTRANKS the classifier here: the classifier misreads
  acks as confusion (~0.55) because the dataset has almost no positive-confirmation
  utterances and MiniLM embeds "makes sense now" beside "not making sense now".
  **Dataset gap recorded: add an `acknowledgment` label + examples in the next data pass.**
- **Conversation memory (§12.3)**: session keeps the last 8 turns; the Qwen prompt gets
  the last 6 with "do not repeat explanations already given". Verified: follow-ups now
  build on prior turns instead of restarting.
- **Qwen cohesion judge** (A1.5 LLM half, local): fires only when a bundle mixes ≥3
  evidence types; can drop only chunk/figure items (diagnostics/bridges protected);
  any failure returns no-drops. `--no-judge` to disable.
- **Representation write-back**: a pure ack following a REPRESENTATION_TRANSLATION turn
  adds the served `supports_representation` values to the concept's
  `representations_known` (§9 coverage finally updates from evidence).
- Verified by replaying the debug_text.txt conversation: ack turn → METACOGNITIVE_REFLECT
  ("That's great to hear! … Now, let's move on"); `is_pure_ack` unit checks pass
  (including the negative cases "…but what is…" and "why are you explaining it again").

Project conventions now codified in `CLAUDE.md` (4-doc lockstep rule, Qwen mandate,
frozen splits, known gotchas).

**v4 (2026-06-15): HOPE detectors wired live + closed-loop hardening.**
- HOPE probe → score → `learner_state.hope_rolling` (see Part 4 "Wired live"); loop now
  logs as `tutor_loop_v4`. Arms `session.pending_hope` on any CT/KT/KI probe; the next
  student attempt (not ack, not hint, ≥4 words) is scored and EMA-folded into the signal.
- Misconception flag given a dedicated lower threshold (`MISCONCEPTION_FLAG_THRESHOLD` 0.4
  vs 0.5): misconception_clue is the classifier's weakest signal and sat right at 0.5 for
  classic "always/never … that's the rule" phrasings (a single comma flipped 0.62↔0.48).
  Rule 8 prefers probing; a served diagnostic is cheap.
- **Full closed loop verified in one session**: misconception probe → wrong-answer
  writeback (mastery 0.30→0.20, misconception `active`) → pure-ack → reflect → transfer
  probe → HOPE KT scored 0.78 → rolling KT updated → all persisted. Analyzer tests 4/4.

All major loops now closed and individually verified: bridge gate (v1), 7-term ranking +
manifest + cohesion (v1/v2), misconception probe→writeback (v2), hint-chain fade (v2),
ack→reflect + conversation memory + Qwen cohesion judge + representation write-back (v3),
HOPE probe→rolling (v4).

**v5 (2026-06-20): multimodal display channel (T9) + closed-loop grading hardening.**
- **T9 display channel**: `tutor_loop.turn()` now returns a `display` list — at most ONE
  task-relevant figure crop per turn (working-memory limit). `figure`-type evidence is
  already gated by query.py to the two show-cases (representation gap / active-misconception
  disambiguation), so it always shows; an incidental `figure_caption` chunk shows only for
  `REPRESENTATION_TRANSLATION`/`VISUAL_ANALOGY`. `image_path` stays store-relative (sinks
  resolve it). The Qwen prompt gets a "refer to the figure on screen" cue on display turns.
  Web UI feasibility path wired: `wini_ui_server.py` serves crops at `/store/<relpath>` and
  `ui/app.js` renders the crop in the Wini bubble (KaTeX added so the LaTeX the tutor emits —
  `\(x\)`, `\[..\]`, `x^2` — renders as real math, not raw text). Voice-side renderer added as a
  separate file `voice/display.py` (`DisplaySink` protocol + `NullDisplaySink` default +
  `TkDisplaySink` always-on-top pane), wired into `voice_hybrid_runner.py` behind an opt-in
  `--display tk` flag synced to TTS start/clear — `--display none` keeps plain text+voice
  unchanged. Verified: graphical-gap parabola question → Fig-2.2 crop shown; audio-only turns
  return `[]`; traversal-guarded route serves PNGs.
- **Grading hardening (three regressions found via `learning_log.jsonl` on a dev test
  session, all fixed):**
  1. *Non-attempt mis-grading* — the closed loop graded EVERY reply, so "I can not
     understand" / "you are repeating yourself" were judged `wrong`, dropping mastery and
     forcing misconceptions active. Fix: a deterministic `non_attempt` guard (no answer cue +
     ack / clarification / bare question / fresh request) short-circuits to `not_an_answer`
     BEFORE the local judge, and gates the HOPE scorer too.
  2. *Confused learner challenged* — a misread curiosity score sent an overwhelmed learner to
     `SOCRATIC_Q`. Fix: deterministic `rule 1b` (clarification cue) re-explains more simply,
     outranking the inferred-misconception probe; plus a Qwen anti-repeat/simplify cue.
  3. *`ct_probe` graded as a misconception* — a `ct_probe` carries a `question`, so it armed
     `pending_check` and was written into `misconception_states` (bogus `ct_probe::…` entry)
     while mastery dropped. Fix: only `bridge_diagnostic`/`misconception` may arm
     `pending_check`; CT/KT/KI probes are HOPE-scored only. Verified end-to-end.
  New standalone cues (`is_clarification_request`, `is_answer_attempt` in cues.py) are NOT in
  the feature vector → no classifier/policy rebuild. `learner_state.json` (developer dummy
  data, corrupted by the above) reset to a clean baseline.
- **Regression coverage**: `smoke_test_phase5.py` extended with T6-T9 (Qwen calls monkeypatched,
  no server needed) — non-attempt not graded, real answer still graded, clarification→EXPLAIN,
  `ct_probe` HOPE-armed not graded, and the display channel surfaces one crop / nothing on
  audio-only. All 11 new checks pass.

**v5.1 (2026-07-20): T9 tier-3 teaching visual — EXPLAIN turns now show a crop by default.**
- Field finding (winipi5): explain turns were text-only in practice. Measured: the graph's
  `illustrated_by`/`has_formula` edges cover **7/108 concepts (0/13 trigonometry)**, so the
  representation-gap show-case could never fire for trig, and the incidental path was gated
  to two rare actions. The store itself is fine: **244 `figure_caption` chunks** carry
  `image_path` + `concept_ids` across all chapters (trig: 9/13 concepts covered).
- Fix: `_build_display(..., teaching=, ranked=, primary_concept=)` gained tier 3 — on a
  non-TEST turn the mode controller is not driving (plain EXPLAIN, or an inner-loop override
  into an explanation), show the top-ranked image-bearing chunk from the turn's own retrieval
  (semantic order = relevance to the utterance), else the primary concept's first visual from
  the new `visuals_by_concept` index. Tiers 1/2 unchanged and still win; TEST turns still
  carry no figure; PRACTICE mode-items stay audio-only.
- Verified on winipi5 2026-07-20: `--once "explain trigonometric ratios to me"` →
  `display=[fig::jemh108::fig_8_8]` (the tan A = 4/3 triangle) and the LVGL panel renders
  the crop + caption under the explain card (mic-free ModeChannelSink replay + scrot proof).
- Open: 644 formula crops are concept-linked only for jemh102 (`has_formula`) — chapter-wide
  linking would let identity-heavy trig turns show the formula image instead of a diagram.
  → CLOSED by v5.2 below.

**v5.2 (2026-07-20): chapter-wide concept→formula links — formula crops reach T9.**
- The v5.1 open item, measured: all 266 graph `has_formula` edges hang off the **7 jemh102
  concepts** (the vision pass emitted `likely_concept_ids` nowhere else), so none of the
  other 637 image-bearing formula crops could ever be selected for display.
- Fix: `link_formulas.py` (new) derives concept links for every formula node
  deterministically — no LLM, no embeddings: score = 0.6·page-inheritance (the concept's
  `concept_scores` mass among the chunk rows on the formula's page) + 0.4·name/alias token
  match (plural-stripped, small trig synonym table) + 0.1 definitional-slug bonus − 0.25
  worked-example-slug penalty (given/step/derived/… — solved-example equations must not
  outrank the definitional form); keep score ≥ 0.35, ≤3 concepts per formula. Writes the
  NEW derived artifact `rag_store/formula_links.json` (2135 links, 1458 to image-bearing
  formulas); graph.json/chunks.jsonl/concepts.json untouched (read-only rule).
- Wiring: `TutorLoop.__init__` merges the links file + the original graph `has_formula`
  edges into `visuals_by_concept` as chunk-shaped pseudo-rows (`kind:"formula"`,
  `representations:["symbolic"]`); caption rows stay first per pool, formula rows follow
  by link score, so v5.1 behavior is unchanged wherever a caption exists.
  `_build_display` resolves pseudo-row ids via a `formula_rows_by_id` fallback.
- **Measured coverage (concepts with ≥1 formula visual): 7/108 → 95/108** — per chapter
  before→after: jemh101 0→7/8, jemh102 7→7/7, jemh103 0→6/6, jemh104 0→7/8, jemh105
  0→5/6, jemh106 0→7/8, jemh107 0→7/8, **jemh108 0→8/8**, jemh109 0→4/5, jemh110 0→4/5,
  jemh111 0→6/7, jemh112 0→5/5, jemh113 0→6/6, jemh114 0→7/7, jemh1a1 0→7/7, jemh1a2
  0→2/7 (appendix has only 4 formula crops). All referenced crop files exist on disk.
- Spot-checked link quality: `jemh108__pythagorean_trig_identities` top link is
  `formula::jemh108::pythagorean_trigonometric_identity` (cos² A + sin² A = 1, score
  0.83); definitional forms rank above worked-example steps across sampled chapters.
- Tier-3 ordering refinement (same session): when the primary concept is known, a crop
  TAGGED with the concept (ranked row, else the concept's `visuals_by_concept` pool)
  now beats a merely semantically-similar crop of another concept — measured live that
  an off-concept caption (fig 8.16) otherwise outranked the concept's own formula crop
  whenever concept resolution abstained (retrieval then spans ALL chunks).
- Rebuild: `python link_formulas.py` (prints the per-chapter before/after table) —
  re-run after any graph/chunks/concepts rebuild.

## 9. PART 8 — Evaluation & monitoring

- Frozen test split (Part 1 splits.json) reused for every dataset-derived model.
- Holdout-chapter generalization check (report §2): retrain bank without 1–2 chapters'
  rows, measure degradation.
- Pilot metrics from `RAG_upgrade_plan.md` §4b (bridge usefulness band, misconception
  resolution ≤ 3 sessions, retention lift) — needs real learners.

---

## 10. Build order and dependencies

```
Part 1 (classifier)  ──┐
Part 2 (resolver)    ──┼─→ Part 3 (analyzer) ─→ Part 7 (loop) ─→ Part 8 (eval/pilot)
Part 4 (HOPE)        ──┘            Part 5 (policy shadow) ──↗
Part 6 (KT) — after real logs exist
```

Parts 1, 2, 4 are independent and parallelizable. Part 1 is first because it unblocks the
analyzer and its splits.json freezes the shared evaluation contract.

Lockstep rule: changes here propagate to `learner_cognitive_state_architecture.md` and
`model_dataset_architecture_report.md` (3-doc rule from rag_memory.md, now 4 docs).

---

## 11. PART 9 — Jetson voice deployment (Layers A & C + in-process serving) — BUILT 2026-06-16

Wiring the verified study core (Parts 1–8) into the end-to-end voice robot on the **Jetson
Orin Nano** (JetPack R36.5, CUDA 12.6, Py 3.10, ROS 2 Humble). Full as-built detail +
spec→reality deltas live in **`WINI_VOICE_STUDY_ARCHITECTURE.md` §12**; this is the
build-status summary. ROS graph: `wakeword_node → /wake_word → fastwhisper_node →
/speech_text → wini_brain_node → /llm_out(+/tts_done) → wini_tts_node`; `/robot_speaking`
is the half-duplex mic gate. Retired (not launched): `llm_pkg` (ollama), `intent_pkg`.

- **Phase 0 — study core imports clean (no cloud deps).** `wini_core` symlink → `cloud CLI`;
  made faiss/google-genai/rank_bm25/rapidfuzz/python-dotenv **lazy**; `load_store(with_index=
  False)`; networkx `edges="edges"` fix; new stdlib `device_config.py` (env paths, MiniLM
  device). Verified `import tutor_loop` with none of those 5 installed.
- **Phase 1 — MiniLM on CPU.** `sentence-transformers 5.5.1 --no-deps`; all-MiniLM-L6-v2 from
  HF cache; ~84 ms/encode CPU.
- **Phase 1.5 — CTranslate2 CUDA from source** (no aarch64 wheel): v4.7.1, `sm_87`,
  `pybind11==2.13.6`; vendored `libctranslate2.so*` + `patchelf $ORIGIN` (no LD_LIBRARY_PATH);
  `get_cuda_device_count()==1`. STT → `small.en/cuda/int8_float16`, **resident**.
- **Phase 2 — in-process Qwen, streaming.** Built `llama-cpp-python 0.3.29` from source CUDA
  (prebuilt 0.3.14 crashes on every gen). New `llm_local.py` (complete/stream_tokens/
  stream_sentences). `tutor_loop.qwen_chat → llm_local.complete` (**:8080 server removed**);
  `turn(text, on_sentence=…)` streams sentences. **MiniLM pinned to CPU** — fixes a process-
  exit crash from torch+llama.cpp dual CUDA context. Pinned `setuptools<80` (colcon).
- **Phase 3 — `wini_brain_pkg`.** Brain node subscribes `/speech_text`, runs
  `TutorLoop.turn(on_sentence→/llm_out)`, owns `/robot_speaking=True` + `/tts_done`; pre-warms
  Qwen at startup. Verified end-to-end; TTFS ≈ 3.4 s.
- **Phase 4 — Kokoro TTS on GPU.** Native Kokoro→**TensorRT impossible** (TRT 10.3 rejects the
  vocoder `STFT` op); CPU RTF≈2.4. Chose **onnxruntime-gpu 1.24.0 CUDA EP** (`--no-deps`,
  numpy 1.24.4 kept; openWakeWord pins CPU so unaffected). `kokoro-onnx 0.5.0`+`phonemizer-
  fork`+`espeakng-loader` `--no-deps`. **RTF≈0.17.** Rewrote `wini_tts_node`: resident Kokoro,
  synth-ahead pipeline, `clean_for_tts()` (LaTeX/markdown), `/tts_done` gate handoff.
- **Phase 5 — integration + robustness.** `wini_pipeline.launch.py` (all 4 nodes, ready ~9 s,
  VRAM ≈ 6.2/7.6 GB). Audio: USB C-Media mic+speaker via **PulseAudio** (default sink/source),
  TTS `output_device='pulse'`; speaker output confirmed. **Anti-self-trigger:** (a) Whisper
  hallucination filter in `fastwhisper_node` (no_speech/logprob + blocklist); (b) `wakeword_
  node` gated on `/robot_speaking`. **Wakeword false-fire fixed** (continuous feed, THRESHOLD
  0.5, 2-frame debounce, refractory — 0 fires/40 s silent). **ALSA underrun fixed** via a
  callback `sd.OutputStream` that fills silence when starved — 0 underruns over 41 sentences.

**Open items:** A2 VAD divergence (RMS endpointing vs spec Silero), occasional harmless
wakeword ambient false-fire, session-context reset on wake, and the live human-voice test
(injected `/speech_text` bypasses Whisper). ~~Qwen TTFS latency tuning~~ — mooted by 11.1.

### 11.1 Jetson cloud-brain mode (2026-07-03) — Part 11 pipeline on the robot

The Jetson rig now runs the **same cloud brain as the Windows rig** (Part 11: Gemini
perception + Gemini generation, `GEN_BACKEND=gemini`), keeping ROS, Whisper ASR, Kokoro
TTS, and the SPI display local. Rationale: the display + ROS integration work on the
Jetson; the brain's model calls move to the cloud per the CLAUDE.md mandate; the board
becomes the reference client for the eventual ESP32 thin client.

- **Sync (3-way merge honored):** Part 11 files copied to the board (`tutor_loop.py`,
  `perception/` + build artifacts, `llm_vertex.py`, `persona.json`, `cues.py`, pacing);
  `query.py` unified (workspace adopted the Jetson's lazy-faiss/`with_index=False`
  variant); `llm_local.py`/`device_config.py` stay Jetson-only. `tutor_loop.py` gained an
  optional `device_config` MiniLM-device pin (CPU on the board) + `load_store(...,
  with_index=False)` — one source now runs on both platforms.
- **Brain node:** in gemini mode, no llama.cpp import/pre-warm (frees ~3.5 GB — the Part
  9 OOM squeeze is gone: full pipeline 4.4 GB used / 2.8 GB free); Vertex clients warmed
  at startup (~6 s, the client-construction gotcha); the whole cloud reply is
  sentence-split (decimal/abbreviation-safe) and published to `/llm_out`, T9 figure up
  BEFORE speech starts. Legacy qwen streaming retained behind the flag.
- **Measured on the board:** headless `tutor_loop.py --once` E2E cloud turn correct
  (concept + display + gemini backend); offline perception tests 5/5 PASS; live ROS turn
  utterance→first TTS sentence ~4 s warm; `/wini/display/image` at 5.0 Hz; visualization
  plea → rule 1a-vis → REPRESENTATION_TRANSLATION with the Fig 2.2 crop on screen.
- **ESP32 forward contract documented** (`JETSON_PIPELINE_RUNBOOK.md` §14.3): the turn
  result's store-relative `image_path` is the stable image ID; thin clients hold the
  `figure_crops/` tree on SD card and blit by ID — the cloud sends metadata only.
- Board network/IP: phone hotspot `172.20.10.2` (old `192.168.29.x` retired); ADC creds
  + `google-genai` installed on-device. Full runbook: `JETSON_PIPELINE_RUNBOOK.md` §14.
- **Superseded the same day by §11.2** — the cloud-brain ROS node was a stepping stone;
  the wakeword/fastwhisper/Kokoro nodes it still relied on were retired that evening.

### 11.2 Jetson THIN-CLIENT split (2026-07-03) — the ESP32 shape, running today

Owner directive: no wakeword, no fastwhisper, nothing model-shaped on the device; the
device is a platform (mic + speaker + display + future touch); everything runs in the
cloud; the package must port to other devices without a dependency mountain.

- **`wini_server.py` (brain service):** the WHOLE pipeline behind one HTTP contract —
  Cloud STT (en-US + maths phrase hints) → TutorLoop (Gemini perception + generation,
  unchanged) → sanitize → Cloud TTS (en-IN Chirp3-HD). stdlib `http.server` (zero new
  server deps); `GET /health`, `POST /turn` (text), `POST /voice_turn` (raw 16 kHz PCM in,
  base64 24 kHz PCM + display METADATA out); hard wall-clock timeouts on every cloud
  call; runs on the Jetson today and is the Cloud Run artifact later (PORT env).
- **`wini_client/` (portable thin client):** deps = numpy + sounddevice + requests, full
  stop. RMS voice-activity endpointing (~40 lines, replaces the wakeword+ASR front),
  half-duplex by construction, display via a pluggable sink (`RosDisplaySink` on the
  Jetson → 480×320 rgb8 on `/wini/display/image` at ~5 Hz, resolving `image_path`
  against the local `rag_store/` copy = the SD-card image-ID contract §11.1/runbook
  §14.3; `--display none/console` elsewhere). `--once-text` and `--trigger enter`
  (push-to-talk = the future touch-sensor shape) for testing. Porting guide + HTTP
  contract: `wini_client/README.md` (4 seams: mic, speaker, display-by-ID, trigger).
- **Retired from the runtime:** wakeword_node, fastwhisper_node, wini_tts_node (Kokoro),
  and the wini_brain_pkg ROS node — all kept on disk as the legacy `run_pipeline.sh`
  stack. New bring-up: `run_thin.sh` (audio pin + display node + server + client).
- **Verified on the board (2026-07-03):** `/voice_turn` with a canned 16 kHz utterance →
  transcript exact, REPRESENTATION_TRANSLATION + Fig 2.2 display metadata, ~834 KB TTS
  audio (STT 1.5–2 s, brain 2.5–5 s, TTS 3–4.5 s); client one-shot turn put the crop on
  the panel (~3.6–5 Hz frames measured) and played the reply on the USB speaker; VAD
  client left running. Windows verification first: same server + client `--once-text` +
  fake-voice `/voice_turn` all green before deploying.
- **Gotchas logged** (rag_memory G24–G27): PulseAudio onboard re-grab (belt:
  `PULSE_SINK/PULSE_SOURCE` env + `device="pulse"` on both streams), PortAudio-blocked
  client ignores SIGTERM (pkill -9), pkill self-match bracket trick, `-u` for detached
  python logs.
- **Open:** live human mic test on the board; touch-sensor trigger; VAD hears all speech
  (no wakeword by design — the touch gate is the plan); filler/latency masking for the
  ~7–10 s silent turn window; Cloud Run deployment of `wini_server.py` + Firestore state.

## 12. PART 10 — Windows hybrid voice pipeline (cloud edges, local brain) — BUILT 2026-06-18

A Windows laptop voice **test rig** that exercises the verified study core (Parts 1–8) over
real speech, with only the voice edges in the cloud. Entry point `python voice_hybrid_runner.py
--live`. Flow: `mic → Cloud STT (forced en-US) → MiniLM analysis → state-based filler →
TutorLoop+Qwen (cohesion judge OFF) → Cloud TTS (en-IN Chirp3-HD, sentence-streamed) → speaker`.
Turn-based / half-duplex (mic records only between Wini's turns); barge-in deferred. New code in
`voice/` (`cloud_stt.py`, `cloud_tts.py`, `fillers.py`, `sanitize.py`, `live_session.py`,
`live_tools.py`) + `pacing/`; the study core is unchanged.

- **Gemini Live API tried and rejected as transport.** Native-audio `gemini-live-2.5-flash`
  (a) would not vocalize a function-result verbatim, (b) when fed text it paraphrased and
  **invented its own maths** (violates the local-brain mandate), and (c) its STT rendered
  Indian-accented English into Telugu/Hindi script. Replaced both edges with purpose-built
  Cloud Speech APIs. (Live reachable only at region `global` for project
  `custom-model-training-493207`; `texttospeech` + `speech` APIs were `gcloud services enable`d.)
- **STT — Cloud Speech-to-Text, forced `en-US`** + maths phrase-hints (boost "discriminant",
  "real roots", …). English-only confirmed on real recordings (no Indic script); residual
  accent errors only ("real roots"→"railroads"), mitigated by the phrase set.
- **TTS — Cloud Text-to-Speech `en-IN-Chirp3-HD-Achernar`**, LINEAR16/24 kHz, **verbatim**
  (speaks the local answer exactly — no embellishment). ~1.5–1.9 s synth for ~8 s audio;
  spoken sentence-by-sentence so first audio is one short-sentence synth.
- **Latency.** Cohesion judge disabled for voice (drops a big-prompt Qwen call per turn) and a
  **Qwen generation warmup at startup**: first turn **11.2 s → 2.2 s**, subsequent 2–5 s.
  Resolver lazy-load (~7 s) and the first MiniLM forward are pre-warmed at startup; per-turn
  triage **~50 ms** (was ~10 s on a cold first turn).
- **Cognitive fillers.** While the brain generates, Wini speaks a short filler chosen by the
  MiniLM `cognitive_update` + triage (confused / curious / frustrated / hint / shift / ack /
  default), a different phrase each time, all pre-synthesised. Replaces the fixed "Let me see".
- **Spoken-budget enforcement (deliver, don't announce).** `qwen_answer` now hard-caps to whole
  sentences within a word budget (`_truncate_to_spoken_budget`, drops token-cut fragments), and
  the generation budget is resized to the ACTUAL action (`_budget_for_generation`) — the pacing
  layer's pre-action guess (EXPLAIN 35 w) starved `WORKED_EXAMPLE`. WORKED_EXAMPLE raised to
  **60 w / 4 sentences / `try_step`**, and the prompt forbids announcing ("let's use an
  example") without working it: examples now substitute and compute to the result
  (`D = (-4)² − 4·2·2 = 0`), and the micro-check asks about delivered content only. Generation
  temperature 0.3 for instruction-following. Speech sanitizer (`voice/sanitize.py`) maps LaTeX/
  symbols to words incl. `*`→"times" and strips stray `yes_no:` labels.

## 13. PART 11 — Cloud pivot (Gemini generation + perception) — **PROMOTED 2026-07-02**

The platform pivoted off Jetson edge to cloud (Cloud Run + Firestore, ESP32 thin client) on
2026-06-30 (CLAUDE.md). Two increments; **increment 1 built + verified; increment 2 PROMOTED —
`PERCEPTION_BACKEND` default is `gemini` since 2026-07-02** (all gates green, §13.2). **Stages
5–6 also complete (2026-07-02): Vertex context cache live, MiniLM-heads runtime path retired —
Part 11 is done** (standing watch: production firing rates).

**Design of record:** `PART11_GEMINI_PERCEPTION_LAYER.md` (perception layer). Generation move is
governed by the same CLAUDE.md cloud mandate.

### 13.1 Increment 1 — Gemini generation backend (BUILT + headless-verified 2026-07-01)
- **`llm_vertex.py`** — shared Vertex Gemini 2.5 Flash client (`asia-south1`), memoized per
  location, **hard wall-clock timeout via `ThreadPoolExecutor.result(timeout=)`** (default 20 s),
  `thinking_budget=0` (Flash's default thinking budget else eats `max_output_tokens` and returns
  empty text — new gotcha, logged). This is the shared client the perception layer will reuse.
- **`GEN_BACKEND=qwen|gemini`** flag in `tutor_loop.py`: `qwen_chat` dispatches to
  `llm_vertex.generate_reply` when `gemini`. One seam covers all three generation call sites
  (`qwen_answer`, `qwen_cohesion_check`, `judge_answer`) — the **manifest-grounded prompt is
  byte-identical across backends**; only the transport changes. Local Qwen `:8080` stays as
  legacy/fallback (default `qwen`).
- **`voice_cloud_tutor.py`** — push-to-talk cloud voice tutor for controlled testing: Cloud STT
  (en-US) → real `TutorLoop` brain (MiniLM perception, retrieval, manifest prompt) → Gemini Flash
  generation → Cloud TTS, warm clients, per-hop timing. (`voice_latency_spike.py` is the earlier
  edges-only probe; `voice_hybrid_runner.py --live` remains the hands-free streamed runner.)
- **Measured (warm, Windows quick-test rig):** generation **~0.9–1.2 s/call**; a full brain turn
  (analysis+retrieval+gen) **~1.3 s**; Cloud TTS ~1.9 s for a 2-sentence answer; **end-to-end
  brain+TTS ~3.2 s** (add ~1.2 s Cloud STT for a mic turn ≈ ~4.4 s). **Cold-start ~5–9 s is one-
  time client construction** (Vertex ADC/channel), paid once at startup via warmup, not per turn —
  the Cloud Run `min-instances=1` case. Headless `tutor_loop.py --once` confirmed a correct,
  manifest-grounded answer from Gemini with **no local Qwen server running**.
- **Not yet done:** user mic test on real speech; lockstep to the report's model numbers is n/a
  (no neural model changed — generation transport only). SAFETY unaffected (no perception change
  in this increment).

#### 13.1a Voice-teaching quality fixes (2026-07-01, from a real mic transcript)
A live trig session (`cloud_education.txt`) exposed content-free one-liners: an opening "I want to
learn trigonometry" was **QUIZ**ed, and every frustrated follow-up drew an **apology that ate the
whole spoken budget** ("Namaste! I'm Wini…", "My apologies! Let's focus…") with the same question
repeated 3×. Root causes + fixes (owner-approved: fuller explanations):
- **Budgets too tight** (25–35 w / 1–2 s) → teaching actions raised: EXPLAIN **65 w / 4 s**,
  WORKED_EXAMPLE **85/5**, ANALOGOUS/REPRESENTATION **60/4**, ENCOURAGE/TRANSFER **45/3**; probes,
  QUIZ, SOCRATIC, REFLECT stay tight by design (`pacing/pacing_controller.py`).
- **No intro path** → new **rule 1c** in `rules_decide`: a not-yet-mastered concept the student
  asks to learn (curiosity / bare question, no distress) routes to EXPLAIN-and-introduce, never
  QUIZ. Gated on `mastery(primary) <= COLD_START_MASTERY` (not `is_known`, which is already True
  after the first `apply_deltas` writes a concept-state row).
- **Frustration mishandled** → `CLARIFY_RE` (cues.py, standalone runtime cue — no classifier
  rebuild) extended to catch "not explaining / keep asking questions / giving different answers"
  so it re-explains (rule 1b) instead of re-probing.
- **Filler + repetition** → hard STYLE block in `qwen_answer`: never greet / self-introduce /
  apologise / announce, and never re-ask a question already in RECENT CONVERSATION; intro tone for
  rule-1c EXPLAIN.
- **Verified** by replaying the same 5 inputs through the voice path on a fresh state
  (`GEN_BACKEND=gemini`): turn 1 now EXPLAINs trigonometry; turns 2–5 each teach something new and
  progressive (hypotenuse → right angle → application → ratios) with a worked example, **zero
  apologies, zero repeated questions**, warm latency preserved (~0.9–1.3 s gen/turn).

#### 13.1b Session-exit + visualization fixes (2026-07-03, from agent transcript review)
An external review of a live tutoring transcript (`gemini_tutor_issues.md`) found five UX
defects; all fixed and offline-tested (`python -m perception.test_perception`, 5/5 PASS):
- **SESSION_CONTROL retention (the biggest):** after "No, I want to go. Bye." the tutor tried
  "let's just quickly finish this one small sum". Root cause: persona instruction said "secure a
  small win" and `_persona_prompt` invited a steer-back for every intent. Fixes: persona rewritten
  (accept immediately, never ask a maths question); SESSION_CONTROL prompt now forbids questions;
  **end-of-session hard rule** in `_apply_session_control` — explicit goodbye OR a second leave
  request in a row (`session.leave_requests`) forces `status="ended"`, the farewell is **scripted,
  never the LLM**, and `session_ended=True` flows through `TutorTurnHandler` so every runner
  (CLI `tutor_loop.py`, `voice_cloud_tutor.py`, `voice/live_session.py` mic loop) **stops taking
  turns**. A LEARNING resume resets the counter. Part 11 §4.3 contract updated to match.
- **SOCIAL blind to context:** "Wini, I was right!" drew "What did you get right?". Fix:
  `_persona_prompt` now includes the last 6 `session.context` turns with "never ask about
  something it already tells you"; SOCIAL instruction tells it to confirm the specific thing.
- **Visualization pleas re-defined instead of pictured:** "I cannot imagine this" (rule 1b) drew
  another textual definition. Fix: new standalone `VISUALIZE_RE`/`is_visualization_request` cue
  (cues.py — no classifier rebuild), new **rule 1a-vis** outranking rule 1b: visualization plea →
  `REPRESENTATION_TRANSLATION` (integrate/KI need), and a generation cue that builds ONE concrete
  everyday scene step by step (or walks the on-screen T9 figure) instead of restating the
  definition. Architecture doc "Decision examples" updated.

#### 13.1c Purpose questions, topic shift, backend observability (2026-07-03, second transcript)
A follow-up live `--live` test (`gemini_tutor_issues.md`, Gemini generation) exposed four more
defects; all fixed, offline tests 7/7 PASS:
- **Purpose/connection questions never answered:** "how is this related to quadratic equation" →
  `transfer_attempt` → rule 5 TRANSFER_PROBLEM (a new problem as the "answer"); two follow-up
  complaints fell to confusion/frustration rules and the connection was stated only on attempt 4.
  Fix: standalone `PURPOSE_RE`/`is_purpose_question` (incl. "you didn't answer my question") →
  **rule 1w** (after 1a-vis, before 1b) → new `WHY_IT_MATTERS` action whose generation tone
  ANSWERS THE EXACT QUESTION FIRST (state the connection / one real-life reason), never a new
  problem or a definition. Budget 60w/4s.
- **Topic shift broken:** "Natural numbers." abstained (off-catalog) → INHERIT → the tutor
  silently continued expanding the old marble equation; the correction "I asked about natural
  numbers, you are explaining me quadratic equation" resolved to the NEGATED quadratic concept
  (conf 0.7) and re-introduced it. Fix (deterministic, all local/free): `TOPIC_REQUEST_RE`
  span extraction (captures the REQUESTED topic) + `is_bare_topic`; `GeminiPerception.
  topic_candidates()` (anchor sims WITH scores); `_maybe_topic_shift` in `turn()` — explicit
  span grounded ≥ .45 switches immediately (re-enters as an intro turn), .25–.45 asks
  ("switch to {name}? yes/no"), < .25 = honest off-catalog reply offering the nearest topic;
  `pending_shift` is consumed next turn by a bare yes/no (yes executes, no continues, anything
  else cancels). Thresholds measured on the shipped anchors (topic names .45–.69, noise ≤ .14).
  The pacing `confirm_shift` branch now speaks the human concept name (was the raw catalog id)
  and arms the same `pending_shift` (previously the offer was made and then forgotten — a "yes"
  never executed). Bare labels are blocked only by GRADED pending questions, not pace-only
  micro-checks.
- **"I want to learn about X" opened with QUIZ:** perception signals were empty and
  `learning_start`'s deterministic disjunct had no learn-request cue; warm mastery also gated it.
  Fix: `LEARN_REQUEST_RE` — an explicit learn request always teaches (EXPLAIN; the welcoming
  intro TONE stays reserved for cold-mastery topics).
- **Replies cut mid-number:** `_truncate_to_spoken_budget` split sentences on DECIMAL POINTS
  ("20 / 0.2" → "…20 / 0." + "2 …"), so the sentence cap cut mid-division and re-joined
  "0. 2 square metres" (the transcript's brick-wall reply). Splitter now requires whitespace/end
  after a terminator; generation token cap raised (90–240, ×3.5) so sentences finish.
- **Backend observability:** the `--live` labels said "qwen" regardless of `GEN_BACKEND` and no
  log recorded the backend. Now: runners print `generation backend: …` at startup; per-turn
  `gen_backend` in `learning_log.jsonl`, turn results and voice logs; non-learning replies log
  `answer_source` (`scripted`/`farewell`/`canned`/backend name).
- **Verified working in the same transcript:** the 13.1b SESSION_CONTROL fixes behaved exactly
  as designed (soft pause with no retention question; second leave request → scripted farewell +
  runner hard stop).
Per `PART11_GEMINI_PERCEPTION_LAYER.md`: ONE structured Gemini call for intent routing +
cognitive signals + concept resolution, feature-flagged `PERCEPTION_BACKEND=qwen_heads|gemini`,
deterministic SAFETY/NONSENSE gates, promoted only on the frozen TEST-split eval gate.
`derive_*`/`apply_deltas` state math reused unchanged.

**Built (code + tests):**
- **`perception/`** — `gates.py` (SAFETY+NONSENSE, model-free, always on), `route.py`
  (`RouteResult` + 8 intents + `INHERIT_CURRENT_CONCEPT`), `build_perception.py` (schema enums +
  cached block generated from `label_space.json` + `concepts_meta.json`, with a drift-guard that
  the authored signal definitions cover EXACTLY the 38 shipped labels), `gemini_perception.py`
  (`GeminiPerception`: one memoized call exposing classify/resolve/route/embed/score_matrix/embedder
  + the OOV validation belt), `config.py` (flags), `test_perception.py`.
- **`persona.json`** — identity + canned/scripted non-learning replies (SAFETY/NONSENSE scripted,
  never model-improvised).
- **`llm_vertex.generate_json`** — the structured-JSON seam (`response_schema`, `temperature=0`,
  `thinking_budget=0`, hard timeout); reuses the Increment-1 memoized client.
- **`tutor_loop.py`** — step-0 front door (gates → Gemini route → `_handle_nonlearning` for
  non-LEARNING, **no state move**, `pending_check` preserved), `_log_safety` (persisted
  `safety_alerts` + supervisor notification), backend wiring (inject `GeminiPerception` as
  classifier+resolver), the `answer_attempt` guard strengthening (§7.4), and a flagged Stage-1
  shadow hook. `analyzer.py` / `learner_state.py` / `query.py` / classifier / resolver / HOPE
  **unchanged**.
- **`eval/perception_eval.py`** — Stage 2 harness over the frozen TEST split (999 rows) + authored
  intent + adversarial SAFETY probe sets → `eval/perception_eval_report.md`.

**Measured (2026-07-01):** Stage 0 live structured call GREEN (schema-valid JSON, ~8 s cold);
deterministic **gate coverage SAFETY 1.0 (20/20) / NONSENSE 1.0 (9/9) / 0 false-gates** (offline,
final); front-door integration test passes (SAFETY/NONSENSE scripted, no state move, LEARNING
passes through).

**Promotion (measured 2026-07-01/02, all in `eval/perception_eval_report.md` +
`eval/behavioral_eval_report.md` + `PART11_PERCEPTION_EVAL_STATUS.md`):**
- **First full 999-row TEST collect (2026-07-01): NO-GO** — intent macro-F1 **1.0** PASS, SAFETY
  recall **1.0** PASS, but concept **0.882/0.933** near-missed the 0.895/0.971 head baselines and
  signal label-F1 failed structurally: the heads were *trained* to reproduce the dense gold
  (`curiosity` gold-labeled on 85% of rows → heads recall 0.95 by memorization vs Gemini 0.06 by
  applying the definition), so a label-reproduction F1 gate cannot be won by a §5.5b-conservative
  perceiver at any scope or threshold. **The signal gate, not Gemini, was the wrong arbiter.**
- **Behavioral state-trajectory eval (2026-07-02, the superseding signals arbiter,
  `eval/behavioral_eval.py`): PASS all 3 pre-fixed gates.** Both backends' signal outputs pushed
  through the UNCHANGED `derive_cognitive_update`/`derive_state_deltas` math and graded on the
  state moves they cause over 48 authored probes: **Gemini field-direction accuracy 0.857 vs
  heads 0.607; must-fire flag recall 0.833 vs 0.500; forbidden-flag rate 0.016 = heads.** The
  heads systematically miss misconception/transfer/prerequisite/frustration flags they were never
  penalized for under label-F1.
- **§5.5 concept hardening (2026-07-02) + full 999-row re-collect (0 errors): concept
  top-1 0.930 / top-3 0.990 — both gates PASS** (vs 0.895/0.971 baselines). Three pieces:
  always-fill 2–3 `secondary_concepts` (top-3 was collapsing to top-1 on the 74% of rows Gemini
  left them empty → 0.990), top-8 MiniLM `candidate_concepts` hints in the per-turn prompt
  (resolver's `anchor_embeddings.npy`, `PERCEPTION_CANDIDATE_K`), and the **deterministic resolver
  cross-check** in `GeminiPerception.resolve` (`fuse_primary`: the local resolver's confident
  top-1 is promoted ONLY when already inside Gemini's {primary+secondaries}; never overrides
  INHERIT; `PERCEPTION_CONCEPT_CROSSCHECK`) which lifted top-1 **0.890 → 0.930** — above both
  the raw-Gemini and resolver-alone (0.895) numbers, because the two rankers correct each other's
  adjacent-concept confusions (58/66 raw misses were same-chapter granularity picks with gold in
  the secondaries).
- **Flip verified:** perception tests + live integration PASS, headless `tutor_loop.py --once`
  E2E turn on the `gemini` default drove correct concept + sensible signals through the unchanged
  state math. **Default is now `gemini`**; the MiniLM classifier/resolver are superseded for the
  runtime path, retained on disk as fallback + eval baselines (removal is Stage 6, owner decision
  after stability). `PERCEPTION_SIGNAL_THRESHOLD` stays 0.5 (calibration sweep was flat — the
  behavioral eval, not label-F1, governs signals). Caches: `eval/perception_eval_raw.jsonl` (v1,
  pre-hardening provenance) and `perception_eval_raw2.jsonl` (v2, prompt of record) — never mix.
- **Stage 5 (2026-07-02): Vertex context cache DONE** (`perception/vertex_cache.py`): the
  6,062-token static block is a cached-content resource (sha-guarded against prompt rebuilds,
  expiry-checked, failed-cache calls retry once with the full system instruction). Measured:
  correctness identical; **~1.0–1.1 s/call warm vs ~1.3–1.5 s uncached; 66% of prompt tokens
  (6,062/9,155) at the cached rate**, remainder = dynamic prompt + un-cacheable response
  schema; ≈$0.0014/turn input. Recreate after prompt rebuilds/TTL:
  `python -m perception.vertex_cache --create`.
- **Stage 6 (2026-07-02, owner-directed): MiniLM-heads runtime path RETIRED.** `tutor_loop.py`
  always injects `GeminiPerception` (stale `PERCEPTION_BACKEND=qwen_heads` → notice + gemini);
  Stage-1 shadow hook removed; learning-path fallback = gates + inherit-concept + neutral
  signals. Head artifacts retained as eval baselines; resolver artifacts still serve the §5.5
  runtime cross-check; MiniLM itself stays in-process for retrieval + HOPE (mandate unchanged).
  **Part 11 complete** — standing watch: production firing rates during the stability window.

---

## 14. PART 12 — Session pedagogy modes (EXPLAIN / PRACTICE / TEST) — Stages 1–4 + 6 BUILT

VanLehn's missing **outer loop** (task selection) over the existing per-turn inner loop.
Design of record: `PART12_PEDAGOGY_MODES_PLAN.md`. `session["mode"]` + a `ModeController`
(`session_modes.py`) dispatched at ONE point in `turn()` after `rules_decide`; EXPLAIN is
the default and byte-identical to pre-Part-12. Only these stages' **measured** results:

- **Stage 1 — mode substrate (BUILT, on-brain 2026-07-14).** ModeController (current/set/
  resolve/consume offers), deterministic cues (`cognitive_classifier/cues.py`
  `is_practice/test/explain/stop_test_request` — **standalone helpers, NOT CUE_NAMES
  entries**, so no classifier/shadow rebuild). Gate met: EXPLAIN decision surface
  (action/need/concept/signals/pending_check) **byte-identical** old-vs-new across 5 rule
  paths (confirmed twice); no perception/classifier rebuilds.
- **Stage 2 — PRACTICE ladder (BUILT, on-brain 2026-07-14).** `learner_state.apply_item_result`
  (third evidence API; item_history/test_history/mastery_gate/concepts_due_for_review, hint-
  discounted gains, ITEM_MASTERY_DELTA); adaptive fading ladder (entry by mastery, up on
  clean solve, down on wrong/3-hints, exit-to-EXPLAIN on 2 wrong at L0); pacing budgets
  COMPLETION_STEP/ISOMORPHIC/TEST_*/MODE_OFFER. Live: "let's practice" @0.65 → ISOMORPHIC_
  PRACTICE (level 2), Gemini isomorphic problem.
- **Stage 3 — TEST (BUILT, on-brain 2026-07-15).** **Store audit finding: ZERO stored
  answers** (0/245 problem_schema instances carry `expected_answer`; 0 concepts have ≥5
  schemas) → no stored quiz bank possible → **`build_quiz_bank.py` designed away; items are
  generated at serve time** (`tutor_loop.generate_quiz_item`, one structured Gemini call
  biased to a single numeric/short answer). Pure planning in `session_modes`
  (`build_quiz_set`/`advance_test`/`score_quiz`, N=5); `tutor_loop._drive_test` owns
  generation + the state machine + the 0.8 gate + Bloom corrective (fail → corrective
  EXPLAIN; concept carries `mastery_gate=failed_pending_retest` → later "test me" =
  parallel-form re-test). Deterministic **`math_grade`** floor under `judge_answer`
  (grader eval **26/26, ZERO non-attempts graded wrong** — hard gate). TEST item OWNS
  `pending_check` (4a-test; assessment ≠ probe-first). **Concept-LOCK** for the set's life
  (short answers re-classify turn-to-turn; without the lock the set restarted every item).
  Live: 5/5 on `fundamental_theorem_of_arithmetic` → gate pass, `test_history` written.
- **Stage 4 — T9 display + voice-plain generation (BUILT, on-brain 2026-07-15).**
  `tutor_loop._mode_display` emits `question_card`/`score_card` channel items (§5.6);
  `wini_platform/ui_cards.py` renders them at 480×320 (per-item marks drawn as shapes —
  cv2 has no tick/cross glyph); `wini_client/display_sinks.py` routes card `kind`s
  (`render_item_frame`), unknown kind ignored (ESP32/audio-safe). Generator now forced to
  voice-plain, already-evaluated answers + `_plainify_math` belt (LaTeX → speech). Live: 5
  question cards + 1 score card per test, questions come through as clean speech; per-turn
  latency 1.3–4.5 s. **Deferred:** on-DSI LVGL `show_card` (reserved client→UI message).
- **Stage 6 — reporting (BUILT 2026-07-15).** `progress_report.py` gained a per-concept
  `test` view (mastery_gate + last_test) + a top-level `quizzes` section + summary counts
  (`quizzes_taken`/`quizzes_passed`); `parent_ui/` renders a **Quiz results** panel + a
  gate badge on each topic card. Verified in-browser against a synthetic test_history
  (1 passed / 3 taken, newest-first, correct labels).
- **Deferred (owner, 2026-07-15):** Stage 5 perception signals (`practice_request`/
  `test_request`) — **BILLED + a design fork** (intent-enum, no `label_space` change, vs
  signal, which touches the trained `label_space.json` 38→40 and the head eval baselines via
  the build's exact-cover drift guard). Deferred because the deterministic cues already detect
  mode requests, so it is an optimization not a dependency.
- **Other pending:** Stage 3 sub-features `parked_questions` + R4 spaced-review swap-in (R4
  conflicts with the set-level concept-lock — needs per-item concept tracking). Full
  explain→practice→test spoken rig session; behavioral_eval mode-trajectory cases (§7.3).

---

## 15. PART 13 — Voice latency: the streaming pipeline — Stages 0–2 BUILT 2026-07-20

Design of record: `PART13_LATENCY_STREAMING_PLAN.md`. Converts the four blocking stages of a
voice turn into a stream so **time-to-first-audio stops scaling with answer length**. Answer
length stays entirely LLM-driven — this changed scheduling, not pedagogy. Every stage sits
behind an env flag (`WINI_STREAM_TTS`, `WINI_STREAM_GEN`), so rollback is one variable.

**Measured baseline (winipi5, 2026-07-20, `voice/latency_probe.py`, two turns):**

| stage | turn 1 | turn 2 |
|---|---|---|
| perception (`pacing.before_turn`) | 1322 ms | 37 ms (memoized) |
| brain (retrieval + generation) | 869 ms | 8661 ms |
| TTS (whole answer, one-shot) | **8332 ms** | **11239 ms** |
| **total before any sound** | **10527 ms** | **19941 ms** |

Answers were 262–268 chars → 22.6–29.8 s of synthesized speech, none of which started playing
until all of it existed. The plan's §1 table under-stated TTS (3.4–4.3 s) because its sample
answers were shorter; the coupling to length is the point.

- **Stage 0 — instrumentation (BUILT).** `latency_ms["perception"]` around `pacing.before_turn`
  (RC-4: it was counted nowhere, which is why the client logged 14.7 s turns against a 7.2 s
  `latency_ms`); a turn-scoped generation ledger in `tutor_loop` (`gen_stats_reset`/`gen_stats`
  → `gemini_calls`, `gemini_ms`); client-side `ttfa_ms` (`Ttfa`, armed when recording ends,
  marked by whichever audio path plays first); and `voice/latency_probe.py`, the replay harness
  that produced the table above — it runs against a **copy** of `learner_state.json`.
- **Stage 1 — streaming TTS + incremental playback (BUILT).** `CloudTts.synth_stream()` over
  `streaming_synthesize` (`synth()` untouched as fallback); `voice/chunker.py` `ClauseChunker`
  cuts a short first chunk then settles into sentence-length ones, and only ever breaks on
  punctuation followed by whitespace so decimals ("0.2") and maths phrases ("x squared") are
  structurally unsplittable; the server emits `{"part":"audio","seq":N,…}` NDJSON lines; the
  client plays chunk N while N+1 arrives, on a background player so the HTTP reader never
  blocks. `set_speaking()` spans the whole chunk sequence so the touch-emotion engine does not
  cut in mid-answer. **Measured: first audio chunk 267–987 ms vs 2040–4269 ms for the same
  answer one-shot.**
- **Stage 2 — streaming generation (BUILT).** `llm_vertex.generate_reply_stream()` over
  `generate_content_stream`, bounded per-delta *and* overall; `tutor_loop._stream_answer()`
  releases **sentence 0** the moment it exists so TTS starts on it while the rest is still
  being written. Only sentence 0 goes out early, and that is a proof rather than a guess:
  `_truncate_to_spoken_budget` keeps sentences in order and rewrites only the LAST kept one
  (and only when >1 is kept), so `kept[0]` is always `sentences[0]`. The remainder is released
  after truncation. Only the answer call site streams — the grader/cohesion/quiz sites parse
  whole JSON objects and must not. **Measured on a tutor-shaped prompt (5 runs): first token
  445–546 ms, first SENTENCE 495–661 ms, full answer 2025–2304 ms** — so streaming buys back
  ~1.5 s of the generation call, and Gemini's time-to-first-token is stable enough that it is
  not a variance source.
- **Also fixed (free ~1.3 s/turn):** the Part 11 Vertex context cache had **expired
  2026-07-03** and been silently absent for 17 days, so every perception call re-sent the full
  6,062-token static block. Recreated (same `context_sha 4585bdd31d0b686f`, so the prompt is
  unchanged): perception on a **fresh** utterance 2843–3533 ms → **1408–1806 ms**.

**Measured after Stages 0–2 (end-to-end through `/voice_turn`, mic-free driver):**

| utterance | stt | perception | brain | tts 1st chunk | **first audio** |
|---|---|---|---|---|---|
| "explain the discriminant to me" | 1320 | 1732 | 1243 | 987 | **4085 ms** |
| "what is a quadratic equation" | 949 | 1408 | 940 | 934 | **3303 ms** |
| "how do I factorise x²+5x+6" | 1634 | 1806 | 845 | 906 | **4410 ms** |

**Time-to-first-audio 10.5–19.9 s → 3.3–4.4 s**, and it no longer tracks answer length (the
22.2 s-of-speech answer starts sooner than the 14.1 s one). 96/37/61 chunks, **0 ordering
violations** across every turn measured.

**Client-path verification (playback + mic stubbed, everything else the shipped code):** 5
consecutive turns, 9/9 assertions each — streamed, answer NOT spoken twice from the final
line's back-compatible `audio_b64`, exactly one first/last chunk (fades only at the true
edges), `set_speaking` bracketing the WHOLE sequence as one True/False pair, `ttfa` marked on
the first chunk, UI driven once, display cleared once. Client-observed `ttfa_ms` across those
5 turns: **3434 / 3947 / 4007 / 7599 / 8807 ms (median ~4.0 s)**. The spread is *not*
generation — it is STT + perception on novel utterances, i.e. exactly what Stages 3–4 target.

**Audio quality (Stage 1 exit criterion, `_audio_quality.py`, 101-chunk answer):** long silence
runs 4 vs 4 for the same text one-shot — the pauses are the sentence pauses, not chunk seams;
max sample jump **at a chunk join 0.0897** against 0.4055 anywhere in the waveform, i.e. the
joins are smoother than ordinary speech transitions. No clicks, no gaps, no reordering.

**Accuracy guardrails (plan §5, all re-run after the change):**

| gate | result |
|---|---|
| `perception_eval --build --gates` | safety recall **1.0** (20/20), nonsense **1.0** (9/9), `learning_false_gate` 0 |
| `behavioral_eval --hardened --replay` | **PASS** — G1 0.8571, G2 0.8889, G3 0.0000 |
| `perception.test_perception --integration` | **PASS** — shapes, session policy, visual/purpose routing, topic shift, gates + belt + front door |

Perception prompt, schema, enums, `PERCEPTION_SIGNAL_THRESHOLD` and the deterministic safety
lexicon are **untouched** by Part 13 — only transport changed — which is why these hold
exactly rather than approximately.

### 15.1 Brain boot time — 126 s → 14.4 s (2026-07-20)

Separate from time-to-first-audio: the device was unusable for ~2 minutes after launch
because `TutorLoop()` construction measured **126 s**. Profiled per loader (`_profile_boot`),
the cost was not where the code reads like it is:

| item | before | note |
|---|---|---|
| `SentenceTransformer(...)` construction | **6.7 s each** | and NOT cheaper the 2nd time — no warm cache |
| `HopeDetector.load()` | 6315 ms | built an embedder that `tutor_loop` **discarded on the next line** |
| `load_chunk_index()` on a cache HIT | 7272 ms | reads like a 5 ms `np.load`; the cost was resolving the lazy `gp.embedder` it never needed |
| CloudStt / CloudTts / Vertex client | 4–9 s **each, serial** | ADC/channel setup (CLAUDE.md) |
| `load_store` (1017 chunks, 3562 nodes) | 75 ms | not a factor |
| `PolicyShadow.load`, `CognitiveAnalyzer` | ~5 ms | not a factor |

Fixes, in order of size:
1. `HopeDetector.load(..., embedder=)` — accept a shared embedder instead of building a
   throwaway. `tutor_loop` passes a `_LazyEmbedder` proxy so sharing stays lazy (assigning
   `gp.embedder` directly would have pulled the model in on the boot path anyway).
2. `load_chunk_index(chunks, embedder_provider)` takes a **callable**, resolved only on a
   cache miss — so a normal boot never touches MiniLM at all.
3. With MiniLM off the boot path, a background `minilm-prewarm` thread loads it during the
   cloud warmup (`WINI_PREWARM_MINILM=0` disables). Correctness never depends on it: the
   first turn blocks on the property if it somehow arrives first.
4. `Brain._load` builds TutorLoop + STT + TTS + the Gemini warm **concurrently**, and runs
   the perception/TTS warm calls concurrently too. `llm_vertex._client` memo is now
   lock-guarded because two of those warms race for the same client.

**Measured after: READY in 14.4 s** — components built 2242 ms, warmup 9951 ms, MiniLM
finishing in the background at 10806 ms (overlapped, not serial). Turns verified unchanged
afterwards, including a `display=True` / `REPRESENTATION_TRANSLATION` turn, which proves
MiniLM retrieval and figure selection still resolve correctly through the lazy proxy.

*(The 126 s baseline was a cold first run — cold SD page cache; the 14.4 s is warm. The
structural wins above are condition-independent: two whole MiniLM loads removed from the
boot path and four serial cloud-client constructions made parallel.)*

- **NOT built: Stage 3 (streaming STT + tighter endpointing)** and **Stage 4 (speculative
  perception + parallel grader).** With Stages 0–2 in, the remaining per-turn cost is STT
  (0.9–1.6 s) + perception (1.4–1.8 s) + the client's fixed 1200 ms VAD hangover, which is
  what those two stages target (plan projects ~2.0 s TTFA). Stage 4's speculative perception
  depends on Stage 3's interim transcripts; the parallel grader within Stage 4 is independent
  but did not fire in any measured turn here (`gemini_calls` was 1 throughout), so its win is
  unquantified on this workload.

---

**Open items:** local-VAD barge-in (currently half-duplex), Part 13 Stages 3–4 (Cloud STT
streaming + speculative perception; batch STT and the 1200 ms hangover remain), and tuning the
RMS endpoint threshold/`silence_ms` for child speech.

---

## 16. PART 14 — Brain architecture audit remediation — **ALL 16 DEFECTS FIXED 2026-07-23**

Source: `BRAIN_ARCHITECTURE_AUDIT.md` (device-verified audit of the deployed brain against
`learner_cognitive_state_architecture.md`). Fixed in the audit's own suggested order, each
stage verified on `winipi5` (`192.168.29.24`) before the next was started. Contract decisions
landed in architecture §6.1 / §6.4 / §6.6 / §6.7 in the same session (lockstep rule).

### Stage 1 — B-1: `\frac{}{}` destroyed spoken fractions

`sanitize_for_speech` stripped `\command` names but never braces, so the brace pair survived
as silent glue. Measured on the exact strings the device generated:

| input | before | after |
|---|---|---|
| `Time is $\frac{63}{x}$ hours.` | `Time is {63}{x} hours.` | `Time is 63 over x hours.` |
| `x = $\frac{378}{9}$ = 42` | `x equals {378}{9} equals 42` | `x equals 378 over 9 equals 42` |

Not a mispronunciation — "63 over x" became "63 x", a **different quantity**, spoken to a
child as maths instruction. Both strings are now regression samples in the suite.

### Stage 2 — D-1 + A-2 + A-3: the tutor can solve the problem the student brought

- **D-1** — revived the one piece of `InputProcessor` the runtime still needs, as a new
  purpose-built `detect_student_problem` rather than the existing `_contains_formula`, which
  fires on any `+`/`-` anywhere (a hyphen in "well-known" counted as an equation). 18/18 on a
  hand-built positive/negative set; "find the area of a circle" (teach) correctly separates
  from "calculate the area when the radius is 7 cm" (solve).
- **A-2** — added `SOLVE_STUDENT_PROBLEM` + rule 4b above the transfer rule.
- **A-3** — truncation is now structure-aware and the action carries a 130-word/9-sentence
  budget; the generation token ceiling was raised 240 → 480 so the derivation is not cut
  before its answer exists.

Measured, on the audit's own probes (`GEN_BACKEND=gemini`, `PERCEPTION_BACKEND=gemini`):

| probe | before | after |
|---|---|---|
| train/car word problem | `TRANSFER_PROBLEM` ("do NOT solve it") | `SOLVE_STUDENT_PROBLEM`, delivers `x = 42`, 42 km/h and 48 km/h |
| `solve x^2 - 5x + 6 = 0` | `QUIZ` | `SOLVE_STUDENT_PROBLEM`, delivers `x = 2` and `x = 3` |
| truncation of the ~190-word solution at EXPLAIN's 65/4 | setup only, `x = 42` silently dropped | result line protected, answer survives at **every** budget tested (10/1 … 130/9) |

**One non-obvious interaction, found by live testing.** With a `pending_check` armed, Gemini
scores an incoming problem as an `answer_attempt`, so the first fix was swallowed on the
quadratic probe (it routed to `QUIZ`). Hence the `directive` distinction in §6.1: a bare
equation defers to the grader, an imperative aimed at the tutor does not. A directive problem
is also treated as a **non-attempt**, so the pending diagnostic is neither graded nor lost —
verified: the bridge check survived un-graded, no mastery moved.

### Stage 3 — A-7: 593 chunks permanently blacklisted

`session.served_items` is persisted and only `/api/reset-session` (a different entry point)
cleared it. Added `LearnerState.begin_session()`, called at brain boot. Measured on the
device: **593 → 0** served items and 0 bridges on the first restart, with mastery untouched
(11 of 41 states carry a measured value, before and after). The hard `continue` became
`w8_repeat_penalty` (0.25); ranking now behaves:

| served | ranking |
|---|---|
| none | `best 0.65`, `weak 0.43` |
| `best` | `weak 0.43`, `best 0.40` (demoted, still available) |
| both | `best 0.40`, `weak 0.18` (resurfaces instead of an empty pool) |

### Stage 4 — B-2 + B-3: no LaTeX, no contradicting visual

The no-LaTeX instruction existed only in `generate_quiz_item`; it is now in the main answer
prompt's style block. Live: both solve probes returned **zero** `$`, `\frac`, `\sqrt` or brace
markup, versus LaTeX throughout beforehand.

The tier-3 teaching visual got the absolute floor it never had. Measured against the live
chunk index:

| utterance | best crop | verdict |
|---|---|---|
| `solve x^2 - 5x + 6 = 0` | prayer-hall area diagram, **0.221** | below 0.30 → **no visual** (was shown) |
| train/car problem | dice-probability table 0.020; whole pool ≤ **0.242** | below floor → **no visual** (was shown) |
| area of a segment | 0.63 | shown |
| what is probability | 0.46 | shown |

**v5.3 (2026-07-23): the tag filter was hiding the right figure — relevance-first
selection.** Field report: a Qutub Minar explanation displayed a generic lettered
triangle. Root cause was not the floor but the *pool* — tier 3 hard-filtered
candidates to those tagged with the resolved concept, and `fig::jemh108::fig_8_1`
(the Qutub Minar diagram) carries only the legacy tags `trigonometry` /
`grade9::right_triangles`. It scores **0.749** on that utterance; the best tagged
crop scored **0.438** and won by default.

Now: score every crop, then admit by origin (in-chapter, concept-tagged, or
≥ `T9_CROSS_CHAPTER_MIN` 0.57 from elsewhere — the minar *figure* is in Ch 8 while
the minar *application* concept is in Ch 9); concept tag became a 0.12 tie-break
bonus; portraits (Gauss, Laplace, Thales) excluded by kind; floor re-measured
0.30 → **0.42**. Cost is one matrix multiply against a crop matrix built during
warmup — measured **`t9` = 113–136 ms** per turn.

Swept over 17 utterances spanning every chapter (`tools/t9_probe.py --cases`):

| utterance | before | after |
|---|---|---|
| qutub minar example (concept → Ch 8) | 0.438 generic triangle | **0.749 Qutub Minar** |
| qutub minar example (concept → Ch 9) | 0.438 generic triangle | **0.749 Qutub Minar** (cross-chapter) |
| when are two triangles similar | none | **0.735 two similar triangles** |
| solve two linear equations by graph | none | **0.590 the two lines plotted** |
| what is the fundamental theorem of arithmetic | 0.541 **portrait of Gauss** | none |
| what is the probability of getting a head | 0.310 spinner (coin question) | none |
| `solve x^2 - 5x + 6 = 0` | none | none (B-3 case preserved) |
| elevation / tangent / segment / polynomial zeroes / shadow | correct | unchanged |

11 of 17 now show a figure that matches the speech; the other 6 correctly show
none. Live on the device the answer and the picture agree — *"In the Qutub Minar
example, imagine a person standing some distance away from the base… look at the
figure"* alongside the diagram of exactly that.

### Stage 5 — the contract-level defects

| ID | Fix | Verified |
|---|---|---|
| A-1 | grounding split `manifest_only` / `method_only`, recorded per turn | log shows `grounding=method_only` on solve turns, `manifest_only` on a curriculum turn |
| A-4 | `MIN_ABS_RELEVANCE` 0.28 + abstention path + trace | `abstained=false, eligible=2` on the train/car turn (22 of 24 candidates filtered), `eligible=24` on-topic |
| A-5 | `w4_repr_gap` now graded (fraction missing) not binary; second writer added (correct answer on a representation-bearing item) | term no longer constant across candidates |
| A-6 | flags stamped in `flag_seen`, TTL 14 days, filtered on dashboard read too | a 2020-dated flag decays away while the re-observed one is kept |
| A-8 | bridges ranked by relevance to the utterance, floor 0.20, max 1/turn, deterministic tie-break | train/car turn now arms **no** bridge (`bridge_ids: []`, `pending_check: null`) — was an unrelated Class-9 mean/average or probability diagnostic, and it differed between identical runs |
| B-4 | pacing ledger keyed on `explaining_concept`, resets on topic change | step 230 + a trigonometry summary → step 1 on a quadratics turn; same concept advances 1→2; new concept resets again |
| B-5 | one `mathtext.py` behind all three surfaces | cross-surface suite passes; merging exposed a real bug — the quiz path rendered `\geq` as `">= q"` |
| D-3 | four §6.4 fields implemented with APIs + snapshot exposure | `cold_recall=None trend=unknown transfer_readiness=0.0 hint_pos=0` — honest "unmeasured", not fabricated numbers |
| D-4 | `has_measured_mastery()`; band reason distinguishes the cases | `cold start (touched, mastery never measured)` vs `(unseen concept)` vs `learner state (measured)` |
| D-8 | `last_signals` written (the docstring had always claimed it) | present on the concept state after a turn |

### What is NOT done

- **D-7** (doc's action list omits `WHY_IT_MATTERS` / `SOCRATIC_Q` / `QUIZ` / the Part-12
  `TEST_*` family, and lists "faded hint"/"cold recall" behaviours with no action) is a
  documentation-only divergence; §6.6 now names `SOLVE_STUDENT_PROBLEM` but the full
  reconciliation of that list is still open.
- The `transfer_readiness` field is implemented and exposed but **rule 5 still routes on the
  perception signal**, not on the measured quantity. Switching it is a pedagogy change that
  wants its own before/after evaluation, not a same-session edit.
- Verification used `tutor_loop --once` and `/turn`. The pacing governor only runs on
  `/voice_turn`, so B-4 was verified by driving `after_turn` directly against a real loop
  rather than through a spoken turn.

## 17. PART 15 — Cloud execution: the whole brain warm on Cloud Run + Firestore — **Phases A/B/C/E BUILT + verified, D partial, F deferred (2026-07-25)**

Design of record: `PART15_CLOUD_EXECUTION_PLAN.md`. Executes the brain as a warm,
streaming Cloud Run service without losing a point of pedagogical accuracy. The plan's
central finding held: the brain is already a cloud-native monolith with server-side Vertex
calls — the work is deployment, persistence, and scheduling, **not** the pipeline.

**Baseline first (frozen splits, current `gemini-2.5-flash`):** perception concept top-1
**0.930** / top-3 **0.990**, intent **1.0**, safety gate **1.0**; behavioral eval **PASS**;
`test_perception --integration` PASS. The before-picture every phase is held against (§7).

### Phase C — model tier (the plan's headline latency lever) → measured a REGRESSION, shipped as the seam only
The plan targeted **Gemini 3.x Flash / 3.5-Flash-Lite**. Probed directly against Vertex:
those IDs **do not exist** (404 in asia-south1 / us-central1 / global). The only real faster
model, **`gemini-2.5-flash-lite`**, is absent from `asia-south1` and served only on `global`
/ `us-central1`. Measured (warm, n=4):

| config | TTFT median | small-call median |
|---|---|---|
| **flash@asia-south1 (current)** | **602 ms** | **582 ms** |
| flash-lite@global | 617 ms | 683 ms |
| flash-lite@us-central1 | 770 ms (jittery) | 934 ms |

Flash-lite is **slower** here — the 31 ms asia-south1 RTT beats its per-token edge on these
short replies, and it is not co-located. So the swap is all cost (threshold re-calibration,
lost context cache on `global`), no benefit. **Decision: stay on `gemini-2.5-flash@asia-south1`.**
Phase C delivered as the **revertible seam**: `llm_vertex.SMALL_MODEL`/`SMALL_LOCATION`
(default = generation flash@asia) + a `small=` flag on `qwen_chat`/`_gemini_chat`, with
grader/cohesion/persona tagged `small=True`. No-op at the shipped default; a genuinely faster
co-located model becomes a one-line env flip. No accuracy re-run needed — the model is unchanged.

### Phase B — parallel grader · removes the RC-3 serial-grader block
`WINI_PARALLEL_GRADER` (default on). The grader needs only the armed `pending_check` +
transcript — never perception — so `voice_turn` submits `judge_answer` on the server pool
**concurrently with the perception call**, joins it, and threads the result as
`precomputed_grade` (turn→text_turn→voice_turn). It is consumed only on the exact branch that
would otherwise call `judge_answer`; a non-attempt still scores `not_an_answer`. **Equivalence
test PASS**: serial vs parallel produce identical outcomes with **0 grader re-calls**, and a
different precomputed value genuinely changes the outcome (proving it is used, not ignored).
Speculative *perception* (the plan's other Phase-B half) needs streaming-STT interims and is
folded into Phase D.

### Phase E — learner state → Firestore · the one real persistence change
`state_backend.py`, `WINI_STATE_BACKEND=json|firestore`. The whole state is stored as **one
JSON string field** (`state_json`) — deliberately, to sidestep every native-Firestore type
limit (nested arrays-of-arrays round-trip fine) and keep the write a single atomic
last-writer-wins `set`. The server **reads once at startup** and **writes at the turn boundary**
(`_persist_state`, after the lock, off the TTFA path) — **never mid-turn** (the plan's §6-E
contract). Firestore **native DB created in `asia-south1`**. Round-trip exact incl. nested
arrays; **restart-durability sentinel test PASS** — a fresh instance logs `loaded learner
state from firestore://…`, and an injected sentinel survives the next turn's persist (proving
load, not cold-start-and-overwrite). No turn-time regression.

### Phase A — deploy the monolith to Cloud Run · the biggest unlock
`Dockerfile` (python:3.12-slim, **CPU-only torch** from the pytorch index so no multi-GB CUDA,
**MiniLM baked** so cold start never waits on HuggingFace) + `.dockerignore`/`.gcloudignore`.
Cloud Build ~4.5 min → `asia-south1-docker.pkg.dev/<proj>/wini/brain:v1`. Deployed service
**`wini-brain`** (asia-south1): **`min-instances=1`, `concurrency=1`**, cpu 4 / 8 GiB,
**`--no-cpu-throttling`** (non-negotiable — the brain loads in a background thread; throttled
CPU outside requests would stall it), runtime SA `wini-brain`
(aiplatform.user + datastore.user + serviceusage.serviceUsageConsumer),
`WINI_STATE_BACKEND=firestore`. **Exit met:** `/health` `ready:true`; **10 live authenticated
turns** all coherent; **turn 1 = 4.7 s wall / 4.2 s brain — no cold-start cliff** (comparable
to later turns); per-turn latency 2.6–4.2 s brain, within Part 13's on-device envelope; the
deployed instance verifiably writes durable state to Firestore (`learner_state/cloudrun_default`,
8 concepts after the run).

| turn | wall | brain | gemini calls |
|---|---|---|---|
| 1 (cold-start check) | 4686 ms | 4165 ms | 2 |
| 4 | 3319 ms | 3036 ms | 2 |
| 7 | 2919 ms | 2651 ms | 2 |
| 10 | 3582 ms | 3364 ms | 2 |

### Phase D — streaming STT · core built + parity-verified, client integration remaining
`voice/cloud_stt.recognize_stream` (v1 `StreamingRecognize`, **the same `RecognitionConfig` +
`MATHS_PHRASES` boost as the batch path** — parity by construction, not hope), with an interim
hook (the seam speculative perception waits on) and a tail-guard (keeps a last un-finalized
interim so streaming never drops the final word). **Hard gate PASS: 20/20 streaming transcript
== batch transcript** on a 20-utterance TTS-generated fixture, real-time paced. Kept on v1
(not v2/Chirp3) precisely to hold the accuracy gate — a Chirp3 swap would need its own
before/after. **Remaining:** the *client* must stream PCM live during speech (the `/voice_turn`
contract change) for the latency benefit; that is device-only and not headless-testable, so it
is the open integration step.

### What is NOT done (Part 15)
- **Phase F (Provisioned Throughput)** — needs sustained real daily traffic to clear break-even
  and a billing commitment; a judgment call on measured p95/p99, not a code change.
- **Phase D client streaming** — the device must feed real-time PCM blocks and drop `silence_ms`;
  needs the Pi client + real audio.
- The Cloud Run service is deployed **authenticated** (`--no-allow-unauthenticated`); the thin
  client will need an identity token / auth path before it can call the cloud brain directly.

**Accuracy posture (§7, non-negotiable):** the perception prompt, schema, enums,
`PERCEPTION_SIGNAL_THRESHOLD`, safety lexicon, context cache, and every `derive_*`/`apply_deltas`
write-back are **untouched**. Phases changed deployment, persistence, and scheduling — not
pedagogy. The grader change is outcome-identical by test; the model is unchanged, so the
baseline gates above still hold.

### P0 Evidence Integrity — COMPLETE locally (2026-08-12)

- Added typed `evidence/` ledger/grading/replay and `items/` candidate/verification/bank modules.
- Made `record_outcome`, `arm_from_script`, and `items.verify` the three mandatory choke points;
  static invariant tests prove the only projection, pending-check assignment, and generated-bank
  append call sites.
- Migrated bridge, misconception, PRACTICE, TEST, response-layer device outcomes, serial grading,
  and concurrent grading. STT confidence/turn identity/idempotency now reach the ledger.
- Added fail-closed identity binding, safety tier/redaction, sparse global observations,
  deterministic streaming-compatible realization checks, TEST non-disclosure, measured transfer
  readiness gating, bridge-partial separation, and no-verified-item downgrade.
- Measured: P0 33/33; response/Board Buddy 77 pass, 5 dependency/fixture skips; golden items 50/50;
  regression harness all checks pass; gate recall 20/20 safety and 9/9 nonsense; compileall and
  diff checks pass. Model-free P0 microbench: realization p95 0.0118 ms, incremental ledger append
  p95 0.2605 ms, duplicate lookup p95 0.0023 ms; zero added TTFA/model calls by placement.
- Migration and rollback: `P0_EVIDENCE_MIGRATION.md`. P1-P4 intentionally remain unstarted.
# Baseline Split checkpoint — lifecycle contracts and state (2026-08-14)

Issue 13 is implemented as an additive checkpoint: immutable lifecycle contracts,
capability-scoped state views, a validated working projection, authoritative evidence
application, and one optimistic whole-state commit through production and deterministic
adapters. Issue 14 now activates this foundation from `TutorLoop` through the temporary
legacy adapter; later checkpoints replace that bridge phase by phase.

Measured verification: 18 new interface tests passed, full `unittest` discovery passed
34 tests, the existing P0 evidence/state runner passed 33 tests, and all 16 frozen
oracle tests passed. Oracle corpus validation passed and the frozen reference reported
zero differences. A complete oracle verdict remains unavailable because the frozen
baseline documents missing runtime artifacts and incomplete model replay coverage.

## Coordinator routing (issue 14)

Issue 14 is active: every canonical `TutorLoop.turn()` call now constructs a typed immutable
Turn Input, traverses the Turn Coordinator, receives a committed typed Turn Result from the
explicit temporary legacy adapter, and serializes the established compatibility dictionary.
The full feature implementation remains in `_legacy_turn` for sequential extraction; the
coordinator contains phase order and failure/recovery policy only.

The Runtime Supervisor aggregates typed failures into `STARTING`, `READY`, `DEGRADED`, and
`UNAVAILABLE`, with the state exposed by the server health response. Existing provisional
speech/meta sinks and terminal exceptions are unchanged. Adapter counters expose one legacy
execution and the number of unextracted phases per Turn. Verification counts are recorded in
the work log after the final full-suite run. Measured verification passed 44/44 full-discovery
tests, 33/33 P0 evidence/streaming invariants, 14/14 focused runtime tests, 16/16 frozen-oracle
tests, the 27-case corpus validation, compilation, and diff checks. The frozen reference
self-check remains zero-difference; its missing-artifact/incomplete-replay limitation is
pre-existing and still prevents a complete verdict.
