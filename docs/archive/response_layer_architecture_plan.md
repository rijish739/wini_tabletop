# Response Layer Architecture Plan

## Scope

This document defines the Response Layer architecture for the embodied AI teacher.
It starts after Retrieval and consumes the frozen contracts from the existing learner
architecture:

- Learner State Snapshot
- Pedagogical Action
- Retrieved Evidence
- Curriculum Metadata
- Teaching Goal
- Evidence Manifest
- Concept
- Misconceptions
- Representation Gaps

This document does not redesign:

- Cognitive Analyzer
- Learner State
- Pedagogical Decision Engine
- Retrieval Layer
- Existing deterministic scene renderer

The core architectural correction is to replace the current answer-first flow:

```text
Brain
-> Generated Answer
-> Scene Selection
-> Speech
-> Visual
```

with a script-first flow:

```text
Frozen learner/retrieval outputs
-> Response Context
-> Teaching Script
-> Validation
-> Modality Compilation
-> Device Execution Package
-> Beat-Synchronized Runtime
-> Telemetry and Assessment Events
```

The Teaching Script is the only source of instructional truth.

## Review Disposition

A follow-up architecture review identified several genuine production issues in
this draft. The accepted fixes are incorporated throughout this document:

- hard time-to-first-audio target: TTFA must remain less than or equal to 4 seconds
  on the normal voice path
- first-beat commit instead of whole-script commit
- streaming beat generation so a valid prefix can execute while later beats are still
  being planned
- template-first planning, with LLM planning reserved for turns where templates do
  not fit
- claim-to-evidence consistency validation, not citation-only grounding
- bounded branching for immediate assessment remediation
- explicit spoken-assessment checkpoints and barge-in handling
- response kinds for instructional, social, administrative, and off-domain turns
- single-writer learner-state rule with idempotent assessment events
- reported, versioned device capability handshake
- cache keys that avoid unsafe learner-state reuse
- transport package limits that never clamp pedagogically required answer length

---

# 1. Pain Point Analysis

## 1.1 Speech/Visual Mismatch

### Root Cause

Speech is generated first, and the visual is selected afterward.

### Why It Happens

The visual layer reacts to an already-written answer instead of sharing the same
pedagogical plan.

### Why Current Architecture Cannot Solve It

Scene selection has no authority over what speech says, and speech generation does
not know the exact visual that will be shown.

### Architectural Change Required

Introduce a canonical Teaching Script before speech, visuals, robot behavior, text,
touch, animation, or assessment are generated.

### Tradeoff

This adds a small planning step before response execution, but it makes coherence
enforceable.

## 1.2 Visuals Are Treated As Default Teaching Output

### Root Cause

Current visual logic can default to showing a teaching visual on many teaching turns.

### Why It Happens

The visual layer is optimized for "show, do not only tell," but not for "show only
when it improves learning."

### Why Current Architecture Cannot Solve It

Retrieval and scene selection know visual availability. They do not decide whether
the learner needs a visual in this turn.

### Architectural Change Required

Add a Visual Benefit Gate inside the Teaching Script Planner using learner state,
representation gaps, teaching goal, cognitive load, and concept affordances.

### Tradeoff

Some turns become speech-only. This may feel less visually rich, but it is better
pedagogy when visuals add load or distraction.

## 1.3 Scene Selection Is Concept-Centric, Not Step-Centric

### Root Cause

Scenes are indexed mainly by concept.

### Why It Happens

`concept_figures.json` maps a concept to a scene, but the same concept can be taught
through explanation, misconception correction, derivation, graph translation, quiz,
hint, or assessment.

### Why Current Architecture Cannot Solve It

A concept-level scene cannot know the current pedagogical move.

### Architectural Change Required

Select visual plans by:

```text
concept
pedagogical_action
representation_gap
misconception_target
teaching_goal
device_profile
```

### Tradeoff

Scene metadata and cache keys become richer, but visual selection becomes
instructionally meaningful.

## 1.4 Evidence Grounding Is Not Shared By All Modalities

### Root Cause

The generated answer uses retrieved evidence, but visual, text, interaction, and
robot layers may use parallel assumptions.

### Why It Happens

The Evidence Manifest is not yet the universal constraint for every modality.

### Why Current Architecture Cannot Solve It

The deterministic visual renderer renders whatever declarative scene spec it
receives. It does not validate pedagogical grounding.

### Architectural Change Required

Every Teaching Script beat must cite evidence IDs. Modality compilers may only
express claims present in that beat.

### Tradeoff

Some generated outputs become shorter because unsupported claims are rejected. This
is the correct tradeoff for a teacher.

## 1.5 Scene Narration Competes With Brain Narration

### Root Cause

Existing scene specs contain their own narration.

### Why It Happens

Standalone scene demos use scene narration as teaching audio. Live tutoring uses
brain-generated speech.

### Why Current Architecture Cannot Solve It

Two independent narration sources can create audio contention and semantic conflict.

### Architectural Change Required

In live tutoring, narration must come only from the Teaching Script. Scene beat
narration becomes authoring metadata or a template source, not runtime speech
authority.

### Tradeoff

Existing scene specs need adaptation metadata, but the renderer can remain unchanged.

## 1.6 Streaming Starts Before Visual Commitment

### Root Cause

Speech may begin before the visual plan is finalized or armed.

### Why It Happens

Low-latency streaming is prioritized before cross-modal synchronization.

### Why Current Architecture Cannot Solve It

There is no response commit point that says the first executable teaching segment is
valid and synchronized.

### Architectural Change Required

Add a first-beat Response Commit step. No modality starts until the first executable
beat is validated and armed. The whole script does not need to be complete before
speech starts; later beats may continue planning, validation, compilation, and
packaging while the first beat plays.

### Tradeoff

The system must preserve the existing voice-first latency target. TTFA is a hard
architectural budget, not a soft preference:

```text
normal voice path TTFA <= 4 seconds
```

This requires template-first planning, beat streaming, and committing only the first
valid beat.

## 1.7 Touch Interaction Is Not Pedagogically Coupled

### Root Cause

Touch UI can be treated as display behavior instead of a planned learning event.

### Why It Happens

Interaction is downstream of UI instead of upstream in the teaching plan.

### Why Current Architecture Cannot Solve It

The learner model needs meaningful assessment events, not raw taps.

### Architectural Change Required

Touch affordances must be declared as Assessment Hooks inside script beats.

### Tradeoff

There will be fewer arbitrary interactions, but each interaction becomes
instructionally meaningful.

## 1.8 Robot Behavior Can Become Decorative

### Root Cause

Gestures, gaze, LEDs, or motion can be selected independently from the learning step.

