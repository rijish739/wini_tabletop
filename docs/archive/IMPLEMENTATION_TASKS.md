# Wini — Pending Implementation Tasks

> Concrete, actionable task spec compiled from a line-by-line pass (×2) over
> `rag_memory.md`, `complete_architecture_build_plan.md`, `model_dataset_architecture_report.md`,
> `RAG_upgrade_plan.md`, `WINI_VOICE_STUDY_ARCHITECTURE.md`, `learner_cognitive_state_architecture.md`,
> and `agent_feedback.txt`. Each task states **what / why / how**, the files it touches, and an
> acceptance check. Nothing pending in those documents was intentionally omitted.
>
> **Explicitly out of scope** (per standing instruction): AEC (`aec_pkg`), full-duplex
> operation, and semantic barge-in (C3). Disfluency repair and wakeword pre-roll ride with AEC
> and are likewise deferred. They are listed once in [§9](#9-deferred-not-in-this-pass) for
> completeness only.

## Priority legend

| Tag | Meaning |
|---|---|
| **P0** | Foundational / unblocks many other tasks |
| **P1** | High impact, buildable now with current data |
| **P2** | Valuable, but depends on real-learner data or a P0/P1 task |

## Dependency map (read this first)

```
T1 Real-learner logging (P0) ──┬─► T11 Neural KT
                               ├─► T12 Neural policy promotion
                               ├─► T13 Neural reranker / weight tuning
                               ├─► T14 Engagement predictor
                               └─► T20 Pilot outcome metrics
T2 acknowledgment label (P1) ──► classifier rebuild
T3 weak-label data pass (P1) ──► classifier rebuild
T6 HOPE teacher re-label (P1) ─► T7 HOPE detector retrain ─► better w7 ranking
T8 Display channel (P1) ───────► T9 Load-modulated budget (P1)  [both = pacing UX]
```

---

# 1. DATA & DATASETS

## T1 — Capture real learner-conversation logs *(P0, blocks all neural upgrades)*

**What.** Stand up a small, consented data-collection loop that records full turn traces from
real Class-10 students using the tutor (text or voice), into the existing append-only
`rag_store/learning_log.jsonl`, plus delayed retention/transfer re-checks at 3 / 7 / 21 days.

**Why.** Every neural model in `model_dataset_architecture_report.md` that is currently
deferred — knowledge tracing (§7.1), neural pedagogy policy (§6), reranker (§4.2), engagement
predictor (§7.5), misconception tracker (§7.4) — is explicitly waiting on *real* logs. The
report (§2.2) ranks "real learner logs" as the highest-value label source, and the build plan
(Part 6/8) and `rag_memory.md` open-item 4 both gate the pilot metrics on real learners. Today
all gold is synthetic / LLM-derived, which is the single largest correctness caveat in the
project (HOPE labels, policy top-1 — 0.558 → **0.680** after the 2026-06-19 fixed-source
rebuild, classifier long tail — partly addressed by the T2/T3 data pass).

**How.**
1. The turn schema already exists — `tutor_loop.turn()` writes the manifest, cognitive update,
   action, shadow suggestion, and write-back outcome per turn (see `learning_log.jsonl`). Add
   the missing longitudinal fields from report §2.1: `student_id_hash`, `session_id`,
   `short_term_outcome` (next-answer-correct, confusion-reduced, hint-used), and a
   `delayed_outcome` stub (`retested_after_days`, `retention_correct`, `transfer_correct`).
2. Add a tiny scheduler/CLI that, per learner, re-serves a held item at +3/+7/+21 days
   (reuse `query.py --need review`) and writes the result back into the originating turn's
   `delayed_outcome`.
3. Add a consent + ID-hashing step at session start (hash the student id; never store raw PII —
   consistent with the privacy boundary in the voice report: cloud sees only audio/answer text).
4. Run a 2–4 week pilot (report Phase 3 begins "immediately after prototype").

**Files.** `tutor_loop.py` (turn-result fields), new `collect_delayed.py`, `learner_state.py`
(per-learner state files), `device_config.py` (data dir).
**Acceptance.** ≥ 40,000 policy traces accumulate (report §6.3 minimum); ≥ 20 % of trajectories
carry a delayed-outcome label; logs validate against the report §2.1 turn schema.

## T2 — Add the `acknowledgment` label and re-curate *(P1)*

**What.** Introduce a first-class `acknowledgment` label to the cognitive-classifier label
space and add positive examples ("yes got it", "ok makes sense", "understood").

**Why.** Recorded gap in the build plan (tutor_loop v3) and `rag_memory.md`: MiniLM embeds
"makes sense now" next to "not making sense now", so the classifier misreads pure acks as
`confusion` (~0.55). Today this is patched only by the deterministic `is_pure_ack` cue in
`cognitive_classifier/cues.py`; a real label makes the signal learnable and lets
`METACOGNITIVE_REFLECT` routing rest on the model, not just a regex.

**How.**
1. Add `acknowledgment` to `cognitive_classifier/label_space.py` (canonical map).
2. Author/curate ~300–500 positive ack utterances + hard negatives ("yes, but why…",
   "yes because D<0…") in `curate_dataset.py` → writes a new `*_curated.json` (originals are
   read-only, per CLAUDE.md). Reuse the disqualifier markers already in `cues.py`
   (`because/since/as/but`).
3. Rebuild: `python -m cognitive_classifier.build_bank` then rebuild the policy shadow
   (the shipped logreg width is baked to CUE_NAMES + label count — see CLAUDE.md gotcha:
   adding a cue/label requires rebuilding **both** the classifier bank and the policy shadow).
**Acceptance.** `acknowledgment` F1 ≥ 0.80 on the curated test split; `is_pure_ack` cases no
longer fire `confusion` > 0.4; analyzer tests (`-m cognitive_analyzer.test_analyzer`) green.

## T3 — Weak-label data pass for the classifier long tail *(P1)*

**What.** Raise real test-set support and accuracy for the labels the build plan flags as weak:
`answer_attempt` (7 test rows), `self_correction` (19), `high_confidence` (21),
`hint_dependency` (18), `representation_shift` (36).

**Why.** Build plan Part 1 §2.5.1: "the honest blocker is **test-set support**, which only more
real (or held-out-quality) labeled data fixes." `high_confidence` additionally suffers from
MiniLM polarity blindness ("so easy" ≈ "so hard").

**How.**
1. For the four behavioural labels, collect from real logs (T1) and/or generate targeted
   utterances where the rare label is **primary** (reuse `augment_rare_labels.py`, now via the
   **local Qwen server**, not Gemini — standing rule in build plan Part 2). Add to the **train
   bank only**; never into val/test (frozen `splits.json`).
2. For `high_confidence`/polarity: add explicit surface-cue features in
   `cognitive_classifier/cues.py` (confidence markers "easy/sure/obviously" vs hedges) —
   pooled embeddings dilute these. Remember the CLAUDE.md gotcha (rebuild both models).
3. Keep all generated rows through the same curation rules so they can't smuggle bad labels.
**Acceptance.** Each target label has ≥ 100 train + ≥ 30 *real* test rows; macro-F1 improves
without regressing the head labels (confusion/curiosity/question/request_hint).

## T4 — Normalize off-action-space policy tags in the exemplar set *(P1, quick)*

**What.** Fix the ~19 exemplar rows that carry `target_policy_action` values outside the
canonical 15-action space.

**Why.** `rag_memory.md` post-plan addendum: "~19 rows carry off-action-space
`target_policy_action` tags … normalize before policy use." Left as-is they corrupt any
policy retraining.

**How.** In `curate_dataset.py` (or a small `normalize_actions.py`), apply the existing
`policy_shadow.canonicalize_action` map (multi-action → first listed; `VERBAL_ANALOGY →
VISUAL_ANALOGY`; drop `RESUME_STATE`/`REQUEST_HINT`). Write a new curated file; log the diff.
**Acceptance.** 0 rows with an action outside the 15-action space; `build_policy.py` consumes
the file with no skipped rows.

## T5 — Scale the seed-level derived datasets *(P2, after T1)*

**What.** Grow `representation_tagger.jsonl` (953 rows), `misconception_clue_bank.jsonl`
(1,504), and `grounding_guard.jsonl` (3,584) toward the report's strong-prototype volumes.

**Why.** `rag_memory.md`: these three are "SEED-level exemplar banks (store exhausted — scaling
needs generation or real logs)." The report targets 15k–40k (representation), 20k–40k
(misconception), 50k (guard).

