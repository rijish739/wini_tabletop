# 00 — Vertical slice map (read first)

This effort is sliced as a **diamond**, not a stack of layers, specifically to defeat three failure
modes:

- **Hidden interface mismatches** — killed by **contract-first + shared golden fixtures** (slice 01).
  The observation types, the two request-field additions, `gate()`'s signature, and the safety
  **composition helper** are frozen up front with an executable conformance fixture set. Producers and
  consumers build against the *same* fixtures, so a drift fails a shared test instead of surfacing at
  integration.
- **Late verification** — killed by the **walking skeleton + CI in slice 01**. A trivial turn runs
  end-to-end and the free-lane CI is green from day one. Every later slice extends a *green* pipeline
  and ships its own tests into the *same* CI. There is no end-of-line "assemble the gate" ticket.
- **No true parallelism** — enabled by the two above. After slice 01, slices 02–10 build against
  frozen fixtures/stubs concurrently.

```
01 CONTRACT + WALKING SKELETON + CI  (the tracer bullet — the only wide top edge)
      │
      ├──> 02 legibility + normalization fidelity        ┐
      ├──> 03 problem detection                          │  parallel vertical
      ├──> 04 reference + drift-guard removal             │  feature slices, each
      ├──> 05 authorization + doubt + repair              │  end-to-end and self-
      ├──> 06 maths grammar            (← 05)             │  verifying into the
      ├──> 07 perception schema + inline rewire (← 03)    │  same green CI
      ├──> 08 STT capture contract doc                    │
      └──> 09 blind corpora (safety + PII)                ┘
      10 WIF (independent prerequisite)

02..07  ──────────────>  11 LEGACY DELETION (convergence; mechanical, everything already verified)
05,09,10,11 ──────────>  12 child_safety Stage 2 (vertical: dispatch→hold→compose→case-record→eval)
09,10,12 ─────────────>  13 personal_data Stage 3 (vertical: detect→redact→sinks→eval)
```

**Rule for every feature slice (02–07):** it is a complete path — one reading implemented in
`observe()`, the consumer(s) that read it rewired, and the invariants/turn-properties/expected-diff
rows that prove it — all landing together and green in CI. A slice never leaves a reading unconsumed
or a consumer reading an assumed shape. Legacy channels stay live until slice 11, so every slice lands
green without a big-bang cutover.

**Startable immediately:** 01, 10 (and 08/09 the moment 01's contract lands). Do 00-docs-truth-pass
context hygiene (see below) before touching code — `CLAUDE.md` is loaded into every session.

**The docs truth pass is folded into slice 01's first commit** rather than a separate ticket, because
a stale `CLAUDE.md` gotcha misleads the very agent building the skeleton. See slice 01 criteria.
