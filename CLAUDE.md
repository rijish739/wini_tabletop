# Wini Pedagogical System — Project Rules

## Source of truth (replaces the former 4-doc lockstep rule)

The lockstep set (`learner_cognitive_state_architecture.md`, `RAG_upgrade_plan.md`,
`model_dataset_architecture_report.md`, `complete_architecture_build_plan.md`) has been
**archived** (`docs/archive/`). Four-way manual propagation is unmaintainable; those
documents drifted apart while all four still claimed authority. Their replacement:

| What you need | Where to find it |
|---|---|
| Layer boundaries, per-layer contracts, system-wide invariants | **`docs/architecture/WINI_ARCHITECTURE.md`** (normative) |
| Safety taxonomy, detection architecture, evaluation floors | **`docs/architecture/SAFETY_ROUTE_TAXONOMY.md`** (normative) |
| Personal-data detection, redaction, sinks, retention | **`docs/architecture/PERSONAL_DATA_CONTRACT.md`** (normative) |
| Domain vocabulary (Utterance, Feature Module, Turn, …) | **`CONTEXT.md`** |
| Measured numbers (store, datasets, eval scores) | The dated record that measured them — never restated in the above |
| Append-style work log | `docs/archive/rag_memory.md` |

**Precedence rule (when two documents disagree):** `CONTEXT.md` vocabulary > `WINI_ARCHITECTURE.md`
> dated measurement records. Among measurement records, the most recently measured date wins.
The two contracts (`SAFETY_ROUTE_TAXONOMY.md`, `PERSONAL_DATA_CONTRACT.md`) are each
**authoritative in their own area** and do not conflict with the architecture document — the
architecture doc defers to them for their topics and never restates their content.

**The propagation obligation is gone.** A number lives in exactly one place. Re-measuring means
writing a new record; it does not mean editing a sentence in the architecture document.

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
- **`cognitive_classifier/cues.py` cue vector retired (ticket 17, 2026-08-27):** the 9-cue
  feature vector no longer runs at runtime. `score_matrix()` zero-fills the cue dims so the
  shipped logreg weights keep working without a re-fit (rebuild path was lost in `5b847a1`).
  `cue_features` / `cue_matrix` remain in `cues.py` for offline tooling only; do NOT add them
  back to any runtime scoring path. If a rebuild ever becomes possible, re-fit requires
  restoring `build_bank.py` from `5b847a1^` first. **PolicyShadow** is retired from the
  runtime entirely — its only consumer was a log line.
  **Zero-fill scope (decided 2026-08-27):** the zero-fill only affects
  `ExemplarCognitiveClassifier.score_matrix()`. In the Gemini runtime `TutorLoop.__init__`
  passes `GeminiPerception` as both classifier and resolver to `CognitiveAnalyzer`, so
  `GeminiPerception.classify()` — not `ExemplarCognitiveClassifier` — feeds
  `derive_cognitive_update` / `derive_state_deltas`. `ExemplarCognitiveClassifier` is called
  only in offline evals and the §5.5 cross-check (where score bias is bounded and acceptable).
  **The legacy classifier is offline-only.** Do not wire it back into any production turn
  path — use `GeminiPerception` for all runtime signal/state-math inputs.
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
- **SAFETY: the architecture was inverted on 2026-08-26 — DECIDED, NOT YET IMPLEMENTED.**
  Read `docs/architecture/SAFETY_ROUTE_TAXONOMY.md` (normative) before touching anything on
  the safety path; decision log in
  `.scratch/deterministic-input-layer/issues/07-decide-the-safety-route-taxonomy.md`.
  - **What the code does TODAY** (unchanged until the implementation lands): the regex
    lexicon in `perception/gates.py` is the primary detector and the floor, and Gemini's
    `safety` boolean is an additive net. `gates.py:5-9`'s docstring still describes this.
  - **What was decided:** a dedicated Gemini call in a new `cloud_run_service/child_safety/`
    package becomes the **primary** detector (every turn, parallel to perception, its own
    prompt/schema/context-cache/eval, `VERTEX_SAFETY_MODEL`/`VERTEX_SAFETY_LOCATION`
    defaulting to `gemini-2.5-flash@asia-south1` with the version **pinned**, 5s hard
    wall-clock + one retry, late verdicts still count). The lexicon survives **only** as the
    degraded-mode outage net: axis-only, `{UNSPECIFIED_CONCERN}`/`ELEVATED`, never
    `CRITICAL`, frozen and CI-maintained.
  - **The invariant that survives, retargeted:** *nothing may ever remove a finding, whatever
    made it.* Model verdict is the verdict; perception's bit unions in; the net contributes
    only on failure; a late verdict unions; **severity is derived at exactly one site** and
    written by no detector.
  - **Do not trust the shipped "SAFETY recall 1.0."** MEASURED 2026-08-26: it is computed on
    a 20-phrase corpus that mirrors the lexicon (`eval/perception_eval.py:120-141` and
    `eval/perception_eval_safety.jsonl` are the same 20 phrases), and the promotion gate
    hard-codes `>= 1.0` against it. `python -m eval.perception_eval --gates` does not even run
    from the repo root (imports `perception.gates`; there is no root `perception/`). Real
    holes measured: peer-at-risk and online solicitation are **total misses**, 6 of 9
    self-harm probes land in the tier-2 catch-all, and `i do not want to die in this level` is
    a tier-3 **false positive**.
  - **The measurement rule replaces "measure gate recall directly":** measure **model** recall
    on **blind per-class corpora** (written against the taxonomy doc's definitions, never
    against the patterns), **publish no aggregate safety number anywhere**, and re-run
    `eval/safety_eval.py` before any prompt / schema / model / region / cache / version change
    — a model's safety recall moves silently in ways a regex's never did.
  - Unrelated but still true: `perception/gemini_perception.py` `score_matrix` is turn-scoped
    (policy-shadow use), and one Gemini call/turn is memoized by *normalized* text — keep
    `InputProcessor.normalize_input` idempotent. (Ticket 02 moves that memo key to
    `utterance_id`; until then, idempotency still matters.)