**How.** Two sources: (a) real logs from T1 (preferred — every response+manifest pair is a free
grounding-guard example, every served hint a leak/no-leak example); (b) local-Qwen generation
of near-miss/hard-negative variants, validated deterministically as `build_local_datasets.py`
already does. Re-run `python build_local_datasets.py --verify` (must stay 20/20).
**Acceptance.** Each dataset ≥ report minimum; `--verify` 20/20; no cross-split leakage.

---

# 2. HOPE METRICS

## T6 — Replace HOPE rater B with human-teacher answer labels *(P1)*

**What.** Re-label the HOPE gold answers with a real teacher (currently rater B is an LLM
stand-in), resolve the 18 `needs_expert_review` answers, and rewrite/drop the prompts flagged
`status: rewrite_or_drop`.

**Why.** The headline caveat across `rag_memory.md` Phase 6 + Part 4 and `RAG_upgrade_plan.md`
§6.4: the κ ≥ 0.6 gate passed as **LLM–LLM** agreement; `final_label = round((rater_a +
rater_b)/2)` is still LLM-derived. The report (§5.6 step 3, §9.2) requires teacher labels before
scaling the bank toward the 5,000+/signal production target.

**How.**
1. Hand the teacher `rag_store/hope_gold_set.jsonl` (888 answers post-clean) blind-shuffled per
   prompt (reuse the Phase-6 shuffling so order leaks nothing).
