# Wini — System Architecture Overview

> **Single entry point.** This document is the clean, end-to-end picture of the Wini
> pedagogical system and the **index** to every other architecture document. It does not
> restate the detailed contracts — it points to where each one lives. The four detailed
> documents below are kept in **lockstep** (see [Document map](#1-document-map) and
> `CLAUDE.md`); this overview sits *above* them and is updated whenever the system's
> external shape changes.
>
> **Scope:** NCERT **Class 10 Mathematics only** (16 chapter docs = 14 chapters + 2
> appendices, 108 concepts). Science is a planned extension that attaches without schema
> change. **All LLM calls use the local Qwen model only** (qwen2.5-3b-instruct via
> llama.cpp); all embeddings are local MiniLM (all-MiniLM-L6-v2). No Gemini/Vertex in the
> runtime brain.

---

## 1. Document map

Wini is described by a small set of documents, each with one job. Read this overview first,
then go to the document that owns the detail you need.

| Document | Role | Status |
|---|---|---|
| **This file** (`WINI_ARCHITECTURE.md`) | End-to-end picture + index to everything else | Living overview |
| [`learner_cognitive_state_architecture.md`](learner_cognitive_state_architecture.md) | **WHAT** the system models — schemas, signals, contracts (source of truth) | Lockstep #1 |
| [`RAG_upgrade_plan.md`](RAG_upgrade_plan.md) | **HOW** the store carries those structures — build/verify plan (executed) | Lockstep #2 |
| [`model_dataset_architecture_report.md`](model_dataset_architecture_report.md) | Datasets + neural models that realize the architecture | Lockstep #3 |
| [`complete_architecture_build_plan.md`](complete_architecture_build_plan.md) | Execution status of every Part (1–10) with measured results | Lockstep #4 |
| [`rag_memory.md`](rag_memory.md) | Append-only **work log** for store/runtime work; incidents & lessons | Work log |
| [`WINI_VOICE_STUDY_ARCHITECTURE.md`](WINI_VOICE_STUDY_ARCHITECTURE.md) | Voice-to-voice runtime (speech in → study core → speech out); Jetson as-built §12 | Voice spec + as-built |
| [`WINI_V2_ARCHITECTURE.md`](WINI_V2_ARCHITECTURE.md) | Legacy full-robot plan. **Study package obsolete**; retained only as the spec source for the speech stack (Layers A/C) | Legacy reference |

**Reference data (not architecture):** [`examples.md`](examples.md) (classifier exemplar
corpus + concept-ID tagging rules), [`dataset/curation_report.md`](dataset/curation_report.md)
(exemplar dataset curation stats), and the `rag_store/*.md` review/rubric artifacts.

**The lockstep rule (mandatory, from `CLAUDE.md`):** lockstep docs #1–#4 describe one system
and must stay consistent. Any behavior/schema change is propagated to all four in the same
work session, plus a `rag_memory.md` log entry. Never edit a measured number without
re-measuring it.

---

## 2. What Wini is

Wini is a **pedagogy-first tutoring system**. It does **not** classify a student message into
one chatbot intent and route it. Instead it models the student's **cognitive state** — what
they currently understand, misunderstand, feel, and are ready for — and chooses a teaching
move from that state. Every spoken or written reply is grounded in retrieved NCERT evidence
(a provenance manifest), never free model memory, and the loop closes: what the student says
next moves mastery, misconception status, hint position, and the rolling HOPE scores **by
evidence**, not by text inference.

The core shift, in one line:

```
OLD:  message → intent classifier → concept match → action
WINI: message → cognitive analyzer → learner-state update → pedagogy decision → grounded response → state write-back
```

> **Front door (Part 11, built 2026-07-01).** A thin router now sits *in front* of the cognitive
> analyzer without changing the shift above: deterministic **SAFETY/NONSENSE gates** run first
> (model-free, scripted replies), then an 8-way **intent** check where **only `LEARNING` enters
> the pipeline and moves state** — SOCIAL / META / OFF-DOMAIN / EMOTIONAL / SESSION-CONTROL get a
> warm persona reply and touch no cognitive state, and SAFETY raises a scripted reply + supervisor
> alert. SESSION-CONTROL additionally honors a **hard stop** (2026-07-03): an explicit goodbye or
> a second leave request ends the session with a *scripted* farewell (never the LLM — no
> "one more sum" retention) and the runners stop taking turns. Since the **Stage 4 promotion (2026-07-02)** perception IS Gemini: the intent +
> cognitive signals + concept all come from ONE structured Gemini 2.5 Flash call (static block
> served from a Vertex context cache; MiniLM candidate hints + a deterministic resolver
> cross-check on the concept pick); the state math downstream is unchanged. The local MiniLM
> heads were retired from the runtime path at Stage 6 (artifacts kept as eval baselines); a
> failed Gemini call degrades to gates + inherit-concept + neutral signals. Measured at
> promotion: concept top-1/top-3 0.930/0.990, behavioral signal eval PASS, intent 1.0, safety
> gates 1.0. Design of record:
> [`PART11_GEMINI_PERCEPTION_LAYER.md`](PART11_GEMINI_PERCEPTION_LAYER.md).

Details: [`learner_cognitive_state_architecture.md`](learner_cognitive_state_architecture.md) §3.

---

## 3. The total pipeline

One spoken (or typed) turn flows through three layers. Layer B (the study core) is the
system in this repo and is fully built; Layers A/C are the speech edges.

```
┌─ LAYER A — SPEECH IN ───────────────────────────────────────────────┐
│  mic → wakeword → VAD/endpoint → STT → utterance text                │
└──────────────────────────────│──────────────────────────────────────┘
                                ▼
┌─ LAYER B — STUDY CORE (BUILT) ──────────────────────────────────────┐
│  B0 Input Processor   normalize, preserve math                       │
│  B1 Cognitive Analyzer  MiniLM classifier + concept resolver         │
│                         → Student Cognitive Update (signals+concept) │
│  B2 Learner State     mastery · misconceptions(status) · hints · HOPE│
│  B3 Pedagogy Decision rules (v4) + policy-shadow → one action        │
│  B4 Retrieval         bridge gate · probe-first · 7-term rank ·      │
│                       cohesion check · provenance manifest           │
│  B5 Response          local Qwen, composed ONLY from the manifest    │
│  B6 Write-backs       probe/bridge results · HOPE score · flags      │
│  B7 Persistence       learner state · append-only learning log       │
└──────────────────────────────│──────────────────────────────────────┘
                                ▼
┌─ LAYER C — SPEECH OUT ──────────────────────────────────────────────┐
│  sentence splitter → TTS → speaker   (half-duplex: mic muted on TTS) │
└─────────────────────────────────────────────────────────────────────┘
```

The orchestrator is [`tutor_loop.py`](tutor_loop.py) (`TutorLoop.turn(text)`), which runs
B0–B7. Full per-box detail: [`WINI_VOICE_STUDY_ARCHITECTURE.md`](WINI_VOICE_STUDY_ARCHITECTURE.md) §4.

### Study-core invariants (the rules the pipeline never breaks)

1. **State moves on evidence, not text.** The analyzer (B1) writes only *soft* state (global
   EMA + concept *flags*). Mastery and misconception status move only through evidence-driven
   write-backs (`apply_probe_result` / `apply_bridge_result`) in B6.
2. **Probe before correcting.** For an active misconception the diagnostic question is served
   first; `why_wrong`/`correct_idea` only after the answer reveals the broken model.
3. **Bridges are gated.** A Class-9 prerequisite recap is served only when the prerequisite's
   mastery is unknown/weak, and always verified with a diagnostic.
4. **Hints fade, never leak.** Help escalates one `hint_chain` level at a time; no hint states
   the final answer. Chain exhausted ⇒ switch action.
5. **Every response carries its evidence.** B5 composes only from the B4 provenance manifest;
   every sentence traces to an exact chunk / figure / bridge / misconception node.

These are enforced in `learner_state.py`, `query.py`, and `tutor_loop.py`, and specified in
architecture §6, §10, and §13 (Rules 1–12).

---

## 4. The knowledge store (RAG, schema v2)

The Curriculum Knowledge Graph is `rag_store/` — not a flat index but the teaching-order map,
the transfer map (KT), the integration map (KI), and the probe bank (CT) in one structure.

- **108 concept cards** (`concepts.json`) — `summary`, `aliases`/`vocabulary`, `difficulty`
  (1–9), `prerequisites`, `representations` (8 types), `transfer_links` (≥2 near + ≥1 far),
  `integration_links` (KI), `ct_probes` (CT), `applications`, `metacognitive_prompts`.
- **Graph** (`graph.json`) — 3,562 nodes / 2,617 edges: concepts, `grade9_concept` bridges,
  `problem_schema` nodes (method steps + isomorphic variables + trap steps), examples/
  exercises with 3-step `hint_chain`, enriched `misconception` nodes (`why_wrong`,
  `correct_idea`, `diagnostic_question`), `ct_probe` nodes, cropped `figure`/`table`/`formula`
  assets with representation semantics.
- **Chunks** (`chunks.jsonl` + `vector.faiss`) — 1,017 vectors = 709 page + 244 figure-caption
  + 64 bridge-recap.
- **Quality gate:** `verify_store.py` scorecard — **18/18 metrics PASS, 100% attainment**.

The store was built/verified by the phased plan in
[`RAG_upgrade_plan.md`](RAG_upgrade_plan.md) (Phases 0–6); the full execution log with every
incident is in [`rag_memory.md`](rag_memory.md).

---

## 5. Models & build status (Parts 1–10)

Detailed results: [`complete_architecture_build_plan.md`](complete_architecture_build_plan.md).
Dataset/architecture rationale: [`model_dataset_architecture_report.md`](model_dataset_architecture_report.md).

| Part | Component | Module | Status / headline result |
|---|---|---|---|
| 1 | Cognitive classifier | `cognitive_classifier/` | ✅ MiniLM evidence+logreg+cues, 38 labels (incl. `acknowledgment`); test micro-F1 **0.83** / macro **0.69** (fixed-source rebuild 2026-06-19) |
| 2 | Concept resolver | `concept_resolver/` | ✅ MiniLM logreg, 108 concepts + ABSTAIN; top-1 **0.89** / top-3 **0.96** / abstain F1 0.97 |
| 3 | Cognitive analyzer | `cognitive_analyzer/` | ✅ Fuses Parts 1+2 → Student Cognitive Update (§6.2 aggregates) |
| 4 | HOPE detectors | `hope_detector/` | ✅ Ordinal KI/KT/CT; discrimination gate (strong−memorized ≥1) PASS on all three |
| 5 | Pedagogy policy | `policy_shadow/` | ✅ **Shadow mode** — 14 actions, top-1 0.68 / top-2 0.84 (fixed-source rebuild 2026-06-19); logged beside rules, not yet authoritative |
| 6 | Knowledge tracing | `learner_state.py` | Rule-based now; neural KT **deferred** until real learning logs exist |
| 7 | Runtime loop | `tutor_loop.py` | ✅ v4 — analyzer → state → rules+shadow → retrieval → Qwen → write-back; all loops closed |
| 8 | Evaluation | `verify_store.py`, frozen splits | ✅ build-time gates; pilot metrics await real learners |
| 9 | Jetson voice deploy | `wini_*_pkg` (ROS 2) | ✅ Layers A & C built/verified on Jetson Orin Nano (voice doc §12) |
| 10 | Windows voice rig | `voice/`, `pacing/`, `voice_hybrid_runner.py` | ✅ Hybrid test rig — Cloud STT/TTS edges, local brain |

**Authoritative pedagogy is rule-based** (`tutor_loop.rules_decide` v4); the neural policy
runs in shadow and is promoted only after it beats the rules on logged real turns.

---

## 6. Voice runtime

Two deployments share the same study core:

- **Jetson Orin Nano (deployment target).** Fully local, half-duplex. openWakeWord (ONNX/CPU)
  → Faster-Whisper `small.en` (CTranslate2 CUDA, built from source) → brain (in-process
  Qwen-3B GPU, MiniLM CPU) → Kokoro TTS (onnxruntime CUDA EP). As-built record, including
  every spec→reality deviation (TensorRT ruled out, in-process LLM, RMS endpointing), is
  **[`WINI_VOICE_STUDY_ARCHITECTURE.md`](WINI_VOICE_STUDY_ARCHITECTURE.md) §12** — that
  section wins over §1–§11 where they disagree.
- **Windows hybrid rig (dev/test).** `python voice_hybrid_runner.py --live`. Cloud STT (forced
  `en-US` + maths phrase hints) and Cloud TTS (`en-IN-Chirp3-HD-Achernar`, verbatim) on the
  edges; the brain stays local and unchanged. **Gemini Live was evaluated and rejected**
  (paraphrased the maths, wrong-script STT) — build plan Part 10 + rag_memory (2026-06-18).

The cognition contract for short spoken turns (one state channel moves per turn; action-aware
spoken budget; deliver-don't-announce) lives in architecture §21 and is implemented in
`pacing/`. Deferred for both: AEC → full-duplex + semantic barge-in.

---

## 7. Repository map

```
WINI_ARCHITECTURE.md              ← you are here (overview + index)
learner_cognitive_state_architecture.md   RAG_upgrade_plan.md
model_dataset_architecture_report.md       complete_architecture_build_plan.md
rag_memory.md                              CLAUDE.md
WINI_VOICE_STUDY_ARCHITECTURE.md           WINI_V2_ARCHITECTURE.md (legacy)

cognitive_input_processor/   B0  normalize + preserve math
cognitive_classifier/        B1  Part 1 — MiniLM signal classifier (+ cues.py)
concept_resolver/            B1  Part 2 — MiniLM concept resolver
cognitive_analyzer/          B1  Part 3 — Student Cognitive Update
hope_detector/               B4/B6  Part 4 — ordinal KI/KT/CT detectors
policy_shadow/               B3  Part 5 — shadow pedagogy policy
learner_state.py             B2  learner model + probe/bridge write-backs + HOPE rolling
query.py                     B4  7-term retrieval + manifest + cohesion check
tutor_loop.py                orchestrator — TutorLoop.turn(); rules_decide v4
voice/  pacing/  voice_hybrid_runner.py    Part 10 Windows voice rig

rag_store/                   the knowledge store (concepts, graph, chunks, FAISS, bridges,
                             HOPE bank, figure crops, learning_log.jsonl, scorecards)
dataset/                     canonical exemplar_dataset_10000_fixed.json + derived _curated.json; archive/ holds raw
models/                      trained artifacts + splits.json (shared eval contract, regen 2026-06-19)
build_index.py  verify_store.py  rag_core.py  enrich_concepts.py  crop_figures.py
build_bridges.py  build_hope_bank.py         store build/verify pipeline
```

---

## 8. Quick commands

```bash
# Tutor chat (Qwen server must be up)
python tutor_loop.py                       # interactive
python tutor_loop.py --once "msg" [--no-answer]

# Windows voice rig
python voice_hybrid_runner.py --live

# Store verification
python verify_store.py --fail-under 90

# Rebuild components (curate first if rules changed)
python -m cognitive_classifier.build_bank
python -m concept_resolver.build_resolver
python -m policy_shadow.build_policy

# Start the local Qwen server (dev box)
python F:/Projects/Pedagogical_study_pkg/scripts/run_llama_server.py
```

See `CLAUDE.md` for the full command list and the hard project mandates.
