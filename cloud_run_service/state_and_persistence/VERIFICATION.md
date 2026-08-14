# Issue 13 verification — 2026-08-14

The new contracts and transactional state seam are additive and are not imported by
the canonical `TutorLoop`, server, voice, UI, or scripted Turn callers. `git diff HEAD`
shows no change to those runtime paths.

Measured offline checks from `cloud_run_service`:

- lifecycle and State/Persistence interface tests: 18 passed;
- full `unittest` discovery with the bundled workspace Python: 34 passed;
- existing P0 evidence/state invariant runner: 33 passed;
- frozen oracle tests: 16 passed;
- frozen corpus validation: pass (27 cases, 9 state fixtures, 7 recordings);
- frozen reference self-check: zero differences.

`python -m baseline_oracle verify` remains `incomplete`, as recorded by the frozen
oracle before this issue, because the checkout lacks `policy_logreg.npz`,
`signal_heads.npz`, the local chunk index, and 25 model-boundary recordings. The
command reports zero structural differences but correctly refuses a complete
candidate-equivalence verdict without those artifacts.