2. Recompute κ(teacher, LLM) per signal; keep the calibration gate ≥ 0.6 and the
   memorized-vs-strong ≥ 1-ordinal separation on ≥ 85 %.
3. Re-derive `final_label` from teacher labels; rewrite/drop the flagged prompts; re-run
   `verify_store.py` (HOPE ≥ 950 total, ≥ 300/signal must hold).
**Files.** `hope_detector/clean_bank.py`, `rag_store/hope_gold_set.jsonl`,
`rag_store/hope_prompt_bank.jsonl`, `verify_store.py`.
**Acceptance.** κ(teacher,·) ≥ 0.6 per signal; bank still ≥ 300/signal; scorecard 100 %.

## T7 — Retrain HOPE detectors + fix absolute calibration *(P1, after T6)*

**What.** Retrain the per-signal ordinal detectors on teacher-relabelled gold and raise QWK on
the two weak signals (KI 0.527, KT 0.448 — both below the 0.6 desideratum; CT 0.651 already
meets it). Add an absolute-score calibration layer.

**Why.** Part 4: detectors "discriminate well RELATIVELY … but absolute scores are conservative"
— fine for w7 (boosts the weakest signal) but wrong for any absolute threshold. KI/KT QWK below
0.6 limits trust.

**How.**
1. Re-run `hope_detector/build_detector.py` on the new gold (keep the answer-only embedding +
   scalar features — embedding prompt+answer+rubric together was the failure mode).
2. Add more labeled answers per prompt (T1 real attempts are ideal) to lift KI/KT QWK.
3. Fit a per-signal isotonic/Platt calibrator on held-out answers so runtime scores are
   absolute-meaningful, then expose a calibrated `score` alongside the raw one.
**Acceptance.** KI & KT QWK ≥ 0.6 (CT maintained); discrimination gate (strong−memorized ≥ 1.0)
still passes on all three; calibration error reported.

## T8 — HOPE-signal weak-supervision sanity sweep *(P2, quick)*

