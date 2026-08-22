# Wini Cognitive-Signal Filler Architecture

> **Status:** design (v1) — 2026-06-23
> **Scope:** the short utterance Wini speaks to mask STT→brain→TTS latency.
> **Hard boundary:** this design adds **no changes to the existing pedagogy pipeline**.
> It consumes only signals the pipeline *already* produces and exposes today, and lives
> entirely inside `voice/fillers.py`. No edits to `pacing/`, `tutor_loop.py`,
> `policy_shadow/`, `hope_detector/`, the analyzer, or the learner state.
>
> This document is a voice-layer companion to `WINI_VOICE_STUDY_ARCHITECTURE.md`. It does
> **not** carry any of the four lockstep contracts (`learner_cognitive_state_architecture.md`,
> `RAG_upgrade_plan.md`, `model_dataset_architecture_report.md`,
> `complete_architecture_build_plan.md`) and therefore is not part of the lockstep
> propagation requirement. Link to it from `WINI_VOICE_STUDY_ARCHITECTURE.md`.

---

## 1. Purpose

Between the moment the student stops speaking and the moment Wini's real answer begins,
there is a gap: STT finalization → cognitive analysis → **local Qwen generation (the long
pole, ~1–4 s on Vulkan)** → first-sentence TTS. A silent gap makes the system feel dead and
makes students repeat themselves.

Wini fills that gap with a short spoken **filler** ("Okay, let me think about that…") that
is chosen from the **cognitive signal of the student's turn**. The goals, in order:

1. **The student must not feel the latency** — audio starts within the gap, every turn.
2. **It must feel like Wini is *thinking*, not playing a recording** — the same cognitive
   state must not always yield the same words.
3. **It must never contradict the answer that follows** (the answer does not exist yet).
4. **It must cost nothing at runtime and nothing to the existing pipeline.**

## 2. Design principles

