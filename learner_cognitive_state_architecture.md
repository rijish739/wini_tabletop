# Learner Cognitive State–Based Architecture

## 1. Purpose

This document defines the **restructured prototype architecture** for the Wini pedagogical system when the central design goal is no longer “classify user intent,” but instead **model the student’s cognitive state during learning**.

The architecture is designed for **Class 10 Maths + Science** and is optimized for the following question:

> What does the student currently understand, misunderstand, feel, and attempt to do next?

This is a **pedagogy-first architecture**. It treats student messages as evidence of cognitive activity rather than as a request to one of a few chatbot intents.

### 1.1 Implementation status and companion documents (updated 2026-06-10)

The current implementation scope is **Class 10 Mathematics only** (NCERT, 16 chapter documents,
108 concepts, 709 grounded chunks in `rag_store/`). Science is a later extension; everything in
this document is written so a Science corpus can attach without schema change.

This document is the source of truth for *what* the system models. Two companion documents
derive from it and are kept in lockstep:

- **`RAG_upgrade_plan.md`** — the phased plan that upgrades the RAG store to carry every
  structure this architecture requires (concept enrichment, problem schemas, hint chains,
  figure crops, Class-9 bridges, learner-state-aware retrieval, evidence provenance, HOPE
  calibration). Where this document says a structure "should" exist, that plan says how it is
  built and verified.
- **`model_dataset_architecture_report.md`** — the dataset and neural-model plan that trains
  the components (MiniLM classifiers, HOPE detectors, pedagogy policy, knowledge tracing)
  against the schemas defined here.

> **Audit RESOLVED (2026-07-23): `BRAIN_ARCHITECTURE_AUDIT.md`.** A device-verified audit of
> this document against the deployed code found 16 defects, including 8 places where the code
> and this document disagreed. **All 16 are fixed and verified on `winipi5`**; the contract
> decisions the audit deferred to this document have been made here, in these sections:
>
> - **§6.1** — the deterministic `detect_student_problem` cue is now this layer's second live
>   responsibility, and the note there settles which layer owns signals after Part 11.
> - **§6.4** — the four specified-but-unimplemented per-concept fields now have contracts and
>   APIs; measured vs. cold-start mastery is an explicit distinction; flags decay;
>   `served_items` is cleared at session start.
> - **§6.6** — `SOLVE_STUDENT_PROBLEM` added, with rule 4b placed above the transfer rule.
> - **§6.7** — the grounding contract is split into `manifest_only` / `method_only`, and the
>   missing relevance floor / abstention path is specified.
>
> Execution status and measured results: `complete_architecture_build_plan.md` Part 14.
> Work log and gotchas: `rag_memory.md`.

Where this document names store objects, it uses the **real store schema**: concept IDs are
chapter-namespaced (`jemh104__discriminant_nature_of_roots`), chunk IDs follow
`<doc_id>::page_<NNN>::chunk_<NNN>` (or `::summary`), concept cards carry `summary` and
`aliases` (not `description`/`vocabulary` — `vocabulary` is added as a separate enrichment
field), and per-chunk concept tags are `concept_ids` + `concept_scores`.

---

## 2. Design Goals

1. **Represent cognition, not just intent**  
   Student input must update mastery, confusion, confidence, curiosity, load, and misconception state.

2. **Preserve pedagogical meaning**  
   A student can ask, explain, answer, challenge, compare, or transfer knowledge in one utterance. The system must capture all of that.

3. **Teach like a tutor, not a router**  
   The system should decide whether to explain, quiz, hint, challenge, revise, or redirect based on learner state.

4. **Ground everything in curriculum structure**  
   Concepts, prerequisites, representations, and misconceptions must come from the curriculum graph and NCERT-aligned content.

5. **Track changes over time**  
   The system must persist learner state across turns and sessions.

6. **Support weak, noisy, and incomplete student expressions**  
   Students often speak in fragments, examples, questions, or analogies. The architecture must remain robust under that ambiguity.

---

## 3. Core Architectural Shift

### Old architecture mindset

```text
Student Message → Intent Classifier → Concept Match → Tutor Action
```

This is insufficient because learning behavior is not a single intent.

### New architecture mindset

```text
Student Message → Cognitive Analyzer → Learner State Update → Pedagogical Planner → Response
```

The important object is not the intent label.
The important object is the **student state vector**.

---

## 4. High-Level System Overview

```text
┌───────────────────────────────────────────────────────────┐
│                        UI Layer                          │
│      Text chat interface for students / testers          │
└───────────────────────────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────┐
│                 Cognitive Input Processor                 │
│  - clean text                                            │
│  - detect topic shift                                    │
│  - detect question / answer / explanation / confusion    │
│  - preserve multiple signals from one utterance          │
└───────────────────────────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────┐
│                 Cognitive Analyzer Layer                  │
│  - confusion estimation                                  │
│  - curiosity estimation                                  │
│  - misconception estimation                              │
│  - transfer attempt detection                             │
│  - confidence / hesitation estimation                     │
│  - abstraction level estimation                           │
└───────────────────────────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────┐
│                     Learner State Model                   │
│  - mastery per concept                                   │
│  - misconception map                                     │
│  - confidence                                             │
│  - engagement                                             │
│  - cognitive load                                         │
│  - curiosity                                              │
│  - representation coverage                                │
└───────────────────────────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────┐
│                   Curriculum Knowledge Graph              │
│  - concept nodes (difficulty, vocabulary, applications)  │
│  - prerequisites (incl. Class-9 bridge nodes)            │
│  - representations (8 types) + visual assets (crops)     │
│  - common misconceptions (why_wrong / diagnostic)        │
│  - transfer links (near/far) + integration links (KI)    │
│  - problem schemas + worked examples + hint chains       │
│  - CT probes + metacognitive prompts                     │
└───────────────────────────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────┐
│                 Pedagogical Decision Engine               │
│  - explain                                               │
│  - quiz                                                  │
│  - hint                                                  │
│  - counterexample                                        │
│  - transfer                                              │
│  - review                                                │
│  - encourage                                             │
└───────────────────────────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────┐
│                        Retrieval Layer                    │
│  - NCERT grounding (text + figure crops)                 │
│  - learner-state-aware ranking (7-term score)            │
│  - misconception support (probe → diagnose → correct)    │
│  - schema / analogous worked-example retrieval            │
│  - bridge recap gating (Class-9 prerequisites)           │
│  - bundle cohesion check + evidence provenance manifest  │
└───────────────────────────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────┐
│                         Response Layer                   │
│  - explanation                                          │
│  - hint                                                 │
│  - question                                             │
│  - correction                                           │
│  - challenge                                           │
└───────────────────────────────────────────────────────────┘
```

---

## 5. Key Architectural Principle

The system must answer these questions in order:

1. **What concept is the student talking about?**
2. **What cognitive signals are present in the message?**
3. **What is the current state of the learner?**
4. **What pedagogical move is most appropriate now?**
5. **What evidence should be used to generate the response?**

This is a **state-driven teaching system**, not a single-pass classifier.

---

## 6. Main Components

## 6.1 Cognitive Input Processor

This layer prepares the student message for interpretation.

### Responsibilities

- Normalize the typed input.
- Preserve the full semantic content of the utterance.
- Detect whether the message contains:
  - a question
  - an answer attempt
  - an explanation
  - a confusion marker
  - a misconception clue
  - a transfer attempt
  - a topic shift
