# Wini — Voice-to-Voice Study Architecture

## Speech (wakeword → STT) → Cognitive-State Study Core → Speech (TTS)

> **What this document is.** `WINI_V2_ARCHITECTURE.md` was the earlier full-robot plan.
> Its **speech front-end and back-end** (wakeword, VAD, ASR, repair, turn-taking, TTS) are
> sound and retained here. Its **study package is obsolete**: the intent-router /
> DKVMN / PPO / hint-bank stack has been **replaced** by the *learner-cognitive-state*
> system actually built in `D:\cloud CLI` (8 parts, all shipped — see
> `complete_architecture_build_plan.md`). This document is the single end-to-end picture:
> how a spoken sentence becomes a spoken, pedagogically-chosen, curriculum-grounded reply.
>
> **Status legend:** ✅ BUILT (exists and verified) · 🔶 SPECIFIED (carried from WINI_V2,
> not yet built) · ⏳ FUTURE (deliberately deferred — wired later) · ⚙️ CONFIG (a
> setting/wiring step).
>
> **Deployment target.** All of this is built to run on the **Jetson Orin Nano** (Linux,
> JetPack 6). The study core (Layer B) is currently *developed* on a Windows + GTX 1650 box,
> but its deployment home is the Jetson. Therefore **no path is hard-coded** in the
> architecture: every file/model/endpoint location is resolved per-device from config/env
> (see §7). Paths shown in this doc are illustrative of the *current dev box*; the Jetson
> values are different and live in the device config.
>
> **Duplex mode (current).** The system is **half-duplex**: the microphone is **muted while
> Wini is speaking** (`robot_speaking == True`). There is **no barge-in yet**, because
> barge-in over the robot's own audio requires **Acoustic Echo Cancellation (AEC)**, which is
> a separate package currently being built (⏳). Full-duplex + semantic barge-in are added
> only once AEC lands.
>
> **Lockstep note:** the study core (Layer B) is governed by the 4-doc lockstep rule in
> `CLAUDE.md`. This document sits *above* those four and must be updated when Layer B's
> external contract changes.

---

## 1. Design goals

1. **Voice-native, fully local.** A child speaks; Wini listens, thinks, and speaks back.
   No audio and no text leaves the device. Every model — wakeword, VAD, STT, MiniLM,
   the Qwen LLM, TTS — runs on-device.
2. **The core models the *learner*, not an intent.** The middle of the pipeline is not a
   router; it is a cognitive-state estimator that updates what the student understands,
   misunderstands, and is ready for, and chooses a teaching move from that state.
3. **Every spoken sentence is grounded.** The reply is composed only from retrieved NCERT
   evidence (the provenance manifest), never from free model memory.
4. **The loop closes.** What the student says next updates mastery, misconception status,
   hint position, and the rolling HOPE scores — by evidence, never by text inference alone.
5. **Perceived latency under ~500 ms** via streaming TTS and a conversational filler that
   covers LLM time-to-first-token.

---

## 2. The end-to-end loop (one picture)

