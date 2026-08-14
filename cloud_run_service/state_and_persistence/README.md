# State and Persistence

This module provides the one-Turn state transaction used during the Baseline Split.
Its public interface is `StateAndPersistence.begin()` plus `commit()`. A working
projection accepts lifecycle `StateChange` values and exposes only immutable paths
granted to the requesting capability.

Invariants:

- loaded state is additively migrated and bound to the requested learner before use;
- changes are checked against capability grants and conflicting writes are rejected;
- evidence can only be appended by `assessment_evidence`, with matching idempotency
  keys, through the existing authoritative evidence writer;
- starting state is never mutated, and later capabilities read the validated working
  projection;
- commit performs one optimistic whole-state write and returns a `TurnCommit` only
  after that write succeeds;
- a failed or stale commit publishes no new in-process state.

`LearnerStatePersistenceAdapter` is the production adapter. It uses either the existing
atomic `LearnerState.save()` JSON path or one configured durable store document write.
`DeterministicPersistenceAdapter` is the offline adapter for module and coordinator
tests.

Run from `cloud_run_service`:

```powershell
python -m unittest discover -s state_and_persistence/tests -v
```
