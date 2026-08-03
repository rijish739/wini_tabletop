# Part 15 — Cloud execution plan: the whole architecture, warm and streaming

**Status:** **EXECUTED 2026-07-25 — Phases A / B / C / E BUILT + verified, D partial, F
deferred.** See `complete_architecture_build_plan.md` §17 (PART 15) for measured results, the
state-persistence contract in `learner_cognitive_state_architecture.md` (§ State persistence
backend), and deploy gotchas in `rag_memory.md`. Live service: `wini-brain` on Cloud Run
(asia-south1, min-instances=1). **Key deviation from this plan:** the Gemini 3.x / Flash-Lite
model swap (§3, §6 Phase C) is a measured *regression* on this project — those models don't
exist and `gemini-2.5-flash-lite` (global-only) is slower than `gemini-2.5-flash@asia-south1`;
Phase C shipped as the revertible model-tier *seam*, not a swap. Phase D's client-side live
streaming and Phase F remain open (see §17 "What is NOT done").

_(Original plan text follows, unchanged, as the design of record.)_

> **Filename note.** Build-plan §16 already owns "PART 14" (brain audit remediation), so
> this — the next item in the lockstep sequence — is **Part 15**.

Design of record for running the *entire* Wini architecture in the cloud with human-type
interaction latency, **without losing a single point of pedagogical accuracy**. It builds
directly on Part 13 (streaming) and Part 11 (Gemini perception + generation).

---

## 1. The finding that shapes everything

**The brain is already a cloud-native monolith, and every LLM call is already a
server-side Vertex Gemini call.** `wini_server.py` is the Cloud Run artifact today — it
just happens to run beside the client on the Pi/Jetson right now. Read against the code,
the question "how do we connect these components in the cloud" has a surprising answer:
**most of them must NOT be connected over the cloud — they are already co-resident in one
process, and a network boundary between any two of them would only add latency.**

There are **5 Gemini call *sites*** in the code — but they are conditional and partly
mutually exclusive, so a turn fires **1–4** of them, not five. All run from the one `Brain`
process, chained server-side, with the deterministic state-math between them:

| Call site | Fires when | Seam (file) |
|---|---|---|
| Perception (intent + signals + concept) | every turn (0 on a memo hit) | `analyze_only` → `llm_vertex.generate_json` (schema + Vertex context cache) |
| Answer generation | every **learning** turn | `qwen_chat` / `_stream_answer` → `generate_reply_stream` (`tutor_loop.py:315,612`) |
| Grader (`judge_answer`) | a `pending_check` is armed **and** `math_grade` is inconclusive (verbal/partial answer) | `qwen_chat` JSON (`tutor_loop.py:757`) |
| Cohesion judge (`qwen_cohesion_check`) | evidence bundle mixes **≥3 source types** with droppable chunk/figure items | `qwen_chat` JSON (`tutor_loop.py:747`) |
| Persona reply (`_nonlearning_reply`) | **non-learning** route (SOCIAL/META/OFF_DOMAIN/EMOTIONAL/SESSION_CONTROL-pause), not scripted | `qwen_chat` (`tutor_loop.py:1557`) |

**Learning and non-learning routes are mutually exclusive — persona never co-occurs with
generation.** Realistic per-turn counts:

| Turn | Gemini calls |
|---|---|
| Typical learning turn (fresh utterance, no pending check, <3 evidence types) | perception + generation = **2** |
| Same, perception memo hit | generation = **1** |
| Child answers a *verbal* probe with a 3-type evidence bundle | perception + grader + cohesion + generation = **4** (realistic max) |
| Social / off-domain turn | perception + persona = **2** (**1** if scripted) |

Everything else runs **in-process, sub-100 ms** and never leaves the box: MiniLM retrieval
embedding (**30 ms measured**, Part 13 §1), FAISS search, HOPE KI/KT/CT detectors, the
`derive_*`/`apply_deltas` state math, the policy-shadow, the T9 figure pick, atomic state
save (**6 ms measured**). Only **three** things ever cross the process boundary: **Gemini,
Cloud STT, Cloud TTS.**

**Corollary — the design principle for this whole plan:**

> Keep the brain a single warm stateful service. Decompose the *device↔brain* boundary
> (already done), never the *component↔component* boundary inside the brain. The
> cognitive-signal / concept / grading / policy / retrieval / state components are
> latency-coupled and share one in-memory learner state; putting a network hop between any
> two of them is pure loss. The only cloud calls worth optimizing are the three that are
> genuinely remote.