### Why It Happens

Embodiment is often treated as engagement polish rather than a pedagogical channel.

### Why Current Architecture Cannot Solve It

Existing retrieval and pedagogy contracts do not schedule embodied behavior.

### Architectural Change Required

Robot behavior must be compiled from script beats as a low-bandwidth pedagogical
channel: attention, turn-taking, encouragement, pointing, pause, celebration, or
uncertainty.

### Tradeoff

The robot becomes less randomly expressive and more instructionally consistent.

## 1.9 Assessment Is Often Added After Explanation

### Root Cause

Checks for understanding are generated as endings, not planned as state-changing
events.

### Why It Happens

Answer generation thinks in prose, not in learning transactions.

### Why Current Architecture Cannot Solve It

The current Response Layer does not own assessment instrumentation.

### Architectural Change Required

Every relevant script includes explicit assessment hooks with expected response
type, scoring method, and learner-state writeback intent.

### Tradeoff

Responses become more structured, but learner modeling becomes more reliable.

## 1.10 Fallbacks Can Preserve The Same Failure

### Root Cause

If a scene fails, fallback may show a crop or generic visual while speech continues.

### Why It Happens

Fallback is availability-based, not coherence-based.

### Why Current Architecture Cannot Solve It

Device renderer failure handling is local. It cannot reason about teaching
coherence.

### Architectural Change Required

If synchronized visual execution cannot be guaranteed, degrade to speech/text-only
for that beat.

### Tradeoff

The system may become less visual during failures, but it will not teach with the
wrong visual.

## 1.11 Cache Key Is Too Coarse

### Root Cause

Concept-level scene caching ignores learner state and pedagogical action.

### Why It Happens

Existing scenes are authored as reusable concept visuals.

### Why Current Architecture Cannot Solve It

A concept cache cannot distinguish "correct misconception" from "derive formula" or
"translate graph to equation."

### Architectural Change Required

Cache reusable visual assets separately from learner-specific Teaching Script
instances.

### Tradeoff

Cache management becomes more complex, but reusable components remain small and
portable.

## 1.12 Device Constraints Are Not First-Class During Planning

### Root Cause

Cloud generation may assume display, memory, animation, or interaction capabilities
the device cannot support.

### Why It Happens

Device rendering is downstream of planning.

### Why Current Architecture Cannot Solve It

The renderer can fail or skip malformed elements, but it cannot redesign the
teaching step.

### Architectural Change Required

The planner must consume a Device Capability Profile before producing a script.

### Tradeoff

The planner needs one more input, but Raspberry Pi to ESP32 migration becomes a
profile change instead of a response architecture rewrite.

## 1.13 Citation Does Not Prove Grounding

### Root Cause

A generated beat can cite a real evidence ID while misstating what the evidence says.

### Why It Happens

Beat-level citation proves provenance, not entailment. The planner still produces
substantive instructional claims.

### Why Current Architecture Cannot Solve It

The Evidence Manifest can show where content should come from, but it does not by
itself verify that the generated claim matches the cited source.

### Architectural Change Required

Add claim-to-evidence consistency validation. Formula and numeric claims require
deterministic checks where possible. Definitional claims must be bounded to cited
evidence spans. Novel uncached claims may require a lightweight NLI-style verification
pass.

### Tradeoff

Validation adds cost on novel claims, but cached/template paths avoid most of that
cost.

## 1.14 Linear Scripts Cannot Handle Immediate Pedagogical Branching

### Root Cause

A linear beat list cannot adapt when an assessment inside the script reveals a new
state.

### Why It Happens

Assessment hooks are embedded in beats, but the original script model only advanced
linearly.

### Why Current Architecture Cannot Solve It

Fallback branching handles failures, not correct pedagogical alternatives such as
"student answered correctly" versus "misconception confirmed."

### Architectural Change Required

Represent the Teaching Script as a shallow, bounded branching DAG. Immediate branches
may handle one-level hint/remediation. Deeper adaptation ends the script and returns
to the existing Pedagogical Decision Engine loop.

### Tradeoff

The script model becomes slightly richer, but the branching scope remains bounded and
does not replace the existing learner loop.

## 1.15 Voice-First Assessment And Barge-In Are Missing

### Root Cause

The device is voice-first, but the first draft treated most beat completion as local
touch or timer behavior.

### Why It Happens

Touch interactions are easier to score locally. Spoken answers require STT,
perception, grading, and cloud re-entry.

### Why Current Architecture Cannot Solve It

The local beat runner cannot grade spoken reasoning by itself and cannot decide
whether an interruption is a new question, an answer, or a request to stop.

### Architectural Change Required

Assessment hooks must support `local` and `spoken` execution modes. Spoken assessment
is a cloud checkpoint that suspends the beat runner until grading/branching returns.
The Device Script Runner must also support barge-in by pausing or ducking TTS and
emitting an interrupt event.

### Tradeoff

Spoken checks add round-trip latency at assessment points, but those points are
explicit and instructionally meaningful.

## 1.16 Non-Instructional Turns Need A First-Class Path

### Root Cause

Not every turn has a concept, evidence, or curriculum target.

### Why It Happens

Greetings, farewells, boredom, session control, and off-domain utterances can bypass
retrieval or have no meaningful concept.

### Why Current Architecture Cannot Solve It

If every response is assumed instructional, the Context Adapter treats missing
concept/evidence as a failure.

### Architectural Change Required

Add `response_kind` with at least `instructional`, `social`, `administrative`, and
`off_domain`. Full evidence grounding is required only for instructional responses.

### Tradeoff

The script schema becomes slightly broader, but the instructional path remains strict.

## 1.17 Learner State Must Have One Writer

### Root Cause

Asynchronous response telemetry can race with the existing synchronous learner-state
update path.

### Why It Happens

Response execution naturally emits events after delivery, while the existing learner
loop already applies probe and bridge results.

### Why Current Architecture Cannot Solve It

If telemetry writes learner state directly, the same assessment can be double-applied
or applied out of order.

### Architectural Change Required

Use a single-writer rule. The Response Layer emits idempotent assessment/outcome
events. The existing learner-state path applies them once at turn close through the
current writeback APIs.

### Tradeoff

State updates are less immediate inside the Response Layer, but ordering and
correctness are preserved.

## 1.18 Device Capabilities Need Runtime Handshake

### Root Cause

A static cloud-side device profile can drift from real firmware and hardware state.

### Why It Happens

Robotics, audio, touch, and display capabilities may fail or change independently of
the cloud planner.

### Why Current Architecture Cannot Solve It

If the planner assumes unsupported primitives, the device may silently drop them.

