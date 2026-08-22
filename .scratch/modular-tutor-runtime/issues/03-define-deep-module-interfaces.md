# Define deep Feature Module interfaces

Status: resolved
Type: grilling
Blocked by: 01

## Question

What are the exact nine deep Feature Module interfaces, what are their single public façades, what typed requests and Module Outcomes do they exchange with the Turn Coordinator, and how is cross-Module implementation coupling forbidden?

Decide how the Turn Coordinator remains free of feature policy while sequencing deep modules.

## Resolution

- Defined 9 in-process Feature Modules: `InteractionControl`, `Perception`, `Pedagogy`, `AssessmentEvidence`, `Retrieval`, `ResponsePlanning`, `ResponseGeneration`, `Presentation`, and `StateAndPersistence`.
- Established that each module exposes exactly one typed public interface.
- Turn Coordinator (`runtime/coordinator.py`) orchestrates turn phases without owning any domain teaching policy.
- Banned direct module-to-module imports; information flow occurs solely via immutable `TurnContext` and typed Module Outcomes.

## Comments