```
            ┌──────────────────────── LAYER A : SPEECH IN ────────────────────────┐
  child ───►│  Mic (16 kHz PCM, ring buffer)   ── GATED: muted while robot speaks  │
  speaks    │      │                                                               │
            │      ▼                                                               │
            │  A1 Wakeword  (openWakeWord TRT)  ── "Hey Wini" + 500 ms pre-roll    │
            │      ▼                                                               │
            │  A2 VAD + adaptive endpoint  (Silero v5) ── commit the utterance     │
            │      ▼                                                               │
            │  A3 STT  (Faster-Whisper small.en, CTranslate2 CUDA int8_float16)    │
            │           ── transcript                                              │
            │      ·  A4 AEC (echo cancellation) ⏳ future package — enables        │
            │           full-duplex + barge-in; disfluency repair later still      │
            └───────│─────────────────────────────────────────────────────────────┘
                   ▼  utterance text
            ┌──────────────────────── LAYER B : STUDY CORE (BUILT) ───────────────┐
            │  B0 Input Processor      normalize, preserve math                    │
            │  B1 Cognitive Analyzer   MiniLM classifier + concept resolver        │
            │        → Student Cognitive Update (signals + concept)                │
            │  B2 Learner State        mastery · misconceptions · hints · HOPE     │
            │  B3 Pedagogy Decision    rules (v4) + policy-shadow → one action     │
            │  B4 Retrieval            bridge gate · probe-first · 7-term rank ·    │
            │        cohesion · provenance manifest  (local MiniLM index)          │
            │  B5 Response             local Qwen, composed from manifest only     │
            │  B6 Write-backs          probe/bridge results · HOPE score · flags   │
            │  B7 Persistence          learner state · learning log                │
            └──────│───────────────────────────────────────────────────────────────┘
                   ▼  reply text (sentence by sentence)
            ┌──────────────────────── LAYER C : SPEECH OUT ───────────────────────┐
  child ◄───│  C1 Sentence splitter (pysbd)  ── stream first sentence early        │
  hears     │  C2 TTS  (Kokoro ONNX/TensorRT)  ── PCM to speaker                   │
            │       set robot_speaking=True → MUTE mic; on completion → unmute     │
            │  C3 Barge-in (semantic LSTM)  ⏳ UNWIRED — needs AEC (A4) first       │
            └──────────────────────────────────────────────────────────────────────┘
                   ▲
                   └── filler ("let me think…") played within 30 ms to mask LLM TTFT
```

Layer A and Layer C are the WINI_V2 speech stack (🔶 specified). Layer B is the system we
built and verified (✅). The system runs **half-duplex** until AEC (A4 ⏳) is added: the mic
is muted during TTS, so there is no barge-in yet (C3 ⏳). The rest of this document explains
every box.

---

## 3. LAYER A — Speech input (wakeword → STT)

The job of Layer A is to turn a continuous microphone stream into **one clean text
utterance**, only when the child is actually addressing Wini, and to know when the child
has finished speaking.

### A1. Wakeword detection 🔶

- **Model:** openWakeWord, compiled to a TensorRT engine (~50 MB, always resident).
- **Input:** the raw 16 kHz mono PCM stream from the microphone, processed continuously
  **while in LISTENING**. Under the half-duplex contract the mic (and therefore wakeword +
  VAD) is **paused during TTS** (§C2) and resumes when Wini finishes speaking.
- **Ring buffer:** the node keeps a rolling **500 ms** audio buffer at all times
  (`deque(maxlen=0.5*16000)`). The instant the wakeword fires, that 500 ms of *pre-trigger*
  audio is prepended to the stream sent to STT — this captures the beginning of the child's
  sentence, which is normally clipped because people start talking right after the wake
  phrase ("Hey Wini, *what is*…").
- **Output:** a `/wake_word` event + the pre-roll buffer. The pipeline leaves IDLE and
  enters LISTENING.
- **Why on the hot path:** wakeword runs every audio frame, so it is tiny, INT8/TRT, and
  ideally on a C++ audio node (no Python GIL) to keep it real-time.

### A2. Voice-activity detection + adaptive endpointing 🔶

- **Model:** Silero VAD v5 (ONNX, ~20 MB).
- **Role:** decide *when the utterance is complete*. A fixed timeout is wrong for children,
  who pause mid-thought. Endpointing is an early-fusion decision over: VAD speech/silence,
  the evolving STT partial transcript, ASR confidence, and explicit stop phrases.
- **Adaptive boundary rules** (`AdaptiveEndpointDetector`): soft cap 15 s, hard cap 45 s;
  commit on 0.8 s of silence — **unless** the last partial word is a continuation token
  ("and", "because", "so", "the"…), in which case keep listening; if the transcript is
  still changing after the soft cap, extend and (once) say "take your time, I'm listening."
- **Output:** the committed audio segment for the utterance.

### A3. Speech-to-text (STT/ASR) 🔶 — `fastwhisper_pkg`

