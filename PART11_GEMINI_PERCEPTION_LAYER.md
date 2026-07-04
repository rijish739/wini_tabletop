# Part 11 (revised) — Gemini Perception Front Door

> **Status: PROMOTED (Stage 4) — `PERCEPTION_BACKEND=gemini` is the default since
> 2026-07-02.** Stages 0–4 built, measured, and flipped. Promotion evidence
> (`eval/perception_eval_report.md`, `eval/behavioral_eval_report.md`,
> `PART11_PERCEPTION_EVAL_STATUS.md`): concept top-1/top-3 **0.930/0.990** on the frozen
> 999-row TEST split (§5.5 hardening: always-fill secondaries + MiniLM candidate hints +
> deterministic resolver cross-check `fuse_primary`); signals gated by the **behavioral
> state-trajectory eval** (state moves through the unchanged `derive_*` math — Gemini
> 0.857/0.833 vs heads 0.607/0.500), which superseded the §8 label-F1 signal gate (the
> heads win label-F1 by construction, being trained on the dense gold); intent macro-F1
> **1.0**; gate coverage **SAFETY 1.0 / NONSENSE 1.0 / 0 false-gates**. **Stages 5–6 also
> complete (2026-07-02, owner-directed):** the static block (6,062 tokens) lives in a
> Vertex context cache (`perception/vertex_cache.py`; ~1.0–1.1 s/call warm, 66% of prompt
> tokens at the cached rate, sha-guarded against a rebuilt prompt), and the MiniLM-heads
> runtime path is **retired** — `tutor_loop.py` always injects `GeminiPerception`; the
> learning-path fallback is gates + inherit-concept + neutral signals. Head artifacts stay
> on disk as eval baselines (and the resolver artifacts serve the §5.5 cross-check).
> **Part 11 is complete**; standing watch: production firing rates during the stability
> window. Full evidence: `PART11_PERCEPTION_EVAL_STATUS.md` §7–§9. See
> `CLOUD_VOICE_STATUS_AND_GOTCHAS.md` §10.
>
> **Supersedes:** the learned-head design in `PART11_INTENT_ROUTER_PLAN.md`. That
> document proposed a *new* MiniLM exemplar head for intent. This revision instead
> folds **intent routing + cognitive-signal classification + concept resolution**
> into **one Vertex Gemini call**, and retires (not rebuilds) the two existing
> MiniLM heads as well. The deterministic front-door gates, persona config, and the
> "only LEARNING moves state" invariant from the original Part 11 are **carried over
> unchanged** (see §4.2, §7.3).
>
> **Trigger:** the platform pivot from Jetson edge → cloud (Cloud Run + Firestore,
> ESP32 thin client). Once generation and STT/TTS are cloud calls, keeping three
> small local classifier heads in the brain container is the wrong trade: they are
> the system's weakest perception link (cognitive classifier 0.77 micro-F1) and a
> maintenance tax (frozen splits, `CUE_NAMES` width trap, OvR/loky crash). A single
> capable model does all three jobs and dissolves the Part 11 learned-head build.

---

## 1. The one principle

> **Gemini *perceives*. Deterministic code *decides* and *writes state*.**

Gemini replaces the **perception** layer only — "what kind of utterance is this,
which concept, which cognitive signals." Everything downstream of perception is
**unchanged**: the tuned signal→state aggregation, the EMA state writes, the
rule-based pedagogy engine, the evidence-only retrieval, the probe-graded
mastery/misconception write-backs, and the manifest-grounded answer. This keeps the
moat (state-driven, evidence-gated pedagogy) exactly where it is and confines the
change to a single, well-tested seam.

---

## 2. Scope