- Do not reduce the utterance to one label too early.
- Detect whether the student has brought **a problem instance of their own** to be
  worked out (`detect_student_problem`) — an equation or expression in the
  utterance, or an imperative solve/find/calculate verb together with numerals.
  This cue is **deterministic and model-free by design**, and it reports
  `directive` separately: an utterance that *commands* the tutor ("solve
  x²−5x+6=0") can never be an answer to a diagnostic the tutor asked, whereas a
  bare equation ("x = 5") usually is. See §6.6 rule 4b.

> **Who computes what (settled 2026-07-23).** Since the Part 11 pivot, the
> signal list, the multi-label scores and `candidate_concepts` above are produced
> by the Gemini perception call, **not** by `InputProcessor.process()`, which the
> runtime does not call. What this layer still owns, and what nothing else
> computes, is the deterministic pair: `normalize_input` and
> `detect_student_problem`. Routing decisions that must not depend on a model's
> judgement live here — rule 4b is the case in point, because the model correctly
> scores a student's word problem as a transfer attempt and that is precisely
> what used to misroute it.

### Why it matters

Students often produce mixed utterances, such as:

- “I think it is because resistance is high, but why does current reduce?”
- “Can I use the graph instead?”
- “This looks like the previous chapter.”

Each of these contains more than one signal.

---

## 6.2 Cognitive Analyzer Layer

This is the central replacement for the intent router.

> **Perception backend (Part 11; PROMOTED 2026-07-02).** *How* these signals are produced is
> feature-flagged (`PERCEPTION_BACKEND`). **Default is `gemini`**: ONE structured Gemini 2.5
> Flash call (`temperature=0`, enum-constrained `response_schema`) emits intent +
> `signal_scores` + `concept` in a single round-trip (`perception/gemini_perception.py`),
> injected as the analyzer's classifier+resolver so **this layer's contract and the
> `derive_*`/`apply_deltas` state math are unchanged** — Gemini changes *what is perceived*,
> not *how perception moves state*. The pre-promotion local MiniLM classifier + resolver were
> **retired from the runtime path at Stage 6 (2026-07-02)** — artifacts stay on disk as eval
> baselines, and a failed Gemini call degrades to gates + inherit-concept + neutral signals
> (a turn never hard-fails). The 6,062-token static block (taxonomy + signal definitions +
> concept catalog) is served from a Vertex context cache (`perception/vertex_cache.py`,
> sha-guarded). A model-free front door runs FIRST:
> deterministic SAFETY/NONSENSE gates and an 8-way **intent** router where **only `LEARNING`
> may move learner state** (mastery, misconception status, HOPE rolling averages, global EMAs)
> or trigger retrieval; every other intent gets a persona/scripted reply and leaves cognitive
> state untouched. `concept_id = INHERIT_CURRENT_CONCEPT` is the abstain sentinel (maps to the
> resolver's abstain branch). Concept resolution is **hybrid** (§5.5): the per-turn prompt
> carries top-8 MiniLM-similar `candidate_concepts` hints, and a deterministic **resolver
> cross-check** (`fuse_primary`) promotes the local resolver's confident top-1 only when it
> already sits in Gemini's {primary+secondaries} — never introducing a concept Gemini didn't
> list, never overriding INHERIT. Promotion evidence (2026-07-02): concept top-1/top-3
> **0.930/0.990** (vs 0.895/0.971 head baselines) on the frozen 999-row TEST split; signals
> gated by the **behavioral state-trajectory eval** (state moves through this layer's math,
> not label-F1) — Gemini 0.857/0.833 vs heads 0.607/0.500 on field-direction/must-fire-flags;
> intent macro-F1 1.0; SAFETY gate recall 1.0. Numbers live in
> `model_dataset_architecture_report.md`; measurement docs `eval/perception_eval_report.md` +
> `eval/behavioral_eval_report.md`. Design of record: `PART11_GEMINI_PERCEPTION_LAYER.md`.

### Responsibilities

Estimate the following signals from the student utterance:

- **confusion**
- **confidence**
- **curiosity**
- **misconception likelihood**
- **transfer attempt**
- **abstraction attempt**
- **self-correction**
- **explanation quality**
- **cognitive load**

### Output

The output is a **Student Cognitive Update**, not a single intent.

Example:

```json
{
  "confusion": 0.72,
  "confidence": 0.31,
  "curiosity": 0.84,
  "misconception_probability": 0.58,
  "transfer_attempt": 0.41,
  "abstraction_attempt": 0.66,
  "cognitive_load": 0.74,
  "self_correction": 0.12
}
```

### Meaning

The architecture does not need to decide immediately whether the student is “asking for help” or “answering a quiz.” It first learns **what mental activity is present**.

---

## 6.3 Concept Resolver

This layer determines which curriculum concept the utterance is about.

### Responsibilities

- Map the utterance to one or more concepts.
- Resolve concept names using semantic similarity.
- Use concept descriptions, examples, and vocabulary.
- Prefer foundational concepts when the student query is ambiguous.

### Output example

```json
{
  "concept_id": "jemh103__substitution_method",
  "concept_confidence": 0.88,
  "secondary_concepts": ["jemh103__pair_linear_equations_intro"],
  "resolution_reason": "student referenced substituting one variable and sign change while solving a pair"
}
```

### Important rule

Concept resolution must operate in **text space** using the concept-card text fields, not graph
embeddings. In the built store those fields are `name`, `summary`, `aliases`, and (after
enrichment) `vocabulary`; worked examples and applications live on linked graph nodes
(`example`, `application`, `problem_schema`) and may be pulled in as secondary anchor text.

---

## 6.4 Learner State Model

This is the authoritative memory of the student.

### Per-concept fields

Each concept should track:

- mastery
- misconception map **with status** (`active / weakening / resolved / recurring`, see §10)
- representation coverage (`representations_known` / `representations_missing`, over the 8 store types)
- recent correctness
- hint dependency **and current hint-chain position** (which hint level was last served)
- cold recall strength
- transfer readiness
- confidence trend
- last practiced time
- items already served this session (no-repeat set for chunks, probes, schemas, figures)

**Field contracts (specified 2026-07-23; before this they were named here and had no
implementation at all).**

| Field | API | Written by | Absent means |
|---|---|---|---|
| `cold_recall_strength` | `cold_recall_strength()` / `record_cold_recall()` | a graded outcome whose gap since `last_practiced` clears `COLD_RECALL_MIN_GAP_DAYS` (1 day) | `None` = **never measured**; not zero |
| `confidence_trend` | `confidence_trend()` | derived on read from the last `CONFIDENCE_TREND_WINDOW` (6) graded outcomes | `"unknown"` (fewer than 3 outcomes) |
| `transfer_readiness` | `transfer_readiness()` | derived: 0.6·mastery + 0.4·(1−hint_dependency), folded 0.7/0.3 with cold recall when measured | `0.0` when mastery was never measured |
| hint-chain position | `hint_chain_position()` | `record_hint_request` (`hints_used_current`, per problem) | `0` = chain untouched |
| `representations_known` | `representations_known()` | a confirmed `REPRESENTATION_TRANSLATION`, **or** a correct answer on a representation-bearing item | `[]` = nothing demonstrated yet |

**Measured vs. cold-start mastery.** `mastery()` substitutes `COLD_START_MASTERY`
(0.30) for a concept with no recorded value, so its return is *not* evidence that
anything was assessed. `has_measured_mastery()` is the distinction, and
`Snapshot.mastery_measured` / `resolve_band`'s reason string carry it downstream.
This matters more than it looks: on the live device 30 of 40 touched concept
states had no mastery value, so the ZPD band was cold-start for **75%** of them
while the ranking layer treated it as a measurement.

**Flags decay.** Per-concept flags are transient turn signals, not durable
knowledge (mastery and `misconception_states` carry that). Each is stamped in
`flag_seen` on every observation and expires after `FLAG_TTL_DAYS` (14). They
were previously append-only and never cleared, which made a single confused
moment a permanent condition on the parent dashboard.

**`served_items` is per-session and must be cleared at session start.**
`LearnerState.begin_session()` does this and the brain calls it on boot. The set
lives in the persisted state, so without an explicit reset it is not
session-scoped at all — it had reached 593 permanently-excluded chunks on the
device. Retrieval treats membership as a **penalty**, never an exclusion (§6.7).

Bridge concepts (Class-9 prerequisites, §6.8) are tracked in the same mastery map with a
cold-start mastery of **0.30**, exactly like unseen Class-10 concepts.

### Global learner fields

- overall engagement
- session mood proxy
- cognitive load
- frustration risk
- persistence across sessions
- response latency pattern
- rolling HOPE scores (recent KI / KT / CT averages — used by retrieval ranking, §6.7)

### Write-back APIs (state is updated by evidence, not only by inference)

The learner state is not write-only from the Cognitive Analyzer. Two structured outcome APIs
(implemented in `learner_state.py`) push results of served evidence back into the model:

- `apply_bridge_result(bridge_id, outcome)` — a Class-9 bridge diagnostic outcome updates the
  bridge concept's mastery (correct → +0.25 capped; wrong/partial → −0.10 and the revealed
  misconception set to `active`). This is what makes a bridge part of the cognitive model
  instead of a recap widget, and doubles as the cold-start mastery probe.
- `apply_probe_result(misconception_id, outcome)` — a misconception diagnostic outcome drives
  the §10 status machine and adjusts misconception confidence and concept mastery.
- `apply_item_result(item_id, outcome, concept_id, *, kind, hints_used)` — **third evidence
  API (Part 12).** A PRACTICE or TEST item outcome moves mastery by `ITEM_MASTERY_DELTA`,
  **hint-discounted** (a hinted solve gains less), and appends to `item_history` /
  `test_history`. Same non-attempt guardrail as the other two: a non-attempt moves nothing.
  `record_test_result(concept_id, ...)` closes a completed quiz set: it appends one
  `test_history` row (`{date, score, n, gate, threshold, item_results}`) and sets the
  concept's `mastery_gate` (`passed` on ≥ 0.8, else `failed_pending_retest`). Mastery still
  moves ONLY through these (now three) evidence APIs — the mode layer never writes state.

**Part 12 session-mode contracts (design of record `PART12_PEDAGOGY_MODES_PLAN.md`).** The
outer loop adds, without disturbing the inner loop: `session["mode"]` (EXPLAIN default,
byte-identical to pre-Part-12) resolved by a `ModeController` (`session_modes.py`) at ONE
dispatch point in `turn()` after `rules_decide`; the compact session structs `practice_plan`
(ladder position) and `test_state` (`{concept_id, n, idx, schema_cycle, items, results,
phase}`, capped at N); new per-concept state fields `item_history` / `test_history` /
`mastery_gate` / `concepts_due_for_review`; and new decision actions `COMPLETION_STEP`,
`ISOMORPHIC_PRACTICE`, `TEST_QUESTION`, `TEST_SUMMARY` (the TEST_* family are checks, not
teaching — `_mode_for_action` maps them to `probe`). A TEST is **concept-locked** for the
set's lifetime and its item **owns** `pending_check` (assessment precedes probe-first). TEST
items are **generated at serve time** (the store carries no stored answers — audited zero)
and graded by the deterministic `math_grade` floor under `judge_answer`. On a failed gate the
mode drops to a corrective EXPLAIN (Bloom mastery cycle); a later "test me" is a parallel-form
re-test. New spoken-pacing budgets for the five actions are in §21's contract table.

**Grading contract (closed loop, `tutor_loop`):** these write-back APIs fire only for a reply that
actually *attempts* the pending question. A **non-attempt** — an acknowledgment, an "I don't
understand / make it simpler / you are repeating yourself" plea, a fresh request, or a
counter-question — is classified `not_an_answer` and moves no state (no mastery delta, no
misconception activation, no HOPE score). This is enforced deterministically *before* the local
judge runs, because the small judge otherwise mislabels plain confusion as `wrong`. Two arming
rules follow from this: (1) only `bridge_diagnostic` and `misconception` evidence may arm the
graded `pending_check`; (2) **CT/KT/KI probes (`ct_probe`/`transfer_target`/`integration_target`)
are scored by the HOPE path only and are never written back as mastery/misconception diagnostics**
— a `ct_probe` carries a `question` field but must not be graded as a misconception.

### Example structure

```json
{
  "concept_states": {
    "jemh103__substitution_method": {
      "mastery": 0.67,
      "misconceptions": [
        {"id": "misconception::sign_error_on_transposition", "status": "active", "confidence": 0.78}
      ],
      "representations_known": ["symbolic", "verbal"],
      "representations_missing": ["graphical"],
      "hint_dependency": 0.42,
      "hint_chain_position": 1,
      "cold_recall": 0.58
    },
    "grade9::linear_equations_two_variables": {
      "mastery": 0.30,
      "source": "bridge_cold_start"
    }
  },
  "global": {
    "confidence": 0.49,
    "curiosity": 0.76,
    "cognitive_load": 0.64,
    "engagement": 0.81,
    "hope_rolling": {"ki": 0.41, "kt": 0.22, "ct": 0.55}
  }
}
```

### Why it matters

A mastery score alone is not enough. Two students may both have 0.8 mastery, but one may still hold a critical misconception.

---

## 6.5 Curriculum Knowledge Graph

This is the structure that defines what can be taught and in what order. It is realized as
`rag_store/concepts.json` + `graph.json` (built by `build_index.py`, enriched per
`RAG_upgrade_plan.md` Phases 1–4).

### Concept-card fields (store schema v2)

Each concept card carries:

- `concept_id` — chapter-namespaced (`jemh102__quadratic_coefficients`)
- `name`, `chapter_doc`, grade, subject
- `summary` — the anchor description (the store's name for "description")
- `aliases` + `vocabulary` — resolver anchor terms (aliases existed in v1; vocabulary is an enrichment field)
- `prerequisites` — same-grade concept IDs; cross-grade prerequisites point at `grade9_concept` nodes (§6.8); **no dangling references allowed**
- `representations` — subset of the 8 store types (§9)
- `misconceptions` — IDs of linked misconception nodes
- `applications` — promoted from the extracted application nodes
- `transfer_links` — **≥2 near + ≥1 far** per concept; near targets are validated concept IDs, far targets name an out-of-corpus domain with a `note` explaining the bridge (KT evidence)
- `integration_links` — concepts this one combines with, each tagged with the representation pair translated, e.g. `symbolic↔graphical` (KI evidence)
- `ct_probes` — 2–3 edge-case/"why" questions + 1 counterexample sketch, each with an expected-insight rubric line (CT evidence)
- `metacognitive_prompts` — 2 post-solve self-explanation prompts, tagged `when: after_success | after_struggle`
- `difficulty` — 1–9, anchored to the median difficulty of the concept's own chunks/exercises (same ZPD scale as item-level tags)

### Graph node types

| Node type | Carries | Pedagogical use |
|---|---|---|
| `chapter`, `concept` | card fields above | teaching-order map |
| `grade9_concept` | name, topic, `bridge_recap`, `diagnostic_question` + expected answer, `source: "generated"` | prior-knowledge bridges (§6.8) |
| `problem_schema` | `name` ("upstream/downstream speed problem"), `method_steps`, `instance_ids`, `isomorphic_variables`, `trap_steps` | analogous worked-example retrieval; isomorphic practice generation |
| `example`, `exercise` | text, `difficulty` 1–9, `bloom_level`, `pedagogical_role`, **`hint_chain`** (3 ordered hints: conceptual nudge → method recall → partial first step; never the answer) | practice selection by ZPD; faded hints |
| `misconception` | `text`, `why_wrong`, `correct_idea`, `diagnostic_question`, runtime `status` | probe → diagnose → correct loop (§10) |
| `ct_probe` | probe text + rubric anchor | challenge / critical-thinking actions |
| `figure`, `table`, `formula` | description, **`image_path` (cropped from the textbook page)**, `alt_text`, `supports_representation`, `disambiguates_misconceptions`, `good_for_questions`, `addresses_gap` | visual evidence for representation gaps and misconception refutation |
| `application`, `representation`, `external_concept` | as extracted | transfer + representation edges |

### Edge types

`contains`, `prerequisite_of`, `bridges_to` (grade-9 → grade-10), `represented_by`,
`has_misconception`, `transfers_to` (typed `near`/`far`), `integrates_with` (typed by
representation pair), `has_schema` / `instantiated_by`, `has_example`, `has_exercise`,
`has_formula`, `illustrated_by`, `probes`, `evidence_for`.

### Example node (real store schema)

```yaml
concept_id: jemh102__quadratic_coefficients
name: Zeroes and Coefficients of a Quadratic
chapter_doc: jemh102
summary: "If alpha and beta are zeroes of ax^2+bx+c, then alpha+beta = -b/a and alpha*beta = c/a."
aliases: [sum and product, quadratic coefficients]
difficulty: 5
prerequisites: [jemh102__quadratic_zero_geometry]
representations: [symbolic, algebraic]
misconceptions: [misconception::sum_is_b_over_a]
transfer_links:
  - {target: jemh104__quadratic_equation_definition, transfer_type: near,
     note: "Sum/product of roots reused when solving and constructing quadratic equations."}
  - {target: jemh105__nth_term_of_ap, transfer_type: near,
     note: "Coefficient-to-structure reading reappears in AP general terms."}
  - {target: projectile height-time models, transfer_type: far,
     note: "Quadratic models a thrown object's path; zeroes are launch/landing times."}
integration_links:
  - {with: jemh102__quadratic_zero_geometry, representations: symbolic↔graphical}
ct_probes:
  - {question: "What happens to the sum of zeroes if a doubles but b stays fixed?",
     expected_insight: "sum halves; ratios, not raw coefficients, carry the relation"}
metacognitive_prompts:
  - {when: after_success, prompt: "Explain in your own words why the sum is -b/a, as if to a Class 9 student."}
```

### Why it matters

The graph is not just a content index. It is the **teaching order map**, the **transfer map**
(KT), the **integration map** (KI), and the **probe bank** (CT) — one structure serving all
three HOPE signals plus prerequisite sequencing.

---

## 6.6 Pedagogical Decision Engine

This layer chooses what the tutor should do next.

### Available actions

- explain
- quiz
- hint (served from the exercise's precomputed `hint_chain`, level k)
- faded hint (hint level k+1 — never skipping to the answer)
- counterexample (from `ct_probes` / misconception `why_wrong`)
- transfer problem (from `transfer_links`, near before far)
- analogous worked example (from the matching `problem_schema`'s `instance_ids`)
- isomorphic practice (regenerate an instance via `isomorphic_variables`)
- bridge recap + bridge diagnostic (gated, §6.8)
- review
- encourage
- corrective explanation (only after a failed diagnostic — see §10 ordering)
- representation translation (using `integration_links` + visual assets)
- metacognitive reflection (from `metacognitive_prompts`, after success or after struggle)
- **solve the student's problem** (`SOLVE_STUDENT_PROBLEM`, added 2026-07-23) —
  work the instance THE STUDENT BROUGHT through to its final result, using the
  stored method

> **Why that last one had to be added.** Every other action in this catalog is
> served *from the store*: its object is a curriculum item. None of them has the
> **utterance itself** as its object. So a child who brought their own word
> problem fell through to the transfer rule — structurally a student-supplied
> problem *is* a transfer attempt — and `TRANSFER_PROBLEM`'s contract is "give
> them a NEW problem… do NOT solve it or give hints unless asked." The tutor
> answered "find the speeds" with a different problem and an explicit refusal to
> solve theirs. The signal was right; the catalog had no action to map it to.

**`SOLVE_STUDENT_PROBLEM` contract.** Retrieval need = `schema` (the manifest
supplies the METHOD). Grounding = `method_only` (§6.7). It must state the final
result explicitly and must **never** leave the last step for the student —
that behaviour belongs to `COMPLETION_STEP`, which is chosen deliberately, not
by running out of words. Spoken budget is derivation-sized (130 words /
9 sentences) rather than `EXPLAIN`'s 65/4.

### Rule order (deterministic rules outrank inferred ones)

Rule 4b, gated on §6.1's deterministic `detect_student_problem` cue, sits
**above** rule 5 (transfer readiness) and below rule 4 (load/frustration). A
*directive* problem also suppresses `learning_start` and counts as a
**non-attempt** for grading: a child who sets our pending question aside to ask
their own must not have that scored as a wrong answer (§13, "state moves only on
evidence").

### Decision inputs

The engine uses:

- learner state (full snapshot, §6.4)
- concept difficulty (now a concept-card field) and item difficulty
- mastery gap
- misconception **status** (`active/weakening/resolved/recurring`), not just likelihood
- cognitive load
- hint dependency and current hint-chain position
- bridge-prerequisite mastery (gating input, §6.8)
- rolling HOPE scores (recent KI/KT/CT)
- current goal of the session
- ZPD target range

### Decision examples and explicit contracts

If the student says they cannot **picture** the idea ("I cannot imagine this", "how does it
look?" — deterministic visualization cue, or a clarification plea carrying a representation
signal):

- **switch representation (`REPRESENTATION_TRANSLATION`, KI need): build one concrete
  everyday scene step by step, or walk the on-screen figure — never restate the definition
  in different words.** This override (`rule 1a-vis`) outranks the generic re-explain,
  because a re-worded definition still fails a learner whose gap is the mental image
  (2026-07-03 transcript regression: "I cannot imagine this" was answered with another
  textual definition of triangle sides).

If the student asks WHY this is worth learning, what it is for, or HOW something just shown
connects to the topic — or complains that their question was not answered (deterministic
purpose cue):

- **answer that exact question first (`WHY_IT_MATTERS`): state the connection explicitly or
  give one concrete real-life reason — never respond with a new problem, a definition, or bare
  encouragement.** This override (`rule 1w`) outranks the transfer/curiosity/frustration rules
  (2026-07-03 transcript regression: "how is this related to quadratic equation" drew a
  TRANSFER_PROBLEM, then two more deflections before the connection was finally stated).

If the student names a different topic (a bare label like "Natural numbers." with no graded
question open, or an explicit "i asked about X / teach me X / switch to X"):

- **honor the shift, never silently continue the old topic.** When perception grounds the new
  concept confidently the pipeline shifts as normal; when it abstains or resolves the *negated*
  mention, the deterministic handler grounds the requested span against the resolver anchors:
  confident match → switch and introduce; moderate → ask ("switch to {name}? yes/no",
  `pending_shift` consumed by a bare yes/no next turn); off-catalog → say so honestly and offer
  the nearest catalog topic. Raw concept ids are never spoken.

If the student explicitly signals they did not understand (an "I don't understand / make it
simpler / you keep repeating yourself" plea — deterministic clarification cue):

- **re-explain the same idea a different, simpler way; never answer a confused learner with a
  Socratic challenge, and never re-serve a probe they just said they could not follow.** This
  override (`rule 1b`) outranks the *inferred*-misconception probe, because the exemplar
  classifier sometimes misreads an overwhelmed plea as high curiosity/confidence and would
  otherwise route to `SOCRATIC_Q`.

If the student is confused but curious:

- explain with a simple representation
- then ask a guided question

If the student is over-relying on hints (`hint_dependency > 0.5`):

- do not serve the full worked example
- serve the next `hint_chain` level only, then encourage an independent attempt

If the student is ready for transfer:

- ask a near-transfer problem first (a `transfers_to: near` target)
- far-transfer later, only when source-concept mastery is high

If the student is stuck on a specific problem type:

- retrieve the matching `problem_schema` and serve an **analogous** worked example
  (different surface variables, same `method_steps`) — not a re-explanation of the concept

If the resolved concept has a weak/unknown Class-9 prerequisite:

- apply the bridge gate (§6.8): recap + diagnostic first, response second

If the student just solved successfully:

- consider a `metacognitive_prompt` (`when: after_success`) before moving on —
  self-explanation feeds the HOPE persistence signal and consolidates the win

---

## 6.7 Retrieval Layer

Retrieval is support, not control — and it is **learner-state-aware**, not only query-aware.
The ranking must answer "what does *this learner* need now?", not just "what matches the text?"

### Responsibilities

- Fetch NCERT-aligned evidence (text chunks AND cropped textbook visuals).
- Retrieve examples, analogies, definitions, problem schemas, probes, and bridge recaps.
- Ground explanations in curriculum material.
- Support misconception handling in the §10 order: probe → diagnose → correct.
- Emit an evidence provenance manifest with every response.

### Ranking contract (the 7-term score)

Each candidate evidence item is scored against the full learner snapshot:

```text
score = w1*semantic_relevance          (query ↔ chunk)
      + w2*difficulty_fit              (item difficulty vs learner ZPD band)
      + w3*role_match                  (pedagogical_role vs decided action)
      + w4*representation_gap_fit      (asset's representation ∈ representations_missing)
      + w5*misconception_priority      (item linked to an active/recurring misconception)
      + w6*hint_dependency_penalty     (suppress worked examples when hint_dependency > 0.5;
                                        prefer the next hint_chain level instead)
      + w7*hope_history_boost          (recent low KI → boost integration evidence;
                                        recent low KT → boost transfer evidence; etc.)
```

Weights are hand-set initially and logged per turn (`ranking_trace`) so they can later be tuned
from the append-only learning log (§12.2).

### Retrieval order

1. resolve concept
2. load the learner snapshot
3. apply the bridge gate (§6.8) — weak Class-9 prerequisite ⇒ prepend recap + diagnostic
4. determine learner need (pedagogy decision)
5. retrieve + rank evidence with the 7-term score
6. bundle cohesion check (below)
7. generate response **only from manifest items**
8. write outcomes back into learner state (§6.4 APIs)

This is the reverse of shallow query-answer systems.

### Bundle cohesion check (cost-gated)

Before generation, the retrieved bundle is validated:

- **Always-on structural checks:** every evidence item within 2 graph hops of the resolved
  concept; difficulty spread ≤ 3 bands; no `correct_idea` present without its misconception in
  the bundle (ordering guard).
- **LLM self-check only when the bundle mixes ≥ 3 source types** (e.g. bridge + concept +
  misconception): one cheap "do these contradict each other?" call that can drop the offending
  item. Simple bundles never pay the judge cost.

### Evidence provenance manifest

Every response carries (and the learning log persists) the exact evidence that justified it:

```json
{
  "evidence": [
    {"id": "jemh102::page_005::chunk_001", "type": "chunk", "why": "explains case (ii) equal roots"},
    {"id": "fig::jemh102::fig_2_4", "type": "figure",
     "image_path": "figure_crops/jemh102/fig_2_4.png", "why": "graphical representation gap"},
    {"id": "misconception::quadratic_always_has_two_real_zeroes", "type": "misconception",
     "why": "status=active, diagnostic served"}
  ],
  "bridge_ids": [],
  "schema_ids": [],
  "ranking_trace": {"w4_repr_gap": 0.31}
}
```

### Grounding contract (two cases, split 2026-07-23)

The manifest records which case applied, in `manifest.grounding`:

- **`manifest_only`** — *curriculum teaching turns*. The response layer may compose
  only from manifest items. Every generated sentence stays traceable to an exact
  chunk / figure / bridge / misconception node.
- **`method_only`** — *student-problem turns* (`SOLVE_STUDENT_PROBLEM`, §6.6). The
  manifest grounds the **method**; the numbers, names and quantities in the
  student's own utterance are authoritative for the **instance**, and the tutor
  does that arithmetic itself.

Stated as one absolute rule, this contract was **unenforceable and routinely
violated**. A student's own problem cannot be in the manifest, so "use ONLY the
evidence" and "answer this question" cannot both hold; the model resolved the
contradiction by ignoring the instruction, which worked by luck. Worse, the
learning log then recorded a manifest that had *not* produced the answer — and
§6.7's whole justification for the manifest is that it "provides the labeled
pairs the grounding-guard model trains on." Silently mislabelled pairs are worse
than no pairs. Splitting the contract makes the log honest about which rule was
in force.

When retrieval abstains (below), the prompt says so plainly instead of asserting
a grounding rule over an empty evidence set.

### Relevance floor and abstention

`w1_relevance` is normalised against the best item in the pool, so the top
candidate always scores 1.0 on it — **even when the whole pool is irrelevant**.
Combined with the hard concept-id pre-filter, a wrong concept resolution
therefore produced a confidently-ranked pack of wrong evidence with no signal
that anything had gone wrong, and there was no "retrieved nothing useful" path.

Ranking is therefore gated on an **absolute** floor (`MIN_ABS_RELEVANCE`, 0.28,
calibrated on the device: on-topic retrieval scores 0.36–0.63, a pool with no
real match tops out near 0.24). Candidates below it are ineligible; if none
qualify the ranker returns empty with `ranking_trace.abstained = true` and a
reason. The same principle governs two other selections that had no floor:

- the tier-3 **teaching visual** (`T9_VISUAL_MIN_RELEVANCE`, 0.30) — being tagged
  with the resolved concept is not evidence that a crop illustrates *this*
  utterance. Failing the floor means showing **no** visual: one that contradicts
  the speech is worse than none.
- the **prerequisite bridge** (`MIN_BRIDGE_RELEVANCE`, 0.20, §6.8) — the gate
  used to select on graph adjacency and mastery alone, which was both unstable
  and often irrelevant, and it arms a *graded* `pending_check`.

### No-repeat is a penalty, not an exclusion

`served_items` membership applies `w8_repeat_penalty`, it does not drop the
candidate. Dropping outright meant the best chunk for a concept could never be
seen twice — fatal for rule 1b, which re-explains the *same* idea and therefore
wants the *same* evidence — and it starved retrieval monotonically as the set
grew. As a penalty, a strong chunk resurfaces when nothing better exists.

---

## 6.8 Prior-Knowledge Bridge Layer (Class 9 → Class 10)

Nearly every NCERT Class 10 chapter opens by recalling Class-9 material ("In Class IX, you
have studied…"). The bridge layer turns that intro material into structured, gated,
state-updating objects instead of leaving it as untagged text.

### Structure

- `grade9_concept` nodes (`grade9::<slug>`): name, Class-9 topic, a 3–5 sentence
  `bridge_recap` generated **only from** the chapter's own intro chunks (flagged
  `source: "generated"`), one `diagnostic_question` + expected answer, and an edge
  `grade9_concept -[bridges_to]-> class10_concept`.
- Intro chunks are tagged `pedagogical_role: "bridge_recall"` and linked as `evidence_for`
  their bridge node.

### Gating contract (bridges are runtime policy objects, not décor)

- **Activate** only when the resolved Class-10 concept has a `bridges_to` predecessor whose
  mastery is unknown (cold start) or `< 0.6`, AND the bridge was not already served this session.
- **Skip** when bridge mastery `≥ 0.6` or the learner's ZPD band center `≥ 7` — advanced
  learners are not slowed by recaps.
- **Check, don't assume:** the diagnostic is always asked; inaccurate prior knowledge actively
  interferes with new learning, so recall is verified, never presumed.
- **Feedback loop:** the diagnostic outcome calls `apply_bridge_result` (§6.4) — correct
  raises bridge mastery and the lesson proceeds; wrong/partial lowers it, activates any
  revealed misconception, and the recap is taught *before* the new concept.

### Why it matters

Prior-knowledge activation is among the best-evidenced effects in learning science; it anchors
new content to existing schemas and improves retention and transfer. The bridge diagnostic is
also the cheapest cold-start mastery probe for a brand-new learner, and every bridge crossing
is a labeled near-transfer event for the HOPE KT signal.

---

## 6.9 Procedural Schemas, Hint Chains, and Metacognitive Prompts

Maths competence is procedural as well as conceptual: a student does not fail "linear
equations" in general — they fail *upstream/downstream boat-speed word problems* specifically.

### Problem schemas

`problem_schema` nodes cluster each concept's worked examples and exercises into problem
types, each carrying:

- `method_steps` — the ordered algorithmic steps for the problem class;
- `instance_ids` — the example/exercise nodes instantiating it;
- `isomorphic_variables` — which surface variables (names, numbers, contexts) can be swapped
  without changing mathematical structure or difficulty — the contract for generating fresh,
  difficulty-preserving practice;
- `trap_steps` — the steps where the linked misconceptions typically bite.

When a student is stuck on a problem, the tutor retrieves an **analogous** instance of the same
schema rather than re-explaining the concept.

### Hint chains (fading support)

Every exercise and every diagnostic question carries `hint_chain`: exactly 3 ordered hints —
(1) conceptual nudge, (2) formula/method recall, (3) partial first step — grounded in the
schema's `method_steps`, with a hard rule that **no hint states the final answer**. The chain
is what the "faded hint" action serves, it caps what the response layer may reveal per hint
request, and the learner's position in the chain is tracked in state (§6.4).

### Metacognitive prompts

Each concept carries 2 self-explanation prompts tagged `after_success` / `after_struggle`
("Explain the steps you just took to a Class 9 student", "What was the trickiest part?").
They are retrieved post-solve, support self-regulation, and feed the HOPE persistence and
cognitive-load signals.

---

## 7. Step-by-Step Runtime Flow

## Step 1: Receive student message

The UI sends the student text to the backend.

Example:

> “What if resistance becomes zero? Does current become infinite?”

---

## Step 2: Clean and preserve the utterance

The message is normalized, but meaning is not compressed too early.

The system preserves that the utterance may contain:

- a physics hypothesis
- a causal question
- a transfer attempt
- a misconception probe

---

## Step 3: Detect cognitive signals

The Cognitive Analyzer estimates:

- curiosity
- confusion
- abstraction
- misconception
- transfer
- cognitive load

In this example, the system may infer:

- high curiosity
- moderate transfer attempt
- low confusion
- potential critical thinking

---

## Step 4: Resolve the concept

The Concept Resolver maps the utterance to a curriculum concept, such as:

- Ohm’s law
- resistance
- current
- circuit behavior

The main target concept is selected, and secondary concepts are stored if needed.

---

## Step 5: Update learner state

The system updates concept-specific and global learner state.

Examples:

- increase curiosity score slightly
- increase transfer readiness
- mark possible misconception if the student asks about infinite current
- adjust confidence based on phrasing and prior performance

---

## Step 6: Evaluate pedagogical need

The pedagogy engine decides what the next best move is.

Possible outcomes:

- the student needs an explanation
- the student needs a hint
- the student needs a counterexample
- the student is ready for a quiz
- the student should be redirected to prerequisite material
- the student should be encouraged to think further

---

## Step 7: Retrieve supporting evidence

The retrieval layer gets the most relevant NCERT-aligned text, examples, figure crops, or
conceptual support, ranked by the 7-term learner-state-aware score (§6.7), gated by the
bridge contract (§6.8), and validated by the bundle cohesion check.

The response should be grounded in curriculum knowledge, not generic model memory — and every
piece of evidence used is recorded in the provenance manifest.

---

## Step 8: Generate pedagogically appropriate response

The response should match the student’s cognitive state.

Examples:

- if the student is confused → explain simply
- if the student is exploring → ask a guided question
- if the student is making a misconception → correct gently
- if the student is ready → challenge with a quiz

---

## Step 9: Update state after response

After the response, update the learner model again based on what happened.

Track:

- whether the student answered
- whether the student needed a hint
- whether the student self-corrected
- whether mastery improved
- whether the misconception weakened

---

## Step 10: Persist the session

Store:

- learner state
- turn history
- concept progress
- misconception status changes (the §10 state machine transitions)
- evidence used (the full provenance manifest, including figure and bridge IDs)
- pedagogical action chosen (with `ranking_trace` weights)
- bridge and probe outcomes (the `apply_bridge_result` / `apply_probe_result` calls)

This ensures the next session starts from the current state, not from zero.

---

## 8. State Transition Logic

The learner state should evolve as a closed loop.

### Example loop

```text
Student message
→ cognitive inference
→ learner state update
→ pedagogical action
→ student response
→ new state update
```

### Important rule

State updates must be incremental and reversible where appropriate.

The system should never assume one answer fully defines the learner.

---

## 9. Representation-Centric Learning

Each concept should be stored with multiple representations.

### The representation taxonomy (store schema — 8 types for Maths)

- symbolic
- verbal
- graphical
- diagrammatic
- algebraic
- tabular
- numerical
- flowchart

(`experimental` is Science-only and will be added when the Science corpus is ingested;
analogy phrasing is captured under `verbal`.)

### Visual assets carry representation semantics

Every cropped figure/table/formula in the store carries `supports_representation`,
`disambiguates_misconceptions`, `good_for_questions`, and `addresses_gap` (§6.5). A crop
without these fields cannot serve knowledge integration — the semantics are what let retrieval
pick the *right* visual for the *current* learner gap, e.g. the actual textbook parabola
(Fig. 2.5) for a learner whose `graphical` representation is missing.

### Why this matters

A learner may know the equation but not the graph, or the verbal meaning but not the symbol.

The system should use representation coverage to decide what to teach next. Representation
translation is exactly what the HOPE KI signal measures, and `integration_links` (§6.5) name
which concept pairs and representation pairs to translate between.

### Example policy

If symbolic is strong and graphical is weak:

- teach the graph — serving the textbook's own cropped figure, not a verbal description of it
- ask one of the figure's `good_for_questions` ("how many zeroes does this parabola show?")
- reward representation translation (raises the learner's KI score)

### When a visual is SHOWN (T9 display contract, updated 2026-07-20)

`tutor_loop._build_display` puts at most ONE crop per turn on the device (working-memory
limit). Three tiers, most pedagogy-specific first:

1. **Gated `figure` evidence** — a representation gap (`reps_missing ∩
   supports_representation`) or corrective disambiguation of an active misconception (§10).
2. **Incidental figure-caption evidence** on inherently visual actions
   (`REPRESENTATION_TRANSLATION` / `VISUAL_ANALOGY`).
3. **Teaching visual (default-on, added 2026-07-20)** — on any teaching turn (not TEST,
   and not a mode-controller-driven PRACTICE/TEST item). When the primary concept is
   known: the top-ranked image-bearing chunk **tagged with that concept**, else the
   concept's stored pool (`visuals_by_concept` — captions first, then formula crops),
   else any ranked image-bearing chunk; concept unknown: the top-ranked image-bearing
   chunk. (The concept-tagged preference matters because retrieval is only
   concept-filtered when resolution didn't abstain — without it, an off-concept but
   semantically similar caption can outrank the concept's own formula crop.) Added
   because the graph's `illustrated_by`/`has_formula` edges cover only 7/108 concepts
   (0/13 trigonometry), which left ordinary EXPLAIN turns text-only — "show, don't only
   tell" was unreachable in practice. TEST turns still never carry a figure (test
   integrity).

The generation prompt receives `figure_on_screen` and teaches THROUGH the visual ("look at
the figure on the screen").

**The `visuals_by_concept` index (updated 2026-07-20, formula links)** merges two sources:

- `figure_caption` chunks carrying `image_path` + `concept_ids` (244 rows, all chapters) —
  these stay FIRST in each concept's pool;
- **formula crops via `rag_store/formula_links.json`** — a derived artifact built by
  `link_formulas.py` that assigns same-chapter concepts to every formula node
  deterministically (0.6·page-inheritance from the chunk rows on the formula's page +
  0.4·name/alias token match, ±definitional/worked-example adjustments, threshold 0.35,
  ≤3 concepts per formula), plus the graph's original vision-emitted `has_formula` edges
  (jemh102 only). Formula rows follow the captions, ordered by link score. This closed
  the former store gap: concepts with ≥1 formula visual went **7/108 → 95/108** (every
  chapter covered; jemh108 trig 8/8). graph.json itself is untouched — the links file is
  merged at `TutorLoop.__init__`.

---

## 10. Misconception Modeling

A major requirement of the new architecture is explicit misconception tracking — both as
**enriched store objects** and as a **runtime state machine**.

### Misconception node fields (store schema v2)

Every misconception node carries, besides its `text`:

- `why_wrong` — what makes the belief incorrect;
- `correct_idea` — the replacement mental model;
- `diagnostic_question` — one question (with its own `hint_chain`) that reveals whether the
  misconception is held;
- optional links from visual assets that refute it (`disambiguates_misconceptions`, §6.5).

### Example misconception record (learner state)

```json
{
  "concept_id": "jemh102__linear_zero_geometry",
  "misconception": "misconception::line_can_have_two_zeroes",
  "confidence": 0.78,
  "last_observed": "2026-06-07T10:15:00Z",
  "status": "active"
}
```

### The status state machine (probe → diagnose → correct, never correction-first)

```text
suspected/active --diagnostic served, answered WRONG--> active (confidence ↑)
                                                        then retrieve why_wrong + correct_idea
                                                        + refuting figure crop
active --diagnostic answered RIGHT--> weakening
weakening --2 consecutive successes, spaced across sessions--> resolved
resolved --later failure--> recurring  (priority-boosted in retrieval ranking, §6.7 w5)
```

Hard ordering rule: for an `active` misconception the `diagnostic_question` is always retrieved
**before** `why_wrong`/`correct_idea`. The system probes first, diagnoses from the answer, and
only then corrects. Every probe outcome calls `apply_probe_result` (§6.4) so the status machine
and concept mastery move together.

### Why it matters

Students often appear correct on the surface while still carrying a broken mental model.

The system should not confuse:

- memorized answer
- with conceptual understanding

The `recurring` state exists precisely because misconceptions relapse: a "resolved" sign error
that returns after 14 days must outrank fresh content in retrieval priority.

---

## 11. Cognitive State Signals

The following signals should be estimated and persisted when possible.

### Core signals

- mastery
- confusion
- curiosity
- confidence
- cognitive load
- misconception probability
- transfer readiness
- abstraction level
- engagement
- self-correction tendency

### Example interpretation

A message like:

> “Why does this formula still work if the shape changes?”

may indicate:

- high abstraction attempt
- strong curiosity
- possible transfer
- good engagement

This is pedagogically valuable even if the student does not yet answer correctly.

---

## 12. Data Stores

## 12.1 Mutable learner state store

Stores the authoritative learner model.

Contents:

- mastery
- misconception map
- session state
- current concept
- ZPD level
- cognitive state summary

## 12.2 Append-only learning log

Stores every turn and the resulting pedagogical decision.

Contents:

- student message
- inferred cognitive state
- chosen tutor action
- retrieval evidence (the full provenance manifest: chunk/figure/bridge/misconception/schema IDs + `ranking_trace`)
- bridge diagnostic and misconception probe outcomes
- reward signals
- delayed retention data

This log is also the training source for the dataset plan
(`model_dataset_architecture_report.md`): policy traces, HOPE turn labels, knowledge-tracing
interactions, and grounding-guard pairs are all derived from it.

## 12.3 Transient context cache

Stores temporary conversation context.

Contents:

- recent turns
- rolling summary
- current local context window

This cache may be rebuilt from stored state.

---

## 13. Pedagogical Policy Rules

### Rule 1: Prefer understanding over classification

Do not force a message into a single intent if the message carries multiple learning signals.

### Rule 2: Use the simplest sufficient response

If a small hint works, do not produce a long explanation.

### Rule 3: Reward productive struggle

Slow but correct reasoning should not be treated as failure.

### Rule 4: Identify and attack misconceptions directly

If the learner reveals a false mental model, correct that model explicitly.

### Rule 5: Teach representations, not only facts

A concept should be taught in more than one form when needed.

### Rule 6: Sequence by prerequisites

Never jump to advanced concepts before foundational ones are ready.

### Rule 7: Adapt to the learner’s zone of proximal development

The task should be challenging but not overwhelming.

### Rule 8: Probe before correcting

For an active misconception, serve the diagnostic question first; `why_wrong` and
`correct_idea` come only after the answer reveals the broken model (§10). Correction-first
teaching robs the diagnosis and risks correcting a misconception the student never held.

### Rule 9: Gate bridges on learner state

Serve a Class-9 bridge recap only when the prerequisite's mastery is unknown or weak, and
always verify with the diagnostic (§6.8). Never assume recall; never slow a learner who has
already demonstrated it.

### Rule 10: Fade through the hint chain, never past it

Help escalates one `hint_chain` level at a time — nudge, then method, then partial first step.
No hint reveals the final answer; if the chain is exhausted, switch action (analogous worked
example or corrective explanation), don't leak.

### Rule 11: Prompt reflection after the work

After a successful solve (or a productive struggle), serve a metacognitive prompt (§6.9).
Self-explanation consolidates learning and feeds the persistence signal.

### Rule 12: Every response carries its evidence

A response may only be composed from items in its provenance manifest (§6.7). If the manifest
cannot support the claim, retrieve more or say less.

---

## 14. Example End-to-End Flow

### Student says

> “I can solve the equation, but I still do not understand why the graph bends like that.”

### The system infers

- equation mastery: moderate to high
- graph understanding: low
- representation gap: strong
- curiosity: high
- confusion: moderate

### The system decides

- do not give another equation drill
- explain graph representation
- translate equation to graph
- ask a small interpretive question

### Response strategy

1. acknowledge the student’s partial understanding
2. explain the graph representation
3. connect equation and graph
4. ask a follow-up question to check understanding

---

## 15. What This Architecture Replaces

This architecture replaces the idea that study behavior is best handled by:

- intent labels
- single-action routing
- keyword-driven classification
- shallow topic matching

It instead builds a **student model first** system.

---

## 16. What This Architecture Keeps

The following ideas are still valuable and should be retained:

- curriculum prerequisite graph
- mastery tracking
- fading hints
- ZPD calibration
- NCERT grounding
- HOPE-style learning metrics
- delayed retention logging
- session persistence

These are now organized around learner cognition rather than chatbot intent.

---

## 17. Out of Scope for This Prototype

The following are not required for this architecture document:

- voice / ASR / TTS (edges only; the **spoken pacing contract** they require IS in scope — see §21)
- turn-taking
- games
- storytelling
- student-facing camera/vision input (note: vision-model extraction of textbook pages and
  figure crops in the data pipeline IS in scope and already built)
- navigation
- pet behavior
- multi-modal embodiment
- on-device RL training
- ingesting the full Class-9 textbook (the bridge layer's `grade9_concept` nodes are designed
  so a future Class-9 ingest attaches without schema change)

---

## 18. Implementation Recommendation

The system should be implemented in this order:

1. Build the curriculum graph. — **Done** (v1: 108 concepts / 2,755 nodes; v2 enrichment per
   `RAG_upgrade_plan.md` Phases 0–4: concept difficulty, transfer/integration links, CT probes,
   metacognitive prompts, problem schemas, hint chains, misconception enrichment, figure
   crops, Class-9 bridges).
2. Define the learner state schema. — **Done in v1 form** (`learner_state.py`); v2 adds
   misconception statuses, hint-chain position, rolling HOPE scores, and the
   `apply_bridge_result` / `apply_probe_result` write-back APIs.
3. Implement the cognitive analyzer. — **Done** (`cognitive_analyzer/`, Part 3; report §3)
4. Implement concept resolution. — **Done** (`concept_resolver/`, Part 2; report §4.1)
5. Implement learner state updates. — **Done in rule form** (`learner_state.py` write-backs +
   the tutor-loop closed loop); neural knowledge tracing (report §7.1) awaits real logs.
6. Implement pedagogical decision rules. — **Done** (`tutor_loop.rules_decide` v3; the
   `policy_shadow/` neural suggester runs in shadow mode, report §6).
7. Add retrieval grounding. — **v1+v2 done** (7-term ranking + provenance manifest +
   cohesion check, `RAG_upgrade_plan.md` Phase 5); tutor loop adds a local MiniLM index + Qwen.
8. Add persistence. — **Done** (learner-state file + append-only `learning_log.jsonl`).
9. Add evaluation metrics. — coverage scorecard (18/18, 100%) + HOPE gold set κ ≥ 0.6 gate
   (Phase 6); **HOPE detectors built (Part 4)** scoring KI/KT/CT 0–3 with the
   strong-vs-memorized discrimination gate passing on all three signals.
10. Only then optimize for scale or deployment.

The neural HOPE detectors (Sec. 5 references) are realized in `hope_detector/`: a per-signal
ordinal head over MiniLM answer embeddings + alignment/length scalars. They feed the rolling
KI/KT/CT scores (§6.4 `hope_rolling`) consumed by the §6.7 ranking (w7).

---

## 19. Final Architectural Summary

The correct architecture for this prototype is:

```text
Student message
→ cognitive signal extraction
→ concept resolution
→ learner state update
→ pedagogy decision
→ grounded response
→ state persistence
```

That is the actual learning loop.

Not intent classification.
Not router-first chatbot design.

A learning system must model the learner.

---

## 20. Next Documents to Derive

From this architecture, the following documents exist or are planned:

**Already derived (kept in lockstep with this document):**

- `model_dataset_architecture_report.md` — datasets + neural architectures for every model named here
- `RAG_upgrade_plan.md` — the store upgrade plan realizing §6.5, §6.8, §6.9, the §6.7 ranking
  contract, and the evaluation gates

**Still to derive:**

- `learner_state_schema.md` (formalize §6.4 incl. the write-back APIs)
- `pedagogy_policy_rules.md` (formalize §13 Rules 1–12 as executable policy)
- `cognitive_signal_definitions.md`
- `session_persistence_spec.md`

---

## 21. Spoken pacing contract (voice runtime)

Voice I/O edges (ASR/TTS) remain out of scope as deployment concerns (§17), but speaking
to a child imposes a *cognition* contract that this document owns: short spoken turns must
not corrupt the learner model, and a turn must DELIVER its idea rather than announce it.
Implemented in `pacing/` and consumed by the Windows voice rig (build plan Part 10) and the
Jetson brain node (Part 9).

**State-channel discipline for spoken replies.** A spoken turn is triaged before the tutor
turn (`pacing/triage.py`) into one of: answer-current-prompt, hint_request, topic_shift, ack,
elaboration, unclear. Only **one** state channel may move per turn, and the §10/§13-rule-8
discipline still holds: deep state (mastery, misconception status, bridge mastery, HOPE)
moves ONLY through `pending_check` closure (`apply_probe_result`/`apply_bridge_result`); a
spoken reply that merely adds a side comment updates **soft** signals only. A pacing
micro-check (`session.pace.pending_micro_check`) is NOT a mastery check and can never move
deep state — it lives separately from `session.pending_check`. A yes/no answer that carries
extra reasoning closes the pace check and keeps the reasoning as soft evidence; a mid-turn
hint request routes to the existing hint chain; an ambiguous concept abstains/confirms rather
than silently switching topic.

**Action-aware spoken budget.** Spoken answers are capped to whole sentences within a word
budget that reflects the ACTUAL pedagogical action (not a pre-action guess): e.g.
`WORKED_EXAMPLE` = 60 words / 4 sentences with a `try_step` check, `SOCRATIC_Q` = 25 words /
1 sentence. The generator must deliver one complete atomic idea — if it uses an example it
must substitute the numbers and compute through to the result — and the closing micro-check
may only ask about content actually delivered in that reply (never "did you understand"
about something not shown). This is the contract that prevents the failure mode where a tight
budget makes the model announce an example and then ask if it was understood without ever
working it.

