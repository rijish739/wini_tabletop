# Wini Tutor — Layered Architecture (NORMATIVE)

**Status: normative**
**Date: 2026-08-27**
**Supersedes:** `docs/archive/WINI_LAYERED_ARCHITECTURE.md` (reasoned the layer model; archived as the derivation record),
`docs/archive/FINAL_WINI_PEDAGOGICAL_ARCHITECTURE_PLAN.md` (reviewed a different repository; archived).

---

## What this document is, and what it is not

This document owns the **layer boundaries, per-layer responsibilities, the contracts between
them, and the system-wide invariants**. It is the single place you read to know what a layer
is allowed to do and what it must never do.

It does **not** absorb:

| Topic | Authoritative source |
|---|---|
| Safety taxonomy, detection architecture, evaluation floors | `docs/architecture/SAFETY_ROUTE_TAXONOMY.md` |
| Personal-data detection, redaction, sinks | `docs/architecture/PERSONAL_DATA_CONTRACT.md` |
| Domain vocabulary (Utterance, Feature Module, Turn, …) | `CONTEXT.md` |
| STT uncertainty contract, Authorization verdict | `.scratch/…/issues/11-decide-the-stt-uncertainty-contract.md` |
| Input-layer implementation spec | `.scratch/…/issues/16-write-the-implementation-spec.md` |

**Precedence rule.** When two documents disagree: `CONTEXT.md` vocabulary beats this document;
this document beats dated measurement records. Among measurement records, the most recent
measured date wins.

**Numbers are not kept here.** A count of turns, graded outcomes, mastery values, or recall
scores belongs in a dated measurement record, not in a document whose first job is to stay
true indefinitely. Citing a stale measurement as a current fact is how the prior lockstep set
rotted.

---

## §1 Architectural Principles

Binding across all layers. Every layer specification below is checked against them.

| # | Principle |
|---|---|
| **P1** | Instrument before you model. Evidence-collection infrastructure precedes learner modelling. |
| **P2** | Observations, hypotheses, and evidence are different kinds of thing. Enforced by contract at every layer boundary. Only L3 may produce evidence. |
| **P3** | No unscored assessment questions. If Wini poses a question it must be able to grade it, or it must not pose it. |
| **P4** | No durable state without an evidence event. L3 is the sole writer of the evidence ledger; L4 is a pure projection. |
| **P5** | An item outcome licenses only claims that item supports. Wrong on an item ≠ holds a specific belief. |
| **P6** | Uncertainty is a first-class output, not a failure. `unknown`, `insufficient_evidence`, `candidate` are valid terminal values. |
| **P7** | Determinism where correctness matters; models where language matters. Safety routing, arming, grading floor, validation, policy = deterministic. Perception, generation, item text = model. |
| **P8** | Extend working mechanisms; do not replace them. |
| **P9** | Conceptual separation ≠ software separation ≠ deployment separation. |
| **P10** | Do not invent learner signals that cannot be observed. |
| **P11** | Latency is a pedagogical constraint. Two model calls stay on the critical path. |
| **P12** | Every durable claim must be traceable to the evidence that justifies it. |

---

## §2 Layer Map

| ID | Name | CONTEXT.md feature | Status | On critical path? | Model calls |
|---|---|---|---|---|---|
| **L0** | Transport & I/O | — | exists | yes | Cloud STT, Cloud TTS |
| **L1a** | Utterance Intake | Utterance Intake | extend | yes | **none** (model-free by invariant) |
| **L1b** | Interaction Control | Interaction Control | extend | yes | **none** (routes from Intake + verdicts) |
| **L1c** | Child Safety | — | new package | parallel to L2 | **1** dedicated Gemini call |
| **L1d** | Personal Data | — | new package | parallel to L2 | **1** dedicated Gemini call |
| **L2** | Perception | Perception | exists | yes | **1** structured Gemini call (memoized) |
| **L3** | Evidence & Grading | Assessment and Evidence | partial → new module | grading parallel | ≤1 rubric grader |
| **L4** | Learner Context | — | partial | no | none |
| **L5** | Pedagogical Policy | Pedagogy | partial | no | none |
| **L6** | Teaching Resources | Retrieval | exists | yes (local) | none |
| **L7** | Item Economy | Assessment and Evidence | absent → new module | no (cached) | 2 cached |
| **L8** | Teaching Plan & Arming | Response Planning | partial | no | none |
| **L9** | Realization | Response Generation | exists | yes | **1** streamed generation + ≤1 board |
| **X1** | Identity, Persistence & Safety Store | — | partial | no | none |
| **X2** | Observability & Reporting | — | partial | no | none |

