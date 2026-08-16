# Perception

`PerceptionInterface.perceive()` is the single public Interface used by the Turn
Coordinator and Interface tests. It accepts an immutable `PerceptionRequest` and
returns a `ModuleOutcome[PerceptionObservation]`; it never receives or mutates the
shared Learner State or Session State object.

The Module owns deterministic safety/nonsense gates, the structured observation
schema, confidence validation, concept inheritance/cross-check results, cognitive
signals, and the neutral degraded fallback. Gemini Perception uses the shared
runtime `ModelGateway` only for transport; prompts and schemas remain local here.
Timeout, unavailable backend, invalid schema, and degraded
fallback conditions are reported as typed `FailureSignal` values so runtime policy
remains in the Turn Coordinator.

Run the public-Interface tests from `cloud_run_service`:

```powershell
python -m unittest discover -s perception/tests -v
```
