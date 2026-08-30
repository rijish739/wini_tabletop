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
3. **Architecture & layer boundaries:** [`docs/architecture/WINI_ARCHITECTURE.md`](docs/architecture/WINI_ARCHITECTURE.md).
4. **Agent & coding guidelines:** [CLAUDE.md](CLAUDE.md).

---

## 🏛️ Codebase Structure

| Directory / File | Description |
|---|---|
| [`cloud_run_service/`](cloud_run_service/) | **Canonical Modular Tutor Runtime** containing all core modules (`runtime/`, `utterance_intake/`, `interaction_control/`, `child_safety/`, `personal_data/`, `perception/`, `pedagogy/`, `retrieval/`, `assessment_evidence/`, `response_planning/`, `response_generation/`, `state_and_persistence/`, `baseline_oracle/`, and `response_layer/`). |
| [`rag_store/`](rag_store/) | NCERT Class-10 Maths knowledge base, 1,017 chunks, 3,562 graph nodes, page images, and embeddings. |
| [`figures/`](figures/) | Cropped textbook geometric and algebraic figures. |
| [`dataset/`](dataset/) | Curriculum exemplars and seed datasets. |
| [`models/`](models/) | Local MiniLM embeddings, concept classifiers, and HOPE models. |
| [`wini_client/`](wini_client/) | Python thin client for voice & display streaming over HTTP. |
| [`wini_platform/`](wini_platform/) | Tabletop device orchestrator (display drivers, eyes animation, touch interface). |
| [`wini_ui/`](wini_ui/) | Embedded C / LVGL user interface client for physical display. |
| [`pi_game/`](pi_game/), [`pi_client_package/`](pi_client_package/) | Raspberry Pi tabletop client packaging. |
| [`tools/`](tools/) | Hardware, latency, and debug diagnostic utilities. |
| [`docs/`](docs/) | Normative architecture specifications, contracts, runbooks, and historical archives. |

---

## 📚 Documentation Index (`docs/`)

- **Normative Architecture & Contracts** ([`docs/architecture/`](docs/architecture/)):
  - [`WINI_ARCHITECTURE.md`](docs/architecture/WINI_ARCHITECTURE.md) — System architecture, layer boundaries, and invariants.
  - [`SAFETY_ROUTE_TAXONOMY.md`](docs/architecture/SAFETY_ROUTE_TAXONOMY.md) — Child safety risk taxonomy, detection architecture, and routing.
  - [`PERSONAL_DATA_CONTRACT.md`](docs/architecture/PERSONAL_DATA_CONTRACT.md) — Personal data detection, exact-match redaction, and sink contracts.
  - [`AUDIO_END_TO_END_FLOW.md`](docs/architecture/AUDIO_END_TO_END_FLOW.md) — End-to-end audio capture, intake, and streaming pipeline.
  - [`CODEBASE_ARCHITECTURE_AND_COUPLING_REPORT.md`](docs/architecture/CODEBASE_ARCHITECTURE_AND_COUPLING_REPORT.md) — Measured coupling metrics and dependency matrix.
- **Runbooks & Operational Guides** ([`docs/runbooks/`](docs/runbooks/)):
  - [`NEW_MACHINE_SETUP.md`](docs/runbooks/NEW_MACHINE_SETUP.md) — Environment bootstrap guide for dev and device.
  - [`JETSON_PIPELINE_RUNBOOK.md`](docs/runbooks/JETSON_PIPELINE_RUNBOOK.md) — Jetson thin client reference guide.
  - [`CLOUD_VOICE_STATUS_AND_GOTCHAS.md`](docs/runbooks/CLOUD_VOICE_STATUS_AND_GOTCHAS.md) — Cloud voice streaming deployment notes.
- **Architecture Decision Records** ([`docs/adr/`](docs/adr/)):
  - [`0001-delete-deterministic-intent-cues.md`](docs/adr/0001-delete-deterministic-intent-cues.md) — Deletion of obsolete deterministic intent cues.
- **Historical Archives** ([`docs/archive/`](docs/archive/)):
  - Archived research, legacy sprint plans (Parts 11–15), RAG research, and duplicate runtime disposition (`DUPLICATE_RUNTIME_DISPOSITION.md`).

---

## 🧪 Verification & Testing

```powershell
# Run the full modular tutor runtime test suite (529+ tests)
$env:PYTHONPATH="cloud_run_service;."
pytest cloud_run_service/

# Run the Board Buddy and response layer test suite
python cloud_run_service/response_layer/run_tests.py
```
