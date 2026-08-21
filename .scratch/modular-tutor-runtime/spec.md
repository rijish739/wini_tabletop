# Modular Tutor Runtime Specification

Status: ready-for-agent

## Problem Statement

The Wini Tutor Runtime currently concentrates most Turn behavior inside one large orchestration implementation and also exists in multiple divergent runtime trees. A developer changing perception, assessment, pedagogy, retrieval, response generation, presentation, or state handling must understand and edit the same shared flow. Feature policy, sequencing, state mutation, model transport, presentation effects, and failure handling are interleaved, so independent verification is difficult and changes by multiple developers would collide or silently alter another capability.

The team needs a behavior-preserving Baseline Split that makes each tutoring capability independently understandable, changeable, and verifiable. The split must not become a feature rewrite, introduce new network boundaries, change prompts or pedagogy, weaken evidence integrity, or allow several implementations to remain behavioral sources of truth. Parallel development begins only after the canonical runtime is modular, equivalent to its frozen baseline, and ready for an explicit Ownership Handoff.

## Solution

Convert the canonical cloud tutor runtime into nine deep, in-process Feature Modules coordinated by a small Turn Coordinator. Each Module presents one small Interface, owns its feature policy and semantic state, returns typed Module Outcomes and Failure Signals, and is tested through the same seam used by the coordinator. Modules never invoke another Module's implementation; the coordinator passes typed outcomes through a deterministic Turn sequence.

State and Persistence provides immutable, capability-scoped views and one Turn transaction. Feature Modules propose typed State Changes, later Modules may observe the validated working projection, and only State and Persistence performs the atomic Turn Commit. Presentation reports what was actually delivered through a Realization Receipt. Streamed speech and visual events remain Provisional Output; only a committed Turn Result is authoritative, and an assessment may be armed only after successful realization.

The Baseline Split is performed by one coordinated development effort. It starts by freezing observable behavior and test fixtures, establishes contracts and state ownership, extracts capabilities incrementally behind a compatibility façade, proves equivalence after each checkpoint, consolidates the runtime into one behavioral source of truth, deletes the experimental duplicate runtime tree after a reviewed disposition, and then opens the Modules to multiple owners at Ownership Handoff.

## User Stories

