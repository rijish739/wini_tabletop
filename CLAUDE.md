# Wini Pedagogical System — Project Rules

> **Entry point:** `WINI_ARCHITECTURE.md` is the end-to-end overview and index to every
> document below. It sits *above* the lockstep set; update it when the system's external
> shape changes (it does not carry authoritative contracts, so it is not part of the
> lockstep propagation requirement).

## The 4-doc lockstep rule (MANDATORY)

These four documents describe one system and MUST stay consistent. Any change to one
must be propagated to the others in the same work session, plus the work log:

| # | Document | Role |
|---|---|---|
| 1 | `learner_cognitive_state_architecture.md` | WHAT the system models (source of truth for schemas, signals, contracts) |
| 2 | `RAG_upgrade_plan.md` | HOW the store carries those structures (build/verify plan; executed, see rag_memory.md) |
| 3 | `model_dataset_architecture_report.md` | datasets + neural models that realize the architecture |
| 4 | `complete_architecture_build_plan.md` | execution status of every Part (1–10) with measured results |

- `rag_memory.md` is the append-style WORK LOG for store work; major incidents and
  lessons go there too.
- Propagation checklist when you change behavior/schema: update the build plan's Part
  section with measured results → check the architecture doc still describes the
  contract correctly → check the report's dataset/model numbers → log gotchas.
- Never edit a number in a doc without re-measuring it.

## Hard mandates

- **LLM calls use Vertex AI Gemini (cloud).** The platform pivoted off Jetson edge to
  cloud on 2026-06-30 (Jetson cost). See `PART11_GEMINI_PERCEPTION_LAYER.md` and
  `technical_investor_report.md`.
  - **Perception** (intent routing + cognitive signals + concept resolution): ONE
    structured **Gemini 2.5 Flash** call (`temperature=0`, response schema), replacing the
    MiniLM cognitive classifier + concept resolver. Reuses the deterministic
    `derive_*`/`apply_deltas` state math unchanged. **PROMOTED 2026-07-02: default
    `PERCEPTION_BACKEND=gemini`** (concept 0.930/0.990, behavioral signal eval PASS,
    intent 1.0, safety 1.0). Concept is **hybrid**: MiniLM `candidate_concepts` hints +
    a deterministic resolver cross-check on the primary (`fuse_primary`,
    `PERCEPTION_CONCEPT_CROSSCHECK`). Signals are promotion-gated on the **behavioral
    state-trajectory eval** (`eval/behavioral_eval.py`), NOT label-F1 vs the heads —
    the heads win label-F1 by construction (trained on the dense gold); do not
    resurrect that gate. See `PART11_GEMINI_PERCEPTION_LAYER.md` +
    `PART11_PERCEPTION_EVAL_STATUS.md`.
  - **Generation** (B5 answer): Gemini 2.5 Flash on Vertex (`asia-south1`), manifest-
    grounded prompt unchanged. `tutor_loop.qwen_chat` → Vertex client (`llm_vertex.py`).
  - **Stays on MiniLM (local, in-container):** retrieval embeddings (`S_rel`) and the
    **HOPE** detectors (KI/KT/CT) — teacher-calibrated, NOT moved to Gemini.
  - **Perception migration COMPLETE (Stages 4–6, 2026-07-02):** gemini-only at runtime
    (`qwen_heads` flag retired — prints a notice, uses gemini); static block on a Vertex
    context cache (`perception/vertex_cache.py`); head artifacts kept for evals + the §5.5
    cross-check. **Generation** is still staged (`GEN_BACKEND=qwen|gemini`): the local Qwen
    path (`llm_local.py` / llama.cpp `:8080`, start `run_llama_server.py`) stays as
    legacy/fallback until its promotion gate is green — do NOT delete it mid-migration.
  - **Hard wall-clock timeout on every Gemini call** (per the bulk-LLM gotcha below).
- **Deployment target: cloud, not edge.** Brain = a multi-tenant service on **Cloud Run
  (`min-instances=1`** to absorb the MiniLM/torch cold start**)**; per-learner state in
  **Firestore** (not local JSON) once multi-instance. Device = **thin client** (ESP32-P4:
  mic in, speaker out, e-ink) — no brain on device. Quick-test rig: Windows laptop
  mic/headphones + cloud brain. The **Jetson is a THIN CLIENT** (2026-07-03): `wini_server.py`
  (Cloud STT → TutorLoop/Gemini → Cloud TTS, one HTTP contract — the future Cloud Run
  artifact) + `wini_client/` (mic/speaker/display platform loop, deps = numpy +
  sounddevice + requests). No wakeword, no local ASR/TTS/LLM on the device; it is the
  reference client for the ESP32 display-metadata contract, at 172.20.10.2 (192.x
  retired). See `JETSON_PIPELINE_RUNBOOK.md` §15 + `wini_client/README.md`. The full
  local ROS pipeline and the in-proc Qwen brain are legacy (kept on disk).