### Architectural Change Required

The device reports a versioned capability profile at session start. The planner uses
the reported profile, and compilers drop unavailable primitives before packaging.

### Tradeoff

Session startup gains a handshake, but planned behavior matches real device ability.

---

# 2. Overall Philosophy

The Response Layer should be a teaching transaction compiler, not an answer
generator.

The central object is the Teaching Script:

```text
Teaching Script
-> speech
-> visuals
-> robot behavior
-> touch interaction
-> animations
-> text
-> assessment
-> telemetry
```

Every modality renders the same script. No modality independently invents
instructional content.

## Why This Exists

The robot is a teacher, not a multimedia chatbot. Learning coherence matters more
than expressive variety.

---

# 3. Architectural Principles

## 3.1 One Pedagogical Step, Many Renderings

A beat contains one atomic teaching idea. Speech, visual, text, robot behavior, and
touch must express that same idea.

## 3.2 Visuals Are Earned, Not Default

A visual appears only if it reduces cognitive load, addresses a representation gap,
disambiguates a misconception, supports interaction, or teaches an inherently
spatial, symbolic, graphical, tabular, or procedural concept.

## 3.3 LLMs Plan; Deterministic Systems Render

LLMs may produce declarative script/spec objects. They must never directly render
graphics or issue arbitrary UI commands.

## 3.4 Grounding Is Beat-Level

Every claim in every modality must point to retrieved evidence, curriculum metadata,
concept metadata, or an approved pedagogical template.

Grounding requires consistency, not only citation. The validator must reject a beat
when the claim is not supported by the cited evidence.

## 3.5 Fallback Reduces Modality Count

If coherence is uncertain, remove modalities. Do not replace a failed visual with an
unrelated visual.

## 3.6 Device Limits Are Planning Inputs

The cloud planner must know whether it is targeting Raspberry Pi, ESP32-P4, LVGL,
touch availability, memory budget, animation budget, and network state.

## 3.7 Preserve Voice-First Responsiveness

The normal voice path must keep TTFA less than or equal to 4 seconds. The architecture
therefore commits the first validated beat, not the full script, and compiles later
beats while the current beat plays.

## 3.8 Macro Pedagogy Belongs Upstream

The Pedagogical Decision Engine owns the turn-level `pedagogical_action`. The Response
Layer owns only micro choreography: how to stage that action across beats and
modalities. It may not choose a different macro action.

## 3.9 Assessment Branching Is Bounded

Within-turn branching may handle immediate hinting or remediation, but deeper
adaptation returns to the existing learner loop. The Response Layer must not become a
second Pedagogical Decision Engine.

## 3.10 Learner State Has A Single Writer

The Response Layer emits idempotent outcome events. It does not directly mutate
Learner State.

---

# 4. Response Layer Boundaries

## 4.1 Starts After Retrieval

The Response Layer consumes frozen upstream outputs and produces an executable
multimodal response package.

For non-instructional responses, such as greetings, farewells, session-control
messages, boredom responses, or off-domain redirects, the system may enter the
Response Layer without a concept or evidence bundle. These responses use
`response_kind != instructional` and are restricted to minimal speech/text behavior.

The deterministic input safety gate on the learner utterance runs before the Response
Layer and is unchanged by this design. Output safety in this document is additive.

## 4.2 Does Not Own

- Cognitive analysis
- Concept resolution
- Learner state model
- Pedagogical policy selection
- Retrieval ranking
- Curriculum graph
- Deterministic scene rendering
- direct learner-state mutation

## 4.3 Owns

- Multimodal teaching plan
- Response synchronization
- Modality selection
- Modality compilation
- Runtime package for device
- Response telemetry
- Assessment event hooks
- Safe fallback behavior
- idempotent outcome events for the existing learner-state writeback path

## Why This Boundary Exists

Upstream modules decide what should be taught and why. The Response Layer decides
how that teaching move is expressed coherently.

The boundary is enforced by a validator rule: every beat's `pedagogical_step` must be
a legal decomposition of the upstream `pedagogical_action`. If the planner selects a
different macro action, the script is rejected.

---

# 5. Module Responsibilities

The architecture uses fewer, stronger modules:

```text
Response Context Adapter
-> Teaching Script Planner
-> Script Validator and Safety Gate
-> Modality Compilers
-> Runtime Package Builder
-> Device Script Runner
-> Telemetry and Outcome Emitter
```

## 5.1 Response Context Adapter

### Why It Exists

Frozen upstream modules output several objects with different schemas and timing.
The Response Layer needs one normalized input envelope.

### Problem It Solves

It prevents inconsistent inputs, missing fields, and unclear priority between
evidence, learner state, and teaching goal.

### Why Existing Modules Cannot Solve It

Retrieval should not know device capability or response packaging. The Pedagogical
Decision Engine should not know rendering constraints.

### Data It Owns

- `response_context_id`
- normalized response request
- device capability profile reference
- turn constraints
- `response_kind`

### Data It Consumes

- learner snapshot
- pedagogical action
- retrieved evidence
- curriculum metadata
- teaching goal
- evidence manifest
- concept
- misconceptions
- representation gaps
- reported device capability profile

### Data It Produces

- `ResponseContext`

### Failure Modes

- missing concept
- weak evidence manifest
- unavailable device profile
- contradictory pedagogical action and teaching goal
- missing concept/evidence on an instructional response
- incorrectly routing a social or administrative response into the instructional path

### Runtime Cost

Very low. Mostly deterministic schema mapping.

### Latency Impact

Negligible.

### Future Extensibility

New device profiles or curriculum fields can be added here without touching upstream
modules.

## 5.2 Teaching Script Planner

### Why It Exists

This is the architectural center. It creates the single synchronized plan before any
modality output exists.

### Problem It Solves

It prevents speech, visuals, touch, robot behavior, text, animation, and assessment
from drifting apart while preserving voice-first responsiveness.

### Why Existing Modules Cannot Solve It

The Pedagogical Decision Engine chooses the teaching action. Retrieval provides
evidence. Neither choreographs multimodal execution.

### Data It Owns

- Teaching Script
- beat graph
- modality policy per beat
- visual benefit decision
- interaction decision
- assessment hook placement
- pacing plan
- first-beat commit boundary
- bounded branch targets

### Data It Consumes

- `ResponseContext`
- device capability profile
- cached scene/asset metadata
- pedagogical templates
- allowed step-sequence table for the upstream pedagogical action

### Data It Produces

- streamed `TeachingScriptDraft` beats
- first validated beat candidate

### Failure Modes

