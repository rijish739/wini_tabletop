# Define the behavioral equivalence oracle

Status: resolved
Type: grilling
Blocked by: 01

## Question

Which frozen Turn Inputs, sanitized state fixtures, recorded model-boundary responses, observable outputs, state projections, evidence events, assessment states, manifests, presentation decisions, normalization rules, and tolerances constitute sufficient proof that the Baseline Split preserves canonical behavior?

Decide how known defects are represented and which integrity-critical behaviors may not be preserved.

## Resolution

- Defined the `baseline_oracle` subsystem for offline deterministic equivalence testing.
- Created frozen representative Turn corpus and sanitized starting-state fixtures.
- Implemented replay model gateway recording boundary calls without live cloud dependencies.
- Established strict path-scoped normalization rules that prevent hiding numeric, evidence, or state differences while accommodating formatting variations.

