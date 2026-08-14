# Dataset and Neural Architecture Plan for Learner Cognitive State Models

## 1. Executive Summary

The product architecture should be trained around a learner-state loop, not a single intent-routing loop. The datasets must therefore capture:

- what the student said,
- which curriculum concept was involved,
- which cognitive signals were present,
- what the learner state looked like before the response,
- what pedagogical action was chosen,
- what happened after that action,
- whether learning improved later through retention or transfer.

The recommended data strategy is staged:

1. Build high-quality exemplar and retrieval datasets first.
2. Use rule policies and expert/LLM-assisted annotation to produce reliable labels.
3. Train compact neural models for HOPE and pedagogy policy after enough turn logs exist.
4. Keep the rule engine as a safety layer while neural models learn action ranking.
5. Add delayed outcome data as soon as real learners use the system.

Recommended initial dataset size for a serious prototype:

| Model area | Minimum useful dataset | Strong prototype dataset | Production target |
|---|---:|---:|---:|
| MiniLM exemplar cognitive classifier | 6,000 to 10,000 examples | 18,000 to 30,000 examples | 50,000+ examples |
| MiniLM concept resolver | 5,000 to 8,000 queries | 15,000 to 25,000 queries | 60,000+ queries |
| MiniLM retrieval relevance/reranking | 8,000 to 12,000 query-chunk pairs | 40,000 to 80,000 pairs | 250,000+ pairs |
| MiniLM representation/misconception taggers | 5,000 to 10,000 examples | 20,000 to 40,000 examples | 100,000+ examples |
| HOPE detectors | 15,000 to 25,000 labeled turns | 60,000 to 120,000 labeled turns | 300,000+ turns plus trajectories |
| Pedagogy policy neural engine | 20,000 to 40,000 policy traces | 100,000 to 250,000 traces | 1M+ traces for RL optimization |
| Knowledge tracing / learner state | 50,000 interactions | 250,000+ interactions | 2M+ interactions |

The first release can work with smaller data if MiniLM models are exemplar-based and the pedagogy engine remains rule-based. Neural policy and PPO should wait until reliable logs and delayed reward labels exist.

> **Scope note:** This plan targets **Class 10 Mathematics only**, matching the corpus the RAG store is built from (NCERT Class 10 Maths). All examples below are Maths examples. Science/Physics is out of scope for this dataset.

### 1.1 What the built RAG store already provides

A first slice of Phase 1 is **already realized** by the RAG store (`rag_store/`), built over the full NCERT Class 10 Maths textbook. Several datasets below can be bootstrapped directly from it rather than from scratch:

| Plan artifact | Already in the RAG store (v1, built) |
|---|---|
| Curriculum concept graph (anchors, prerequisites, representations, misconceptions) | **108 concepts across 16 chapter documents (14 NCERT chapters + 2 appendices)** with `summary`, `aliases`, `prerequisites`, `representations`, `misconceptions`; graph edges `prerequisite_of`, `represented_by`, `has_misconception`, and `transfers_to` (near/far — 59 edges in v1, only on the Polynomials chapter plus vision-extracted application bridges) |
| Retrieval corpus + grounding | **709 NCERT-grounded chunks**, every chunk tethered to ≥1 chapter concept (field `concept_ids`, with `concept_scores`), full `source_path` + `page` provenance |
| Difficulty / ZPD labels | every chunk (and extracted exercise/example node) carries a `difficulty` 1–9 tag (item-level cognitive-load estimate) |
| Pedagogical-role labels | every chunk tagged `definition / explanation / worked_example / practice / challenge / application / summary / historical_note` (v2 adds `bridge_recall`) |
| Representation taxonomy | the graph uses 8 representation types: `symbolic, verbal, graphical, diagrammatic, algebraic, tabular, numerical, flowchart` (no `experimental` — that is Science-only) |
| Structured evidence nodes | figures, formulas, worked examples, exercises, tables extracted and concept-linked |

### 1.2 What the store v2 upgrade adds (per `RAG_upgrade_plan.md`, in progress)

The store is being upgraded to **schema v2** (phases, acceptance criteria, and verification in
`RAG_upgrade_plan.md`). The datasets below should treat these as available fields once the
corresponding phase's scorecard passes:

| v2 addition | Contents | Datasets it feeds |
|---|---|---|
| Concept-card enrichment | `difficulty` (1–9, on the card), `transfer_links` (≥2 near + ≥1 far, validated IDs), `integration_links` (KI, with representation pairs), `ct_probes` (with rubric anchors), `applications`, `vocabulary`, `metacognitive_prompts` (`after_success`/`after_struggle`) | concept resolver anchors (4.1), HOPE bank (5.6), policy inputs (6.2) |
| Misconception enrichment | every misconception node gets `why_wrong`, `correct_idea`, `diagnostic_question` (with its own hint chain); runtime status machine `active/weakening/resolved/recurring` | misconception tagger (4.4), misconception tracker (7.4) |
| Problem schemas | `problem_schema` nodes per concept: `method_steps`, `instance_ids`, `isomorphic_variables`, `trap_steps` | policy traces (6.4 — analogous worked-example action), KT items |
| Hint chains | 3-level `hint_chain` (nudge → method recall → partial step, never the answer) on all exercises + diagnostics | grounding/leakage guard (7.3), policy engine (6) |
| Visual assets | cropped figure/table/formula images (`image_path`) with `alt_text`, `supports_representation`, `disambiguates_misconceptions`, `good_for_questions`, `addresses_gap`; retrievable `figure_caption` chunks | representation tagger (4.3), retrieval corpus (4.2), KI items |
| Class-9 bridges | `grade9_concept` nodes (`bridge_recap`, `diagnostic_question` + expected answer) with `bridges_to` edges; gating contract + `apply_bridge_result` write-back | knowledge tracing (7.1 — cold-start probes), KT items, policy traces |
| Retrieval policy artifacts | 7-term learner-state-aware ranking with per-turn `ranking_trace`; evidence provenance manifest per response; bundle cohesion check | retrieval reranker (4.2), grounding guard (7.3), policy traces (6.4) |
| HOPE bootstrap | `hope_prompt_bank.jsonl` (≥1,000 curated KI/KT/CT prompts) + `hope_gold_set.jsonl` (~1,200 teacher-labeled answers, κ ≥ 0.6 gate) | HOPE detectors (5), rubric calibration (9.2) |

So the **concept resolver anchors** (Sec. 4.1), the **retrieval relevance corpus** (Sec. 4.2), the **representation taxonomy** (Sec. 4.3), the **misconception families** (Sec. 4.4), and the **HOPE seed corpus** (Sec. 5.6) should be seeded from the store's `concepts.json`, `chunks.jsonl`, `graph.json`, and the v2 artifacts before any new authoring begins.

---

## 2. Common Dataset Foundation

All model datasets should share a common schema so outputs can be joined across the learning loop.

### 2.1 Core Turn Schema

