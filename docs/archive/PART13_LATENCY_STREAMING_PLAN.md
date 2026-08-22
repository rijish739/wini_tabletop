# Part 13 — Voice Latency: the streaming pipeline

**Status:** **Stages 0–2 BUILT + verified on winipi5 2026-07-20.** Stages 3–4 NOT built.
Measured results live in `complete_architecture_build_plan.md` §15 (the authoritative
record); this file stays the design of record.

**Achieved so far:** time-to-first-audio **10.5–19.9 s → 3.3–4.4 s**, and TTFA no longer
scales with answer length. Streaming TTS gives the first chunk in 267–987 ms against
2040–4269 ms one-shot; streamed generation releases sentence 0 while the rest is written.
A free ~1.3 s/turn also came from recreating the Part 11 Vertex context cache, which had
expired 2026-07-03 and been silently absent for 17 days (see §1 note below).

**Remaining to reach the ~2 s target:** Stage 3 (streaming STT, 0.9–1.6 s) + Stage 4
(speculative perception, 1.4–1.8 s) + the client's fixed 1200 ms VAD hangover.

Design of record for cutting time-to-first-audio from ~10 s to ~2 s on winipi5.

**Goal:** the child stops speaking and hears Wini begin within ~2 s, and Wini keeps
talking naturally from there. **Answer length stays LLM-driven and dynamic** — no
clamping is introduced by this work. The whole point of the design is that
time-to-first-audio becomes *independent* of how long the answer is.

**Non-goal:** changing what Wini says. Same models, same prompts, same
`temperature=0` perception schema, same `derive_*`/`apply_deltas` state math.
This plan changes **scheduling**, not pedagogy.

---

## 1. Measured baseline (winipi5, 2026-07-20)

Full `/voice_turn` replay with per-stage timers, run against a *copy* of
`learner_state.json`. Two consecutive real turns:

| Stage | Trial 1 | Trial 2 | Counted in `latency_ms`? |
|---|---|---|---|
| VAD silence hangover (`silence_ms=1200`) | 1200 ms | 1200 ms | ❌ invisible |
| ⚠️ VAD *never endpointed* on the device — see RC-5 | +12 000 ms | +12 000 ms | ❌ invisible |
| 1. Cloud STT (batch `recognize`) | 4079 ms | 1221 ms | ✅ `stt` |
| 2. Perception Gemini (`pacing.before_turn`) | **2193 ms** | 0 ms (memoized) | ❌ **invisible** |
| 3. `tutor.turn` — retrieval + generation | 992 ms | **4044 ms** | ✅ `brain` |
| 4. Cloud TTS (whole answer, batch) | **4322 ms** | **3388 ms** | ✅ `tts` |
| 5. base64 + state save + HTTP | 10 ms | 8 ms | — |
| **Total before any sound** | **~12.8 s** | **~9.9 s** | |

Answers were 236–309 chars → **18–23 seconds of synthesized speech**, none of
which starts playing until all of it exists.

### Ruled out — do not re-investigate

| Suspect | Measured | Verdict |
|---|---|---|
| MiniLM retrieval embedding on Pi CPU | **30 ms** | not a factor |
| Network RTT to `asia-south1` | **31 ms** | not a factor |
| HTTP / localhost transport | **9 ms** (1.211 s wall vs 1.202 s STT) | not a factor |
| Atomic learner-state save (36 KB) | **6 ms** | not a factor |
| Thermal / CPU throttling | 54 °C, `throttled=0x0` | not a factor |
| base64 of 1.4 MB audio | **4 ms** | not a factor |

`TutorLoop()` construction is **69 s**, but that is a one-time boot cost on a
long-lived server, not per-turn. (It is why `min-instances=1` matters on Cloud Run.)

---

## 2. Root causes

### RC-1 — Nothing streams; four stages block in series
STT waits for the whole utterance, perception waits for STT, generation waits for
perception, TTS waits for the whole answer, playback waits for all the audio.
Every stage's full cost lands on the critical path. **This is the architectural
cause; RC-2..4 are its symptoms.**

### RC-2 — TTS synthesizes the entire answer before one byte plays
The single largest block (3.4–4.3 s). `CloudTts.synth` is one-shot
`synthesize_speech`. Because the cost scales with answer length, *today* a longer
answer is directly a slower answer — which is exactly the coupling this plan removes.