- overlong script
- unsupported modality request
- ungrounded claim
- too many beats
- visual included without learning justification
- missing assessment when action requires one
- selecting a macro pedagogical action different from the upstream action
- pre-authoring a correction before a misconception is confirmed
- producing a whole-script plan too slowly for the TTFA budget

### Runtime Cost

Low on the template fast path. Medium to high only when LLM-based planning is needed.
Planner calls must use structured streaming, bounded beats per call, and
`thinking_budget=0` where the backend supports it.

### Latency Impact

Primary cloud planning cost. The normal voice path must satisfy TTFA <= 4 seconds by
committing the first validated beat while later beats continue behind playback.

### Future Extensibility

Future modalities attach to the script beat schema, not to upstream learner modules.

### Planning Modes

The default fast path is template-first:

```text
PDE action + concept type + representation/misconception state
-> script spine
-> streamed spoken/content fill
-> first-beat commit
```

The medium path uses a full LLM planner only when no template fits. The slow path
must never block a live turn on new visual authoring.

## 5.3 Script Validator and Safety Gate

### Why It Exists

Generation cannot be trusted as the enforcement layer.

### Problem It Solves

It catches hallucinated claims, unsupported visuals, unsafe robot commands, malformed
scene specs, excessive cognitive load, and invalid assessment hooks.

### Why Existing Modules Cannot Solve It

Upstream systems do not see the final multimodal plan.

### Data It Owns

- validation results
- rejection reasons
- safe fallback policy
- script safety status
- claim-to-evidence consistency status
- allowed-step compliance status

### Data It Consumes

- `TeachingScriptDraft`
- Evidence Manifest
- renderer schema
- device limits
- safety policy
- age and grade constraints
- formula and numeric extraction helpers
- allowed step-sequence table

### Data It Produces

- `ValidatedTeachingScript`
- or `FallbackTeachingScript`

### Failure Modes

- false rejection
- overly conservative fallback
- validator schema drift
- citation present but claim not entailed by the cited evidence
- wrong-but-valid enum choices

### Runtime Cost

Low to medium. Mostly deterministic.

Claim/evidence consistency is tiered by cost:

- formulas and numbers use deterministic cross-checks where possible
- factual and definitional claims must stay paraphrase-bounded to cited evidence spans
- novel uncached claims may use a lightweight NLI-style pass
- cached/template scripts skip expensive checks only when their claims were previously
  validated against the same curriculum source version

### Latency Impact

Small, but must run before execution.

For streaming execution, validation runs beat-by-beat. The first valid beat can commit
while later beats continue validating.

### Future Extensibility

New validators can be added per modality without changing the planner contract.

### Required Validator Rules

- `response_kind=instructional` requires concept/evidence grounding.
- `response_kind=social`, `administrative`, and `off_domain` must remain speech/text
  only unless a product rule explicitly allows otherwise.
- Every `pedagogical_step` must be legal under the upstream `pedagogical_action`.
- Misconception correction beats are unreachable until the relevant probe confirms the
  misconception.
- `visual_type` must be compatible with `pedagogical_step`, representation target, and
  device profile.
- Robot primitives absent from the reported device capability profile are dropped
  before packaging.

## 5.4 Modality Compilers

### Why They Exist

Each modality needs different runtime artifacts, but none should invent content.

### Problem They Solve

They convert canonical beats into speech text, visual specs, LVGL text, touch
affordances, robot primitives, animation timing, and assessment events.

### Why This Should Not Be Absorbed Into The Planner

Planning and compilation have different failure profiles. The planner decides
teaching intent. Compilers enforce device-specific output contracts.

### Data They Own

- compiled speech chunks
- visual scene references/specs
- text captions
- touch widgets
- robot primitive sequence
- assessment event schema

### Data They Consume

- `ValidatedTeachingScript`
- device profile
- renderer vocabulary
- TTS profile
- robot capability profile

### Data They Produce

- `CompiledResponseBundle`

### Failure Modes

- TTS-unfriendly wording
- visual spec too large
- touch layout unsupported
- robot primitive unavailable
- animation exceeds frame budget

### Runtime Cost

Low to medium.

### Latency Impact

Moderate if TTS pre-synthesis is included.

### Future Extensibility

New modality compilers can be added as long as they consume beat semantics.

## 5.5 Runtime Package Builder

### Why It Exists

The device should receive a compact, deterministic, executable package.

### Problem It Solves

It handles network fragility, duplicate data transfer, asset hashing, and device
payload limits.

### Why Existing Modules Cannot Solve It

Cloud planners do not manage LVGL asset paths, hashes, frame slots, or ESP32 memory
budgets.

### Data It Owns

- response bundle ID
- asset hashes
- script manifest
- cache directives
- payload size limits

### Data It Consumes

- compiled response bundle
- local/cloud cache index
- device profile

### Data It Produces

- `DeviceExecutionPackage`

### Failure Modes

- package too large
- missing asset hash
- cache miss
- stale asset version

### Runtime Cost

Low.

### Latency Impact

Small, but important for ESP32.

### Future Extensibility

Supports future binary packing, compression, or pre-rendered frame bundles.

## 5.6 Device Script Runner

### Why It Exists

Synchronization must be enforced at runtime, not merely described.

### Problem It Solves

It prevents visuals from advancing early, speech from lagging, touch events from
being assigned to the wrong beat, and robot behavior from drifting.

### Why Existing Renderer Cannot Solve It

The renderer draws frames. It does not own teaching-time orchestration.

### Data It Owns

- beat execution state
- local playback clock
- modality acknowledgements
- touch event capture
- fallback execution
- spoken-assessment checkpoint state
- interruption and resume state

### Data It Consumes

- `DeviceExecutionPackage`
- local renderer
- TTS/audio output
- LVGL UI
- robot control interface
- touch input
- VAD/interruption signal

### Data It Produces

- execution acknowledgements
- beat completion events
- interaction events
- local error reports
- interrupt events
- checkpoint suspend/resume events

### Failure Modes

- audio unavailable
- frame render failure
- UI reload failure
- touch timeout
- robot motor unavailable
- WiFi drop mid-turn
- barge-in during speech
- spoken assessment waiting on cloud grading

### Runtime Cost

Low to medium depending on rendering.

### Latency Impact

Beat-level and predictable.

### Future Extensibility

The same package model can target Raspberry Pi now and ESP32-P4 later.

### Barge-In Contract

While speech plays, VAD remains active. On learner speech, the runner:

```text
duck or pause TTS
-> capture the utterance
-> emit interrupt(script_id, beat_id, audio_ref, resume_point)
-> wait for cloud decision: resume, answer interjection, or end script
```

Each beat declares whether it is `resumable` and where execution should resume.

