# Wini — Pedagogy-First Tutoring System (NCERT Class 10 Maths)

Wini models a student's **cognitive state** during learning — what they understand,
misunderstand, feel, and are ready for — and chooses a teaching move from that state, instead
of routing a message to one chatbot intent. Every reply is grounded in retrieved NCERT
evidence, and the learner model moves only on evidence (probe/bridge outcomes, HOPE scores),
never on text inference alone.

```
message → cognitive analyzer → learner-state update → pedagogy decision
        → grounded response (local Qwen) → state write-back
```

## Start here

- **[WINI_ARCHITECTURE.md](WINI_ARCHITECTURE.md)** — end-to-end overview and index to every
  other document. Read this first.

Detailed docs (kept in lockstep — see `CLAUDE.md`):

- [learner_cognitive_state_architecture.md](learner_cognitive_state_architecture.md) — what the system models
- [RAG_upgrade_plan.md](RAG_upgrade_plan.md) — how the store was built
- [model_dataset_architecture_report.md](model_dataset_architecture_report.md) — datasets + neural models
- [complete_architecture_build_plan.md](complete_architecture_build_plan.md) — build status (Parts 1–10)
- [WINI_VOICE_STUDY_ARCHITECTURE.md](WINI_VOICE_STUDY_ARCHITECTURE.md) — voice-to-voice runtime
- [rag_memory.md](rag_memory.md) — append-only work log

## What is built

- **Knowledge store** (`rag_store/`): 108 NCERT Class-10 Maths concepts, schema v2, 1,017
  grounded chunks, 3,562 graph nodes (concepts, Class-9 bridges, problem schemas, hint chains,
  enriched misconceptions, CT probes, cropped figures). `verify_store.py` scorecard: 18/18 PASS.
- **Models** (Parts 1–5): MiniLM cognitive classifier, concept resolver, cognitive analyzer,
  ordinal HOPE detectors, shadow pedagogy policy.
- **Runtime** (`tutor_loop.py`): the closed learner-state loop — bridge gate, misconception
  probe→correct, 7-term learner-state-aware retrieval, provenance manifest, write-backs.
- **Voice**: Jetson Orin Nano deployment (fully local) and a Windows hybrid test rig
  (cloud STT/TTS edges, local brain).

## Hard mandates

- **LLM = local Qwen only** (qwen2.5-3b-instruct via llama.cpp). Embeddings = local MiniLM.
  No Gemini/Vertex in the runtime brain.
- **Class 10 Mathematics only** (Science attaches later without schema change).
- Canonical dataset = `dataset/exemplar_dataset_10000_fixed.json` (raw archived under
  `dataset/archive/`); `curate_dataset.py` projects it to `_curated.json`, the build input.
  `models/.../splits.json` is the shared train/val/test contract (regenerated 2026-06-19).

## Quick commands

```bash
python tutor_loop.py                       # tutor chat (Qwen server must be up)
python tutor_loop.py --once "msg"          # scripted single turn
python voice_hybrid_runner.py --live       # Windows voice rig
python verify_store.py --fail-under 90      # store scorecard
```

See `CLAUDE.md` for the full command list, project rules, and known gotchas.