1. As a tutor-runtime developer, I want each tutoring capability behind a small Interface, so that I can understand and change one capability without reading the entire Turn implementation.
2. As a tutor-runtime developer, I want the Turn Coordinator to contain sequencing rather than feature policy, so that orchestration changes and teaching-behavior changes remain distinct.
3. As a Module owner, I want my Module to own its implementation and invariants, so that fixes remain local and apply consistently to every caller.
4. As a Module owner, I want one public façade for my Module, so that callers and tests do not depend on internal files.
5. As a Module owner, I want typed inputs and Module Outcomes, so that integration mistakes are visible before production.
6. As a Module owner, I want to emit a typed Failure Signal without choosing global recovery, so that I can report capability-specific facts while runtime policy remains consistent.
7. As a runtime integrator, I want Feature Modules to avoid importing one another's implementations, so that the dependency graph remains acyclic.
8. As a runtime integrator, I want Module Outcomes passed explicitly through the Turn Context, so that information flow is inspectable and testable.
9. As a runtime integrator, I want concurrency owned by the Turn Coordinator, so that parallel perception, grading, or streaming cannot create hidden Module-to-Module coordination.
10. As a runtime integrator, I want the logical Turn phases to remain deterministic even when selected work runs concurrently, so that state and failure behavior are predictable.
11. As an Interaction Control owner, I want session admission, continuation, topic redirection, non-learning routing, and termination to have one owner, so that session lifecycle rules do not leak across Modules.
12. As a Perception owner, I want learner intent, cognitive signals, and concept observations behind the Perception Interface, so that perception backends can be tested without invoking the entire tutor.
13. As a Pedagogy owner, I want strategy, mode, practice/test planning, and pacing decisions localized, so that teaching policy can later evolve independently.
14. As an Assessment and Evidence owner, I want item eligibility, assessment arming, grading, and evidence projection governed together, so that evidence integrity has one authoritative seam.
15. As an Assessment and Evidence owner, I want prior-attempt grading separated from the decision to arm a new assessment, so that a Turn cannot confuse old and new evidence.
16. As an Assessment and Evidence owner, I want new assessments armed only after successful realization, so that the learner is never graded on a question that was not actually delivered.
17. As a Retrieval owner, I want grounded manifest construction behind one Interface, so that ranking and cohesion changes do not leak into orchestration or generation.
18. As a Response Planning owner, I want teaching and modality intent decided before response generation, so that presentation is pedagogically justified rather than inferred from incidental output.
19. As a Response Generation owner, I want learner-facing answer generation separated from model transport, so that prompts and output validation remain feature policy while client lifecycle remains infrastructure.
20. As a Presentation owner, I want speech, crop, authored visual, and device realization behind one Interface, so that the rest of the runtime consumes a truthful Realization Receipt rather than assuming success.
21. As a State and Persistence owner, I want all durable writes applied through one transaction, so that Learner State, Session State, and evidence remain consistent.
22. As a State and Persistence owner, I want each Module to receive only its immutable typed view, so that raw shared-dictionary mutation cannot bypass invariants.
23. As a State and Persistence owner, I want semantic ownership assigned for every state field, so that two Modules cannot compete to define the same state transition.
24. As an infrastructure maintainer, I want model clients, deadlines, retries, streaming mechanics, and metrics behind one Model Gateway, so that expensive clients are constructed once and failure behavior is observable.
25. As an infrastructure maintainer, I want feature prompts and schemas owned by the consuming Module, so that the Model Gateway does not become a new policy monolith.
26. As a server caller, I want the existing Turn response contract preserved through a compatibility façade, so that HTTP, voice, UI, and scripted callers do not migrate during extraction.
27. As a streaming client, I want early speech and visual events explicitly identified as Provisional Output, so that I do not mistake them for committed learning progress.
28. As a streaming client, I want a terminal error if Turn Commit fails after provisional output began, so that the client does not present an uncommitted Turn as successful.
29. As a learner, I want tutoring behavior to remain unchanged during modularization, so that architecture work does not unexpectedly alter teaching quality.
30. As a learner, I want safety, identity, state, and assessment-integrity failures to fail closed, so that the system never fabricates progress or applies another learner's state.
31. As a learner, I want optional visual or filler failures to degrade explicitly to a valid response, so that a nonessential capability does not unnecessarily end the Turn.
32. As a learner, I want retrieval or generation failure to produce only a safe, non-assessing fallback, so that an ungrounded response cannot affect mastery.
33. As an operator, I want the Runtime Supervisor to expose `STARTING`, `READY`, `DEGRADED`, and `UNAVAILABLE`, so that service health reflects repeated and initialization failures rather than only process liveness.
34. As an operator, I want Failure Signals to include capability, phase, severity, recoverability, and cause, so that degraded behavior is diagnosable.
35. As an operator, I want steady-state model-call counts and model-client construction measured, so that the split does not increase cloud cost or latency invisibly.
36. As an operator, I want startup latency, non-model Turn overhead, and time-to-first-audio tracked separately, so that regressions are attributable.
37. As a tester, I want a frozen corpus of representative Turn Inputs and sanitized state fixtures, so that old and modular runtimes can be compared deterministically.
38. As a tester, I want recorded model-boundary responses replayed offline, so that normal verification is stable, fast, private, and non-billed.
39. As a tester, I want external Turn Results, state transitions, evidence events, assessment lifecycle, manifests, and presentation decisions compared, so that equivalence covers behavior beyond answer text.
40. As a tester, I want nondeterministic learner-facing wording normalized only by explicit rules, so that equivalence does not hide structural regressions.
41. As a tester, I want each Module tested through its public Interface, so that tests survive internal refactoring.
42. As a tester, I want cross-Module scenario tests through the compatibility façade, so that sequencing and integration remain covered at the highest stable seam.
43. As a tester, I want architecture tests for forbidden imports and direct state writes, so that module independence is continuously enforced.
44. As a reviewer, I want known non-integrity defects documented and preserved during the Baseline Split, so that fixes do not become unreviewed scope expansion.
45. As a reviewer, I want safety, identity, state-integrity, and assessment-integrity defects treated as explicit exceptions to preservation, so that the baseline is not used to perpetuate dangerous behavior.
46. As the Baseline Split implementer, I want the extraction performed sequentially by one coordinated effort, so that multiple developers do not collide before seams stabilize.
47. As the Baseline Split implementer, I want the application runnable and reversible after every checkpoint, so that a failed extraction can be isolated and rolled back safely.
48. As the Baseline Split implementer, I want only boundary-establishing mechanical cleanup allowed, so that unrelated rewrites do not contaminate equivalence evidence.
49. As a repository maintainer, I want one canonical behavioral source, so that fixes do not need to be copied among divergent runtime trees.
50. As a repository maintainer, I want the experimental duplicate runtime inventoried before deletion, so that active callers or unique required assets are not lost.
51. As a repository maintainer, I want every duplicate-only item explicitly migrated, adapted, archived, or discarded, so that deletion is reviewable rather than speculative.
52. As a repository maintainer, I want remaining root entrypoints to be thin adapters only, so that compatibility does not recreate a second implementation.
53. As a future Module owner, I want a concise Module document describing its Interface, invariants, dependencies, failures, and test commands, so that I can work independently after handoff.
54. As a future Module owner, I want a primary and backup owner recorded, so that review responsibility is clear.
55. As a contract producer, I want affected consumers to review Interface changes, so that independent development does not break downstream assumptions.
56. As a runtime integration owner, I want coordinator and lifecycle-contract changes routed through integration review, so that cross-Module behavior remains coherent.
57. As an engineering lead, I want objective Ownership Handoff gates, so that parallel development begins only after the runtime is actually modular and verified.
58. As an engineering lead, I want mandatory architecture documentation updated from measured results, so that the written system and deployed system remain consistent.

