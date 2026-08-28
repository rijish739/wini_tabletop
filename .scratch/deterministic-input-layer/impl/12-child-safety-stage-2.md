# 12 — `child_safety/` Stage 2 (vertical: dispatch → hold → compose → case-record → eval)

**What to build:** The complete primary-safety path: a dedicated Gemini call on every turn, perception
held until its verdict is analyzed, the verdict composed through the helper frozen in slice 01, a finding
that reaches the case record and never gets removed, and per-class recall measured against the blind
corpora. The lexicon is demoted to the outage net. `SAFETY_ROUTE_TAXONOMY.md` is normative; this ticket
carries seam-level facts only.

**Blocked by:** 05 (the unconfirmed/discarded stamps and the auth interplay), 09 (safety corpora), 10
(WIF), 11 (standing set green post-deletion).

**Status:** ready-for-agent

- [ ] New `cloud_run_service/child_safety/`, sibling of `perception/`; Gemini call **every turn,
  unconditionally**, parallel to perception (gating on a lexicon trip forbidden). Own prompt-of-record,
  schema, Vertex context cache, eval. `VERTEX_SAFETY_MODEL`/`VERTEX_SAFETY_LOCATION` default
  `gemini-2.5-flash@asia-south1` **version pinned**; `temperature=0`, `response_schema`,
  `thinking_budget=0`; empty text + `finish_reason=MAX_TOKENS` is a failure, never a negative verdict.
- [ ] 5s hard wall-clock + one retry in the same envelope, memoized on `utterance_id`; late verdicts
  still count and escalate.
- [ ] **Turn topology (the vertical seam):** safety dispatched first, perception immediately after,
  perception's output **held until the safety verdict is analyzed**, bounded by the 5s envelope, then
  released degraded with the `safety_model_unavailable` stamp. Invariant 6 asserted.
- [ ] The composition helper (frozen in slice 01) gains the model verdict; **its legacy-20 test file is
  not edited.** Model emits classes + imminence, union-only — never severity, never
  `caregiver_implicated`; severity derived at exactly one site, written by no detector; findings union,
  never subtract; the safety path reads neither `authorization` nor `TranscriptReading` (invariant 1).
- [ ] Lexicon demoted to degraded-net only: axis-only, `{UNSPECIFIED_CONCERN}`/`ELEVATED`, never
  `CRITICAL`, never a class; frozen + CI-maintained under its own floor; divergence net-vs-model published
  as **monitoring only**.
- [ ] Session hands the prompt a count + max severity (never classes, never text); sees
  `session["context"][-2:]`; class set never revised by history, severity may be raised never lowered. A
  safety trip suppresses the repair screen; low-confidence trip stamps `transcript_unconfirmed`, still
  writes/notifies; a `DISCARDED` finding survives stamped `transcript_discarded`; severity not capped.
- [ ] `eval/safety_eval.py` mirrors `--collect` (billed, resumable, one call/uncached row, cache keyed by
  prompt hash) / `--score` (offline); per-class recall against blind corpora; model / incremental / union
  recall published as three separate numbers, **no aggregate anywhere**; mixing caches across prompt
  hashes is a test failure. `billed-safety` CI job behind the WIF Environment.
- [ ] **Union cutover gate (billed once, stop-ship):** the union must trip on every utterance today's
  lexicon trips on. A class below floor stays out of the enum and is named in the release record and the
  not-covered statement. Turn-level property: a stubbed `CRITICAL` reaches the case record with perception
  held; a stubbed 5s timeout releases degraded with the stamp.
