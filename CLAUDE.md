# Wini Pedagogical System — Project Rules

## The 4-doc lockstep rule (MANDATORY)

These four documents describe one system and MUST stay consistent. Any change to one
must be propagated to the others in the same work session, plus the work log:

| # | Document | Role |
|---|---|---|
| 1 | `learner_cognitive_state_architecture.md` | WHAT the system models (source of truth for schemas, signals, contracts) |
| 2 | `RAG_upgrade_plan.md` | HOW the store carries those structures (build/verify plan; executed, see rag_memory.md) |
| 3 | `model_dataset_architecture_report.md` | datasets + neural models that realize the architecture |
| 4 | `complete_architecture_build_plan.md` | execution status of every Part (1–8) with measured results |

- `rag_memory.md` is the append-style WORK LOG for store work; major incidents and
  lessons go there too.
- Propagation checklist when you change behavior/schema: update the build plan's Part
  section with measured results → check the architecture doc still describes the
  contract correctly → check the report's dataset/model numbers → log gotchas.
- Never edit a number in a doc without re-measuring it.

## Hard mandates

- **LLM calls use the LOCAL Qwen model only** (qwen2.5-3b-instruct via llama.cpp,
  OpenAI-compatible API at http://127.0.0.1:8080, Vulkan GPU). No Gemini/Vertex clients
  in new code, no offline stubs. Start: `python F:/Projects/Pedagogical_study_pkg/scripts/run_llama_server.py`
- **Frozen splits**: `models/exemplar_classifier/splits.json` is the shared train/val/test
  contract for EVERY model trained on `dataset/exemplar_dataset_10000_curated.json`.
  Never re-split; supplementary files (augmented/gap rows) carry their own split fields
  and never enter val/test of the original 10k.
- **Original dataset files are read-only**: curation/generation writes NEW files
  (`*_curated.json`, `augmented_*.json`, `concept_gap_*.json`).
- **Probe before correcting** (architecture §10/§13 rule 8) and **state moves only on
  evidence** (apply_probe_result / apply_bridge_result), never from text inference alone.

## Known gotchas (verified, do not rediscover)

- Concept-card `misconceptions` field is free TEXT; real misconception nodes hang off
  `has_misconception` graph edges — always walk the edges.
- sklearn `OneVsRestClassifier(n_jobs=-1)` crashes on Windows (joblib loky) — keep sequential.
- `cognitive_classifier/cues.py` CUE_NAMES length is baked into the shipped logreg widths —
  adding a cue feature requires rebuilding BOTH the classifier bank and the policy shadow.
- Bulk-LLM scripts need hard wall-clock timeouts around every call (ThreadPoolExecutor
  `.result(timeout=...)` for SDK clients, `requests(timeout=...)` for the Qwen server);
  SDK-level HttpOptions timeouts have stalled for hours.
- Console output: pass `PYTHONIOENCODING=utf-8` when printing dataset text (cp1252 console).

## Quick commands

- Rebuild classifier: `python -m cognitive_classifier.build_bank` (curate first if rules changed)
- Rebuild resolver: `python -m concept_resolver.build_resolver`
- Rebuild policy shadow: `python -m policy_shadow.build_policy`
- Analyzer tests: `python -m cognitive_analyzer.test_analyzer --integration`
- Tutor chat: `python tutor_loop.py` (Qwen server must be up); scripted: `--once "msg" [--no-answer]`
- Store scorecard: `python verify_store.py --fail-under 90`
