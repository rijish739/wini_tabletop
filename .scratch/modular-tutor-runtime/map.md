# Modular Tutor Runtime

## Destination

An implementation-ready modularization specification for the canonical `cloud_run_service` tutor runtime: deep in-process Feature Modules, explicit typed interfaces, single-owner state, deterministic verification, a behavior-preserving Baseline Split, deletion of `cloud_workspace_v8`, and a safe Ownership Handoff to multiple developers.

## Notes

- Implementation-facing synthesis: [`spec.md`](spec.md) (`ready-for-agent`).
- Domain language lives in [`CONTEXT.md`](../../CONTEXT.md).
- Use Wayfinder for the decision map, Grilling plus Domain Modeling for HITL decisions, and Codebase Design when placing seams or defining Module interfaces.
- `cloud_run_service` is the sole target and future behavioral source of truth.
- The first implementation is one coordinated Baseline Split. It preserves behavior and introduces no feature, prompt, policy, or performance improvements.
- Multiple developers begin independent feature work only after the Ownership Handoff gates pass.
- The agreed Feature Modules are Interaction Control, Perception, Pedagogy, Assessment and Evidence, Retrieval, Response Planning, Response Generation, Presentation, and State and Persistence. `runtime` owns coordination; `infrastructure/model_gateway` owns model transport.
- The Turn Coordinator sequences Modules but contains no feature policy. Modules do not call one another's implementations.
- Modules emit typed outcomes, State Changes, and Failure Signals. Runtime policy decides recovery. Only State and Persistence applies and commits state.
- Streamed output is provisional. Assessment is armed only after a successful Realization Receipt, and a Turn Result is authoritative only after Turn Commit.
- Existing callers retain the `TutorLoop.turn()` dictionary/JSON contract through a temporary compatibility facade.
- `cloud_workspace_v8` must be inventoried, dispositioned, and then deleted. Required root entrypoints may remain only as thin adapters into the canonical runtime.
- Normal verification is offline and deterministic. Live-cloud smoke verification is separate and bounded.
- Repository architecture documents remain subject to the mandatory four-document lockstep rule plus `rag_memory.md` and the `WINI_ARCHITECTURE.md` overview.

## Decisions so far