```json
{
  "turn_id": "t_000001",
  "student_id_hash": "s_013",
  "session_id": "sess_204",
  "grade": 10,
  "subject": "mathematics",
  "chapter": "quadratic_equations",
  "student_text": "If the discriminant is zero, does the equation still have two roots?",
  "normalized_text": "If the discriminant is zero, does the equation still have two roots?",
  "current_concept_id": "jemh104__discriminant_nature_of_roots",
  "candidate_concepts": ["jemh104__discriminant_nature_of_roots", "jemh104__roots_of_quadratic_equation", "jemh104__quadratic_formula"],
  "conversation_context": "student was solving ax^2 + bx + c = 0 using the quadratic formula",
  "learner_state_before": {
    "mastery": 0.52,
    "confidence": 0.48,
    "cognitive_load": 0.42,
    "hint_dependency": 0.20,
    "hint_chain_position": 0,
    "misconceptions": [
      {"id": "misconception::quadratic_always_has_two_real_zeroes", "status": "active", "confidence": 0.61}
    ],
    "representations_missing": ["graphical"],
    "hope_rolling": {"ki": 0.41, "kt": 0.22, "ct": 0.55}
  },
  "evidence": [
    {"id": "jemh104::page_008::chunk_001", "type": "chunk", "why": "explains discriminant cases"},
    {"id": "fig::jemh102::fig_2_4", "type": "figure",
     "image_path": "figure_crops/jemh102/fig_2_4.png", "why": "graphical representation gap"},
    {"id": "misconception::quadratic_always_has_two_real_zeroes", "type": "misconception",
     "why": "status=active, diagnostic served"}
  ],
  "bridge_ids": [],
  "schema_ids": [],
  "ranking_trace": {"w1_relevance": 0.78, "w4_repr_gap": 0.31, "w5_misconception": 0.40},
  "teacher_action": "SOCRATIC_COUNTEREXAMPLE",
  "model_action": null,
  "response_summary": "asked what equal roots mean geometrically, when the parabola just touches the x-axis at one point",
  "learner_state_after": {
    "mastery": 0.55,
    "confidence": 0.50,
    "cognitive_load": 0.45,
    "misconception_transitions": [
      {"id": "misconception::quadratic_always_has_two_real_zeroes", "from": "active", "to": "weakening"}
    ]
  },
  "short_term_outcome": {
    "next_answer_correct": true,
    "confusion_reduced": true,
    "hint_used": false
  },
  "delayed_outcome": {
    "retested_after_days": 7,
    "retention_correct": null,
    "transfer_correct": null
  }
}
```

> The `subject`, `current_concept_id`, `candidate_concepts`, and evidence fields above use the **real schema of the built RAG store**: concept IDs are chapter-namespaced (`<doc_id>__<concept>`, e.g. `jemh104__…`) and chunk IDs follow `<doc_id>::page_<NNN>::chunk_<NNN>` (or `::summary`). The turn-schema field `candidate_concepts` maps directly from the store's per-chunk **`concept_ids`** field (with companion `concept_scores`), so this schema joins onto the store without remodeling.
>
> The `evidence` array IS the runtime **provenance manifest** (architecture §6.7) — the retrieval layer emits it with every response and the append-only log persists it verbatim, so this turn schema costs nothing extra to collect. `ranking_trace` records the 7-term ranking weights that selected the evidence (reranker training features, Sec. 4.2). `misconception` entries carry the §10 status machine values (`active/weakening/resolved/recurring`), and `learner_state_after.misconception_transitions` plus the `apply_bridge_result`/`apply_probe_result` outcomes are the supervision signal for the misconception tracker (Sec. 7.4) and knowledge tracing (Sec. 7.1).

### 2.2 Label Sources

Use four sources in this order:

1. Curriculum experts: define concepts, misconceptions, representations, and teaching actions.
2. Teacher annotation: label real and generated student utterances.
3. Offline LLM judge: bootstrap labels, generate edge cases, and flag disagreements.
4. Real learner logs: convert teacher/rule decisions plus outcomes into training traces.

The runtime should not depend on an LLM judge for every decision. The LLM is best used offline as a label generator and reviewer, then distilled into smaller models.

### 2.3 Data Split Rules

Avoid leakage by splitting at student/session level, not random row level.

- Train: 70 percent
- Validation: 15 percent
- Test: 15 percent
- Holdout chapters: keep 1 to 2 chapters unseen for generalization checks
- Holdout misconceptions: keep selected misconception families unseen for robustness checks

---

## 3. MiniLM Based Exemplar Classifier

### 3.1 Purpose

This model is the semantic replacement for regex intent and signal rules. It detects surface and cognitive signals in student messages while preserving multi-label meaning.

It should classify:

- question,
- answer attempt,
- explanation attempt,
- confusion marker,
- curiosity,
- misconception clue,
- transfer attempt,
- topic shift,
- self-correction,
- abstraction attempt,
- request for hint,
- frustration or disengagement.

> Note: the architecture's Cognitive Analyzer (§6.2) also lists `confidence`, `explanation quality`, and `cognitive load`. These are not produced by this multi-label surface classifier; they are estimated downstream by the HOPE detectors (Sec. 5) and the Learner State Model (Sec. 7.1), then written into the learner state.

### 3.2 Recommended Architecture

Start with an exemplar classifier, not a fully fine-tuned transformer.

```text
student utterance
-> MiniLM embedding
-> cosine similarity against labeled exemplars
-> top-k evidence per label
-> calibrated multi-label scores
-> thresholded signal set
```

Recommended model:

- `sentence-transformers/all-MiniLM-L6-v2`
- normalized embeddings
- cosine similarity
- per-label thresholds
- hard negative bank for confusing labels

Optional second stage:

- logistic regression or shallow MLP on MiniLM embeddings,
- trained only after at least 15,000 labeled examples exist.

### 3.3 Dataset Required

Minimum:

- 300 to 500 examples per label,
- 12 labels,
- 6,000 to 10,000 total examples including hard negatives.

Strong prototype:

- 1,000 to 1,500 examples per label,
- 18,000 to 30,000 total examples,
- at least 30 percent mixed-signal utterances.

Production:

- 50,000+ labeled utterances,
- balanced across all 16 Class 10 Maths chapters (algebra, geometry, trigonometry, statistics, probability),
- multilingual/noisy variants if the UI allows Indian English, Hindi-English, or shorthand.

**Realized (2026-06-19).** Canonical dataset = `dataset/exemplar_dataset_10000_fixed.json`:
10,000 audit-corrected base rows + 800 supplementary `split:"train"` rows (T2 acknowledgment
+ T3 weak-label pass). 38 canonical labels (incl. `acknowledgment`). `curate_dataset.py`
projects it to `_curated.json` (the build input); raw is archived under `dataset/archive/`.
Shipped exemplar classifier: evidence+logreg+cues, test micro/macro-F1 **0.83 / 0.69**
(build status + history in `complete_architecture_build_plan.md` §2.5.2). The Optional
second stage above is now shipped as part of the selected ensemble.

> **Repurposed as the perception eval contract (Part 11; measured + PROMOTED 2026-07-02).**
> The frozen TEST split (`models/exemplar_classifier/splits.json` → 999 rows of
> `_curated.json`) is ALSO the promotion gate for the Gemini perception layer
> (`PART11_GEMINI_PERCEPTION_LAYER.md`), and the full 999-row run is now measured. **Runtime
> perception is Gemini (`PERCEPTION_BACKEND=gemini` default since 2026-07-02):**
> - **Concept (hybrid, §5.5-hardened): top-1 0.930 / top-3 0.990** vs the resolver baselines
>   0.895/0.971 — raw Gemini primary is 0.890/0.990; the deterministic MiniLM-resolver
>   cross-check (`fuse_primary`) adds the final +0.04 top-1.
> - **Signals: gated by the behavioral state-trajectory eval, not label-F1.** Gemini's
>   label-reproduction micro-F1 vs this dense gold is 0.39 — structurally unwinnable for a
>   conservative perceiver because the heads (0.83) were *trained* on this gold (`curiosity`
>   is gold-labeled on 85% of rows; heads recall it 0.95 by memorization, Gemini 0.06 by
>   definition). On state moves through the unchanged `derive_*` math (48 authored probes),
>   Gemini beats the heads 0.857-vs-0.607 (field direction) and 0.833-vs-0.500 (must-fire
>   flags) — `eval/behavioral_eval_report.md`.
> - **Intent macro-F1 1.0; SAFETY/NONSENSE gate recall 1.0/1.0, 0 false-gates.**
> The head numbers in this report (**0.83/0.69** signals; resolver top-1 in §4) are retained
> as the **eval baselines** of the superseded-for-runtime local heads (kept on disk as
> fallback until Stage 6). Measurement docs: `eval/perception_eval_report.md` (v2 cache
> `perception_eval_raw2.jsonl` is the prompt of record) + `eval/behavioral_eval_report.md`.
> New eval files only; the dataset + splits stay read-only.