| Principle | Consequence |
|---|---|
| **Deterministic by state** | The *bank* (the set a filler is drawn from) is a pure function of the cognitive signal. The same cognitive state always routes to the same bank — behavior is predictable and testable. |
| **Stochastic within state** | *Which phrase* inside the bank is sampled randomly (with anti-repeat). Determinism where it matters, liveliness where the ear notices. |
| **Compose, don't enumerate** | Phrases are built from slot fragments, so a few dozen fragments yield hundreds of distinct utterances — the "pre-recorded" feeling disappears. |
| **Pre-synthesize, never block** | All filler audio is synthesized once at startup (or shipped as WAVs on the Jetson) and played from cache. The filler must never add latency — it exists to *hide* latency. |
| **Affect-safe** | A filler may assert only what is *already known* (the student's affect/intent). It may never assert correctness. |
| **Read-only, isolated** | Reads `decision.analysis` only. Writes nothing to state. Touches one file. |

## 3. The cognitive-signal contract (what the filler is allowed to read)

The filler is chosen **before generation**, so it may use only what exists at that instant.
That is exactly the output of the analyzer's read-only `analyze_only()` call, already hanging
on the `PacingDecision` the voice loop holds:

```
decision.analysis = CognitiveAnalyzer.analyze(transcript)   # ~50 ms, no state mutation
   ├─ analysis["signals"]          : List[str]   # the fired MiniLM labels (the 38-label space)
   ├─ analysis["signal_scores"]    : Dict[str,float]  # per-label score, only those >= 0.05
   └─ analysis["cognitive_update"] : Dict[str,float]  # 10 section-6.2 aggregates, each 0..1
        confusion, curiosity, confidence, misconception_probability,
        transfer_attempt, abstraction_attempt, self_correction,
        cognitive_load, engagement, frustration_risk
```

**That is the entire input surface.** No HOPE signals, no policy action, no learner-state
read, no second model call. (HOPE/policy are deliberately out of scope — see §11.)

**Integration point — unchanged.** The voice loop already calls, on every turn:

```python
decision = self.handler.analyze(transcript)      # unchanged
phrase, filler_pcm = self.fillers.pick(decision) # unchanged signature
threading.Thread(target=self._play, args=(filler_pcm,)).start()
out = self.handler.respond(transcript, decision) # Qwen runs here, in parallel
```

This design reimplements only the body of `FillerBank.pick()` / `pick_bucket()` inside
`voice/fillers.py`. The signature `pick(decision) -> (phrase, pcm)` and the call site in
`voice/live_session.py` do not change.

## 4. Data flow

```
 mic ──▶ STT ──▶ analyze_only (≈50 ms) ──▶ analysis{signals, cognitive_update}
                                                  │
                          ┌───────────────────────┴───────────────────────┐
                          │                                                │
                 route_bank(signals, cu)                          handler.respond()
                          │  (deterministic)                      Qwen generate (1–4 s)
                          ▼                                                │
                 compose(bank, anti_repeat)                                │
                          │  (stochastic)                                  │
                          ▼                                                ▼
                 cache[utterance] ──▶ 🔊 FILLER  ───(covers the gap)──▶ 🔊 REAL ANSWER
```

The filler plays on its own thread while Qwen generates on the main path. When the answer's
first sentence is ready, `_speak_chunked()` takes over (already the case today).

## 5. Bank routing (deterministic)

Banks are chosen by a **priority cascade** — first match wins — evaluated over the fired
labels and the aggregate floats. Priority encodes pedagogy: emotional safety first, then
explicit requests, then cognitive content, then a neutral default.

```
route_bank(signals, cu):                          # cu = cognitive_update
  # ── Layer A · AFFECT OVERRIDE (dominates everything) ──────────────
  if cu.frustration_risk >= 0.6 or cu.cognitive_load >= 0.7
     or {"frustration","anxiety","cognitive_overload",
         "disengagement","prerequisite_weakness"} ∩ signals
     or cu.confidence <= 0.25:                       → "empathic"

  # ── Layer B · EXPLICIT REQUEST (student asked for a thing) ────────
  if {"request_hint","hint_dependency"}  ∩ signals:  → "hint"
  if "example_request"                   in signals: → "example"
  if {"request_representation","representation_shift",
      "diagrammatic","graphical","tabular",
      "physical","verbal_analogy"}       ∩ signals:  → "represent"
  if "simplification_request"            in signals: → "simplify"
  if "topic_shift"                       in signals: → "shift"

  # ── Layer C · COGNITIVE CONTENT ──────────────────────────────────
  if cu.misconception_probability >= 0.5
     or {"misconception_clue","recurring_error"} ∩ signals: → "probe"
  if {"self_monitoring","self_correction",
      "prerequisite_awareness"}          ∩ signals:  → "reflect"
  if {"ready_for_next","high_confidence","transfer_attempt",
      "abstraction_attempt"}             ∩ signals:  → "advance"
  if {"skepticism","conflict"}           ∩ signals:  → "consider"
  if "question"                          in signals: → "question"
  if cu.curiosity >= 0.6 and cu.confusion < 0.4:     → "curious"
  if cu.confusion >= 0.4:                            → "clarify"

  # ── Layer D · DEFAULT ────────────────────────────────────────────
  return "thinking"
```

Every one of the 38 labels has a home (full map in §10, Appendix A). The cascade is total:
an empty `signals` list with neutral aggregates falls through to `thinking`.

**Prosody modifier (still cognitive-signal only).** The chosen bank fixes *what* is said;
the aggregates tune *how* it is said, without changing the bank:

| Condition | Prosody |
|---|---|
| `confidence` low **or** `cognitive_load` high | slower rate, warmer lead, longer pre-pause |
| `engagement` high **or** `curiosity` high | brisker rate, lighter lead |
| otherwise | neutral baseline |

If the TTS backend can't vary rate live, bake 2–3 prosody variants per utterance into the
cache and pick by the same rule (see §7).

## 6. The liveliness engine: compositional slots

A flat list of 4–6 phrases per bank repeats audibly within one session. Instead each filler
is assembled from a **three-slot grammar**:

```
FILLER  =  LEAD (affect token)  +  BRIDGE (thinking move)  +  TEASE (action hint)
```

- **LEAD** — a short acknowledgement token, weighted by the prosody rule
  (gentle when low-confidence/high-load, light when engaged).
- **BRIDGE** — the "I'm working on it" move, flavored by the bank.
- **TEASE** — a content-neutral hint at what's coming, ending on a continuation-friendly
  word ("so…", "now…") so the real answer flows out of the filler instead of a hard stop.

Each slot offers 3–5 variants per bank, so a bank yields **3×4×4 ≈ 48** unique utterances
before anti-repeat — and ~13 banks → **hundreds** of distinct fillers from ~120 fragments.

**Example — `probe` bank (misconception detected), low-confidence prosody:**

| Slot | Variants sampled |
|---|---|
| LEAD | "Okay," · "Mm, alright," · "No rush —" · "Right," |
| BRIDGE | "let me check one thing with you," · "let me look at this carefully," · "I want to be sure here," |
| TEASE | "one quick question coming." · "something here's worth a look." · "let's test it together." |

→ *"No rush — let me look at this carefully, something here's worth a look."* (slow, warm)

## 7. Anti-repetition & naturalness

1. **Sample without replacement, per bank and per slot.** Keep a ring buffer of the last
   *N* = 3 selections per bank (and optionally per slot); exclude them from the next draw.
   (Today's code excludes only the last-1 phrase — extend to last-N.)
2. **Prosodic jitter.** Vary TTS rate ±5–8 % and the pre-lead pause 120–280 ms so even a
   repeated phrase sounds re-spoken. With a pre-synth cache, bake 2–3 jittered variants per
   utterance and sample among them.
3. **Continuation endings.** Prefer TEASE fragments ending on "so…/now…/okay so…" so the
   filler tail hands off seamlessly into the streamed first answer sentence.

## 8. Pre-synthesis & caching

- **Startup (cloud TTS path).** Enumerate the full composed set per bank, synthesize each
  once with `CloudTts`, and store `cache[utterance_string] = pcm`. This preserves today's
  "fillers ready in N ms, then instant" behavior — only the *number* of cached clips grows
  (hundreds, still a few seconds of parallel synth at startup).
- **Jetson / edge.** Pre-render the composed set to WAV offline and ship the files; load
  from disk on the Orin. Edge TTS is too slow to do at turn time, and these clips never
  change. (Consistent with the existing Jetson voice port.)
- **Lazy fallback.** If a composed utterance is somehow uncached, synthesize on demand once
  and memoize — same as the current `pick()` fallback.

Cache size is bounded: `Σ_bank (LEAD × BRIDGE × TEASE) × prosody_variants`. With the §6
sizing that is ≈ 600 × 2 ≈ 1 200 short clips — trivial on disk, a few seconds to synth.

## 9. Safety: never pre-judge the answer

The filler is committed to audio **before the answer exists**, so:

- ✅ It may reflect the student's *affect/intent* — that is what the classifier gave us
  ("Good question, let me think about that").
- ❌ It must **never** assert correctness ("Yes, that's right!", "Well done!"). The answer
  may turn out wrong; praise belongs to the graded turn, not the filler.

Concretely: the current `ack` bank ("Great!", "Well done!", "Nice work.") fires *before*
grading and is therefore **removed** in this design. Acknowledgement that something was
*heard* is fine ("Okay,", "Right,"); acknowledgement that it was *correct* is not.

## 10. Bank catalog

Each bank is a slot grammar (LEAD/BRIDGE/TEASE). Representative composed outputs shown.

| Bank | Routes from (primary signals) | Tone | Example composed filler |
|---|---|---|---|
| `empathic` | anxiety, frustration, cognitive_overload, disengagement, low_confidence, prerequisite_weakness; or `frustration_risk≥0.6` / `cognitive_load≥0.7` / `confidence≤0.25` | slow, warm | "That's okay — let's take this slowly, one step at a time." |
| `hint` | request_hint, hint_dependency | light | "Sure — here's a small nudge to get you going." |
| `example` | example_request | engaged | "Good idea — let me line up an example for you." |
| `represent` | representation_shift, request_representation, diagrammatic, graphical, tabular, physical, verbal_analogy | curious | "Let me show you this another way, so it clicks." |
| `simplify` | simplification_request | calm | "No problem — let's strip it back to the basics." |
| `shift` | topic_shift | accommodating | "Sure — let's switch over to that now." |
| `advance` | ready_for_next, high_confidence, transfer_attempt, abstraction_attempt | energetic | "Nice — you're ready, let's push ahead." |
| `probe` | misconception_clue, recurring_error; or `misconception_probability≥0.5` | careful, curious | "Hmm — let me check one thing with you." |
| `reflect` | self_monitoring, self_correction, prerequisite_awareness | measured | "Good catch — let's step back a second and look." |
| `consider` | skepticism, conflict | thoughtful | "Fair point — let me think that through with you." |
| `question` | question | warm | "Good question — let me get to that for you." |
| `curious` | curiosity (and `confusion<0.4`) | bright | "Ooh, I like that — let's dig in." |
| `clarify` | confusion (`≥0.4`) | reassuring | "Okay — let's untangle this together." |
| `thinking` | **default**: algebraic, procedural_focus, answer_attempt, shortcut_seeking, environmental_feedback, or no fired label | neutral | "Okay — let me put this clearly for you." |

### Appendix A — every label's home bank

```
empathic : anxiety, frustration, cognitive_overload, disengagement,
           low_confidence, prerequisite_weakness
hint     : request_hint, hint_dependency
example  : example_request
represent: representation_shift, request_representation, diagrammatic,
           graphical, tabular, physical, verbal_analogy
simplify : simplification_request
shift    : topic_shift
advance  : ready_for_next, high_confidence, transfer_attempt, abstraction_attempt
probe    : misconception_clue, recurring_error
reflect  : self_monitoring, self_correction, prerequisite_awareness
consider : skepticism, conflict
question : question
curious  : curiosity
clarify  : confusion
thinking : algebraic, procedural_focus, answer_attempt, shortcut_seeking,
           environmental_feedback   (+ the neutral / no-label fallthrough)
```

(38th slot = the "no salient signal" case → `thinking`.)

## 11. Non-goals (explicit)

- **No HOPE signals and no policy action drive selection.** They are excluded by scope. (At
  filler time HOPE is mostly standing state and the policy action runs *inside*
  `loop.turn()`, i.e. after the filler is already chosen — using either would require moving
  pipeline work earlier, which this design forbids.) Cognitive signal only.
- **No pipeline edits.** No new model calls, no state writes, no changes to triage, the
  analyzer, the shadow, the HOPE detector, or the budgeting.
- **No interruption/barge-in changes.** Half-duplex behavior is unchanged.

## 12. Logging & measurement

The voice turn log (`live_turn_log.jsonl`) already records `filler` and `filler_state`. Add,
within the same write (no new pipeline surface):

```
bank                 : chosen bank
fired_signals        : decision.analysis["signals"]
prosody              : "warm-slow" | "neutral" | "bright-brisk"
repeat_within_session: bool   # was this exact utterance used earlier this session?
ttf_filler_ms        : ms from STT-final to first filler audio
```

Health targets: `repeat_within_session` rate ≈ 0 over a normal session; `ttf_filler_ms`
small and stable (cache hit). These let "feels pre-recorded" be measured, not guessed.

## 13. Failure modes & fallback

| Failure | Behavior |
|---|---|
| Empty `signals`, neutral aggregates | Cascade falls to `thinking` (always valid). |
| Composed utterance missing from cache | Lazy single synth + memoize (current fallback). |
| TTS unavailable at startup | Ship/keep a minimal `thinking` WAV set so a filler always plays. |
| Generation finishes before filler ends | Let the filler tail finish, or cut on its next continuation token; first answer sentence streams right after. |

## 14. Future extensions (out of current scope)

If the no-pipeline-change constraint is ever relaxed, the same slot engine extends cleanly:
route Layer C by the **predicted policy action** (one cheap `shadow.suggest(analysis)` call,
already feasible from `analysis` alone) and use the **standing HOPE state** as an additional
prosody modifier. The bank grammar and cache need no redesign — only the router gains inputs.
Documented here only to show the architecture does not dead-end; it is **not** part of v1.
