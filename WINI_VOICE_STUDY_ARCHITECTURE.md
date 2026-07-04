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
>
> **⚑ AS-BUILT (2026-06-16):** Layers A & C are now **built and verified on the Jetson Orin
> Nano** (Phases 0–5). The realized system differs from §1–§11 in several places — LLM is
> **in-process** (not a `:8080` server), TTS runs on the **onnxruntime CUDA EP** (Kokoro→
> TensorRT proved impossible), MiniLM is **CPU**, and the wakeword/STT nodes gained
> anti-self-trigger fixes. **§12 is the authoritative as-built record**; where §1–§11 and §12
> disagree, §12 wins. Inline spots that changed are flagged `(as-built: §12)`.

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
actually", answer attempt, etc.) that pooled embeddings dilute. Emits **38 multi-label
cognitive signals** with calibrated per-label thresholds: `confusion, curiosity,
low_confidence, frustration, request_representation, misconception_clue, request_hint,
self_correction, ready_for_next, acknowledgment, graphical/…` etc. Test micro-F1 0.83 /
macro-F1 0.69 (fixed-source rebuild 2026-06-19); rule-governed labels (`question`,
`request_hint`, `simplification_request`, `acknowledgment`) at F1 1.0 / near-1.0.

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
  **14 tutor actions** (test top-1 0.68 / top-2 0.84 vs 0.41 majority; fixed-source rebuild
  2026-06-19). It runs every turn
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

- **Model:** Qwen2.5-3B-Instruct via **llama.cpp**, GPU. No Gemini, no offline stub — the
  hard project mandate. **(as-built: §12)** On the Jetson this is **in-process**
  (`llm_local.py`, `llama-cpp-python` built from source) wired directly into the brain node —
  **not** the `127.0.0.1:8080` HTTP server (that was the dev-box form).
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

- **Model (the only one):** **Kokoro TTS (82M)**, non-autoregressive, expressive. Default for
  all modes. (The Fish-Speech narration path from WINI_V2 is STORY-only and not part of the
  study core.) **(as-built: §12)** Runs on the **onnxruntime CUDA EP**, **not** a TensorRT
  engine — TRT 10.3 cannot parse Kokoro's vocoder `STFT` op. Real measured throughput is
  **RTF ≈ 0.17 (~0.5–0.8 s/sentence)**, not <100 ms; perceived latency is hidden by
  sentence-streaming + a callback playback stream that never underruns.
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
| **B5 LLM TTFT** | Qwen first sentence | spec ~600–900 ms; **as-built ~3.4 s** (prefill of the large grounded prompt — §12.9) | **to be masked by filler** |
| TTS | Kokoro per sentence | spec <100 ms; **as-built ~0.5–0.8 s** (RTF 0.17, ORT-CUDA — §12.8) | streamed (gapless, no underrun) |

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
| LLM | Qwen2.5-3B-Instruct, llama.cpp, GPU | **Qwen2.5-3B Q4_K_M, in-process llama.cpp** (as-built §12.6) |
| Embeddings | all-MiniLM-L6-v2 (torch) | **MiniLM torch on CPU** (as-built §12.4; avoids 2nd CUDA ctx) |
| LLM endpoint | `http://127.0.0.1:8080` (from env) | **none — in-process** (`llm_local.py`, no HTTP server) |
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
| A1 | Wakeword | openWakeWord **ONNX (CPU)**; continuous-feed + thr 0.5 + debounce + `/robot_speaking` gate | ✅ §12.9 |
| A2 | VAD/endpoint | spec Silero v5 + AdaptiveEndpointDetector; **as-built RMS-energy endpointing in `fastwhisper_node`** | ⚠️ divergent §12.10 |
| A3 | STT | Faster-Whisper small.en, **CTranslate2 int8_float16 CUDA built from source**, resident, + halluc filter | ✅ §12.5 |
| A4 | AEC (echo cancellation) | `aec_pkg` (being built) — enables full-duplex/barge-in | ⏳ |
| A4+ | Disfluency repair | BERT NER INT8 | ⏳ deferred |
| B0 | Normalize | `cognitive_input_processor/` | ✅ |
| B1 | Classifier | `cognitive_classifier/` (MiniLM evidence+logreg+cues, 38 labels) | ✅ |
| B1 | Resolver | `concept_resolver/` (MiniLM logreg, 108+ABSTAIN) | ✅ |
| B1 | Analyzer | `cognitive_analyzer/` (Student Cognitive Update) | ✅ |
| B2 | Learner state | `learner_state.py` (+ `update_hope`, write-backs) | ✅ |
| B3 | Pedagogy | `tutor_loop.rules_decide` + `policy_shadow/` | ✅ |
| B4 | Retrieval | `query.py` + `models/local_chunk_index/` | ✅ |
| B4/B6 | HOPE detector | `hope_detector/` (ordinal KI/KT/CT) | ✅ |
| B5 | LLM | Qwen2.5-3B via **in-process** llama.cpp (GPU); `llm_local.py` | ✅ §12.6 |
| B7 | Store | `rag_store/` (concepts, graph, chunks, FAISS, bridges, HOPE bank) | ✅ |
| C1 | Sentence split | pysbd (streamed from `llm_local.stream_sentences`) | ✅ §12.6 |
| C2 | TTS + mic-gate | **Kokoro ONNX on onnxruntime CUDA EP** (not TRT); half-duplex mute + `/tts_done`; callback playback | ✅ §12.8 |
| — | Brain node | `wini_brain_pkg` (`TutorLoop.turn` → `/llm_out`, owns gate True edge) | ✅ §12.7 |
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

