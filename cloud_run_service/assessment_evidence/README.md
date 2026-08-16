# Assessment and Evidence

`AssessmentEvidenceInterface.evaluate_prior_attempt()` is the module's public seam.
It receives an immutable `AssessmentStateView`, recognizes non-attempts, grades a
previously realized verified item deterministically before using the model grader, and
returns typed `StateChange` values. It never mutates learner or session state directly.

The module owns prior-attempt validity, confidence floors, evidence idempotency, and the
decision to disarm a consumed pending assessment. Evidence is emitted only as an
idempotent append to `evidence_ledger`; `WorkingStateProjection` routes that append through
`evidence.record_outcome`, the authoritative evidence writer, so mastery,
misconceptions, replay, and migration retain one implementation.

Obvious non-attempts, uncertain perception, and low-confidence grades produce no state
changes and leave the pending assessment armed. Malformed, stale, cross-learner, and
legacy-unverified pending assessments produce invalid `assessment_evidence` Failure
Signals. The coordinator's recovery policy fails closed on those integrity failures.

Run from `cloud_run_service`:

```powershell
python -m unittest assessment_evidence.tests.test_assessment_evidence -v
python -m unittest runtime.tests.test_compatibility_facade -v
```