### 3.4 Dataset Creation Method

1. Create label definitions with positive and negative examples.
2. Generate student utterances from the Class 10 Maths concepts in the curriculum graph.
3. Include short, messy, incomplete, and mixed utterances.
4. Add hard negatives, such as factual questions that look like curiosity but are not transfer attempts.
5. Have two annotators label each row as multi-label.
6. Resolve disagreements through teacher review.
7. Build exemplar banks per label with clean positive, borderline positive, and hard negative examples.

### 3.5 Covered Points

The dataset must cover:

- single-signal messages,
- mixed question plus answer attempt,
- mixed confusion plus misconception,
- topic shift within one message,
- transfer across chapters,
- self-correction,
- confident wrong answers,
- low-confidence correct answers,
- equation-heavy messages,
- informal student language.

### 3.6 Five Dataset Examples

| Student text | Subject | Concept | Labels | Notes |
|---|---|---|---|---|
| "I think the parabola opens upward because a is positive, but why exactly?" | Maths | quadratic_zero_geometry | answer_attempt, explanation_attempt, question, confusion | Mixed reasoning and question |
| "Can I use the graph instead of solving the equation?" | Maths | graphical_method_solving | question, representation_shift, transfer_attempt | Student wants another representation |
| "Is finding HCF just the repeated division we did earlier?" | Maths | prime_factorization_hcf_lcm | transfer_attempt, curiosity, abstraction_attempt | Cross-method analogy |
| "Wait, I moved x to the other side but maybe I changed the sign wrongly." | Maths | substitution_method | self_correction, confusion, misconception_clue | Reveals sign-change error |
| "Just give hint, I cannot start this." | Maths | quadratic_equation_definition | request_hint, low_confidence, cognitive_load | Useful for hint dependency |

---

## 4. Remaining MiniLM Based Models

MiniLM should also support concept resolution, retrieval relevance, representation detection, and misconception clue detection. These are separate datasets because the labels and negative examples differ.

### 4.1 MiniLM Concept Resolver

#### Purpose

Map student text to one primary concept and optional secondary concepts using text-to-text semantic similarity against curriculum concept anchors.

#### Architecture

```text
student utterance
-> MiniLM embedding
-> compare with concept anchor embeddings
-> lexical rescue for spelling/noisy terms
-> prerequisite depth tie-breaker
-> primary concept + secondary concepts
```

> **Important Rules for Concept ID Assignment:**
> 1. **`INHERIT_CURRENT_CONCEPT` label:** Do not force the Concept Resolver to pick a concept for generic text (e.g., "what is this diagram, i am not able to understand", "this is so boring", "ok what next", "explain the equations, why is it like that?"). Instead, a first-class label in the concept space called `INHERIT_CURRENT_CONCEPT` exists. When the model outputs this label, the system simply looks at the Learner State (the `current_concept_id` in the turn schema) and carries it forward — no concept resolution is performed. This prevents hallucinated or forced concept assignments for utterances that are purely affective, procedural, or context-dependent.
> 2. **RAG-sourced concept IDs only:** The `concept_id` tagging of all examples must be retrieved strictly from the RAG store (`rag_store/concepts.json` and `rag_store/vector.faiss`). Do not invent or randomly add any concept IDs outside of this defined list. Valid concept IDs follow the `<doc_id>__<concept>` format (e.g., `jemh108__intro_trigonometry`).
> 3. **Assignment criterion:** A specific `concept_id` from the RAG store should only be assigned when the utterance **explicitly and unambiguously** names a mathematical concept that maps to a known entry in `concepts.json`. See `examples.md` for the full exemplar corpus with `concept_id` annotations following these rules.

#### Dataset Required

Minimum:

- 50 to 80 examples per concept,
- ~108 Class 10 Maths concepts (the curriculum graph already built in the RAG store),
- 5,000 to 8,000 examples.

Strong prototype:

- 150 to 250 examples per concept,
- 15,000 to 25,000 examples.

Production:

- 60,000+ concept queries,
- includes ambiguous and multi-concept turns.

#### Five Dataset Examples

| Student text | Primary concept | Secondary concepts | Label type | Hard negative |
|---|---|---|---|---|
| "Why does the graph of y = ax^2 bend upward?" | quadratic_zero_geometry | quadratic_coefficients | primary + secondary | linear_zero_geometry |
| "In ax + by + c = 0, if I change b, what happens to the line?" | pair_linear_equations_intro | graphical_method_solving | primary + secondary | quadratic_zero_geometry |
| "How do I know if two triangles are similar?" | triangle_similarity_criteria_intro | basic_proportionality_theorem | primary + secondary | similar_figures |
| "How do I find the distance between two points?" | distance_formula | section_formula | primary + secondary | midpoint_formula |
| "The roots are same, so is the discriminant zero?" | discriminant_nature_of_roots | roots_of_quadratic_equation | primary + secondary | solving_by_factorization |

### 4.2 MiniLM Retrieval Relevance Model

#### Purpose

Retrieve NCERT-aligned chunks, examples, analogies, and misconception corrections. This model does not decide pedagogy; it supplies evidence.

#### Architecture

```text
query or current concept
-> MiniLM embedding
-> FAISS top-k chunk retrieval
-> optional MiniLM cross-feature reranker
-> relevant evidence chunks
```

> Runtime alignment: the deployed retrieval layer ranks with the 7-term learner-state-aware
> score (architecture §6.7: relevance, difficulty fit, role match, representation-gap fit,
> misconception priority, hint-dependency penalty, HOPE-history boost) and logs a
> `ranking_trace` per turn. Those traces are free training data for the reranker: the
> structured terms become cross-features, and accepted/rejected evidence becomes graded
> relevance labels. The corpus also includes the v2 `figure_caption` and `bridge_recap`
> chunks, so "show me the graph of a quadratic with no real zeroes" must learn to retrieve a
> figure asset, not only text.

#### Dataset Required

Minimum:

- 8,000 to 12,000 query-chunk relevance pairs.

Strong prototype:

- 10,000 queries,
- 4 to 8 labeled chunks per query,
- 40,000 to 80,000 query-chunk pairs.

Production:

- 250,000+ query-chunk pairs,
- graded relevance labels: 0 irrelevant, 1 related, 2 useful, 3 directly supporting.

#### Five Dataset Examples

| Query | Positive chunk type | Relevance label | Hard negative chunk | Notes |
|---|---|---:|---|---|
| "Why does a quadratic polynomial have at most two zeroes?" | quadratic zeroes geometry explanation | 3 | cubic zeroes section | Similar vocabulary |
| "How does the graph change for a quadratic equation?" | parabola graph section | 3 | linear equation graph | Similar vocabulary |
| "What is an arithmetic progression?" | AP definition chunk | 3 | geometric pattern aside | Related word "progression" |
| "Why is the sum of the first n terms (n/2)(2a+(n-1)d)?" | AP sum derivation | 3 | nth term formula | Same chapter hard negative |
| "How to find HCF using Euclid's algorithm?" | Euclid division lemma example | 3 | polynomial long division | Procedural hard negative |

