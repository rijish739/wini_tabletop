# Wini — Pedagogy-First Tutoring System (NCERT Class 10 Maths)

Wini models a student's **cognitive state** during learning — what they understand, misunderstand, feel, and are ready for — and chooses a teaching move from that state, instead of routing a message to a simple chatbot intent. Every reply is grounded in retrieved NCERT evidence, and the learner model updates strictly on verified evidence.

```
message → Interaction Control → Perception & Grading → Pedagogy Decision
        → Grounded Retrieval → Response Planning → Generation & Presentation → State Commit
```

---

## 🚀 Quick Start for Developers

1. **New to the project?** Read [DEVELOPER_ONBOARDING.md](DEVELOPER_ONBOARDING.md).
2. **Domain concepts & terminology:** [CONTEXT.md](CONTEXT.md).
3. **Agent & coding guidelines:** [CLAUDE.md](CLAUDE.md).
4. **Active ticket tracking & decisions:** [`.scratch/modular-tutor-runtime/map.md`](.scratch/modular-tutor-runtime/map.md).

---

## 🏛️ Codebase Structure

| Directory / File | Description |
|---|---|
| [`cloud_run_service/`](cloud_run_service/) | **Canonical Modular Tutor Runtime** containing all 9 feature modules (`runtime/`, `interaction_control/`, `pedagogy/`, `retrieval/`, `assessment_evidence/`, `response_planning/`, `response_generation/`, `state_and_persistence/`, `baseline_oracle/`, and `perception/`). |
| [`rag_store/`](rag_store/) | NCERT Class-10 Maths knowledge base, 1,017 chunks, 3,562 graph nodes, and embeddings. |
| [`figures/`](figures/) | Cropped textbook geometric and algebraic figures. |
| [`dataset/`](dataset/) | Curriculum exemplars and seed datasets. |
| [`models/`](models/) | Local MiniLM embeddings and concept classifier models. |
| [`pi_game/`](pi_game/), [`pi_client_package/`](pi_client_package/) | Raspberry Pi tabletop display client and packaging. |
| [`voice/`](voice/) | Voice STT/TTS streaming pipelines. |
| [`wini_platform/`](wini_platform/), [`wini_client/`](wini_client/) | Hardware platform runner and client interfaces. |
| [`docs/`](docs/) | Complete project documentation, architecture specifications, runbooks, and historical archives. |

---

## 📚 Documentation Index (`docs/`)

- **Architecture Specifications** ([`docs/architecture/`](docs/architecture/)):
  - [`WINI_ARCHITECTURE.md`](docs/architecture/WINI_ARCHITECTURE.md) — System architecture overview.
  - [`WINI_V2_ARCHITECTURE.md`](docs/architecture/WINI_V2_ARCHITECTURE.md) — Deep architectural specification.
  - [`learner_cognitive_state_architecture.md`](docs/architecture/learner_cognitive_state_architecture.md) — Cognitive state modeling.
  - [`model_dataset_architecture_report.md`](docs/architecture/model_dataset_architecture_report.md) — Dataset and neural model architecture.
  - [`rag_memory.md`](docs/architecture/rag_memory.md) — System work log and gotchas.
  - [`WINI_ROSLESS_PLATFORM_PLAN.md`](docs/architecture/WINI_ROSLESS_PLATFORM_PLAN.md) — Hardware platform architecture.
- **Runbooks & Operational Guides** ([`docs/runbooks/`](docs/runbooks/)):
  - [`NEW_MACHINE_SETUP.md`](docs/runbooks/NEW_MACHINE_SETUP.md) — Environment bootstrap guide.
  - [`JETSON_PIPELINE_RUNBOOK.md`](docs/runbooks/JETSON_PIPELINE_RUNBOOK.md) — Pipeline runbook.
  - [`CLOUD_VOICE_STATUS_AND_GOTCHAS.md`](docs/runbooks/CLOUD_VOICE_STATUS_AND_GOTCHAS.md) — Voice deployment notes.
- **Historical Sprint Plans & Research** ([`docs/archive/`](docs/archive/)):
  - Past milestone plans (Parts 11–15), RAG research, and audit logs.

---

## 🧪 Verification & Testing

```powershell
# Run the full modular tutor runtime test suite (138+ tests)
$env:PYTHONPATH="cloud_run_service;."
pytest cloud_run_service/test_p0_evidence.py cloud_run_service/runtime/ cloud_run_service/interaction_control/ cloud_run_service/pedagogy/ cloud_run_service/retrieval/ cloud_run_service/assessment_evidence/ cloud_run_service/response_planning/ cloud_run_service/response_generation/ cloud_run_service/state_and_persistence/ cloud_run_service/baseline_oracle/ cloud_run_service/perception/tests/ -v

# Run the Board Buddy and response layer test suite
python cloud_run_service/response_layer/run_tests.py
```