| | In scope (moves to Gemini) | Out of scope (unchanged) |
|---|---|---|
| **Perception** | Intent routing (8-class front door); cognitive **signals**; **concept** resolution | — |
| **Embeddings** | — | MiniLM stays for retrieval `S_rel` **and** HOPE features |
| **HOPE (KI/KT/CT)** | — | Stays on the teacher-calibrated ordinal heads (separation ≥ 1.0 gate). **Explicitly not moved** per owner decision. |
| **Decision/state** | — | `derive_cognitive_update`, `derive_state_deltas`, `apply_deltas`, `rules_decide`, `apply_probe_result`/`apply_bridge_result` |
| **Retrieval/generation** | — | 7-term rerank, cohesion, manifest-only generation |

**Net effect on artifacts:** the cognitive-signal classifier and concept resolver
are **retired from the runtime path** (kept on disk as fallback + eval baselines);
the Part 11 learned intent head and `intent_router_dataset.json` are **cancelled**;
the deterministic SAFETY/NONSENSE gates and `persona.json` are **kept**.

---

## 3. The invariant (carried from `PART11_INTENT_ROUTER_PLAN.md` §3.1)

> **Only `LEARNING`-intent utterances may move learner state (global EMAs, mastery,
> misconception status, HOPE rolling averages) or trigger maths retrieval.** Every
> other intent produces an in-character response and leaves cognitive state
> untouched.

Strengthened by the §1 principle: even for a `LEARNING` turn, the Gemini output is
*advisory input* to the **same** deterministic state machine — it never writes state
directly. `apply_probe_result` / `apply_bridge_result` remain the only paths that
move mastery, and only on graded evidence.

---

## 4. Architecture

### 4.1 New `turn()` flow

```
student text
  → [Stage A] deterministic gates: SAFETY → NONSENSE          (regex, no model, run FIRST)
  → [Stage B] ONE Gemini perception call (structured JSON):
        intent · also_learning · concept · signal_scores · answer_attempt
  → branch on intent.primary:
        ≠ LEARNING → _handle_nonlearning()  (persona/scripted; NO state move; preserve pending_check)
        = LEARNING → existing pipeline, fed via the precomputed_analysis seam:
              derive_cognitive_update → derive_state_deltas → apply_deltas   (UNCHANGED)
              → rules_decide → 7-term retrieval → manifest-grounded generation
              → pending_check / pending_hope grading → write-backs           (UNCHANGED)
```

### 4.2 Defense in depth (non-negotiable, from original Part 11 §3.2/§12)

SAFETY is **gate-only**. The deterministic SAFETY lexicon (and the cheap NONSENSE
gate) run **before** the Gemini call and short-circuit to a **fully scripted**
reply. Gemini may *also* surface a `safety` flag as a secondary recall net, but it
may **never downgrade** a gate-flagged safety case, and the system's safety
guarantee never depends on a model being available, fast, or correct.

### 4.3 Per-intent handler contracts (decisions resolved 2026-06-30)

Eight top-level intents. Each handler's state effect is part of the contract; only
LEARNING may move cognitive state (§3).

| Intent | Handler behavior | State effect | Response source |
|---|---|---|---|
| **LEARNING** | existing pipeline, unchanged | normal (full) | manifest-grounded generation |
| **SOCIAL** | warm persona reply, gentle steer back to maths | none | persona / canned |
| **META_CAPABILITY** | honest "here's what I can do" + offer to learn | none | persona |
| **OFF_DOMAIN_ACADEMIC** | **one accurate one-line answer, then redirect to maths** | none | persona + 1 factual sentence |
| **SESSION_CONTROL** | **accept immediately + warm goodbye/pause; NO maths question, no retention; explicit bye OR 2nd leave request = hard stop (`session_ended` → runner exits); preserve `pending_check` + learner state** | **session flags only** (cognitive state untouched) | persona (pause) / scripted farewell (end) |
| **EMOTIONAL** | acknowledge feeling, light support, offer continue-or-pause | none | persona |
| **SAFETY** ⚠️ | **deterministic gate → scripted calm reply + "tell a trusted adult" + persisted `safety_alert` + active supervisor notification** | none + alert | fully scripted |
| **NONSENSE** | "I didn't catch that — can you say it again?" | none | scripted |

