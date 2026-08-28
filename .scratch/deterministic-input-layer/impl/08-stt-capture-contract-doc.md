# 08 — `STT_CAPTURE_CONTRACT.md` (producer handoff)

**What to build:** The requirements **on the STT producer** (a different developer's streaming service),
written against the frozen `Utterance` shape so they can satisfy Intake without reading its source. A
document, not capture-edge code — no capture-edge change is implemented in this effort.

**Blocked by:** 01 (the `Utterance` shape is frozen there).

**Status:** ready-for-agent

- [ ] `docs/architecture/STT_CAPTURE_CONTRACT.md` written new, as producer requirements:
  `max_alternatives=5` (unconditional, request-time), `enable_word_confidence`,
  `enable_word_time_offsets`, the `0.0`→`None` sentinel mapping, minting `UtteranceProvenance`, deleting
  the `stt_confidence = 1.0` fabrication, removing the empty-transcript early return.
- [ ] Three streaming rules: one `Utterance` per **final** result; the utterance boundary is the
  recognizer's endpointing; Intake never runs on a non-final result. No `is_final` field is added.
- [ ] Caveats stated: `latest_short` confidence is disclaimed by Google; word confidence is Preview.
  Facts recorded: STT v1 has no `asia-south1` region (STT and Vertex not co-located); v2's `asia-south1`
  matrix is UNVERIFIED. Deferred-with-owners: the concept-scoped phrase set; `en-US`→`en-IN`.
- [ ] Standing rule in the file: whoever changes `Utterance` updates this file in the same session.