---

## 12. AS-BUILT JETSON DEPLOYMENT (Phases 0–6) ✅

> This section is the authoritative record of what was actually deployed on the **Jetson
> Orin Nano** (JetPack R36.5, CUDA 12.6, Python 3.10, ROS 2 Humble, venv at
> `ROS2WS_audio_pipeline/.venv`). It supersedes the 🔶/⏳ status and several model claims in
> §1–§11 where they differ. The §1–§11 design intent is unchanged; the items below are the
> realized engineering. Layers A and C are now **BUILT and verified end-to-end**, not just
> specified. Where reality forced a deviation from the spec it is called out explicitly.
>
> **⚑ Phase 6 (2026-06-22):** the study core was refreshed from the workspace — the **T9
> on-screen display channel** (the robot now *shows* the chosen figure crop), the grading-loop
> fixes, the fixed-source **38-label classifier / 14-action policy**, and the **T10 spoken-budget
> governor**. Verified by a 10-utterance topic-driven full-pipeline run (brain→Qwen→TTS→display).
> Details in **§12.11**.

### 12.1 Spec → as-built deltas (read this first)

| Item | §1–§11 spec | **As-built on Jetson** | Why it changed |
|---|---|---|---|
| LLM serving | llama.cpp HTTP server `127.0.0.1:8080` | **in-process** `llama-cpp-python` (`llm_local.py`), wired directly into the brain node | one process speech→LLM→TTS; no server to manage |
| LLM model | Qwen-7B-Q4 on Jetson | **Qwen2.5-3B-Instruct Q4_K_M** GGUF (2.1 GB), all layers on GPU | fits the 8 GB pool beside Whisper+Kokoro |
| MiniLM (B1) | ONNX, TRT-EP, GPU | **torch on CPU** (`WINI_MINILM_DEVICE=cpu`) | avoids a 2nd in-proc CUDA context that crashed teardown next to llama.cpp; ~84 ms, within the B1 budget |
| STT (A3) | small.en / CUDA / int8_float16 | **exactly that**, but **CTranslate2 built from source** (no aarch64 CUDA wheel exists); model **resident**; **+ hallucination filter** (new) | source build for sm_87; resident kills per-session reload |
| Wakeword (A1) | openWakeWord **TRT**, 500 ms pre-roll | openWakeWord **ONNX on CPU**; **continuous feed + threshold 0.5 + 2-frame debounce + refractory**; **gated on `/robot_speaking`** (new); pre-roll not wired | TRT not needed for a tiny model; the rewrite fixes false-firing (12.7) |
| VAD/endpoint (A2) | Silero v5 + `AdaptiveEndpointDetector` | **RMS-energy endpointing inside `fastwhisper_node`** (Silero not wired) | as-built divergence — see 12.8 (open item) |
| TTS (C2) | Kokoro ONNX→**TensorRT**, **<80–100 ms/sentence** | Kokoro ONNX on **onnxruntime CUDA EP** (TensorRT **impossible** — see 12.6); **RTF ≈ 0.17 (~0.5–0.8 s/sentence)**; callback-streamed | TRT 10.3 can't parse Kokoro's `STFT` op |
| TTS latency claim | sub-100 ms | **NOT achievable** for full-sentence neural TTS on this device | physical limit; masked by sentence-streaming |
| Half-duplex | mute mic on `robot_speaking` | same, **+ new `/tts_done` topic**; brain owns the True edge, TTS owns the False edge; **wakeword also gated** | streaming reply needs an explicit end-of-turn signal |
| Hot-path TTFS | ~600–900 ms LLM TTFT, filler-masked | **~3.4 s** (Qwen prefill of the large grounded prompt); filler + prompt-trim tuning still pending | measured; see 12.9 |
| Display (T9) | audio-only (no visual channel in §1–§11) | brain publishes the chosen figure crop as `sensor_msgs/Image` to the **existing `display_controll` node** on `/wini/display/image` (rgb8 480×320, ~5 Hz keepalive) | §9 "show, don't only tell" on the robot screen — see 12.11 |
| Spoken budget (T10) | per-action only | brain `PacingController` caps each reply to an action-appropriate word/sentence budget | shorter voice turns under load — see 12.11 |
| B1 models | 36-label classifier / 15 actions | **38-label (+`acknowledgment`) classifier / 14-action policy**, built from `exemplar_dataset_10000_fixed.json` | fixed-source rebuild — see 12.11 |

