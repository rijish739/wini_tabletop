# Ownership Handoff Verification

Status: **blocked — handoff not authorized**

This is the reproducible evidence bundle for the Baseline Split. Run from the
repository root:

```powershell
python -m cloud_run_service.handoff_verification --json .scratch/handoff-verification.json
```

The command is conservative and returns exit code `2` while any gate is blocked.
It validates the frozen oracle, runs every retained Module-interface suite, checks
cross-Module implementation imports, checks compatibility entrypoints, and verifies
duplicate-runtime disposition. Credentialed live-cloud smoke and performance
comparison remain separate gates and are never run implicitly.

## Current evidence

The oracle asset self-check passes: 27 corpus cases and 9 state fixtures validate.
The equivalence reference is incomplete: only 7 of 32 expected model-boundary calls
are replayable and the canonical runtime artifacts needed for a full capture are not
present. Therefore `baseline_oracle verify` correctly exits with status 2.

The local environment also lacks `numpy` and `networkx`, so suites importing those
dependencies are reported as blocked rather than skipped. This report must be
regenerated in the artifact-complete build environment before handoff.

## Handoff gates

Handoff may begin only when the generated report is all-pass and the following are
attached: artifact-complete before/after oracle captures, bounded live-cloud smoke
results, startup/non-model p95/time-to-first-audio measurements, model call and
client-construction counters, the duplicate deletion review, and the owner/review
matrix in `OWNERSHIP_HANDOFF_OWNERS.md`.

Known limitations and measured values must be updated together in the four lockstep
architecture documents and `rag_memory.md`; values must be remeasured, never copied.
