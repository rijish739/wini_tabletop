# Wini Tutor Runtime

The Wini Tutor Runtime turns a learner interaction into a pedagogically grounded response and an evidence-backed learner-state transition.

## Language

**Turn**:
One learner input carried through interpretation, pedagogy, response production, and the resulting committed state transition.
_Avoid_: Request, loop iteration

**Turn Coordinator**:
The component that sequences a Turn across Feature Modules while leaving feature policy and feature-specific state ownership to those modules.
_Avoid_: Tutor loop, god object

**Feature Module**:
An independently owned tutoring capability with explicit inputs, outputs, invariants, and verification. A Feature Module participates in a Turn without controlling the entire Turn.
_Avoid_: Helper, section, phase file

**Turn Input**:
The immutable learner interaction, identity, device capabilities, budgets, and any trusted precomputed observations available when a Turn begins.
_Avoid_: Request dictionary, arguments bag

**Turn Context**:
The transient record of typed observations, decisions, and artifacts accumulated while coordinating one Turn. It is not durable learner history.
_Avoid_: Session dictionary, scratch state

**Module Outcome**:
A Feature Module's explicit result, including its produced artifacts and proposed state changes.
_Avoid_: Return dictionary, side effect

**Turn Result**:
The complete externally relevant outcome of a Turn after its state changes have been committed.
_Avoid_: Response dictionary, output blob

**Learner State**:
The durable, evidence-backed record of a learner's demonstrated knowledge and learning history.
_Avoid_: Session, context

**Session State**:
The continuity needed across nearby Turns, such as the active topic, mode, pending interaction, and recent conversation.
_Avoid_: Learner State, global dictionary

## Feature responsibilities

**Interaction Control**:
The capability that governs whether and how an interaction enters, continues, redirects, or ends a tutoring session.
_Avoid_: Front door, routing helpers

**Perception**:
The capability that derives the learner's apparent intent, cognitive signals, and subject concept from a Turn Input.
_Avoid_: Classification step, analyzer call

**Pedagogy**:
The capability that selects the teaching strategy, learning mode, and pacing appropriate to the learner's current situation.
_Avoid_: Rules block, mode controller

**Assessment and Evidence**:
The capability that governs assessable items, grades learner attempts, and records evidence-backed learning outcomes.
_Avoid_: Grader, pending check handling

**Retrieval**:
The capability that assembles a grounded evidence manifest suitable for the selected pedagogical strategy.
_Avoid_: Query helper, chunk search

**Response Planning**:
The capability that turns a pedagogical decision and evidence manifest into an approved teaching and modality plan.
_Avoid_: Response Layer, visual gate

**Response Generation**:
The capability that produces the learner-facing verbal response from an approved response plan and its grounded evidence.
_Avoid_: LLM call, answer helper

**Presentation**:
The capability that realizes approved speech, visual, and device intentions and reports what was actually presented.
_Avoid_: Display code, Board Buddy path

**State and Persistence**:
The capability that owns Learner State and Session State integrity, applies authorized changes, and commits them at Turn boundaries.
_Avoid_: State dictionary, save helper

## Runtime integrity

**Failure Signal**:
A typed report from a Feature Module describing a detected failure, its context, and whether the module can still produce a valid outcome. It informs runtime policy but does not select the recovery action.
_Avoid_: Exception swallowing, module fallback decision

**Provisional Output**:
Speech or presentation emitted before the Turn's state changes have been committed. It is observable by the learner but cannot confirm learning progress.
_Avoid_: Turn Result, committed response

**Realization Receipt**:
Presentation's report of what was actually delivered successfully to the learner during a Turn.
_Avoid_: Intended display, response plan

**Turn Commit**:
The atomic acceptance of the authorized Learner State and Session State changes produced by a Turn.
_Avoid_: Save call, streamed completion

**Baseline Split**:
The initial behavior-preserving conversion of the canonical runtime into Feature Modules, completed by one coordinated effort before parallel feature ownership begins.
_Avoid_: Rewrite, feature improvement, parallel development phase

**Ownership Handoff**:
The point after the Baseline Split passes its verification gates and Feature Modules may be assigned to independent development teams.
_Avoid_: Initial file split, partial extraction