Part 13 already proved the thesis: time-to-first-audio went **10–13 s → 3.3–4.4 s** with
zero pedagogy change, purely by streaming those remote calls instead of blocking on them.

---

## 2. Target deployment architecture

```
┌─ DEVICE (thin client, unchanged) ──────────────────────────────────────┐
│  mic ─► floor-relative VAD ─► PCM stream ──┐         ┌──► speaker        │
│  e-ink / LVGL panel  ◄── display metadata ─┤         │   (NDJSON audio   │
│  touch ─► X-Wini-Mode header               │         │    chunks, in     │
└────────────────────────────────────────────│─────────│────order)────────┘
                                             ▼         │
┌─ BRAIN = ONE Cloud Run service (asia-south1, min-instances=1) ──────────┐
│  wini_server.py  (PORT env, concurrency=1, half-duplex under self._lock) │
│                                                                          │
│   Cloud STT ─► perception ─┐          IN-PROCESS, sub-100 ms:            │
│   (streaming   (Gemini      ├─ retrieval (MiniLM + FAISS)  · state math  │
│    Chirp 3)     Flash-Lite) │  · HOPE detectors · rules v4 + policy      │
│        │           │         │  · T9 figure pick · grading logic          │
│        │      grader (Gemini Flash-Lite, PARALLEL — needs no perception) │
│        │           │                                                     │
│        ▼           ▼                                                     │
│   generation (Gemini Flash, streaming) ─► clause chunker ─► Cloud TTS    │
│                                            (streaming Chirp 3 HD)        │
│                    │                                                     │
│   learner state ◄──┴──► Firestore  (read at turn start, write at end)    │
│   learning log ─────────► append to GCS / BigQuery                       │
└─────────────────────────────────────────────────────────────────────────┘
                     ▲                              ▲
                     │  all three remote calls in ONE region, warm clients │
              Vertex AI Gemini              Cloud Speech-to-Text / TTS v2
```

Everything inside the brain box stays exactly where it is today. The plan changes **where
the box runs**, **how its state persists**, and **the scheduling + model tier of the three
remote calls** — not the pipeline.

---

## 3. Component → cloud-tool mapping (what is hosted vs. in-process)

The load-bearing column is the last one.

| Component | Tool | Hosted service, or in-process? |
|---|---|---|
| Cognitive signals | Gemini **3.5 Flash-Lite** (perception) | Remote *call*; logic stays in the monolith |
| Concept resolving | MiniLM hints + Gemini + deterministic cross-check | **In-process** (MiniLM ~30 ms) |
| Learner state | **Firestore** (regional) | Hosted DB, touched only at turn boundaries |
| Learner grading | Gemini **3.5 Flash-Lite** (JSON) | Remote call, run **parallel** to perception |
| Pedagogy policy | rules v4 + policy-shadow | **In-process** (pure Python, ~0 ms) |
| Retrieval + reranking | FAISS + 7-term rank | **In-process** now; Vertex AI Vector Search *only if* corpus outgrows one box |
| Response generation | Gemini **3.6 Flash** (streaming) | Remote streaming call |
| Persistent learner DB | **Firestore** + append log → GCS/BigQuery | Hosted |
| STT | **Cloud Speech-to-Text v2, Chirp 3, `StreamingRecognize`** | Hosted, streaming (300–600 ms interim) |
| TTS | **Cloud TTS, Chirp 3 HD, `StreamingSynthesize`** | Hosted, streaming (already built, Part 13 Stage 1) |
| Orchestration host | **Cloud Run**, `min-instances=1` | The monolith itself |

**Model swap — the highest-leverage latency change, and its accuracy catch.** Everything
runs on **`gemini-2.5-flash`** today (`VERTEX_GENERATION_MODEL` `llm_vertex.py:25` +
`VERTEX_PERCEPTION_MODEL` `perception/config.py:32`, both defaulting to it). Two materially
faster models have since shipped: **Gemini 3.1 Flash-Lite** (Mar 2026, **2.5× faster
time-to-first-token than 2.5 Flash**, +45% output speed) and **Gemini 3.5 Flash-Lite**
(Jul 21 2026, fastest 3.5-class, **350 tok/s**). Because generation streams (Part 13), TTFT
*is* the driver of time-to-first-audio — so this is the single highest-leverage model
change available. Target: **generation → 3.6 Flash** (or 3.5 Flash-Lite if the answer
quality gate holds — the answer is manifest-grounded, low reasoning burden); the small
schema-constrained calls (**perception / grader / cohesion / persona) → 3.5 Flash-Lite**.