**Critical-path model calls: 2** (perception, generation). Child Safety and Personal Data run in
parallel. Grading runs in parallel. Item verification is cached and off-path. **This architecture
does not extend TTFA.**

**Three kinds of boundary (P9).** Conceptual (naming and data shape only) · Software (module
with interface and test suite) · Deployment (separate process or network call). These must not
be conflated. Zero new deployment boundaries in this architecture — one Cloud Run process, one
thin client, existing external services.

---

## §3 Layer-by-Layer Specification

Each layer: **purpose · inputs · outputs · model usage · must not do**.

---

### L0 — Transport & I/O

**Purpose.** Terminate the network/audio boundary. Produce a transcript with reliability
metadata. Stream speech back. Serialize turns. Generate a `turn_id`.

**Inputs.** HTTP POST, PCM audio + sample rate, API key, mode header, device profile.

**Outputs.** `Utterance` (raw text + STT evidence + `turn_id`), streamed TTS, `turn_meta`.

**Model usage.** Cloud STT, Cloud TTS. **No LLM.**

**Must not do.** Interpret meaning · touch learner cognitive state · decide pedagogy · grade ·
omit the `turn_id` from what it passes down.

*The `turn_id` is what makes L3's idempotency contract hold against client retries. It is
generated here and carried to every downstream consumer.*

---

### L1a — Utterance Intake

**Purpose.** Turn one raw `Utterance` into a typed, model-free `UtteranceObservation`. It
observes; it decides nothing. Pure of session state (rule: Intake may not read session context
— ticket 03).

**Inputs.** `Utterance` (raw text + STT evidence).

**Outputs.** `UtteranceObservation` — five required readings:
1. `legibility: LegibilityReading` — normalized text + NONSENSE judgment + empty/illegibility flag
2. `reference: ReferenceReading` — anaphors, same-problem followup signal
3. `attempt: AttemptReading` — answer-attempt / non-attempt signal
4. `authorization: AuthorizationReading` — derived from STT evidence; see ticket 11
5. `safety: SafetySignals` — **lexicon-only**, axis + `caregiver_implicated` flag; see `SAFETY_ROUTE_TAXONOMY.md` §8

**Model usage.** **None, by invariant.** Intake runs before any model call. `SafetySignals`
carries `source=LEXICON`; the `MODEL` source is **unconstructable** inside Intake.

**Must not do.** Call any model · read session state · derive intent · assign a concept ·
emit a `SafetyVerdict` (that requires the child_safety verdict; Intake emits only the lexicon
reading).

---

### L1b — Interaction Control

**Purpose.** Decide whether this turn enters the learning pipeline, and which route it takes.
Routes: `LEARNING | SAFETY | NONSENSE | SOCIAL | OFF_DOMAIN | CLARIFY`.

**Inputs.** `UtteranceObservation` (from L1a), `SafetyVerdict` (composed from L1c + L1a +
perception's `safety` bit), `PersonalDataVerdict` (from L1d), `PerceptionObservation` (from
L2, where available), session mode.

**Outputs.** Route decision + `InteractionControlResult`. On `SAFETY`: runs the scripted
safety response, writes the case record, never learner state. On `LEARNING`: passes the turn
downstream.

**Model usage.** None. Interaction Control composes verdicts from model calls that ran
elsewhere; it does not make them.

**Must not do.** Write learner cognitive state on a non-LEARNING route · override a safety
verdict · suppress a `SafetyVerdict` finding · call a model.

*The composition of the `SafetyVerdict` happens here — exactly one site, per
`SAFETY_ROUTE_TAXONOMY.md` §6.7. The composition rule is monotone: nothing may ever remove a
finding.*