### 12.2 Topic graph (as-built)

```
wakeword_node ──/wake_word──► fastwhisper_node ──/speech_text──► wini_brain_node
 (openWakeWord ONNX, CPU)       (small.en, CT2 CUDA,             (TutorLoop + in-proc
        ▲                        resident, halluc-filter)         Qwen-3B GPU; MiniLM CPU)
        │ gated                                                        │
        │                                                   /llm_out (one sentence/msg)
        └──────────── /robot_speaking (half-duplex mic gate) ──┐   /tts_done
                                                               │       │
                              brain sets True on utterance ────┘       ▼
                              TTS sets False after last sentence   wini_tts_node
                                                                 (Kokoro GPU, ORT-CUDA,
                                                                  callback stream → USB speaker)
```
**T9 display branch (Phase 6).** `wini_brain_node` also publishes the chosen figure crop to the
**existing** display node (from the robot's display workspace, `~/Downloads/ros2_ws`), no new
package:

```
wini_brain_node ──/wini/display/image (sensor_msgs/Image, rgb8 480×320, ~5 Hz keepalive)──►
    display_controll/wini_display   (SPI screen; overrides the eyes while a figure is shown,
    auto-reverts to the face ~0.5 s after frames stop). Brain clears it on the /robot_speaking
    False edge at end of turn.
```
Retired and **not launched**: `llm_pkg` (ollama) and `intent_pkg` (their source is left in
place). Bringup: `ros2 launch wini_brain_pkg wini_pipeline.launch.py`.

### 12.3 Phase 0 — study core imports clean on the Jetson (no cloud deps) ✅

- Created symlink **`wini_core` → `cloud CLI`** (flat modules, no package) so ROS nodes import
  the study core by bare name (as `tutor_loop` already imports its siblings).
- Made `faiss`, `google-genai`, `rank_bm25`, `rapidfuzz`, `python-dotenv` **lazy imports**
  inside the functions that use them (`rag_core.py`, `query.py`) — they were top-level and
  blocked import; `google-genai` is also forbidden by the Qwen-only mandate.
- `load_store(store, with_index=False)` now skips the FAISS index (the loop ranks with the
  local MiniLM index, so faiss is never needed on the Jetson).
- Fixed `query.load_store` networkx call to pass `edges="edges"` (graph.json uses the "edges"
  key; networkx 3.4.2 defaults to the deprecated "links").
- Added stdlib-only **`device_config.py`** (env-resolved paths; `minilm_device` default `cpu`;
  LLM GGUF path; Kokoro paths) — the device-config layer §7/§11 called for.
- **Verified:** `import tutor_loop` succeeds with none of faiss/genai/bm25/rapidfuzz/dotenv
  installed. Those 5 must **not** be installed.

### 12.4 Phase 1 — MiniLM (B1) on CPU ✅

- Installed `sentence-transformers 5.5.1` **`--no-deps`** (transitive deps already present;
  torch/numpy/transformers pins untouched). `all-MiniLM-L6-v2` in the existing HF cache
  (`HF_HOME=~/.cache/huggingface`). Analyzer smoke test ~84 ms/encode on CPU.
- The classifier/resolver/HOPE detector load with `device="cpu"` from `device_config`.

### 12.5 Phase 1.5 — CTranslate2 CUDA from source (STT runtime) ✅

- No aarch64 CUDA wheel for CTranslate2 exists → built **v4.7.1** (matches faster-whisper
  1.2.1) from source (`build_ct2_cuda.sh`): `-DWITH_CUDA=ON -DWITH_CUDNN=ON -DWITH_MKL=OFF
  -DCMAKE_CUDA_ARCHITECTURES=87 -DBUILD_CLI=OFF`, `make -j4`.
- Python binding needs pybind11 ≥2.10 → pinned `pybind11==2.13.6`.
- **Runtime:** vendored `libctranslate2.so*` into the venv `ctranslate2/` package dir +
  `patchelf --set-rpath '$ORIGIN'` on `_ext*.so` → loads with **no `LD_LIBRARY_PATH`**.
  `ctranslate2.get_cuda_device_count() == 1`. `fastwhisper_node` flipped to
  `small.en / cuda / int8_float16`, **model resident** (loaded once in `__init__`, no
  per-session load/unload).

### 12.6 Phase 2 — in-process Qwen, fully streaming ✅

- Built **`llama-cpp-python 0.3.29` from source with CUDA** (`build_llamacpp_cuda.sh`:
  `CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=87"`). **The jetson-ai-lab prebuilt
  `0.3.14` cu126 wheel crashes on every generation** (`llama_kv_cache_unified::seq_rm` assert
  — wrapper/llama.cpp API mismatch), so source build is mandatory.
- New **`llm_local.py`** (in-proc singleton): `complete()` (blocking, for the grader/cohesion
  judge), `stream_tokens()`, and `stream_sentences()` (pysbd, decimal-safe). One generation
  lock (llama.cpp is not reentrant; the pipeline is half-duplex).
- Patched `tutor_loop.py`: `qwen_chat` → `llm_local.complete` (the `:8080` `requests.post`
  is gone); split `qwen_answer` into `build_answer_prompt` + `qwen_answer`; `turn(text,
  on_sentence=None)` streams sentences to the callback and reassembles the full text for
  book-keeping.
- **Teardown-crash fix:** wired `device_config.minilm_device` into `TutorLoop` so MiniLM runs
  on CPU. With torch-MiniLM **and** llama.cpp both opening CUDA contexts in one process,
  process exit crashed (`Py_FinalizeEx → llama_free → ggml_cuda_error`). MiniLM-on-CPU leaves
  llama.cpp as the only CUDA user → clean exit.
- Toolchain gotchas: upgraded venv pip (old pip's build isolation broke scikit-build-core
  metadata); that pulled setuptools 82 which breaks colcon → pinned **`setuptools<80`**.

### 12.7 Phase 3 — `wini_brain_pkg` brain node ✅

- New ament_python package; node `wini_brain_node` (entry `brain_node`). Adds `wini_core` to
  `sys.path`, subscribes `/speech_text`, runs `TutorLoop.turn(text, on_sentence=cb)` on a
  worker thread (one turn at a time), streams each sentence to `/llm_out`.
- Half-duplex: publishes `/robot_speaking=True` the instant an utterance arrives, `/tts_done=
  True` once generation completes; releases the gate itself on an empty reply / exception.
- TutorLoop + **Qwen pre-warm** (`llm_local.complete("hi", max_tokens=4)`) run in a background
  thread at startup (utterances before `ready` are dropped). Verified end-to-end; TTFS ≈ 3.4 s.

### 12.8 Phase 4 — Kokoro TTS on the GPU ✅ (TensorRT ruled out)

- **TensorRT investigation (decisive):** native Kokoro→TRT engine **fails** — TRT 10.3's ONNX
  parser rejects the vocoder's `STFT` op (`checkSTFT`). Piper→TRT also fails (float `scales`
  → `Range` shape-tensor type error). CPU Kokoro is too slow (**RTF ≈ 2.4**). Chosen path:
  **Kokoro on GPU via onnxruntime CUDA EP** → **RTF ≈ 0.17** (~0.5–0.8 s/sentence, 14× CPU).
