# Decide the personal-data contract

Status: resolved
Type: grilling
Blocked by: 08, 07

## Question

What does the Input Layer do when a child discloses personal information?

Docx §11 sets three obligations that pull in different directions:

1. **Detect and redact before the sinks** — "ordinary analytics, telemetry, prompts,
   screenshots and tutor-visible summaries."
2. **Do not echo it back** — "do not repeat it back, ask for more identifying details, or
   make a false promise that it was deleted."
3. **Do not derail the lesson** — §11's own student-facing script is a gentle correction, not
   an escalation. But §14 lists personal data as one of the six safety routes.

Decisions to close:

- **Route or annotation?** Is personal-data disclosure a *route* (short-circuits the turn to
  a scripted privacy reply, like SAFETY does today) or an *annotation* on an otherwise normal
  turn (redact, continue teaching)? §11's example reply suggests route; §11's "a child should
  never need to disclose personal information to get help with a concept" suggests the maths
  ask should still be answered. Resolve — and note this is the same shape as the
  unconsumed-`also_learning` bug the map ruled out of scope.
- **Redact where?** The prompt sent to Gemini is one of §11's five sinks. Redacting before
  the model call changes what the model sees and could break concept resolution. Redacting
  only at the logging boundary leaves the prompt unredacted. Which sinks, in what order?
- **Detect-only vs. redact vs. both**, and does the un-redacted text survive anywhere?
  §11 permits "a minimised, access-controlled case reference where a legal/safeguarding
  process requires review" — so the answer is not simply "never retain".
- **The numeric collision.** Ticket 08 will quantify it. Decide the false-positive policy: a
  maths tutor that redacts "3825" has broken the lesson. What is the tie-break?
- **The data boundary.** Docx §3: "Safety case data must not be written into mastery,
  confidence, 'hope', engagement, or future personalisation features." Today a SAFETY turn
  short-circuits before the analyzer, so nothing is written — but a personal-data turn that
  *continues* to learning would flow into `derive_*`/`apply_deltas`. Does the Input Layer
  carry a "do not learn from this turn" flag, and who enforces it?
- **Truthfulness.** §2, "No pretend capabilities": the reply must not claim deletion the
  product did not perform. What can the layer honestly assert?

Blocked on 07 as well as 08, because whether personal data is a safety route is decided there.

---

## Rulings handed down by ticket 07 (2026-08-26)

07 is resolved; three of 09's open questions are now partly answered by it. 09 still owns
`PrivacyReading`'s internals, the sink order, and the numeric-collision policy.

1. **Route or annotation — settled: annotation.** Personal data is **off the safety axis
   entirely**. Docx §14 lists it as one of six "safety routes", but it is not a harm
   disclosure: §11's own handling is a gentle correction that keeps teaching, and routing it
   to SAFETY would make every phone number pause the lesson. It never produces a
   `SafetyClass`, never sets `safety_alert`, and never reaches the safeguarding case queue on
   its own.

2. **Personal data co-occurring with a safety trip — settled.** Redaction holds
   **unconditionally** at every ordinary sink (analytics, telemetry, prompts, screenshots,
   tutor-visible summaries). The safeguarding case record is *not* an ordinary sink — §11
   permits "a minimised, access-controlled case reference" — but in v1 it carries identifier
   **class labels** (`ADDRESS_PRESENT`, `SCHOOL_PRESENT`), **never raw values**. ERSS-112's
   location requirement is met by the human hand-off asking, not by the tutor harvesting, and
   **the tutor must never solicit a location** (§12: do not investigate).

3. **The data boundary — reinforced.** 07's write boundary applies to safety fields; 09 still
   owns the "do not learn from this turn" question for a personal-data turn that continues to
   learning. Note 07 measured a live violation on the safety side: `safety_alerts` is written
   into the learner state document beside `evidence_ledger` (`legacy_adapter.py:441`), which
   §11's "separate learning progress from safety records" forbids. Moving it is a backlog
   ticket; 09 should not replicate the pattern for privacy events.

See `docs/architecture/SAFETY_ROUTE_TAXONOMY.md` §2 and §14.

---

## Resolution (2026-08-27, /grilling — 24 questions over 4 rounds)

**Normative output: `docs/architecture/PERSONAL_DATA_CONTRACT.md`.** It is the artifact a
corpus author and an implementing agent both read; `spec.md` (ticket 16) should **reference**
rather than restate it, exactly as 07's taxonomy is referenced.

The organizing decision, from which everything else falls out: **a model is the only detector.
There is no regex, no lexicon, and no deterministic component anywhere on this path** (user,
round 2 — "phone number is not safety critical, it can be done by the AI slowly"). That trades
away in-turn protection and accepts zero detection during a Vertex outage, in exchange for not
shipping the measured F1 = 0.379 maths-eating failure mode.

### The decisions

