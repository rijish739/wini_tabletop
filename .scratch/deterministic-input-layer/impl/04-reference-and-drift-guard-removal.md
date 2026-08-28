# 04 — Reference/anaphora slice + drift-guard removal

**What to build:** A complete path for coreference *evidence*: `observe()` publishes anaphor spans (not a
boolean), the duplicate anaphora predicate and the silent drift guard are deleted, and the
null-concept-no-write protection is made explicit. This slice carries a **deliberate, recorded behavior
change** — with the drift guard gone, a confident resolution to an unrelated concept is accepted until
the concept resolver lands.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] `is_anaphoric_followup` migrated as `ReferenceReading` = `anaphors: tuple[AnaphorSpan, ...]` +
  derived `has_anaphora`; the unmeasured 12-word cutoff and `word_count` discarded (recorded in the
  handover doc as an artefact, not an inherited requirement). Compute-and-mark deferral on unauthorized.
- [ ] Deleted: `control.py`'s verbatim static `_is_anaphoric_followup`; the drift guard and the two
  duplicate concept suppliers in `legacy_adapter.py`.
- [ ] `ReferenceReading` ships on the required `InteractionControlRequest.observation` (produced,
  currently unread) — which is what stops a future consumer `getattr`-falling back to a private regex.
- [ ] Invariant asserted: `concept_id is None` ⇒ no learner-state write and no mastery movement.
- [ ] The interim regression is recorded **as a deliberate change, not a delta to hold identical**:
  a confident resolution to an unrelated concept is now accepted and the session concept follows it.
- [ ] Fixtures for anaphor spans in the conformance suite; green in CI.
