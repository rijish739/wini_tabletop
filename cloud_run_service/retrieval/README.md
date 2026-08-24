# Retrieval

`RetrievalInterface.retrieve()` is the public seam for selecting grounded evidence,
bridges, schemas, and verified assessment candidates. It receives immutable
`RetrievalRequest` and returns `ModuleOutcome[RetrievalResult]`; it does not mutate
learner state or invoke another Feature Module.

Retrieval owns ranking, cohesion, grounding provenance, assessment eligibility, and
its typed degradation signals. Model and embedding transport remain injected
infrastructure ports. State changes are proposals applied by State and Persistence.

Run from `cloud_run_service`:

```powershell
python -m unittest discover -s retrieval/tests -v
```
