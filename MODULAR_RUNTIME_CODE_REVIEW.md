# Modular Tutor Runtime — Implementation Review

## Scope and conclusion

Reviewed the current worktree against `.scratch/modular-tutor-runtime/spec.md`, `map.md`, tickets `01`–`28`, `cloud_run_service/`, and `CLAUDE.md`. Because no fixed Git reference was supplied, `origin/main` (`6df0cec`) was used as the comparison baseline; committed and uncommitted worktree changes were included.

The implementation has useful typed seams and focused tests, but it is not yet a completed Baseline Split or Ownership Handoff. The production Turn still uses the legacy monolithic callback, state is published through short-lived projections rather than one Turn transaction, Presentation is not wired into the production façade, the duplicate runtime remains, and equivalence/performance evidence is incomplete.

## Spec findings

### S1 — Critical: legacy behavior is still the canonical Turn source

`cloud_run_service/tutor_loop.py:1875-1883` passes `turn_behavior=self._canonical_turn` into `TutorLoopCompatibilityFacade`; `cloud_run_service/runtime/compatibility.py:42-58` passes it to `TurnRuntime`; and `cloud_run_service/runtime/turn_runtime.py:330-365` invokes `self._turn_behavior(...)` after module calls. The extracted modules therefore wrap the legacy implementation instead of replacing it. This fails the intent of tickets 14 and 26 and the spec requirement that every Turn route through the nine Feature Module Interfaces.

Pending: extract remaining behavior into the module interfaces/coordinator flow, remove the callback from `TurnRuntime`, remove migrated policy from the adapter, and reduce compatibility to input construction/result serialization.

### S2 — Critical: no single authoritative Turn transaction

`cloud_run_service/runtime/turn_runtime.py:302-315` batches only some outcomes. Continuity changes are applied later at `:361-366`. `_apply_state_changes()` at `:459-479` creates a new projection and immediately publishes it, while `:383-386` performs a separate save/commit. Changes from response planning, generation, and Presentation are not part of one shared working projection. This permits partial state publication before later phases finish.

Pending: begin one projection at Turn start, pass immutable views, apply all accepted changes to it, validate once, and commit exactly once through State and Persistence.

### S3 — High: raw state access and incomplete ownership matrix

`cloud_run_service/runtime/turn_runtime.py:52-68`, `:73-87`, and `:249-275` read `self._state.data` directly. `cloud_run_service/pacing/pacing_controller.py:178-188` directly writes session fields including `explaining_concept`, `expected_response_type`, `last_spoken_answer`, `last_explanation_summary`, `last_voice_latency_ms`, and `explanation_step`; these are absent from `state_and_persistence/ownership.py:26-66`.

Pending: inventory every field, assign one semantic owner, route module reads through scoped views, convert writes to `StateChange`, and add direct-write architecture checks.

### S4 — High: phase ordering/concurrency is incomplete

`cloud_run_service/runtime/coordinator.py:180-227` runs Perception before Interaction Control admission/routing and runs prior-attempt assessment sequentially. The spec requires admission/routing first and coordinator-owned concurrency only for explicitly independent work.

Pending: admission first; run approved perception/grading work under coordinator deadlines; join deterministically; project state before Pedagogy.

### S5 — High: Presentation is isolated but not production-wired

The façade construction at `cloud_run_service/tutor_loop.py:1875-1929` passes no `presentation` implementation. The coordinator request at `cloud_run_service/runtime/coordinator.py:317-323` supplies no speech/display callbacks, display items, authored scene, device profile, or interruption callback. `presentation/interface.py:60-63` and `:93-99` only mark delivery after an actual callback. Consequently production cannot produce a truthful realization receipt, leaving tickets 22–24 incomplete.

Pending: wire actual delivery ports/artifacts, preserve provisional output and interruption semantics, and arm assessments only from a matching successful receipt.

### S6 — High: Model Gateway extraction is partial

`cloud_run_service/tutor_loop.py:1923-1928` constructs `VertexModelGateway`, but the main response path still delegates to the legacy callback. Gateway-owned deadlines, retry policy, replay, metrics, and client-construction equivalence are not demonstrated. Ticket 21 remains partial.

