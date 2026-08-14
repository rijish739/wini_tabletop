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

Run from `cloud_run_service`:

```powershell
python -m unittest discover -s runtime/tests -v
```
