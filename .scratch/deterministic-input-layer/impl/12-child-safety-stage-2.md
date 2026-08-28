# 12 — `child_safety/` Stage 2 (vertical: dispatch → hold → compose → case-record → eval)

**What to build:** The complete primary-safety path: a dedicated Gemini call on every turn, perception
held until its verdict is analyzed, the verdict composed through the helper frozen in slice 01, a finding
that reaches the case record and never gets removed, and per-class recall measured against the blind
corpora. The lexicon is demoted to the outage net. `SAFETY_ROUTE_TAXONOMY.md` is normative; this ticket
carries seam-level facts only.

**Blocked by:** 05 (the unconfirmed/discarded stamps and the auth interplay), 09 (safety corpora), 10
(WIF), 11 (standing set green post-deletion).

**Status:** done — code complete, offline-green (407 passed). **Two things are deliberately NOT done and
are named below: the billed cutover run, and late-verdict collection.**

- [x] New `cloud_run_service/child_safety/`, sibling of `perception/`; Gemini call **every turn,
  unconditionally**, parallel to perception (gating on a lexicon trip forbidden). Own prompt-of-record,
  schema, Vertex context cache, eval. `VERTEX_SAFETY_MODEL`/`VERTEX_SAFETY_LOCATION` default
  `gemini-2.5-flash@asia-south1` **version pinned**; `temperature=0`, `response_schema`,
  `thinking_budget=0`; empty text + `finish_reason=MAX_TOKENS` is a failure, never a negative verdict.
  - *Pinning caveat:* `VERTEX_SAFETY_MODEL_VERSION` defaults **empty** on purpose — a version id is a
    fact about the Vertex catalog at deploy time and inventing one would put an unverified string into
    every case record. Empty means *honestly unpinned*, is recorded as `model_pinned: false` in every
    case and eval record, and is a **hard block** in `--cutover`.
- [x] 5s hard wall-clock + one retry in the same envelope, memoized on `utterance_id`; late verdicts
  still count and escalate.
  - *Collection caveat:* `late_verdict()` + `union_late` are implemented and tested, but **no runtime
    caller collects a late verdict.** Doing so needs a case store that can update an already-written
    record; today's sink is a session dict + a `notify_safety` callback, neither revisable after
    release. Recorded in `dispatch.py`'s module docstring. The gap is in the store, not this package.
- [x] **Turn topology (the vertical seam):** safety dispatched first, perception immediately after,
  perception's output **held until the safety verdict is analyzed**, bounded by the 5s envelope, then
  released degraded with the `safety_model_unavailable` stamp. Invariant 6 asserted.
- [x] The composition helper (frozen in slice 01) gains the model verdict; **its legacy-20 test file is
  not edited.** Model emits classes + imminence, union-only — never severity, never
  `caregiver_implicated`; severity derived at exactly one site, written by no detector; findings union,
  never subtract; the safety path reads neither `authorization` nor `TranscriptReading` (invariant 1).
- [x] Lexicon demoted to degraded-net only: axis-only, `{UNSPECIFIED_CONCERN}`/`ELEVATED`, never
  `CRITICAL`, never a class; frozen + CI-maintained under its own floor; divergence net-vs-model published
  as **monitoring only**.
- [x] Session hands the prompt a count + max severity (never classes, never text); sees
  `session["context"][-2:]`; class set never revised by history, severity may be raised never lowered. A
  safety trip suppresses the repair screen; low-confidence trip stamps `transcript_unconfirmed`, still
  writes/notifies; a `DISCARDED` finding survives stamped `transcript_discarded`; severity not capped.
- [x] `eval/safety_eval.py` mirrors `--collect` (billed, resumable, one call/uncached row, cache keyed by
  prompt hash) / `--score` (offline); per-class recall against blind corpora; model / incremental / union
  recall published as three separate numbers, **no aggregate anywhere**; mixing caches across prompt
  hashes is a test failure. `billed-safety` CI job behind the WIF Environment.
- [x] **Union cutover gate (billed once, stop-ship):** the union must trip on every utterance today's
  lexicon trips on. A class below floor stays out of the enum and is named in the release record and the
  not-covered statement. Turn-level property: a stubbed `CRITICAL` reaches the case record with perception
  held; a stubbed 5s timeout releases degraded with the stamp.
  - *Run caveat:* the gate is **implemented and tested, and has NOT been run.** It cannot be, from here:
    it needs WIF configured, the corpora signed off (all 10 are `review_scope: unreviewed`), and the
    model version pinned. Two of those three are hard blocks inside the gate itself. **No safety recall
    number has been measured. Do not describe the model as meeting any floor.**

## Known violations carried forward (recorded, not fixed here)

- **§14 write boundary, widened.** The case record still goes to
  `session["__learner_safety_alerts__"]` → the learner document that holds `evidence_ledger`. §14 already
  names that placement a violation with a backlog ticket; slice 12 made the *payload* wider (`classes`,
  `findings`, `evidence_id`s — exactly §14's "only to the safeguarding case record" fields). Documented at
  the write site in `control.py`. **The fix is the case-store move, not trimming the record** — §14.1
  requires those fields for a reviewer. Highest-value follow-on.
- **§15 gains a fifth `model_status`.** `"unavailable"` = no detector was wired, distinct from a call that
  ran and failed. Reusing `"error"` would assert a failure that never happened (§12). `_stamps` now
  distinguishes `safety_model_unavailable` (real outage) from `no_safety_detector` (nothing ran).
- **§9's emergency-resource script withholding is not implemented.** The taxonomy withholds the CRITICAL
  script until the §12 direct question is answered. That is response-side; this slice owes the record and
  the notification, both of which it delivers. Unowned — needs a ticket.
- **`_CAREGIVER_RE` is new lexicon content** (added earlier in this branch, required by §4.1) and is not
  covered by the §8 freeze corpus, which freezes axis trips only. It cannot affect an axis trip. Worth a
  freeze row set of its own.
- **Nested executors.** `child_safety`'s pool submits into `llm_vertex`'s shared pool; queue time is
  charged to the 5s envelope. Fails toward `TIMEOUT` (a non-answer), never toward a false negative.
  Documented in `dispatch.py`.