**What.** Run the `derive_cognitive_update` HOPE-signal mapping over the full exemplar dataset
and sanity-check the distribution.

**Why.** Build plan Part 3 "still open": a nice-to-have validation of the label→aggregate
formulas that was never run.
**How.** Script over `dataset/exemplar_dataset_10000_curated.json`; histogram the derived
KI/KT/CT proxies vs the `hope_signals` column; flag systematic mismatches.
**Acceptance.** A short report; any mapping bug filed/fixed.

---

# 3. PEDAGOGY, PACING & MULTIMODAL

## T9 — Multimodal display channel (the "show, don't only tell" path) — *flagship #1* *(P1)*

**What.** Add an output channel that **displays** the figure crop / symbolic step-card the
retrieval layer already selected, in sync with speech — so geometry, graphs, and representation
translations are *shown*, not just narrated.

**Why.**
- Cognitive-expert verdict in `agent_feedback.txt` (§4, §5): for conceptual maths "a picture is
  better for content"; long speech-only monologues overtax a child's working memory. The single
  biggest comprehension lever the architecture is **not yet using**.
- The data already exists end-to-end but dead-ends at audio: `query.py` builds the manifest with
  `image_path` for `figure_caption` evidence (`tutor_loop.py:541`, `:649`), figures carry
  `supports_representation` / `addresses_gap` semantics (architecture §6.5, §9), and the
  `REPRESENTATION_TRANSLATION` / `VISUAL_ANALOGY` actions exist (§6.6). Nothing renders them.
- This is an extension, not a redesign — architecture §9 already says "serve the textbook's own
  cropped figure, not a verbal description of it."

**How.**
1. **Surface the asset in the turn result.** In `tutor_loop.turn()`, after the manifest is
   built, extract display items: any `manifest.evidence[i]` with `type == "figure"` and a
   non-null `image_path` (also accept `kind == "figure_caption"`). Add a `display` list to the
   returned dict: `[{image_path, alt_text, why, supports_representation}]`. (The fields are on
   the graph node — `self.figure_misconceptions` already indexes `image_path` nodes at
   `tutor_loop.py:359`.)
2. **Decide speak / show / both.** Show when (a) action ∈ {`REPRESENTATION_TRANSLATION`,
   `VISUAL_ANALOGY`}, or (b) the resolved concept's `representations_missing` intersects the
   crop's `supports_representation`, or (c) the crop `disambiguates_misconceptions` for an
   `active` misconception. Otherwise audio-only. Keep it to **one** primary visual per turn
   (working-memory limit).
3. **Render it.** Add a minimal display adapter:
   - Windows rig: a small always-on-top Tk/Qt pane (or write the crop path to a watched file a
     browser tab reloads) driven from `voice_hybrid_runner.py` right after
     `result = loop.turn(...)` (`voice_hybrid_runner.py:129`) and synced to TTS start.
   - Jetson: publish the `image_path` on a new ROS topic `/display_image` from
     `wini_brain_node`; a lightweight display node shows it on the robot screen.
   - Abstract behind a `DisplaySink` protocol (like the STT/TTS adapters) so both share code.
4. **Sync to speech.** Put the image up when the first sentence starts streaming to TTS; clear it
   on `/tts_done` (Jetson) or playback end (Windows). Resolve `image_path` via `device_config`
   (relative to store root — never hard-code).
5. **Reference it in words.** The Qwen prompt for visual actions should say "refer to the figure
   on screen" (the manifest already feeds the prompt; just add the cue for display turns).
**Files.** `tutor_loop.py`, `query.py` (already carries image_path — verify it survives into
`manifest`), new `voice/display.py` (DisplaySink + Windows pane), `voice_hybrid_runner.py`,
`wini_brain_pkg`/new `wini_display_pkg` (Jetson), `device_config.py`.
**Acceptance.** A graphical-gap learner asking about a parabola gets the Fig-2.x crop shown while
Wini speaks (smoke-test the case already covered by `smoke_test_phase5.py`); audio-only turns
show nothing; image clears on turn end; no hard-coded paths.

