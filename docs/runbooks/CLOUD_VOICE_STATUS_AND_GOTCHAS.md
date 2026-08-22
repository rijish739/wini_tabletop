# Cloud Voice Pipeline — Status & Gotchas (Part 11, Increment 1)

> **Scope:** the move of Wini's voice loop to the cloud — STT/TTS edges, Gemini Flash
> generation, and the voice-teaching quality fixes that followed the first live mic test.
> This is a **status + gotcha log**, not a lockstep contract doc. Authoritative status
> lives in `complete_architecture_build_plan.md` §13 (this doc expands on it).
>
> **Repo:** `D:\cloud CLI` (the real project). **GCP:** `custom-model-training-493207`.
> **Date:** 2026-07-01.

---

## 1. Status at a glance

| Piece | State |
|---|---|
| Edge latency spike (STT/Flash/TTS) | ✅ done, measured |
| Gemini generation backend (`GEN_BACKEND=gemini`) | ✅ built, headless-verified |
| Cloud voice tutor runner (`voice_cloud_tutor.py`) | ✅ built |
| Voice-teaching quality fixes (budgets, intro routing, anti-apology) | ✅ built, replay-verified |
| **User mic test on live speech** | ⏳ pending (your turn) |
| Increment 2 — Gemini **perception** layer (`PART11_GEMINI_PERCEPTION_LAYER.md`) | ✅ **COMPLETE 2026-07-02** — promoted (concept 0.930/0.990, behavioral eval PASS), Stage 5 context cache live, Stage 6 heads retired from runtime (`PART11_PERCEPTION_EVAL_STATUS.md` §7–§9) |

**Net effect:** with `GEN_BACKEND=gemini` the whole voice loop runs cloud-only
(**no local Qwen server needed**): mic → Cloud STT → real pedagogical brain (MiniLM
perception + retrieval, unchanged) → Gemini 2.5 Flash generation → Cloud TTS → speaker.
Warm end-to-end ≈ **~4 s/turn**.

---

## 2. What was built

### 2.1 Edge latency spike (throwaway probe)
Purpose: get real per-hop numbers before committing to a design. **Not wired into the
brain**; a fixed system-prompt Flash call stands in for the tutor.
- `voice_latency_spike.py` — `mic/wav → {Cloud STT, Gemini Live STT side-by-side} →
  Gemini Flash → Cloud TTS`, per-hop timing, `--loop` keeps clients warm.
- `voice/gemini_live_stt.py` — Gemini **Live API used for input transcription only** (no
  audio-out), so it can be compared against Cloud STT.

### 2.2 Gemini generation backend (Increment 1)
- `llm_vertex.py` — shared Vertex **Gemini 2.5 Flash** client (`asia-south1`), **memoized
  per region**, **hard wall-clock timeout** via `ThreadPoolExecutor.result(timeout=)`
  (default 20 s), `thinking_budget=0`. This is the client the perception layer will reuse.
- `tutor_loop.py` — new flag **`GEN_BACKEND=qwen|gemini`**. `qwen_chat` dispatches to
  `llm_vertex.generate_reply` when `gemini`. **One seam** covers all three generation call
  sites (`qwen_answer`, `qwen_cohesion_check`, `judge_answer`) — the manifest-grounded
  prompt is **byte-identical** across backends; only the transport changes. Local Qwen
  `:8080` stays as legacy/fallback (default `qwen`).
- `voice_cloud_tutor.py` — push-to-talk cloud voice tutor: Cloud STT → real `TutorLoop`
  brain → Gemini gen → Cloud TTS, warm clients, per-hop timing. Reuses
  `voice.live_tools.TutorTurnHandler` (no brain-code duplication).

