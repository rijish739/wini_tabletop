# 05 — Authorization + doubt + repair slice

**What to build:** The complete acoustic-doubt path: an injected transcript policy decides
`Authorization`, the doubt verdict is OR-ed from the available signals, nothing is graded or written from
an unauthorized transcript, and a below-floor voice turn produces the repair screen instead of a graded
answer. This is the slice that wires the STT-uncertainty contract end-to-end through its consumers.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] `authorization` filled from an **injected transcript policy** (`UtteranceIntake(transcript_policy=
  ...)`); Intake never compares confidence to a threshold. Three states (`AUTHORIZED`/`UNAUTHORIZED`/
  `DISCARDED`); the `DISCARDED`→`UNAUTHORIZED` fold forbidden.
- [ ] `TranscriptReading` doubt verdict OR-ed from the three signals (utterance confidence, min word
  confidence, alternate disagreement); `disagreement`/`min_word_confidence` = `None` when their inputs
  are absent; the alternate-disagreement measure computed over `normalized_text`, before authorization.
- [ ] Three env-backed floors through `runtime_flags.confidence_floor` (0.60 / ~0.40 / disagreement
  ceiling), entered **PROVISIONAL** in the numbers register against the captured-STT corpus.
- [ ] Consumers wired: `AssessmentRequest.observation` added; Assessment + Evidence grade/write only on
  `authorization is AUTHORIZED`; the two downstream float checks (`evidence/ledger.py`,
  `assessment_evidence/interface.py`) **deleted and replaced** by an `AUTHORIZED` precondition that
  **raises**; Interaction Control's LEARNING path gates on `authorization` (the `stt_confidence` float
  read deleted); Perception is not run on an `UNAUTHORIZED` turn.
- [ ] `repair_choices` is the one sanctioned export; the response layer reads it and is forbidden from
  reading `utterance.alternates`. The learner always chooses; nothing auto-selects an alternate.
- [ ] Three uncertainties, three names: `RouteResult.uncertain` → `perception_degraded` across all seven
  sites; the bare word "uncertain" banned as a new field name; `triage_turn(stt_uncertain=)` left legacy
  and **not** re-wired.
- [ ] Invariants asserted: (2) exactly one branch on `Utterance.source` (the trust policy); (3) no
  consumer reads `utterance.alternates`; (4) for `VOICE`, `UNAUTHORIZED` iff `transcript.doubtful`.
- [ ] Turn-level property: the repair round-trip preserves `provenance.repairs` (in `runtime/tests/`,
  stub policy, free lane). Startup capability assertion + health endpoint report which doubt signals the
  current producer supplies (day-one: only the float; repair-path delta predicted ≈ zero, written down).
- [ ] Fixtures for the three authorization states + doubt causes; green in CI.