| # | Question | Ruling |
|---|---|---|
| Q1 | Route or annotation, and who detects | **Annotation** (07). Detection is **model-only** — no regex net, unlike safety. |
| Q2 | Sink enforcement | **A type, not a discipline.** Sinks take `RedactedText` and have no `str` overload. |
| Q3 | Does un-redacted text survive | **No vault, no key, no reversibility.** Raw lives in memory for the turn only. 07's class labels are the whole of §11's carve-out. |
| Q4 | "Do not learn from this turn" flag | **No such flag.** The boundary is on **fields, not turns** — no class label or value in learner state; `derive_*` runs normally. |
| Q5 | Child-facing behaviour | Maths answer first, always; one scripted line, **once per session**; may not claim deletion. |
| Q6 | Deferral under UNAUTHORIZED / DISCARDED | **Split by consequence.** Redaction unconditional; the correction waits for `AUTHORIZED`. |
| Q7 | Media (COPPA class 8) | **Rule, no code.** No audio store exists; display is metadata-only. |
| Q8 | Which Gemini call | **Its own**, in `personal_data/`, fired right after Intake. Eval independence decided it — riding perception or safety makes every privacy prompt tweak re-bill their evals. |
| Q9 | What the verdict carries | **Verbatim substrings.** Not spans (LLM offset arithmetic), not a rewrite (licence to alter the maths). The verdict object is identifier-bearing and never serialized. Fail closed on a substring miss. |
| Q10 | Where the verdict lives | **`PrivacyReading` is deleted from `UtteranceObservation`.** Intake is model-free and structurally cannot fill it; a permanently-unfillable required field is a lie in the type. Six readings become five. |
| Q11 | Late or absent verdict | **Fail closed on persistence, fail open on the child.** No transcript in logs without a verdict; generation proceeds unredacted rather than leaving the child unanswered. **No retro-scrub** — unrecallable sinks make it a promise we cannot keep. |
| Q12 | The correction, with no precision gate left | **Keep it**, fire on the model finding; the FP cost is bounded to one odd sentence after a correct answer. |
| Q13 | Class list + floors | **9 classes** + `OTHER_IDENTIFIER`. 07's "no class below its floor" inherited, pointed at **both** axes: per-class recall **and** a hard precision gate. |
| Q14 | Placeholder | Typed, uppercase, **un-indexed**, digit-free. An index becomes a cross-turn pseudo-identifier the moment someone makes it stable. |
| Q15 | Prior-turn context | **One preceding exchange**, same as safety — the only thing that catches the split disclosure. Findings may name only the current utterance. |
| Q16 | Seams and budget | Mirror 07: `flash@asia-south1`, pinned, `thinking_budget=0`, 5s + one retry. **Two deadlines**: opportunistic for generation, full envelope for the sinks. |
| Q17 | Persistence of privacy events | **Class labels on the analytics row; no separate store.** A privacy-event store is itself a DPDP §9(3) behavioural record of a child, with no consumer. |
| Q18 | Safety case record's dependency | **Never waits**; stamped `privacy_unavailable`, late verdict unions in. |
| Q19 | Sinks in scope | **Four sites**: the two `learning_log.jsonl` writers, `debug_logger`, the generation prompt. Grading and perception prompts exempt (Vertex-to-Vertex, no echo); the parent dashboard is protected by construction and gets a rule instead of code. |
| Q20 | Corpora | Two, blind-authored: per-class disclosure (≥50/class, recall ≥ 0.80) and maths-dense precision (≥500 rows, FP ≤ 1%). No aggregate number published. |
| Q21 | Package and type placement | `cloud_run_service/personal_data/` — not `privacy/`, which would over-claim consent/retention/deletion. `RedactedText` stays in-package so only the redactor can construct one. |
| Q22 | Context cache | **Yes**, own cache, `perception/vertex_cache.py` fallback semantics. |
| Q23 | Deliverable | **Its own normative doc** — Q20's blind-authorship gate is unimplementable without a definitions document that is not the prompt. |
| Q24 | Amendment set | 03, taxonomy §2 + §14, ticket 16, map, one CLAUDE.md pointer. **Four-doc lockstep does not fire.** |

### Things this resolution deliberately did not do

- It did **not** decide the false-positive tie-break the ticket asked for, because the design
  removed the need: with no threshold and no shape rule, the maths is protected by construction
  and the residual risk sits entirely on the model, where §12's precision gate measures it.
- It did **not** define a sink *order*. There is no order — there is a four-site conversion list
  and one criterion (persists / streams / can speak it back).

### Backlog spawned

- The grading prompt's logged output must not quote `LEARNER RESPONSE` — a one-line fix at
  `evidence/grading.py`, out of this effort's scope.
- 07's existing backlog item (moving `safety_alerts` out of the learner state document,
  `legacy_adapter.py:441`) is reinforced, not duplicated, by §9's write boundary.
