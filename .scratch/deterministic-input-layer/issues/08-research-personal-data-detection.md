# Research: personal-data detection in child maths speech

Status: resolved
Type: research
Blocked by: —

## Question

Docx §11 requires: "Detect and redact obvious identifiers before ordinary analytics,
telemetry, prompts, screenshots and tutor-visible summaries." **Nothing in the codebase does
this** — a grep for `redact|PII|personal_data|phone_number` across `cloud_run_service/**/*.py`
returns only safety-log tier labels (`tutor_loop.py:1909`, `control.py:917`) and
`baseline_oracle` test fixtures. There is no detector.

The hard part is domain-specific: **this is a maths tutor.** A child's turn is full of bare
numbers. "63 km in 3 hours", "9 x 25 x 17 = 3825", "x = 2" must not trip a phone-number or
identifier detector, and a detector tuned to avoid that will miss a spoken phone number.
Docx §9 compounds it — STT output of spoken digits is exactly the ambiguous case.

Research targets:

- India DPDP Act 2023 §9 (docx source [8]) and the current DPDP Rules materials: what counts
  as a child's personal data, and what "detrimental processing" and tracking limits require
  at the point of collection.
- FTC COPPA FAQ (source [9]): the enumerated categories — note it includes **audio
  recordings** and **persistent identifiers** as personal information.
- UNESCO guidance for generative AI in education (source [4]) on data privacy in the
  learning loop.
- Practical detection: what identifier classes are reliably detectable from short
  conversational text (name, school, address, phone, email, password/code, live location,
  photo reference); published precision/recall for lexical vs. model-based approaches; how
  existing PII detectors handle numeric-dense text.
- Prior art on redaction that preserves downstream utility — what a redacted token must carry
  so the maths still parses.

Deliverable: a Markdown findings file capturing (a) the identifier classes the spec obliges
us to handle, (b) detectability and the numeric-collision problem with evidence, (c) what
"redact before analytics" means concretely at each of the five sinks §11 names.

Do **not** decide the contract here — ticket 09 owns that.

---

## Resolution (2026-08-26)

Findings: `docs/architecture/PERSONAL_DATA_DETECTION_RESEARCH.md`. Consumed by ticket 09,
which decided the contract (`docs/architecture/PERSONAL_DATA_CONTRACT.md`).
