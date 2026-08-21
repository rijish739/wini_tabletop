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

<!-- Resolved tickets are indexed here; the decision detail lives only in the ticket. -->

## Not yet specified

- The exact extraction and rollback checkpoints beyond the first stable seams; this becomes precise after the Module dependency graph, state ownership, failure policy, and duplicate-tree disposition are resolved.
- The exact compatibility-fixture corpus and normalization rules beyond the required behavior surfaces; these depend on the canonical behavior inventory.
- Risk-specific live-cloud smoke scenarios and latency budgets beyond the no-new-call/no-new-network constraints; these depend on the Baseline Split sequence and measured baseline.

## Out of scope

- Performing the refactor, deleting files, or assigning parallel feature work during this Wayfinder effort.
- Feature improvements, prompt or model changes, policy changes, optimizations, and unrelated cleanup during the Baseline Split.
- Fixing known defects during the Baseline Split unless preserving them would violate safety, identity, state integrity, or assessment integrity.
- Splitting the runtime into separately deployed services or introducing new network boundaries.
- Post-handoff feature development and the resulting improvement backlog.
- Migrating this local map to GitHub Issues before the canonical repository and authenticated issue tooling are confirmed.