**OFF_DOMAIN_ACADEMIC (Q1 resolved).** Give **exactly one** correct sentence, then
steer back — e.g. *"Paris is the capital of France. But I'm your maths buddy — shall
we get back to [current concept]?"* The factual line is hard-capped at one sentence so
the answer is honest without inviting scope creep; never elaborate or continue the
off-domain thread.

**SAFETY (Q2 resolved — "best safety").** Highest-assurance path, never log-only:
(1) the deterministic high-recall gate **owns the decision** (the model may only *add*
recall, never remove it); (2) an immediate **scripted** calm, supportive reply
pointing the child to a trusted adult; (3) a **persisted `safety_alert` record**; and
(4) an **active notification to the supervising adult** (parent/teacher) over the most
reliable channel the deployment has — in cloud, a flagged Firestore record that fires a
push/email/dashboard alert; on device, a visible/audible supervisor signal. The reply
is fixed and human-reviewed; no model improvisation.

**SESSION_CONTROL (Q3 resolved — chose the better-for-pedagogy option).**
*What it is:* utterances where the child manages the **session**, not the maths —
"stop", "I'm tired", "I'm bored", "let's take a break", "bye", "I don't want to study",
"can we do something else". *Why a real session effect beats a verbal-only reply:*
honoring an expressed desire to stop/pause is **autonomy support** (self-determination
theory → higher intrinsic motivation), respects **cognitive-load / fatigue** limits (a
tired learner encodes poorly and builds negative affect toward maths), and protects
**trust** in a child-facing device. So the handler does three things: (a) **acknowledge**
the feeling/request warmly and **accept it** — praise the work done, no maths question,
no "one more sum" (the original "secure a small win" off-ramp was **REVISED 2026-07-03**
after kid testing: the LLM read it as licence to retain — "let's just quickly finish this
one small sum" after an explicit bye — see `gemini_tutor_issues.md` #1/#5); (b) apply the
**end-of-session hard rule**: an explicit goodbye, or a **second leave request in a row**,
sets `status="ended"` and the reply is a **scripted** farewell (never the LLM — zero
chance of an appended question); the turn result carries `session_ended=True` and every
runner (CLI, push-to-talk, `--live` mic loop) stops taking turns; (c) set a
**real, lightweight session flag** (`session.status ∈ {active, paused, ended}` /
`break_requested` / `leave_requests` counter) so the engine stops pushing maths, while
**preserving `pending_check` and all learner cognitive state** so nothing is lost. Next
turn (a new session): a learning utterance resumes the preserved question and resets the
leave counter. This is intentionally a few flags, not a heavy state machine, for v1. Only
the first, *soft* pause request may use the persona LLM, and its prompt forbids asking
any question or proposing a problem.

---

## 5. The single Gemini perception call

### 5.1 Request

- **Model:** Gemini 2.5 Flash on Vertex AI, region `asia-south1`. Low cost, fast;
  structured output + context caching supported.
- **Generation config:** `temperature = 0`, `response_mime_type = application/json`,
  `response_schema` = the enum-constrained schema in §5.3. Hard wall-clock timeout
  (CLAUDE.md gotcha: LLM calls need explicit timeouts — SDK-level timeouts have
  stalled for hours).
- **Cached (static) block** — via Vertex **context caching**, embedded once:
  - the intent taxonomy + per-intent definitions,
  - the canonical **signal** label list + one-line definition each (generated from
    the shipped classifier label artifact — see §5.4),
  - the **concept catalog** (108 ids + display names, generated from
    `models/concept_resolver/concepts_meta.json`),
  - a handful of few-shot anchors drawn from the **TRAIN** split only.
- **Per-turn (dynamic) block:**
  - `normalized_text` (reuse `InputProcessor.normalize_input` — keep the same
    normalization the heads saw),
  - session context: `current_concept`, `last_action`, and the open
    `pending_check.question` if one is armed (lets Gemini judge `answer_attempt`),
  - a short rolling history window (last 1–2 turns).

### 5.2 Why context caching matters here

The concept catalog + signal definitions are large and static; re-sending them every
turn is the dominant token cost and adds latency. Caching them makes each call a
small dynamic delta → **fraction of a cent/turn** and **lower latency**.

### 5.3 Response schema (enum-constrained)

```json
{
  "intent": "LEARNING | SOCIAL | META_CAPABILITY | OFF_DOMAIN_ACADEMIC | SESSION_CONTROL | EMOTIONAL | SAFETY | NONSENSE",
  "also_learning": false,
  "concept_id": "<one of the 108 catalog ids> | INHERIT_CURRENT_CONCEPT",
  "concept_confidence": 0.0,
  "secondary_concepts": ["<catalog id>", "..."],
  "signal_scores": { "confusion": 0.0, "curiosity": 0.0, "...": 0.0 },
  "answer_attempt": false,
  "safety": false
}
```

- `concept_id` enum is generated from the catalog, so Gemini **cannot** emit an
  out-of-vocab concept. `INHERIT_CURRENT_CONCEPT` is the abstain sentinel.
- `signal_scores` keys are constrained to the canonical label set (§5.4); values in
  `[0,1]` so the existing `derive_cognitive_update` (which reads continuous scores)
  works unchanged.
- `answer_attempt` directly feeds the §7.4 non-attempt logic.

### 5.4 Label/concept enums are **generated, never hand-typed**

At build time, `build_perception.py` reads the **shipped** classifier label list and
`concepts_meta.json` and writes the schema enums + the cached definition block. This
honors the CLAUDE.md `CUE_NAMES`/width-coupling spirit: the schema is derived from
the artifacts of record, so it can't silently drift from them.

### 5.5 Output validity & anti-generosity calibration

Two distinct failure modes, two distinct defenses.

**(a) Out-of-vocabulary — a hard guarantee.** `intent`, `concept_id`, and each
`signals` item are **`enum`** fields in `response_schema` (with
`response_mime_type = application/json`). Vertex controlled generation masks decoding
to schema-valid tokens, so the model **cannot** emit a concept outside the 108-catalog
(+ `INHERIT_CURRENT_CONCEPT`), a signal outside the canonical set, or an intent outside
the 8 classes. A **local validation belt** backs this up: parse → assert every field is
in its allowed set → drop/coerce anything invalid → on parse failure, fall back
(inherit-concept + neutral). Net: no OOV value ever reaches the state machine. (Enums
stop *invented* values; they do **not** stop a *wrong-but-valid* pick — that is (b).)

**(b) Generosity (in-vocab over-firing) — calibrated, not trusted raw.** Layered:
- **`temperature = 0`** — deterministic, no sampling noise.
- **Conservative prompt** — each signal definition carries its *negative boundary*
  ("do NOT flag confusion for an acknowledgment or a neutral next-question request") and
  an explicit **default-to-absent / default-to-INHERIT** rule; a positive requires a
  quotable span from the utterance. Reuses the tuned `label_space.py` / `cues.py`
  boundaries (e.g. the `acknowledgment` vs `confusion` rule).
- **Downstream thresholds own the decision, not the model's score.** The existing
  `FLAG_THRESHOLD` / `MISCONCEPTION_FLAG_THRESHOLD` and the concept abstain `tau` are
  **re-calibrated on the frozen TEST split** to Gemini's score distribution; a generous
  skew is absorbed by raising the operating point.
- **Deterministic gates** remove the model from the highest-stakes/easiest cases
  (SAFETY, NONSENSE, strong greetings), where generosity is most dangerous or most likely.
- **Balanced few-shot** includes neutral / "nothing detected" / inherit anchors so the
  model learns an empty result is common and correct.
- **Consistency belt** — non-LEARNING ⇒ signals forced empty; `is_pure_ack` overrides a
  spurious `confusion`; etc.
- **The Stage 2 eval gate is the backstop:** an over-firing model tanks precision and
  fails to beat the 0.77 micro-F1 / 0.895 top-1 baselines, so it cannot be promoted.
  Stage 1 shadow + production firing-rate monitoring catch drift over time.

**Optional concept hardening (hybrid).** Because MiniLM stays for retrieval, the top-K
concepts by embedding similarity can be passed as the *only* candidates Gemini chooses
among (108-way → K-way), and/or Gemini's pick can be cross-checked against the resolver
— disagreement ⇒ abstain/inherit. Cheap precision boost using assets already loaded.

---

## 6. Reusing the deterministic aggregation (the key to low risk)

Gemini produces only `signal_scores` + `concept` + `intent`. The mapping from those
to learner-state deltas stays **exactly** as today:

```
gemini → signal_scores (dict) , signals (= scores ≥ FLAG_THRESHOLD) , concept(dict)
       → derive_cognitive_update(signal_scores)          # cognitive_analyzer/analyzer.py:46  (UNCHANGED)
       → derive_state_deltas(update, signals, resolution)# cognitive_analyzer/analyzer.py:87  (UNCHANGED)
       → apply_deltas(state, deltas)                     # cognitive_analyzer/analyzer.py:124 (UNCHANGED)
```

So the tuned EMA weights, the `MISCONCEPTION_FLAG_THRESHOLD = 0.4` probe-first bias,
and the flag derivation remain the single source of truth. Gemini changes **what is
perceived**, not **how perception moves state**.

The `concept` block must match the existing resolver contract
(`concept_resolver/resolver.py:155-176`):

```json
{ "concept_id": "...", "concept_confidence": 0.0, "secondary_concepts": [],
  "abstained": false, "resolution_reason": "..." }
```

Mapping: `INHERIT_CURRENT_CONCEPT` ⇒ `abstained = true` and
`concept_id = current_concept` (identical to the resolver's abstain branch).

---

## 7. Integration points (exact, minimal-edit)

### 7.1 Recommended wiring — inject one perception object

`CognitiveAnalyzer.__init__` already accepts injected `classifier`/`resolver` stubs.
Implement **one** `GeminiPerception` object that:

- makes **one** cached Gemini call per utterance (memoized by normalized text),
- exposes `.classify(text)` → `{"scores": {...}, "signals": [...]}` (reads cache),
- exposes `.resolve(text, current_concept)` → resolver-shaped dict (reads cache),
- exposes `.route(text, session)` → `RouteResult` (intent/also_learning/safety),
- exposes `.embedder` → a lazily-loaded MiniLM (for HOPE + chunk index).

Then in `TutorLoop.__init__`:

```python
if PERCEPTION_BACKEND == "gemini":
    gp = GeminiPerception(...)
    self.analyzer = CognitiveAnalyzer(classifier=gp, resolver=gp)   # analyze() works UNCHANGED
else:
    self.analyzer = CognitiveAnalyzer()                              # MiniLM heads (today)
```

Because `self.analyzer.classifier` is now `gp`, the existing
`self.analyzer.classifier.embedder` references at **tutor_loop.py:394** (HOPE) and
**:396** (chunk index) keep working with **zero edits**. `CognitiveAnalyzer.analyze`
(analyzer.py:170) is also untouched — it calls `classify` then `resolve` then the
`derive_*` helpers, exactly as in §6.

### 7.2 Step 0 in `turn()`

Add the front door at the top of `TutorLoop.turn` (**tutor_loop.py:464**), before
the analysis at :466–468:

```python
# 0. front door (deterministic gates → Gemini route)
route = self.gate(text) or self.analyzer.classifier.route(text, session)
if route.safety_alert:
    self._log_safety(text, route)
if route.primary != "LEARNING":
    return self._handle_nonlearning(route, text, answer_budget)   # no state move
# else: existing pipeline. Pass the cached analysis through the precomputed seam:
analysis = self.analyzer.analyze_and_apply(text, self.state, current_concept=self.current_concept)
```

(The Gemini call is already memoized, so `route()` and the subsequent
`analyze_and_apply` share **one** network round-trip.)

### 7.3 `_handle_nonlearning` contract (verbatim from original Part 11 §6.1)

MUST NOT call `analyze_and_apply` (use `analyze_only`, tutor_loop.py:412, if logging
is needed); MUST NOT arm/grade `pending_check`/`pending_hope`; **MUST preserve an
open `pending_check`** so the next learning turn returns to the question; MUST NOT
run retrieval; uses persona prompt (SOCIAL/META/OFF_DOMAIN/EMOTIONAL/SESSION) or a
**scripted** reply (SAFETY/NONSENSE); still logs to `learning_log.jsonl` with the
resolved intent; returns the **same result-dict shape** as `turn()` with
`display: []`.

### 7.4 `answer_attempt` strengthens the non-attempt guard

The 1a guard (tutor_loop.py:479-500) currently infers "is this an attempt at the
pending question" from cues. Gemini's `answer_attempt` becomes the primary signal,
with the existing cues as fallback:

```python
answer_try = route.answer_attempt or ("answer_attempt" in _sig) or is_answer_attempt(text)
```

This directly attacks the logged regression where "i can not understand" was graded
`wrong` and dropped mastery.

---

## 8. Implementation stages

Each stage is independently shippable, reversible (feature-flagged), and gated by an
acceptance criterion. **Do not promote a stage until its gate is green.**

### Stage 0 — Vertex plumbing & feature flag
- `llm_vertex.py`: shared Vertex client (ADC creds, `asia-south1`, model id, **hard
  timeout**, bounded retry). This is the same client generation will later reuse.
- Config flag `PERCEPTION_BACKEND ∈ {qwen_heads (default), gemini}`; SAFETY/NONSENSE
  gates available independently of the flag.
- **Gate:** a smoke test issues one structured call and parses valid JSON against the
  schema.

### Stage 1 — Perception adapter in **shadow**
- `perception/gemini_perception.py`: implement `GeminiPerception` (§7.1) returning
  the analysis-dict shape; `build_perception.py` generates the schema enums + cached
  block from the artifacts of record (§5.4).
- Run it in **shadow** (like `policy_shadow`): on each turn, call both the MiniLM
  heads (authoritative) and Gemini (logged only); write both to `learning_log.jsonl`.
- **Gate:** over a replayed transcript, Gemini output validates against the schema
  and produces a well-formed analysis dict on 100% of turns; zero unhandled
  exceptions; latency recorded.

### Stage 2 — Offline eval & promotion gate
- `eval/perception_eval_*.jsonl` built from the **TEST** rows of the frozen splits
  (`models/exemplar_classifier/splits.json`) — **new files; originals stay
  read-only**. Few-shot anchors come from TRAIN only (no val/test leakage).
- Harness (parallels `cognitive_analyzer/test_analyzer.py`) reports, with Gemini
  graded against the **same** TEST rows the heads were measured on:

  | Metric | Baseline to beat | Source |
  |---|---|---|
  | Concept top-1 / top-3 | **0.895 / 0.971** | resolver |
  | Signal micro-F1 / macro-F1 | **0.77 / 0.62** | cognitive classifier |
  | Intent macro-F1 (non-safety) | set after first run | new |
  | **SAFETY recall** | **~100%** (via gates) | new, adversarial probe set |
  | LEARNING→non-LEARNING mis-route | minimal | new |

- **Gate:** Gemini ≥ baselines on concept + signals, intent macro-F1 acceptable,
  SAFETY recall ~100%. Writes `eval/perception_eval_report.md`. (CLAUDE.md: never
  promote a number without re-measuring it.)

### Stage 3 — Model-free front door (ships independently of the backend flag)
- `perception/gates.py` (SAFETY + NONSENSE deterministic, from original Part 11
  §5.1), `persona.json`, `_handle_nonlearning`, `_log_safety`, and the
  **LEARNING no-op regression test** (turn() output byte-for-byte identical to
  pre-router on a fixed LEARNING transcript).
- **Gate:** regression test passes; social / safety / nonsense produce correct
  in-character replies and move no state.

### Stage 4 — Promote perception to authoritative
- Flip `PERCEPTION_BACKEND = gemini`. Intent + signals + concept now come from
  Gemini; `derive_*`/`apply_deltas` reused unchanged; MiniLM embedder retained for
  HOPE + retrieval.
- Robustness: on Gemini timeout/parse-failure, **fall back** to (a) gates for
  SAFETY/NONSENSE always, and (b) `INHERIT_CURRENT_CONCEPT` + neutral signals for
  the learning path (a turn never hard-fails). Optionally fall back to the still-
  loaded MiniLM heads.
- **Gate:** full regression suite green; live latency within §10 budget; a week of
  shadow logs shows no material divergence from the eval expectation.

### Stage 5 — Latency & cost tuning
- Move the static block to Vertex **context cache**; confirm per-turn token cost
  drops. Record p50/p95 added latency and per-turn cost.
- (Forward hook) when generation embeddings later move to a Vertex embeddings API,
  run the query-embedding call **in parallel** with this perception call — same raw
  text, no added critical-path latency. *Out of scope for this Part; noted so the
  interface is parallel-friendly.*
- **Gate:** added critical-path latency and per-turn cost within budget.

### Stage 6 — Lockstep propagation & cleanup
- Propagate to the four docs + work log (§12). Mark the cognitive classifier, concept
  resolver, and the Part 11 learned-head design as **superseded by this Part**.
- **Remove the sklearn heads from the runtime** once Gemini has been authoritative and
  stable (owner decision, post-Stage-4). This is a *maintenance* simplification, **not**
  a cold-start fix: MiniLM/torch stay in the container for HOPE + retrieval embeddings,
  so cold start is handled at the platform level by **Cloud Run `min-instances=1`** (one
  warm instance), not by removing the heads. Retain the head artifacts in the repo as
  the eval baseline.
- After removal, the learning-path fallback (Stage 4) becomes **gates + inherit-concept
  / neutral signals** (the heads are no longer available to fall back to).

---

## 9. Data & evaluation rules

- **New files only.** `eval/perception_eval_*.jsonl` and the few-shot anchor file are
  new; `exemplar_dataset_10000_*.json`, `splits.json`, and `concepts_meta.json` stay
  **read-only** (CLAUDE.md). The frozen splits are *repurposed as the eval contract*,
  not re-split.
- **SAFETY** is measured on an oversampled adversarial probe set and is satisfied by
  the deterministic gate, never by the model alone.
- **Console:** pass `PYTHONIOENCODING=utf-8` in eval scripts that print dataset text
  (cp1252 console gotcha).

---

## 10. Latency, cost, failure modes

- **Latency:** +1 Gemini Flash call (~300–600 ms, small structured output) on the
  critical path *before* retrieval. Mitigated by Flash + context caching + a tight
  dynamic prompt. This is the deliberate cost paid for accuracy + simplicity.
- **Cost:** a fraction of a cent/turn on Flash; caching removes the static-token tax.
  Negligible beside STT/TTS minutes.
- **Failure:** hard timeout around the call; deterministic gates keep SAFETY/NONSENSE
  alive without the model; learning path degrades to inherit-concept + neutral
  signals (or the MiniLM heads, while they remain) so a turn never crashes.
- **Cold start (deployment):** MiniLM/torch remain in the brain container (HOPE +
  retrieval embeddings), so the container is not torch-free. Cold start is absorbed by
  **Cloud Run `min-instances=1`** (one always-warm instance) — the chosen mitigation —
  rather than by removing local models.

---

## 11. Config / flags

- `PERCEPTION_BACKEND = qwen_heads | gemini` (default `qwen_heads` until Stage 4).
- `PERCEPTION_SHADOW = true|false` (Stage 1: log Gemini beside the heads).
- `VERTEX_REGION = asia-south1`, `VERTEX_PERCEPTION_MODEL = gemini-2.5-flash`,
  `PERCEPTION_TIMEOUT_S` (hard wall-clock).
- Front-door gates (`perception/gates.py`) run regardless of backend.

---

## 12. Documentation lockstep (on build, per CLAUDE.md)

This touches behavior + schema + dataset + model, so on **implementation** it
propagates in the same work session:

1. `learner_cognitive_state_architecture.md` — perception is now a Gemini structured
   call; the intent taxonomy + "only LEARNING moves state" contract; the
   signal/concept schema; the unchanged `derive_*`/write-back boundary.
2. `complete_architecture_build_plan.md` — this **Part 11 (revised)** with measured
   results; mark the classifier/resolver Parts superseded for the runtime path.
3. `model_dataset_architecture_report.md` — datasets repurposed as eval; replace the
   0.77/0.895 head numbers with the measured Gemini numbers (re-measured, not edited).
4. `RAG_upgrade_plan.md` — note that perception + non-learning replies are a
   documented exception to "compose only from the manifest" (they are persona/schema
   grounded, not store-grounded).
5. `rag_memory.md` — work-log entry + gotchas; `WINI_ARCHITECTURE.md` — external-shape
   update (the front door changes outward behavior).

> **Mandate note:** the CLAUDE.md hard mandate "LLM calls use the LOCAL Qwen model
> only … no Gemini/Vertex clients" has been **updated (2026-06-30, this session)** to
> the cloud/Vertex direction (perception + generation on Gemini; HOPE + embeddings stay
> MiniLM; staged + feature-flagged; local Qwen retained as legacy/fallback). Keep
> CLAUDE.md and this Part consistent as stages land.

---

## 13. Risks & open questions

**Risks**
- **Determinism.** A learned head is deterministic; Gemini is not. Mitigate with
  `temperature = 0`, strict `response_schema`, and enum-constrained concept/signal
  fields so output is always parseable and in-vocab.
- **Safety recall.** Keep deterministic, over-trigger, human-reviewed lexicon; the
  model never owns the guarantee.
- **Latency creep.** Two sequential Gemini calls per learning turn (perceive →
  generate). Budget and measure; caching + Flash keep perceive cheap.
- **Eval honesty.** Promotion is gated on the frozen TEST split; do not let few-shot
  anchors leak from val/test.

**Resolved decisions (2026-06-30)**
1. `OFF_DOMAIN_ACADEMIC` → **one accurate sentence, then redirect** (§4.3).
2. SAFETY → **best-assurance path**: deterministic gate + scripted reply + persisted
   alert + **active supervisor notification** (not log-only) (§4.3).
3. `SESSION_CONTROL` → **real lightweight session flags + autonomy-supportive graceful
   off-ramp**, preserving `pending_check` + learner state (§4.3) — chosen as the
   better-for-pedagogy option over verbal-only.
4. MiniLM heads → **removed after Stage 4** once Gemini is stable (kept as eval baseline
   in the repo); cold start handled by Cloud Run `min-instances=1` (Stage 6, §10).

---

## 14. File map (new artifacts on build)

```
perception/
  __init__.py
  gates.py              # Stage A deterministic SAFETY + NONSENSE gates
  gemini_perception.py  # GeminiPerception: one cached call; classify/resolve/route/embedder
  build_perception.py   # generate schema enums + cached block from artifacts of record
persona.json            # identity + canned SOCIAL/SAFETY/NONSENSE replies (from orig Part 11)
llm_vertex.py           # shared Vertex client (perception now; generation later)
eval/
  perception_eval_*.jsonl   # from frozen TEST split (new files; originals read-only)
  perception_eval_report.md
tutor_loop.py           # +step 0 front door, +_handle_nonlearning, +_log_safety,
                        #  +backend flag wiring  (edits only; analyzer.py untouched)
```

The cognitive classifier, concept resolver, policy shadow, HOPE detector,
`learner_state.py`, `query.py`, and `cognitive_analyzer/analyzer.py` are **not
modified** — the classifier/resolver are swapped by injection, and the analyzer's
`derive_*` math is reused as-is.
