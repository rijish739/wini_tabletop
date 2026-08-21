# 22 — Realize speech and retrieved presentation

**What to build:** A Presentation Interface that realizes speech-only and retrieved-display response plans and returns an accurate Realization Receipt while preserving provisional streaming behavior.

**Blocked by:** 20 — Extract Response Planning; 21 — Extract Response Generation and the Model Gateway.

**Status:** ready-for-agent

- [ ] Expose one Presentation Interface used by the coordinator and Interface-level tests.
- [ ] Realize speech-only, question-card, score-card, retrieved-crop, and formula presentation through the Interface.
- [ ] Preserve device capability filtering, crop relevance, display metadata, speech sanitization, and answer streaming order.
- [ ] Identify early speech and display events as Provisional Output.
- [ ] Return a Realization Receipt that distinguishes intended, delivered, skipped, degraded, interrupted, and failed output.
- [ ] Emit typed Failure Signals for unavailable display, invalid assets, streaming interruption, and partial realization.
- [ ] Preserve explicit speech-only degradation when optional retrieved presentation fails.
- [ ] Verify device variants, speech-only, cards, crops, formulas, interruption, and degradation through the Module Interface and compatibility façade.
- [ ] Remove migrated speech and retrieved-presentation policy from the legacy adapter while keeping the equivalence oracle green.

