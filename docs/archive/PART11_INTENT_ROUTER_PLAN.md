# Part 11 — Utterance Intent Router ("Front Door")

> **Status:** DESIGN ONLY (2026-06-30). Not yet built. No code or lockstep-doc
> changes have been made. This document is the design of record to be reviewed
> before any implementation begins.
>
> **Trigger:** Live kid testing showed children routinely address the robot with
> non-learning utterances ("how are you", "what is your name", jokes, "I'm tired",
> emotional asks, gibberish). The system handles these badly because it has no
> concept of an utterance that is *not* a maths learning move.

---

## 1. Problem statement

### 1.1 The single-path assumption

`TutorLoop.turn()` ([tutor_loop.py:464](tutor_loop.py)) has exactly one processing
path. Every utterance, regardless of what it is, flows:

```
text
  -> analyze_and_apply           (37 learning-state labels + concept resolver)   [tutor_loop.py:468]
  -> rules_decide                (pedagogy action)                               [tutor_loop.py:580]
  -> maths retrieval             (bridge / misconception / need / chunk)         [tutor_loop.py:595]
  -> qwen_answer                 ("Use ONLY the evidence below ...")             [tutor_loop.py:235]
  -> writes engagement/confusion EMAs; may arm/grade pending_check + pending_hope
```

The entire stack **assumes the input is a Class-10 Maths learning move.** Evidence
in the code:

- The cognitive classifier's label space is *all* learning-state signals
  (confusion, curiosity, misconception, transfer_attempt, ...) — there is no label
  meaning "this is not a learning utterance at all"
  ([cognitive_classifier/label_space.py](cognitive_classifier/label_space.py)).
- The concept resolver can only **abstain**; the loop proceeds into maths retrieval
  regardless ([tutor_loop.py:589-599](tutor_loop.py)).
- `qwen_answer` is explicitly forbidden from saying anything not grounded in the
  retrieved maths evidence: *"Use ONLY the evidence below — if it does not support a
  claim, say less."* ([tutor_loop.py:235](tutor_loop.py)).

### 1.2 What goes wrong for off-domain input

When a child says "what is your name":

1. The concept resolver false-anchors to a maths concept or abstains.
2. Retrieval pulls irrelevant maths chunks.
3. Qwen, told to use only those chunks, produces a confused, empty, or wrong reply.
4. The learner-state EMAs (engagement, confusion, cognitive_load) drift on pure
   noise via `apply_deltas` ([cognitive_analyzer/analyzer.py:124](cognitive_analyzer/analyzer.py)).
5. If a `pending_check` is open from the previous turn, the off-topic reply can be
   mis-graded (the non-attempt guard at [tutor_loop.py:499](tutor_loop.py) catches
   *some* of this, but only classifies it as "not an answer" — it does not give the
   child a real social/empathetic response).

### 1.3 Why this is architectural, not a labeling bug

This cannot be fixed by adding training rows or a label. The system is missing a
**layer**: a top-level decision about *what kind of utterance this is* before any
learning machinery runs. The fix is a new front-door router.

---

## 2. Scenario inventory

The failures are broader than chit-chat. Children produce at least these categories:

| Intent | Representative utterances | Current failure mode |
|---|---|---|
| **SOCIAL / rapport** | "what's your name", "how are you", "are you a robot", "do you like me", "how old are you", "who made you" | force-fit into maths retrieval |
| **META / capability** | "what can you do", "tell me a joke", "can you sing", "can you dance", "play a game" | no honest capability answer; manifest has none |
| **OFF-DOMAIN academic** | "capital of France", "spell elephant", science homework, "what's 9th std physics" | answered from maths chunks or refused |
| **SESSION control** | "stop", "I'm tired", "bye", "I don't want to study", "let's do something else", "take a break" | treated as a maths answer / non-attempt |
| **EMOTIONAL / personal** | "I'm sad", "I had a fight with my friend", "I'm hungry", "I'm bored" | empathy needed; gets a maths probe |
| **SAFETY-critical** ⚠️ | distress, self-harm, harm disclosure ("someone hurt me") | **must never** get a maths reply — highest stakes for a child-facing robot |
| **NONSENSE / ASR garbage** | gibberish, "blah blah", profanity-testing, empty/half-words from STT | mis-graded, EMA drift |
| **Embodiment (spoken)** | "wave", "touch your nose", "look at me", "move your ears" | partly handled by the Jetson **sensor** reflex layer (chin/ear), but *spoken* requests are not |
| **Multi-intent** | "hi, can you teach me fractions" | social + learning collapsed into one wrong path |

> **Boundary note (embodiment):** the Jetson reflex layer already handles physical
> *sensor* events (chin touch → BLUSH; ears disabled per EAR_ACTUATION_ISSUE.md).
> The router handles *spoken* embodiment requests only, and should defer to / not
> conflict with the reflex layer. Treat spoken embodiment as a sub-type of
> META_CAPABILITY in v1.

