# P0 Evidence Integrity — migration and rollback

Scope: `cloud_run_service`, the Docker/Cloud Run brain used by the connected Wini
project. This migration deliberately stops at P0. It adds no process, network
service, deployment boundary, teaching-strategy memory, or post-generation model
judge.

## Persisted-state migration

- Learner state is upgraded additively to `state_schema_version: 2` on load.
- `evidence_ledger` is an append-only logical ledger embedded in the same atomic
  learner-state snapshot. `LearnerState.save()` writes a fsynced temporary file,
  retains one `.bak`, then atomically replaces the primary. Firestore continues to
  write one atomic document at the existing turn boundary.
- Existing `concept_states`, mastery values, histories, and global values are not
  recalculated or destructively rewritten. The pre-first-event snapshot is stored
  as `evidence_projection_base`; new outcomes are projected incrementally and full
  replay is reserved for verification/migration.
- A legacy `evidence_log` is loaded as `evidence_ledger`; schema-0 rows receive a
  deterministic legacy event ID. Legacy misconception statuses are mapped safely:
  one failure becomes `candidate`; only two consistent failures can become
  `supported`. Evidence references and transition lists are added when absent.
- A persisted legacy `pending_check` without verification provenance is labelled
  `legacy_unverified` and voided when encountered. It is never graded.
- Legacy callers may continue to call `LearnerState.apply_outcome_event`; it is a
  compatibility adapter to `evidence.record_outcome`, not a second writer.

## Item migration

- Existing pre-authored graph questions use the `items.from_authored` compatibility
  adapter and receive an `authored_verified` token derived from their stored ID,
  question, key/rubric, and verifier version.
- Generated candidates never use that adapter. They become servable only through
  `items.verify`, which independently checks the proposed answer and appends a
  fsynced row to `rag_store/verified_items.jsonl`.
- Normal learner turns only read that prepared bank. If the bank has no suitable
  item, Wini explains without posing an assessing question. Item generation and
  verification remain explicit off-path operations.

## Identity integration

The current brain owns one in-memory `TutorLoop`, so it is explicitly a
single-learner process. `WINI_IDENTITY_MODE=single_learner` is the local JSON
default and binds the state to `local_single_learner`, never `default`.

Firestore or any multi-learner deployment must provide one of:

- `WINI_LEARNER_ID` from the authenticated deployment;
- `WINI_AUTHENTICATED_DEVICE_ID`; or
- `WINI_AUTHENTICATED_SESSION_ID`.

The latter two are pseudonymized. Missing identity, a state/identity mismatch, or
a Firestore initialization failure now fails closed with the brain unready; it no
longer falls back to a possibly shared local learner. Authentication itself is an
external deployment responsibility and is not implemented in this repository.

## Rollback

The three integrity choke points are not runtime-disableable: allowing a legacy
writer behind a flag would invalidate their guarantees. To roll back application
code, restore the pre-P0 code version while retaining a copy of the state file and
its `.bak`. The additive P0 keys are ignored by legacy readers; do not delete the
ledger. To retry P0 after a failed migration, restore the `.bak` in a temporary
fixture, diagnose, and restart with P0 code. Do not edit production mastery or
ledger rows by hand.

`WINI_RESPONSE_LAYER=0` remains the existing response-layer presentation rollback;
its single source/default is `cloud_run_service/runtime_flags.py`. It does not
disable evidence, item verification, arming, safety, STT, or identity integrity.

## Operational checks

Run from `cloud_run_service`:

```text
python test_p0_evidence.py
python -m items.golden_eval
python -m evidence.regression_eval
python -m response_layer.run_tests
```

No generated cache or learner fixture produced by these checks belongs in the
repository or production `rag_store`.