- **Model (the only one):** **Faster-Whisper `small.en`** on the **CTranslate2** runtime,
  `device=cuda`, `compute_type="int8_float16"` (~500 MB resident, ~200–400 ms per utterance).
  This is the single planned configuration — no `whisper.cpp` variant. The backend is one
  config line (`device: cuda`, `compute_type: int8_float16`) in `fastwhisper_pkg/config.yaml`.
- **Input:** pre-roll (A1) + committed segment (A2).
- **Output:** a transcript string, e.g. *"why do we even check the discriminant"*.
- **Note:** `small.en` is English; Indian-English phrasing ("na", "pls") is handled
  downstream in text. Switching to a multilingual Whisper is a config change, not an
  architecture change.

### A4. Acoustic Echo Cancellation (AEC) ⏳ FUTURE — package being built

- **Status:** a **separate package currently under development**, to be added later. It is
  **not in the pipeline yet.**
- **Role when added:** remove the robot's own speaker output from the microphone signal so
  the mic can stay open *while Wini is talking* without hearing itself. AEC is the
  prerequisite for **full-duplex** operation and therefore for **barge-in (C3)**.
- **Until then:** the system is half-duplex (mic muted during TTS, §C2). No echo path, so no
  self-trigger.
- **Disfluency repair (further future):** conversational-repair / disfluency removal
  (a BERT-NER stripping "um, no I mean…") is **deliberately deferred** to a later phase. It is
  *not* part of this stage. When added it will sit after A3, before B0.

> **Handoff to Layer B:** Layer A delivers a single utterance string straight from STT.
> Wini's `InputProcessor` (B0) does deterministic normalization, so no repair step is
> required for the core to function.

---

## 4. LAYER B — The study core (BUILT) ✅

This is the system in `D:\cloud CLI`. It is the replacement for WINI_V2's entire study
package. Orchestrated by [`tutor_loop.py`](tutor_loop.py) (`TutorLoop.turn(text)`), which
runs the steps B0–B7 below for each utterance.

### B0. Input Processor — normalization ✅

- **Module:** [`cognitive_input_processor/input_processor.py`](cognitive_input_processor/input_processor.py).
- **What it does:** NFKC-normalizes the text, strips zero-width characters, collapses
  whitespace, and **preserves math** (symbols, equations like `b^2-4ac`, numbers). It does
  *not* paraphrase or lowercase the stored raw text — meaning is never compressed early.
- **Why it matters:** STT output is noisy; the math must survive so the concept resolver and
  the classifier see "b squared minus 4ac" intact.
- **Output:** the normalized utterance, fed to B1.

### B1. Cognitive Analyzer — what is going on in the student's head ✅

The analyzer ([`cognitive_analyzer/analyzer.py`](cognitive_analyzer/analyzer.py)) is the
replacement for the old intent router. It runs two MiniLM models and fuses them into a
**Student Cognitive Update**.

