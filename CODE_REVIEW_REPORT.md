# Modular Tutor Runtime — Implementation Review

## Review scope

Reviewed the effective modular-runtime implementation against `origin/main` plus the current worktree, with the governing materials in `.scratch/modular-tutor-runtime/spec.md`, `map.md`, and tickets 01–28. The branch is three commits ahead of `origin/main` and the worktree also contains uncommitted runtime, handoff, and documentation changes.

## Executive conclusion

The work establishes useful typed seams and several passing unit suites, but it is not yet a completed Baseline Split or Ownership Handoff. The central Turn path still executes the legacy monolith, the coordinator does not own a single atomic state transaction, Presentation is not wired into production, and the duplicate runtime remains. The handoff verifier correctly reports `blocked`.

## Findings

### F1 — Critical: the canonical Turn still runs the legacy monolith

`TutorLoop` constructs the façade with `turn_behavior=self._canonical_turn` in `cloud_run_service/tutor_loop.py:1869-1885`. `TurnRuntime._execute()` then calls that callback at `cloud_run_service/runtime/turn_runtime.py:347-359`. This means the new modules provide partial pre/post processing, but the legacy implementation remains the behavioral source of truth. This fails tickets 26 and 27 and the spec requirement that the coordinator route every Turn through the nine Feature Module Interfaces.

Pending: extract the remaining seven phases, remove the legacy behavior callback/adapter, and reduce the compatibility façade to input construction and result serialization only.

### F2 — Critical: state changes are not applied through one Turn transaction

`TurnRuntime._execute()` batches some outcomes at `cloud_run_service/runtime/turn_runtime.py:302-315`, but `_apply_state_changes()` creates and publishes a new projection each time at `cloud_run_service/runtime/turn_runtime.py:459-479`. Continuity changes are applied in a second transaction at lines 360–365, after the legacy callback has already mutated state directly. Changes from response planning, generation, and Presentation are not included in the batch at all. This permits cross-module overwrites and silently drops future module state changes, contrary to ticket 25 and the atomic-commit contract.

Pending: create one working projection at Turn start, apply every accepted module change to it, validate conflicts/invariants once, and commit exactly once through State and Persistence.

### F3 — High: modules still receive raw mutable shared state

`TurnRuntime` reads `self._state.data` directly throughout `cloud_run_service/runtime/turn_runtime.py:52-249`, and the legacy code continues direct mutation in `cloud_run_service/learner_state.py:95-105` and `cloud_run_service/tutor_loop.py:1276-1280`. The state ownership matrix does not cover all fields being written by the runtime; for example, pacing writes `explaining_concept`, `expected_response_type`, `last_spoken_answer`, `last_explanation_summary`, `last_voice_latency_ms`, and `explanation_step` in `cloud_run_service/pacing/pacing_controller.py:178-188`, but those fields are absent from `cloud_run_service/state_and_persistence/ownership.py:26-66`.

Pending: complete the ownership matrix, issue capability-scoped immutable views to every module, prohibit raw `.data` writes in production paths, and add architecture checks for direct mutation.

### F4 — High: required concurrency and phase ordering are not implemented

The spec permits perception and prior-attempt grading to run concurrently and requires admission/routing before the perception-plus-grading phase. `TurnCoordinator.run()` calls perception first at `cloud_run_service/runtime/coordinator.py:180-204`, then evaluates assessment at lines 223–227; there is no coordinator-owned concurrency or join barrier. This leaves ticket 13 and the sequencing requirements only partially implemented.

Pending: perform admission/routing first, run only the explicitly permitted work concurrently, join both outcomes, then project state before pedagogy.

### F5 — High: Presentation is not production-wired and cannot prove delivery

The façade does not pass a `Presentation` implementation (`cloud_run_service/tutor_loop.py:1875-1931`), so the coordinator never invokes the new Presentation interface in the canonical path. Even when supplied in tests, the coordinator creates `PresentationRequest` without speech/display callbacks, display items, authored scenes, or device profile at `cloud_run_service/runtime/coordinator.py:317-323`. The runtime consequently synthesizes a `PARTIAL` receipt when no receipt is supplied at `cloud_run_service/runtime/turn_runtime.py:417-431`. This prevents truthful end-to-end realization and assessment arming, leaving tickets 22–24 incomplete.

Pending: wire retrieved and authored realization through the interface, pass actual delivery ports/events, preserve provisional output, and arm only after a matching successful receipt.

### F6 — High: the Model Gateway extraction is not complete

The production façade constructs `VertexModelGateway()` directly at `cloud_run_service/tutor_loop.py:1923-1928`, while the core Turn still calls the legacy generation behavior. There is no demonstrated deterministic replay adapter, bounded gateway-level retry/deadline policy, or end-to-end model-call/client-construction equivalence evidence. Ticket 21 remains unchecked and the oracle reports only 7 of 32 expected model-boundary calls replayable.

