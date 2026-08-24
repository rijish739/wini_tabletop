# Response Planning

`ResponsePlanningInterface.plan()` is the public seam for converting pedagogical
decisions and grounded retrieval into a validated, unrealized `ResponsePlan`.
The module owns teaching-script policy, modality approval, assessment proposals,
and validation. It does not realize output, arm an assessment, persist state, or
construct a model client.

Invalid grounding, unsupported capability, and validation failures are typed
`FailureSignal` values. The coordinator owns recovery policy; Presentation owns
what was actually delivered.

Run from `cloud_run_service`:

```powershell
python -m unittest discover -s response_planning/tests -v
```