### 2.3 Voice-teaching quality fixes (from the first mic transcript)
A live trig session (`cloud_education.txt`) produced content-free one-liners: the opening
"I want to learn trigonometry" was **quizzed**, and every frustrated follow-up drew an
**apology that ate the whole spoken budget** ("Namaste! I'm Wini…", "My apologies! Let's
focus…"), repeating the same question 3×. Fixes (owner chose *fuller explanations*):

| Root cause | Fix | File |
|---|---|---|
| Budgets too tight (22–35 w / 1–2 s) | Teaching actions raised (see §5) | `pacing/pacing_controller.py`, `pacing/ledger.py` |
| No "introduce a fresh topic" path → QUIZ default | **Rule 1c**: unmastered concept + learn-intent → EXPLAIN-introduce | `tutor_loop.py` (`rules_decide`, `turn`) |
| Frustration → REFLECT/SOCRATIC + apology | `CLARIFY_RE` extended to "not explaining / keep asking / different answers" → re-explain (rule 1b) | `cognitive_classifier/cues.py` |
| Filler + repeated questions | Hard STYLE block: no greeting/self-intro/apology/announcing; never re-ask a prior question; intro tone for rule-1c | `tutor_loop.py` (`qwen_answer`) |

**Before → after** (same 5 inputs, fresh state, `GEN_BACKEND=gemini`):

| Turn | Old | New |
|---|---|---|
| "I want to learn trigonometry" | "Namaste! I'm Wini… which angle is 90°?" (QUIZ) | 4-sentence intro: what it is, the constant-ratio idea, an application, then "Does this make sense?" (EXPLAIN) |
| "you're giving different answers" | "Apologies! Let's focus on trigonometry." | Teaches trig ratios with a 30° example |
| "you're not answering anything" | "My apologies! What is a right-angled triangle?" | Explains right/acute angles with an example |
| "answers are not complete" | "My apologies! What is a right-angled triangle?" *(repeat)* | Explains hypotenuse with a 3-4-5 example |
| "same question again and again" | "My apologies! Let's try this." | Explains opposite/adjacent sides |

Zero apologies, zero repeats, progressive teaching, warm latency intact.

---

## 3. Measured latency (Windows quick-test rig)

| Hop | Cold (first call in a fresh process) | Warm (steady state) |
|---|---|---|
| Cloud STT | ~5–7 s | **~1.0–1.5 s** |
| Gemini Live STT (transcription-only) | ~8–10 s | **~7.7–8.4 s** ← rejected on latency |
| Gemini 2.5 Flash generation | ~4–8 s | **~0.9–1.3 s** |
| Cloud TTS | ~1.5–6 s | **~1.1–1.9 s** |
| **Full mic turn (Cloud STT + brain + TTS)** | ~20–30 s | **~4 s** |

Cold cost is almost entirely **one-time client construction** (see gotcha G2), paid once at
startup via warmup — the Cloud Run `min-instances=1` case.

---

## 4. How to run

```powershell
cd "D:\cloud CLI"
$env:GEN_BACKEND="gemini"            # cloud generation; no local Qwen server needed

# Cloud voice tutor (push-to-talk; Enter to start, speak, Enter to stop):
python voice_cloud_tutor.py --loop

# Edge-only latency probe (STT vs Live, Flash, TTS):
python voice_latency_spike.py --push-to-talk --speak --loop
python voice_latency_spike.py --push-to-talk --speak --loop --no-live   # skip slow Live leg

# Headless sanity (no mic, no Qwen server):
python tutor_loop.py --once "why do we check the discriminant" --no-judge
```

- `learner_state.json` carries session state across runs; delete it for a clean slate.
- Default `GEN_BACKEND=qwen` still uses the local llama.cpp server at `:8080` (fallback).

---

## 5. Voice answer budgets (after the fix)

`pacing/pacing_controller.py` → `ACTION_BUDGETS` (max_words / max_sentences):

| Action | Words | Sentences | Note |
|---|---|---|---|
| EXPLAIN | 65 | 4 | teaching — raised from 35/2 |
| WORKED_EXAMPLE | 85 | 5 | raised from 60/4 |
| ANALOGOUS_EXAMPLE | 60 | 4 | raised from 30/2 |
| REPRESENTATION_TRANSLATION | 60 | 4 | raised from 40/2 |
| ENCOURAGE | 45 | 3 | raised from 25/2 |
| TRANSFER_PROBLEM | 45 | 3 | raised from 35/2 |
| MISCONCEPTION_PROBE | 35 | 2 | check — stays tight |
| SOCRATIC_Q | 30 | 2 | check — stays tight |
| QUIZ | 30 | 2 | check — stays tight |
| METACOGNITIVE_REFLECT | 30 | 2 | check — stays tight |

Design intent preserved: **teaching actions deliver a full idea; checking actions stay
short.** The prompt caps *and* a post-truncation step (`_truncate_to_spoken_budget`)
enforce these.

---

## 6. Config / environment

`.env` (gitignored) in `D:\cloud CLI`:
```
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=custom-model-training-493207
GOOGLE_CLOUD_LOCATION=global          # STT/TTS
VERTEX_REGION=asia-south1             # Gemini generation
```
Flags: `GEN_BACKEND` (qwen|gemini), `VERTEX_GENERATION_TIMEOUT_S` (default 20),
`VERTEX_GENERATION_MODEL` (default gemini-2.5-flash). ADC already set up
(`gcloud auth application-default`); project active in `gcloud config`.

---

## 7. File map

**New:**
```
llm_vertex.py                 shared Vertex Gemini Flash client (memoized, hard timeout, thinking off)
voice/gemini_live_stt.py      Gemini Live STT-only probe (comparison, not adopted)
voice_latency_spike.py        edges-only latency probe
voice_cloud_tutor.py          push-to-talk cloud voice tutor (real brain + Gemini gen)
.env                          Vertex config
CLOUD_VOICE_STATUS_AND_GOTCHAS.md   this doc
```
**Modified:**
```
tutor_loop.py                 GEN_BACKEND flag + qwen_chat dispatch; rule 1c + learning_start;
                              qwen_answer intro tone + STYLE block
pacing/pacing_controller.py   ACTION_BUDGETS raised; AnswerBudget defaults
pacing/ledger.py              default max_words 35 -> 60
cognitive_classifier/cues.py  CLARIFY_RE extended (standalone runtime cue; no classifier rebuild)
voice/audio_io.py             record_push_to_talk gains optional device= arg
CLAUDE.md                     cloud-pivot mandate merged in; new gotchas
complete_architecture_build_plan.md   Part 11 §13 + §13.1a
rag_memory.md                 work-log entries
```

---

## 8. Gotchas (verified this session — do not rediscover)

**G1 — Gemini 2.5 Flash `thinking` defaults ON and can eat the whole output budget.**
A short reply came back **empty** with `finish_reason=MAX_TOKENS` and no visible text,
because the default thinking budget consumed all of `max_output_tokens`. Fix:
`thinking_config=ThinkingConfig(thinking_budget=0)` for short, latency-sensitive replies
(done in `llm_vertex.py`).

**G2 — Client construction, not the API call, is the cold-start cost.**
Building a fresh `genai.Client(...)` (Vertex ADC/gRPC channel) or a Cloud STT/TTS client
costs **~4–9 s**; the actual call once warm is **sub-1.5 s**. `llm_vertex.py` was
originally rebuilding the client on every call, silently paying full cold-start every turn.
Fix: **memoize / build once per process.** This is exactly why the deployment uses Cloud
Run `min-instances=1` (one always-warm instance).

**G3 — Gemini Live API for STT-only is correct now but ~5–6× slower than Cloud STT.**
Re-tested 2026-07-01 (input transcription only, no audio-out): the transcript was right
this time (no repeat of the 2026-06-18 wrong-script bug), but latency is **~7.7–8.4 s/turn**
vs Cloud STT's **~1.0–1.5 s**, because a Live session runs a full model turn even when only
the input transcription is read. **Cloud STT stays the STT choice — now on latency, not just
correctness.**

**G4 — `is_known(concept_id)` means "has a state row", NOT "has been taught".**
It returns `True` as soon as `apply_deltas` writes a concept-state row on the **first** turn,
so routing that wants "brand-new topic" must gate on **`mastery(primary) <= COLD_START_MASTERY`
(0.30)** instead — mastery only rises on graded evidence. **Debugging trap:** a standalone
probe that calls only `analyze_only` (never `apply_deltas`) sees `is_known=False` and hides
the bug. **Reproduce routing through the full `turn()` / `TutorTurnHandler` path**, not a
one-shot analyze.

**G5 — Voice budgets that are too tight produce content-free one-liners.**
At 22–35 words / 1–2 sentences, a single greeting or apology consumes the entire spoken
reply and nothing is taught. Gemini is *especially* prone to opening with an
acknowledgment/apology, so the budget must both (a) be large enough for teaching actions and
(b) be protected by a prompt that forbids greeting/self-intro/apology/announcing.

**G6 — There are two `CLAUDE.md` files; only one is the repo.**
The real project is `D:\cloud CLI` (git repo). The session's working directory
`D:\Data\My Dnlds` is a **downloads folder** holding a **stale copy** of `CLAUDE.md` (and
some architecture docs). A prior session edited the cloud-pivot mandate into the copy by
mistake. **Always edit files under `D:\cloud CLI`.**

**G7 — Running a script from the scratchpad doesn't put the project on `sys.path`.**
Python adds the *script's own directory* to `sys.path`, not the current working directory,
so `import tutor_loop` fails when the script lives in the temp scratchpad. Fix:
`sys.path.insert(0, r"D:\cloud CLI")` at the top, or run the script from the repo.

**G8 — New runtime cues are standalone (no classifier rebuild).**
`is_clarification_request` / `CLARIFY_RE`, `is_answer_attempt`, `is_pure_ack` are **not** in
`CUE_NAMES` / `cue_features`, so extending them does **not** require rebuilding the classifier
bank or policy shadow (unlike adding a cue *feature*, which does — see CLAUDE.md).

> Pre-existing project gotchas (misconception edges, OvR/loky on Windows, `CUE_NAMES` width,
> bulk-LLM timeouts, cp1252 console) are in **`CLAUDE.md` → Known gotchas**; not repeated here.

---

## 9. Pending / next steps

1. **User mic test** of `voice_cloud_tutor.py --loop` on live speech (latency + teaching feel).
2. **Increment 2 — Gemini perception layer: COMPLETE 2026-07-02** (see §10): promoted
   (`gemini` default), Stage 5 context cache live (6,062 tokens cached, ~1.0–1.1 s/call
   warm; recreate with `python -m perception.vertex_cache --create` after prompt rebuilds
   or TTL expiry), Stage 6 heads retired from runtime (artifacts = eval baselines).
   Standing watch: production firing rates.
3. **Optional latency polish:** sentence-streamed TTS on the push-to-talk path (the `--live`
   path already streams), and running query-embedding in parallel with perception once
   embeddings move to a Vertex API.

---

## 10. Increment 2 — Gemini perception layer (built 2026-07-01; **PROMOTED 2026-07-02**, default `gemini` — full evidence in `PART11_PERCEPTION_EVAL_STATUS.md` §7–§8)

The front door from `PART11_GEMINI_PERCEPTION_LAYER.md`. **Gemini perceives; deterministic
code decides and writes state** — perception (intent + signals + concept) becomes ONE
structured Gemini call; the `derive_*`/`apply_deltas` state machine is reused byte-for-byte.

### 10.1 What was built
```
perception/gates.py            deterministic SAFETY + NONSENSE gates (model-free, always on)
perception/route.py            RouteResult + the 8 intents + INHERIT sentinel
perception/build_perception.py schema enums + cached block from the artifacts of record (§5.4)
perception/gemini_perception.py GeminiPerception: one memoized call; classify/resolve/route/
                               embed/score_matrix/embedder + the validation belt (§5.5a)
perception/config.py           PERCEPTION_BACKEND / _SHADOW / _TIMEOUT_S / _SIGNAL_THRESHOLD
perception/test_perception.py  gates + belt + interface + full front-door integration test
persona.json                   identity + canned/scripted non-learning replies
llm_vertex.generate_json       structured-JSON seam (response_schema, temp 0, thinking off)
eval/perception_eval.py        Stage 2 harness (frozen TEST split + intent/safety probes)
tutor_loop.py                  step-0 front door, _handle_nonlearning, _log_safety,
                               backend wiring, answer_attempt guard, shadow hook
```
`analyzer.py`, `learner_state.py`, `query.py`, the classifier/resolver/policy-shadow/HOPE
code are **unmodified** — `GeminiPerception` is injected as classifier+resolver.

### 10.2 Verified
- **Stage 0 gate GREEN (live):** one structured call returns schema-valid JSON (~8 s cold — G2).
- **Gate coverage (offline, final):** SAFETY **1.0** (20/20 adversarial), NONSENSE **1.0** (9/9),
  **0** real learning utterances falsely gated.
- **Front-door integration test (qwen_heads default):** SAFETY → scripted reply + persisted
  `safety_alerts` + supervisor console alert; NONSENSE → scripted; both preserve `pending_check`
  and move **no** cognitive state; a LEARNING utterance passes through to the normal pipeline
  unchanged. `python -m perception.test_perception --integration` passes.
- **8-row live Gemini smoke:** 0 parse/transport errors, intent macro-F1 1.0, safety recall 1.0
  (full concept/signal numbers pending the 999-row run — `eval/perception_eval_report.md`).

### 10.3 Gotchas (new this increment)
- **G9 — Enums stop *invented* concepts, not *wrong* ones.** `response_schema` enum-masks
  decoding so Gemini cannot emit an out-of-catalog concept/signal/intent, but it can still pick
  a wrong-but-valid one. The validation belt only coerces OOV → INHERIT/drop; correctness is a
  *threshold/eval* problem (§5.5b), which is why signal firing is gated by
  `PERCEPTION_SIGNAL_THRESHOLD`, not the raw score, and calibrated on TEST.
- **G10 — the deterministic gate must be near-total on its own.** First pass scored SAFETY gate
  recall 0.75 because the lexicon missed gerunds ("ending my life" vs "end my life") and oblique
  phrasings ("nobody would care if I disappeared"). The model is only a secondary net (§4.2), so
  the gate was broadened to 1.0 on the probe set — measure gate recall directly
  (`--gates`), don't lean on the model for the safety floor.
- **G11 — `score_matrix` under the Gemini backend is turn-scoped.** The policy shadow calls
  `classifier.embed([norm])` then `classifier.score_matrix(emb)`; `GeminiPerception` returns the
  Gemini signal vector for the text most recently `embed()`-ed (one utterance/turn). Fine for the
  serial tutor loop; don't call it out of that order.
- **G12 — one Gemini call per turn is memoized by *normalized* text.** `route()` (front door),
  then `classify()`+`resolve()` (analyzer) all hit the same memo, so a learning turn is ONE
  perception round-trip — but only because `route(raw)` and `classify(normalize(raw))` normalize
  to the same key (idempotent normalization). Keep `InputProcessor.normalize_input` idempotent.
