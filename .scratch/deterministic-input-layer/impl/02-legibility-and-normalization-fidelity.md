# 02 — Legibility + normalization-fidelity slice

**What to build:** A complete path for the textual-illegibility axis: `observe()` fills
`LegibilityReading`, `gate()` translates illegible → NONSENSE, and typed maths typography survives
normalization intact (`x²` does not become `x2`). Consumer, reading, and proof land together.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] `is_nonsense` migrated onto normalized text as `LegibilityReading` — five branches collapse to one
  boolean + `LegibilityCue` ∈ {`LEGIBLE`,`EMPTY`,`NO_ALPHANUMERIC`,`CHARACTER_RUN`,`NO_LEXICAL_CONTENT`,
  `KEYBOARD_MASH`}; thresholds unchanged.
- [ ] NFKC removal proven: fixtures for `x²`, `½`, U+2212, U+00A0, zero-width joiners assert the maths
  typography survives; the accommodating spike assertion ("NFKC normalizes superscript 2") does not
  return.
- [ ] `gate()` NONSENSE arm consumes `observation.legibility` (textual axis only; nothing acoustic feeds
  NONSENSE); SAFETY-beats-NONSENSE priority still in one place.
- [ ] Expected-diff manifest rows added for `normalize_input` (NFKC removal), each row producing a diff
  (symmetric manifest); Tier-A: the 9-row NONSENSE probe stays byte-identical.
- [ ] Fixtures added to slice-01's conformance suite; all green in the existing CI job.