**B1a. Exemplar cognitive classifier (Part 1).**
[`cognitive_classifier/`](cognitive_classifier/classifier.py). All-MiniLM-L6-v2 (frozen,
384-dim) → a `knn + logistic-regression` ensemble over a 8 k-row exemplar bank, plus **9
deterministic surface-cue features** (question form, hint ask, self-correction "wait/
actually", answer attempt, etc.) that pooled embeddings dilute. Emits **36 multi-label
cognitive signals** with calibrated per-label thresholds: `confusion, curiosity,
low_confidence, frustration, request_representation, misconception_clue, request_hint,
self_correction, ready_for_next, graphical/…` etc. Test micro-F1 0.77 / macro-F1 0.62;
rule-governed labels (`question`, `request_hint`, `simplification_request`) at F1 1.0.

**B1b. Concept resolver (Part 2).**
[`concept_resolver/`](concept_resolver/resolver.py). MiniLM utterance vector → a
multinomial logistic head over **108 curriculum concepts + an ABSTAIN class** (blend of
card-anchor cosine + exemplar k-NN kept as fallback). Returns the architecture §6.3 schema:
primary `concept_id` + confidence + `secondary_concepts` + reason + `abstained`. When the
utterance names no concept ("this is so confusing"), it **abstains and inherits the session
concept**. Test top-1 0.89 / top-3 0.96; abstain F1 0.97. (The 10 originally-uncovered
concepts were filled with Qwen-generated utterances — `dataset/concept_gap_utterances.json`.)

**B1c. Fusion → Student Cognitive Update (Part 3).** `derive_cognitive_update` maps the raw
signal scores to the architecture §6.2 aggregates with documented deterministic formulas:
`confusion, curiosity, confidence, misconception_probability, transfer_attempt,
abstraction_attempt, self_correction, cognitive_load, engagement, frustration_risk`. Example
output for *"why do we even check the discriminant"*: `{confusion: 0.41, curiosity: 0.14,
cognitive_load: 0.22, …}` + concept `jemh104__discriminant_nature_of_roots`.

### B2. Learner State Model — the authoritative student memory ✅

- **Module:** [`learner_state.py`](learner_state.py) (`LearnerState`), persisted to
  `learner_state.json`.
- **Per-concept:** mastery (cold-start 0.30), misconception map **with status**
  (`active/weakening/resolved/recurring`), `representations_known/missing` (8-type
  taxonomy), `hint_dependency` (EMA) and current hint-chain position, struggle flags.
- **Global:** confidence, curiosity, cognitive_load, engagement (EMA-updated each turn by
  `apply_deltas`), and **`hope_rolling` {KI, KT, CT}** — the rolling 0–1 mastery of the
  three HOPE signals, consumed by retrieval ranking term w7.
- **The analyzer writes only soft state** (global EMA + concept *flags* such as
  `misconception_suspected`, `hint_requested`, `frustration_risk`). It **never** moves
  mastery from text — that is reserved for evidence-driven write-backs (B6), per the
  "probe before correcting" rule.

### B3. Pedagogical Decision Engine — choose the teaching move ✅

- **Rules (authoritative):** `tutor_loop.rules_decide` (v4) — ten ordered rules
  implementing architecture §6.6/§13. First match wins: misconception suspected →
  `MISCONCEPTION_PROBE`; hint asked → analogous example (never the answer); high
  load/frustration → `ENCOURAGE`; transfer-ready → `TRANSFER_PROBLEM`; representation gap →
  `REPRESENTATION_TRANSLATION`; self-corrected or **pure acknowledgment** →
  `METACOGNITIVE_REFLECT` (the v3 fix that stops re-explaining after "yes, got it");
  curiosity+low-confusion → `SOCRATIC_Q`; confusion default → `EXPLAIN`; else `QUIZ`.
  The misconception flag uses a dedicated lower threshold (0.4) because that signal is the
  classifier's weakest and probing is cheap.
- **Policy shadow (learning, non-authoritative):** [`policy_shadow/`](policy_shadow/shadow.py).
  A multinomial logreg over (MiniLM embedding + signal scores + §6.2 aggregates) → one of
  **15 tutor actions** (test top-1 0.56 / top-2 0.75 vs 0.20 majority). It runs every turn
  and is **logged beside the rule decision**; it does not act until it demonstrably beats
  the rules on real logged turns.

### B4. Retrieval Layer — assemble grounded, learner-fit evidence ✅

Reuses [`query.py`](query.py) machinery, over a **local MiniLM chunk index**
(`models/local_chunk_index/`, 1,017 NCERT chunks — the Gemini FAISS index is untouched).
Order, per architecture §6.7:

1. **Bridge gate (§6.8).** Walks 2 levels of `prerequisite_of` ancestors → `bridges_to`
   Class-9 predecessors; if a prerequisite's mastery is unknown/<0.6 and the learner isn't
   advanced, **prepend the recap + diagnostic** (prior knowledge activated before new
   content). The diagnostic outcome is graded next turn (B6).
2. **Misconception mechanics (§10).** For an active misconception, serve the
   **diagnostic only** (probe); `why_wrong`/`correct_idea` are withheld until a probe fails.
   Correction can never precede the probe by construction.
3. **Need evidence.** Per the decided action: transfer targets (near before far), KI
   integration links + the figure crop for a representation gap, CT probes within ±2 of the
   ZPD band, problem schemas + analogous worked examples, or the metacognitive prompt.
4. **7-term snapshot rerank.** Chunk candidates scored by
   `semantic + difficulty_fit + role_match + representation_gap_fit + misconception_priority
   + hint_dependency_penalty + hope_history_boost` — the last term boosts whichever HOPE
   signal is currently weakest. Served items are excluded (no-repeat).
5. **Cohesion check (§A1.5).** Structural rules always (2-hop scope, difficulty spread,
   ordering guard) + a **local Qwen contradiction judge** only when ≥3 evidence types mix
   (can drop only chunk/figure items; any failure drops nothing).
6. **Provenance manifest.** The turn returns `{evidence:[{id,type,why,…}], bridge_ids,
   schema_ids, ranking_trace, …}`. The response may compose **only** from these items.

### B5. Response generation — local Qwen, grounded ✅

- **Model:** Qwen2.5-3B-Instruct via **llama.cpp** (OpenAI-compatible server at
  `127.0.0.1:8080`, GPU). No Gemini, no offline stub — the hard project mandate.
- **`qwen_answer`** builds a prompt with: the chosen action's *tone* (e.g. for
  `MISCONCEPTION_PROBE` — "ask the diagnostic FIRST, don't reveal the correction"), the last
  6 turns of conversation memory ("don't repeat explanations already given"), and the
  manifest evidence — with an explicit rule to **never print internal IDs**. Output is
  produced sentence by sentence for streaming to Layer C.