It is a one-line env change per call site (`llm_vertex.py` already takes `model=`), but
"without losing accuracy" is **not** free — three things break on a naive swap and are hard
prerequisites (see §6 Phase C):

1. **`PERCEPTION_SIGNAL_THRESHOLD` is calibrated to 2.5-flash's score distribution.** A new
   model emits a different raw-score scale, so signal firing must be **re-calibrated on the
   frozen TEST split** — the enum schema stops *invented* values, not *shifted* ones.
2. **The full `perception_eval` must be re-run and hold** — concept 0.930/0.990, intent 1.0,
   **safety 1.0 exactly**, behavioral eval PASS.
3. **The Vertex context cache is model-pinned** (`perception/vertex_cache.py:77`) — it must
   be **recreated** after the swap, or every call silently falls back to the full
   6,062-token prompt (the exact regression that cost 1.3 s/turn for 17 days, Part 13 §1).

---

## 4. Server selection (the "which server / which model where" question)

Server selection here is three orthogonal dials, chosen **per call site**, all inside the
one process:

1. **Model tier.** **3.5 Flash-Lite** for perception / grader / cohesion / persona;
   **3.6 Flash** for the answer (see §3 for the swap rationale + accuracy catch).
   `llm_vertex.py` already takes `model=` per call — a config change, not a rewrite.
2. **Region.** Pin Cloud Run **and** Vertex **and** STT/TTS to **`asia-south1` (Mumbai)**.
   Measured RTT to `asia-south1` is 31 ms (Part 13 §1); up to four remote LLM calls per turn
   means a cross-region hop is taxed on every one. One region beats any single model swap.
3. **Capacity mode.** On-demand to start; move to **Vertex Provisioned Throughput** once
   steady daily traffic clears the break-even (~$50/day on-demand on one model). PT buys a
   **stable latency floor regardless of regional demand** — which, for a child-facing tutor
   where one slow turn breaks the illusion, matters more than the discount.

---

## 5. Chaining the LLM calls in the cloud, no local processing

**You already do this, and it is the correct design.** The 1–4 Gemini calls a turn fires
(§1) all run from `wini_server.py`, chained, with the deterministic state-math between them.
The device sends audio up **once** and receives an audio stream back; **no LLM output ever
round-trips through the device.** "Local" in this system is only the thin client — the
entire multi-LLM orchestration is server-side today. There is nothing to relocate; there is
only tuning:

- **Parallelize the independent calls.** The grader (`tutor_loop.py:747`) needs only the
  transcript + the armed `pending_check` — **not** perception. Today it can land serially
  after perception, which is exactly the Trial-1 `brain`=992 ms vs Trial-2 `brain`=4044 ms
  spread (Part 13 §2, RC-3). Fan it out on the `ThreadPoolExecutor` the server already holds
  and join before `turn()`. This is Part 13 Stage 4, pulled forward.
- **Do NOT move the chain into a managed agent runtime.** Vertex AI Agent Engine could host
  the perception→generation chain, but our orchestration is not an open-ended agent loop —
  it is a fixed, deterministic pipeline with hard pedagogy invariants (evidence-only
  write-backs, probe-before-correct, gated bridges) that live in `tutor_loop.py` and are
  guarded by the frozen-split evals. An agent framework adds a scheduling layer and its own
  latency for control we already have in tighter, testable Python. Keep the chain
  in-process; it is faster and it is where the accuracy gates already sit.

---

## 6. Staged execution

Each phase is independently shippable, independently verifiable, and independently
revertible (flag or config, never a revert). Ordered by unlock-per-effort.

### Phase A — Deploy the monolith to Cloud Run · biggest unlock, ~no code change
1. `wini_server.py` runs unchanged (already reads `PORT`). Container image = current deps
   (numpy, torch/MiniLM, faiss, google-genai, google-cloud-speech/texttospeech).
