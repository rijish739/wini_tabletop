# 13 — `personal_data/` Stage 3 (vertical: detect → redact → sinks → eval)

**What to build:** The complete personal-data path: a model-only detector fires immediately after Intake,
redacts by exact-match on `normalized_text`, and the sinks take a redacted type no `str` can satisfy and
fail closed. The system never claims it deleted something it cannot delete. `PERSONAL_DATA_CONTRACT.md`
is normative; this ticket carries seam-level facts only.

**Blocked by:** 09 (PII corpora), 10 (WIF), 12 (Stage 2 complete — safety-first ordering; its case
record is a consumer of this verdict but never waits on it).

**Status:** ready-for-agent

- [ ] New `cloud_run_service/personal_data/`, sibling of `perception/` and `child_safety/`; Gemini call
  fired **immediately after Intake** (redaction is exact-match on `normalized_text`). **Model-only — no
  regex, no lexicon, no outage net**; a Vertex outage means zero detection, made safe by fail-closed sinks.
- [ ] `VERTEX_PERSONAL_DATA_MODEL`/`_LOCATION` default `gemini-2.5-flash@asia-south1` version pinned;
  `thinking_budget=0`; 5s + one retry; context one preceding exchange; **two deadlines** — opportunistic
  for the child's answer, the full envelope for the sinks.
- [ ] Verdict carries **verbatim substrings** (not spans, not a rewrite); identifier-bearing and **never
  serialized**; fail closed on a substring miss. `RedactedText` lives in the `personal_data` package;
  exact-match redaction with typed, uppercase, **un-indexed, digit-free** placeholders; no threshold, no
  shape rule (maths protected by construction).
- [ ] Four sinks converted to take `RedactedText` (lose their `str` overload): `_log_shift`,
  `_log_nonlearning`, `debug_logger._fan_out`, the generation prompt; grading/perception prompts exempt;
  `_log_nonlearning`'s `safety_alert`-only redaction special case deleted.
- [ ] Fail closed on persistence, fail open on the child; **no retro-scrub**; write boundary on **fields,
  not turns** (no do-not-learn flag; `derive_*` runs normally); safety case record written stamped
  `privacy_unavailable`, a late verdict unions in; no separate privacy store.
- [ ] Child-facing: maths answer first always; one scripted line once per session; may never claim
  deletion; redaction unconditional, spoken correction waits for `AUTHORIZED`.
- [ ] `eval/personal_data_eval.py` `--collect`/`--score`; per-class recall + hard precision gate on the
  ≥500-row maths-dense corpus; floors by reference to personal-data §12; no aggregate. `billed-personal-
  data` CI job behind the WIF Environment.
- [ ] The two structural assertions that are the contract: `RedactedText` is unconstructable without a
  landed verdict; no raw identifier value appears in any `__str__`/`__repr__` (invariant 5).
