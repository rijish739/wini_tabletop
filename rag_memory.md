# RAG Upgrade — Complete Work Log

Implementation record of [RAG_upgrade_plan.md](RAG_upgrade_plan.md) (all 7 phases, 0–6),
executed 2026-06-10 → 2026-06-11. Final state: **18/18 scorecard metrics PASS, 100.0%
target attainment** ([rag_store/scorecard_phase6.txt](rag_store/scorecard_phase6.txt)).

Store: NCERT Class 10 Maths · 17 docs · 108 concepts · schema v2 ·
1,017 chunks == FAISS vectors · 3,562 graph nodes / 2,617 edges.

Environment for every LLM run:
`GOOGLE_GENAI_USE_VERTEXAI=True  GOOGLE_CLOUD_PROJECT=custom-model-training-493207  GOOGLE_CLOUD_LOCATION=global`
(ADC via gcloud; models: gemini-2.5-flash generation/vision, gemini-embedding-001 3072-dim, gemini-2.5-pro as second HOPE rater.)

---

## Phase 0 — HOPE-readiness scorecard (`verify_store.py`, rewritten)

- Replaced the old structural checker with an 18-metric scorecard mapped 1:1 to the plan's
  §4a build-completion table, while keeping the structural checks (chunks == meta == FAISS).
- Metrics: concept difficulty / transfer links (≥2 near + ≥1 far, near targets validated
  against the 108 IDs) / integration links / CT probes / applications / vocabulary /
  metacognitive prompts (both `after_success` and `after_struggle` required) / problem
  schemas / misconception enrichment / 3-hint chains (with answer-leak regex
  `\b(the\s+)?(final\s+)?answer\s*(is|=|:)`) / figure+table and formula `image_path` /
  grade-9 bridge chapter coverage / bridge diagnostics / dangling prereq count /
  chunk concept-link + difficulty guards / HOPE bank rows.
- `--fail-under <pct>` gates on overall **target attainment** = mean of min(value/target, 1);
  `--save <file>` persists reports.
- **Baseline (matches plan §1 gap table): 11.1%** → saved to `rag_store/scorecard_baseline.txt`.
  Phase snapshots: phase1 66.7% → phase2 77.8% → phase3 94.4% → phase4 94.4% (rebuild,
  no regression) → phase6 100.0%.

## User addition — hard "struggle" definition (`learner_state.py`)

The plan had `when: "after_struggle"` metacognitive prompts with no definition of struggle.
Implemented as hard data, not LLM judgment:

- `STRUGGLE_HINT_THRESHOLD = 3` (exhausted the 3-hint chain on ONE problem) OR
  `STRUGGLE_FAIL_THRESHOLD = 2` (consecutive failures on the same diagnostic).
- `record_hint_request(concept_id, problem_id)` — per-problem hint counter that auto-resets
  on a new problem; feeds the `hint_dependency` EMA (`0.7*old + 0.3*used/3`) consumed by
  ranking term w6.
- `apply_probe_result(misconception_id, outcome, concept_id, hints_used)` — the A2.4/A2.6
  write-back: misconception status machine per architecture §10
  (`active → weakening` on 1 correct → `resolved` after 2 consecutive correct →
  `recurring` on any later failure), mastery deltas `{correct +0.15, partial +0.05,
  wrong −0.10}`, computes `struggled` and returns `metacognitive_when`
  (`after_struggle`/`after_success`) so the engine retrieves the right prompt.
- `is_struggling()` / `metacognitive_when()` helpers. All transitions + thresholds unit-tested.

## Phase 1 — Concept enrichment (`enrich_concepts.py`, new; ~270 LLM calls)

Stages (single resumable cache `rag_store/concept_enrich_cache.jsonl`, issues log
`concept_enrich_issues.log`):

1. **repair** (deterministic, no LLM): discovered that ALL vision-era graph edges used
   un-prefixed concept IDs (`quadratic_coefficients`) while the store's 108 concepts are
   doc-prefixed (`jemh102__quadratic_coefficients`) — so 0/108 concepts could reach their
   example/exercise nodes. Re-pointed **184 edges** via same-doc prefix match
   (`<doc-of-target>__<source>` ∈ 108); `prerequisite_of` edges deliberately left for
   Phase 3 (G7). Edges carry `repaired_from` for audit.
2. **concepts** (108 calls, one JSON-mode call each, grounded in: the card, its own chunks
   sorted by concept score, linked formulas/misconceptions/applications, median-difficulty
   anchor, full 108-ID list): generated `difficulty` (1–9, anchored), `transfer_links`
   (≥2 near from the 108 + ≥1 far with note; the curated Polynomials links from
   `chapter_seed_polynomials.json` preserved verbatim in front, generated ones deduped
   behind), `integration_links` (KI, representation pair normalized to `a<->b`),
   `ct_probes` (2–3 incl. ≥1 counterexample, each with `expected_insight` rubric line),
   `applications` (227 application nodes promoted/deduped), `vocabulary`,
   `metacognitive_prompts` (exactly one per `when`).
3. **Hard validation** (plan step 3): invalid near/integration targets rejected; one retry
   with errors fed back; then valid subset kept + shortfall logged. 17 issues total logged.
4. **misconceptions** (batched ~30/call, 2 rounds): all **276/276** nodes got `why_wrong`,
   `correct_idea`, `diagnostic_question`, `expected_answer` (+`enrichment_source`).
5. **schemas** (A1.1/A1.3, ~101 calls): clustered each concept's same-doc example/exercise
   nodes + worked_example/practice/challenge chunks into **245 `problem_schema` nodes**
   (`schema::<concept>::<slug>`: name, `method_steps` 3–8, `instance_ids` validated ⊆
   provided, `chunk_instance_ids`, `isomorphic_variables`, `trap_steps` with optional
   misconception link). Edges `has_schema` / `instantiated_by`. Coverage 94.4% of concepts.
6. **hints** (A1.2, batched 25/call, 2 rounds): 3-step faded chains
   (conceptual_nudge → method_recall → partial_first_step) on **100% of 647 exercises and
   261/276 diagnostics** (908 total; 15 diagnostics kept leaking the expected answer after
   retry → logged, left without chains). Leak validation = regex + expected-answer
   containment on normalized text.
7. **write**: additive card/graph updates; backups `concepts.json.phase1.bak`,
   `graph.json.phase1.bak`; meta `phase1_enrichment` block.

Incident: first run crashed at schema 100/108 on `int(None)` from a JSON `"step": null`
trap; fixed with try/except default, resumed from cache with zero loss.

## Phase 2 — Visual assets (`crop_figures.py`, new; cache `fig_crop_cache.jsonl`)

- **Local extraction (no API)**: per page — `cluster_drawings()` vector clusters (padded
  8pt, merged, <1% page area dropped) + raster image rects, with the **full-page NCERT
  watermark raster excluded** (>65% page area filter); caption anchors found at WORD level
  (`Fig./Table X.Y (+(i))`) so side-by-side captions on one printed line stay separate;
  captions claim the nearest box above/around; composite boxes claimed by multiple captions
  are split (x-midpoints for side-by-side, horizontal bands for stacked); crops rendered
  straight from the PDF at 2× via clip. Single-leftover-node + single-free-box pairing as
  a secondary matcher. 169/245 figure+table nodes matched locally.
- **Formula crops**: exact `search_for` failed on NCERT's private-use math glyphs
  (only 206/911). Replaced with **rapidfuzz sliding-window matching** over normalized word
  streams (window sizes n−2…n+3, accept ≥80, ≤60pt height) → **644/911 = 70.7%**
  (target ≥60%); misses skipped by design (inline formulas).
- **Gemini bbox fallback**: one call per page with unmatched nodes (0–1000 normalized
  boxes; cache key includes an md5 of the requested node set so the quality loop can
  re-query the same page with different nodes). Two bugs fixed: bare-list JSON payloads
  (`data.get` on list) and `fitz.Pixmap(pix, rect)` not being a valid constructor in
  PyMuPDF 1.26 (now re-renders from the PDF with a clip rect). Recovered **101 crops**.
