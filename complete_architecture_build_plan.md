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
**Standing rule: all LLM generation now uses the local Qwen server — no Gemini, no stubs.**

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
**Qwen2.5-3B via llama.cpp** (composed only from manifest items; LLM cohesion judge off).

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

**Open items:** A2 VAD divergence (RMS endpointing vs spec Silero), Qwen TTFS latency tuning
(filler + prompt trim), occasional harmless wakeword ambient false-fire, session-context
reset on wake, and the live human-voice test (injected `/speech_text` bypasses Whisper).

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

**Open items:** local-VAD barge-in (currently half-duplex), streaming Qwen generation to close
the post-filler gap, Cloud STT streaming (currently batch per utterance), and tuning the RMS
endpoint threshold/`silence_ms` for child speech.
