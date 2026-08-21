# Response Generation

`ResponseGeneration.generate()` is the module's only public Interface. It accepts an
approved Response Plan and grounded Retrieval manifest, composes the learner-facing
prompt, applies the spoken answer budget, and returns a `GeneratedResponse` in a typed
`ModuleOutcome`.

The module owns prompts, action-specific speech policy, validation, exact verified
assessment questions, and the safe non-assessing fallback. It does not own model
clients or transport. Those cross-feature concerns live behind `runtime.model_gateway`.

Invariants:

- Instructional claims are composed from the grounded manifest (or the learner's own
  numbers under `method_only`).
- Stored assessment speech is deterministic and is never paraphrased by a model.
- A timeout, transport error, or empty reply emits a typed Failure Signal and only the
  non-assessing fallback.
- Streaming emits the final budgeted answer, so spoken text cannot diverge from the
  compatibility result.

Offline verification:

```text
python -m unittest response_generation.tests.test_response_generation
```
