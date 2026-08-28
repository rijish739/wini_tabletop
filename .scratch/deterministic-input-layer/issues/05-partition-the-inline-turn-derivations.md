# Partition the inline turn-body derivations

Status: resolved
Type: grilling
Blocked by: 03

## Question

`cloud_run_service/tutor_loop.py:2266-2330` derives ten booleans from the raw utterance
inside `_legacy_turn`. This is the single largest reason the answer to "is the input layer
out of `tutor_loop.py`" is **no**. Which of the ten are Input Layer output, and which are a
consumer's reading of input plus session state?

The ten, with what each actually depends on:

| Name | Line | Depends on |
|---|---|---|
| `clarification` | 2273 | `is_clarification_request(text)` OR a Gemini signal |
| `wants_visual` | 2278 | cue OR (`clarification` AND Gemini representation signals) |
| `wants_why` | 2283 | `is_purpose_question(text)` — pure text |
| `wants_animation` | 2295 | `is_animation_request(text)` — pure text |
| `wants_real_life` | 2296 | `is_real_life_request(text)` — pure text |
| `answer_try` | 2302 | interaction-control flag OR `route.answer_attempt` OR Gemini signal OR cue |
| `student_problem` | 2313 | `problem_cue` (deterministic) AND `answer_try` |
| `wants_hint` | 2315 | state deltas / Gemini signals |
| `fresh_request` | 2317 | Gemini signal set only |
| `non_attempt` | 2327 | `answer_try` + `is_pure_ack` + `clarification` + `is_question` + `fresh_request` + directive |

The pattern: **`wants_why` / `wants_animation` / `wants_real_life` are pure text facts**;
`fresh_request` and `wants_hint` are pure *semantic-layer* facts (out of boundary);
`clarification`, `wants_visual`, `answer_try`, `student_problem`, `non_attempt` are **fusions**
of deterministic cue, Gemini signal, and session state.

Decisions to close:

- Does the Input Layer emit only the deterministic half of each fusion, leaving the OR to a
  consumer? That keeps the layer model-free and testable without Vertex, at the cost of
  scattering the fusion rule.
- Or does a separate, named fusion step own all ten — and if so, whose module is it? These
  are pedagogy inputs; `pedagogy/` already exists as a Feature Module.