## T10 — Load-modulated spoken budget (turn-length governor) — *flagship #2* *(P1)*

**What.** Make the spoken word/sentence budget shrink under high cognitive load / confusion and
relax when the learner is engaged and confident — instead of the current fixed per-action table.

**Why.**
- `agent_feedback.txt` (§4 "turn-length governor", §6): pace should be "one claim, one worked
  micro-example, one question," adapted to `cognitive_load`, `confusion`, `engagement` — exactly
  the signals the analyzer already produces. Speech-only kids lose the thread on long turns.
- Today the budget is keyed by **action only** (`pacing/pacing_controller.py`
  `ACTION_BUDGETS` + `budget_for_action`, lines 14–23, 76–89). The learner-state signals are
  *available* at the budget call site but unused: `budget_after_action(action, decision, loop)`
  has `decision.analysis` (the cognitive update) and `loop.state` (global `cognitive_load`,
  `engagement`, `confidence` — see `learner_state.py:17`).

**How.**
1. **Compute a load multiplier.** Add `def load_multiplier(analysis, state) -> float` in
   `pacing_controller.py`:
   - read `cu = analysis["cognitive_update"]` → `confusion`, `cognitive_load`,
     `frustration_risk`; read global `engagement`/`confidence` from `loop.state["global"]`.
   - `m = 1.0; if cognitive_load > 0.6 or confusion > 0.6 or frustration_risk > 0.6: m = 0.7`
     (one tighter idea); `elif engagement > 0.7 and confidence > 0.6 and load < 0.4: m = 1.15`
     (room to breathe). Clamp `m ∈ [0.6, 1.2]`.
2. **Apply it** in `budget_for_action` (thread `multiplier` and `analysis` through, or apply in
   `budget_after_action`): `max_words = round(base_max_words * m)`, then **floor** to keep whole
   ideas (never below 1 sentence; never drop the micro-check). Under high load force
   `max_sentences = min(max_sentences, 2)` and `micro_check_type` stays set (one claim → one
   check).
3. **Persist for audit.** Write the chosen `multiplier` + reason into the pace ledger
   (`ledger.data["budget_multiplier"]`) so `after_turn` logs it — feeds later policy tuning.
4. **Guardrails.** Never modulate `MISCONCEPTION_PROBE` / diagnostic budgets below their floor
   (the question must be fully heard — same exception the filler logic already makes). Keep the
   `WORKED_EXAMPLE = 60 w / 4 sentences / try_step` deliver-don't-announce contract intact
   (architecture §21).
**Files.** `pacing/pacing_controller.py`, `pacing/ledger.py`, `learner_state.py` (read-only
accessors), architecture §21 (document the governor).
**Acceptance.** A high-load turn (`cognitive_load` 0.8) yields a visibly shorter EXPLAIN
(≈ 24 w) ending in a yes/no check; an engaged-low-load turn allows the full budget; diagnostics
unchanged; ledger records the multiplier; spoken-budget truncation still keeps whole sentences.

## T11 — Robot engagement-motion cues *(P2, Jetson/hardware)*

**What.** Lightweight social motion (ear-wiggle / head-nod) signalling "listening" vs "speaking"
vs "thinking", separate from content visuals.

**Why.** `agent_feedback.txt` §5: "motion is better for attention" as a social cue; best design
is minimal motion + a task-relevant visual (T9). It also reinforces the half-duplex turn signal.
**How.** Drive from existing state edges on the Jetson: `/robot_speaking` True → "speaking"
motion; idle/listening → subtle "listening" idle; filler window → "thinking" nod. Keep amplitude
small; never during a diagnostic question's audio.
**Acceptance.** Motion maps to the three states; no motion during diagnostic playback; runs on
the Jetson without contending with the audio hot path.

## T12 — Policy-shadow promotion harness *(P2, after T1)*

**What.** Build the offline-evaluation harness that decides when the shadow policy (top-1 0.680
after the 2026-06-19 fixed-source rebuild) may replace the rule engine.