---

## 3. Solution overview

Add an **Utterance Intent Router** that runs as **step 0** of `turn()`, before the
cognitive analyzer. It classifies each utterance into a small fixed taxonomy. Only
`LEARNING` flows into the existing pipeline unchanged; every other intent is
dispatched to a bounded handler.

### 3.1 The new invariant

> **Only `LEARNING`-intent utterances may move learner state (global EMAs, mastery,
> misconception status, HOPE rolling averages) or trigger maths retrieval.** All
> other intents produce an in-character response and leave cognitive state
> untouched.

This is a strict extension of two rules already in the system:
- "state moves only on evidence" (CLAUDE.md, architecture §10/§13 rule 8), and
- the non-attempt guard that already refuses to grade acks/confusion as answers
  ([tutor_loop.py:499](tutor_loop.py), memory: grading-loop-guardrails).

### 3.2 Design principles

1. **Defense in depth.** High-stakes intents (SAFETY) are caught by deterministic,
   auditable gates, never left to a 3B model or a soft classifier head.
2. **Fail safe toward teaching.** When the learned head is unsure, default to
   `LEARNING` — the home turf — *except* that SAFETY is gate-only and overrides.
3. **Reuse, don't duplicate.** Share the MiniLM embedder already in VRAM; mirror the
   existing `cues.py` + exemplar-bank pattern; keep the intent head a **separate
   artifact** from the cognitive classifier.
4. **Persona is config, not code.** One source of truth for identity and canned
   responses so all surfaces (web / Windows / Jetson) answer identically.

---

## 4. Intent taxonomy and handler contracts

Eight top-level classes. Each handler's state effect is part of the contract.

| Intent | Handler behavior | State effect | Response source |
|---|---|---|---|
| **LEARNING** | existing pipeline, unchanged | normal (full) | manifest-grounded Qwen |
| **SOCIAL** | warm persona reply, gentle steer back to maths | none | persona prompt / canned |
| **META_CAPABILITY** | honest "here's what I can do" + offer to learn | none | persona prompt / canned |
| **OFF_DOMAIN_ACADEMIC** | "I'm your maths buddy" redirect (optional 1-line answer) | none | persona prompt |
| **SESSION_CONTROL** | pause / resume / graceful goodbye / encourage | session flags only | persona prompt / canned |
| **EMOTIONAL** | acknowledge feeling, light support, offer continue-or-pause | none | persona prompt |
| **SAFETY** ⚠️ | scripted calm support + "tell a trusted adult" + supervisor alert | none + alert log | **fully scripted** |
| **NONSENSE** | "I didn't catch that — can you say it again?" | none | **fully scripted** |

### 4.1 Multi-intent handling

The router returns a structured result, not a bare label:

```
RouteResult {
    primary: str            # one of the 8 intents
    scores: dict[str,float] # per-intent confidence (Stage B) or 1.0 (Stage A gate)
    also_learning: bool     # a learning ask is also present (e.g. "hi, teach me fractions")
    matched_by: str         # "gate:safety" | "gate:social" | "head" | "default"
    safety_alert: bool
}
```

If `primary != LEARNING` but `also_learning` is true, the handler emits a one-line
social/empathetic acknowledgement and then **falls through to the LEARNING path**.

---

## 5. Router architecture — two stages

New package `intent_router/` (parallels `cognitive_classifier/` and `concept_resolver/`).

### 5.1 Stage A — deterministic gates (`intent_router/gates.py`)

Checked in **stakes order**, first match wins. Built in the style of
[cognitive_classifier/cues.py](cognitive_classifier/cues.py) (compiled regex +
keyword lexicons), so they are auditable and require no model.

1. **SAFETY gate** — curated high-recall lexicon (self-harm, harm disclosure, abuse,
   violence, "I want to die", "someone is hurting me"). Deliberately over-triggers.
   Returns a **scripted** response (never a model improvisation) and sets
   `safety_alert = true` so the supervising adult is notified via the log/UI.
2. **NONSENSE gate** — empty, below a minimum token count, no alphabetic content, or
   ASR-garbage heuristics (e.g. single repeated syllable, no dictionary words).
3. **Strong SOCIAL gate** — greetings and identity questions ("what is your name",
   "how are you", "hi/hello", "are you a robot"). Resolves the exact, highest-
   frequency cases seen in testing instantly and deterministically.

Anything not matched by Stage A falls through to Stage B.

### 5.2 Stage B — learned intent head (`intent_router/router.py`)

- **Embedder:** reuse `self.analyzer.classifier.embedder` (the MiniLM already loaded
  in VRAM — see [tutor_loop.py:392-396](tutor_loop.py) for the same sharing pattern
  used by HopeDetector). No new heavy model.