## 5.7 Telemetry and Outcome Emitter

### Why It Exists

The system must report what was actually delivered, not only what was planned.

### Problem It Solves

It prevents learner state updates and RL training from using imaginary delivery
events.

### Why Existing Learner State Cannot Solve It

Learner State needs delivery evidence and learner response events, but it should not
inspect UI internals.

### Data It Owns

- response execution log
- assessment event results
- modality delivery status
- latency metrics
- fallback markers
- idempotency keys for assessment and delivery events

### Data It Consumes

- device execution events
- touch responses
- speech completion
- assessment hooks
- script IDs

### Data It Produces

- learning events for existing learner-state APIs
- telemetry logs
- RL reward features

### Failure Modes

- missing device acknowledgement
- duplicate event delivery
- delayed touch event
- network reconnection replay
- out-of-order spoken assessment result

### Runtime Cost

Low.

### Latency Impact

Asynchronous after response.

### Future Extensibility

Supports RL, dashboards, debugging, audits, and policy evaluation.

### Single-Writer Rule

The Telemetry and Outcome Emitter does not write Learner State directly. It emits
events that flow through the existing synchronous learner-state writeback path, such
as `apply_probe_result` and `apply_bridge_result`, at turn close.

Every assessment event carries:

```text
script_id
beat_id
attempt
assessment_hook_id
idempotency_key = script_id + beat_id + attempt
```

Events arriving during an active or frozen test are recorded but gated by the existing
test protection rules.

---

# 6. Runtime Pipeline

```text
1. Retrieval completes.
2. Response Context Adapter builds ResponseContext.
3. Reported Device Capability Profile is attached.
4. Teaching Script Planner selects a template spine or starts an LLM planner stream.
5. Planner emits beat[0].
6. Visual Benefit Gate decides beat[0] modality policy.
7. Script Validator checks beat[0] grounding, coherence, safety, and device limits.
8. Modality Compilers compile beat[0].
9. Runtime Package Builder sends the first executable beat package.
10. Device Script Runner starts beat[0].
11. Later beats continue planning, validating, compiling, and packaging behind playback.
12. Assessment checkpoints may suspend execution and re-enter the cloud.
13. Telemetry and Outcome Emitter records delivery and assessment events.
14. Existing learner loop consumes idempotent outcome events through the single writer path.
```

## Why This Exists

The runtime pipeline creates hard ordering:

- planning before modality output
- first-beat validation before first audio
- execution before learner-state delivery claims

It also preserves the voice-first latency target:

```text
normal voice path TTFA <= 4 seconds
```

The system does not wait for a whole-script commit before speaking.

---

# 7. Data Ownership

## 7.1 Upstream-Owned Data

| Data | Owner |
|---|---|
| learner mastery | Learner State |
| misconception state | Learner State |
| cognitive signals | Cognitive Analyzer |
| pedagogical action | Pedagogical Decision Engine |
| retrieved chunks/figures | Retrieval Layer |
| evidence manifest | Retrieval Layer |
| curriculum graph | Existing curriculum/retrieval system |

## 7.2 Response-Layer-Owned Data

| Data | Owner |
|---|---|
| `ResponseContext` | Response Context Adapter |
| `TeachingScript` | Teaching Script Planner |
| modality policy | Teaching Script Planner |
| validation status | Script Validator |
| compiled speech/visual/touch/robot artifacts | Modality Compilers |
| device package | Runtime Package Builder |
| execution status | Device Script Runner |
| delivered-response telemetry | Telemetry and Outcome Emitter |

## Why This Exists

The learner architecture remains authoritative for learning state. The Response
Layer is authoritative for delivered teaching behavior.

---

# 8. Cloud vs Device Split

## 8.1 Cloud Responsibilities

The cloud runs:

- Response Context Adapter
- Teaching Script Planner
- Script Validator
- most Modality Compilation
- TTS preparation where needed
- cache lookup
- package building
- telemetry aggregation
- RL policy shadowing
- session-level reported capability cache

## Why Cloud

LLM reasoning, validation, retrieval references, and heavier planning do not fit
ESP32 memory or latency constraints.

## 8.2 Device Responsibilities

The device runs:

- deterministic scene renderer or LVGL-native equivalent
- Device Script Runner
- touch input capture
- robot primitive executor
- local beat clock
- local fallback behavior
- asset cache
- optional simple TTS playback
- session-start capability report

## Why Device

Rendering and embodied timing must remain local and deterministic.

## Core Rule

```text
Cloud decides the teaching script.
Device executes the teaching script.
Device never invents teaching content.
Device reports what it can actually execute.
```

## 8.3 Capability Handshake

At session start, the device sends a versioned capability profile:

```text
device_class
firmware_version
profile_schema_version
display_capabilities
touch_capabilities
audio_capabilities
robot_primitives
known_disabled_features
memory_limits
package_limits
```

The planner uses this reported profile. If firmware or hardware disables a capability,
the compiler drops that modality before packaging and logs the drop.

---

# 9. Module Dependency Graph

```text
Frozen Inputs
  |-- Learner State Snapshot
  |-- Pedagogical Action
  |-- Retrieved Evidence
  |-- Curriculum Metadata
  |-- Evidence Manifest
  |-- Concept
  |-- Misconceptions
  `-- Representation Gaps
        |
        v
Response Context Adapter
        |
        v
Teaching Script Planner
        |
        v
Script Validator and Safety Gate
        |
        v
Modality Compilers
  |-- Speech Compiler
  |-- Visual Compiler
  |-- Interaction Compiler
  |-- Robot Behavior Compiler
  |-- Text Compiler
  `-- Assessment Hook Compiler
        |
        v
Runtime Package Builder
        |
        v
Device Script Runner
        |
        v
Telemetry and Outcome Emitter
        |
        v
Existing learner-state update path
```

---

# 10. Teaching Script Architecture

The Teaching Script is the canonical response object.

## 10.1 Top-Level Fields

```text
script_id
turn_id
response_kind
learner_snapshot_ref
pedagogical_action
teaching_goal
concept_id
misconception_targets
representation_targets
evidence_manifest_ref
device_profile
beats{}
entry_beat_id
fallback_policy
telemetry_policy
streaming_policy
```

For `response_kind=social`, `administrative`, or `off_domain`, `concept_id`,
`evidence_manifest_ref`, `misconception_targets`, and `representation_targets` may be
empty. These scripts are constrained to minimal speech/text behavior.

## 10.2 Beat Fields

```text
beat_id
pedagogical_step
atomic_learning_claim
evidence_refs
spoken_content
visual_intent
text_intent
interaction_intent
robot_intent
assessment_hook
timing_policy
completion_condition
fallback_behavior
resumable
on_complete
on_correct
on_incorrect
on_nonresponse
```

