# Baseline Split equivalence reference

- Status: **PASS**
- Reference: `baseline-split-canonical-2026-08-14`
- Canonical commit: `772c0b6`
- Frozen cases: 27
- Behavioral differences in self-check: 0
- Performance measurement: `unavailable_missing_runtime_artifacts`

The offline corpus, state fixtures, model-boundary recordings, observation projections,
and normalization rules are internally valid and self-equivalent. The repository copy
cannot execute an unchanged canonical Turn because required runtime artifacts are absent;
no latency value has been guessed or copied from unrelated measurements.

## Capture limitations

- `canonical_runtime_missing_policy_logreg.npz`
- `canonical_runtime_missing_signal_heads.npz`
- `canonical_runtime_missing_local_chunk_index`

## Observable surfaces

`assessment_lifecycle`, `case_id`, `compatibility`, `degradation_reasons`, `evidence_events`, `failure_signals`, `manifest`, `metrics`, `model_usage`, `realization_receipt`, `result`, `state_after`, `state_before`, `state_changes`, `stream_events`, `tags`