- Installed `onnxruntime-gpu 1.24.0` (jetson-ai-lab `jp6/cu126`) **`--no-deps`** after
  `pip uninstall onnxruntime` → **numpy stays 1.24.4**. Providers become
  `[Tensorrt, CUDA, CPU]`; **openWakeWord hardcodes `CPUExecutionProvider`, so it's
  unaffected.** `kokoro-onnx 0.5.0` + `phonemizer-fork` + `espeakng-loader` (bundles the
  espeak-ng binary — no apt) installed `--no-deps` because kokoro pins a false `numpy>=2`
  floor (runs fine on 1.24). Models: `kokoro-v1.0.onnx`, `voices-v1.0.bin`.
- Rewrote `wini_tts_node` (Piper→Kokoro): resident model, `ONNX_PROVIDER=CUDAExecutionProvider`
  (forces CUDA, skips the TRT-EP/STFT failure), **two-stage synth-ahead pipeline** (synth
  worker → audio queue → play worker) so sentences play back-to-back, `_END` sentinel releases
  the gate, and `clean_for_tts()` strips LaTeX/markdown (`\(3x^2\)` → "3 x to the power 2").

### 12.9 Phase 5 — integration, audio output, and robustness fixes ✅

- **Launch:** `src/wini_brain_pkg/launch/wini_pipeline.launch.py` brings up wakeword →
  fastwhisper → brain → tts, sets `HF_HOME`, `WINI_MINILM_DEVICE=cpu`,
  `ONNX_PROVIDER=CUDAExecutionProvider`. All 4 nodes ready ~9 s, no crashes, no OOM.
