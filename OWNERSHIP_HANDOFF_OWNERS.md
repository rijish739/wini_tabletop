# Feature Module Ownership and Review Rules

Status: **pending named-owner confirmation**. Role assignments below are the
handoff matrix; parallel feature work is not authorized until people are recorded
for every primary and backup slot and the verification report is all-pass.

| Module | Primary owner | Backup owner | Public interface | Review rule |
|---|---|---|---|---|
| Interaction Control | TBD | TBD | `InteractionControlInterface.control` | producer + consumer |
| Perception | TBD | TBD | `PerceptionInterface.perceive` | producer + consumer |
| Pedagogy | TBD | TBD | `PedagogyInterface.decide` | producer + consumer |
| Assessment and Evidence | TBD | TBD | `AssessmentEvidenceInterface.evaluate_prior_attempt` | producer + consumer |
| Retrieval | TBD | TBD | `RetrievalInterface.retrieve` | producer + consumer |
| Response Planning | TBD | TBD | `ResponsePlanningInterface.plan` | producer + consumer |
| Response Generation | TBD | TBD | `ResponseGeneration.generate` | producer + consumer |
| Presentation | TBD | TBD | `PresentationInterface.realize` | producer + consumer |
| State and Persistence | TBD | TBD | `StateAndPersistence.begin` / `commit` | producer + consumer |
| Runtime integration | TBD | TBD | `TurnCoordinator` | integration owner |

Interface changes require review from the Module producer and every known consumer.
Lifecycle-contract, coordinator ordering, recovery-policy, or state-ownership
changes additionally require Runtime Integration review. A change that affects
both an Interface and lifecycle contract cannot merge until all three reviews are
recorded in the change description.

Each module README documents its invariants, state ownership, failure signals,
approved dependencies, adapters, and verification command. The README is part of
the Interface-change review surface.