`beats{}` is a shallow, bounded branching DAG. It is not an unrestricted dialogue
policy. Immediate branches may handle one level of hint/remediation. Anything deeper
terminates the script and returns control to the existing Pedagogical Decision Engine
loop.

## 10.3 Example Beat

```text
Beat 2
Pedagogical step: representation translation
Atomic claim: The x-intercepts of the graph are the zeroes of the quadratic polynomial.
Speech: Explain that zeroes are where y becomes 0.
Visual: Highlight graph crossing x-axis.
Touch: Ask learner to tap one intercept.
Robot: Look or point toward screen.
Assessment: Tap location scored as intercept recognition.
Evidence refs: graph chunk plus concept metadata.
```

## Why This Exists

Every modality references the same `atomic_learning_claim`. That is the unit of
coherence.

The beat graph exists because assessment can change the immediate next step. It is
bounded because long-horizon adaptation belongs to the frozen learner and pedagogy
loop.

---

# 11. Synchronization Strategy

The system uses beat-level synchronization.

Each beat executes as:

```text
Prepare visual/text/robot state
-> Show frame/caption
-> Start speech
-> Run aligned robot primitive
-> Wait for speech completion
-> If local interaction is required, wait for touch or timeout
-> If spoken assessment is required, suspend and re-enter cloud grading
-> Emit beat-complete event
-> Advance to the next beat target
```

## Why Beat-Level Synchronization

The existing scene system already uses "beat = sentence." Beat-level sync is simple
enough for Raspberry Pi and ESP32, avoids word-level timing complexity, and prevents
visual drift.

## Hard Rule

```text
A later beat cannot display until the current beat has completed, branched, suspended
for spoken assessment, or failed safely.
```

## Commit Rule

```text
Response commit = first beat validated, compiled, packaged, and armed.
```

The full script may still be streaming. Later beats are committed independently as
they validate. A truncated planner stream may still yield a usable prefix of valid
beats.

## Fallback Rules

| Failure | Behavior |
|---|---|
| visual fails | continue speech/text only for that beat |
| speech fails | show text and pause for tap-to-continue |
| touch fails | timeout and record non-response |
| robot fails | suppress robot behavior only |
| validation fails | regenerate or use speech-only fallback |
| spoken checkpoint times out | end current script and return to main learner loop |
| barge-in occurs | pause/duck TTS and emit interrupt event |

---

# 12. Visual Planning Architecture

Visual planning is inside the Teaching Script Planner, not after speech.

## 12.1 Visual Benefit Gate

A visual is allowed only if at least one condition is true:

- concept is inherently spatial, graphical, geometric, symbolic, procedural, or tabular
- learner has a representation gap that the visual addresses
- misconception is better corrected visually
- interaction requires visible objects
- animation reveals a process that static speech cannot explain well
- retrieved evidence includes a relevant figure with strong manifest support

A visual is rejected if:

- learner cognitive load is high and visual adds split attention
- concept is better taught verbally
- evidence does not support the visual
- device cannot render it within budget
- visual would reveal an answer during test/practice
- scene is only loosely concept-related

## 12.2 Visual Types

```text
none
static_text_formula
static_diagram
retrieved_crop
authored_scene
generated_declarative_scene_spec
interactive_visual
animation
```

## 12.3 Authored Scene Adaptation Contract

Existing authored scenes may contain narration. In live tutoring, the Teaching Script
remains the speech authority. Each authored scene therefore needs adaptation metadata:

```text
scene_id
concept_id
teaches_claims[]
representation_targets[]
misconception_targets[]
pedagogical_actions_supported[]
narration_mode = as_authored | visual_only | script_override
beat_claim_map[]
device_profiles_supported[]
```

The planner may use a scene as authored only when its narration matches the planned
claim and pedagogical action. Otherwise, it uses the scene visual-only and compiles
speech from the Teaching Script.

## Why This Exists

Visuals become pedagogical instruments, not decorative output.

---

# 13. Interaction Planning Architecture

Interaction is planned only when it creates useful learner evidence.

## 13.1 Interaction Types

```text
tap target
multiple choice
drag/order
trace path
select misconception
step confirmation
confidence check
```

## 13.2 Required Fields

Each interaction defines:

```text
prompt
execution_mode
expected action
scoring rule
timeout
hint-on-failure
learner-state signal
telemetry event
```

`execution_mode` is one of:

```text
local
spoken
```

`local` interactions are scored on-device. `spoken` interactions suspend the device
runner and create a cloud checkpoint for STT, perception, grading, and branching.

## Why This Exists

Touch interaction should feed learning, not merely make the robot feel interactive.

## Failure Mode

The learner may tap randomly.

## Recovery

Treat the event as low-confidence evidence unless it is repeated or paired with
spoken reasoning.

---

# 14. Speech Planning Architecture

Speech is compiled from the Teaching Script, not generated independently.

## 14.1 Speech Rules

- one atomic idea per beat
- age-appropriate language
- short spoken sentences
- no reference to visuals unless the beat includes that visual
- no claim without evidence ref
- no "look at this" unless device acknowledged display
- no answer reveal during assessment beats
- align with pedagogical action budget

## 14.2 Speech Compiler Outputs

```text
sentence_chunks
tts_hints
pause_points
emphasis_tags
fallback_text
```

## Why This Exists

Spoken tutoring is cognitively fragile. Long turns increase load and reduce useful
feedback.

---

# 15. Robot Behavior Planning

Robot behavior should support attention and social regulation. It should not teach
new content independently.

## 15.1 Allowed Primitives

```text
look_at_screen
look_at_learner
point_to_screen_region
nod
encourage
thinking_pause
celebrate_small_success
show_uncertainty
idle_still
```

## 15.2 Beat Alignment Examples

| Beat Type | Robot Behavior |
|---|---|
| explanation | look at screen |
| question | look at learner |
| misconception correction | calm/neutral behavior |
| success | brief positive acknowledgment |
| high cognitive load | stillness, fewer motions |

## Why This Exists

Embodiment can improve engagement, but unmanaged motion distracts from learning.

## Failure Mode

Robot unavailable.

## Recovery

Suppress the robot channel without changing teaching content.

---

# 16. Assessment Hooks

Assessment hooks are explicit script objects.

## 16.1 Hook Types

```text
micro_check
diagnostic_probe
misconception_probe
representation_translation_check
worked_step_check
confidence_check
reflection_prompt
retention_marker
```

## 16.2 Required Fields

