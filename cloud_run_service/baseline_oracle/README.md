# Baseline Split equivalence oracle

This package is the frozen, standard-library-only behavioral oracle for the canonical
Tutor Runtime. It compares complete Turn observations rather than answer text alone:
the compatibility result, committed state, semantic State Changes, evidence,
assessment lifecycle, grounding manifest, Realization Receipt, provisional stream
order, failures/degradation, latency, and model usage.

## Commands

Run from `cloud_run_service`:

```powershell
python -m baseline_oracle validate
python -m baseline_oracle verify
python -m baseline_oracle verify --candidate path\to\candidate-capture.json
python -m baseline_oracle report --json baseline_oracle\reference\baseline_report.json --markdown baseline_oracle\reference\baseline_report.md
python -m unittest discover -s baseline_oracle\tests -v
```

`verify` without `--candidate` performs the frozen-reference integrity check and exits
with status 2 while the canonical capture is incomplete. A
candidate capture may be either a JSON observation list or the envelope written by
`capture`.

To capture a runtime, expose a zero-argument factory returning an adapter with the
`RuntimeAdapter` interface in `runner.py`, then run:

```powershell
python -m baseline_oracle capture --adapter your_package.adapter:create --output candidate.json
```

The adapter receives a deep-copied sanitized starting state, the immutable corpus
case, a `ReplayModelGateway`, and an event sink. It returns one `RuntimeTurn`. The
runner owns observation capture and model-call accounting, keeping adapters small.

## Frozen assets

- `fixtures/states/`: nine sanitized starting states.
- `fixtures/corpus.json`: 27 representative Turn Inputs.
- `fixtures/model_replays.json`: redacted model-boundary responses and failures,
  keyed by request SHA-256 rather than raw prompts or credentials.
- `reference/expected_outcomes.json`: canonical contract characterization.
- `reference/metadata.json`: commit, normalization, provenance, and limitations.
- `reference/baseline_report.*`: preserved reference self-check.

## Current reference limitation

The repository does not contain `policy_logreg.npz`, `signal_heads.npz`, or the local
chunk-index binary. The pinned runtime imports successfully in an isolated environment,
but unchanged `TutorLoop` construction fails while loading those artifacts. The frozen
contract characterization therefore records performance as unavailable and 7 of 32
expected external calls as replayable; it does not invent missing recordings or latency
measurements. In an artifact-complete deployment checkout, run `capture` with the
canonical adapter and replace the constrained reference/report after review.