---

### L1c — Child Safety (parallel to L2)

**Purpose.** Produce the primary child-safety verdict. The model is the primary detector;
the Intake lexicon is the outage net. See `SAFETY_ROUTE_TAXONOMY.md` §1 for the full
architecture, §7 for the call spec, §8 for degraded mode.

**Inputs.** `normalized_text`, one preceding exchange (`session["context"][-2:]`), prior
safety summary.

**Outputs.** Structured verdict: classes (`frozenset[SafetyClass]`), `imminence_cue`,
`caregiver_implicated`. **Never** `severity` — severity is derived in L1b's composition step.

**Model usage.** One dedicated Gemini 2.5 Flash call, `temperature=0`, `thinking_budget=0`,
response schema. Hard wall-clock 5s + one retry inside the envelope. Memoized on
`utterance_id`. Its own `cloud_run_service/child_safety/` package, context cache, and eval
harness — never fused with the Perception call.

**Must not do.** Derive `severity` · clear a prior finding · run conditionally on a lexicon
trip · share a prompt or schema with Perception.

*Evaluation: blind per-class corpora, never against the lexicon; no aggregate recall number
anywhere. See `SAFETY_ROUTE_TAXONOMY.md` §10.*

---

### L1d — Personal Data (parallel to L2)

**Purpose.** Detect personal identifiers in the normalized utterance and produce a verdict
the redactor uses to build `RedactedText`. See `docs/architecture/PERSONAL_DATA_CONTRACT.md`
for the full contract.

**Inputs.** `normalized_text`, one preceding exchange (for split-disclosure detection).

**Outputs.** `PersonalDataVerdict` — per-finding `IdentifierClass` + verbatim substring to
remove. The verdict object is identifier-bearing; it is consumed and dropped; only class labels
survive it.

**Model usage.** One dedicated Gemini 2.5 Flash call per `PERSONAL_DATA_CONTRACT.md` §13.
**No deterministic component, no regex fallback** — the reason is measured: generic pattern
detectors score F1 ≈ 0.38 on maths dialogue by eating the maths.

**Must not do.** Run in Utterance Intake (post-Intake timing is forced by the normalization
dependency) · set `safety_alert` · set `safety_class` · pause the lesson · produce a
`SafetyClass` of any kind.

*Personal data is **off the safety axis entirely**. A disclosure is an annotation on a
normal turn, not an escalation. See `PERSONAL_DATA_CONTRACT.md` §1.*

---

### L2 — Perception

**Purpose.** Convert one admitted utterance into typed, turn-scoped **observations**. Nothing
more. The output is observations, not decisions.

**Inputs.** `UtteranceObservation.legibility.normalized_text`, conversation context, current
concept, pending-check context, concept catalog (via Vertex context cache).

**Outputs.** `PerceptionObservation` — `intent`, `concept_candidate`, `concept_confidence`,
`answer_attempt`, `signals[]`, `safety` (boolean add-only net), `uncertain` flag; plus
deterministic cues from the cue battery.

**Model usage.** One structured Gemini 2.5 Flash call, `temperature=0`, response-schema
constrained, served from a Vertex context cache. Memoized on **`utterance_id`** (not
normalized text — ticket 02). Client construction is memoized per process; never per turn
(dominant cold-start cost, measured ~4–9s).

**Two promoted rules from ticket 13 (binding, not advisory):**

1. **Never softmax, always independent per-label thresholds.** Signal scores are not a
   probability distribution over mutually exclusive outcomes. Applying softmax mis-normalises
   them and systematically suppresses co-occurring signals. Each signal fires or does not fire
   against its own threshold, calibrated on the frozen TEST split.

2. **Do not strip stop words.** Stop-word removal discards the distinction between *"I do
   like math"* and *"I do not like math"*, which fired `transfer_attempt = 0.8` on both in
   the HeuristicSemanticClassifier that is now deleted. Perception's input is the full
   normalized utterance; do not pre-strip.