- **Crop semantics (A2.5)**, batched 5 crops/vision call on the crop itself: `alt_text`,
  `supports_representation` (validated against the 8 store types),
  `disambiguates_misconceptions` (validated against the linked concepts' misconception IDs),
  `good_for_questions` (≤2 stems), plus derived `addresses_gap`
  (`representation_missing`/`misconception_active` conditions). All **244 cropped
  figures/tables enriched**; 244 `figure_caption` mini-chunks embedded into chunks.jsonl +
  FAISS, inheriting `concept_ids`/median `difficulty` from their page's text chunks when no
  `illustrated_by` edge exists (keeps the 100% chunk guards green — an earlier version
  regressed them to 85%/83% and was retro-patched).
- **Quality loop**: the semantics call also judges `crop_quality`; bad local crops are
  evicted (PNG deleted, manifest entry removed, `badlocal::` marker persisted so the crops
  stage can never resurrect them) and re-cropped via the Gemini fallback. The first-pass
  judge was too lenient (passed crops that were half body text — e.g. Fig 2.2, Fig 7.7,
  Fig 10.10); criterion tightened to "ANY running body-text lines → bad". Fig 2.2 was
  force-re-cropped (now a clean parabola). **Per user decision: the remaining first-pass
  crops were left as-is for manual review via the contact sheet**
  ([rag_store/figure_crops/contact_sheet.html](rag_store/figure_crops/contact_sheet.html)).
- Final coverage: **figure/table 99.6%** (244/245), crop sources: 644 text_span /
  120 caption / 101 gemini / 23 cluster. Graph nodes carry
  `image_path`/`bbox`/`crop_source` + semantics. Backups `*.phase2.bak`.

## Phase 3 — Class-9 bridges + G7 (`build_bridges.py`, new; cache `bridge_cache.jsonl`)

- **detect**: 71 recall chunks tagged `pedagogical_role: "bridge_recall"` (original role
  preserved in `original_role`; `intro_section: true` marked on page ≤ 4 chunks);
  `bridge_recall` added to `pedagogy_enrich.py` ROLES enum for future rebuilds.
- **extract** (16 chapter calls, validated + 1 retry-with-feedback): named Class-9
  dependencies per chapter with `grade9_topic`, `bridge_recap` (3–5 sentences grounded ONLY
  in the chapter's intro chunks), `diagnostic_question` + `expected_answer`,
  `target_concept_ids` (validated ⊆ chapter concepts), `evidence_chunk_ids` (validated ⊆
  supplied chunks).
- **graph**: **62 `grade9_concept` nodes** (global, one per named dependency; later
  chapters add edges + their own recap chunk), **110 `bridges_to` edges**,
  `bridge_chunk -[evidence_for]->` provenance edges. **16/16 chapters covered, 100% with
  diagnostics.**
- **G7 dangling resolution — 29 → 0**: 9 exact-suffix matches into the 108, 6 fuzzy
  matches (rapidfuzz ≥85) into grade-9 nodes (audited: `hcf →
  grade9::hcf_and_lcm_using_prime_factorisation`, `right_triangle → grade9::right_triangles`
  etc., all sensible), 14 typed `external_concept`. Re-pointing keeps `repaired_from`.
- **embed**: 64 `bridge_recap` chunks (difficulty 3, role bridge_recall, concept-linked)
  → chunks.jsonl + FAISS (store: 1,017 == FAISS verified).
- **Bridge policy contract (A2.4) in `learner_state.py`**, fully tested:
  `BRIDGE_MASTERY_THRESHOLD=0.6`, `BRIDGE_SKIP_ZPD_CENTER=7.0`,
  `should_serve_bridge(bridge_id, zpd_center)` (mastery < 0.6 AND zpd < 7 AND not served
  this session; cold-start 0.30 means new learners trigger every bridge once = cheap
  cold-start probe), `apply_bridge_result(bridge_id, outcome, revealed_misconception_id)`
  (correct → +0.25 & `proceed`; wrong/partial → −0.10, misconception set active,
  `serve_recap_first`). Session tracking via `bridges_served`.
- Human-review file: [rag_store/bridge_recaps_review.md](rag_store/bridge_recaps_review.md)
  (all 62 recaps; 3-sample verified grounded). Backups `*.phase3.bak`.

## Phase 4 — Pipeline consolidation (`build_index.py` + refactors)

- **Refactors for reuse**: `enrich_concepts.apply_enrichment()` (pure card+graph mutation,
  extracted from write_back), `crop_figures.apply_crops()` + `caption_chunk_rows()`,
  bridges' `run_detect`/`run_graph`/`run_dangling` imported directly.
- **`EmbedCache` in `rag_core.py`**: sha1(text)-keyed disk cache
  (`embed_cache_keys.json` + `embed_cache_vecs.npy` in the store), **seeded from the
  existing FAISS index via `reconstruct_n`** — this is what satisfies the plan's "full
  rebuild" and "no re-embedding of existing content" simultaneously. Rebuild re-embedded
  only the 108 concept texts + 1 changed overlay text.
- **`emit_enrichment_edges()`** (plan step 1): **433 `transfers_to`** (near→valid IDs,
  far→`external::` nodes), **131 integration links** — 37 standalone `integrates_with`
  edges + **94 carried as `also_integrates=True` + `representation_pair` attributes on
  existing transfer edges** (nx.DiGraph allows one edge per pair; first build silently
  dropped them — found because only 37 landed), **324 `ct_probe` nodes** with `probes`
  edges (kind/question/expected_insight/difficulty).
- Build flags `--with-crops` / `--with-bridges` (cache-driven overlay stages); enrichment
  overlay auto-applies when its cache exists; bridge re-tagging runs after pedagogy
  enrichment so rebuilds re-tag correctly; figcap/bridge rows appended AFTER concept
  linking + pedagogy so guards hold.
- `meta.json`: `store_schema_version: 2`, full `node_type_counts` + new
  `edge_type_counts`, per-phase overlay blocks.
- **Full rebuild executed and verified**: 709 base chunks / 108 concepts unchanged,
  1,017 total == FAISS, only additive graph deltas, scorecard identical (94.4%),
  `--fail-under 90` green. Backups `*.prebuild4.bak`.
- Canonical rebuild command:
  `python build_index.py --docs "F:\Projects\Pedagogical_study_pkg\database\Maths" --out rag_store --seed curriculum_seed_full.json --with-crops --with-bridges`

## Phase 5 — Learner-snapshot retrieval (`query.py` rewritten)

- **Snapshot** (consumed per turn): primary concept, mastery, ZPD band (from mastery via
  `mastery_to_band`, `--level` manual override), hint_dependency, representations_missing
  (concept's representations − learner's `representations_known`), active/recurring
  misconceptions of the primary concept, rolling KI/KT/CT (`hope_rolling`, default 0.5),
  served-items set. New `learner_state.py` accessors for all of these.
- **7-term ranking** replacing `0.70/0.20/0.10`:
  `w1 .40 relevance + w2 .15 difficulty_fit + w3 .10 role_match + w4 .12 repr_gap_fit +
  w5 .10 misconception_priority + w6 .08 hint_dependency_penalty (suppresses
  worked_examples when hint_dependency > 0.5) + w7 .05 hope_history_boost (low KI → 
  figure_caption/multi-representation, low KT → application, low CT → challenge/analyze+)`.
  Served items excluded (no-repeat). Weights + top-item components logged per turn as
  `ranking_trace`.
- **Bridge gate wired**: walks **2 levels of `prerequisite_of` ancestors** before checking
  `bridges_to` predecessors — found via failing smoke test: bridges anchor on chapter
  *intro* concepts (e.g. `triangle_similarity_criteria_intro`) while queries resolve to
  downstream concepts (`aa_similarity`). Activated bridges prepend recap + diagnostic
  (+ hint chain) as the FIRST evidence; `--need bridge` bypasses only the
  served-this-session check.
- **Misconception mechanics (A2.6)**: `consecutive_failures == 0` → diagnostic only
  (`why_wrong`/`correct_idea` withheld); after a failed probe (via `apply_probe_result`) →
  corrective evidence + the disambiguating figure crop. Correction can never precede the
  probe by construction.
- **Need modes** `--need transfer|integrate|challenge|bridge|schema|reflect` (+ legacy
  explain/example/practice/review): KT follows `transfers_to` near-first (far only at
  mastery ≥ 0.7); KI follows `integrates_with` OR `also_integrates` edges + attaches the
  figure whose `supports_representation` hits the learner's gap; CT serves `ct_probe`
  nodes within ±2 of ZPD center; reflect serves the metacognitive prompt chosen by
  `metacognitive_when()`. `--stuck-on <node>`: hint_dependency > 0.5 → **hint step k+1**
  from the exercise's chain (k = `hints_used_current`), else problem schema + analogous
  worked example from `instance_ids`.
- **Evidence provenance manifest (A2.2)**: every turn returns
  `{evidence: [{id, type, why, image_path?, ...}], bridge_ids, schema_ids, ranking_trace,
  cohesion_log, snapshot, band_reason}`, appended to `rag_store/learning_log.jsonl`;
  the answer prompt is composed ONLY from manifest items. `--mark-served` writes served
  ids + bridges back to the learner-state file.
- **Cohesion check (A1.5, cost-gated)**: always-on structural rules — every item within
  2 graph hops of the resolved concepts (derived ids `hint::`/`meta::` resolve to their
  base node — was a drop-bug, fixed), chunk difficulty spread ≤ 3 (bridges exempt, farthest
  from ZPD center dropped first), `correct_idea` never without its misconception in-bundle;
  the LLM contradiction self-check runs ONLY when ≥3 evidence types mix (`--no-judge` to
  disable), and its failure can never break retrieval.
- **Smoke tests (`smoke_test_phase5.py`) — 12/12 PASS**, covering exactly the plan's
  verify list: bridge-first for a low-mastery similar-triangles learner + mastery moved
  0.30 → 0.55 by `apply_bridge_result`; hint-dependent (0.7) learner got **hint level 2**,
  no worked example; graphical-gap learner got the Fig 2.2 crop; probe→correct ordering
  verified in both directions; all manifests non-empty with every id resolving to a store
  object.

## Phase 6 — HOPE dataset bootstrap (`build_hope_bank.py`, new; cache `hope_cache.jsonl`)

- **Bank**: one call per concept → exactly 3 KI (representation-translation from
  `integration_links`, figure-referencing validated) + 3 KT (from `transfer_links`, note
  as anchor) + 3 CT (from `ct_probes`) prompts, each
  `{prompt_id, signal, prompt, difficulty, bloom_level, rubric_anchor, figure_id?,
  concept_id}` — plus 62 deterministic bridge prompts from grade-9 diagnostics.
  **1,034 rows: 324 KI / 324 KT / 324 CT / 62 bridge** (gates: ≥1,000 total, ≥300/signal).
- **Written rubric** ([rag_store/hope_rubric.md](rag_store/hope_rubric.md)): 0–3 ordinal
  per signal, hard-coding the three mandatory discriminations — memorized recall caps at
  1 on KI, surface analogy caps at 1 on KT, unjustified curiosity caps at 1 on CT; bridge
  scored on the KT scale.
- **Calibration before scaling (A2.3)**: stratified ~300-prompt gold sample
  (signal × difficulty band, seeded RNG) → 4 synthetic answers per prompt
  (weak / memorized / partial / strong, substance-differentiated) → **two independent
  raters, blind**: rater A = gemini-2.5-flash strict-grader persona, rater B =
  gemini-2.5-pro experienced-teacher persona, answers deterministically shuffled per
  prompt so no rater sees level order.
- **Results — ALL GATES PASSED**: Cohen's κ **KI 0.780 / KT 0.753 / CT 0.764** (gate
  ≥ 0.6); **memorized-vs-strong separated by ≥1 ordinal on 85.7%** of gold prompts (gate
  ≥ 85%); 1,036 labeled answers in
  [rag_store/hope_gold_set.jsonl](rag_store/hope_gold_set.jsonl); 18 answers with
  |A−B| ≥ 2 flagged `needs_expert_review`; prompts failing discrimination flagged
  `status: rewrite_or_drop` in the bank. 30-prompt human spot-check file:
  [rag_store/hope_bank_review_sample.md](rag_store/hope_bank_review_sample.md).
- **CAVEAT (recorded)**: the plan requires 1 human teacher among the raters; rater B is
  the pluggable LLM stand-in. Replace rater B with teacher labels before scaling the bank
  toward the report's 5,000+/signal production target. κ here is LLM–LLM agreement.

### Phase 6 operational incidents (lessons recorded)

1. Run stalled twice for ~3 h each on a single `generate_content` call hanging on a dead
   connection. Fix #1 (`HttpOptions(timeout=120_000)`) did NOT work — seconds-vs-ms
   ambiguity makes it effectively infinite in this SDK/httpx combination.
   Fix #2 (working): every call runs in a `ThreadPoolExecutor` worker with
   `future.result(timeout=240)` — a Python-enforced wall-clock cap that feeds the normal
   retry, then skips the batch. **Apply this pattern to any future bulk-LLM script**
   (the Phase 1–3 scripts still use plain retries).
2. The first stall watchdog never alerted because its pipeline went through `awk` dedup,
   which buffered the alert. Replacement watchdog emits directly from the shell loop.
3. A concurrently running user job (`generate_exemplar_dataset.py --count 10000`) shared
   the Vertex quota; user paused it for the final calibration stretch.

---

## Final inventory

**Scripts** (all resumable, cache-driven, UTF-8-safe on Windows):
`verify_store.py` (scorecard) · `enrich_concepts.py` (Phase 1) · `crop_figures.py`
(Phase 2) · `build_bridges.py` (Phase 3) · `build_index.py` (consolidated build, schema v2)
· `query.py` (Phase 5 retrieval) · `smoke_test_phase5.py` (12 checks) ·
`build_hope_bank.py` (Phase 6) · `learner_state.py` (struggle thresholds, probe/bridge
write-backs, snapshot accessors) · `rag_core.py` (+`EmbedCache`) · `pedagogy_enrich.py`
(+`bridge_recall` role).

**Store artifacts** (`rag_store/`): `chunks.jsonl` (1,017: 709 page + 244 figure_caption +
64 bridge_recap) · `vector.faiss` (1,017) · `concepts.json` (108 enriched cards) ·
`graph.json` (3,562 nodes / 2,617 edges) · `meta.json` (schema v2 + edge counts) ·
`figure_crops/**` + `crops_manifest.json` + `contact_sheet.html` ·
`bridge_recaps_review.md` · `hope_prompt_bank.jsonl` · `hope_gold_set.jsonl` ·
`hope_rubric.md` · `hope_bank_review_sample.md` · `learning_log.jsonl` ·
caches (`vision_cache`, `pedagogy_cache`, `concept_enrich_cache`, `fig_crop_cache`,
`bridge_cache`, `hope_cache`, `embed_cache_*`) · scorecards (baseline/phase1/2/3/4/6) ·
backups (`*.phase1.bak`, `*.phase2.bak`, `*.phase3.bak`, `*.prebuild4.bak`).

## Post-plan addendum — local grounded datasets (2026-06-11, `build_local_datasets.py`)

Built the five report datasets derivable WITHOUT any LLM call, under the strict rule that no
sample is randomly selected/tagged — every label is a deterministic function of a store
field/edge and every row carries `grounding` provenance (+ tier `store` vs `generated`):

- `dataset/concept_resolver.jsonl` — 12,748 rows (2,748 store-grounded: HOPE prompts, ct_probes,
  misconception diagnostics, concept-linked exercises, figure question stems, alias/vocab
  anchors; + 10,000 generated-tier exemplar rows incl. 3,912 INHERIT_CURRENT_CONCEPT). Bridge
  diagnostics excluded per report §4.1 rule 3 (don't unambiguously name the Class-10 concept).
- `dataset/retrieval_relevance.jsonl` — 9,176 graded pairs (0–3): 3 = same concept + role-fit /
  own figcap / own bridge recap; 2 = same concept other role or KI/near-KT neighbor; 1 =
  prerequisite/sibling chunk; 0 = high-BM25 lexical overlap with NO graph path ≤2 hops.
- `dataset/representation_tagger.jsonl` — 953 rows from chunk `representations` + figcap
  `supports_representation`.
- `dataset/misconception_clue_bank.jsonl` — 1,504 rows over all 276 families (positive=text,
  hard_negative=correct_idea/expected_answer, error_explanation=why_wrong, + schema trap steps).
- `dataset/grounding_guard.jsonl` — 3,584 rows (2,724 validated safe hints; answer_leak by
  construction = hint + own expected_answer; grounded = page_summary↔its own page chunks;
  unsupported = summary↔other-doc evidence by deterministic mismatch).

Splits per report §2.3: 70/15/15 hashed on NORMALIZED TEXT (fixes 171 cross-split duplicate
leaks found on first build), holdout chapters jemh105+jemh111 (2,254 rows), holdout
misconception families (144 rows). Verifier: `python build_local_datasets.py --verify` —
**20/20 compliance checks PASS** (§4.1 ID rules incl. INHERIT, §4.2 grading+volume, §4.3
taxonomy, §4.4 families+hard negatives, §7.3 leak rules both directions, §2.3 ratios/holdouts/
no-leakage, full provenance, Maths-only scope). Volume status: resolver+retrieval MEET report
minimums; representation/misconception/guard are SEED-level exemplar banks (store exhausted —
scaling needs generation or real logs). Manifest: `dataset/datasets_manifest.json`.
Exemplar set audit: all 10,000 concept_ids valid vs store; ~19 rows carry off-action-space
`target_policy_action` tags (not consumed by these datasets; normalize before policy use).

## HOPE detector build — Part 4 (2026-06-12, `hope_detector/`)

Human review cleared the Phase-6 blocker: user supplied `hope_bank_review_human.txt`
(30-prompt HOPE quality audit) and approved dropping the non-discriminating prompts.

- `clean_bank.py`: dropped the 37 `status: rewrite_or_drop` bank prompts + their 148 gold
  answers; attached 28 joinable human ratings (`human_hope_rating`, joined by position vs
  the ordered review sample, signal-consistency asserted). Backups `*.prehope.bak`.
  Bank 1034→997, gold 1036→888; per-signal KI 318 / KT 313 / CT 315 (still ≥300).
- `verify_store.py`: HOPE total target 1000→950 + new ≥300/signal gate; scorecard 100%.
- Gold labels confirmed clean & learnable: weak→0, memorized→1, partial→2-3, strong→3;
  raters agreed 84% exact / 98.6% within 1; `final_label == round((rater_a+rater_b)/2)`.
- **Feature lesson**: embedding prompt+answer+rubric TOGETHER fails (a prompt's 4 answer
  levels embed near-identically → QWK 0.04–0.27, discrimination gate fails). Fix in
  `features.py`: embed the ANSWER ALONE + standardized scalars (answer↔rubric cos,
  answer↔prompt cos, log words, reasoning markers, math tokens). Strong answers are ~2×
  longer (78 vs 36 words) and align better — that's the separating signal.
- Detectors (`build_detector.py`, per-signal logreg, bridge→KT, split by prompt 70/15/15,
  C tuned on val): test QWK KI 0.527 / KT 0.448 / CT 0.651; **discrimination gate
  (strong−memorized ≥1.0) PASS on all three** (1.65 / 1.29 / 1.81). Runtime memorized→0.06,
  strong→1.86. Label caveat unchanged (final_label still LLM-derived; human round was a
  prompt audit, not a full answer re-label).
- **Wired live (2026-06-15, tutor_loop v4)**: `learner_state.update_hope(signal, 0-3)`
  EMA-folds (0.4, /3 normalized) a detector score into rolling KI/KT/CT. Loop arms
  `session.pending_hope` on any CT/KT/KI probe; next attempt (not ack/hint, ≥4 words)
  scored → rolling updated → persisted → feeds query.py w7. Verified end-to-end. Also
  added `MISCONCEPTION_FLAG_THRESHOLD=0.4` (misconception_clue is the weakest classifier
  signal; a comma flipped 0.62↔0.48 across the old 0.5 flag). Calibration note: detectors
  discriminate well RELATIVELY on free text (strong 1.4 > mem 0.3 > weak 0.2) but absolute
  scores are conservative — fine for w7 (boosts weakest signal, not absolute thresholds).

**Open items / next steps:**
1. Human pass over `contact_sheet.html` (known: some caption-sourced crops contain body
   text; re-judge/re-crop loop is wired — wipe `sem::` rows for caption/cluster nodes in
   `fig_crop_cache.jsonl` and run `python crop_figures.py` to trigger it).
2. Human read of `bridge_recaps_review.md` (62 recaps) and the 30-prompt HOPE sample.
3. Replace HOPE rater B with human-teacher labels; resolve the 18 expert-review answers;
   rewrite/drop the flagged non-discriminating prompts; then scale the bank.
4. Pilot-phase §4b metrics (bridge usefulness 40–80% band, misconception resolution within
   3 sessions, retention lift at 3/7/21 days) — defined, awaiting real learners.
5. Keep the lockstep rule: changes here must propagate to
   `learner_cognitive_state_architecture.md`, `model_dataset_architecture_report.md`, and
   `complete_architecture_build_plan.md` (CLAUDE.md now lists all four).

- **Windows hybrid voice pipeline (2026-06-18, build plan Part 10).** Added a cloud-edge/local-
  brain voice rig (`voice/`, `pacing/`; `python voice_hybrid_runner.py --live`). **Gemini Live
  API rejected**: native-audio model would not speak local text verbatim (paraphrased and
  invented its own maths) and its STT produced Telugu/Hindi script for English speech. Switched
  to **Cloud STT forced en-US** (+maths phrase-hints) and **Cloud TTS `en-IN-Chirp3-HD-Achernar`**
  (verbatim, sentence-streamed). Latency: cohesion judge OFF for voice + Qwen generation warmup
  at startup → first turn **11.2 s→2.2 s**, then 2–5 s; resolver pre-warmed so per-turn triage
  ~50 ms. Fillers now chosen by MiniLM cognitive state + triage (varied, pre-synthesised), not a
  fixed "let me see". **Spoken-budget bug fixed** (the user's report): a tight pre-action EXPLAIN
  budget made Qwen *announce* a worked example then ask "did you understand" without working it.
  Fix = `_budget_for_generation` resizes to the real action (WORKED_EXAMPLE 60 w/4 s/`try_step`),
  `_truncate_to_spoken_budget` keeps whole sentences only, prompt forbids announce-without-deliver
  and requires computing examples to the result, gen temp 0.3. Gotchas: google-genai rejects
  `enterprise=False` next to `vertexai=True`; `texttospeech`+`speech` APIs had to be enabled;
  sanitizer must convert `*`→"times" BEFORE markdown-stripping. Store untouched (RAG_upgrade_plan
  unaffected); no new models/datasets (report unaffected).

## Dataset re-point + T2/T3 classifier pass (2026-06-19, `dataset/` + `cognitive_classifier/` + `policy_shadow/`)

Store untouched (RAG_upgrade_plan unaffected). Two things, rebuilt together; full build status in
complete_architecture_build_plan.md §2.5.2 / §6.

- **Canonical dataset moved to `exemplar_dataset_10000_fixed.json`** (was the curate source = raw
  `exemplar_dataset_10000.json`). `_fixed.json` = 10,000 audit-corrected base rows (external Gemini
  audit + an 11-rule text-evidence second pass, `dataset/apply_audit_fixes.py`) + 800 T2/T3
  supplementary rows carrying `split:"train"`. `curate_dataset.py` now reads `_fixed.json` and
  writes `_curated.json` (gold-rule projection = build input); raw + 100-sample + old backups moved
  to `dataset/archive/`. `augmented_rare_labels.json` reverted to its original 1,331 (the 800 now
  flow through fixed — no duplication).
- **T2/T3**: `acknowledgment` registered as the 38th canonical label (`is_pure_ack` gold rule in
  curate ⇒ +acknowledgment, −confusion/−low_confidence); ~300 pure-ack + 100×5 weak-label rows
  authored. build_bank splits only the 10k base; supp + augmented are train-only. build_policy now
  ALSO trains on the 800 (it reads curated).
- **Splits REGENERATED** (old frozen one → `models/exemplar_classifier/_old_splits/`); 893/999 test
  rows changed; val/test confined to base rows.
- **Results**: classifier test micro/macro 0.77/0.62 → **0.83/0.69** (scorer flipped to
  evidence+logreg); policy top-1/top-2 0.56/0.74 → **0.68/0.84** (EXPLAIN F1 0.50→0.73). Pure-ack
  smoke: "ok got it"→ack 0.95, confusion ≤0.25.
- **Gotchas**: (1) the four external audit files use DIFFERENT row-numbering (cats_123/last_100 =
  array index; cats_456/789 = JSON line number = 8·idx+2) — match by utterance text, not row#.
  (2) keyword matching this dataset needs word boundaries: `coin`⊂coincident, `block`⊂blocked,
  `rope`/`tie`⊂properties, `sum`⊂summary; "sum" here means "a math problem". (3) rare-label test
  F1 (ack, hint_dependency) stays noisy — the authored rows are train-only, so natural test support
  is tiny; only real logged data fixes it. CLAUDE.md mandates + WINI_ARCHITECTURE/README/report/
  build-plan updated to match.

## T9 display channel + closed-loop grading incident (2026-06-20, `tutor_loop.py` + `cues.py` + `ui/`)

Two pieces of work in one session, both touching the runtime loop (build-plan Part 7 v5).

- **T9 multimodal display channel (flagship #1)**: `tutor_loop.turn()` now emits a `display`
  list — ≤1 figure crop/turn. `_build_display` relies on query.py already gating `figure`-type
  evidence to the two show-cases (representation gap / active-misconception disambiguation); an
  incidental `figure_caption` chunk shows only for `REPRESENTATION_TRANSLATION`/`VISUAL_ANALOGY`.
  `image_path` kept store-relative (channel-agnostic; web `/store/` route, future Windows pane /
  Jetson `/display_image` each resolve). Qwen gets a "refer to the figure on screen" cue. Web UI
  feasibility wired (`wini_ui_server.py` `/store/<relpath>`, `ui/app.js` `buildFigure`). Verified:
  graphical-gap parabola → Fig-2.2 crop; audio-only → `[]`; 888 figure nodes carry valid crops.

- **Closed-loop grading incident — 3 bugs found in one dev-test transcript** (a confused learner
  said "this looks scary… how can I learn easily", "what did you mean, I can not understand", "you
  are repeating the same answer"). `learning_log.jsonl` showed each graded **wrong** → mastery
  0.20→0.10, misconceptions forced active, HOPE scored 0:
  1. **Non-attempts were graded.** The loop ran every reply through `judge_answer`; the weak 3B
     judge returns `wrong` for plain confusion. Fix: deterministic `non_attempt` guard (no answer
     cue + ack/clarification/bare-question/fresh-request) → `not_an_answer` before the judge; same
     guard gates the HOPE scorer.
  2. **Confused → SOCRATIC.** Misread curiosity (0.67) routed an overwhelmed plea to a challenge.
     Fix: `rule 1b` clarification override in `rules_decide` (re-explain simply), outranking the
     inferred-misconception probe; + Qwen anti-repeat/simplify cue.
  3. **`ct_probe` graded as a misconception.** A `ct_probe` carries a `question`, so it armed the
     graded `pending_check` AND `pending_hope`; grading wrote a bogus
     `misconception_states["ct_probe::…"] = active` and dropped concept mastery. Fix: only
     `bridge_diagnostic`/`misconception` may arm `pending_check`; CT/KT/KI probes are HOPE-only.
  **Gotchas/lessons**: (1) any evidence type carrying a `question`/`diagnostic_question` field will
  be picked up by arming loops — gate by `type`, not by field presence. (2) New runtime cues
  (`is_clarification_request`, `is_answer_attempt`) are standalone like `is_pure_ack` — NOT in
  `cue_features`/`CUE_NAMES`, so no classifier/policy rebuild. (3) `mastery: None` entries seen in
  the dummy state are legacy artifacts; no current code path writes them and `mastery()` handles
  them. `learner_state.json` (developer dummy data, corrupted by the above) reset to a clean
  baseline. Lockstep: architecture §6.4 grading contract + §6.6 rule 1b, build-plan Part 7 v5.

- **Cloud voice latency spike: STT/Flash/TTS, pre-Part-11 (2026-07-01).** Before starting the
  real `PART11_GEMINI_PERCEPTION_LAYER.md` build, measured a throwaway pipeline
  (`voice_latency_spike.py`, `llm_vertex.py`, `voice/gemini_live_stt.py` — none wired into
  `tutor_loop.py`/`PERCEPTION_BACKEND`) to get real numbers per hop: Cloud STT → Gemini 2.5
  Flash (`asia-south1`) → Cloud TTS, with a Gemini Live STT-only leg run in parallel for
  comparison. **Warm steady-state per turn ≈ 3.8 s** (Cloud STT ~1.0-1.5 s, Flash ~0.9-1.1 s,
  Cloud TTS ~1.1-1.5 s) — but a **cold process pays ~4-9 s per client** (Vertex/Cloud
  channel+ADC setup dominates, not the API call), ~20-30 s total if every client is built
  fresh; fixed by memoizing the Gemini client in `llm_vertex.py` (was rebuilding it every
  call). **Gemini Live STT re-tested (STT-only, no audio-out) got the transcript right this
  time** (no repeat of the 2026-06-18 wrong-script bug) **but measured ~7.7-8.4 s/turn, 5-6x
  slower than Cloud STT** — a Live session still runs a full model turn even when only input
  transcription is read, so **Cloud STT remains the STT choice, now on latency, not just
  correctness**. Also hit a fresh gotcha: Gemini 2.5 Flash's default `thinking` budget can
  consume all of `max_output_tokens` and return empty text (`finish_reason=MAX_TOKENS`) —
  fixed with `thinking_config=ThinkingConfig(thinking_budget=0)`. Both findings logged as
  gotchas in CLAUDE.md. **Also found & fixed**: a prior session's cloud-pivot edit to
  CLAUDE.md's hard mandates had landed in `D:\Data\My Dnlds\CLAUDE.md` (not a repo, unrelated
  downloads folder) instead of this repo's `CLAUDE.md`, leaving the real file still saying
  "LOCAL Qwen only, no Gemini/Vertex clients" — merged the cloud-pivot mandate into the real
  file. Lockstep: none of the 4 architecture docs changed (no schema/contract touched); this
  is prep evidence for Part 11 Stage 0, not an implementation.

- **Part 11 increment 1 — Gemini generation backend (built, headless-verified 2026-07-01).**
  Wired Gemini 2.5 Flash generation into the real tutor brain behind a `GEN_BACKEND=qwen|gemini`
  flag. **One-seam change**: `tutor_loop.qwen_chat` now dispatches to `llm_vertex.generate_reply`
  when `GEN_BACKEND=gemini`, so all three generation call sites (`qwen_answer`,
  `qwen_cohesion_check`, `judge_answer`) switch at once with the **manifest-grounded prompt
  byte-identical** across backends. `llm_vertex.py` promoted to the shared Vertex client
  (memoized per-location, hard `ThreadPoolExecutor` timeout 20 s, `thinking_budget=0`). New
  `voice_cloud_tutor.py`: push-to-talk cloud tutor (Cloud STT → real brain → Gemini gen → Cloud
  TTS, warm clients, per-hop timing) reusing `voice.live_tools.TutorTurnHandler` (no brain-code
  duplication). **Verified**: `tutor_loop.py --once` with `GEN_BACKEND=gemini` and **no Qwen
  server running** produced a correct, manifest-grounded answer (concept resolved 0.979, 6
  evidence); the runner spoke a budgeted, speech-sanitized 2-sentence reply. **Latency (warm):**
  gen ~0.9-1.2 s, full brain turn ~1.3 s, Cloud TTS ~1.9 s → brain+TTS ~3.2 s (+~1.2 s STT for a
  mic turn ≈ ~4.4 s); cold ~5-9 s is one-time client construction paid at startup. **Gotcha
  confirmed at brain scale**: Flash's default `thinking` budget must be disabled or short replies
  return empty (`finish_reason=MAX_TOKENS`). Lockstep: build plan **Part 11** section added +
  the two stale "Qwen-only" standing rules (§3, §8) annotated as superseded; report/architecture
  model numbers unchanged (generation transport only, no neural model touched). **Pending:** user
  mic test on live speech; increment 2 = the perception layer (`PART11_GEMINI_PERCEPTION_LAYER.md`).

- **Part 11 increment 2 — Gemini perception layer (built, promotion gate pending 2026-07-01).**
  Implemented the front door from `PART11_GEMINI_PERCEPTION_LAYER.md`: **Gemini perceives;
  deterministic code decides and writes state.** New `perception/` package — `gates.py`
  (model-free SAFETY+NONSENSE, always on), `route.py` (`RouteResult` + 8 intents + `INHERIT`
  sentinel), `build_perception.py` (generates the enum-constrained schema + cached context block
  from `label_space.json` + `concepts_meta.json`, with a drift-guard asserting the authored signal
  definitions cover EXACTLY the 38 shipped labels), `gemini_perception.py` (`GeminiPerception`:
  ONE memoized Gemini call exposing classify/resolve/route/embed/score_matrix/embedder + the OOV
  validation belt), `config.py`, `test_perception.py`. Added `persona.json` (canned/scripted
  non-learning replies; SAFETY/NONSENSE never model-improvised), `llm_vertex.generate_json` (the
  structured-JSON seam: `response_schema`, `temperature=0`, `thinking_budget=0`, hard timeout), and
  `eval/perception_eval.py` (Stage-2 harness over the frozen TEST split + intent/adversarial-SAFETY
  probes). `tutor_loop.py` gained a **step-0 front door** (gates → Gemini route → `_handle_nonlearning`
  for non-LEARNING with **no state move** and `pending_check` preserved), `_log_safety` (persisted
  `safety_alerts` + supervisor notification), the `PERCEPTION_BACKEND` wiring (inject
  `GeminiPerception` as classifier+resolver — the design's zero-edit seam), the §7.4 `answer_attempt`
  guard, and a flagged Stage-1 shadow hook. `analyzer.py`/`learner_state.py`/`query.py`/classifier/
  resolver/HOPE **unmodified**. **Verified**: Stage 0 live structured call GREEN (~8 s cold, G2);
  **gate coverage SAFETY 1.0 (20/20) / NONSENSE 1.0 (9/9) / 0 false-gates** (offline, final);
  front-door integration test passes (SAFETY/NONSENSE scripted, no state move, LEARNING passes
  through); **8-row live Gemini smoke** = 0 errors, intent macro-F1 1.0, safety recall 1.0.
  **Gotchas (new):** (G9) enums stop *invented* concepts, not *wrong* ones — correctness is a
  threshold/eval problem, so signals fire on `PERCEPTION_SIGNAL_THRESHOLD`, not raw score, and are
  calibrated on TEST; (G10) the deterministic gate must be near-total on its own — first pass hit
  only 0.75 SAFETY recall (missed gerunds "ending my life" and oblique phrasings), broadened to
  1.0, measure gate recall directly; (G11) `GeminiPerception.score_matrix` is turn-scoped (returns
  the last-`embed()`-ed text's Gemini vector for the policy shadow); (G12) one call/turn is memoized
  by *normalized* text, so keep `normalize_input` idempotent. **Pending (blocks Stage 4 promotion):**
  the full 999-row TEST eval (concept top-1/top-3 vs **0.895/0.971**, signal micro/macro-F1 vs
  **0.77/0.62**) + threshold calibration — do NOT flip `PERCEPTION_BACKEND=gemini` or remove the
  MiniLM heads until green (CLAUDE.md: re-measure, never edit a number blind). Lockstep: build plan
  §13.2, `PART11_GEMINI_PERCEPTION_LAYER.md` status header, `CLOUD_VOICE_STATUS_AND_GOTCHAS.md` §10,
  architecture §6.2 perception seam, report + RAG-plan exception notes, CLAUDE.md commands+gotchas.

- **Voice-teaching quality fixes from a real mic transcript (2026-07-01).** First live trig
  session (`cloud_education.txt`) was "not good for learning": opening "I want to learn
  trigonometry" got **QUIZ**ed; every frustrated follow-up got an **apology that consumed the whole
  spoken budget** ("Namaste! I'm Wini…", "My apologies! Let's focus…"), same question repeated 3×.
  Diagnosed 4 root causes and fixed (owner chose fuller explanations): (1) **budgets too tight** —
  teaching actions raised (EXPLAIN 35→65 w/4 s, WORKED_EXAMPLE 60→85/5, ANALOGOUS/REPRESENTATION
  60/4, etc.; probes/QUIZ/SOCRATIC/REFLECT stay tight) in `pacing/pacing_controller.py` + ledger
  default. (2) **no intro path** — new **rule 1c** in `rules_decide`: not-yet-mastered concept +
  learn intent (curiosity/question, no distress) → EXPLAIN-introduce, never QUIZ. (3) **frustration
  mishandled** — `CLARIFY_RE` extended (standalone cue, no classifier rebuild) to catch "not
  explaining / keep asking questions / different answers" → re-explain (rule 1b). (4) **filler +
  repetition** — hard STYLE block in `qwen_answer`: no greeting/self-intro/apology/announcing,
  never re-ask a question already in history; intro tone for rule-1c EXPLAIN. **Gotcha (cost me a
  debug loop):** `is_known(concept_id)` is True as soon as `apply_deltas` writes a concept-state
  row on the FIRST turn — it means "has a state row", NOT "taught". rule 1c must gate on
  **`mastery(primary) <= COLD_START_MASTERY`** (0.30), which only rises on graded evidence. A
  standalone probe that only calls `analyze_only` (never `apply_deltas`) sees `is_known=False` and
  hides the bug — reproduce routing through the FULL `turn()`/handler path. **Verified**: replaying
  the same 5 inputs (`GEN_BACKEND=gemini`, fresh state) now teaches trigonometry progressively
  (hypotenuse → right angle → application → ratios), zero apologies, zero repeats, warm latency
  intact. Lockstep: build plan §13.1a added; report/architecture untouched (pacing + rule tweak,
  no schema/model change).

- **Part 11 Stage 4 PROMOTED: perception default flipped to Gemini (2026-07-02).** The 2026-07-01
  999-row TEST run came back NO-GO but diagnostic: intent 1.0 / SAFETY 1.0 PASS, concept 0.882/0.933
  near-miss, and signal label-F1 failing STRUCTURALLY (gold averages 5.4 signals/row, Gemini emits
  2.6 by conservative design; `curiosity` gold-labeled on 85% of rows -> heads recall 0.95 by
  training-set memorization vs Gemini 0.06 by definition). Re-scoping to the 16 state-material
  labels did not close it -> conclusion: the label-reproduction gate, not Gemini, was the wrong
  arbiter. **Superseding signals arbiter = behavioral state-trajectory eval**
  (`eval/behavioral_eval.py`): both backends' signals pushed through the UNCHANGED
  `derive_cognitive_update`/`derive_state_deltas` math, graded on the STATE MOVES over 48 authored
  probes (bands + must-fire/must-not-fire flags, gates fixed before measurement) -> **PASS: Gemini
  0.857/0.833 vs heads 0.607/0.500, forbidden-rate equal**; heads systematically miss
  misconception/transfer/prereq/frustration flags. **Concept fixed by S5.5 hardening**: (a) prompt
  rule ALWAYS fill 2-3 `secondary_concepts` (74% of rows had them empty -> top-3 collapsed to
  top-1; now 0.990), (b) top-8 MiniLM `candidate_concepts` hints per turn (resolver
  `anchor_embeddings.npy`, `PERCEPTION_CANDIDATE_K`), (c) deterministic **resolver cross-check**
  `fuse_primary` in `GeminiPerception.resolve` (confident resolver top-1 promoted ONLY if already in
  Gemini's primary+secondaries set; never overrides INHERIT; `PERCEPTION_CONCEPT_CROSSCHECK`):
  top-1 0.890 -> **0.930** (beats resolver-alone 0.895 - the two rankers fix each other's
  same-chapter granularity confusions, 58/66 raw misses). Full re-collect 999/999, 0 errors, into
  `perception_eval_raw2.jsonl` (v2 = prompt of record; v1 kept as provenance; NEVER mix caches
  across prompt versions). All promotion checks green -> `PERCEPTION_BACKEND` default = `gemini`
  (perception/config.py), verified by offline+integration tests and a headless E2E `--once` turn.
  Heads stay on disk as fallback/baseline (Stage 6 removal = owner decision after stability).
  **Gotchas:** (G13) an eval gate that grades a model against labels ANOTHER model was trained on
  is memorization-biased - grade on downstream behavior instead; (G14) Gemini leaves optional
  schema arrays empty unless the prompt says ALWAYS fill them - an instruction, not a capability
  gap; (G15) grading fusion rules offline from a cached collect is free - measure deterministic
  post-processing (cross-check) from the cache before paying for another collect. Still open:
  Stage 5 Vertex context cache (cost/latency), Stage 6 head removal, stability watch. Lockstep
  DONE this session: build plan S13/S13.2, architecture S6.2, report S3.3 note, status doc S7,
  CLAUDE.md mandate, WINI_ARCHITECTURE.

- **Part 11 Stages 5+6 COMPLETE (2026-07-02, owner-directed) - Part 11 is done.** Stage 5:
  `perception/vertex_cache.py` puts the 6,062-token static block (taxonomy + 38 signal defs +
  108-concept catalog + anchors) in a Vertex cached-content resource; per-call now sends only the
  dynamic prompt + response schema. Graceful by construction: `active_name()` checks expiry
  (2-min margin) AND a context sha (a `build_perception` rebuild invalidates the cache - never
  serve a stale block) AND model id; `GeminiPerception._gemini_call` retries a failed cached call
  once with the full system instruction then drops the cache for the process. Measured gate
  (warm, real schema): correctness identical; ~1.0-1.1 s/call cached vs ~1.3-1.5 s uncached;
  66% of prompt tokens (6,062/9,155) at the cached rate; ~$0.0014/turn input. **Gotchas:** (G16)
  the per-call `response_schema` is generation CONFIG and cannot go in the cached content - with
  a 108-enum concept schema it is ~3k tokens of un-cacheable prompt every call; (G17) implicit
  Gemini 2.5 prefix caching showed up in the meter (cached_tokens=9036 on an uncached repeat
  call) - do not mistake it for the explicit cache working, and do not rely on it (not
  guaranteed); (G18) recreate the cache after any prompt rebuild or TTL expiry
  (`python -m perception.vertex_cache --create`); superseded resources are deleted to stop
  storage billing. Stage 6: MiniLM-heads runtime path RETIRED from `tutor_loop.py` - always
  injects `GeminiPerception`; stale `PERCEPTION_BACKEND=qwen_heads` prints a notice and uses
  gemini (never crashes); Stage-1 shadow hook (`PERCEPTION_SHADOW`) removed; learning-path
  fallback on a failed Gemini call = gates + inherit-concept + neutral signals. Head artifacts
  RETAINED (`models/exemplar_classifier/`, `models/concept_resolver/`) - the evals load them as
  baselines and the resolver artifacts serve the runtime S5.5 cross-check; MiniLM itself stays
  in-process for retrieval + HOPE (mandate unchanged). Verified: perception tests offline +
  `--integration` PASS; E2E `tutor_loop.py --once` hint turn on the cached+retired stack
  (request_hint -> rule 3 hint, correct concept + secondaries). Lockstep DONE: build plan S13,
  architecture S6.2, WINI_ARCHITECTURE, CLAUDE.md mandate + commands, CLOUD_VOICE S1/S9/S10,
  both PART11 docs. Standing watch: production firing rates during the stability window.

- **Front-door UX fixes from agent transcript review (2026-07-03).** `gemini_tutor_issues.md`
  (owner's reviewing agent) flagged 5 defects in a live tutoring transcript; all fixed +
  offline-tested (`python -m perception.test_perception` 5/5 PASS, includes 2 new tests).
  (1) **SESSION_CONTROL retention — the big one**: "No, I want to go. Bye." drew "let's just
  quickly finish this one small sum". Root cause was OUR OWN persona/contract text: "secure a
  small win" + the unconditional "if you steer back to maths..." line in `_persona_prompt` —
  the LLM read them as licence to retain. Fix: persona rewritten (accept immediately, praise,
  NEVER ask a maths question); **end-of-session hard rule** in `_apply_session_control`
  (explicit bye OR 2nd leave request in a row -> `status="ended"` via `session.leave_requests`
  counter, reset on LEARNING resume); ended sessions reply with a **scripted farewell, never
  the LLM**; `session_ended=True` propagates through `TutorTurnHandler` and stops the turn
  loop in ALL runners (CLI, `voice_cloud_tutor.py`, `voice/live_session.py`). (2) **SOCIAL
  context-blindness** ("I was right!" -> "what did you get right?"): `_persona_prompt` now
  carries the last 6 `session.context` turns + "never ask about something it already tells
  you". (3+4) **visualization pleas** ("I cannot imagine this") were re-defined, not pictured:
  new standalone `VISUALIZE_RE` cue (no rebuild), **rule 1a-vis** outranks rule 1b ->
  `REPRESENTATION_TRANSLATION` + a generation cue that builds ONE concrete everyday scene (or
  walks the on-screen T9 figure); plain representation signals stay at rule 6 priority so the
  probe/hint rules are not starved. (5) end-of-session policy = the hard rule in (1).
  **Gotcha (G19):** persona instructions are executed by the LLM literally — a pedagogically
  well-meant phrase like "secure a small win" IS a retention instruction after a goodbye;
  session-ending replies must be deterministic/scripted, not generated. Also fixed in passing:
  interactive CLI crashed on non-learning turns (`out['shadow']['action']` with shadow=None).
  Lockstep: build plan §13.1b, architecture "Decision examples" (rule 1a-vis), PART11 §4.3
  SESSION_CONTROL contract + intent table row.

- **Second transcript pass: purpose questions, topic shift, backend observability (2026-07-03
  afternoon).** The owner re-tested `--live` (Gemini generation — no local Qwen server was
  running) and hit 4 more defects; all fixed offline-tested 7/7 (`perception.test_perception`).
  (1) **"how is this related to quadratic equation" was never answered**: Gemini emitted
  `transfer_attempt` -> rule 5 served ANOTHER problem; follow-ups fell to confusion/frustration
  rules. Fix: `PURPOSE_RE` (incl. "you didn't answer my question") -> **rule 1w** ->
  `WHY_IT_MATTERS` action, tone = answer the exact question FIRST. (2) **topic shift broken**:
  "Natural numbers." abstained -> INHERIT -> silently continued the marble expansion; the
  correction resolved to the NEGATED concept (quadratic, 0.7). Fix: `TOPIC_REQUEST_RE` span
  extraction + `is_bare_topic` + `GeminiPerception.topic_candidates` (anchor sims) +
  `_maybe_topic_shift`/`_consume_pending_shift` in turn(): >=.45 direct switch (re-enters as
  "I want to learn about {name}", `_allow_shift=False` guard), .25-.45 confirm (pending_shift,
  bare yes/no next turn), <.25 honest off-catalog offer. Thresholds MEASURED on shipped anchors
  (topics .45-.69, "natural numbers" .31, noise <=.14). Pacing confirm_shift now speaks the
  human name (was raw id!) and arms the same pending_shift (the old offer was never executable).
  (3) **"I want to learn about X" -> QUIZ**: signals empty + warm mastery gated rule 1c; new
  `LEARN_REQUEST_RE` makes explicit learn requests always teach (intro tone still cold-only).
  (4) **mid-number cutoffs**: `_truncate_to_spoken_budget` split sentences at DECIMAL POINTS
  ("20 / 0.2" -> "...20 / 0." + "2 ..."), the real cause of the "0. 2 square metres...divide
  20 / 0." reply; splitter now requires whitespace/end after the terminator; token cap 90-240.
  **Gotcha (G20):** transcripts/logs never recorded which LLM generated a reply and the --live
  labels hard-said "qwen" (seam name) — attribution was impossible. Now: startup banner +
  per-turn `gen_backend` in learning_log/turn results/voice logs + `answer_source` for persona
  replies. **G21:** the sentence splitter regex `[^.!?]*[.!?]` treats decimals as boundaries —
  any word/sentence budgeting over maths text must require whitespace after the terminator.
  Lockstep: build plan §13.1c, architecture "Decision examples" (rule 1w + topic-shift
  contract). SESSION_CONTROL 13.1b fixes verified live in the same transcript (soft pause clean,
  2nd leave -> scripted farewell + hard stop).

## 2026-07-03 — Jetson cloud-brain port (Part 11 pipeline on the robot) + ESP32 display contract

Owner directive: run the SAME cloud pipeline (Gemini perception + generation) from the
Jetson because ROS + the SPI display work there; wire the T9 visual-cue channel to the
robot screen; document the ESP32 thin-client image plan; board IP is now 172.20.10.2
(hotspot — old 192.168.29.x retired, do not use).

Done (all measured on the board):
- **Branch unification:** workspace adopted the Jetson's `query.py` (lazy faiss/dotenv,
  `load_store(with_index=False)`, nx `edges=` fix — pure superset, diff was ONLY the Part 9
  device adaptations). `tutor_loop.py` gained an optional `device_config` import (Jetson-only
  module → MiniLM pinned CPU there, absent on Windows) + `with_index=False`; `GeminiPerception
  .load(device=…)`/`HopeDetector.load(device=…)` take the pin. One tutor_loop source now runs
  on BOTH platforms — the 3-way merge shrank to `llm_local.py` + `device_config.py` + brain node.
- **Sync:** tutor_loop, perception/ (+ build artifacts + vertex_cache.json), llm_vertex.py,
  persona.json, cues.py, pacing/{ledger,controller}, build-time scripts → board (backups in
  `_wini_backups`). `google-genai` 2.10.0 + `python-dotenv` into the venv; ADC creds →
  `~/.config/gcloud/`; `.env` (project) + `export GEN_BACKEND=gemini` in the env prelude
  (GEN_BACKEND is read BEFORE dotenv loads — must be a real env var, not .env-only).
- **Brain node (gemini mode):** no llama.cpp import/prewarm (OOM squeeze gone — full pipeline
  4.4 GB used / 2.8 GB free); Vertex clients warmed at startup (~6 s); whole cloud reply
  sentence-split and published per sentence to /llm_out; T9 figure up BEFORE speech.
- **Verified E2E:** perception tests 5/5 offline; headless --once cloud turn correct; live ROS
  turn ~4 s utterance→first TTS sentence; /wini/display/image 5.0 Hz; "i cannot imagine the
  graph…" → rule 1a-vis → REPRESENTATION_TRANSLATION + Fig 2.2 crop on the panel.
- **ESP32 forward contract** (runbook §14.3): store-relative `image_path` = stable image ID;
  thin client keeps `figure_crops/` on SD card, cloud sends metadata only ({figure_id,
  image_path, alt_text}); unknown ID ⇒ keep the face. Jetson brain node is the reference
  consumer of exactly that metadata.

Gotchas:
- **G22:** the naive sentence splitter split "Fig. 2.2." into "Fig." + "2." TTS clips —
  abbreviation periods (Fig./e.g./Dr.) pass the whitespace-after-terminator rule; the brain
  node splitter re-joins abbreviation/lowercase/digit-initial fragments.
- **G23:** `pkill -f brain_node` issued from an ssh one-liner whose OWN command string contains
  "brain_node" kills the ssh shell itself (exit 255). Put pkill last or use a launcher script.
- Lockstep: build plan §11.1 (new), runbook §0/§1/§5/§12/§14 (new §14). Architecture/report
  untouched — no schema/model change, transport + deployment only.

## 2026-07-03 (evening) — Jetson THIN-CLIENT split: wakeword/fastwhisper/Kokoro retired

Owner directive (same day as the cloud-brain port, superseding its ROS-node shape): nothing
model-shaped on the device — no wakeword, no local ASR/TTS; device = mic + speaker + display
+ future touch; everything in the cloud; the client package must be trivially portable.

Built + verified on the board:
- **`wini_server.py`** — whole pipeline behind HTTP (stdlib http.server, zero new server
  deps): Cloud STT (en-US + maths hints) → TutorLoop (Gemini) → sanitize → Cloud TTS.
  `GET /health`, `POST /turn`, `POST /voice_turn` (raw 16 kHz PCM in → base64 24 kHz PCM +
  display METADATA out). Hard timeouts on every cloud call. Same file = future Cloud Run
  artifact (PORT env). google-cloud-speech/texttospeech installed in the Jetson venv.
- **`wini_client/`** — portable thin client, deps = numpy + sounddevice + requests. RMS VAD
  endpointing (~40 lines) replaces wakeword+Whisper; half-duplex by construction; display via
  pluggable sinks — `RosDisplaySink` publishes 480×320 rgb8 to /wini/display/image (~5 Hz,
  message built once per figure), resolving `image_path` against the local rag_store copy
  (the ESP32 SD-card image-ID contract, verbatim). `--once-text`, `--trigger enter`
  (= the future touch-sensor shape), README.md with the HTTP contract + 4 porting seams.
- **Retired from runtime** (files kept, legacy `run_pipeline.sh`): wakeword_node,
  fastwhisper_node, wini_tts_node, wini_brain_pkg node. New bring-up `run_thin.sh`
  (audio pin + display node + server + client, all detached per §2.1 pattern, python -u).
- **Verified:** Windows first (server + client --once-text + fake-voice /voice_turn), then
  Jetson: canned-utterance /voice_turn → exact transcript, REPRESENTATION_TRANSLATION +
  Fig 2.2 metadata, ~834 KB TTS audio; client one-shot → crop on the panel (3.6–5 Hz
  measured) + speech on the USB speaker; VAD client left listening (PULSE_SOURCE pinned).

Gotchas:
- **G24:** PulseAudio's default sink/source revert to the onboard card even after
  select_usb_audio.sh ran — belt = eval `select_usb_audio.sh --export` into the launcher env
  AND open sounddevice streams with device="pulse" (raw ALSA default = onboard, no mic).
- **G25:** a client blocked in a PortAudio read ignores SIGTERM — pkill -9 the thin procs.
- **G26:** detached `python > log` buffers stdout — launch with `python -u` or logs look dead.
- **G27:** `ros2 topic hz` under a short `timeout` from a cold CLI prints nothing (daemon
  spin-up) — warm with `ros2 topic list` first; cost a whole phantom-bug hunt (the sink was
  publishing fine all along).
- Lockstep: build plan §11.2 (new), runbook §0 rewrite + §5 legacy note + §13 + new §15;
  wini_client/README.md is the client contract doc. Architecture/report untouched (transport +
  deployment only; T9 display contract unchanged in shape).

## 2026-07-15 — Part 12 session modes: Stages 3, 4, 6 (`session_modes.py` + `tutor_loop.py` + `progress_report.py` + `parent_ui/`)

VanLehn outer loop (EXPLAIN/PRACTICE/TEST). Design of record `PART12_PEDAGOGY_MODES_PLAN.md`;
Stages 1–2 landed 2026-07-14. This session: **Stage 3 TEST + Stage 4 T9 cards + Stage 6
reporting**, all on-brain verified on winipi5 (Raspberry Pi 5, `GEN_BACKEND=gemini`).

Built + verified:
- **Stage 3 TEST.** Store audit first: **ZERO gradeable stored answers** (0/245 problem_schema
  instances carry `expected_answer`; 0/108 concepts have ≥5 schemas, median 2). So the planned
  `build_quiz_bank.py` batch is **impossible → designed away**; items are **generated at serve
  time** (`generate_quiz_item`, one structured Gemini call, biased to a single numeric/short
  answer so the deterministic `math_grade` floor scores them). Planning stays pure in
  `session_modes` (`build_quiz_set`/`advance_test`/`score_quiz`, N=5); `tutor_loop._drive_test`
  owns generation + state machine + 0.8 gate + Bloom corrective. Grader eval 26/26, **0
  non-attempts graded wrong**. Live 5/5 → gate pass, `test_history` written.
- **Stage 4 T9 cards + voice-plain generation.** `_mode_display` → `question_card`/`score_card`
  channel items; `ui_cards.py` renders 480×320 (per-item marks are SHAPES, cv2 has no tick
  glyph); `display_sinks.render_item_frame` routes card kinds, unknown kind ignored. Generator
  forced to voice-plain, pre-evaluated answers + `_plainify_math` belt. Live: clean spoken
  questions ("...12x squared y and 18xy squared..."), cards each turn, 1.3–4.5 s/turn.
- **Stage 6 reporting.** `progress_report.py` + `parent_ui/` gained a Quiz-results panel + a
  per-topic gate badge (`test_history`/`mastery_gate`). Verified in-browser (1 passed / 3 taken).

Gotchas:
- **G28 (concept drift restarts a test):** during a TEST the student's short answers ("6xy",
  "48") re-classify to *other* concepts turn-to-turn; honouring the drift rebuilt the quiz set
  every item (never reaching the gate). Fix: `_drive_test` **concept-LOCKS** to `ts.concept_id`
  while `phase != done`. Grading already used each item's own concept, so mastery stayed safe.
  Consequence: R4 cross-concept spaced-review items conflict with the lock → deferred.
- **G29 (LaTeX is unspeakable/unrenderable):** the generator emitted `$12x^2y$`; the cv2 card
  and the TTS both render/read verbatim (KaTeX exists only in the web UI). Fix at the source
  (plain-text instruction) + a `_plainify_math` belt — NOT a panel LaTeX renderer.
- **G30 (Stage 5 is a real fork, not a drop-in):** `build_perception` has an exact-cover drift
  guard — `SIGNAL_DEFS` must equal `label_space.json`. Adding `practice_request`/`test_request`
  as **signals** would move the trained label space 38→40 (+ head eval baselines); as **intents**
  it dodges that guard but reroutes intent classification. Either way validation is BILLED.
  Deferred to an explicit owner decision — deterministic cues already cover mode requests.
- Lockstep: build plan §14 (new), plan §4.4 + §5.6 build notes + staging table, this entry.
  Architecture doc: new third evidence API + mode layer + mastery-gate state (§6.4/§6.6/§12/§13).

## Part 13 — voice latency streaming (2026-07-20, Stages 0–2 built)

Cut time-to-first-audio **10.5–19.9 s → 3.3–4.4 s** on winipi5 by streaming TTS and
generation; answer length stays LLM-driven and TTFA no longer tracks it. Measured tables in
build plan §15. Gotchas that cost real time here — do not rediscover:

- **G31 (urllib3 `chunk_size=None` means "read to EOF"):** `r.iter_lines(chunk_size=None)`
  buffers the ENTIRE response and hands every line over at once. The server was streaming
  correctly (verified with `curl -N`, lines arriving 0.5–5 s apart) while the client saw all
  of them land together at 14.1 s — streaming looked completely broken and was not. Use a
  small int (512). Diagnose this class of bug by isolating with `curl -N` BEFORE touching the
  server.
- **G32 (never open a Cloud TTS stream before you have text):** the first cut opened
  `streaming_synthesize` at the top of `text_turn` to "pre-warm" it, so the input side sat
  idle through STT + perception + generation. Cloud TTS drops an idle streaming input: the
  worker died, `feed()` pushed text nobody was reading, and the turn silently fell back to
  one-shot synthesis (`chunks: 0`). Intermittent — it only bit when generation was slow.
  Block on the first sentence, THEN open the stream.
- **G33 (streaming TTS wants `AudioEncoding.PCM`, not `LINEAR16`):** LINEAR16 returns a
  44-byte WAV header that a raw int16 player emits as a click. Streaming PCM is headerless.
  Chirp3-HD supports streaming; older voices do not.
- **G34 (the Vertex context cache expires silently and nobody notices):** the Part 11 cache
  died **2026-07-03** (24 h TTL) and had been absent for 17 days. The documented fallback —
  send the full 6,062-token static block — works, so nothing broke; perception just cost
  ~1.3 s/turn more (2843–3533 ms vs 1408–1806 ms fresh). `vertex_cache --status` reports
  `active: false`. **Treat cache recreation as recurring ops, not a one-time setup step.**
- **G35 (streamed answer text must not be re-fed):** the server feeds the answer to the speech
  pipeline after `turn()` for scripted/canned replies — guarded on `was_fed()`, because
  re-feeding an answer that streamed generation already delivered speaks it TWICE.
- **G36 (only sentence 0 is safe to speak early):** `_truncate_to_spoken_budget` keeps
  sentences in order and rewrites only the LAST kept one (and only when >1 kept), so
  `kept[0] == sentences[0]` always. Anything past sentence 0 can still be rewritten by the
  budget, and audio already spoken cannot be recut. This is a proof, not a heuristic — do not
  "optimize" it into releasing more.
- **G37 (per-chunk fades make chunked TTS sound robotic):** `_prep_audio` faded both edges of
  every buffer; applied per chunk that is an audible dip at every seam. Fade in on the first
  chunk, out on the last only. Verified objectively: max sample jump **at a join 0.0897** vs
  0.4055 anywhere in the waveform, and the same long-silence-run count as one-shot synthesis.
- **G38 (dev-loop, not product):** Git Bash mangles absolute POSIX paths in argv
  (`/home/x` → `E:/Git/home/x`) — set `MSYS_NO_PATHCONV=1` for any ssh/paramiko helper, or
  every remote path silently points somewhere else. Run the server with `python -u` or its
  stdout block-buffers into the log and failures stay invisible for minutes.

- **G39 (boot cost was not where the code reads like it is):** `TutorLoop()` measured 126 s.
  Profiling per loader found (a) `HopeDetector.load()` building a `SentenceTransformer` that
  `tutor_loop` **discarded on the very next line** — 6.3 s of pure waste; (b)
  `load_chunk_index()` costing 7.3 s on a cache HIT, because passing `gp.embedder` as an
  argument RESOLVED the lazy MiniLM property the cache-hit path never needed — it reads like
  a 5 ms `np.load`. Each `SentenceTransformer(...)` is ~6.7 s on the Pi and is **not** cheaper
  the second time, so every accidental construction is a full 6.7 s. Fix: pass a *callable*
  provider, not an embedder; share via a `_LazyEmbedder` proxy; prewarm on a background
  thread. **Lesson: an eagerly-evaluated argument defeats a lazy property — profile loaders
  individually, never reason about boot cost from reading the code.**
- **G40 (serial cloud-client construction dominated the rest of boot):** CloudStt, CloudTts
  and the Vertex client are each 4–9 s of ADC/channel setup and were built one after another.
  Building them concurrently (plus concurrent warm calls) took boot **126 s → 14.4 s**.
  `llm_vertex._client`'s memo needed a lock once two warms could race for it.

- Lockstep: build plan §15 (new), `PART13_LATENCY_STREAMING_PLAN.md` (design of record),
  `wini_server.py` + `wini_client/README.md` `/voice_turn` NDJSON contract (turn_meta + audio
  parts, `audio_streamed`, either-order note), this entry. Architecture doc: the turn is now a
  stream, not a request/response — §19 runtime loop.

### 2026-07-20 — device UX: warm-gated UI start, on-screen close, one-path launcher

Report was "the desktop icon and `bash run_wini_package.sh` are not the same". They already
ran the *same script*; the difference was purely timing — the UI came up ~1 s in while the
brain took ~2 min (now ~15 s), so the picker was tappable and dead. Three changes:

- **G41 (a visible-but-dead UI reads as a broken launcher):** the launcher now starts `wini_ui`
  only after `/health` reports `ready` (poll, 180 s cap), and `screens/splash.c` lost its
  1500 ms auto-advance — it holds until `{"cmd":"ready"}` arrives. Because the UI is started
  *after* the brain is warm, a plain `send()` would go to nobody: `ModeChannel.set_sticky()`
  re-sends the signal to every UI that connects. **Lesson: when you reorder startup, re-check
  every one-shot message that assumed the peer was already listening.**
- **G42 (the lock fd leaked into the whole process tree):** `flock` on `logs/.launch.lock`
  serializes the impatient second tap, but every long-lived child inherits fd 9 and keeps
  holding the lock after the launcher exits — so the *next* tap silently no-ops forever. The
  leak surfaced through `wini_ui` → close button → `stop_wini_package.sh` → `touch_service.py`,
  i.e. a grandchild of a grandchild. Fix: spawn each with `9>&-`. **Lesson: an advisory lock is
  only stale-proof if no descendant holds the descriptor.**
- **Close button** (`wini_ui/widgets/close_button.c`): floating pill bottom-LEFT (pause is
  bottom-right — never adjacent to a mis-tap), confirm dialog, then `$WINI_STOP_CMD` detached
  via `setsid`. A child's stray tap must not end the session, hence the confirm.

Verified on winipi5: UI absent at t=4 s and up at t=30 s; splash released to the picker;
second tap during warmup ignored; tap while running "already running"; Close → brain/client/UI
all gone + touch service resumed + lock released.

- Lockstep: `WINI_UI_STATUS.md` (§ one-press start + `ready` row in the command table + close
  button), `wini_ui/README.md` IPC contract, `Wini.desktop` (canonical copy now in-repo), this
  entry. No schema/model/dataset change — the 4-doc set is untouched.

### 2026-07-20 — T9 tier-3 teaching visual: EXPLAIN turns show a crop by default

Report from studying with the device: "there is just text shown while explaining — a figure
or formula on screen would teach much better." Root cause was NOT the store and NOT the
client: the panel's figure card worked, but the brain almost never selected a visual.

- **Measured gap:** graph `illustrated_by`/`has_formula` edges cover **7/108 concepts —
  0/13 trigonometry** — so the representation-gap show-case could never fire for trig; the
  incidental path was gated to two rare visual actions. Meanwhile 244 `figure_caption`
  chunks carry `image_path` + `concept_ids` for every chapter (trig 9/13 concepts), and
  the crops themselves are on the device (jemh108: 127 files, jemh109: 66).
- **Fix (`tutor_loop.py`):** `visuals_by_concept` index built in `__init__` from the
  caption chunks; `_build_display` gained tier 3 — on a teaching turn (`mode != "TEST"`
  and `mode_item is None`), show the top-ranked image-bearing chunk from the turn's own
  retrieval, else the primary concept's first stored visual. Tiers 1/2 unchanged and still
  win; TEST turns still never carry a figure; the existing `figure_on_screen` prompt cue
  makes generation teach THROUGH the crop.
- **Verified on winipi5:** `--once "explain trigonometric ratios to me"` picked
  `fig::jemh108::fig_8_8` (tan A = 4/3 triangle, on-topic) and a mic-free
  ModeChannelSink replay + scrot showed the crop + caption rendered under the explain
  card on the DSI panel. (Driver artifact, not a bug: feeding raw `turn()` JSON to the
  sink mangles the header — `wini_server.py:331` flattens `concept` to the id string for
  real clients.)
- **Lesson:** the pedagogy gates assumed graph edges that were never built for most
  chapters — a gate is only as good as the data it reads. Gate coverage (edges per
  concept) should have been measured when T9 shipped.
- **Open:** 644 formula crops are concept-linked only for jemh102 — chapter-wide
  `has_formula` linking would let identity-heavy turns show the formula image itself.
- Lockstep: architecture §9 (T9 display contract, 3 tiers), build plan v5.1, this entry.
  No dataset/model/schema change — the report doc is untouched.

### 2026-07-20 — chapter-wide concept→formula links: formula crops reach T9 (build plan v5.2)

Closes the v5.1 open item: 644 formula crops existed but the vision pass emitted
`likely_concept_ids` only for jemh102, so all 266 graph `has_formula` edges hang off 7
jemh102 concepts — no other chapter could ever show a formula image.

- **`link_formulas.py` (new)** derives concept links for every formula node
  deterministically (no LLM, no embeddings): 0.6·page-inheritance (concept_scores mass of
  the chunk rows on the formula's page) + 0.4·name/alias token match + 0.1 definitional
  bonus − 0.25 worked-example penalty (given/step/derived/… slugs must not outrank the
  definitional form); score ≥ 0.35, ≤3 concepts/formula. Writes the NEW derived artifact
  **`rag_store/formula_links.json`** (2135 links, 1458 image-bearing); graph.json /
  chunks.jsonl / concepts.json untouched (read-only rule).
- **Wiring:** `TutorLoop.__init__` merges the links + the original graph `has_formula`
  edges into `visuals_by_concept` as chunk-shaped pseudo-rows (`kind:"formula"`,
  `representations:["symbolic"]`, resolved via `formula_rows_by_id` in `_build_display`).
  Captions stay first per pool; formula rows follow by link score.
- **Coverage measured: 7/108 → 95/108 concepts with ≥1 formula visual** (every chapter;
  jemh108 trig 8/8; jemh1a2 only 2/7 — the appendix has just 4 formula crops). All
  referenced crop files exist on disk.
- **Tier-3 ordering fix found live:** on the cold "explain the pythagorean trigonometric
  identities" turn, concept resolution ABSTAINED → retrieval spanned ALL chunks → an
  off-concept caption (fig 8.16) beat the concept's own formula crop. `_build_display`
  tier 3 now prefers a crop TAGGED with the primary concept (ranked row, else the
  concept's stored pool) over merely semantically-similar crops; concept unknown keeps
  the old order. **Verified:** mid-session explain turn on
  `jemh108__pythagorean_trig_identities` displays
  `formula_jemh108_pythagorean_trigonometric_identity.png` (cos² A + sin² A = 1).
- **Latent race fixed in passing (`perception/gemini_perception.py`):** the MiniLM
  prewarm thread and the first turn raced into the unlocked lazy `embedder` property;
  two concurrent SentenceTransformer constructions corrupt each other via accelerate's
  global init_empty_weights state → BOTH fail with "Cannot copy out of meta tensor"
  (seen deterministically on the slow laptop; standalone load fine). Double-checked
  lock = single-flight construction. **Lesson: a lazy property shared with a prewarm
  thread needs a lock — the failure mode looks like a broken torch install, not a race.**
- **Smoke: ALL 25 CHECKS PASSED** (twice: after wiring, and after the tier-3 ordering
  fix; T9c picks the same caption crop as before — captions-first preserved).
- Rebuild: `python link_formulas.py` after any graph/chunks/concepts rebuild (also in
  CLAUDE.md quick commands).
- Lockstep: architecture §9 (visuals_by_concept sources + tier-3 order), RAG plan §2.1
  addendum, build plan Part 7 v5.2, this entry. No dataset/model change — the report
  doc is untouched.


---

## 2026-07-23 — Brain architecture audit remediation (all 16 defects)

`BRAIN_ARCHITECTURE_AUDIT.md` audited the deployed brain against
`learner_cognitive_state_architecture.md` and found 16 defects. All fixed and verified on
`winipi5` in the audit's suggested order. Execution detail + measured before/after:
**build plan Part 14**. Contract decisions: architecture §6.1, §6.4, §6.6, §6.7. No dataset
or model artifact changed — report §6.1 carries the note on why the new action is *not* in
the policy-shadow label space.

### Gotchas worth not rediscovering

- **A pending_check makes perception score an incoming problem as `answer_attempt`.** The
  first cut of rule 4b was gated on `not answer_try` and was therefore swallowed whenever a
  diagnostic was armed — the quadratic probe still routed to `QUIZ` and looked like the fix
  had not deployed. The discriminator is whether the utterance is a *directive* ("solve …",
  "find …"): a command aimed at the tutor cannot be an answer to the tutor's own question,
  while a bare equation ("x = 5") usually is. Do not blanket-suppress `answer_try`.
- **A directive problem must also be a NON-ATTEMPT for grading**, or setting our question
  aside to ask their own gets scored as a wrong answer and moves mastery on evidence the
  child never gave.
- **Two prompt clauses fought the new action and won.** Telling the model to "state the final
  answer" while also telling it to "ask them to state the result" (the generic pacing
  micro-check) produced *"x = 378/9. Calculate the value of x. What is the speed?"* — the
  answer withheld, through the pacing block rather than the action. Both the tone string and
  the micro-check clause needed the SOLVE case carved out.
- **`_truncate_to_spoken_budget` has a streaming invariant**: `_stream_answer` speaks
  sentence 0 before the rest exists, so anything that evicts sentences must never touch index
  0. Audio already spoken cannot be un-spoken.
- **`item_history` is keyed BY ITEM** (`{item_id: {last_seen, outcomes[]}}`), not a flat
  chronological log — anything wanting a recent-outcomes sequence has to sort on `last_seen`
  and flatten.
- **The pacing governor runs only on `/voice_turn`**, never on `/turn` or
  `tutor_loop --once`. A ledger fix cannot be verified through the text paths; drive
  `after_turn` directly against a real loop instead.
- **`pkill`/`disown` in a compound `pi.py run` returns 127** even when the kill worked. Use
  `stop_wini_package.sh`, or check `pgrep` afterwards rather than trusting the exit code.
- **Thresholds were measured, not guessed** (0.28 retrieval / 0.30 visual / 0.20 bridge):
  on-topic retrieval on this store scores 0.36–0.63 while a pool with no real match tops out
  near 0.24, and the two figures the audit caught scored 0.221 and 0.020. Re-measure these if
  the chunk index or the embedder changes.
- **Merging the three math-to-text implementations surfaced a live bug**, which is the
  argument for having done it: the quiz path rendered `\geq` as `">= q"` because `\ge` was
  replaced before `\geq`. Longer macros first, always.

### Deployment note

`tutor_loop.py` on the device was BEHIND the laptop (missing the 2026-07-20 formula-links
block); pushing the laptop copy carries that block, which is inert without
`rag_store/formula_links.json` — still not deployed to `winipi5`.

### Part 15 — Cloud Run + Firestore deployment (2026-07-25)

The brain now runs as a warm Cloud Run service (`wini-brain`, asia-south1, min-instances=1,
concurrency=1) with learner state in Firestore. Traps found, so they aren't rediscovered:

- **flash-lite is SLOWER here, not faster.** The plan's Gemini 3.x targets don't exist; the
  only real faster model (`gemini-2.5-flash-lite`) isn't in `asia-south1` (only `global`/
  `us-central1`) and measured slower than `gemini-2.5-flash@asia-south1` on short replies. The
  model swap is a regression — Phase C shipped as a revertible seam only, no flip.
- **`--no-cpu-throttling` is mandatory on Cloud Run for this brain.** It loads in a background
  thread (`Brain._load`); Cloud Run throttles CPU outside request handling, which would stall
  that thread and the instance would never become `ready`. Always-allocated CPU keeps min-
  instances warm and lets the load complete.
- **Cloud Build uses `.gcloudignore` (NOT `.dockerignore`) to decide the UPLOAD.** Without a
  `.gcloudignore` the bundled `google-cloud-sdk/` + `.git` inflate the context. Ship both.
- **Cloud Build now runs as the Compute Engine default SA.** On a fresh project it lacks
  `storage.objects.get` on the source bucket → 403 "could not resolve source". Grant
  `<projnum>-compute@` roles/cloudbuild.builds.builder + storage.admin + artifactregistry.writer
  + logging.logWriter.
- **CPU-only torch.** Install `torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu`
  before the rest — the default index pulls multi-GB CUDA the container can't use. Bake MiniLM
  in the image (`SentenceTransformer(...)` at build) so a cold instance never blocks on a
  HuggingFace download.
- **Firestore state = one JSON field.** Storing `LearnerState.data` as a native map trips
  Firestore's no-nested-arrays rule; serialize the whole dict to a `state_json` string field —
  atomic, last-writer-wins, no type limits.
- **Parallel grader is outcome-identical.** `WINI_PARALLEL_GRADER` runs `judge_answer` alongside
  perception and injects `precomputed_grade`; it is consumed only where the serial path would
  have graded, so a non-attempt still scores `not_an_answer`. Proven by equivalence test.
- **Streaming STT parity needs real-time pacing + a tail-guard.** Dumping all audio blocks
  instantly drops the final word and looks like a regression; pacing blocks at ~50 ms (as the
  device streams) plus keeping the last un-finalized interim gives 20/20 batch parity.

---

## 2026-08-12 — P0 Evidence Integrity implementation

- Started from a clean connected worktree and the active `cloud_run_service` Docker/runtime;
  did not clone, fetch, switch, commit, or modify production learner/RAG data.
- The 306-row learning log exposed 3 duplicate `The answer is 5` grades (correct/correct/wrong),
  3 quadratic contradiction rows that all set misconception `active`, and 30 legacy QUIZ rows.
  The read-only P0 regression harness now dedupes the reply, does not strengthen the contradicted
  misconception, preserves non-attempts, and confirms the unconditional QUIZ fallback is gone.
- Generated item verification measured 50/50 agreement (100%, 98% gate). The prepared JSONL bank
  is intentionally absent until an explicit off-path preparation job populates it; empty bank
  means no assessment, not synchronous generation.
- Performance gotcha found and fixed: a first ledger transaction snapshot copied the entire
  growing ledger (append p50 13.66 ms at 1,000 rows). Scoped projection undo restored O(1)-style
  behavior: p50 0.1031 ms, p95 0.2605 ms; duplicate lookup p95 0.0023 ms. Realization p95 was
  0.0118 ms and runs after streaming, so measured added TTFA is 0 ms.
- Identity/store failures now fail closed; multi-learner authentication remains an external
  deployment integration. Full migration/rollback detail: `P0_EVIDENCE_MIGRATION.md`.
# 2026-08-14 — Issue 13 lifecycle/state foundation

Added feature-neutral Turn lifecycle contracts and an inactive State and Persistence
module beside the canonical runtime. The module migrates and identity-binds a copied
starting state, supplies immutable capability-scoped Learner/Session views, validates
exclusive ownership and overlapping changes, routes evidence through `record_outcome`,
and commits with optimistic whole-state versioning. The local adapter reuses atomic
`LearnerState.save`; the durable adapter performs one existing store save; deterministic
success/failure behavior is available without cloud access.

Gotcha: validate Turn identity before persistence so receipt construction cannot fail
after a successful write. Non-evidence append changes need durable idempotency too;
their keys live in `state_change_index`, separate from the evidence index.

Verification measured 18 new tests, 34 full-discovery tests, 33 existing P0 invariant
tests, and 16 oracle tests passing. The frozen oracle self-check has zero differences;
its pre-existing incomplete artifact/replay status still blocks a full equivalence
verdict.

# 2026-08-14 — Issue 14 typed coordinator activation

Routed the canonical `TutorLoop.turn()` compatibility façade through a typed Turn Coordinator.
The façade now builds immutable identity/interaction/device/budget/precomputed-observation input,
then thaws only the committed compatibility result back to the legacy dictionary/list contract.
The original Turn body is `_legacy_turn` behind `LegacyTurnAdapter`, explicitly measured as one
temporary adapter execution with every logical phase still unextracted.

Added coordinator-owned recovery classification and Runtime Supervisor health. Unclassified
legacy exceptions become observable typed Failure Signals, fail closed, and re-raise the same
exception type/message; repeated invalid Turns transition `DEGRADED` to `UNAVAILABLE`. Existing
streaming sinks remain untouched, so provisional ordering and terminal errors keep their prior
behavior. `/health` now includes the runtime health state.

Review also converted recovery metadata into behavior: degradation is recorded on the typed
result, retrieval/generation fallback is accepted only with a valid outcome, and every remaining
invalid outcome fails closed. A committed legacy Turn is never replayed for retry; bounded
idempotent retry awaits a pre-commit operation port. Recovery-critical capability names are
enum-backed.

Review correction: the first bridge receipt only hashed working state and incorrectly inferred
presentation delivery from intended output. The adapter now invokes the configured local/remote
commit boundary before issuing its receipt, restores working/local state on commit failure, and
records downstream presentation as unobserved `PARTIAL` with no fabricated delivered modality.
The initial frozen-projection loop was removed during review because feeding expected output
back into itself was not valid equivalence evidence.

The frozen corpus still has its pre-existing missing-artifact/incomplete-replay limitation; no
model, prompt, dataset, retrieval, persistence technology, or network boundary changed.

Measured verification: 44/44 full `unittest` discovery, 33/33 P0 evidence/streaming invariants,
14/14 focused runtime tests, and 16/16 frozen-oracle tests passed; the 27-case corpus validated
and compile/diff checks passed. The frozen reference self-check remains zero-difference, while
its already-recorded missing artifacts and incomplete replay prevent a complete verdict.
