# Interaction Control

`InteractionControlInterface.control()` is the single public Interface for session
admission, deterministic front routing, non-learning interactions, topic continuity,
redirection, conversation continuity, mode-stop interaction, and termination. It
returns `ModuleOutcome[InteractionDecision]`: either a completed compatibility result
or an admitted learning continuation for the remaining migration adapter.

The Module receives an immutable `InteractionControlRequest` and never receives or
mutates the shared learner-state object. Continuity changes are returned as typed
`StateChange` values. `interaction_control` owns `current_concept`, `pending_shift`,
conversation `context`, session status/leave flags, steer cooldown, and the session
safety alert. Mode/test-plan changes retain `pedagogy` ownership; stale pending
assessment changes retain `assessment_evidence` ownership. Safety notifications and
append-only operational logs use injected internal ports.

Run the public-Interface tests from `cloud_run_service`:

```powershell
python -m unittest discover -s interaction_control/tests -v
```
