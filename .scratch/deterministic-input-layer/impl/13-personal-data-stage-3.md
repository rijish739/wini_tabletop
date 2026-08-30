# 13 — `personal_data/` Stage 3 (vertical: detect → redact → sinks → eval)

**What to build:** The complete personal-data path: a model-only detector fires immediately after Intake,
redacts by exact-match on `normalized_text`, and the sinks take a redacted type no `str` can satisfy and
fail closed. The system never claims it deleted something it cannot delete. `PERSONAL_DATA_CONTRACT.md`
is normative; this ticket carries seam-level facts only.

**Blocked by:** 09 (PII corpora), 10 (WIF), 12 (Stage 2 complete — safety-first ordering; its case
record is a consumer of this verdict but never waits on it).

**Status:** done — code complete, offline-green (401 unittest / 516 pytest). **Three things are
deliberately NOT done and are named below: the billed collection, the production enable flag, and
late-verdict collection (which this contract forbids rather than defers).**

- [x] New `cloud_run_service/personal_data/`, sibling of `perception/` and `child_safety/`; Gemini call
  fired **immediately after Intake** (redaction is exact-match on `normalized_text`). **Model-only — no
  regex, no lexicon, no outage net**; a Vertex outage means zero detection, made safe by fail-closed sinks.
  - Asserted, not just intended: `DetectorSourceGuardTests` fails if any module in the package imports
    `re`, binds a name containing `threshold`/`score`/`floor`/`cutoff`, or imports `child_safety`.
- [x] `VERTEX_PERSONAL_DATA_MODEL`/`_LOCATION` default `gemini-2.5-flash@asia-south1` version pinned;
  `thinking_budget=0`; 5s + one retry; context one preceding exchange; **two deadlines** —
  `landed_verdict()` (non-blocking, generation) and `await_verdict()` (full envelope, persisting sinks).
  - *Pinning caveat, same as 12:* `VERTEX_PERSONAL_DATA_MODEL_VERSION` defaults **empty** on purpose. A
    version id is a fact about the Vertex catalog at deploy time; inventing one would put an unverified
    string into every eval record. Empty means *honestly unpinned*, is recorded as `model_pinned: false`,
    and is a **hard block** in `--gate`.
- [x] Verdict carries **verbatim substrings** (not spans, not a rewrite); identifier-bearing and **never
  serialized**; fail closed on a substring miss. `RedactedText` lives in the `personal_data` package;
  exact-match redaction with typed, uppercase, **un-indexed, digit-free** placeholders; no threshold, no
  shape rule (maths protected by construction).
  - The unmatchable finding is **not** dropped in the validation belt. Dropping it would convert an
    unverifiable redaction into an apparently clean one; the check lives in `redact`, where its
    consequence is fail-closed. Findings are validated against the *original* text before any
    substitution, so a nested finding cannot fail the turn closed against a string this code changed.
- [x] Four sinks converted to take `RedactedText` (lose their `str` overload): `_log_shift`,
  `_log_nonlearning`, `debug_logger._fan_out`, the generation prompt; grading/perception prompts exempt;
  `_log_nonlearning`'s `safety_alert`-only redaction special case deleted.
  - **Plus a fifth, found during implementation:** the live analytics rows come from **five
    `interaction_control.log_event` call sites**, not from `tutor_loop`'s two helpers, which §6.3's table
    named by their pre-extraction line numbers. Same rows, same criterion, converted too.
  - The generation sink takes `GenerationText`, not `RedactedText`: §8 makes generation the one sink that
    fails **open**, so the type carries `redaction_confirmed` and the prompt gains an anti-echo
    instruction exactly when it is False. A silent `or raw_text` would have hidden the concession.
- [x] Fail closed on persistence, fail open on the child; **no retro-scrub**; write boundary on **fields,
  not turns** (no do-not-learn flag; `derive_*` runs normally); safety case record written stamped
  `privacy_unavailable`, a late verdict unions in; no separate privacy store.
  - `PersonalDataDispatch` has **no `late_verdict()`**, deliberately — compare `child_safety`, where one
    exists. §8 forbids the retro-scrub, so a verdict arriving after the sinks have written changes
    nothing, and offering the API would imply a promise the product cannot keep. The one late consumer
    the contract names is the safety case record, which is the safety side's store problem (12's
    carried-forward gap), not this package's.