- **Grounding guarantee:** only manifest text is in the prompt, so every sentence traces to
  an exact chunk / figure / bridge / misconception node.

### B6. Closed-loop write-backs — state moves on evidence ✅

The turn that *serves* a probe arms a pending check; the **next** student utterance closes it:

- **Diagnostic answers** (bridge or misconception): a hint request escalates the hint chain
  one level (`record_hint_request`, never past the answer); otherwise the reply is graded by
  local Qwen (`judge_answer` → correct/partial/wrong/not_an_answer, fail-safe to
  not_an_answer) and written back via `apply_probe_result` / `apply_bridge_result`. Verified:
  a wrong answer drives the misconception to `active` and mastery 0.30 → 0.20.
- **HOPE probe answers** (CT/KT/KI): if last turn served a `ct_probe` / `transfer_target` /
  `integration_target`, the student's attempt is scored 0–3 by the **HOPE detector** (Part 4,
  [`hope_detector/`](hope_detector/detector.py): answer-only MiniLM embedding + alignment/
  length scalars; discrimination gate strong−memorized ≥ 1 passes on all three signals) and
  folded into `hope_rolling` via `update_hope` (EMA). That rolling value feeds B4's w7 next
  turn — the loop is closed.
- **Representation write-back:** a confirmed `REPRESENTATION_TRANSLATION` marks the served
  representations as `known` (§9 coverage updates from evidence).

### B7. Persistence + session memory ✅

- **Learner state** saved to `learner_state.json` every turn (mastery, misconceptions,
  hope_rolling, flags, served-items no-repeat set, current concept).
- **Append-only learning log** `rag_store/learning_log.jsonl`: per turn — utterance, signals,
  cognitive update, chosen action + reason, **shadow suggestion**, full provenance manifest,
  write-back outcome, HOPE update. This is the training source for the neural policy and
  knowledge tracer once real sessions accumulate (architecture §12.2).
- **Transient context** (last 8 turns) kept in session for B5's conversation memory (§12.3).

---

## 5. LAYER C — Speech output (TTS)

Layer C turns the streamed reply text into audio. **It is half-duplex:** while Wini speaks,
the microphone is muted; Wini listens again only after speech completes. Barge-in is not
present yet (it needs AEC, A4 ⏳).

### C1. Sentence streaming 🔶