**Why.** Build plan Part 5 + `agent_feedback.txt` §4: shadow stays non-authoritative "until it
demonstrably beats the rules on real logged turns." The mechanism to *prove* that doesn't exist
yet.
**How.** Over T1 logs, compute action agreement vs rules, teacher-reviewed action quality
(report §9.3 rubric 0–3), and offline estimated reward (report §6.5); promotion gate = report
§10 ("top-3 agreement > 0.85, no increase in overload/answer leakage"). Keep the rule layer as a
hard-constraint safety net (report §6.2).
**Acceptance.** A repeatable report comparing shadow vs rules on held-out logged turns with the
promotion gate evaluated.

---

# 4. PENDING NEURAL MODELS (report §4 / §7 — most gated on T1)

## T13 — Neural knowledge tracing (DKVMN) *(P2, after T1)*
**Why.** Report §7.1; build plan Part 6: "Neural KT waits for real learning-log data. No
synthetic KT." Mastery is rule-based today. **How.** Train DKVMN-style KT on T1 interaction
sequences (bridge + probe outcomes already arrive pre-labeled with concept/outcome). **Acceptance.**
Beats the rule-based mastery on held-out next-answer prediction.

## T14 — Neural retrieval reranker / weight tuning *(P2, after T1)*
**Why.** Report §4.2: the 7-term weights (`w1..w7`) are hand-set and logged as `ranking_trace`
precisely so they "can later be tuned from the append-only learning log." Dataset
`retrieval_relevance.jsonl` (9,176 graded pairs) already exists. **How.** Use accepted/rejected
evidence from logs as graded labels; the `ranking_trace` terms become cross-features; either tune
the linear weights or train a small MiniLM reranker. **Acceptance.** recall@5 ≥ 0.90 on direct
concept queries (report §10); no regression on the 12 Phase-5 smoke tests.

## T15 — ZPD / difficulty calibrator *(P2, after T1)*
**Why.** Report §7.2: not built; only the heuristic `mastery_to_band` exists. **How.** Tabular
MLP/GBM over mastery, latency, recent correctness, hint count, item difficulty, load → next
difficulty band + overload risk. **Acceptance.** Predicts good-ZPD vs too-hard/too-easy above
baseline on logged attempts.

## T16 — Grounding & leakage guard classifier *(P1 — dataset ready)*
**Why.** Report §7.3: runtime uses structural + LLM cohesion checks only; the trained guard
isn't built, yet `grounding_guard.jsonl` (3,584 rows: grounded / unsupported / answer_leak /
safe) is ready. **How.** Train a MiniLM pair classifier (response+evidence → label); run it as a
cheap always-on guard beside the cost-gated LLM cohesion judge. **Acceptance.** answer-leak
recall high; 0 answer-leaks on a hint audit; runs < 50 ms.

## T17 — Misconception state tracker (neural) *(P2, after T1)*
**Why.** Report §7.4: rule transitions exist (§10 machine); neural tracker "learns soft versions
from logged sequences." `misconception_clue_bank.jsonl` (1,504, all 276 families) seeds it.
**How.** Sequence model over clue score + probe outcomes + correctness → status + confidence.
**Acceptance.** Matches/improves rule transitions on logged misconception sequences.

## T18 — Response-time & engagement predictor *(P2, after T1)*
**Why.** Report §7.5: not built; needs timestamped turns. **How.** Calibrated regression over
latency + interaction features → effort / overload / disengagement. **Acceptance.** Separates
productive-struggle from overload on labeled latency patterns.

## T19 — Standalone representation & misconception-clue taggers *(P2)*
**Why.** Report §4.3/§4.4: currently folded into the Part-1 classifier labels
(`graphical/diagrammatic/…`, `misconception_clue`). The report specs them as separate
per-concept exemplar models with hard negatives. **How.** Train from
`representation_tagger.jsonl` / `misconception_clue_bank.jsonl` once scaled (T5). Optional — only
if the folded labels underperform. **Acceptance.** ≥ folded-label F1; decide whether to ship
separately or keep folded.