- **PERSONAL DATA: contract DECIDED 2026-08-27, NOT YET IMPLEMENTED.** Read
  `docs/architecture/PERSONAL_DATA_CONTRACT.md` (normative) before touching redaction, logging
  of learner text, or the generation prompt; decision log in
  `.scratch/deterministic-input-layer/issues/09-decide-the-personal-data-contract.md`. Three
  things to know before you touch anything nearby: today there is **no detector at all** and
  `_log_shift`/`_log_nonlearning` write the child's raw turn to `learning_log.jsonl`
  (`tutor_loop.py:1856`, `:1884` — the latter redacts only on a `safety_alert` turn); detection
  is decided as **model-only with no regex fallback**, because a pattern detector scores
  F1 0.379 on maths dialogue by eating the maths; and personal data is **off the safety axis**
  (annotation, never a route) with the §3 write boundary landing on **fields, not turns** —
  there is no do-not-learn-from-this-turn flag.
- **CONCEPT INHERITANCE: partly executed, resolution UNOWNED (2026-08-27).** Read
  `cloud_run_service/concept_resolver/CONCEPT_RESOLUTION_HANDOVER.md` before touching anything
  that decides which concept an utterance is about; decision log in
  `.scratch/deterministic-input-layer/issues/12-decide-where-coreference-confidence-lives.md`.
  - **Measure first, always:** **35.5%** of the frozen hardened run predicts
    `INHERIT_CURRENT_CONCEPT`, and **gold says 39.2% should** (`eval/perception_eval_raw2.jsonl`,
    1019 rows, offline). "Carry the session's concept" is the *correct* answer for ~2 in 5
    utterances. Deleting inheritance globally breaks the common case to fix a rare one — do not
    treat docx §8/§14 as license to rip it out.
  - **`INHERIT_CURRENT_CONCEPT` is a historical name.** It means *the model declined to name a
    concept*. It stays welded to the response schema, prompt-of-record, context cache, dataset
    gold and `eval/perception_eval.py:64`; do not rename it.
  - **Five silent-inherit sites existed.** Three are deleted by the input-layer effort (the drift
    guard `control.py:427-436`, and the duplicate suppliers `legacy_adapter.py:102` / `:215` /
    `:245`). **Two survive on purpose** — `perception/interface.py:151-153` (abstain) and
    `_degraded` (outage) — and are the concept resolver's first two deletions, not yours.
  - **Concept resolution is bigger than `concept_resolver/resolver.py`.** That file is a
    stateless MiniLM scorer and becomes a *component* of the layer; the layer owes chat-history
    reading and a follow-up question requested from pedagogy. It does not exist yet.
  - **Invariant:** `concept_id is None` ⇒ no learner-state write and no mastery movement.
  - Docx §8's three bands, §14's coreference row and §16's clarification-UI item are **unmet and
    unowned**. Do not describe the system as satisfying them.

## Quick commands

- Rebuild classifier / policy shadow / curate dataset: **UNREPRODUCIBLE** — `build_bank.py`,
  `build_policy.py` and `curate_dataset.py` were deleted by `5b847a1` and no longer exist. The
  shipped logreg + policy artifacts are frozen; a re-fit requires restoring `build_bank.py` from
  `5b847a1^` first (see the `cues.py` gotcha). PolicyShadow is retired from the runtime.
- Rebuild resolver: `python -m concept_resolver.build_resolver`
- Analyzer tests: `python -m cognitive_analyzer.test_analyzer --integration`
- Rebuild perception schema/cache: `python -m perception.build_perception` (regen enums + cached block from artifacts)
- Perception tests: `python -m perception.test_perception [--integration]` (gates + belt + front door)
- Perception eval: `python -m eval.perception_eval --build --gates` (offline); `--hardened --score` (offline re-score of the prompt-of-record v2 cache); `--hardened --collect` (BILLED re-collect)
- Behavioral signals eval: `python -m eval.behavioral_eval --hardened --run` (48 probe calls billed once, then cached; `--replay` alone is offline)
- Perception context cache (Stage 5): `python -m perception.vertex_cache --create [--ttl-hours 24] | --status | --delete` — recreate after `build_perception` rebuilds or TTL expiry; calls fall back to the full system prompt automatically if absent/expired/stale
- Perception is gemini-only at runtime since Stage 6 (2026-07-02); `PERCEPTION_BACKEND=qwen_heads` is retired (prints a notice, uses gemini). Head artifacts stay for the evals + §5.5 cross-check.
- Tutor chat: `python tutor_loop.py` (Qwen server must be up); scripted: `--once "msg" [--no-answer]`
- Store scorecard: `python verify_store.py --fail-under 90`
- Rebuild concept->formula links: `python link_formulas.py` (writes rag_store/formula_links.json; re-run after any graph/chunks/concepts rebuild)