### RC-3 — Up to four serial Gemini calls per turn
`qwen_chat` is the shared Gemini seam. Per turn it can fire:

| Call site | Fires when | Needs perception first? |
|---|---|---|
| `analyze_only` (via `pacing.before_turn`) | every turn | — |
| grader — `tutor_loop.py:499` | a `pending_check` is armed | **No** — only transcript + pending question |
| cohesion judge — `tutor_loop.py:455` | droppable evidence exists | yes (needs retrieval) |
| answer generation — `tutor_loop.py:357` | every turn | yes |
| persona reply — `tutor_loop.py:954` | social / off-domain route | yes |

Trial 1 `brain`=992 ms vs Trial 2 `brain`=4044 ms is this: extra judge/grader calls
landing serially. The grader is on the critical path **despite not depending on
perception at all**.

### RC-4 — Perception (~2.2 s) is invisible and unavoidable-by-construction
It lives in `pacing.before_turn`, which `text_turn` never even calls, so it appears
in no counter. This is why the client logged 14.7 s turns while `latency_ms` summed
to 7.2 s. It is memoized by *normalized text*, so repeated phrasing costs 0 — but a
fresh utterance always pays full price.

### RC-5 — Fixed 1200 ms VAD hangover before anything starts
`record_utterance(silence_ms=1200)` in `wini_client/client.py`. Dead time on every
single turn, invisible to all server metrics.

> **RC-5 was far worse than a 1200 ms hangover — FIXED 2026-07-23.** The hangover
> was never actually reached on the device. `record_utterance` compared RMS to ONE
> fixed gate (`0.018`) for both starting and stopping, and the reSpeaker Lite's own
> noise floor measures **p50 0.024, peaks 0.030** (`tools/mic_floor.py`): **0 %** of
> idle blocks fall below 0.018, so "quiet again" was unreachable. Every field turn
> in `logs/client.log` ended `reason="hard_cap", capture_ms=15000, hangover_ms=0`
> — the child spoke for ~3 s and then waited ~12 s in silence, *and* STT was handed
> 15 s of mostly-nothing (3.0–3.9 s) instead of ~3 s (0.8–1.5 s).
>
> Replaced with a floor-relative endpointer: the floor is **measured** over a 300 ms
> calibration window at the head of every recording (25th percentile, so the mic's
> turn-on transient cannot inflate it), and the gates hang off it with hysteresis —
> stop at `floor x 1.7`, start at `floor x 2.3`, start always above stop. Speech on
> this mic measures p50 0.076 with 0.16–0.29 onsets (`tools/mic_speech_level.py`),
> so the separation is comfortable. `silence_ms` is now 700.
>
> **No absolute cap on the gates.** An intermediate revision capped the start gate at
> 0.045 so a loud room could not make Wini deaf; measuring the room at floor 0.050
> showed the cap put *both* gates under the room and re-created the exact hard_cap
> bug. A gate below the noise floor is never the safer choice.
>
> Guards: `wini_client/test_vad.py` (synthetic mic, 11 cases incl. the measured
> device profile and the loud-room regression) and, on hardware,
> `tools/mic_floor.py --idle` + `tools/mic_speech_level.py --endpoint`.

---

## 3. Target architecture

Convert four blocking stages into one continuous stream:

```
mic ──► streaming STT ──► [interim transcript] ──► speculative perception
                    └──► [final transcript] ────► perception (memo hit = free)
                                                        │
                              grader (parallel, needs no perception)
                                                        ▼
                                          streaming generation (token deltas)
                                                        │
                                         sentence chunker (~first clause)
                                                        ▼
                                     streaming TTS ──► NDJSON audio chunks
                                                        ▼
                                     client plays chunk N while N+1 synthesizes
```

The server **already has the NDJSON emit channel** (`/voice_turn`, the filler
line), and the client **already holds a persistent output stream** across turns
(`_out_stream`, kept open to avoid codec clicks). Both are the right seams — this
plan extends them rather than replacing them.

### Projected budget