---

# 5. STORE QUALITY & HUMAN-REVIEW BACKLOG

## T20 — Re-crop body-text-contaminated figures *(P1, human + wired loop)*
**Why.** `rag_memory.md` Phase 2 + open-item 1: some caption/cluster crops contain running body
text (e.g. Fig 7.7, Fig 10.10); the re-judge/re-crop loop is wired but un-run. **How.** Human
pass over `rag_store/figure_crops/contact_sheet.html`; for bad crops, wipe their `sem::` rows for
caption/cluster nodes in `fig_crop_cache.jsonl` and run `python crop_figures.py` (re-routes via
Gemini bbox fallback). **Acceptance.** contact-sheet review < 5 % bad crops; figure/table
coverage stays ≥ 99 %.

## T21 — Fix the 15 answer-leaking diagnostic hint chains *(P1, quick)*
**Why.** `rag_memory.md` Phase 1 step 6: 15 diagnostics "kept leaking the expected answer after
retry → logged, left without chains." Those diagnostics currently can't serve a faded hint
(architecture Rule 10). **How.** Re-generate just those 15 chains via local Qwen with a stricter
no-leak prompt; validate with the existing regex + expected-answer-containment check; if still
leaking, author by hand. **Acceptance.** 100 % of diagnostics have a 3-step, no-leak chain;
scorecard hint-chain metric unaffected/improved.

## T22 — Close the problem-schema coverage gap *(P2, quick)*
**Why.** `rag_memory.md` Phase 1 step 5: schema coverage 94.4 % — ~6 concepts have no
`problem_schema`, so they can't serve an analogous worked example (architecture §6.9). **How.**
Identify the uncovered concepts; cluster their chunk-instances (the eval report notes 102/108
have chunk instances available); generate schemas via the existing stage. **Acceptance.**
≥ 98 % concepts with ≥ 1 schema; no regression elsewhere.

## T23 — Human read of bridge recaps & HOPE sample *(P1, review only)*
**Why.** `rag_memory.md` open-item 2: human read of `bridge_recaps_review.md` (62 recaps) and the
30-prompt `hope_bank_review_sample.md` is outstanding (only 3-sample spot-checked). **How.**
Teacher review; flag any ungrounded recap; regenerate flagged ones from intro chunks only.
**Acceptance.** All 62 recaps confirmed grounded; flagged prompts handled in T6.

---

# 6. VOICE RUNTIME (excl. AEC / full-duplex / barge-in)

## T24 — Qwen TTFS latency tuning *(P1)*
**Why.** Voice report §12.9/§12.10 + build plan Parts 9/10: measured TTFS ≈ 3.4 s on Jetson (the
sub-1 s spec is not met); the filler + prompt-trim work is "still pending." **How.** Wire the
filler bank on the B1→B5 gap (already exists in `voice/fillers.py` for Windows — port to Jetson),
trim the evidence prompt to ≤ 3000 chars, cap reply length (ties into T10). **Acceptance.**
Perceived first-audio < ~1 s via filler; raw TTFS reduced by prompt trim.

## T25 — Stream Qwen generation in the Windows rig *(P1)*
**Why.** Build plan Part 10 open item: generation is currently whole-then-speak after the filler,
leaving a gap; Jetson already streams via `llm_local.stream_sentences`. **How.** Switch
`voice_hybrid_runner.py`/`live_session.py` to consume `on_sentence` token-streaming + pysbd and
feed Cloud TTS sentence-by-sentence. **Acceptance.** First real sentence speaks immediately after
the filler; no whole-answer wait.

## T26 — Cloud STT streaming *(P2)*
**Why.** Build plan Part 10 open item: STT is batch-per-utterance. **How.** Move
`voice/cloud_stt.py` to the streaming Speech API; emit partials for endpointing. **Acceptance.**
Lower STT latency; partials available to endpoint logic.