## Implementation Decisions

- The canonical cloud tutor runtime becomes the only behavioral source of truth.
- The Baseline Split is a behavior-preserving architectural change performed by one coordinated implementation effort. Parallel Module development is prohibited until Ownership Handoff.
- The runtime remains one in-process deployment. No Feature Module introduces an HTTP, RPC, queue, or other network boundary.
- The agreed Feature Modules are Interaction Control, Perception, Pedagogy, Assessment and Evidence, Retrieval, Response Planning, Response Generation, Presentation, and State and Persistence.
- A deliberately small runtime layer owns the Turn Coordinator, lifecycle-wide contracts, per-Turn failure policy, and Runtime Supervisor. It owns no tutoring feature policy.
- Model transport is shared infrastructure. The Model Gateway owns client construction, hard deadlines, retry mechanics where safe, streaming transport, call metrics, and test adapters. Feature Modules retain ownership of prompts, schemas, validation, and feature-specific fallbacks.
- Each Feature Module is a deep Module with exactly one public Interface. Internal seams may exist for its implementation and tests but are not exposed to the coordinator.
- A proposed Module that merely forwards most of its caller-visible complexity is rejected or deepened. Removing a valid Module would redistribute meaningful behavior across callers.
- The Turn Coordinator imports only Feature Module Interfaces, lifecycle contracts, and infrastructure ports. Feature Modules do not import another Feature Module's implementation.
- Lifecycle-wide contracts cover Turn Input, Turn Context, Turn Result, Module Outcome conventions, State Change, Failure Signal, Provisional Output, Realization Receipt, and Turn Commit.
- Each Feature Module owns the contracts specific to its public Interface. Shared lifecycle contracts must not absorb feature-specific schemas and become a new monolith.
- The Turn Input is immutable and contains the learner interaction, bound identity, device capabilities, budgets, and trusted precomputed observations.
- The Turn Context is a transient typed working record for one Turn. It is not a general mutable dictionary and is not durable learner history.
- The logical Turn sequence is: interaction admission and routing; perception plus prior-attempt grading; working-state projection and pedagogical decision; grounded retrieval; response planning; response generation; presentation and realization reporting; assessment arming, Turn Commit, and final Turn Result.
- Perception and grading of a prior assessment may execute concurrently because both depend on the Turn Input and the starting snapshot. Their outcomes are joined before pedagogical decision-making. The coordinator alone owns this concurrency.
- Interaction Control owns session admission, non-learning routing, topic continuity, redirection, conversation continuity, and lifecycle termination.
- Perception owns observations of intent, cognitive signals, safety additions, and subject concept. It proposes any permitted soft-state changes rather than writing state.
- Pedagogy owns teaching action, mode, practice/test plan, pacing, and progression policy. It decides whether assessment is pedagogically appropriate but does not grade or write evidence.
- Assessment and Evidence owns verified items, pending-assessment lifecycle, grading, assessment validity, idempotency, and durable evidence projection. It evaluates a prior attempt early in the Turn and finalizes a newly planned assessment only after realization.
- Retrieval owns grounded evidence-manifest assembly, including prerequisite bridges, misconception evidence, ranking, served-history filtering, and cohesion behavior.
- Response Planning owns the approved teaching sequence and modality intent. It decides whether a visual or assessment presentation is justified but does not assume either was realized.
- Response Generation owns only the learner-facing verbal answer from the approved response plan and grounded manifest.
- Presentation owns speech/display/device realization, crop or authored-visual execution, grounding validation for presented artifacts, and the Realization Receipt.
- State and Persistence owns state schema integrity, capability-scoped immutable views, working projection, State Change validation, idempotent application, persistence adapters, and the atomic Turn Commit.
- Semantic ownership is exclusive. Interaction Control owns interaction-continuity state; Pedagogy owns mode and learning-plan state; Assessment and Evidence owns pending assessments and evidence semantics. Other Modules request changes through typed State Changes.
- Later Modules may read the validated working projection after earlier Module Outcomes have been applied in memory. No Feature Module writes durable state directly.
- Evidence remains append-only and idempotent. The evidence writer and assessment arming path remain single-writer invariants.
- Presentation produces a Realization Receipt describing what was actually delivered. Intended output is insufficient to arm an assessment or claim presentation success.
- Speech and visual events emitted before Turn Commit are Provisional Output. They may improve latency but cannot confirm state or learning progress.
- A newly posed assessment is armed only when its verified item and successful Realization Receipt agree on what the learner received.
- The final Turn Result is produced only after Turn Commit. A commit failure after streaming begins emits a terminal error and makes no mastery, evidence, mode, or assessment-success claim.
- Feature Modules detect local failures and emit Failure Signals. A Module may state whether it still has a valid outcome but may not select runtime recovery policy or transition service health directly.
- The Turn Coordinator maps current-Turn Failure Signals to continue, explicit degradation, safe non-assessing fallback, retry where idempotent and bounded, or fail-closed termination.
- The Runtime Supervisor aggregates initialization and repeated cross-Turn failures into `STARTING`, `READY`, `DEGRADED`, or `UNAVAILABLE` service state.
- Identity mismatch, corrupt or incompatible state, safety-integrity failure, assessment-integrity failure, and Turn Commit failure fail closed.
- Optional visual, filler, and diagnostic failures may degrade explicitly when the remaining outcome is valid. The Turn Result records degradation reasons.
- Retrieval or Response Generation failure may only produce a safe non-assessing fallback with no mastery or evidence change. It may not generate an ungrounded assessed response.
- A Perception backend failure may use the already-established deterministic gates, inherited concept, and neutral valid signals only when those produce a contract-valid outcome; the degradation is observable.
- Broad exception swallowing is not a valid recovery policy. Existing defensive catches are replaced or wrapped incrementally with typed Failure Signals while preserving externally observable behavior.
- Existing server, voice, UI, and scripted callers retain the established Turn dictionary/JSON behavior through a temporary `TutorLoop.turn()` compatibility façade.
- The compatibility façade delegates to the typed Turn Coordinator and serializes Turn Result. It contains no feature policy, state mutation, prompt, retrieval, or presentation implementation.
- Required legacy entrypoints outside the canonical runtime may remain only as thin adapters. They contain no copied feature implementation.
- Before extraction, the implementer inventories canonical caller expectations and freezes a representative compatibility corpus with sanitized state fixtures and recorded model-boundary responses.
- Equivalence compares Turn Result fields, state transitions, evidence events, assessment lifecycle, grounded manifests, presentation decisions, streaming events, and failure/degradation metadata. Exact model wording is compared only under approved normalization rules.
- Known defects are preserved through the Baseline Split unless preservation would violate safety, identity, state integrity, or assessment integrity. Noncritical fixes become separate post-handoff work.
- The migration proceeds in stable checkpoints: behavior inventory and characterization; lifecycle contracts, state façade, and failure framework; lower-coupling Feature Module extraction; separation of response planning from presentation; consolidation of assessment and evidence; extraction of pedagogy and interaction control; activation of the new coordinator; compatibility-façade reduction; duplicate-tree disposition and deletion; final verification and Ownership Handoff.
- Although lower-coupling Modules can be logically prepared as separate checkpoints, the Baseline Split is not assigned to multiple independent developers. One coordinated effort owns the full split until handoff.
- Only mechanical changes required to create seams are allowed during the Baseline Split: imports, names, adapters, typed contracts, dependency injection, and test relocation. Prompt, model, pedagogy, feature, optimization, and unrelated cleanup changes are deferred.
- The application remains runnable after every checkpoint. Each checkpoint records the old seam, new seam, equivalence evidence, state compatibility, activation mechanism, and rollback action.
- The experimental duplicate runtime is inventoried before deletion. Every unique caller, behavior, test, asset, or operational script receives a reviewed disposition: migrate, adapt, archive outside the runtime, or discard as obsolete.
- Only behavior required by an active caller or current production contract migrates automatically. Experiments are not promoted merely because they exist in the duplicate tree.
- Ownership Handoff occurs only after the equivalence suite, architecture rules, state invariants, duplicate deletion, compatibility façade, performance gates, Module tests, cross-Module scenarios, bounded live smoke checks, and documentation checks pass.
- After handoff, every Feature Module has a primary and backup owner. Interface changes require affected producer and consumer review; coordinator or lifecycle-contract changes require runtime integration review.
- Each Feature Module includes concise maintainer documentation covering its Interface, invariants, semantic state ownership, Failure Signals, approved dependencies, adapters, and verification commands.
- Automated architecture rules reject forbidden cross-Module implementation imports, raw state mutation outside State and Persistence, duplicate feature implementations, and feature policy in the Turn Coordinator.
- Baseline performance is measured before extraction. The split adds no steady-state model calls, model-client constructions, or network boundaries. Non-model p95 Turn overhead must remain within ten percent of the measured baseline; startup and time-to-first-audio are measured separately.
- Architecture documentation, measured build status, dataset/model reports where affected, and the work log are updated together under the repository's lockstep documentation rule. Numbers are remeasured rather than copied or guessed.