**Must not do.** Move mastery · confirm a misconception · create durable learner traits ·
grade an answer · choose a teaching action · emit a `CRITICAL` or `ELEVATED` safety verdict
(it may only contribute the `safety` boolean; the verdict is composed in L1b) ·
strip stop words · softmax signal scores.

**Fallback.** On model timeout or error, `_fallback` must emit `uncertain=True` and L8 must
suppress arming on such turns. The fallback must not fabricate instructional certainty.

**Open evaluation question (compound-utterance chunking).** A turn that both explains
something *and* asks a question currently yields one signal set. Whether splitting it would
produce better grounded signals is an open empirical question — not decided, not blocked.

---

### L3 — Evidence & Grading

**Purpose.** The sole producer of durable truth. Convert an answered question into a
verified, provenance-carrying, idempotent `OutcomeEvent` and append it to the evidence ledger.
Nothing else in the system may write learning evidence.

**Inputs.** Armed `pending_check` (item, key, purpose, rubric), learner reply,
`answer_attempt`/`non_attempt` status (from L1a), `stt_confidence`, `turn_id`, assistance
counters.

**Outputs.** `OutcomeEvent | None`; grading verdict for the assistance ladder.

**Model usage.** ≤1 rubric grader call, only when the deterministic floor defers. Runs in
parallel with Perception.

**Invariants.** See §4. The key ones:
- E1: No unscored assessment questions — enforced at L8 arming.
- E2: No mastery mutation without an evidence event — `record_outcome` is the sole writer.
- E3: Idempotency — `idempotency_key(turn_id, item_id, normalize(reply))`; the `turn_id`
  distinguishes a client retry from a repeated answer.
- E6: An item outcome licenses only what the item supports — `consistent_with_misconception`
  gates hypothesis promotion.
- E7: A non-attempt never grades.
- E10: A binary item may raise but never confirm a hypothesis.
- E12: A leaked answer voids the check; produces no evidence.

**Must not do.** Choose the next action · retrieve content · generate language ·
infer a belief the item does not support (P5) · write twice for one `turn_id` + reply.

---

### L4 — Learner Context (derived read model)

**Purpose.** Answer *"what do we believe about this learner, and why?"* as a pure projection
of the evidence ledger plus session state. Read-only with respect to evidence.

**Inputs.** Evidence ledger, session, concept graph, current concept.

**Outputs.** `LearnerContext` — `mastery`, `mastery_status` (not `mastery_measured`; extends
it to `insufficient_evidence`), `active_hypotheses`, `barrier`, `barrier_confidence`,
`assistance_state`, `intervention_history`, `reps_missing`, `transfer_readiness`, `cold_recall`,
`zpd_band`.

**Four partitions (P2 in practice).** Observations (TTL) · Hypotheses (decay or reject) ·
Evidence (immutable) · Confirmed/derived (durable, projection-only).

**Misconception tiers.** `candidate` (first failure, or a binary-item failure) →
`supported` (two convergent failures, or one high-confidence failure on a non-binary item) →
`weakening`/`resolved`/`recurring`. The corrective phase and `misconception_confirmed` gate on
`supported` only. A first correct probe must not produce an `active` record.

**Model usage.** None.

**Must not do.** Write evidence · call a model · choose an action ·
report a number it cannot justify (use `insufficient_evidence`) ·
surface degenerate global EMAs as measurements (curiosity/engagement values from EMA over
message type frequency are not observations of the child — gate them on `n_observations`).

---

### L5 — Pedagogical Policy

**Purpose.** Decide one thing: given what we believe and what happened, what should Wini do
next, with how much help, and to gather what evidence?

**Inputs.** `LearnerContext`, `PerceptionObservation` + cues, mode state, last outcome,
`intervention_history`.

**Outputs.** `PolicyDecision` — action, assistance level, assessment purpose, delivery style,
`intervention_history` update.

**Model usage.** None. A policy-shadow model may be logged but must never choose.

**Failed-strategy memory.** `intervention_history[concept_id]` tracks what was tried. On
repeated confusion, escalate rather than repeat: 1st → `EXPLAIN_SIMPLER`; 2nd →
`EXPLAIN_DIFFERENT_ROUTE + ELICIT_ATTEMPT`; 3rd → `REPRESENTATION_TRANSLATION`. Escalation
is not withholding — Wini must never refuse an explanation to a child who asks for one.