### 4.3 MiniLM Representation Tagger

#### Purpose

Detect which representation the student is using or requesting. The label space is the 8 representation types the curriculum graph already uses: symbolic, verbal, graphical, diagrammatic, algebraic, tabular, numerical, flowchart. (There is no experimental/lab representation in Maths; verbal-analogy phrasing is captured under `verbal`.)

#### Architecture

```text
student utterance + active concept
-> MiniLM embedding
-> representation exemplar bank
-> multi-label representation scores
-> representation coverage update
```

Use per-concept representation exemplars because a "graph" in coordinate geometry, a "diagram" in circles/triangles, and a "table" in statistics carry different teaching implications even within Maths.

#### Dataset Required

Minimum:

- 5,000 examples.

Strong prototype:

- 15,000 to 25,000 examples,
- at least 2,000 examples per representation type.

Production:

- 75,000+ examples with concept and representation pairs.

#### Five Dataset Examples

| Student text | Concept | Representation label | Secondary label | Notes |
|---|---|---|---|---|
| "Can you show it on a graph?" | quadratic_zero_geometry | graphical | request_representation | Direct request |
| "I only remember x = -b plus minus root..." | quadratic_formula | symbolic | partial_recall | Symbolic fragment |
| "Is an AP just adding the same step each time on a number line?" | ap_definition_identification | numerical | transfer_attempt | Number-line / verbal analogy |
| "In the figure, why is this angle equal to that one?" | triangle_similarity_criteria_intro | diagrammatic | question | Diagram reasoning |
| "From the frequency table, how do I get the mean?" | mean_grouped_data | tabular | question | Tabular/numerical data |

### 4.4 MiniLM Misconception Clue Tagger

#### Purpose

Detect utterances that likely reveal a known misconception before the deeper analyzer or HOPE detector evaluates it.

#### Architecture

```text
student utterance + concept candidates
-> MiniLM embedding
-> misconception exemplar bank per concept family
-> hard-negative comparison against correct explanations
-> misconception clue score
```

This model should not mark a misconception as active by itself. It should raise a clue score that the cognitive analyzer and misconception state tracker confirm over time.

> Bootstrap from store v2: every one of the 276 misconception nodes now carries `why_wrong`,
> `correct_idea`, and `diagnostic_question`. The misconception `text` seeds positive
> exemplars; `correct_idea` phrasings are the natural **hard negatives** (correct reasoning
> using the same vocabulary); `diagnostic_question` + expected answers generate near-miss
> examples. This cuts the cold-start authoring for the exemplar bank substantially.

#### Dataset Required

Minimum:

- 100 examples per misconception family,
- 50 misconception families,
- 5,000 examples.

Strong prototype:

- 20,000 to 40,000 examples.

Production:

- 100,000+ examples,
- includes near-miss and corrected reasoning examples.

#### Five Dataset Examples

| Student text | Concept | Misconception clue | Label | Notes |
|---|---|---|---|---|
| "A straight-line graph can cross the x-axis at two points." | linear_zero_geometry | line_can_have_two_zeroes | positive | From the curriculum graph |
| "The degree is 3 because the polynomial has 3 terms." | polynomial_degree | degree_equals_number_of_terms | positive | From the curriculum graph |
| "A zero of a polynomial just means the number zero." | zero_of_polynomial | zero_means_number | positive | From the curriculum graph |
| "The sum of the zeroes is b/a." | quadratic_coefficients | sum_is_b_over_a | positive | Sign/ratio error |
| "Every quadratic must cut the x-axis at two points." | quadratic_zero_geometry | quadratic_always_has_two_real_zeroes | positive | Ignores discriminant cases |

### 4.5 Dataset Creation Method for Remaining MiniLM Models

1. Build concept anchors from the curriculum graph nodes using the fields actually present in `concepts.json`: `name`, `summary` (description), `aliases`, `prerequisites`, `representations`, and `misconceptions` — plus, once store v2 lands, `vocabulary`, `applications`, `transfer_links`, `integration_links`, and `difficulty` directly on the card. Worked examples remain on linked `example` / `problem_schema` graph nodes; pull them in as secondary anchor text when needed.
2. For each concept, write 50 to 250 student-style queries at different levels of clarity.
3. For retrieval, pair each query with direct, related, weakly related, and irrelevant NCERT chunks.
4. For representation tagging, create examples where the same concept appears in the store's representation types: symbolic, verbal, graphical, diagrammatic, algebraic, tabular, numerical, and flowchart forms.
5. For misconception clue tagging, create positive examples, corrected examples, and hard negatives that use similar vocabulary but do not contain the misconception.
6. Add noisy variants: spelling mistakes, shorthand, mixed English/Hindi-English phrasing, partial equations, and vague references like "this graph" or "same formula."
7. Annotate primary concept, secondary concepts, representation labels, misconception clue labels, and relevance grade.
8. Review all examples where MiniLM nearest neighbors disagree with teacher labels; these become the hard-negative set.

### 4.6 Covered Points for Remaining MiniLM Models

These datasets must cover:

- exact concept naming and vague concept references,
- one-message multi-concept queries,
- prerequisite confusion,
- chapter-level ambiguity,
- retrieval against current concept and graph neighbors,
- off-syllabus detection,
- representation request and representation use,
- misconception clues versus correct but similar explanations,
- spelling and symbol noise,
- short fragments such as "why graph curve?" or "x sign change?"

---

## 5. HOPE Detectors Neural Network Architecture and Dataset

### 5.1 Purpose

HOPE detectors measure learning quality signals, especially:

- KI: knowledge integration and representation translation,
- KT: knowledge transfer across contexts,
- CT: critical thinking,
- persistence and productive struggle,
- confidence/load patterns that affect learning.

These detectors should be compact online models trained from teacher/LLM-labeled data and real learner trajectories.

### 5.2 Recommended Neural Architecture

Use a multi-task architecture with shared text features and structured learner features.

```text
student text
recent tutor prompt
retrieved concept evidence
recent conversation summary
-> MiniLM text embedding

learner state vector
concept metadata vector
representation coverage vector
recent performance vector
-> structured feature encoder

MiniLM embedding + structured encoding
-> shared dense layers
-> KI head
-> KT head
-> CT head
-> cognitive load head
-> persistence/productive struggle head
-> uncertainty calibration head
```

Recommended first version:

- freeze MiniLM,
- concatenate MiniLM embedding with structured features,
- 2-layer MLP with dropout,
- multi-task sigmoid or ordinal heads,
- output each signal on a 0 to 1 scale.

Recommended strong version:

- add recent-turn attention over last 3 to 5 turns,
- add concept graph features,
- add delayed reward prediction auxiliary head.

### 5.3 Input Features

Text features:

- current student utterance,
- previous tutor action,
- previous tutor question,
- active transfer problem text,
- retrieved concept explanation summary.

Structured features:

- concept id embedding,
- subject and chapter,
- mastery before turn,
- confidence,
- cognitive load,
- hint dependency **and hint-chain position**,
- misconception flags **with status** (`active/weakening/resolved/recurring`),
- representation coverage,
- bridge-prerequisite mastery (Class-9 `grade9_concept` mastery for the active concept),
- concept difficulty (card-level, store v2) and current problem difficulty,
- active `problem_schema` id when the turn is inside a procedural problem,
- time since last practice,
- response latency,
- correctness of latest answer.

### 5.4 Labels

Each detector should use ordinal labels:

- 0: absent,
- 1: weak,
- 2: moderate,
- 3: strong.

Convert to normalized 0 to 1 scores for runtime.

HOPE labels:

- `ki_score`: connects multiple representations or concepts,
- `kt_score`: applies knowledge to a new context,
- `ct_score`: evaluates, questions assumptions, finds edge cases, or explains why,
- `productive_struggle`: persists with reasoning despite difficulty,
- `load_risk`: cognitive overload or frustration risk.

### 5.5 Dataset Required

Minimum:

- 15,000 to 25,000 labeled turns,
- at least 5,000 labeled examples each for KI, KT, and CT.

Strong prototype:

- 60,000 to 120,000 labeled turns,
- 10,000 to 20,000 examples per HOPE signal,
- 5,000 multi-turn trajectories.

Production:

- 300,000+ labeled turns,
- 50,000+ student trajectories,
- delayed retention/transfer labels for at least 20 percent of trajectories.

### 5.6 Dataset Creation Method

1. Start with curated transfer, representation, and critical-thinking prompts — **realized as
   `hope_prompt_bank.jsonl`** (`RAG_upgrade_plan.md` Phase 6): ≥1,000 prompts generated from
   the enriched store (KI from `integration_links`, KT from `transfer_links`, CT from
   `ct_probes`, plus bridge diagnostics), each row carrying `prompt`, `concept_id`, `signal`,
   `difficulty`, `bloom_level`, `rubric_anchor`, optional `figure_id`.
2. Generate student answers at weak, **memorized**, partial, correct, and advanced levels —
   the memorized level is mandatory so the labels can discriminate recall from understanding.
3. Collect teacher ratings for KI, KT, CT, load, and persistence — **realized as
   `hope_gold_set.jsonl`**: ~300 stratified prompts × 4 answer levels ≈ 1,200 labeled answers,
   ≥2 raters (teacher + independent LLM judge with written rubric).
4. Use an offline LLM judge to propose labels and rationales.
5. Keep only examples where teacher and judge agree or expert resolves disagreement.
   **Calibration gate: Cohen's κ ≥ 0.6 per signal before any scaling**; prompts on which
   memorized and strong answers receive the same score are rewritten or dropped (target:
   ≥1 ordinal level of separation on ≥85% of gold items).
6. Add real learner logs and annotate the next-turn outcome.
7. Add delayed retention and transfer checks after 3, 7, and 21 days.

### 5.7 Covered Points

The HOPE dataset must cover:

- representation translation,
- analogy quality,
- near transfer,
- far transfer,
- critical edge-case reasoning,
- misconception correction,
- productive struggle,
- overconfidence,
- low-confidence correct reasoning,
- cognitive overload,
- hint dependency,
- delayed retention.

### 5.8 Five Dataset Examples

| Student text | Context | KI | KT | CT | Other labels |
|---|---|---:|---:|---:|---|
| "The parabola is steeper because a is larger, so y grows faster for the same x." | Quadratic graph | 3 | 2 | 2 | confidence_high |
| "Finding the zeroes of p(x) is the same as solving p(x) = 0, like the roots of the equation." | Linking polynomial zeroes with quadratic roots | 2 | 3 | 1 | transfer_valid |
| "If the discriminant is zero the formula gives one repeated root, but on the graph the parabola only touches the x-axis." | Edge case: equal roots | 2 | 2 | 3 | abstraction_high |
| "I tried the hint, but I think I should first identify what is given and what is asked." | Word problem solving | 1 | 1 | 2 | productive_struggle |
| "The equation and the graph are the same because both show how y changes when x changes." | Algebra representation | 3 | 1 | 2 | representation_translation |

---

## 6. Pedagogy Policy Engine Neural Network Architecture and Dataset

### 6.1 Purpose

The pedagogy policy engine chooses the next tutor move. In the prototype it should remain rule-based for safety. The neural model should first learn to imitate expert/rule policy traces, then later optimize long-term learning outcomes.

Action space (aligned with architecture §6.6):

- `EXPLAIN`,
- `VISUAL_ANALOGY` (serves a cropped textbook figure whose `addresses_gap` matches the learner),
- `WORKED_EXAMPLE`,
- `ANALOGOUS_EXAMPLE` (an instance of the matching `problem_schema` with different surface variables),
- `ISOMORPHIC_PRACTICE` (regenerated instance via `isomorphic_variables`),
- `SOCRATIC_COUNTEREXAMPLE`,
- `SOCRATIC_Q`,
- `QUIZ`,
- `GIVE_HINT` (hint_chain level k — never free-form),
- `FADING_HINT` (hint_chain level k+1; chain exhausted ⇒ switch action, never leak the answer),
- `TRANSFER_PROBLEM` (from `transfer_links`; near before far),
- `BRIDGE_RECAP` (gated Class-9 recap + diagnostic, architecture §6.8),
- `MISCONCEPTION_PROBE` (diagnostic_question first — the §10 probe→diagnose→correct order),
- `METACOGNITIVE_REFLECT` (from `metacognitive_prompts`, after success/struggle),
- `ENCOURAGE`,
- `REVIEW`,
- `REPRESENTATION_TRANSLATION` (driven by `integration_links` + visual assets).

> **`SOLVE_STUDENT_PROBLEM` is deliberately NOT in this list (2026-07-23).** The rule engine
> gained it (architecture §6.6 rule 4b, build plan Part 14) so the tutor can work a problem the
> student brought. This list is the **policy-shadow label space** — the classes the shadow
> model was trained on — and adding a label to it means retraining the shadow and re-running
> its eval, not editing prose. Until that happens the shadow simply cannot propose the action;
> it is logged-only, so the runtime is unaffected. **No dataset or model artifact changed in
> Part 14** — the exemplar dataset, splits, classifier bank, resolver, HOPE detectors and
> policy shadow are all untouched, and every number elsewhere in this report still stands.
>
> Worth recording for whoever does retrain it: on the audit's train/car probe the shadow
> preferred `EXPLAIN` (p=0.311) over the rule engine's `TRANSFER_PROBLEM` (p=0.2375) — the
> shadow was closer to right than the rules were, which is a point in favour of eventually
> giving it the new label rather than leaving this to rule 4b alone.

### 6.2 Recommended Neural Architecture

First version: supervised action-ranker.

```text
learner state vector (incl. misconception statuses, hint-chain position,
                      bridge-prerequisite mastery, rolling HOPE scores)
concept features (incl. card-level difficulty, transfer/integration link availability)
cognitive analyzer scores
HOPE scores
retrieval confidence + ranking_trace terms
recent action history
-> feature normalization
-> MLP encoder
-> action ranking head
-> auxiliary outcome heads
```

Hard policy constraints (rule layer stays active, architecture §13 Rules 8–12): probe before
correct for active misconceptions; bridge gate by prerequisite mastery/ZPD; hints only from the
precomputed `hint_chain`, one level at a time; responses composed only from the evidence
manifest.

Outputs:

- probability for each pedagogical action,
- expected next-turn correctness,
- expected confusion reduction,
- expected mastery gain,
- risk of overload,
- uncertainty score.

Recommended shape:

- 80 to 200 structured input features,
- 2 to 4 dense layers,
- 128 to 512 hidden units,
- dropout 0.1 to 0.3,
- softmax action head,
- regression heads for reward components.

Stronger version:

- action ranking instead of only classification,
- transformer or GRU over last 5 turns,
- graph-aware concept embeddings,
- constrained policy layer to block unsafe/bad actions.

RL/PPO version:

- train only after supervised imitation works,
- use offline evaluation first,
- optimize delayed reward,
- keep rule constraints active.

### 6.3 Dataset Required

Minimum:

- 20,000 to 40,000 policy decision traces,
- each action should have at least 1,000 examples.

Strong prototype:

- 100,000 to 250,000 traces,
- each action should have 5,000 to 15,000 examples,
- 10,000 multi-turn sessions.

Production:

- 1M+ traces,
- delayed outcome labels,
- randomized or counterfactual action exploration under teacher-safe constraints.

### 6.4 Dataset Creation Method

1. Run the initial system with the rule-based policy.
2. Log state, action, response type, retrieval evidence, and outcome.
3. Ask teachers to review a sample of decisions and mark better alternatives.
4. Generate counterfactual candidates: "what if hint vs worked example?"
5. Label action quality as poor, acceptable, good, or best.
6. Train supervised action imitation.
7. Add outcome prediction heads.
8. Move to constrained offline RL only after enough delayed rewards exist.

### 6.5 Reward Design

Use multi-component reward:

- immediate correctness,
- reduction in confusion,
- lower hint dependency,
- improved next-turn explanation quality,
- mastery gain,
- transfer success,
- delayed retention,
- engagement maintained,
- overload avoided.

Do not optimize only for short-term correctness. That would overproduce hints and worked examples.

### 6.6 Covered Points

The policy dataset must cover:

- low mastery versus high mastery,
- high curiosity with low confusion,
- high confusion with low confidence,
- confident misconception (probe-first ordering),
- hint overuse (hint-chain escalation vs ENCOURAGE),
- readiness for transfer (near vs far gating),
- representation gap (visual asset vs verbal explanation),
- review after forgetting,
- prerequisite weakness — same-grade AND Class-9 bridge cases (activate vs skip the bridge),
- stuck-on-problem-type (ANALOGOUS_EXAMPLE vs re-EXPLAIN),
- post-success reflection (METACOGNITIVE_REFLECT vs immediately advancing),
- off-syllabus or uncertain retrieval.

### 6.7 Five Dataset Examples

| Learner state and message | Concept | Best action | Bad action to avoid | Reason |
|---|---|---|---|---|
| Mastery 0.25, high load. "I do not know where to start." | quadratic_equation_definition | WORKED_EXAMPLE | TRANSFER_PROBLEM | Needs scaffold before challenge |
| Mastery 0.62, asks "Why does the parabola open downward when a < 0?" | quadratic_zero_geometry | SOCRATIC_Q | LONG_EXPLAIN | Curiosity can be guided |
| Mastery 0.70, misconception active. "The sum of the zeroes is b/a." | quadratic_coefficients | SOCRATIC_COUNTEREXAMPLE | QUIZ | Misconception needs direct attack |
| Mastery 0.82, low hint dependency. "Can I try a harder one?" | substitution_method | TRANSFER_PROBLEM | REVIEW | Ready for transfer |
| Three hint requests without attempt. "Hint again please." | triangle_similarity_criteria_intro | ENCOURAGE | GIVE_HINT | Prevent hint gaming |
| New chapter opened; Class-9 prerequisite mastery unknown. "What is a quadratic equation?" | quadratic_equation_definition | BRIDGE_RECAP | EXPLAIN | Verify Class-9 recall (polynomials) before building on it |
| Mastery 0.45, stuck on a boat-speed word problem after one hint | pair_linear_equations_intro | ANALOGOUS_EXAMPLE | EXPLAIN | Same problem schema, different surface story — don't re-teach the concept |

---

## 7. Other Pending Models: Dataset and Architecture Plan

The architecture also implies several pending models beyond the named MiniLM, HOPE, and pedagogy policy models.

## 7.1 Knowledge Tracing / Learner State Model

### Purpose

Track mastery per concept over time and update learner state after every interaction.

### Recommended Architecture

Start with DKVMN-style knowledge tracing:

```text
concept id + item id + correctness + time + hint use
-> static key memory from curriculum graph
-> dynamic value memory per learner
-> mastery vector per concept
```

Interaction sources include two structured streams the runtime already produces
(architecture §6.4 write-back APIs): **bridge diagnostics** (`apply_bridge_result` — also the
cold-start mastery probe for new learners, covering `grade9_concept` nodes at cold-start 0.30)
and **misconception probes** (`apply_probe_result`). Both arrive pre-labeled with
concept/misconception IDs and outcomes, so knowledge tracing gets supervised interactions from
day one of rule-based operation.

Future target:

- graph-aware knowledge tracing,
- attention over recent interactions,
- calibration layer for item difficulty,
- misconception and representation coverage as auxiliary state.

### Dataset Required

Minimum:

- 50,000 learner interactions,
- 1,000+ learners or simulated learner profiles,
- 80 to 120 concepts.

Strong prototype:

- 250,000+ interactions,
- 5,000+ learners,
- item difficulty labels,
- hint usage and response time.

Production:

- 2M+ interactions,
- delayed recall checks,
- transfer checks,
- separate train/test by learner.

### Five Dataset Examples

| Interaction | Concept | Correct | Hint used | State update target |
|---|---|---:|---:|---|
| Solves the pair `x+y=5, x-y=1` by substitution without hint | substitution_method | 1 | 0 | mastery increases |
| Needs two hints for quadratic factorization | solving_by_factorization | 0 | 2 | hint_dependency increases |
| Correctly relates sum/product of zeroes to coefficients | quadratic_coefficients | 1 | 0 | mastery and confidence increase |
| Fails transfer from polynomial zeroes to quadratic-equation roots | roots_of_quadratic_equation | 0 | 1 | transfer_readiness decreases |
| Correct after 7-day cold recall | triangle_similarity_criteria_intro | 1 | 0 | cold_recall increases |

## 7.2 ZPD and Difficulty Calibrator

### Purpose

Estimate the next task difficulty that is challenging but not overwhelming.

### Recommended Architecture