- **Splitter:** pysbd. As Qwen emits tokens, completed sentences are cut and handed to TTS
  immediately — Wini starts speaking the first sentence while the rest is still generating.
  This is the main perceived-latency lever.

### C2. Text-to-speech 🔶

- **Model (the only one):** **Kokoro TTS (82M)** ONNX → TensorRT engine (~300 MB resident,
  <80–100 ms per sentence, non-autoregressive, expressive). Default for all modes. (The
  Fish-Speech narration path from WINI_V2 is STORY-only and not part of the study core.)
- **Emotion:** primary = `[EMOTION:…]` tags the LLM injects; fallback = keyword rules; then
  pyrubberband pitch/tempo over 8 emotion profiles.
- **Mic gating (half-duplex contract):** on TTS start, set `robot_speaking = True` and
  **mute/disable the mic capture** (wakeword + VAD paused); on TTS completion, set
  `robot_speaking = False` and **re-enable the mic** (re-enter LISTENING). This is what makes
  barge-in unnecessary *and* unsafe right now — without AEC the open mic would hear the
  speaker and self-trigger.
- **Output:** PCM via sounddevice to the speaker.

### C3. Semantic barge-in ⏳ FUTURE — unwired until AEC

- **Deferred.** A semantic barge-in LSTM (backchannel vs genuine interrupt over the open mic)
  is **not wired** in this stage. It depends on AEC (A4 ⏳) to cancel the robot's own audio
  from the mic; without that, an open mic during TTS self-triggers.
- **When AEC lands:** flip the duplex contract — instead of muting the mic during TTS, run
  AEC + the barge-in LSTM on the cleaned mic stream; a genuine interrupt halts the TTS buffer,
  records the truncation point, trims context, and re-enters LISTENING. Until then, the child
  simply waits for Wini to finish, then speaks.

---

## 6. Perceived-latency budget

| Stage | Component | Typical | On hot path? |
|---|---|---|---|
| Wakeword | openWakeWord TRT | per-frame, ~ms | yes (tiny) |
| Endpoint | Silero VAD + adaptive | decision only | yes |
| STT | Faster-Whisper small.en, CTranslate2 int8_float16 CUDA | 200–400 ms | yes |
| **B1 analyzer** | MiniLM classify + resolve | ~100–150 ms | yes |
| **B4 retrieval** | local MiniLM rank + cohesion | ~50–150 ms | yes |
| **B5 LLM TTFT** | Qwen first sentence | ~600–900 ms | **masked by filler** |
| TTS | Kokoro per sentence | <100 ms | streamed |

(No disfluency-repair stage and no barge-in monitor at this stage — both arrive with AEC.)

**Filler trick:** within ~30 ms of B1 producing the action, an intent-conditioned filler
("Let me think about that for a moment.") is sent to TTS and spoken while B4+B5 run in
parallel. The child perceives an immediate response; the grounded answer follows seamlessly
as the first real sentence streams. **Exception:** never play a filler ahead of a diagnostic
question or a mode-switch confirmation — the child must hear the actual question.

---

## 7. What is local, and where it runs — paths are device-resolved

Everything is on-device. **The deployment target is the Jetson Orin Nano** (Linux). The
study core is *developed* on a Windows + GTX 1650 box, but it is written to deploy on the
Jetson, so **no path, model location, or endpoint is hard-coded** — each is resolved from a
per-device config/env at startup.

| | Dev box (development only) | **Jetson Orin Nano (deployment)** |
|---|---|---|
| OS / compute | Windows + GTX 1650 (CUDA) | Linux/JetPack 6, Orin Nano 8 GB (CUDA/TRT) |
| Filesystem root | `D:\cloud CLI\…` (Windows paths) | Linux paths under the device's install root |
| HF / model cache | `D:\HuggingFaceCache` (`HF_HOME`) | Jetson cache dir from `HF_HOME` on-device |
| LLM | Qwen2.5-3B-Instruct, llama.cpp, GPU | Qwen2.5-7B Q4_K_M, llama.cpp mmap |
| Embeddings | all-MiniLM-L6-v2 (torch) | MiniLM ONNX (shared, TRT-EP) |
| LLM endpoint | `http://127.0.0.1:8080` (from env) | local llama.cpp server (from env) |
| Study core | ✅ built (Layer B) | same code, retargeted by config |
| Speech I/O | not run on dev box | 🔶 openWakeWord / Faster-Whisper / Kokoro |