| | Today | Target |
|---|---|---|
| endpoint detection | 1200 ms | ~500 ms (STT-side endpointing) |
| STT final transcript | 1200–4100 ms | ~300 ms (streams during speech) |
| perception | 2200 ms | ~0 ms typical (speculative), 2200 ms on miss |
| grader (when armed) | ~600 ms serial | 0 ms (parallel with perception) |
| generation → first sentence | 1000–4000 ms | ~500 ms |
| TTS → first audio chunk | 3400–4300 ms | ~700 ms |
| **time-to-first-audio** | **~10–13 s** | **~2.0 s typical / ~4.2 s worst case** |

---

## 4. Staged execution

Each stage is independently shippable, independently verifiable on the Pi, and
independently revertible. **Do not skip Stage 0** — it is what proves each later
stage worked.

### Stage 0 — Instrumentation (no behavior change) · ~1.5 h

The hidden perception cost is why this went undiagnosed. Make every stage visible
before optimizing any of it.

1. `wini_server.py` `voice_turn`: time `pacing.before_turn` → `latency_ms["perception"]`.
2. `tutor_loop.qwen_chat`: count calls + accumulate ms per turn (a turn-scoped
   counter, same shape as the existing turn-scoped `score_matrix`) →
   `latency_ms["gemini_calls"]`, `latency_ms["gemini_ms"]`.
3. Client: log `t_record_end → t_first_audio` as `ttfa_ms` — the number that
   actually matters to the child, and the one this plan is judged on.
4. Add `voice/latency_probe.py` — the replay harness used to produce §1, checked in
   so any future regression is one command away. It must run against a **copy** of
   `learner_state.json`.

**Exit:** 10 live turns logged with a full per-stage breakdown summing to within
200 ms of `ttfa_ms`. No unexplained gap.

### Stage 1 — Streaming TTS + incremental playback · ~1 day · **biggest single win**

Removes RC-2, and decouples latency from answer length.

1. `voice/cloud_tts.py`: add `synth_stream(text_iter) -> Iterator[bytes]` using
   `client.streaming_synthesize` (confirmed available: `google-cloud-texttospeech`
   **2.37.0** on the Pi, `StreamingSynthesizeRequest` present). Keep `synth()`
   untouched as the fallback path.
2. Add a sentence/clause chunker: emit on `.?!` and on `,`/clause boundaries past
   ~60 chars, so the *first* chunk is short and the rest stay natural. Chunk
   boundaries must never split a number or a maths phrase ("x squared").
3. `wini_server.py`: emit `{"part":"audio","seq":N,"audio_b64":...,"audio_rate":...}`
   NDJSON lines as chunks are produced; final line stays the full turn JSON
   (**back-compatible** — a non-streaming reader that parses only the last line
   still works, as documented in the module docstring).
4. `wini_client/client.py`: play chunk `seq=N` while `N+1` arrives. The persistent
   `_out_stream` makes this natural — write into the open stream, no per-chunk
   open/close (which is what caused the codec clicks). Preserve `PLAY_TAIL_S`
   handling on the **final** chunk only.
5. Ordering guarantee: a bounded queue keyed on `seq`; never play out of order,
   and underrun → wait, don't skip.

**Exit:** first audio within ~1 s of the answer's first sentence existing; no
clicks, no gaps, no reordering across 10 turns; a 300-char answer starts speaking
no later than a 60-char one.

**Risk:** `audio_manager.set_speaking()` currently wraps a single blocking play.
It must now span the whole chunk sequence, or the touch-emotion engine will think
Wini stopped talking mid-answer and interrupt with its own audio (single reSpeaker
playback substream — see `wini_client/SPEAKER_TROUBLESHOOTING.md`).

### Stage 2 — Streaming generation · ~0.5 day

Feeds Stage 1 sooner. Without this, Stage 1 still waits for the full answer text.

1. `llm_vertex.py`: add `generate_reply_stream(...) -> Iterator[str]` via
   `client.models.generate_content_stream` (confirmed: `google-genai` **2.11.0**).
   Keep the `ThreadPoolExecutor` hard wall-clock bound — **per chunk and overall**
   (CLAUDE.md: SDK timeouts have stalled for hours). A stalled stream must abort,
   not hang.
2. `tutor_loop.qwen_chat_stream` — new, alongside `qwen_chat`. Only the **answer**
   call site (`tutor_loop.py:357`) streams. The JSON-returning sites (grader,
   cohesion, quiz) must **not** stream — they parse whole objects.
3. `thinking_config=ThinkingConfig(thinking_budget=0)` stays (CLAUDE.md gotcha:
   thinking tokens eat the budget and return empty text).
