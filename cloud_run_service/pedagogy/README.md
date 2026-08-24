# Pedagogy

`PedagogyInterface.decide()` is the public seam for selecting the next teaching
action from the validated perception and learner-state views. Pedagogy owns action
policy, need selection, mode behavior, and pedagogical state-change proposals. It
does not retrieve evidence, compose prompts, realize output, or commit durable
state.

Failures are returned as typed `FailureSignal` values; the Turn Coordinator decides
whether a valid degraded decision can continue. State and Persistence remains the
only durable writer.

Run from `cloud_run_service`:

```powershell
python -m unittest discover -s pedagogy/tests -v
```