## T27 — Tune child-speech endpointing & reconcile VAD divergence *(P1)*
**Why.** Build plan Part 10 + voice report §12.10 open item 1: RMS endpoint threshold/`silence_ms`
need tuning for children, **and** the spec's Silero v5 + `AdaptiveEndpointDetector` (A2) is not
the as-built path (`fastwhisper_node` uses RMS energy). **How.** Either wire Silero as specced or
formally adopt RMS in `WINI_VOICE_STUDY_ARCHITECTURE.md` §A2/§9; tune `--rms-threshold` /
`silence_ms` on real child recordings. **Acceptance.** Stable endpointing on child speech; spec
and as-built agree (one chosen, documented).

## T28 — Session-context reset on wake *(P1, quick)*
**Why.** Voice report §12.10 open item 4 + build plan Part 9: `learner_state.json` persists across
runs by design, so a prior session's **transient** context can leak into a fresh launch. **How.**
On `/wake_word`, clear `session` transient context (last-N turns, pace ledger, pending checks)
**without** touching the per-concept learner model. **Acceptance.** Fresh launch starts with empty
conversation memory but retained mastery/misconception state.

## T29 — Wakeword ambient false-fire tuning *(P2, harmless now)*
**Why.** Voice report §12.10 open item 3: occasional ambient false-fire, currently harmless (the
Whisper hallucination filter drops it). **How.** Tune `THRESHOLD`/`TRIGGER_FRAMES` if a live word
is ever missed. **Acceptance.** No missed real wakes; false-fire rate acceptable.

## T30 — Live human-voice end-to-end test *(P1)*
**Why.** Voice report §12.10 open item 6: the one unverified path — injected `/speech_text`
bypasses Whisper, so mic→STT accuracy on a real child voice is untested. **How.** Run the full
Jetson pipeline and the Windows rig with a person speaking; log STT WER on a maths phrase set.
**Acceptance.** End-to-end turn works from a live voice; STT errors characterized.

---

# 7. PILOT OUTCOME METRICS

## T31 — Instrument the §4b pilot metrics *(P2, measure with learners via T1)*
**Why.** `RAG_upgrade_plan.md` §4b + `rag_memory.md` open-item 4 + report §10: three
learning-outcome metrics are *defined* but unmeasured — bridge usefulness (40–80 % failed-
diagnostic band), misconception resolution within 3 sessions, retention lift at 3/7/21 days.
**How.** Add counters over the learning log: % activated bridges with a failed diagnostic;
`active→resolved` transition latency in sessions; delayed-recall correctness vs non-bridged
concepts (uses T1's delayed-outcome field). **Acceptance.** A pilot dashboard reporting all three
once real-learner data exists.

---

# 8. DOCUMENTATION DERIVATIONS (architecture §20 "still to derive")

These four are named in `learner_cognitive_state_architecture.md` §20 as not-yet-written specs.
Low urgency (the behavior is implemented; these formalize it), but listed for completeness.

| Task | Doc | What it formalizes |
|---|---|---|
| T32 | `learner_state_schema.md` | §6.4 fields + the `apply_probe_result` / `apply_bridge_result` write-back APIs |
| T33 | `pedagogy_policy_rules.md` | §13 Rules 1–12 as executable policy |
| T34 | `cognitive_signal_definitions.md` | the §6.2 / §11 signal definitions and formulas |
| T35 | `session_persistence_spec.md` | §12 data stores (learner state, learning log, transient cache, pace ledger) |

**Lockstep reminder (CLAUDE.md):** any task here that changes behavior or schema must propagate
across the 4 lockstep docs + a `rag_memory.md` log entry in the same session.

---

# 9. Deferred (NOT in this pass)

Listed once so nothing reads as "missed": **AEC** (`aec_pkg`), **full-duplex** operation,
**semantic barge-in** (C3), **disfluency repair**, **wakeword pre-roll**, and **sub-100 ms TTS**
(physically impossible for full-sentence neural TTS on the Jetson — masked by sentence
streaming). These are tracked in `WINI_VOICE_STUDY_ARCHITECTURE.md` §11/§12.10 and were excluded
by instruction.