**Must not do.** Call a model · retrieve content · write the words · move mastery ·
pose a question without a purpose and a verified item.

---

### L6 — Teaching Resources (Retrieval)

**Purpose.** Select pedagogically eligible and relevant content objects that realize the
decision.

**Inputs.** `PolicyDecision`, `LearnerContext`, concept ids, served set.

**Outputs.** Evidence manifest (typed blocks with provenance and reasons).

**Structure.** Eligibility filter (hard pre-filter: may this object legally appear right
now?) → rank (semantic × role fit × difficulty fit × novelty × representation fit × HOPE nudge)
→ abstention floor (0.28, unchanged — a genuinely good invariant).

**Model usage.** Local MiniLM embeddings (in-container). No LLM.

**Must not do.** Choose the teaching strategy · decide assistance level · generate items ·
surface a `before_attempt` object while a probe is armed · serve below the abstention floor
without logging why.

---

### L7 — Item Economy

**Purpose.** Guarantee a supply of valid, gradeable, provenance-carrying assessment items for
every assessment purpose.

**Inputs.** `assessment_purpose`, concept id, problem schema, learner's `item_history`,
difficulty target.

**Outputs.** `VerifiedItem | None`. `None` is a legitimate and important answer —
it triggers a graceful downgrade, not an error.

**Verification pipeline.** Bank lookup → authored item → generate from problem schema
(`temperature=0`) → deterministic verification (sympy / `math_grade`) or independent
model re-solve (`temperature=0`, solver never sees the proposed key) → cache on accept →
reject on second failure and return `None`.

**Model usage.** Two model calls, both cached: generator + independent verifier. Off the
critical path. Bank hits are free.

**An unverified item is never served.** `item_verified=False` ⇒ the beat is downgraded and
no question is posed.

**Must not do.** Serve an unverified key · decide whether to assess · generate at
`temperature > 0` · write learner state.

---

### L8 — Teaching Plan & Arming

**Purpose.** Turn a `PolicyDecision` + content + item into a compact executable plan, and be
the **single choke point** where a question becomes gradeable.

**Inputs.** `PolicyDecision`, evidence manifest, `VerifiedItem | None`, device profile,
`LearnerContext`.

**Outputs.** `TeachingScript` (1–3 beats, hooks, constraints), `VisualIntent`,
`session.pending_check` (when armed).

**Arming.** `arm_from_script()` is the **only writer of `session["pending_check"]`** in the
system. It will not arm unless `hook.item_verified` is `True` and `hook.expected_answer` is
set. An unverified item causes the beat to be downgraded to non-assessing; the question is not
posed.

**On a fallback turn** (`PerceptionObservation.uncertain=True`), arming is suppressed.

**Model usage.** None.

**Must not do.** Change the macro action (L5 owns it) · retrieve content · generate language ·
grade · arm an unverified item · arm on a fallback turn.

---

### L9 — Realization (Generation · Visual · Validation)

**Purpose.** Turn the plan into words and pixels without redesigning the lesson, and prevent
an unconstrained generation from corrupting evidence.

**Inputs.** `TeachingScript`, evidence manifest, conversation continuity, assistance/reveal
constraints, budgets, grounding mode.

**Outputs.** Streamed answer text, board/scene artifacts, `realization_flags`.

**Model usage.** One streamed Gemini 2.5 Flash generation call (critical path) + ≤1 board
authoring call (post-speech). `thinking_budget=0`.

**Validation classes.**
- Class A (verbatim, pre-stream): test and misconception-probe questions are served verbatim
  from the armed item; never paraphrased.
- Class B (post-hoc, full answer): expected-answer leak check + numeric allowlist vs manifest.
  On failure: **void `session["pending_check"]`; never retract audio**. Voiding the check
  prevents an invalid evidence event; the utterance is physics and cannot be recalled.
- Class C (compile-time): board value-grounding belt (exists, keep).