## Testing Decisions

- Good tests assert observable behavior through a Module's public Interface or the highest end-to-end compatibility seam. They do not assert private helper calls, internal file layout, or incidental intermediate structures.
- The highest system seam is the existing Turn compatibility façade. It verifies the complete learner-visible result and committed state behavior without requiring callers to understand the new coordinator.
- Each Feature Module's one public Interface is its isolated test seam. Internal seams are private and exist only when the implementation genuinely has multiple adapters or substitutable dependencies.
- Test dependencies are accepted rather than constructed internally. True external model and cloud dependencies use injected ports with production and deterministic test adapters.
- Old tests that only lock shallow implementation structure are replaced once equivalent behavior is covered at the deep Module Interface. Valuable invariant and regression cases are retained and moved to the appropriate Interface seam.
- A canonical behavior inventory precedes extraction. It records active callers, external response fields, streaming order, state transitions, evidence events, assessment lifecycle, manifests, presentation decisions, failure behavior, and measured performance.
- The frozen equivalence corpus includes learning, non-learning, safety, nonsense, topic shifts, acknowledgements, clarification, learner-supplied problems, hints, practice, tests, pending assessment attempts, non-attempts, misconception probes, bridges, HOPE updates, visual and speech-only turns, presentation degradation, session termination, and commit failure scenarios.
- State fixtures are sanitized and contain representative cold-start, active-session, pending-assessment, misconception, mastery, mode, practice, test, and migration states.
- Model-boundary responses are recorded once and replayed offline. Fixtures retain schemas, finish states, timeouts, and relevant metadata while excluding credentials and learner-sensitive data.
- Equivalence assertions cover typed Turn Result and compatibility serialization, not only answer text. They compare semantic state changes, evidence idempotency keys, assessment arming/voiding, manifest provenance, realization status, and degradation reasons.
- Any normalization of nondeterministic generated wording is explicit, narrowly scoped, and tested. It may not discard numbers, actions, assessment content, evidence references, presentation decisions, or state-affecting meaning.
- Interaction Control tests cover admission, non-learning routing, pending shifts, mode stops, topic continuity, session termination, and ownership of conversation-continuity changes.
- Perception tests cover deterministic front gates, structured observations, inherited-concept fallback, neutral degraded outcomes, schema validation, timeout reporting, and absence of direct state mutation.
- Pedagogy tests cover rule priority, modes, practice/test planning, pacing, acknowledgement handling, clarification, learner-problem handling, and decisions based on the working state projection.
- Assessment and Evidence tests cover verified-item eligibility, prior-attempt grading, non-attempt preservation, assessment arming after realization, voiding, single-writer enforcement, idempotency, append-only events, replay, migration, and projection correctness.
- Retrieval tests cover bridge precedence, probe-before-correction evidence, need modes, ranking, served-history filtering, cohesion, provenance manifests, and safe failure without assessed output.
- Response Planning tests cover pedagogical sequence, modality intent, visual-benefit decisions, assessment proposal, grounding constraints, device capability constraints, and invalid-plan rejection.
- Response Generation tests cover grounded prompt construction, action-specific response policy, answer budgets, streaming sentence release, transport-independent behavior, and safe non-assessing fallback.
- Presentation tests cover speech-only realization, retrieved and authored visuals, grounding validation, compilation, device capability differences, interruption, partial realization, and accurate Realization Receipts.
- State and Persistence tests cover immutable views, ownership validation, conflicting State Changes, working projection visibility, atomic Turn Commit, rollback, local and remote adapters, identity binding, schema migration, and commit failure.
- Turn Coordinator scenario tests verify logical phase ordering, permitted parallel perception/grading, join-before-pedagogy, failure-matrix decisions, provisional streaming, realization-before-arming, commit-before-final-result, and terminal error after failed commit.
- Runtime Supervisor tests feed repeated and initialization Failure Signals and assert only observable `STARTING`, `READY`, `DEGRADED`, and `UNAVAILABLE` transitions.
- Architecture tests parse imports and state access to reject Feature Module implementation dependencies, forbidden raw state mutation, feature code in compatibility adapters, and duplicate behavioral sources.
- Prior art includes the existing evidence-ledger single-writer and idempotency checks, assessment-realization checks, deterministic pedagogy-mode tests, perception gate tests, response-plan validation tests, presentation/Board rendering tests, and end-to-end Turn smoke tests. These are moved or adapted to the approved seams rather than discarded wholesale.
- Normal test runs are offline, deterministic, and non-billed. They must not construct live cloud clients or depend on network availability.
- A separate bounded live-cloud smoke suite verifies authentication, model schemas, hard timeouts, model-call counts, streaming transport, and representative end-to-end integration. It does not require exact generated wording.
- Performance verification records baseline and modular results for startup, non-model p95 Turn overhead, time-to-first-audio, total Turn latency, model-call count, model-client construction count, and presentation-selection overhead.
- The split fails its performance gate if it introduces a new network boundary, increases steady-state model calls or client constructions, or exceeds the accepted non-model p95 tolerance without explicit review.
- Duplicate-tree deletion is tested by verifying active callers resolve to the canonical runtime, required assets exist in their reviewed destination, no duplicate feature implementation remains, and obsolete deployment paths are absent.
- Ownership Handoff evidence is one reviewed report linking the equivalence results, Module test results, architecture checks, live smoke results, performance comparison, duplicate disposition, documentation updates, and owner matrix.