- **Canonical dataset = `dataset/exemplar_dataset_10000_fixed.json`** (10000 audit-corrected
  base rows + 800 T2/T3 supplementary rows that carry `split:"train"`). `curate_dataset.py`
  reads it and writes `dataset/exemplar_dataset_10000_curated.json`, the **gold-rule
  projection** that build_bank / build_policy / concept_resolver consume. `_curated.json`
  is a DERIVED build artifact, NOT a competing source. The raw `exemplar_dataset_10000.json`
  is archived under `dataset/archive/` (provenance only).
- **Splits**: `models/exemplar_classifier/splits.json` is the shared train/val/test contract;
  it was regenerated (2026-06-19) when the source moved to `_fixed.json`, stratified over the
  10000 base rows only. Supplementary rows (`split:"train"`) and `augmented_rare_labels.json`
  are TRAIN-ONLY and never enter val/test. Reuse this splits.json; only re-split deliberately
  (delete it to regenerate) when the base labeling changes, and rebuild every dependent model.
- **Original dataset files are read-only**: curation/generation writes NEW files
  (`*_curated.json`, `augmented_*.json`, `concept_gap_*.json`). `_fixed.json` is edited only by
  the dataset/ audit + T2/T3 generator scripts, never by the training pipeline.
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
- **Gemini 2.5 Flash `thinking` defaults on** and can consume the entire `max_output_tokens`
  budget on hidden thinking tokens, returning empty text with `finish_reason=MAX_TOKENS` and
  no visible content. Set `thinking_config=ThinkingConfig(thinking_budget=0)` for short,
  latency-sensitive replies (see `llm_vertex.py`).
- **`genai.Client(...)` construction (Vertex ADC/channel setup), not the API call itself, is
  the dominant cold-start cost** for every Gemini/Vertex + Cloud STT/TTS client measured
  2026-07-01: ~4-9s to build a fresh client vs. sub-1.5s per call once warm. Build clients
  once per process/service (memoize), never per turn — this is exactly why Cloud Run
  `min-instances=1` matters.
- **Gemini Live API re-tested for STT-only (no audio-out) 2026-07-01**: transcript was
  correct this time (no repeat of the 2026-06-18 wrong-script bug), but steady-state latency
  is ~7.7-8.4s per utterance vs. Cloud STT's ~1.0-1.5s — 5-6x slower, because a Live session
  still runs a full model turn even when only the input transcription is used. **Cloud STT
  stays the STT choice on latency grounds alone**, independent of the earlier correctness
  rejection. See `voice/gemini_live_stt.py` and `voice_latency_spike.py`.
- **Perception `response_schema` enums stop *invented* values, not *wrong* ones** (Part 11).
  Vertex controlled generation masks decoding to schema-valid tokens, so Gemini can't emit an
  out-of-catalog concept/signal/intent — but it can still pick a wrong-but-valid one. Keep the
  local validation belt (coerce OOV→INHERIT/drop) AND gate signal firing on
  `PERCEPTION_SIGNAL_THRESHOLD` (calibrated on the frozen TEST split), never on the raw score.
- **The deterministic SAFETY gate must be near-total on its own** (Part 11) — the Gemini
  `safety` flag may only *add* recall, never remove it. First-pass lexicon scored 0.75 recall
  (missed gerunds "ending my life" vs "end my life" and oblique phrasings); broaden and
  **measure gate recall directly** (`python -m eval.perception_eval --gates`), don't lean on
  the model for the safety floor. `perception/gemini_perception.py` `score_matrix` is
  turn-scoped (policy-shadow use), and one Gemini call/turn is memoized by *normalized* text —
  keep `InputProcessor.normalize_input` idempotent.

## Quick commands

- Rebuild classifier: `python -m cognitive_classifier.build_bank` (curate first if rules changed)
- Rebuild resolver: `python -m concept_resolver.build_resolver`
- Rebuild policy shadow: `python -m policy_shadow.build_policy`
- Analyzer tests: `python -m cognitive_analyzer.test_analyzer --integration`
- Rebuild perception schema/cache: `python -m perception.build_perception` (regen enums + cached block from artifacts)
- Perception tests: `python -m perception.test_perception [--integration]` (gates + belt + front door)
- Perception eval: `python -m eval.perception_eval --build --gates` (offline); `--hardened --score` (offline re-score of the prompt-of-record v2 cache); `--hardened --collect` (BILLED re-collect)
- Behavioral signals eval: `python -m eval.behavioral_eval --hardened --run` (48 probe calls billed once, then cached; `--replay` alone is offline)
- Perception context cache (Stage 5): `python -m perception.vertex_cache --create [--ttl-hours 24] | --status | --delete` — recreate after `build_perception` rebuilds or TTL expiry; calls fall back to the full system prompt automatically if absent/expired/stale
- Perception is gemini-only at runtime since Stage 6 (2026-07-02); `PERCEPTION_BACKEND=qwen_heads` is retired (prints a notice, uses gemini). Head artifacts stay for the evals + §5.5 cross-check.
- Tutor chat: `python tutor_loop.py` (Qwen server must be up); scripted: `--once "msg" [--no-answer]`
- Store scorecard: `python verify_store.py --fail-under 90`