**Board Buddy is a compiler target, not a planner.** The board is authored from the generated
answer; it may not contain a second pedagogical plan. The orchestrator (`WINI_BB_ORCHESTRATOR`,
default off) stays off.

**Must not do.** Introduce pedagogical claims not in the plan · reveal beyond assistance level ·
emit numbers absent from manifest + history · author a second lesson plan inside Board Buddy ·
retract audio on a validation failure.

---

### X1 — Identity, Persistence & Safety Store (cross-cutting)

**Purpose.** Know whose learner model this is; keep session, durable, and safety data in
separate lifecycles with separate access.

**Three-way document split.** `profile` (durable evidence + derived), `session` (TTL),
`safety` (restricted access-controlled collection — never written beside `evidence_ledger`).

**Must not do.** Store safety events in the learning log · retain raw child utterances
indefinitely · infer identity from content.

*Verify the Firestore 1 MiB document limit before shipping the evidence ledger; move to a
subcollection if exceeded.*

**Parent-facing reporting.** A parent may be shown only what evidence supports. A number with
`mastery_status=insufficient_evidence` is displayed as "not enough practice yet to say", never
as a percentage. Degenerate EMAs (global curiosity, engagement) are **not shown** until they
are gated on a meaningful observation count.

---

### X2 — Observability & Reporting (cross-cutting)

**Purpose.** Make every decision traceable from logs and state alone.

**The decision-side logging is already good** — `ranking_trace`, `action_reason`,
`shadow_suggestion`, `latency_ms`, manifest. The gap is outcomes: the evidence funnel
(questions posed → attempts received → grades issued → ledger rows written) must be computable
from `learning_log.jsonl` alone.

**Must not do.** Promote engagement/session length/message count to a success metric ·
retain raw utterances past the retention window · log a safety class beside a learning-log
row.

---

## §4 Evidence Invariants

| # | Invariant | Enforced by |
|---|---|---|
| **E1** | No unscored assessment questions | L8 `arm_from_script` — sole path from plan to question |
| **E2** | No mastery mutation without an evidence event | L3 `record_outcome` — sole writer |
| **E3** | Every state-changing outcome is idempotent | `idempotency_key(turn_id, item_id, normalize(reply))` |
| **E4** | A generated key must be verified before it can affect learner state | L7; `item_verified=False` ⇒ never armed |
| **E5** | Low-confidence STT or grading must not silently produce durable change | L1b `Authorization`; L3 confidence gating |
| **E6** | An item outcome licenses only what that item supports | L3 `consistent_with_misconception` |
| **E7** | A non-attempt never grades | L1a `attempt: AttemptReading` |
| **E8** | Self-report never moves mastery | L3 refuses acks |
| **E9** | Assisted correctness ≠ independent mastery | `assistance_consumed` on every ledger row |
| **E10** | A binary item may raise but never confirm a hypothesis | L3 promotion rule |
| **E11** | Ledger replay reproduces derived state exactly | L4 is a pure projection |
| **E12** | A leaked answer produces no evidence | L9 voids the pending check |

---

## §5 Contracts Between Layers

Each contract lists what the downstream layer may assume and what the upstream layer must
never do.

### L1a → L1b · Utterance Intake → Interaction Control

```
IN:   Utterance (raw text + STT evidence + turn_id)
OUT:  UtteranceObservation{legibility, reference, attempt, authorization, safety}
MUST NOT: call a model · read session state · derive intent · emit SafetyVerdict
```

### L1c → L1b · Child Safety → Interaction Control

```
IN:   normalized_text, one preceding exchange, prior safety summary
OUT:  structured verdict: frozenset[SafetyClass], imminence_cue, caregiver_implicated
MUST NOT: set severity · clear a prior finding · run conditionally · share prompt with Perception
```

### L1d → L9 (via redactor) · Personal Data → generation prompt

```
IN:   normalized_text, one preceding exchange
OUT:  PersonalDataVerdict{utterance_id, status, findings}
MUST NOT: set safety_alert · set SafetyClass · pause the lesson · be awaited before the case record is written
```

### L2 → L3/L4 · Perception