4. `_truncate_to_spoken_budget` currently post-processes the complete answer. With
   streaming, apply it to the **accumulated** text and stop emitting once exceeded —
   never re-cut already-spoken audio. *(See §6 open question.)*

**Exit:** first sentence available ≤600 ms after generation starts; full streamed
answer is byte-identical to the non-streamed answer for the same prompt+seed on a
10-prompt fixture.

### Stage 3 — Streaming STT + tighter endpointing · ~1 day

Removes RC-4's dependency stall and RC-5.

1. `voice/cloud_stt.py`: add `recognize_stream(pcm_chunk_iter)` using
   `streaming_recognize` (confirmed: `google-cloud-speech` **2.40.0**), with
   `interim_results=True` and `single_utterance` endpointing. **Keep**
   `language_code`, `model`, and the `MATHS_PHRASES` `SpeechContext` boost
   identically — that phrase set is what stops "discriminant" → "railroads".
2. `wini_client/client.py`: `record_utterance` becomes a generator yielding 50 ms
   blocks as they are captured; the client opens the `/voice_turn` request and
   streams the body instead of buffering the whole utterance.
3. Drop `silence_ms` 1200 → ~500 once STT-side endpointing is authoritative. Keep
   the RMS gate as the *start* trigger (it costs nothing and avoids opening a
   billed stream on silence).
4. Keep the hard cap (15 s) and the `stop_event`/pause checks — PortAudio blocking
   reads ignore SIGTERM.

**Exit:** final transcript ≤400 ms after speech ends; transcript accuracy equal to
batch on a 20-utterance fixture (**this is a hard gate — no accuracy regression**).

### Stage 4 — Speculative perception + parallel grader · ~0.5 day

Removes the last serial block.

1. On the first stable interim transcript (unchanged for ~300 ms), fire
   `analyze_only` speculatively in a worker.
2. When the final transcript arrives:
   - `normalize_input(final) == normalize_input(speculative)` → the memoizer
     returns the cached analysis **free**. Common case.
   - Differs → discard and re-run on the final. **Costs exactly what today costs —
     never worse, never less accurate.**
   This is why the guard matters: the speculative result is only ever *used* when
   it was computed on text identical to the final. `InputProcessor.normalize_input`
   must stay idempotent (CLAUDE.md).
3. Run the grader (`tutor_loop.py:499`) **concurrently with perception** — it needs
   only the transcript and the armed `pending_check`, not the analysis. Join before
   `turn()`.
4. Cohesion judge (`tutor_loop.py:455`): gate behind a config flag and measure how
   often it actually flags anything ("usually the list is empty"). If the positive
   rate is near zero, make it non-blocking or drop it — **decide on measured data,
   not assumption.**

**Exit:** speculative hit rate ≥70% on live turns; on a miss, total time ≤ today's.

---

## 5. Accuracy guardrails (non-negotiable)

This plan must not cost a single point of accuracy. Before/after, on the frozen splits:

- `python -m eval.perception_eval --build --gates` — concept 0.930/0.990, intent 1.0,
  **safety 1.0 must hold exactly.**
- `python -m eval.behavioral_eval --hardened --replay` — state-trajectory PASS.
  (Per CLAUDE.md: gate on the behavioral eval, **not** label-F1 vs the heads.)
- `python -m perception.test_perception --integration` — gates + belt + front door.
- STT: 20-utterance fixture, streaming vs batch transcripts must match.
- Generation: 10-prompt fixture, streamed vs non-streamed text must match.

Perception prompt, schema, enums, `PERCEPTION_SIGNAL_THRESHOLD`, the deterministic
safety lexicon, and the Vertex context cache are **untouched** by every stage above.

## 6. Open questions

1. **`_truncate_to_spoken_budget`** (`tutor_loop.py:358`, `:955`) already clamps
   answers via `AnswerBudget`. Your instruction is that length stays LLM-driven and
   dynamic. That existing clamp is Part-10 pacing behavior, so this plan **leaves it
   alone** rather than silently changing pedagogy — but if you want answers fully
   uncapped, that is a separate, deliberate change. Flagging, not assuming.
2. **Cohesion judge** — keep, make async, or drop? Decide from the Stage-4 measurement.
3. **Barge-in** (child interrupts mid-answer) is out of scope here, but streaming
   playback is the prerequisite that makes it possible later.