**Path-resolution rule (mandatory):** all locations come from a single device config layer
(env vars + a `device_config.yaml`), e.g. `WINI_STORE_DIR`, `WINI_MODELS_DIR`,
`WINI_LLM_URL`, `HF_HOME`. Code must read these, never embed `D:\…` or `/home/…` literally.
The illustrative paths elsewhere in this doc (`rag_store/`, `models/…`, `127.0.0.1:8080`) are
**dev-box values**; on the Jetson they resolve to the device's own locations. Moving to the
Jetson is then a deployment exercise (quantize the LLM to 7B-Q4; MiniLM/Whisper/Kokoro to
ONNX-TRT; point the config at Jetson paths), not an architecture change.

---

## 8. Old WINI_V2 study stack → current core (the replacement map)

| WINI_V2 study component | Replaced by (built) | Why |
|---|---|---|
| `wini_intent_pkg` (sigmoid router, K-means, slot filling) | **B1 Cognitive Analyzer** (exemplar classifier + concept resolver) | model cognition, not intent; multi-label signals + abstaining concept resolution |
| DKVMN knowledge tracer | **B2 Learner State** (rule write-backs now; neural KT deferred to real logs) | no synthetic KT; mastery moves on probe/bridge evidence |
| PPO pedagogy policy + hint BANK | **B3 rules_decide (v4) + policy shadow** | rules first; the shadow learns from logged turns before promotion |
| `wini_rag_pkg` FAISS + reranker | **B4 Retrieval** (7-term learner-state ranking + manifest + cohesion) | learner-state-aware, grounded, auditable |
| `answer_grader` + HOPE detectors (NLI) | **B6 + `hope_detector/`** (ordinal KI/KT/CT) + Qwen `judge_answer` | trained detectors with a verified discrimination gate |
| Socratic LoRA on Qwen-7B | **B5 prompt-conditioned Qwen-3B** (action tone + manifest) | no adapter needed at this scale; grounding via manifest |
| Curriculum graph + Node2Vec | **`rag_store/` graph (schema v2)** — bridges, schemas, hint chains, CT probes, figure crops | one structure serving prerequisites + transfer + integration + probes |

**Kept from WINI_V2 unchanged:** the entire speech stack (Layers A & C), the filler trick,
the adaptive endpoint, the barge-in policy, and the edge-first/zero-cloud philosophy.

---

## 9. Component & model inventory

| Layer | Component | Model / module | Status |
|---|---|---|---|
| A1 | Wakeword | openWakeWord TRT | 🔶 |
| A2 | VAD/endpoint | Silero v5 ONNX + AdaptiveEndpointDetector | 🔶 |
| A3 | STT | Faster-Whisper small.en, CTranslate2 int8_float16 (CUDA) | 🔶 |
| A4 | AEC (echo cancellation) | `aec_pkg` (being built) — enables full-duplex/barge-in | ⏳ |
| A4+ | Disfluency repair | BERT NER INT8 | ⏳ deferred |
| B0 | Normalize | `cognitive_input_processor/` | ✅ |
| B1 | Classifier | `cognitive_classifier/` (MiniLM knn+logreg+cues, 36 labels) | ✅ |
| B1 | Resolver | `concept_resolver/` (MiniLM logreg, 108+ABSTAIN) | ✅ |
| B1 | Analyzer | `cognitive_analyzer/` (Student Cognitive Update) | ✅ |
| B2 | Learner state | `learner_state.py` (+ `update_hope`, write-backs) | ✅ |
| B3 | Pedagogy | `tutor_loop.rules_decide` + `policy_shadow/` | ✅ |
| B4 | Retrieval | `query.py` + `models/local_chunk_index/` | ✅ |
| B4/B6 | HOPE detector | `hope_detector/` (ordinal KI/KT/CT) | ✅ |
| B5 | LLM | Qwen2.5-3B via llama.cpp (GPU) | ✅ |
| B7 | Store | `rag_store/` (concepts, graph, chunks, FAISS, bridges, HOPE bank) | ✅ |
| C1 | Sentence split | pysbd | 🔶 |
| C2 | TTS + mic-gate | Kokoro ONNX/TRT; half-duplex mic mute on `robot_speaking` | 🔶 |
| C3 | Barge-in | semantic LSTM | ⏳ unwired (needs AEC) |
| orch | Tutor loop | `tutor_loop.py` (`TutorLoop.turn`) | ✅ |