```
IN:   UtteranceObservation.legibility.normalized_text, conversation context,
      active concept, pending-check context
OUT:  PerceptionObservation{intent, concept_candidate, concept_confidence,
                            answer_attempt, signals[], safety (bool), uncertain}
      + deterministic cues
MUST NOT: directly change mastery · confirm misconceptions · create durable traits
          · grade an answer · choose a teaching action
          · softmax signal scores · strip stop words
```

### L3 → L4 · Evidence

```
IN:   armed hook, reply, attempt status, stt_confidence, turn_id, assistance counters
OUT:  OutcomeEvent | None
MUST NOT: choose the next action · retrieve content · generate language
          · infer a belief the item does not support (P5)
          · write twice for one turn_id + reply
INVARIANT: sole writer of evidence in the system
```

### L4 → L5 · Learner Context

```
IN:   evidence ledger, session, graph
OUT:  LearnerContext{mastery, mastery_status, active_hypotheses,
                     barrier, barrier_confidence, assistance_state,
                     intervention_history, reps_missing, transfer_readiness,
                     cold_recall, zpd_band}
MUST NOT: write evidence · call a model · choose an action
          · report a number it cannot justify (use insufficient_evidence)
```

### L5 → L6/L7/L8 · Policy

```
IN:   LearnerContext, PerceptionObservation + cues, mode state, last outcome
OUT:  PolicyDecision
MUST NOT: call a model · retrieve content · write the words
          · move mastery · pose a question without a purpose AND a verified item
```

### L6 → L8 · Retrieval

```
IN:   PolicyDecision, LearnerContext, concept ids, served set
OUT:  evidence manifest[{id, type, reason, text, provenance}]
MUST NOT: choose the strategy · decide assistance level · generate items
          · surface a before_attempt object while a probe is armed
          · serve below the abstention floor (0.28)
```

### L7 → L8 · Item Economy

```
IN:   assessment_purpose, concept, schema, item_history, difficulty target
OUT:  VerifiedItem | None   ← None is a valid, expected answer
MUST NOT: serve an unverified key · decide whether to assess
          · generate at temperature > 0 · write learner state
```

### L8 → L9 · Teaching Plan

```
IN:   PolicyDecision, manifest, VerifiedItem|None, device profile
OUT:  TeachingScript{beats[1..3], hooks, realization_constraints}, VisualIntent
SIDE EFFECT: arms session.pending_check ← SOLE WRITER
MUST NOT: change the macro action · retrieve · generate · grade
          · arm an unverified item · arm on an uncertain fallback turn
```

### L9 → learner / L3 · Realization

```
IN:   TeachingScript, manifest, continuity, constraints, budgets
OUT:  streamed answer, board artifacts, realization_flags
MUST NOT: introduce pedagogical claims not in the plan
          · reveal beyond assistance_level
          · emit numbers absent from manifest + history
          · author a second lesson plan inside Board Buddy
ON FAILURE: void the pending check; never retract audio
```

---

## §6 Reconciliation with Resolved Tickets

Key places where resolved tickets have overturned what `WINI_LAYERED_ARCHITECTURE.md` stated
as mandates. The layer specs above already reflect the resolution; this table records the
specific inversions so they are not re-derived.

| Overturned statement | What replaced it | Ticket |
|---|---|---|
| "Model usage: NONE by mandate" at L1 | A dedicated Gemini call in `child_safety/` is the **primary** safety detector; the lexicon is the outage net | 07 |
| "gate recall measured directly" | Blind per-class corpora; **no aggregate safety number anywhere** | 07 |
| STT floor "start 0.6, calibrate per DEC-044" | `DEC-044` never existed; `latest_short` confidence is not a true confidence score; the floor is an `Authorization` verdict computed from three signals (ticket 11) | 11 |
| PII as a safety risk tier | Personal data is **off the safety axis entirely**; it is an annotation, not an escalation | 07 + 09 |
| No Utterance Intake layer; Admission reads `transcript` + `stt_confidence` directly | Utterance Intake (L1a) is a distinct model-free capability producing `UtteranceObservation` | 01, 02, 03 |
| No `UtteranceObservation` input to Perception | L2 receives `UtteranceObservation.legibility.normalized_text` as its primary input | 03 |
| No `Feature Module` / `TurnPhase` / `ModuleOutcome` vocabulary | These terms are in `CONTEXT.md` and are current | `CONTEXT.md` |
| `HeuristicSemanticClassifier` / `SemanticClassifier` Protocol seam kept as offline fallback | Seam deleted entire (ticket 13); offline fallback is the lexicon outage net; a local classifier would back Perception, not Intake | 13 |
| `PrivacyReading` as a required slot on `UtteranceObservation` | Deleted — Intake is model-free and cannot fill it; personal data detection runs post-Intake | 09 |

