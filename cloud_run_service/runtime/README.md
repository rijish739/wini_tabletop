# Turn lifecycle contracts

`runtime.contracts` contains only feature-neutral values that cross phases of one
Turn: `TurnInput`, `TurnContext`, `ModuleOutcome`, `StateChange`, `FailureSignal`,
`ProvisionalOutput`, `RealizationReceipt`, `TurnCommit`, and `TurnResult`.

The contracts are immutable, recursively detach mapping/list payloads from their
callers, and validate lifecycle identity and enum values. `ModuleOutcome` supplies only
the common state-change/failure envelope around a generic feature-owned value.
Feature-specific schemas, prompts, evidence manifests, and presentation plans belong
to their Feature Modules and must not be added here.

`TurnResult` is authoritative only when it carries a matching `TurnCommit` and
`RealizationReceipt`. Output produced earlier in the lifecycle is represented by
`ProvisionalOutput` and cannot claim committed learning progress.

## Coordinator activation checkpoint

`TutorLoop.turn()` is now the caller-stable compatibility façade. It constructs an
immutable `TurnInput`, invokes `TurnCoordinator`, and thaws the committed
`TurnResult.compatibility` mapping back to the exact dictionary/list shapes expected by
the server, CLI, streaming, and scripted callers.

The coordinator owns only the deterministic logical phase order and current-Turn
recovery policy. It records explicit degradation, accepts retrieval/generation fallback
only when the reported outcome remains valid, and otherwise fails closed. A committed legacy
Turn is never replayed for retry; bounded idempotent retry belongs at a future pre-commit
operation port. `RuntimeSupervisor` aggregates typed failures across Turns and
exposes `STARTING`, `READY`, `DEGRADED`, and `UNAVAILABLE`. Unclassified exceptions at
the legacy seam become observable `FailureSignal` values and fail closed while the
original exception type and message remain terminal for existing callers.

`InteractionControlInterface` now owns the first logical phase. The coordinator invokes
it with an immutable state snapshot, applies its typed proposed changes through the
temporary migration adapter, and either completes the non-learning Turn or passes an
admitted learning decision to the remaining legacy behavior.

`LegacyTurnAdapter` is intentionally named as a temporary adapter, not a Feature Module.
It executes the seven still-unextracted phases, leaves existing provisional streaming
mechanics untouched, and reports `legacy_adapter_turns` plus
`legacy_adapter_unextracted_phases`. It invokes the existing local/durable whole-state
persistence boundary before producing a `legacy_commit_*` receipt; a failed commit restores
the starting working state and remains terminal. Future extraction checkpoints replace this
bridge with State and Persistence's authoritative transaction one phase at a time.

The `TutorLoop` seam cannot observe downstream TTS or device delivery. Its temporary
`RealizationReceipt` therefore records intended modalities with `PARTIAL` status and an empty
delivered set instead of treating intended `answer`/`display` fields as proof of realization.
The adapter's phase trace records that this limitation was reported; it does not claim those
modalities were completed. The server's existing provisional stream and device behavior remain
caller-visible as before.

Run from `cloud_run_service`:

```powershell
python -m unittest discover -s runtime/tests -v
```
