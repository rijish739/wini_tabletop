# Inventory the canonical Turn behavior and compatibility surface

Status: resolved
Type: task
Blocked by: none

## Question

What externally observable behavior, state transition, evidence event, assessment lifecycle, retrieval manifest, presentation decision, streaming event, performance measurement, and caller expectation does the current `cloud_run_service` runtime expose and therefore require the Baseline Split to characterize or preserve?

Produce a referenced inventory, not a proposed new design. Include every active caller and distinguish authoritative contracts from incidental implementation behavior.

## Resolution

- Characterized canonical turn behavior in `cloud_run_service/tutor_loop.py`.
- Formulated the 10 sequential turn phases: admission/front-gate, perception, prior-attempt assessment, pedagogical decision, grounded retrieval, response planning, generation, presentation/realization, assessment arming, and turn commit.
- Documented compatibility dictionary formats consumed by HTTP, voice, and test harnesses.
- Confirmed single-writer invariants for evidence events, learner state persistence, and assessment arming.