---

## §7 Open Evaluation Questions

These are not decisions — they are empirically open questions the architecture acknowledges
rather than silently closing.

**Compound-utterance chunking.** A turn that both explains something and asks a question
currently yields one signal set from Perception. Whether splitting such turns would produce
better-grounded signals is an open empirical question. The architecture does not mandate
splitting; it notes the question exists.

**Assistance-ladder rung ordering.** Escalation (do not repeat a failed strategy) is
justified by the intervention history evidence. Which rung ordering maximizes learning is a
hypothesis (DEC-041) with supporting evidence from classroom/screen contexts; the voice-only
equivalent is not yet tested.

---

## §8 Other files in `docs/architecture/`

These live alongside this document. They are **not** normative architecture; the one-line
status on each says what it is.

| File | Status |
|---|---|
| `SAFETY_ROUTE_TAXONOMY.md` | normative — safety detection architecture and evaluation contract |
| `PERSONAL_DATA_CONTRACT.md` | normative — personal-data detection, redaction, and sinks |
| `AUDIO_END_TO_END_FLOW.md` | explainer — the only end-to-end walk of the audio path |
| `CODEBASE_ARCHITECTURE_AND_COUPLING_REPORT.md` | research (dated 2026-08-25; superseded by ticket 13) |
| `INPUT_LAYER_SEMANTIC_INTENT_RESEARCH.md` | research (dated; decisions resolved — tickets 07, 13) |
| `MATH_AWARE_STT_NORMALIZATION_RESEARCH.md` | research (dated; feeds ticket 11 / ticket 14) |
| `PERSONAL_DATA_DETECTION_RESEARCH.md` | research (dated; feeds ticket 09) |
| `CHILD_SAFETY_RISK_TAXONOMIES_RESEARCH.md` | research (dated; feeds ticket 07) |

---

## §9 What this document does not cover (full table)

The following are decided and documented elsewhere; this document cites them and never
restates them.

| Topic | Where |
|---|---|
| Safety class definitions, imminence, severity, evaluation floors, degraded mode, case record | `docs/architecture/SAFETY_ROUTE_TAXONOMY.md` |
| Personal data class definitions, redaction, sinks, retention | `docs/architecture/PERSONAL_DATA_CONTRACT.md` |
| STT uncertainty: Authorization, N-best, confirmation UI | `.scratch/…/issues/11-decide-the-stt-uncertainty-contract.md` |
| Concept coreference, INHERIT_CURRENT_CONCEPT, concept resolver | `.scratch/…/issues/12-decide-where-coreference-confidence-lives.md` and `cloud_run_service/concept_resolver/CONCEPT_RESOLUTION_HANDOVER.md` |
| Input-layer implementation spec (types, module layout, deletion manifest) | `.scratch/…/issues/16-write-the-implementation-spec.md` |
| No-regression verification gate | `.scratch/…/issues/15-decide-the-no-regression-verification-gate.md` |
| Test contract and corpora | `.scratch/…/issues/14-define-the-test-contract-and-corpora.md` |
| Store build/verify results | `docs/archive/RAG_upgrade_plan.md` (dated measurement record) |
| Dataset and model numbers | `docs/archive/model_dataset_architecture_report.md` (dated measurement record) |
| Execution status of Parts 1–11 | `docs/archive/complete_architecture_build_plan.md` (dated measurement record) |
| Append-style work log | `docs/archive/rag_memory.md` |