- **VRAM (all resident):** Whisper-CUDA + Qwen-GPU + Kokoro-GPU + MiniLM-CPU ≈ **6.2 GB /
  7.6 GB** — tight but stable. (Co-load is sensitive to stray processes holding GPU memory.)
- **Audio:** the mic+speaker is one USB **C-Media PnP** device (ALSA card 0). It rejects 24 kHz
  / 16 kHz raw, so everything routes through **PulseAudio** (USB set as default sink+source via
  `pactl`); TTS plays via `output_device='pulse'` (Pulse resamples Kokoro's 24 kHz). Speaker
  output **confirmed audible**.
- **Self-trigger fix #1 (Whisper hallucination):** on near-silence Whisper emitted filler
  ("Thank you."). `fastwhisper_node.process_command` now uses `no_speech_threshold=0.6,
  condition_on_previous_text=False` and drops a transcript when empty, or
  `max no_speech_prob>0.6 & min avg_logprob<-0.5`, or it matches a hallucination blocklist.
- **Self-trigger fix #2 (acoustic feedback):** `wakeword_node` now subscribes
  `/robot_speaking` (drains callbacks via `spin_once`) and **runs no detection while the robot
  speaks** → 0 wakeword fires during playback.
- **Wakeword false-fire root cause (12.7 model was fine; the node was wrong):** it fed
  openWakeWord **discontinuously** (only when RMS≥0.02, replaying a 1 s buffer), which corrupts
  the streaming model's rolling features; the ambient floor (~0.024 RMS) sat on the 0.02 gate
  causing constant flapping; `THRESHOLD=0.15` was below the ambient score ceiling (~0.16–0.17;
  digital silence scores ~0.001, the real word ~0.8+); and `hit_count>=1` fired on one frame.
  **Fix:** feed `model.predict()` **every** chunk; `THRESHOLD=0.5`; `TRIGGER_FRAMES=2`
  consecutive; `REFRACTORY_SEC=2.0`. **Verified: 0 fires over 40 s of silence** (was ~6/35 s).
- **ALSA underrun fix:** `snd_pcm underrun occurred` during playback. Per-sentence `sd.play`,
  then persistent blocking `write()` (even at 0.3 s buffer) still under-ran at stream
  boundaries. **Final fix: callback-driven `sd.OutputStream(callback=…)`** — the play worker
  appends float32 blocks to a lock-guarded `deque`; the pull callback fills each block from the
  deque or **silence when empty**, so the device buffer cannot starve. **Verified: 0 underruns
  over 41 sentences / 2 long turns under full GPU contention.** Param `playback_latency=0.3`.

### 12.10 Remaining / open items

1. **VAD divergence:** the spec's Silero v5 + `AdaptiveEndpointDetector` (A2) is **not** the
   as-built path — `fastwhisper_node` uses RMS-energy endpointing. Reconcile (wire Silero) or
   formally adopt the RMS approach in the spec.
2. **Latency tuning (Qwen TTFS ~3.4 s):** add the filler bank (§6) on the B1→B5 gap, trim the
   evidence prompt (≤3000 chars), and cap reply length. Reply length **is now capped (Phase 6
   T10 governor)**; the **filler bank + prompt-trim are still pending** and remain the main
   perceived-latency win.
3. **Wakeword still false-fires on ambient occasionally** (THRESHOLD sensitivity) — now
   **harmless** (the Whisper filter drops the resulting noise), but `THRESHOLD`/`TRIGGER_FRAMES`
   are tunable if a live "weenee" is ever missed.
4. **Session reset on wake:** `learner_state.json` persists across runs (by design), so a
   prior session's transient context can leak into a fresh launch; consider clearing the
   session context (not the learner model) on `/wake_word`.
5. **Sub-100 ms TTS, AEC, full-duplex barge-in (C3), disfluency repair, wakeword pre-roll**
   remain deferred (⏳) as in §11.
6. **Live human voice test** is the one unverified path (injected `/speech_text` bypasses
   Whisper) — only a person speaking can validate mic→STT accuracy. Everything **downstream**
   of `/speech_text` (brain → Qwen → TTS → display) is verified by the Phase 6 topic-driven
   10-utterance run (§12.11); only mic→STT remains.

### 12.11 Phase 6 — study-core refresh, T9 display, T10 pacing (2026-06-22) ✅

Ported the workspace's post-Phase-5 work onto the live Jetson (study core via the `wini_core`
symlink; ROS pkgs are `--symlink-install` so `src/` edits are live without a rebuild). Because
the Jetson runs the **in-process** branch (`llm_local` + streaming), the study-core changes were
applied as a **3-way merge**, never a copy. `wini_core` + `src` are backed up under
`_wini_backups/` and the prior models under `wini_core/_wini_model_backup_*`.