```text
target_concept
target_misconception
execution_mode
expected_response_type
correctness_rule
hint_chain_ref
state_update_intent
evidence_refs
telemetry_tags
branch_targets
idempotency_key
```

`execution_mode` is required:

- `local`: touch, multiple choice, drag, trace, or simple confirmation scored on-device
- `spoken`: learner utterance captured by device, sent through cloud STT/perception,
  graded, then returned as a branch decision

Spoken assessment is modeled as a checkpoint:

```text
pause script
-> capture learner utterance
-> cloud grade
-> emit idempotent outcome event
-> resume, branch, or end script
```

## Why This Exists

The system needs to know whether the learner merely heard content or demonstrated
understanding.

## Boundary

The Response Layer emits assessment events. The frozen Learner State system remains
the authority for applying state changes.

## Branching Limit

Within-script branching is limited to immediate remediation:

```text
one assessment hook
-> at most correct / incorrect / nonresponse branches
-> one remediation or hint level
-> then complete or return to the main learner loop
```

Misconception correction cannot become reachable until the diagnostic probe result
confirms the misconception.

---

# 17. Caching Strategy

Cache three different things separately.

## 17.1 Reusable Assets

Examples:

- authored scene specs
- static diagrams
- formula layouts
- crop metadata
- robot primitive maps

Keyed by:

```text
concept_id
representation_type
visual_shape
device_class
asset_version
```

## 17.2 Teaching Script Templates

Reusable pedagogical structures keyed by:

```text
pedagogical_action
concept_type
misconception_type
representation_gap_type
grade_level
```

## 17.3 Final Script Instances

Short-lived learner-specific instances keyed by:

```text
concept_id
pedagogical_action
representation_target
learner_state_bucket
device_class
curriculum_source_version
```

`learner_state_bucket` is a coarse discretization of only the dimensions that change
teaching:

```text
mastery_tier = low | medium | high
active_misconception = present | absent
grade_level
representation_gap_type
```

Do not key final script instances on the full evidence manifest hash; it varies too
often to protect latency. The template cache is the real fast path. The instance cache
is best-effort.

## 17.4 Cache Safety Rules

- Never serve a cached instructional script that assumes a misconception is resolved
  when the learner still has it active or unconfirmed.
- Never serve a cached script whose curriculum source version differs from the
  current source version.
- Revalidate cached claims when their evidence source version changes.
- Social and administrative script caches may ignore learner-state buckets, but must
  remain content-safe and age-appropriate.

## Why This Exists

Concept visuals are reusable, but complete Teaching Scripts are learner-specific.

---

# 18. Latency Strategy

## 18.0 Hard Latency Budget

The normal voice-first path must meet:

```text
TTFA <= 4 seconds
```

Any design path that cannot meet this budget is not acceptable for the live tutor
path. It may only run offline, in background preparation, or in an explicitly slower
mode.

## 18.1 Fast Path

Use:

```text
PDE-driven template spine + cached visual + first-beat commit + streamed speech fill
```

## 18.2 Medium Path

Use:

```text
bounded LLM planner stream + deterministic beat validation + cached assets
```

## 18.3 Slow Path

Use:

```text
offline or background visual generation only
```

Never block a live student turn on brand-new visual authoring unless explicitly
allowed.

## 18.4 Latency Tactics

- prefetch likely next concept assets
- cache device packages
- stream only after first validated segment
- commit the first beat, not the full script
- stream beats as structured records so a valid prefix can execute
- bound beats per planner call and continue in a second call when needed
- configure planner calls with no hidden thinking budget where supported
- keep first beat speech-only if visual package needs one extra moment
- use compact declarative scene specs
- avoid HD raster transfer
- use local deterministic rendering
- track `MAX_TOKENS` finish reasons and speech-only degradation rate

## Why This Exists

Coherence should not require unacceptable waiting.

---

# 19. Failure Recovery

## Principle

```text
When uncertain, reduce modality count.
```

## Failure Policies

| Failure | Recovery |
|---|---|
| script validation fails | regenerate once, then speech-only grounded fallback |
| visual spec invalid | suppress visual for affected beats |
| renderer fails | continue speech/text only |
| TTS fails | display text, pause for tap |
| touch unavailable | convert interaction to spoken question |
| robot unavailable | suppress robot behavior |
| network drop before package | use local fallback message |
| network drop during package execution | finish the current coherent move if cached, then pause safely |
| evidence insufficient | say less or ask clarifying question |
| planner stream truncates | execute validated prefix only, then close gracefully |
| `MAX_TOKENS` planner finish | log degradation, execute validated prefix or grounded speech-only fallback |
| duplicate event replay | deduplicate by assessment idempotency key |

## Minimum Coherent Unit

The system must not start a teaching move it cannot finish.

On Raspberry Pi, prefer packaging the whole turn when feasible. On ESP32 or other
streamed-package devices, package at least one complete teaching move before its speech
starts. If the network drops mid-turn, the device completes the cached move and then
uses a graceful pause rather than stopping mid-sentence.

## Why This Exists

The robot must never confidently teach inconsistent content.

---

# 20. Safety Architecture

The existing deterministic input safety gate on the learner utterance runs before the
Response Layer and remains unchanged. The Response Layer adds output and embodiment
safety after retrieval.

Response Layer safety has three layers.

## 20.1 Pedagogical Safety

Prevents:

- overloading learner
- revealing test answers
- correcting unconfirmed misconception too early
- skipping prerequisite bridge when required
- using visual when it harms learning

## 20.2 Content Safety

Prevents:

- unsupported claims
- off-curriculum explanations
- hallucinated formulas
- unsupported examples
- mismatch with NCERT evidence

## 20.3 Embodiment Safety

Prevents:

- unsafe motion
- excessive movement
- startling behavior
- robot behavior during sensitive correction
- motor commands outside approved primitive library

## Why This Exists

In an embodied teacher, bad content and bad behavior both harm learning trust.

---

# 21. Telemetry

Telemetry captures planned behavior, delivered behavior, and learner responses.

## 21.1 Events

```text
script_planned
script_validated
beat_started
visual_rendered
speech_started
speech_completed
touch_prompt_shown
touch_response_received
spoken_checkpoint_started
spoken_checkpoint_resolved
interrupt_detected
resume_decision_received
assessment_scored
robot_action_started
robot_action_failed
fallback_triggered
beat_completed
script_completed
```

## 21.2 Metrics

- planning latency
- validation failures
- render time
- TTS time
- beat drift
- visual usage rate
- visual suppression reasons
- touch response accuracy
- misconception probe outcomes
- learner engagement proxy
- fallback frequency
- TTFA
- planner `MAX_TOKENS` finish rate
- speech-only degradation rate
- duplicate event replay rate
- interrupt rate
- spoken-checkpoint round-trip latency