| Ticket | Title | Type | Status | Resolution Summary |
| --- | --- | --- | --- | --- |
| [01](issues/01-inventory-canonical-turn-behavior.md) | Inventory the canonical Turn behavior and compatibility surface | task | resolved | Characterized 10 sequential turn phases and single-writer invariants in `cloud_run_service/tutor_loop.py`. |
| [02](issues/02-define-behavioral-equivalence-oracle.md) | Define the behavioral equivalence oracle | grilling | resolved | Established deterministic offline equivalence baseline via `baseline_oracle` and path-scoped normalization. |
| [03](issues/03-define-deep-module-interfaces.md) | Define deep Feature Module interfaces | grilling | resolved | Defined 9 deep in-process Feature Modules and single typed public interfaces with acyclic dependencies. |
| [04](issues/04-assign-state-ownership.md) | Assign exclusive semantic state ownership | grilling | resolved | Assigned exclusive field ownership across modules and single transactional commit in `state_and_persistence`. |
| [05](issues/05-define-failure-policy.md) | Define failure classification, recovery policy, and supervisor health | grilling | resolved | Defined typed `FailureSignal`, fail-closed invariants, explicit degradation, and 4-state supervisor. |
| [06](issues/06-inventory-duplicate-runtimes.md) | Inventory duplicate-runtime callers, behavior, and assets | task | resolved | Inventoried `cloud_workspace_v8` and root directories against canonical `cloud_run_service`. |
| [07](issues/07-decide-duplicate-disposition.md) | Decide duplicate-runtime disposition | grilling | resolved | Approved deletion of `cloud_workspace_v8` snapshot and maintenance of thin root entrypoints. |
| [08](issues/08-specify-baseline-split-sequence.md) | Specify the Baseline Split sequence and rollback checkpoints | grilling | resolved | Specified sequential Baseline Split order across Tickets 11–28 with zero downtime and stable checkpoints. |
| [09](issues/09-define-verification-and-handoff-gates.md) | Define verification, performance, and handoff gates | grilling | resolved | Defined 8 strict gates including 100% test pass rate, no ungrounded assessment, and performance parity. |
| [10](issues/10-assign-module-ownership.md) | Assign Feature Module ownership and review rules | grilling | resolved | Assigned primary/backup owners and producer-consumer review rules for all 9 modules and coordinator. |
| [11](issues/11-freeze-baseline-equivalence-oracle.md) | Freeze the Baseline Split equivalence oracle | task | resolved | Implemented `baseline_oracle` with frozen corpus, replay gateway, and observation comparisons. |
| [12](issues/12-disposition-duplicate-runtime.md) | Disposition duplicate-runtime behavior and assets | task | resolved | Purged `cloud_workspace_v8` snapshot via `git rm -rf` and preserved thin compatibility adapters. |
| [13](issues/13-expand-lifecycle-contracts-and-state.md) | Expand lifecycle contracts and working state | task | resolved | Implemented `runtime/contracts.py` and `state_and_persistence/` working state projection. |
| [14](issues/14-route-legacy-through-coordinator.md) | Route legacy Turn through the Turn Coordinator | task | resolved | Implemented `TurnCoordinator` and `TutorLoopCompatibilityFacade` in `runtime/`. |
| [15](issues/15-extract-interaction-control.md) | Extract Interaction Control | task | resolved | Extracted `interaction_control/` owning front gate, persona, topic routing, and mode transitions. |
| [16](issues/16-extract-perception.md) | Extract Perception | task | resolved | Extracted `perception/` owning cognitive analysis, intent classification, and degraded fallbacks. |
| [17](issues/17-extract-prior-assessment-and-evidence.md) | Extract Prior Assessment and Evidence | task | resolved | Extracted `assessment_evidence/` owning grading contracts, verification, and idempotent evidence. |
| [18](issues/18-extract-pedagogy.md) | Extract Pedagogy | task | resolved | Extracted `pedagogy/` owning strategy, rules decision, test driver, mode state, and pacing. |
| [19](issues/19-extract-retrieval.md) | Extract Retrieval | task | resolved | Extracted `retrieval/` owning vector retrieval, bridges, misconceptions, and cohesion checks. |
| [20](issues/20-extract-response-planning.md) | Extract Response Planning | task | resolved | Extracted `response_planning/` owning modality selection, teaching steps, and candidate items. |
| [21](issues/21-extract-generation-and-model-gateway.md) | Extract Response Generation and Model Gateway | task | resolved | Extracted `response_generation/` and `runtime/model_gateway.py` with streaming and budget realization. |
| [22](issues/22-realize-speech-and-retrieved-presentation.md) | Realize speech and retrieved presentation | task | resolved | Implemented speech synthesis, display cards, and realization receipts in `response_layer/`. |
| [23](issues/23-realize-authored-visual-presentation.md) | Realize authored visual presentation | task | resolved | Implemented Board Buddy drawing, layout, and visual grounding validation in `response_layer/`. |
| [24](issues/24-arm-assessments-from-realization.md) | Arm assessments from realization | task | resolved | Implemented authoritative item arming matching realized speech beats and voiding leaked keys. |
| [25](issues/25-complete-state-ownership-and-enforcement.md) | Complete state ownership and architecture enforcement | task | resolved | Enforced state immutability, transactional projection, and AST modular boundary validation. |
| [26](issues/26-contract-legacy-turn-implementation.md) | Contract the legacy Turn implementation | task | resolved | Contracted `tutor_loop.py` to a thin compatibility facade delegating to `TurnCoordinator`. |
| [27](issues/27-consolidate-canonical-runtime.md) | Consolidate the canonical runtime | task | resolved | Consolidated all canonical runtime code in `cloud_run_service` and removed obsolete duplicates. |
| [28](issues/28-verify-ownership-handoff.md) | Verify and complete Ownership Handoff | task | resolved | Verified complete test suite (138+ unit tests passing) and prepared documentation for handoff. |

## Not yet specified

- Post-handoff parallel feature backlogs for each individual Feature Module.

## Out of scope

- Feature improvements, prompt or model changes, policy changes, optimizations, and unrelated cleanup during the Baseline Split.
- Splitting the runtime into separately deployed microservices or introducing new network boundaries.
- Migrating this local map to GitHub Issues before the canonical repository and authenticated issue tooling are confirmed.
