# Define verification, performance, and handoff gates

Status: resolved
Type: grilling
Blocked by: 02, 05, 08

## Question

What objective gates must pass before the Baseline Split is declared complete and Feature Modules are opened to multiple independent developers?

## Resolution

- Defined 8 strict Handoff Gates:
  1. 100% equivalence on frozen test corpus without behavioral regressions.
  2. 100% pass rate on all modular unit tests (138+ tests).
  3. Strict architecture enforcement (zero circular dependencies, zero illegal state writes).
  4. No ungrounded assessment or answer leak.
  5. Single-writer guarantees for evidence and persistence.
  6. Performance parity (overhead within 10% of baseline, no extraneous model calls).
  7. Successful removal of `cloud_workspace_v8` without broken imports.
  8. Lockstep documentation update.
