# Presentation

`PresentationInterface.realize()` is the public seam for selecting and emitting
approved speech/display artifacts. It returns a `PresentationResult` with a
`RealizationReceipt` and provisional output events; it never claims delivery that
the downstream device has not acknowledged.

Presentation owns modality degradation, artifact validation, device variants,
stream ordering, and realization receipts. It does not own response prompts,
retrieval, assessment grading, or durable state. Assessment arming is proposed
only after successful realization and committed by State and Persistence.

Run from `cloud_run_service`:

```powershell
python -m unittest discover -s presentation/tests -v
```