## Why This Exists

Without delivery telemetry, RL and learner-state updates learn from what the system
intended, not what the child experienced.

Telemetry is observational. Learner-state mutation remains single-writer through the
existing learner-state update path.

---

# 22. RL Integration

RL should not directly control modalities.

## 22.1 Safe RL Control Points

```text
choose among validated script templates
rank modality policies
adjust hint depth
choose assessment timing
choose visual vs no-visual when both are valid
adjust pacing
select encouragement frequency
```

## 22.2 RL Must Not

- generate facts
- bypass evidence validation
- directly render visuals
- directly control robot motors
- reveal answers
- override misconception probe-before-correct rules

## 22.3 Reward Signals

- assessment correctness
- reduced hint need
- representation gap closure
- misconception weakening
- productive struggle
- retention improvement
- low fallback rate
- low cognitive load indicators
- engagement without distraction

## 22.4 Recommended Mode

```text
shadow policy
-> constrained candidate ranking
-> online guarded policy
```

## Why This Exists

RL is useful for policy optimization, but unsafe as an unconstrained content
generator.

---

# 23. Future Extensibility

The architecture extends by adding new compilers, not by changing upstream learner
modules.

## 23.1 Future Additions

- camera-based attention signal
- handwriting input
- richer robot gestures
- collaborative classroom mode
- Science experiment simulations
- multilingual speech
- offline mode
- local small model for script repair
- adaptive animation pacing
- personalized voice style

## 23.2 Extension Contract

```text
New modality must consume TeachingScript beats.
New modality must not invent teaching content.
New modality must emit delivery telemetry.
New modality must degrade independently.
```

## Why This Exists

The Teaching Script remains stable while hardware and modalities evolve.

---

# 24. Migration From Raspberry Pi To ESP32-P4

## 24.1 Keep

- cloud planner
- Teaching Script schema
- evidence grounding
- visual benefit gate
- deterministic declarative rendering contract
- beat-level synchronization
- LVGL UI model
- telemetry event model

## 24.2 Change

| Raspberry Pi | ESP32-P4 |
|---|---|
| Pillow rendering possible | prefer LVGL-native rendering or pre-rendered lightweight frames |
| more RAM | strict scene size limits |
| Python runtime possible | C/C++ runtime package interpreter |
| local file paths | asset table / flash cache |
| larger frame buffers | reduced canvas, fewer elements |
| richer fallback | simpler deterministic fallback |

## 24.3 ESP32 Package Constraints

```text
max beats per package
max visual elements per beat
max text length per beat
max cached assets
no arbitrary fonts unless embedded
no large raster transfer during live turn
prefer vector-like LVGL primitives
```

These are transport and memory constraints, not pedagogy constraints. Beat limits must
never clamp the answer length. Longer scripts are split into sequential packages, and
package N+1 streams while package N plays.

The minimum coherent unit rule still applies: do not begin a teaching move until the
device has enough cached package data to finish that move.

## Why This Exists

ESP32 migration is feasible only if the device remains an executor, not a planner.

---

# 25. Implementation Roadmap

## Phase 1: Define Contracts

Deliver:

- `ResponseContext` schema
- `TeachingScript` schema
- beat schema
- bounded beat-DAG schema
- modality policy enum
- assessment hook schema
- device capability profile schema
- response kind enum
- idempotent outcome event schema

Why first: every later module depends on stable contracts.

## Phase 2: Build Script Planner Without New Visual Generation

Deliver:

- planner using retrieved evidence and existing scenes/crops
- visual benefit gate
- speech-only support
- script validator
- coherence tests
- template-first script spine selector
- first-beat commit path with TTFA <= 4 seconds
- claim-to-evidence consistency checks

Why: this fixes the root cause before adding more visual complexity.

## Phase 2.5: Add Authored Scene Adaptation Metadata

Deliver:

- scene `adaptation_contract`
- scene claim tags
- beat-to-claim mapping
- `as_authored`, `visual_only`, and `script_override` narration modes
- review pass for already-authored scenes

Why: existing scene narration cannot remain an independent runtime speech authority.

## Phase 3: Compile Existing Modalities From Script

Deliver:

- speech compiler
- visual compiler targeting current scene renderer
- LVGL text compiler
- basic robot primitive compiler
- touch prompt compiler
- unavailable-primitive dropping based on reported device profile

Why: this replaces answer-first flow while preserving the renderer.

## Phase 4: Device Script Runner

Deliver:

- beat executor
- modality acknowledgements
- fallback handling
- touch event capture
- telemetry events
- barge-in pause/duck/resume contract
- spoken-assessment checkpoint suspension and resume
- minimum coherent unit handling

Why: synchronization must be enforced at runtime.

## Phase 5: Assessment Integration

Deliver:

- micro-check hooks
- misconception probe hooks
- representation translation checks
- learner-state event emission
- idempotency keys
- single-writer turn-close application

Why: teaching effectiveness requires measured learning events.

## Phase 6: Cache And Latency Optimization

Deliver:

- asset cache
- script template cache
- package cache
- prefetch next likely visuals
- latency dashboards
- `MAX_TOKENS` and speech-only-degradation dashboards

Why: production tutoring must feel responsive.

## Phase 7: ESP32 Preparation

Deliver:

- constrained device profile
- package size limits
- LVGL-native visual interpreter
- reduced-memory scene subset
- offline fallback scripts
- sequential package streaming
- package-size limits that do not cap answer length

Why: migration should be a target profile change, not a redesign.

---

# 26. Final Architecture Summary

Replace:

```text
Brain
-> Generated Answer
-> Scene Selection
-> Speech
-> Visual
```

With:

```text
Frozen Learner/Retrieval Outputs
-> Response Context
-> Streaming Teaching Script
-> First-Beat Validation and Commit
-> Beat-Level Modality Compilation
-> Device Execution Packages
-> Beat-Synchronized Runtime with Checkpoints
-> Telemetry and Assessment Events
```

The key architectural decision is:

```text
The Teaching Script is the only source of instructional truth.
```

Speech, visuals, robot behavior, touch, animation, text, and assessment are all
compiled from it. Visuals are optional, justified, evidence-bound, and deterministic.
If coherence cannot be guaranteed, the system teaches with fewer modalities rather
than risking contradiction.

The final design is script-first but not whole-script-blocking. It preserves the
voice-first TTFA target by committing the first valid beat, supports bounded
assessment branching, treats spoken answers as cloud checkpoints, and keeps learner
state mutation in the existing single-writer path.