---

## 10. End-to-end worked example (one spoken turn)

> Child, mid-lesson on quadratics, says aloud: **"a quadratic always has two real roots na,
> that's the rule, right?"**

1. **A1** openWakeWord already fired this session; the mic stream + 500 ms pre-roll flow in
   (mic is live because Wini is not currently speaking — half-duplex).
2. **A2** Silero detects 0.8 s silence after "right?", no continuation token → commit.
3. **A3** Faster-Whisper (CTranslate2 int8_float16, CUDA) →
   *"a quadratic always has two real roots na that's the rule right"*.
4. **A4** AEC/disfluency not present at this stage → transcript passes straight to B0.
5. **B0** normalized; math/keywords preserved.
6. **B1** classifier fires `misconception_clue` (≈0.6), `question`; resolver →
   `jemh104__discriminant_nature_of_roots` (conf 0.53). Update: `misconception_probability
   0.62` → flag `misconception_suspected`.
7. **B3** rules → `MISCONCEPTION_PROBE` (shadow logged: also MISCONCEPTION_PROBE).
8. **B4** serves the concept's misconception **diagnostic only** (probe-first); manifest
   built; arms `pending_check`.
9. **B5** Qwen, given the "ask the diagnostic, don't reveal the correction" tone + manifest:
   *"Let's test that — what does the discriminant b²−4ac tell you when it's negative?"*
10. **C1/C2** first sentence streams to Kokoro; `robot_speaking=True` mutes the mic while it
    plays (~filler covered the wait); on completion the mic re-enables.
11. **Next turn** the child answers; **B6** grades it with Qwen `judge_answer`. Wrong →
    `apply_probe_result`: misconception → `active`, mastery 0.30 → 0.20, persisted (**B7**);
    next retrieval now serves `why_wrong` + `correct_idea` + the refuting figure crop. The
    loop has closed and moved the learner model on evidence.

---

## 11. What remains to build for full voice

The study core (Layer B) is complete and verified. **All Layer A/C work happens on the
Jetson Orin Nano**, not on the dev box. Remaining integration (🔶/⏳), all specified in
`WINI_V2_ARCHITECTURE.md`:

1. Wakeword + VAD + **Faster-Whisper/CTranslate2** STT nodes feeding text into
   `TutorLoop.turn`.
2. Sentence-streaming wrapper around `qwen_answer` (it returns full text today; switch to
   token streaming + pysbd).
3. Kokoro TTS node with the **half-duplex mic-gate** (mute on `robot_speaking`); **no
   barge-in** yet.
4. The filler bank on the B1→B4/B5 gap.
5. **Device config layer** so every path/model/endpoint resolves per-device (dev box vs
   Jetson) — no hard-coded paths.
6. On Jetson: quantize Qwen to 7B-Q4; MiniLM/Whisper/Kokoro to ONNX-TRT.

**Deferred to a later phase (⏳):** `aec_pkg` (Acoustic Echo Cancellation) → then full-duplex
+ semantic barge-in (C3); and disfluency repair after AEC.

Data/human items unchanged from the build plan: human re-label of the HOPE answer set for
absolute calibration, an `acknowledgment` label data pass, shadow-policy promotion review,
and neural knowledge tracing once the learning log has real sessions.