- **Head:** a small **single-label** logreg or kNN exemplar bank over an intent
  exemplar set, same construction as `build_bank.py`. Single-label because top-level
  intent is mutually exclusive (multi-intent is handled by the `also_learning` flag,
  computed from a cheap secondary LEARNING-cue check, not from multi-label output).
- **Abstain → LEARNING.** If max class probability is below a calibrated threshold,
  default to `LEARNING`. SAFETY is **never** assigned by the head (gate-only), so a
  low-confidence head can never *downgrade* a safety case.
- **Separate artifact.** Stored under `models/intent_router/`. **Do NOT** extend
  `cues.CUE_NAMES` or the cognitive classifier's logreg widths — CLAUDE.md gotcha:
  that width is baked into the shipped classifier bank *and* the policy shadow, and
  changing it forces a full rebuild of both. The intent router is independent.

---

## 6. Integration into `turn()`

A new **step 0** at the top of `TutorLoop.turn()` (before the step-1 analysis at
[tutor_loop.py:466](tutor_loop.py)):

```python
# 0. front door: what KIND of utterance is this?
intent = self.router.route(text, session)
if intent.safety_alert:
    self._log_safety(text, intent)            # supervisor-visible alert
if intent.primary != "LEARNING":
    return self._handle_nonlearning(intent, text, answer_budget)
# else: existing pipeline runs unchanged.
# if intent.also_learning, _handle prepends a one-line social ack to the answer.
```

### 6.1 `_handle_nonlearning` contract (the heart of the invariant)

The handler MUST:

- **NOT** call `analyze_and_apply` (no EMA drift). If any analysis is needed for
  logging, use `analyze_only` ([tutor_loop.py:412](tutor_loop.py)), which does not
  mutate state.
- **NOT** arm or grade `pending_check` / `pending_hope`.
- **Preserve an open `pending_check`.** If the tutor asked a maths question last turn
  and the child goes off-topic, the handler answers the off-topic utterance and
  **leaves `pending_check` in place**, so the next learning turn returns to the
  question. (Today an off-topic reply pops or mis-handles it.)
- **NOT** run bridge / misconception / need / chunk retrieval.
- Use a **Wini-persona prompt** for SOCIAL / META / OFF_DOMAIN / EMOTIONAL /
  SESSION_CONTROL — warm, age-appropriate, NOT the manifest-only prompt. For
  **SAFETY** and **NONSENSE**, use a **fully scripted** reply (no Qwen freedom).
- Still **log** to `learning_log.jsonl` with the resolved intent and `matched_by`,
  so real-world intent frequencies can be measured and the head retrained.
- Return the same result dict shape as `turn()` (so the voice/Jetson layers consume
  it unchanged), with `action` set to a router action label (e.g. `SOCIAL_REPLY`,
  `SAFETY_RESPONSE`, `REPROMPT`) and `display: []`.

### 6.2 Regression guarantee

When `intent.primary == LEARNING` and `also_learning` is false, `turn()` must behave
**exactly** as it does today — the router is a pure no-op on learning turns. This is
an explicit acceptance test (§9).

---

## 7. Persona configuration

A single `persona.json` (loaded once by `TutorLoop`):

```json
{
  "name": "Wini",
  "identity": "a friendly Class 10 Maths buddy",
  "age_appropriate_self": "I'm Wini, a robot who loves helping you with maths!",
  "capabilities": ["explain maths step by step", "give hints", "practice problems", "show figures"],
  "cannot": ["play music", "browse the internet", "do other subjects (for now)"],
  "canned": {
    "name": "I'm Wini! What should I call you?",
    "how_are_you": "I'm great and excited to do some maths with you! How are you feeling today?",
    "nonsense": "Oops, I didn't catch that. Can you say it again?",
    "safety": "I'm really glad you told me. That sounds important — please talk to a grown-up you trust, like a parent or teacher, right now. I'm here with you."
  }
}
```

Benefits: "what is your name" is answered correctly and identically on every surface
with zero model call; SAFETY/NONSENSE replies are fixed and reviewable.

---

## 8. Dataset and model build

### 8.1 Dataset

- New file `dataset/intent_router_dataset.json` — **its own label space**, NOT mixed
  into the canonical `exemplar_dataset_10000_fixed.json` (different task; honors the
  "new capability = new file, originals read-only" rule in CLAUDE.md).
- **Seed sources, in priority order:**
  1. Real kid-test transcripts (highest-value signal — captures actual phrasing).
  2. Qwen-generated, balanced rows per intent (local model only, per CLAUDE.md).
  3. The scenario examples in §2 as starter/anchor rows.
- Hold out a stratified test split; SAFETY gets an oversampled adversarial probe set.

### 8.2 Build script