- tabular MLP or gradient boosted baseline,
- inputs: mastery, response time, recent correctness, hint count, item difficulty (the store's per-chunk / per-exercise `difficulty` 1–9 tags; the store does not tag difficulty on concept cards), cognitive load,
- output: recommended difficulty band and overload risk.

### Dataset Required

Minimum:

- 20,000 task attempts with difficulty labels.

Strong prototype:

- 100,000 attempts.

Production:

- 500,000+ attempts with delayed outcome.

### Five Dataset Examples

| Learner state | Task difficulty | Outcome | Label |
|---|---:|---|---|
| Mastery 0.30, high load, failed previous two | 0.75 | failed | too_hard |
| Mastery 0.65, medium load, correct with one hint | 0.62 | partial success | good_zpd |
| Mastery 0.90, low load, instant correct | 0.35 | easy success | too_easy |
| Mastery 0.55, curious, no hints | 0.60 | correct after effort | good_zpd |
| Mastery 0.48, high frustration, long latency | 0.70 | abandoned | too_hard |

## 7.3 Grounding and Leakage Guard

### Purpose

Check whether generated responses are supported by retrieved NCERT evidence and whether hints leak full answers.

The training pairs come largely for free from the runtime: every response carries its
**evidence provenance manifest** (architecture §6.7), so `(response, manifest)` pairs with
automated claim-coverage checks bootstrap the `grounded/unsupported` labels; and every hint is
served from a precomputed `hint_chain` whose hard rule is "no hint states the final answer", so
chain-violations provide the `answer_leak` class. The runtime **bundle cohesion check**
(structural always-on + LLM self-check on ≥3-source bundles) supplies a third label stream:
incoherent-bundle examples.

### Recommended Architecture

Start with structured judge rules plus retrieval overlap. Later train a small classifier using MiniLM embeddings of response plus evidence.

```text
response text + retrieved chunks + intended action
-> MiniLM pair features
-> classifier
-> supported / unsupported / answer_leak / safe_hint
```

### Dataset Required

Minimum:

- 10,000 response-evidence pairs.

Strong prototype:

- 50,000 pairs.

Production:

- 200,000+ pairs, including adversarial unsupported explanations.

### Five Dataset Examples

| Tutor response behavior | Evidence available | Intended action | Label |
|---|---|---|---|
| Explains zeroes of a quadratic using the retrieved NCERT chunk | quadratic zeroes chunk | EXPLAIN | grounded |
| Gives the final answer during the first hint | Problem statement only | GIVE_HINT | answer_leak |
| Mentions a syllabus concept not present in retrieval | unrelated chunk | EXPLAIN | unsupported |
| Asks a guiding question without revealing the solution | relevant chunk | SOCRATIC_Q | safe |
| Uses the wrong formula for the sum of an AP | AP chunk | WORKED_EXAMPLE | unsupported |

## 7.4 Misconception State Tracker

### Purpose

Maintain active, weakening, resolved, or recurring misconception states per concept.

### Recommended Architecture

- sequence model or state machine plus classifier,
- inputs: misconception clue score, **diagnostic probe outcomes** (`apply_probe_result`), correctness, explanation quality, repeated errors,
- output: misconception status and confidence.

The rule-based v1 transitions are fixed (architecture §10): diagnostic wrong → stay `active`
(confidence ↑); diagnostic right → `active → weakening`; 2 consecutive successes spaced across
sessions → `weakening → resolved`; later failure → `resolved → recurring` (priority-boosted in
retrieval). Probe outcomes are always collected **before** correction is shown
(probe → diagnose → correct ordering), which keeps the labels uncontaminated by the
correction itself. The neural tracker later learns soft versions of these transitions from the
logged sequences.

### Dataset Required

Minimum:

- 10,000 misconception-labeled turns.

Strong prototype:

- 50,000 turns across at least 50 misconception families.

Production:

- 200,000+ turns with longitudinal resolution labels.

### Five Dataset Examples

| Student pattern | Misconception | Previous status | New status | Reason |
|---|---|---|---|---|
| Repeats "the degree equals the number of terms" after correction | degree_equals_number_of_terms | active | active | Persistent |
| Explains why a linear polynomial has exactly one zero | line_can_have_two_zeroes | active | weakening | Corrected reasoning emerging |
| Reads zeroes off linear and cubic graphs, not just quadratics | only_for_quadratics | weakening | resolved | Generalised beyond quadratics |
| Correct answer but still says "every quadratic has two real zeroes" | quadratic_always_has_two_real_zeroes | active | active | Surface correctness only |
| Same "sum is b/a" error returns after 14 days | sum_is_b_over_a | resolved | recurring | Delayed relapse |

## 7.5 Response Time and Engagement Predictor

### Purpose

Use response latency and interaction patterns to estimate cognitive effort, disengagement, and frustration risk.

### Recommended Architecture

- simple calibrated regression first,
- later MLP over time features and learner state,
- separate reading time from cognitive time where possible.

### Dataset Required

Minimum:

- 20,000 turns with timestamps.

Strong prototype:

- 100,000 timestamped turns.

Production:

- 1M+ timestamped interactions across devices and learner profiles.

### Five Dataset Examples

| Pattern | State | Label | Use |
|---|---|---|---|
| Long delay, correct explanation | high effort | productive_struggle | Continue challenge |
| Long delay, blank answer | high load | overload_risk | Scaffold |
| Fast repeated hint clicks | low effort | hint_dependency | Encourage attempt |
| Normal delay, self-correction | engaged | self_monitoring | Ask guided question |
| Very short wrong answers repeated | disengaged | frustration_or_low_effort | Switch action |

---

## 8. Dataset Creation Roadmap

### Phase 1: Curriculum and Exemplar Foundation

Duration: 2 to 4 weeks.

Deliverables:

- concept graph for Class 10 Maths — **already built** (108 concepts, 16 chapters in the RAG store),
- concept anchor texts — **already built** (`concepts.json`: name, summary, aliases, prerequisites, representations, misconceptions),
- misconception taxonomy — **seeded** from the per-concept misconceptions already in the graph,
- representation taxonomy — **seeded** (the 8 store types: symbolic, verbal, graphical, diagrammatic, algebraic, tabular, numerical, flowchart),
- **store v2 enrichment** (per `RAG_upgrade_plan.md` Phases 0–4): concept difficulty,
  transfer/integration links, CT probes, metacognitive prompts, misconception
  `why_wrong`/`correct_idea`/`diagnostic_question`, problem schemas + hint chains, figure
  crops with representation semantics, Class-9 bridge nodes, 0 dangling prerequisites —
  gated by the coverage scorecard,
- `hope_prompt_bank.jsonl` (≥1,000 prompts) + `hope_gold_set.jsonl` (κ ≥ 0.6 gate) —
  `RAG_upgrade_plan.md` Phase 6,
- 10,000 MiniLM exemplar examples,
- 8,000 concept resolver examples (bootstrap anchors from `concepts.json`),
- 12,000 retrieval relevance pairs (bootstrap from the 709 grounded chunks in `chunks.jsonl`
  plus the v2 `figure_caption` / `bridge_recap` chunks).

### Phase 2: Cognitive and HOPE Labels

Duration: 4 to 8 weeks.

Deliverables:

- 25,000 to 60,000 cognitive analyzer labels,
- 25,000 to 60,000 HOPE detector labels,
- teacher-reviewed rubric,
- inter-annotator agreement report,
- validation set with difficult mixed utterances.

### Phase 3: Policy Trace Logging

Duration: begins immediately after prototype.

Deliverables:

- rule policy decisions logged,
- outcome labels attached,
- teacher review of sampled actions,
- first 40,000 policy traces,
- action confusion matrix.

### Phase 4: Neural Policy and Delayed Outcomes

Duration: after real usage begins.

Deliverables:

- 100,000+ policy traces,
- delayed retention checks,
- transfer checks,
- supervised action-ranker,
- offline policy evaluation,
- constrained PPO only after stable imitation learning.

---

## 9. Annotation Rubrics

### 9.1 Cognitive Signal Rubric

Use multi-label scoring:

- 0.00 to 0.20: absent,
- 0.21 to 0.40: weak,
- 0.41 to 0.70: moderate,
- 0.71 to 1.00: strong.

Annotators should label all signals present. They should not force a single intent.

### 9.2 HOPE Rubric

KI:

- 0: no connection,
- 1: mentions another idea but does not connect,
- 2: partially connects concepts or representations,
- 3: clearly integrates concepts or representations.

KT:

- 0: no transfer,
- 1: surface analogy only,
- 2: near transfer with partial correctness,
- 3: valid transfer to a new context.

CT:

- 0: no reasoning,
- 1: simple why/how question,
- 2: causal reasoning or error checking,
- 3: edge-case reasoning, counterexample, or assumption testing.

Mandatory discriminations the rubric must enforce (calibrated on `hope_gold_set.jsonl`,
κ ≥ 0.6 per signal before any scaling):

- **memorized answer vs representation translation** (KI) — restating the formula scores 0–1
  even when correct; mapping between symbolic and graphical forms scores 2–3;
- **surface analogy vs structural transfer** (KT) — "this looks like that" scores 1;
  carrying the method to a new context with correct correspondence scores 2–3;
- **curiosity vs genuine critical evaluation** (CT) — an interested "why?" scores 1;
  testing an assumption or producing an edge case scores 2–3.

Prompts on which memorized and strong answers receive the same score are rewritten or dropped
(target: ≥1 ordinal level of separation on ≥85% of gold items).

### 9.3 Pedagogy Policy Rubric

Action quality:

- 0: harmful or wrong,
- 1: acceptable but weak,
- 2: good,
- 3: best available action.

Annotators should also record why the action was chosen:

- mastery gap,
- misconception,
- high load,
- transfer readiness,
- representation gap,
- hint dependency,
- retention need.

---

## 10. Quality and Evaluation Plan

### MiniLM Exemplar Classifier

Metrics:

- per-label precision, recall, F1,
- macro F1,
- calibration error,
- hard-negative false positive rate.

Acceptance target:

- macro F1 above 0.80 for strong prototype,
- recall above 0.85 for confusion, misconception clue, and hint request.

### Concept Resolver

Metrics:

- top-1 accuracy,
- top-3 accuracy,
- primary concept accuracy,
- secondary concept recall,
- ambiguous-query accuracy.

Acceptance target:

- top-1 above 0.82,
- top-3 above 0.93.

### Retrieval

Metrics:

- recall at 5,
- nDCG at 10,
- mean reciprocal rank,
- off-syllabus rejection accuracy.

Acceptance target:

- recall at 5 above 0.90 for direct concept queries.

### HOPE Detectors

Metrics:

- macro F1 for ordinal buckets,
- Spearman correlation with teacher scores,
- calibration error,
- trajectory-level prediction accuracy.

Acceptance target:

- Spearman above 0.65 initially,
- above 0.75 after real logs.

### Pedagogy Policy

Metrics:

- top-1 action agreement,
- top-3 action agreement,
- action quality score,
- offline estimated reward,
- safety override rate.

Acceptance target:

- top-3 agreement above 0.85,
- no increase in overload or answer leakage.

### Grounding, Ordering, and Bridge Quality (runtime/store-side gates, from `RAG_upgrade_plan.md` §4b)

Build-time verifiable:

- evidence-grounding rate: 100% of responses carry a valid manifest (all IDs exist in the
  store); ≥95% claim coverage on a 50-response audit,
- misconception ordering compliance: `why_wrong`/`correct_idea` never retrieved before the
  diagnostic for `active` misconceptions — 100% (automated test),
- hint answer-leak rate: 0 hints containing the final answer (regex + sample audit),
- false off-syllabus rate: ≤2% of generated transfer links/probes reference content outside
  NCERT Class 9–10 scope (100-sample manual audit).

Pilot-phase (defined now, measured with real learners):

- bridge usefulness: 40–80% of activated bridges have a failed diagnostic (below = over-bridging, above = gate too lax),
- misconception reduction: % of `active` misconceptions reaching `resolved` within 3 sessions of first probe,
- retention lift: 3/7/21-day delayed-recall checks vs non-bridged concepts.

---

## 11. Final Recommendation

The dataset should not be created as one large generic chat corpus. It should be created as joined datasets around the learning loop:

```text
student utterance
-> MiniLM signal/concept/retrieval datasets
-> cognitive and HOPE labels
-> learner state update labels
-> pedagogy action traces
-> response quality labels
-> delayed retention and transfer labels
```

For the first serious prototype, target approximately:

- 30,000 MiniLM signal/concept examples,
- 50,000 retrieval relevance pairs,
- 60,000 HOPE-labeled turns,
- 100,000 policy traces,
- 250,000 knowledge-tracing interactions.

For an MVP, the system can begin with roughly one third of those numbers if rules remain active and neural policy is used only as a recommendation layer.

### Document alignment

This report is one of three documents kept in lockstep:

1. **`learner_cognitive_state_architecture.md`** — defines *what* the system models (learner
   state, curriculum graph schema v2, bridge layer §6.8, schemas/hints/metacognition §6.9, the
   7-term retrieval contract and provenance manifest §6.7, misconception state machine §10,
   policy rules 1–12).
2. **`RAG_upgrade_plan.md`** — defines *how the store gets there* (Phases 0–6 with coverage
   scorecard §4a and quality gates §4b).
3. **This report** — defines *what data trains the models* against those exact schemas: the
   turn schema (Sec. 2.1) persists the runtime provenance manifest verbatim; the action space
   (Sec. 6.1) matches architecture §6.6 one-to-one; HOPE bootstrapping (Sec. 5.6) consumes the
   plan's Phase 6 artifacts with the same κ ≥ 0.6 gate; and the store-side quality gates
   (Sec. 10) are the plan's §4b criteria.

**Voice rig (build plan Part 10) adds no models or datasets.** The Windows hybrid voice
pipeline puts STT/TTS in the cloud (Google Cloud Speech-to-Text forced en-US; Cloud TTS
`en-IN-Chirp3-HD-Achernar`) and leaves the brain unchanged, so the model inventory and every
dataset/metric in this report are unaffected. The only runtime-generation change is pacing
discipline (action-aware spoken budget, deliver-don't-announce), which alters prompt/budget,
not any trained model — see architecture §21.

### Part 12 addendum (2026-07-15) — no new trained model; a grader-eval dataset only

The EXPLAIN/PRACTICE/TEST mode layer (Part 12) added **no new neural model and no new
training dataset**. TEST-mode quiz items are **generated at serve time** by Gemini, not drawn
from a stored bank: a store audit found **zero gradeable stored answers** (0/245
`problem_schema` instances carry `expected_answer`; 0/108 concepts have ≥5 schemas), so the
planned `build_quiz_bank.py` derivation was designed away. The only new labeled data is the
**grader-eval set** behind `eval/grader_eval.py` (realistic child answers per item type —
correct/partial/wrong/misconception-matching/non-attempt), used to gate the deterministic
`math_grade` floor (26/26; **zero non-attempts graded wrong**), not to train anything. The
existing trained models (classifier heads, resolver, HOPE detectors) are untouched.

Any future change to one document must be propagated to the others (this report, the
architecture doc, the RAG upgrade plan, and the build plan that tracks execution status).

### P0 evidence-integrity addendum (2026-08-12)

P0 adds no trained model, training dataset, RL/bandit/BKT/IRT component, learning-style label,
per-turn pedagogy evaluator, or default post-generation LLM judge. The normal model topology
remains one perception call and one response-generation call. Existing rubric grading is used
only when deterministic `math_grade` defers and can remain parallel with perception.

The new evaluation artifacts are executable code, not training data: 50 human-checkable item
verification judgments measured 50/50 agreement; the 306-row learning log regression harness
reproduces the duplicate-reply, quadratic-contradiction, non-attempt, and legacy QUIZ failures.
Deterministic safety/nonsense gates measured 20/20 and 9/9 recall respectively with zero
learning false-gates. These measurements do not change any historical model metric.
# Baseline Split contract impact (2026-08-14)

Issue 13 adds lifecycle contracts and a transactional state seam only. It changes no
dataset, label space, split, model artifact, prompt, model client, inference path, or
measured model result. Evidence-derived learning fields remain protected behind the
existing evidence writer, so the dataset/model architecture and all reported counts
remain unchanged.

Issue 14 activates coordinator routing with the complete existing Turn behind a temporary
in-process adapter. It adds no model call, client construction, prompt, schema, model artifact,
training/evaluation row, label, retrieval index, or network boundary. Immutable Turn Input
wrapping and typed result serialization are architecture-only work; every model boundary and
all reported dataset/model measurements remain unchanged.
## Interaction Control extraction checkpoint (2026-08-14)

Session admission, non-learning routing, topic continuity/redirection, mode-stop
interaction, conversation continuity, and termination now sit behind one typed Feature
Module Interface. Existing deterministic gates, Gemini perception routing port, persona
generation port, and scripted safety/farewell behavior are reused without changing a
prompt-of-record, model choice, dataset, split, label, artifact, or reported evaluation
number. Learning decisions continue into the migration adapter with the already-derived
analysis observation.