- **T9 multimodal display channel (flagship).** `tutor_loop.turn()` now returns a `display` list
  (≤1 figure crop/turn): `_build_display` picks the pedagogy-gated `figure` crop, or an incidental
  `figure_caption` crop only for the visual actions (`REPRESENTATION_TRANSLATION` / `VISUAL_ANALOGY`).
  `image_path` stays **store-relative**. The brain node resolves it against `tutor_loop.STORE`,
  letterboxes the crop to **480×320 rgb8**, and publishes a `sensor_msgs/Image` to the **existing**
  `display_controll/wini_display` node on `/wini/display/image`, **republished at ~5 Hz** (the
  display reverts to the eyes if no frame arrives within its 0.5 s timeout); it is cleared on the
  `/robot_speaking` False edge at end of turn. **No new package** — Wini's display already existed.
  On display turns Qwen is cued to *refer to the figure on screen*.
- **Grading-loop fixes** (merged from the workspace `f6b0071`): rule 1b (an explicit "I don't
  understand / make it simpler" → re-explain, never a Socratic challenge or a re-probe); a
  deterministic **non-attempt guard** so an ack / confusion-plea / fresh question is never graded
  `wrong` and never moves mastery; and **`ct_probe` is HOPE-scored only**, never armed as a graded
  misconception. New standalone cues `is_clarification_request` / `is_answer_attempt` (not in the
  feature vector — no model rebuild needed).
- **Fixed-source models.** Swapped in the artifacts built from `dataset/exemplar_dataset_10000_fixed.json`:
  the **38-label classifier** (adds `acknowledgment`, test micro-F1 0.83) and the **14-action policy
  shadow** (top-1 0.68). Runtime modules (`classifier.py`/`resolver.py`/`shadow.py`) were
  byte-identical (device comes from `.load(device=…)`), so only the data artifacts + `label_space.py`
  changed; classifier and policy are swapped **together** (the policy logreg width tracks the
  38-label signal vector).
- **T10 spoken-budget governor.** Copied the `pacing/` package and wired `PacingController` into the
  brain node (`before_turn` → action-appropriate `answer_budget` + reused analysis;
  `turn(answer_budget=…, precomputed_analysis=…)`; `after_turn` pace ledger). The streamed reply is
  capped to the action's sentence budget. **Deliberate deviation:** the robot does **not** honour the
  controller's `clarify`/`confirm_shift` *canned answers* — its triage canned-responds to any ≤1-word
  input, which would block legitimate 1-word maths answers ("zero", "yes") from the grader, so every
  turn goes through the tutor. All pacing is best-effort (falls back to a plain turn on any error).
- **Streaming clip fix.** `stream_sentences` flushes its trailing buffer even with no terminal
  punctuation; when the model stops mid-sentence that tail was spoken verbatim ("…parabolic graphs:
  graph"). The streaming path now trims a non-terminated final item to its last complete clause via
  `_clean_dangling_tail` (or drops a bare scrap), so TTS never ends a reply mid-thought.

**Verification.** Study-core guard suite T6–T9 **11/11** (analyzer + retrieval + grading + display,
Qwen stubbed). Live **topic-driven full-pipeline run, 10/10 turns** (wakeword/Whisper bypassed by
publishing `/speech_text`): every turn was accepted, spoke through Kokoro, and cycled the half-duplex
gate; the 2 graphical requests published the `jemh102` parabola crop to `/wini/display/image` (correct
480×320 rgb8) and Qwen referred to it on screen; the other 8 were audio-only; pedagogy actions and the
T10 budgets were applied throughout.

**Still open after Phase 6:** the filler bank + prompt-trim for TTFS (§12.10.2), live mic→STT
(§12.10.6), and the deferred AEC / full-duplex / barge-in set (§11).