Pending: move prompt/schema/fallback policy into Response Generation, keep transport/lifecycle/deadlines in the gateway, add replay/timeout tests, and remove legacy model transport.

### S7 — Medium: assessment arming is a seam, not an end-to-end lifecycle

`cloud_run_service/assessment_evidence/interface.py:168-243` correctly rejects missing or unsuccessful receipts, but production has no wired Presentation outcome and the legacy callback still owns the main response. The delivered-question → receipt → arm → commit lifecycle is therefore unproven through the façade.

Pending: include arming changes in the one transaction and test spoken, displayed, mismatched, partial, interrupted, duplicate, degraded, and failed realization cases end to end.

### S8 — Medium: duplicate runtime remains

`cloud_workspace_v8/` still exists with approximately 1,430 files, including server, tutor, voice, deployment, and feature implementations. This directly blocks tickets 06, 07, 12, and 27.

Pending: complete migrate/adapt/archive/discard decisions, verify all active callers/assets, retain only thin adapters, delete the duplicate tree, and rerun deletion-focused checks.

### S9 — Medium: handoff evidence is incomplete

The handoff verifier reports an incomplete oracle (`27` cases, `7` recordings, status `incomplete`), no live-cloud smoke, and no artifact-complete performance comparison. Full discovery found 100 tests but 9 import errors because `numpy` and `networkx` are unavailable.

Pending: run the declared dependency-complete environment, complete the frozen oracle, run all module/runtime suites, perform bounded live smoke, and publish startup, non-model p95, time-to-first-audio, model-call, and client-construction measurements.

## Ticket status and remaining work

Ticket files show `01–10` as `open` and `11–28` as `ready-for-agent`; their acceptance checklists remain unchecked.

| Tickets | Assessment | Pending work |
|---|---|---|
| 01–05 | Planning not closed | Canonical behavior, oracle, interfaces, ownership, and failure-policy decisions. |
| 06–10 | Planning not closed | Duplicate inventory/disposition, split sequence, verification gates, and owner assignments. |
| 11–14 | Partial foundation | Complete corpus/replays, lifecycle contracts, admission/routing, recovery, and adapter-removal checkpoint. |
| 15–20 | Partial extraction | Remove legacy policy/raw state access and prove façade scenarios. |
| 21 | Partial | Complete gateway/replay/deadline/metrics extraction. |
| 22–23 | Partial | Wire real speech/display/device/authored realization and receipts. |
| 24 | Partial | Connect receipt validation to authoritative arming and atomic commit. |
| 25 | Incomplete | Finish field matrix, immutable views, conflict checks, direct-write checks, and transaction integration. |
| 26 | Not done | Remove legacy Turn as an active behavior source. |
| 27 | Not done | Consolidate callers/assets and delete `cloud_workspace_v8`. |
| 28 | Not done | Pass oracle, module, architecture, live-cloud, performance, documentation, and ownership gates. |

## Standards findings

No separate `CONTRIBUTING.md` or coding-standard document was found; `CLAUDE.md` is the governing project-rules file. No additional hard style violation was established. The relevant judgement-call smells are:

- **Shotgun Surgery / Divergent Change:** `TutorLoop`, `TurnRuntime`, coordinator, façade, and adapter all participate in one partially extracted behavior.
- **Middle Man / Speculative Generality:** `LegacyTurnAdapter` and the `turn_behavior`/`legacy_turn` parameters preserve a layer the target architecture intends to retire.
- **Primitive Obsession:** ownership scope/path and capability names are strings across the transaction boundary; central validation helps, but the registry should be the only construction path.

## Verification snapshot

Command: `python -m cloud_run_service.handoff_verification --json .scratch/handoff-verification.json`

- Pass: oracle self-validation, module-import architecture check, compatibility entrypoints, Interaction Control, Perception, Assessment/Evidence, Response Planning, Presentation, and State/Persistence.
- Blocked: oracle equivalence, duplicate-runtime deletion, Pedagogy, Retrieval, Response Generation, and Runtime.
- Not run: credentialed live-cloud smoke and performance comparison.

## Recommendation

Keep the task in implementation, not Ownership Handoff. The next checkpoint should remove the legacy callback, integrate one State/Persistence transaction, and wire real Presentation delivery; then rerun the complete oracle and architecture/deletion gates.