## Out of Scope

- New tutoring features or changes to existing learner-facing behavior during the Baseline Split.
- Prompt revisions, model migration, new model calls, or changes to pedagogical policy.
- Performance optimization beyond preventing regressions introduced by the split.
- Fixing known noncritical defects during modularization.
- Parallel Feature Module development before Ownership Handoff.
- Separately deployed Modules, microservices, new queues, or other network boundaries.
- New persistence technology, identity provider, authentication system, or device protocol.
- Dataset relabeling, model retraining, knowledge-store rebuilding, or curriculum changes.
- Redesigning the external Turn JSON/streaming contract while the compatibility façade is required.
- Automatically promoting experiments found in the duplicate runtime.
- Post-handoff feature work, cleanup, and improvement backlog.
- Migrating the local specification and decision map to a hosted issue tracker before repository identity and authenticated tooling are confirmed.

## Further Notes

- This specification uses the Wini Tutor Runtime glossary: Turn, Turn Coordinator, Feature Module, Turn Input, Turn Context, Module Outcome, Turn Result, Learner State, Session State, Failure Signal, Provisional Output, Realization Receipt, Turn Commit, Baseline Split, and Ownership Handoff.
- The specification deliberately favors a few high, deep seams over many helper-level seams. The compatibility façade is the primary end-to-end seam; each Feature Module Interface is the only additional externally testable seam required for independent ownership.
- The State and Persistence Interface and Model Gateway are genuine seams because each has production and test adapters. Internal pure computation remains inside its owning deep Module rather than gaining unnecessary ports.
- The Baseline Split is complete only when deleting a Feature Module would redistribute meaningful behavior across callers, while deleting the Turn Coordinator would redistribute only sequencing.
- The local Wayfinder map remains the decision and dependency index for unresolved implementation-detail investigations. This specification is the implementation-facing synthesis and is triaged `ready-for-agent`.