## 7. Risks & rollback

| Risk | Mitigation |
|---|---|
| Streaming TTS chunk boundaries sound unnatural | Clause-aware chunker; A/B listen before merge |
| Touch-emotion engine interrupts mid-answer | `set_speaking()` spans the full chunk sequence (Stage 1) |
| Streaming STT drops the phrase-boost accuracy | Hard gate: 20-utterance fixture must match batch |
| A streamed Gemini call stalls | Hard wall-clock bound per chunk *and* overall |
| Speculative perception uses wrong text | Re-run guard on normalized-text equality |

Every stage sits behind an env flag (`WINI_STREAM_TTS`, `WINI_STREAM_GEN`,
`WINI_STREAM_STT`, `WINI_SPECULATIVE_PERCEPTION`), defaulting **off**. Rollback is
one flag, not a revert.

## 7b. Field-report fixes, 2026-07-23 (executed, measured on winipi5)

Four defects reported from real use, all verified on the device. None needed the
unbuilt Stage 3/4 streaming STT — three of them were bugs, not missing features.

| # | Report | Root cause | Fix |
|---|---|---|---|
| 1 | Explanation truncated with `...`; `x^2` on screen; mangled `x=2 =-2` | `ModeChannelSink` capped the body at **200 chars** (transport ceiling: `MAX_LINE` 480 / `IPC_LINE_MAX` 512), truncated mid-token, and `_ASCII_MAP` actively downgraded `²`→`^2` even though the panel fonts carry `²³×÷−√≤≥°±πΔθ` | Widened the whole chain (`IPC_LINE_MAX` 2048, `MAX_LINE` 1900, dispatch `body[1024]`, cap 900) and added `mathtext.to_panel_unicode` — real glyphs, one shared parser with the spoken path. Truncation, if it ever fires, now cuts at a sentence end |
| 2 | Warmup doesn't cover STT/LLM/TTS | `Brain._load` warmed only one-shot TTS + perception. **STT was never called** and the **streaming** TTS method (what every turn uses) was never opened — both handshakes landed on the child's first sentence | Warm all four legs in parallel before `ready` flips; the launcher already gates the UI on `ready`, so it is paid behind the splash. Client now primes mic+speaker right after `wait_ready` instead of inside `run_session` (which does not run until a card is tapped) |
| 3 | 20 s+ per turn | Mostly a consequence of #4: 15 s of captured silence also cost 3.0–3.9 s of STT instead of 0.8–1.5 s. Compounded by an **expired Vertex context cache** (2026-07-21), so every perception call re-sent the full 6 062-token prompt | VAD fix below; cache recreated (`p_gem_cached: 1` confirms reuse) |
| 4 | Listening always waits the same long time | **RC-5, above** — one fixed gate below the mic's own noise floor, so no turn ever endpointed | Floor-relative adaptive gates with hysteresis |

**Measured after (first turn following a cold boot, `tools/first_turn_probe.py`):**
`stt` 0.8–1.8 s, `perception` 1.3 s (cache hit), `brain` 1.7 s,
`tts_first_chunk` 0.19–0.22 s → **first audio 3.7–4.9 s**, with no cold-start cliff
on turn 1. Capture is now ~2.9 s + 0.7 s hangover instead of a flat 15 s, so ~12 s
of dead air per turn is gone.

Boot moved from ~13 s to ~20 s (`warmup in 15431 ms`) — deliberate: that time is
spent behind the splash so the panel lights up ready.

New instruments, all checked in: `wini_client/test_vad.py`,
`tools/mic_floor.py`, `tools/mic_speech_level.py`, `tools/first_turn_probe.py`,
`tools/ui_drive.py` (mic-free panel driver).

## 8. Doc lockstep

This file is a plan only — no contract or measured number changes yet, so the 4-doc
lockstep is not triggered by its creation (same posture as
`PART12_PEDAGOGY_MODES_PLAN.md`). **On execution**, each stage must update
`complete_architecture_build_plan.md` with *measured* results, and Stage 3/4 touch
the `/voice_turn` NDJSON contract → update `WINI_ARCHITECTURE.md`,
`wini_client/README.md`, and `JETSON_PIPELINE_RUNBOOK.md` §15. Gotchas → `rag_memory.md`.
