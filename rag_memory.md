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