Pending: make Response Generation own prompts/validation/fallbacks, make the gateway own transport lifecycle and metrics, add replay and timeout tests, and remove model transport from the legacy path.

### F7 — Medium: assessment arming is implemented as a seam but not end-to-end

`AssessmentEvidence.arm_after_realization()` correctly rejects missing or non-realized receipts at `cloud_run_service/assessment_evidence/interface.py:168-243`, but the production coordinator has no Presentation outcome to provide, and the runtime still delegates response behavior to the legacy callback. The implementation therefore tests the isolated contract without proving the required delivered-question lifecycle through the compatibility façade.

Pending: integrate the arming outcome into the single projection/commit path and verify spoken, displayed, mismatched, partial, interrupted, duplicate, and degraded scenarios end to end.

### F8 — Medium: duplicate-runtime consolidation has not happened

`cloud_workspace_v8` still exists. The handoff verifier reports `duplicate-runtime: blocked`, and active callers/tests remain under that tree. This directly blocks tickets 06, 07, 12, and 27; thin root adapters alone do not satisfy deletion and caller-disposition requirements.

Pending: inventory every duplicate caller/asset/test/deployment path, record migrate/adapt/archive/discard decisions, migrate required assets, verify active callers, then delete the duplicate tree.

### F9 — Medium: verification evidence is incomplete and environment-blocked

The generated handoff report passes oracle self-validation, architecture import checks, compatibility-entrypoint checks, and the interaction-control, perception, assessment-evidence, response-planning, presentation, and state/persistence suites. It is blocked by an incomplete equivalence corpus, retained duplicate runtime, and missing `numpy`/`networkx` dependencies for pedagogy, retrieval, response-generation, and runtime suites. Live-cloud smoke, performance comparison, owner matrix, and final documentation lockstep evidence are also absent.

Pending: run in the artifact-complete environment, publish full before/after oracle captures, run the bounded live smoke suite, measure startup/non-model p95/time-to-first-audio/model counts, and attach the ownership/review matrix.

## Ticket status and remaining work

No ticket in `.scratch/modular-tutor-runtime/issues` is marked complete. Tickets 01–10 remain `open`; tickets 11–28 are `ready-for-agent` and retain unchecked acceptance items.

| Tickets | Assessment | Main remaining work |
| --- | --- | --- |
| 01–05 | Planning still open | Canonical behavior inventory, interface decisions, state ownership, and failure-policy decisions need explicit closure artifacts. |
| 06–10 | Planning still open | Duplicate inventory/disposition, split sequence, verification gates, and ownership assignments are not closed. |
| 11–14 | Partial foundation | Complete frozen oracle, lifecycle contracts, coordinator routing, rollback checkpoints, and measurable temporary-adapter removal plan. |
| 15–20 | Partial extraction | Interaction, perception, assessment, pedagogy, retrieval, and response planning are present as seams but still depend on raw state/legacy execution and lack full equivalence proof. |
| 21 | Partial | Complete Model Gateway/replay/timeout/metrics extraction and remove legacy generation policy. |
| 22–23 | Partial | Wire actual speech/display/device realization, authored scenes, synchronization, interruption, fallback, and truthful receipts. |
| 24 | Partial | Connect realization receipt to authoritative assessment arming and atomic commit. |
| 25 | Incomplete | Finish ownership matrix, immutable views, one transaction, conflict/invariant enforcement, and architecture tests. |
| 26 | Not done | Remove legacy Turn implementation and make coordinator/module interfaces authoritative. |
| 27 | Not done | Dispose of and delete `cloud_workspace_v8`; prove all callers use the canonical runtime. |
| 28 | Not done | Complete all equivalence, module, architecture, live-cloud, performance, documentation, and ownership gates. |

## Standards axis

No repository-specific coding-standard document was found in the reviewed paths. Against the code-review smell baseline, the main judgement-call smells are Shotgun Surgery/Divergent Change in `TutorLoop` and `TurnRuntime` (feature extraction still requires edits in the monolith, coordinator, adapter, and façade), and Middle Man/Speculative Generality in the current legacy adapter layer. These are secondary to the specification failures above; the dominant issue is incomplete extraction rather than style.

## Verification snapshot

- `python -m unittest discover -s cloud_run_service -p 'test*.py'`: 100 tests discovered; 9 import errors because `numpy` and `networkx` are unavailable.
- `python -m cloud_run_service.handoff_verification --json ...`: exit code 2; status `blocked`.
- Passing handoff gates: oracle validation, architecture import check, compatibility entrypoints, interaction control, perception, assessment/evidence, response planning, presentation, and state/persistence suites.
- Blocked handoff gates: full oracle equivalence, duplicate-runtime deletion, pedagogy, retrieval, response generation, runtime suites, live-cloud smoke, and performance comparison.

## Handoff recommendation

Do not authorize Ownership Handoff or parallel module ownership yet. The next implementation checkpoint should be removal of the legacy behavioral source and conversion of state handling to one authoritative projection/commit transaction; only then should the full equivalence and deletion gates be rerun.