`intent_router/build_router.py` (parallels
[cognitive_classifier/build_bank.py](cognitive_classifier/build_bank.py)):
embed exemplars with the shared MiniLM, fit the single-label head, calibrate the
abstain threshold, write artifacts to `models/intent_router/`.

> Windows gotcha (CLAUDE.md): keep sklearn sequential —
> `OneVsRestClassifier(n_jobs=-1)` crashes via joblib loky. Single-label logreg
> avoids OvR entirely.

---

## 9. Evaluation & acceptance criteria

| Metric | Target | Rationale |
|---|---|---|
| **SAFETY recall** | ~100% | A missed safety case is unacceptable; a false trigger is cheap. Accept low precision here. |
| LEARNING→non-LEARNING mis-route | minimal | Mis-routing a real maths turn into SOCIAL blocks teaching. |
| non-LEARNING→LEARNING mis-route | minimal | This is the *current* bug; the whole point is to drive it down. |
| Overall macro-F1 (non-safety) | report, set bar after first build | Honest baseline; refine with real data. |
| **Regression: LEARNING no-op** | exact match | `turn()` output identical to pre-router behavior on a fixed transcript of learning turns. |

Eval harness parallels `cognitive_analyzer/test_analyzer.py` and writes an
`eval_report.md` under `models/intent_router/`.

---

## 10. Documentation lockstep (on build, per CLAUDE.md)

This change touches behavior + schema + dataset + model, so on implementation it
propagates to all four lockstep docs **in the same work session**:

1. `learner_cognitive_state_architecture.md` — the intent taxonomy, the
   "only LEARNING moves state" contract, the SAFETY guarantee, multi-intent rules.
2. `complete_architecture_build_plan.md` — a new **Part 11** with measured results.
3. `model_dataset_architecture_report.md` — the intent dataset + intent-head numbers.
4. `RAG_upgrade_plan.md` — a documented **exception** to the "compose only from
   manifest" invariant for non-learning intents (their replies are persona-grounded,
   not store-grounded).
5. `rag_memory.md` — work-log entry; `WINI_ARCHITECTURE.md` — external-shape update
   (the front door changes the system's outward behavior).

---

## 11. Rollout plan (phased)

**Phase 1 — model-free front door (highest ROI, smallest risk).**
`persona.json` + Stage A deterministic gates + `_handle_nonlearning` + the
state-protection wiring. This alone removes the worst, most embarrassing failures
(social, safety, nonsense) with **no new model and no dataset**.

**Phase 2 — learned head.**
Build `intent_router_dataset.json` from transcripts, train the Stage B head, calibrate
the abstain threshold, run the eval harness.

**Phase 3 — lockstep propagation.**
Update the four docs + work log with measured results.

**Phase 4 — surface rollout.**
Verify the new result-dict shape is consumed unchanged by the voice rig and the
Jetson layer; port as in the prior Jetson port (memory: jetson-port-2026-06-22).

---

## 12. Risks & open questions

**Risks**
- **Safety recall is make-or-break.** Keep it deterministic, over-trigger, and review
  the lexicon with a human. Never let the learned head assign or override SAFETY.
- **Starving teaching.** Abstain must default to LEARNING, and the regression guard
  (§9) must prove learning turns are byte-for-byte unchanged.
- **CUE_NAMES rebuild trap.** Keep the intent head a separate artifact; do not touch
  the cognitive logreg widths.
- **Latency.** Stage A is regex (negligible). Stage B reuses the loaded embedder, so
  adds one small matmul — acceptable, but measure on the Jetson (8 GB OOM history;
  memory: jetson-oom-lean-runs).

**Open questions for review**
1. Should OFF_DOMAIN_ACADEMIC ever give a *real* one-line answer (e.g. capital of
   France) before steering back, or always redirect? (Engagement vs. scope creep.)
2. SAFETY alerting: where does the supervisor see it — log only, or a UI/Jetson
   signal? Needs the deployment owner's call.
3. Does SESSION_CONTROL need to actually pause/end the session (state machine), or is
   a verbal response enough for v1?
4. Spoken embodiment ("wave"): route to META in v1, or wire to the Jetson actuation
   layer (constrained by the ear-actuation defect)?

---

## 13. File map (new artifacts, when built)

```
intent_router/
  __init__.py
  gates.py            # Stage A deterministic gates (safety/nonsense/social)
  router.py           # Stage B learned head + RouteResult + route()
  build_router.py     # dataset -> models/intent_router/ artifacts
persona.json          # single source of identity + canned responses
dataset/
  intent_router_dataset.json
models/intent_router/
  bank / head artifacts
  eval_report.md
tutor_loop.py         # +step 0, +_handle_nonlearning, +_log_safety  (edits)
```

No existing dataset or model artifact is modified. The cognitive classifier, concept
resolver, and policy shadow are untouched.