2. **`min-instances=1`** — non-negotiable: `TutorLoop()` construction is **69 s** and the
   Gemini client build is 4–9 s (Part 13 §1 + CLAUDE.md). One warm instance means no child
   ever pays cold start.
3. **`concurrency=1`** per instance (half-duplex — one turn at a time under `self._lock`);
   scale out on instances, not on in-instance concurrency.
4. Region `asia-south1` for Cloud Run to match Vertex/STT/TTS.

**Exit:** health check green with `ready:true`; 10 live turns from a remote thin client
with TTFA within Part 13's on-device envelope (no cold-start cliff on turn 1).

### Phase B — Parallel grader + speculative perception (Part 13 Stage 4) · removes last serial LLM block
1. Run the grader concurrently with perception; join before `turn()`.
2. On the first stable interim transcript, fire `analyze_only` speculatively; use the result
   **only** when `normalize_input(final) == normalize_input(speculative)` (memo hit = free),
   else re-run on the final (costs exactly today's cost, never worse, never less accurate).
3. Cohesion judge: measure its positive rate; make async or drop if near-zero (decide on
   data, per Part 13 §4).

**Exit:** speculative hit rate ≥70% on live turns; on a miss, total ≤ today's; grader no
longer adds serial time to `brain`.

### Phase C — Model swap to the 3.x tier · biggest latency-per-effort, gated on accuracy
1. Generation → **`gemini-3.6-flash`**; perception / grader / cohesion / persona →
   **`gemini-3.5-flash-lite`** via the `model=` arg (`VERTEX_GENERATION_MODEL` /
   `VERTEX_PERCEPTION_MODEL` + the per-`qwen_chat`-site model). 2.5× faster TTFT feeds Stage-1
   TTS sooner.
2. **Re-calibrate `PERCEPTION_SIGNAL_THRESHOLD`** on the frozen TEST split — the new model's
   raw-score scale differs; the old threshold is not valid across models.
3. **Recreate the Vertex context cache** (`python -m perception.vertex_cache --create`) — it
   is model-pinned; a stale cache silently reverts to the full-prompt path.
4. **Hard gate before merge** (§7): perception concept top-1/top-3 **0.930/0.990**, intent
   **1.0**, safety **1.0** must hold exactly; behavioral state-trajectory eval PASS; answer
   quality spot-checked. If any slips on a site, keep it on the prior model.

**Exit:** accuracy suite unchanged, perception + generation TTFT measurably lower, cache
reuse confirmed (`p_gem_cached: 1`).

### Phase D — Streaming STT (Part 13 Stage 3) · removes the STT block + endpoint stall
1. `recognize_stream` via `StreamingRecognize`, `interim_results=True`, `single_utterance`
   endpointing; **keep** `language_code`, `model`, and the `MATHS_PHRASES` `SpeechContext`
   boost identically (that phrase set is what stops "discriminant" → "railroads").
2. Client streams 50 ms PCM blocks; drop `silence_ms` 700 → ~500 once STT-side endpointing
   is authoritative.

**Exit:** final transcript ≤400 ms after speech ends; **transcript accuracy equal to batch
on the 20-utterance fixture — hard gate, no regression.**

### Phase E — Learner state → Firestore · the one real persistence change
1. One document per learner, `asia-south1`. **Read at turn start, write at turn end** — the
   in-memory `state.data` stays the working copy; Firestore is only the durable load/store
   at turn boundaries. **No Firestore access mid-turn** (would inject a network hop into the
   sub-100 ms state math).
2. Keep the atomic-save discipline conceptually: last-writer-wins per learner is fine
   because turns are half-duplex per learner.
3. Append-only learning log → GCS (or BigQuery streaming insert) for the eventual neural-KT
   training corpus (build-plan Part 6 is deferred until real logs exist — this is how they
   accumulate).

**Exit:** a learner's mastery/misconception state survives instance restart and is correct
after a cold instance picks up mid-session; no turn-time regression vs. the JSON path.

### Phase F — Provisioned Throughput · when traffic justifies it
1. Reserve GSU capacity for the answer model (and perception if it dominates) once daily
   on-demand spend clears break-even.
2. Measure the p95 latency floor before/after; PT's value here is variance reduction, so
   judge it on **p95/p99**, not mean.

**Exit:** p95 TTFA stable under regional load where on-demand drifted.

---

## 7. Accuracy guardrails (non-negotiable — identical posture to Part 13 §5)

No phase above may cost a point of accuracy. Before/after each phase, on the frozen splits:

- `python -m eval.perception_eval --build --gates` — concept **0.930/0.990**, intent **1.0**,
  **safety 1.0 must hold exactly.**
- `python -m eval.behavioral_eval --hardened --replay` — state-trajectory PASS. (Per
  CLAUDE.md: gate on the behavioral eval, **not** label-F1 vs the retired heads.)
- `python -m perception.test_perception --integration` — gates + belt + front door.
- STT (Phase D): 20-utterance fixture, streaming vs batch transcripts must match.
- Generation: 10-prompt fixture, streamed vs non-streamed text byte-identical.

The perception prompt, schema, enums, `PERCEPTION_SIGNAL_THRESHOLD`, the deterministic
safety lexicon, the Vertex context cache, and every `derive_*`/`apply_deltas` write-back are
**untouched** by every phase. This plan changes deployment, persistence, and scheduling —
**not pedagogy** (the Part 13 non-goal, restated).

---

## 8. Human-type interaction — the path, and the fork to NOT take

"Human-type" for Wini means the child stops speaking and hears Wini begin within ~2 s, Wini
keeps talking naturally, and (later) the child can interrupt. That is the **cascade made to
feel live**, and it is nearly all built:

- Streaming TTFA — Part 13 Stages 0–2, done.
- Backchannel fillers — built, opt-in (`WINI_FILLERS`), a "thinking" face otherwise.
- **Barge-in** (child interrupts mid-answer) — Part 13 §6 flags it; streaming playback (now
  in place) is the prerequisite. This is the highest-value remaining human-ness lever; scope
  it as its own part once Phases A–D land.

**The fork to NOT take:** the maximally "human" option is the **Gemini Live API native-audio
model** (`gemini-live-2.5-flash-native-audio`, GA on Vertex Dec 2025 — bidirectional
WebSocket, human-like speech). But native audio-in→audio-out **bypasses the entire brain** —
no cognitive state, no evidence grounding, no grading, no probe-before-correct. That is the
opposite of what Wini is. Live API is a candidate **only** as a possible STT + endpointing
front end (audio→text) if Phase D streaming STT underperforms — and even then the
deterministic brain stays in the middle. The brain is the product; the voice is the edge.

---

## 9. Risks & rollback

| Risk | Mitigation |
|---|---|
| Cold start hits a child (Cloud Run scaled to zero) | `min-instances=1`; alert on instance count = 0 |
| Flash-Lite drops perception/safety accuracy | Hard eval gate (§7); per-site — keep Flash where it slips |
| Firestore read/write injected mid-turn | Contract: read at start, write at end only; assert no client call inside `turn()` |
| Streaming STT loses the phrase-boost accuracy | 20-utterance fixture must match batch (Phase D exit) |
| Cross-region tax multiplies over 5 calls | Single-region pin (§4) verified in deploy checklist |
| A streamed Gemini call stalls | Existing per-chunk + overall wall-clock bound (`llm_vertex.generate_reply_stream`) |

Every phase sits behind a flag or config default (`WINI_STREAM_STT`,
`WINI_SPECULATIVE_PERCEPTION`, the `model=` per-site setting, a `WINI_STATE_BACKEND=json|firestore`
switch). Rollback is one setting, not a revert — the Part 13 discipline, extended.

---

## 10. Recommended order (one line)

**A** (Cloud Run, warm) → **B** (parallel grader) → **C** (Flash-Lite, gated) → **D**
(streaming STT) → **E** (Firestore) → **F** (Provisioned Throughput). A–D are latency; E is
scale/persistence; F is variance. Each is a clean, gated, revertible increment.

---

## 11. Doc lockstep

Plan only — no contract or measured number changes yet, so lockstep is not triggered by
this file's creation. **On execution:** Phase A/E touch deployment + state-persistence
contracts → propagate to `WINI_ARCHITECTURE.md` + `learner_cognitive_state_architecture.md`
(§6.7 persistence) + `JETSON_PIPELINE_RUNBOOK.md`; Phase D touches the `/voice_turn` NDJSON
contract → `wini_client/README.md`. Every phase records *measured* results in
`complete_architecture_build_plan.md` (this would become build-plan Part 15). Gotchas →
`rag_memory.md`.