- `student_problem` (`:2313`) and `non_attempt` (`:2327`) carry real safety-adjacent
  pedagogical rules ("a directive student problem is a non-attempt outright, whatever the
  answer cue says") with logged regressions behind them — the `"i can not understand"` graded
  wrong → mastery dropped incident. Whose invariant is that, and where is it tested?
- `_is_anaphoric_followup` is duplicated verbatim at `tutor_loop.py:1359` and
  `interaction_control/control.py:664`. One owner. Which? (Ticket 12 decides whether
  coreference is even a regex problem.)
- `_is_same_problem_followup` (`tutor_loop.py:1375`) reads `session["context"]` — is a
  cue that inspects conversation history still an input-layer cue?

## Resolution (2026-08-26, /grilling)

**This ticket resolves as a disposition record, not a design decision.** Its design question
— who owns the fusion of cue, model signal and session state — left this effort by user
decision (2026-08-26): **Perception owns `answer_attempt`; a future layer owns `LearnerAsk`,
the `non_attempt` derivation and the rest of the ten; the response layer owns its own rules.**
What remains here is where each of the ten goes, what Utterance Intake supplies, what the
in-place rewire touches, and what the future layer inherits — which is what ticket 16 needs.

### Findings that reshaped the ticket (verified against code, 2026-08-26)

**1. The fusion already exists four times, and the copies disagree.** The ticket framed this
as "scatter the OR to consumers, or name a fusion step". The scatter has already happened:

| Where | Fields | Filled from | Divergence |
|---|---|---|---|
| `_legacy_turn` inline (`tutor_loop.py:2266-2330`) | all ten | raw `text` + signals + session | the copy with the regression history |
| `PedagogyObservation` (`runtime/legacy_adapter.py:113`) | 8 near-twins | **normalized** text + signals | `learner_problem` = `is_problem AND directive` — **not** the legacy rule |
| `ResponsePlanningStateView` (`response_planning/interface.py:41`) | `wants_visual`, `wants_animation`, `wants_real_life`, `clarification` | only `clarification` | three fields **declared and never filled** |
| `ResponseGenerationStateView` (`response_generation/interface.py:21`) | `clarification`, `same_problem` | only `clarification` | `same_problem` **declared and never filled** |

The destinations exist; the live values are computed inline and passed to the modules through
`_legacy_turn`'s kwargs instead.

**2. There is a fourth non-attempt rule, and it is the one that protects grading.**
`evidence/grading.py:17 obvious_non_attempt` gates the writeback at
`assessment_evidence/interface.py:96`. `tutor_loop`'s `non_attempt` gates **only** HOPE probe
scoring (`tutor_loop.py:2350`). The ticket's "safety-adjacent rules with logged regressions"
premise is right, but the protection is split across two independent implementations in two
modules that do not know about each other.

**3. After ticket 01's deletions most of the ten are nearly dead.** `wants_why` has **no live
consumer** — only the debug `_cues` line (`:2450`); the live purpose judgment is
`PedagogyObservation.purpose_requested`. `student_problem` feeds only `non_attempt` plus that
same debug line. `wants_hint` feeds only `fresh_request`; `fresh_request` feeds only
`non_attempt`. `_response_layer` (`tutor_loop.py:1791`) **ignores all seven** of
`wants_visual / clarification / intro / grounding / crop_items / wants_animation /
wants_real_life`. And `answer_try`'s first two arms are the same fact twice:
`_interaction_answer_attempt` is already `perception.answer_attempt or route.answer_attempt`
(`interaction_control/control.py:447`).

**4. Eight of nine live consumption sites gate on `and not answer_try`.** The exceptions are
the dead `_response_layer` arguments and the debug line.

### Two inherited facts corrected

- **Perception executes *before* Interaction Control** (`runtime/coordinator.py:169` vs `:188`),
  despite `LOGICAL_TURN_PHASES` listing `ADMISSION_AND_ROUTING` first. The phase tuple is a
  **trace** contract, not the execution order. Anything reasoning about "the front door runs
  first" must reason about `coordinator.run`, not the enum.
- **`gate()` is called inside `Perception.perceive`** (`perception/interface.py:102`), not by
  Interaction Control. Ticket 01's manifest line ("Interaction Control keeps calling `gate()`
  unchanged") is loose about the caller; ticket 03 has it right. The *decision* ownership claim
  is unaffected — `gate()` stays exactly where it is and reads the intake observation.

### Disposition of the ten

| # | Boolean | Where the judgment lands | What this effort does to the line |
|---|---|---|---|
| 1 | `clarification` | `simplification_request` label | rewrite the regex arm as the label read |
| 2 | `wants_visual` | `request_representation` / `representation_shift` | same; the OR collapses to a plain label read |
| 3 | `wants_why` | new `purpose_question` label | rewrite arm; debug-only consumer handed to **ticket 13** |
| 4 | `wants_animation` | new `animation_request` label | rewrite arm |
| 5 | `wants_real_life` | new `real_life_request` label | rewrite arm |
| 6 | `answer_try` | Perception `answer_attempt`, authoritative | delete the `is_answer_attempt` arm; the first two arms are already one fact (`control.py:447`) |
| 7 | `student_problem` | Intake `ProblemReading` + a fusion the future layer owns | read `observation.problem`; **delete `analysis["problem_cue"]`** |
| 8 | `wants_hint` | `request_hint` + concept flags | untouched; stays a private local of `non_attempt` |
| 9 | `fresh_request` | labels only | untouched |
| 10 | `non_attempt` | **derived downstream from existing labels — not a new schema field** | untouched |

**Everything in the "untouched" column stays verbatim at `tutor_loop.py:2266-2330`**, now
model-fed rather than regex-fed, for the future layer to lift out intact. This effort's diff on
that block is exactly one kind of change — regex arm becomes label read — which is what keeps
ticket 15's measurement readable.

### `non_attempt` is not a fifth schema promotion

Perception already emits `answer_attempt: BOOLEAN` (`perception/gemini_perception.py:362`), and
`non_attempt` is built from `answer_attempt` + `acknowledgment` + `question` + the fresh-request
signals — all of which either exist or are already in ticket 01's promotion set. Making it its
own schema field would be a **fifth** promotion on top of 01's four labels plus `SESSION_CONTROL`,
with no dataset gold and a `build_perception` -> `vertex_cache --create` -> billed-eval rebuild
behind it. It stays a derivation, somewhere a regression test can pin it without a Vertex call.

`evidence/grading.py:17 obvious_non_attempt` **stays** as grading's own text-only floor, and is
**add-only**: it may add a refusal to grade, never remove one — the same direction rule ticket 07
uses for the safety gate. It has to survive independently because the Part 15 Phase B speculative
grader runs concurrently with perception and structurally cannot read a label (ticket 01's
accepted risk; ticket 04 spent its predicates).

### `analysis["problem_cue"]` is deleted, not mirrored

Its two consumers — the inline `student_problem` (`tutor_loop.py:2288`) and `pedagogy_request`
(`runtime/legacy_adapter.py:112`) — both read `observation.problem` instead, and Perception's own
`InputProcessor` construction (`perception/gemini_perception.py:149`) goes with it, completing
ticket 01's retirement of the two independent constructions. Keeping it as a transition mirror
was rejected: two suppliers of one fact is precisely the pattern that produced the four
disagreeing copies in Finding 1.

### `_is_anaphoric_followup`: one owner, decided here

Three implementations today — the `InputProcessor` method, `tutor_loop.py:1366`'s delegate, and a
**verbatim static copy** at `interaction_control/control.py:669`.

- The **evidence** is Utterance Intake's: `ReferenceReading` (anaphor spans + `word_count`),
  fixed by ticket 03.
- The **decision** stays Interaction Control's: the concept-drift guard at `control.py:431` is its
  own, and it is the only module holding `current_concept`.
- Therefore the `control.py` copy is **deleted in this effort**. Shipping Intake with a private
  duplicate of one of its own readings on day one is not a transition state worth having.
- `InteractionControlRequest` gains a `utterance_observation` field, filled by the adapter and
  injected by the coordinator, the same shape `perception` already uses. Rejected: hanging the
  reading off `PerceptionObservation` (makes Perception re-publish another module's reading —
  how `problem_cue` became a floating dict), and hanging it off `TurnInput` (puts a derived
  judgment on the raw input value ticket 02 kept to captured facts).
- Confidence bands and the word-count threshold remain **ticket 12's**.

### `_is_same_problem_followup`: out of scope

It is a generator-continuity rule (reuse the numbers already on the table), it reads
`session["context"]`, and `ResponseGenerationStateView.same_problem` already exists unfilled.
The response layer owns its own rules by the same user decision that moved the fusion out. This
effort does not place it; it records that the field it belongs in is already declared.

### The two logged regressions get tests now

Both become **named cases in ticket 14's corpus in this effort**, asserted at the layer boundary
(*given these labels, the turn must not be graded / must not move mastery*), not at the inline
expression:

- `"i can not understand"` graded wrong -> mastery dropped.
- A directive student problem (`"solve x^2-5x+6=0"`) while a bridge check is armed, swallowing
  the pending diagnostic.

Their only memory today is an inline expression and a comment, in a block scheduled to move. A
test that outlives the move is the cheapest insurance available.

### Open, and explicitly not reconciled here

`student_problem` (`is_problem AND (directive OR not answer_try)`) and
`PedagogyObservation.learner_problem` (`is_problem AND directive`) have disagreed on every
non-directive problem with no answer attempt since the modular split. The reconciliation is
**the future layer's**, since the rule is its property. Recorded target: the legacy rule, which
is the one the two incidents above were fixed against; the adapter's is a silent narrowing.
This effort changes neither copy.

### Consequences handed to other tickets

- **12** — narrowed further: Intake supplies the spans, Interaction Control produces the
  predicate, 12 decides the band and the threshold. The duplicate is gone before 12 starts.
- **13** — inherits a named dead-code list from this ticket: `_response_layer`'s seven ignored
  parameters, and `wants_why`'s debug-only consumer. Deliberately not deleted during the rewire
  so this effort's diff on the block stays one kind of change.
- **14** — the two regression cases above, asserted at the layer boundary.
- **15** — the measurable deltas from this ticket: regex arm -> label read on eight of the ten;
  `analysis["problem_cue"]` deleted; `control.py`'s anaphora copy deleted;
  `InteractionControlRequest` gains a field. No fusion expression changes, so no fusion delta to
  measure.
- **16** — the spec carries the disposition table, the future-layer inheritance list, and the two
  corrected facts (execution order, `gate()`'s caller).