- [ ] Child-facing: maths answer first always; one scripted line once per session; may never claim
  deletion; redaction unconditional, spoken correction waits for `AUTHORIZED`. **NOT DONE — see below.**
- [x] `eval/personal_data_eval.py` `--collect`/`--score`; per-class recall + hard precision gate on the
  ≥500-row maths-dense corpus; floors by reference to personal-data §12; no aggregate. `billed-personal-
  data` CI job behind the WIF Environment.
- [x] The two structural assertions that are the contract: `RedactedText` is unconstructable without a
  landed verdict; no raw identifier value appears in any `__str__`/`__repr__` (invariant 5).

## Not done, and why

- **The child-facing scripted line (§11) is not implemented.** `TurnRedaction.found` is the signal it
  needs and is threaded to Interaction Control, but the line itself is response-side: it must be appended
  *after* the maths answer, once per session, and gated on `AUTHORIZED` for the spoken half. That is the
  response layer's composition seam, which this slice does not touch and which has the same unowned
  status as §9's emergency-resource withholding on the safety side. Recorded rather than half-built: a
  scripted line appended in the wrong place is the derailment §11 forbids.
- **No number has been measured.** `--collect` needs WIF configured, the ten corpora signed off (all
  `review_scope: unreviewed`) and the model version pinned. Two of those three are hard blocks inside
  `--gate`. **Do not describe the detector as meeting the 0.80 floor or the 1% precision gate.**
- **`PERSONAL_DATA_ENABLED` defaults OFF.** The production construction site
  (`TutorLoopCompatibilityFacade`) is also what the offline suite drives, so a default of on would bill a
  Vertex call for every turn in `pytest` on any machine with working ADC. Off is §8's behaviour, not a
  broken build: every analytics row logs `[WITHHELD_NO_REDACTION]`. `wini_server` prints which state it
  booted in.

## Finding: an unconverted persisting sink the contract's inventory missed

**`session["context"]` writes the child's raw turn to `learner_state.json`.**
`InteractionContinuity.response_state_changes` appends `{"role": "student", "text": text[:250]}`
as a SESSION-scoped `StateChange`, so the learner-state document holds **up to eight raw learner
turns, verbatim**. Measured, not inferred — the checked-in `learner_state.json` contains them.

That contradicts §9's claim that learner state "holds no raw utterance text. Protected *by
construction*", which is the entire reason the parent dashboard was listed as needing no code
change. §6.3's inventory does not list this path either.

**Not converted, deliberately.** Unlike a log line, this text is load-bearing: it is the
conversation history the generation prompt reads and the `context[-2:]` window both model calls
read. §8's fail-closed rule would silently drop a turn out of the conversation whenever a verdict
was late — a functional regression the contract never weighed. Writing the *redacted* form
instead is probably right and is a **contract decision, not an implementation one**: it changes
what the tutor can remember about the child mid-lesson. Recorded at the site
(`interaction_control/control.py`, `InteractionContinuity`) and as a marked correction in
§6.3 of the contract. **Highest-value follow-on on this axis.**

## Known consequences carried forward (recorded, not fixed here)

- **The debug UI loses its live transcript view.** `voice/cloud_stt.py` emits `stt_done` with the raw
  transcript *before* Intake has run, so no verdict can exist for it and `_scrub` withholds it every
  time. That is §6.3 working as written — `debug_logger` is converted because it is SSE **and** disk —
  and the fix is for that call site to stop sending text, not for the sink to grant it an exemption.
- **`child_safety`'s gateway is still not wired into the production facade** (12 left it at the
  coordinator seam). Not this slice's to change — enabling it bills a call per turn — but it means the
  safety case record's new `privacy` field is exercised only in tests today.
- **`debug_logger` exists twice** (repo root and `cloud_run_service/`). Only the `cloud_run_service` copy
  is converted; the root copy belongs to the legacy local pipeline.
