# The Personal-Data Contract (NORMATIVE)

**Status: DECIDED 2026-08-27 (ticket 09, `/grilling`, 24 questions). IMPLEMENTED
2026-08-28 (ticket 13) — with two things NOT done, named here so nobody has to find them:**

1. **No number has been measured.** `eval/personal_data_eval.py` and the `billed-personal-data`
   CI job exist and are tested offline, but the billed collection has never run: it needs WIF
   configured, the ten corpora signed off (all are `review_scope: unreviewed`), and
   `VERTEX_PERSONAL_DATA_MODEL_VERSION` pinned. Two of those three are hard blocks inside the
   gate itself. **Do not describe this detector as meeting §12's 0.80 floor or its 1% precision
   gate. Neither has been measured.**
2. **The detector is not enabled by default.** `PERSONAL_DATA_ENABLED` defaults off, because
   the production construction site is also what the offline test suite drives and a default of
   on would bill a call per test turn. With it off the system behaves exactly as §8 says it
   should on a total outage: every persisting sink writes its structured fields and no
   transcript. Set `PERSONAL_DATA_ENABLED=1` in the Cloud Run environment.

What *is* implemented: `cloud_run_service/personal_data/` (call, prompt-of-record, schema,
context cache, redactor), the Turn Coordinator seam, and the sink conversion — `learning_log.jsonl`
can no longer receive the child's raw turn from any path. See §16 for the delta as it now stands.

**Owner:** `.scratch/deterministic-input-layer/issues/09-decide-the-personal-data-contract.md`
(the decision log — every rule here traces to a numbered question there).
**Evidence base:** `docs/architecture/PERSONAL_DATA_DETECTION_RESEARCH.md` (ticket 08).
**Upstream rulings:** `docs/architecture/SAFETY_ROUTE_TAXONOMY.md` §2, §14 (ticket 07).
**Requirements source:** `docs/archive/AI_Tutor_Child_Safe_Interaction_Specification.docx`
§2, §3, §11, §14.

> **This document is the contract a corpus author writes against.** If you are building the
> §12 evaluation corpora, read this file and **never** read the prompt. A corpus written by
> reading the prompt measures the prompt, not the requirement — that is exactly how the
> shipped 20-phrase safety probe came to report 1.0 recall while missing whole classes.
> This doc exists *because* §12's blind-authorship gate is unimplementable without a
> definitions document that is not the prompt.

---

## 1. What this is, and what it is not

Personal data is **off the safety axis entirely** (ticket 07 §2). Docx §14 lists it among six
"safety routes", but it is not a harm disclosure: §11's own handling is a gentle correction
that keeps teaching. It never produces a `SafetyClass`, never sets `safety_alert`, never
reaches the safeguarding case queue on its own, and never pauses the lesson.

It is an **annotation on an otherwise normal turn**: detect, redact, keep teaching.

§11 imposes three obligations that pull against each other. This contract satisfies each by a
different mechanism, and says which:

| §11 obligation | Mechanism | Where |
|---|---|---|
| **Redact before the sinks** | sinks are typed to accept only `RedactedText` | §6 |
| **Do not echo it back** | the generation prompt is built from redacted text | §6.3 |
| **Do not derail the lesson** | annotation, never a route; the maths answer always ships first | §1, §11 |

---

## 2. Architecture: a model is the only detector. There is no lexicon.

| | Safety (ticket 07) | Personal data (here) |
|---|---|---|
| Primary detector | a dedicated Gemini call | a dedicated Gemini call |
| Deterministic component | lexicon survives as the **outage net** | **none. No regex anywhere.** |
| On a Vertex outage | degraded detection, never zero | **zero detection** (§8) |
| Verdict may be late | yes, late verdicts still count | yes — lateness is the design (§8) |

**Why no lexicon, and why zero-on-outage is acceptable.** A disclosed phone number is not a
safety-critical event; nobody is on call for it. That is what buys the latitude a regex would
otherwise have to cover — and the regex is not merely unnecessary here, it is *harmful*. The
measured evidence (ticket 08 §3.3, MathEd-PII, arXiv:2602.16571) is that a generic pattern
detector scores **F1 = 0.379** on maths-tutoring dialogue, failing precisely by **eating the
maths**: "numeric expressions frequently resemble structured identifiers", and false redactions
"cluster in math-dense text regions". A maths tutor that redacts `3825` has broken the lesson,
which is the one §11 outcome that is unrecoverable. Domain-aware model prompting reaches
**0.80–0.82** on the same benchmark.

**The consequence, stated plainly rather than hidden:** with no deterministic component,
nothing in this system can protect a sink *in-turn*. Every sink is downstream of a verdict
that may be late or may never arrive. §8 is the whole answer to that, and it is the
load-bearing section of this document.

**Where the call sits.** Immediately **after** Utterance Intake — not at turn start. Redaction
is exact-match against `normalized_text` (§4), and Intake is what produces `normalized_text`.
Intake is pure, deterministic and sub-millisecond, so this costs nothing; but the ordering is
forced, not a preference.

---

## 3. The classes

Nine enum members. `OTHER_IDENTIFIER` is the honest residual and is **always** available.

A class **never** enters the enum until it clears **both** floors in §12. A known but unmet
class is recorded in the eval report and the map backlog — **never** as a silent enum member
that reports zero, because downstream that is indistinguishable from "this never happens".
(Inherited from ticket 07 §3.)

Each definition below is written for a corpus author. It says what the class *is*, not what any
pattern matches.

### 3.1 `NAME`

A person's name, the learner's own or anyone else's — a classmate, a sibling, a teacher. First
name alone counts. COPPA §312.2(1).

### 3.2 `SCHOOL`

The name of a school, class, section, or other institution the learner attends, or names as
someone else's. An institution name is a physical-locator identifier for a child.

### 3.3 `ADDRESS`

A home or other physical address, or any fragment of one specific enough to locate a dwelling —
street name, building name, flat number, locality. COPPA §312.2(2).

### 3.4 `LIVE_LOCATION`

Where the learner is *right now*, at a granularity that could bring someone to them. Distinct
from `ADDRESS`: "I'm at the park behind the market" is a live location and not an address.
COPPA §312.2(9).

**The tutor must never solicit a location** (docx §12: do not investigate). This class exists to
redact an unsolicited disclosure, never to harvest one — including on a safety turn, where
ERSS-112's location requirement is met by the human hand-off asking (ticket 07 §14).

### 3.5 `PHONE`

A telephone number, spoken or typed, the learner's own or anyone else's. COPPA §312.2(5).
**This is the collision class.** See §5.

### 3.6 `EMAIL`

An email address, or any other identifier permitting direct contact — a messaging handle, a
gamertag functioning as contact information, a VOIP identifier. COPPA §312.2(3),(4). Spoken
email arrives as words ("at", "dot"), not symbols.

### 3.7 `CREDENTIAL`

A password, PIN, OTP, access code, or answer to a security question.

**Detectable only by disclosure cue, never by shape** — a bare code is token-identical to a
maths answer, and no production detector ships a "secret in free text" recognizer (ticket 08
§5.6). A corpus author writing this class must write cued utterances ("my password is …"),
because the uncued case is not detectable by anything, and a corpus that contains it is
measuring an impossibility.

### 3.8 `GOVERNMENT_ID`

A government-issued identifier — Aadhaar, passport, birth-certificate or state-ID number.
COPPA §312.2(6); DPDP Rules 2025 Rule 10 makes these the highest-consequence class.

### 3.9 `OTHER_IDENTIFIER`

An identifier the learner disclosed that is plainly personal but fits no class above. The honest
residual. A verdict of `OTHER_IDENTIFIER` is a real finding and redacts normally.

### 3.10 Deliberately excluded

| Excluded | Why |
|---|---|
| `PERSISTENT_IDENTIFIER` (COPPA §312.2(7)) | Not a speech class. Device/session ids live in telemetry payloads; the remedy is not logging them beside a transcript, not a detector. |
| Photograph / video / **audio** (COPPA §312.2(8)), biometric (§312.2(10)) | Not transcript classes. The child's voice recording is personal information *before a word is transcribed* — a rule (§10), not code. No audio store exists to guard. |

---

## 4. What the verdict carries

The model returns, per finding, the **verbatim substring** of `normalized_text` to remove, plus
its class.

**Why verbatim, and not character spans or a rewritten string.** Spans leak no value, but LLMs
are unreliable at exact offset arithmetic and a wrong offset redacts the wrong half of a
sentence. A model-returned *rewrite* hands the model a licence to alter the arithmetic, which is
exactly the utility failure MathEd-PII measures. Verbatim substrings give deterministic,
auditable `str.replace` redaction — and, decisively, mean **there is no threshold and no shape
rule anywhere in this system**: we replace exactly what the model named and nothing else.

**The cost, and the rule that pays it.** The identifier now transits the model's structured
response. Therefore:

> **The verdict object is itself identifier-bearing. It is consumed by the redactor and
> dropped. It is never serialized, never logged, never a sink payload, and never reaches
> `debug_logger`. Only class labels survive it.**

`IdentifierFinding.__repr__` masks `value`. There is no `asdict` path, no `json.dumps` path, and
no `__str__` that reveals it. Ticket 14 carries an assertion that the raw value appears in no
emitted bytes.

**Fail closed on a miss.** If a named substring is not found in `normalized_text`, redaction has
failed and cannot be verified. The finding's **class** is still recorded, the turn is stamped
`redaction_incomplete`, and the sink receives **no transcript at all** — never one we could not
confirm we cleaned.

---

## 5. The numeric collision, and why this contract has no tie-break

The collision (ticket 08 §3.4) is that `9 x 25 x 17 = 3825` and a spoken phone number are the
same shape, and any threshold that spares one misses the other.

**This contract does not resolve the collision with a threshold, because it has none.**
Redaction is exact-match on a substring a maths-aware model named. A bare digit run is redacted
if and only if the model, having read the whole utterance, asserts that specific run is a phone
number. The tie-break the ticket asked for is therefore structural: **the maths is protected by
construction**, and the residual risk moves entirely onto the model — which is why §12 puts a
hard **precision** gate on a maths-dense corpus, not a footnote.

---

## 6. The redaction primitive and the sinks

### 6.1 The placeholder

A **typed, uppercase, un-indexed** placeholder in angle brackets: `<PHONE>`, `<SCHOOL>`,
`<GOVERNMENT_ID>`. Presidio's `replace` operator is the prior art (`<ENTITY_TYPE>`), and a typed
token is skippable by a maths parser where a blank or `****` re-introduces an ambiguous token
into the arithmetic.

- **Un-indexed.** Two names in one utterance both become `<NAME>`. The unit is one short spoken
  turn; distinguishing them has no consumer, and an index is exactly the field someone later
  makes *stable across turns* — at which point it is a persistent pseudo-identifier, COPPA
  class 7, reintroduced by a helpful refactor.
- **No digits, ever**, in any placeholder. `math_grade.normalize` must never be able to parse one
  as a number.

### 6.2 Enforcement is a type, not a discipline

Sinks accept `RedactedText` and **have no `str` overload**. `RedactedText` is constructible only
by the redactor, from `normalized_text` plus a landed verdict.

The evidence that discipline fails is already in the tree: `_log_nonlearning` redacts the
utterance on the safety branch and not on the ordinary one (`tutor_loop.py:1884`), and
`debug_logger._fan_out` serializes whatever it is handed to an SSE stream *and* to disk. Each of
these is a five-line log statement written by someone not thinking about §11, and the next one
will be too. §11 is an obligation that must survive the next person adding a log line.

### 6.3 The sink inventory — converted, and not

| Sink | Disposition | Why |
|---|---|---|
| `_log_shift` (`tutor_loop.py:1853`) | **converted** | writes `"question": text` raw today |
| `_log_nonlearning` (`tutor_loop.py:1881`) | **converted** | raw unless `safety_alert`; a privacy-only turn writes raw text to disk today |
| `debug_logger` (`_fan_out`) | **converted** | SSE **and** disk; unrecallable once emitted |
| **generation** prompt (B5 answer) | **converted** | the only sink that can **echo the identifier back to the child**; §11 obligation 2 is enforceable only if the generator never sees it |
| perception prompt | not redacted | Vertex-to-Vertex, same processor, no echo path; the raw turn already goes to Vertex for the detection call itself, so marginal exposure ≈ 0 |
| `child_safety` prompt | not redacted | same, and necessarily so |
| `personal_data` prompt | not redacted | it *is* the detector |
| **grading** prompt (`evidence/grading.py:58`, `LEARNER RESPONSE: …`) | not redacted | Vertex-to-Vertex; returns a verdict, not a spoken reply, so no echo path. **But its logged output must not quote the learner response.** |
| `_log_safety` (`tutor_loop.py:1863`) | unchanged | already SHA-256 hashes the utterance |
| **parent dashboard** / tutor-visible summaries | **no code change** | fed from learner state (`learner_state.py:635`, `analyzer.py:35`), which holds no raw utterance text. Protected *by construction* — and §9 makes that a rule instead of an accident |

> **CORRECTION, measured 2026-08-28 (ticket 13).** The last row's premise is **false**, and the
> row above it is incomplete.
>
> `session["context"]` is a SESSION-scoped state change written by
> `InteractionContinuity.response_state_changes`, and it lands in `learner_state.json`: **the
> learner-state document holds up to eight raw learner turns, verbatim.** "Learner state holds
> no raw utterance text" is not true today. (Whether any dashboard *reads* that field is a
> separate question this correction does not answer; the document contains it either way.)
>
> It was **not** converted by ticket 13, deliberately. Unlike a log line this text is
> load-bearing — it is the conversation history the generation prompt reads and the
> `context[-2:]` window both model calls read — so §8's fail-closed rule would silently drop a
> turn out of the conversation whenever a verdict was late. Feeding it the redacted form
> instead is probably right and is a **contract decision, not an implementation one**: it
> changes what the tutor can remember about the child mid-lesson. Recorded at the site in
> `interaction_control/control.py`. This is the highest-value open item on this axis.
>
> Also added by ticket 13, and not a correction so much as a completion: the live analytics
> rows come from **five `interaction_control.log_event` call sites**, not from `tutor_loop`'s
> two helpers named above. Same rows, same criterion; all five converted.

The criterion, stated once so future sinks can be classified without re-litigating: **a sink is
converted if it persists the turn, streams it, or can speak it back to the child.** A sink is
exempt only if it is a Vertex call with no echo path.

---

## 7. Two deadlines, one call

| Deadline | Bound | Missed ⇒ |
|---|---|---|
| **Generation** | opportunistic: generation waits only until it is otherwise ready to build its prompt, adding no wall-clock of its own | §8 fail-open |
| **Persisting sinks** | the full 5s envelope | §8 fail-closed |

Firing right after Intake buys the whole perception→retrieval span as headroom, so the verdict
usually lands before generation needs it **without adding a millisecond**. That is the entire
latency argument; it does not depend on the model being fast.

---

## 8. Late, or never: fail closed on persistence, fail open on the child

This is the load-bearing section. With no deterministic detector (§2), every sink is downstream
of a verdict that may not arrive.

**Persisting sinks fail CLOSED.** `RedactedText` cannot be constructed without a landed verdict.
With no verdict, the analytics/telemetry/debug sinks receive their structured fields and **no
transcript**. Losing a log line costs nothing; persisting a child's phone number costs
everything. A Vertex outage therefore degrades to transcript-free logs — the correct shape of
"zero detection" for something nobody is on call for.

**Generation fails OPEN.** It cannot run without the text. A late verdict means generation
proceeds on unredacted text and the anti-echo obligation falls back to a prompt instruction for
that turn. This is a deliberate, accepted §11 concession: echoing a number back to the child who
just said it aloud is a breach with near-zero marginal harm, while persistence is the harm §11
is actually about.

**No retro-scrub, ever.** You cannot recall an SSE frame or a shipped log line. A retro-scrub is
a promise the product cannot keep, and docx §2's "no pretend capabilities" applies to what we
tell ourselves in an architecture document, not only to what we tell the child.

**Late is normal, not exceptional.** A verdict landing at 4.9s produces fully redacted logs and
no correction (§11). Nothing is retried, escalated, or alerted on.

---

## 9. The write boundary

- **No identifier value is written anywhere.** Ever. See §4 and §10.
- **The turn's ordinary analytics row carries `privacy_classes: [ADDRESS]`** — class labels only
  — and nothing else.
- **There is no separate privacy-event store.** A standing list of *"this child disclosed an
  address on this date"* is itself a behavioural record of a child — the thing DPDP §9(3) bans —
  built in the name of privacy, with no consumer. Detector quality is measured from §12's
  corpora, never harvested from production.
- **No `personal_data` field may enter learner state or any personalisation path.** This is the
  docx §3 boundary, applied to *fields, not turns* — see §9.1. It is also what protects the
  parent dashboard (§6.3), so it is a rule here rather than a happy accident.
- **This contract does not replicate the safety-side violation.** Ticket 07 measured
  `safety_alerts` written into the learner state document beside `evidence_ledger`
  (`legacy_adapter.py:441`), which §11's "separate learning progress from safety records"
  forbids. Nothing in `personal_data` may follow that pattern.

### 9.1 There is no "do not learn from this turn" flag

The ticket asked whether a personal-data turn carries one. **It does not.**

Docx §3's boundary bans *safety case data* from entering mastery, confidence, hope, engagement
and personalisation — and ticket 07 took personal data **off the safety axis entirely**. The
maths in *"my number is 98765, anyway the answer is 12"* is legitimately pedagogical.
Suppressing the learning write would punish the child for disclosing and silently lose the
lesson, which is the derailment §11 forbids.

The boundary is on **fields**, not turns: no class label and no identifier value reaches learner
state, and `derive_*` / `apply_deltas` run on the turn like any other.

### 9.2 Interaction with a safeguarding case

Ticket 07 §14 ruled that where personal data co-occurs with a safety trip, the case record
carries identifier **class labels** (`ADDRESS_PRESENT`), never raw values. That makes the case
record a consumer of this verdict.

**The safety case record never waits for it.** It is written with the privacy field stamped
`privacy_unavailable` — 07's own `safety_model_unavailable` convention — and a late verdict
**unions in** (add-only, 07 §6). A safeguarding case must not be delayed by an annotation about
a phone number, and 07 already established that an honest `unknown` is acceptable while a
fabricated value is a stop-ship.

---

## 10. Retention: detect and redact, nothing reversible

- `Utterance.text` is raw by contract (ticket 02), and docx §9 forbids overwriting transcript
  provenance. It lives **in memory, for the turn**. It is never persisted, never serialized, and
  crosses no process boundary except the Vertex calls §6.3 permits.
- **No vault, no key, no reversible placeholder.** Presidio ships `encrypt` and `hash` operators;
  both are rejected. A reversible redaction is a retention of the identifier wearing a costume,
  and the key becomes a second thing to govern.
- The §11 carve-out — "a minimised, access-controlled case reference where a legal/safeguarding
  process requires review" — is satisfied **in full** by 07's class labels on the case record
  (§9.2). Nothing else needs the value.
- **Media rule (no code today).** No raw audio and no child-identifying image may be attached to
  any ordinary sink, ever. COPPA §312.2(8) makes the child's voice recording personal information
  before transcription. There is no audio store to guard and the display contract carries
  metadata only (`wini_server.py:47`), so this is a sentence that costs nothing now and stops
  someone attaching a waveform to a telemetry event next quarter.

---

## 11. What the child hears

**The maths answer always ships first.** Then, at most **once per session**, one short scripted
line appended after it.

- **Fires on the model finding.** There is no high-precision second source to gate on (§2). The
  false-positive cost is bounded by the ordering: a misfire is a slightly puzzling extra sentence
  attached to a correct maths answer — not a derailed lesson, which is the failure §11 actually
  forbids.
- **Once per session, not per turn.** A child who names their school three times is not lectured
  three times.
- **Skipped entirely when the verdict is late** (§8 fail-open). Never delivered a turn later, out
  of context.
- **Truthfulness (docx §2).** It may honestly assert only that the tutor does not need personal
  details and that the child should keep them out of the lesson. It may **not** claim the
  disclosure was deleted, forgotten, or not recorded — the product did not do those things.
- It **never asks for more identifying detail**, and never asks a follow-up about the disclosure.

---

## 12. Evaluation

Two corpora. Both **authored blind against §3's definitions, by someone who has never read the
prompt** (ticket 07's rule, and the reason this document exists).

| Corpus | Size | Measures | Gate |
|---|---|---|---|
| **Per-class disclosure** | ≥50 rows per class of §3 | per-class recall | **≥ 0.80 per class** |
| **Maths-dense precision** | ≥500 rows from `dataset/exemplar_dataset_10000_fixed.json` + ticket 14's golden set, containing **zero** identifiers — any finding is a false positive | false-positive rate | **≤ 1%** |

- **The recall floor is 0.80 because that is what the state of the art achieves.** MathEd-PII's
  domain-aware ceiling is 0.80–0.82. A floor above the published ceiling is a gate that never
  goes green, which in practice means a gate that gets waived.
- **The precision gate is hard, not advisory.** Over-redaction is the failure that breaks the
  product; the maths corpus is where §5's residual risk is actually measured.
- The disclosure corpus **must** include split-across-turns cases (§14) and cued `CREDENTIAL`
  cases only (§3.7).
- **Re-run both before any prompt / schema / model / region / cache / version change**
  (CLAUDE.md's standing rule for model-backed detectors — a model's recall moves silently in ways
  a regex's never did).
- **Publish no aggregate number anywhere.** Per-class only. An aggregate is how the safety side
  came to report a meaningless 1.0.

---

## 13. Operational seams

- Package: **`cloud_run_service/personal_data/`** — a sibling of `perception/` and
  `child_safety/`. Holds the call, the prompt-of-record, the schema, the context cache, the
  redactor, and the eval. *Not* `privacy/`: a module named `privacy` implies it owns consent,
  retention and deletion, none of which it does, and over-claiming in a package name is how an
  obligation comes to be assumed met.
- `RedactedText` lives **in that package, not in `runtime/contracts.py`.** Sinks import it to
  accept it; the constructor is a module-level factory taking `normalized_text` + a landed
  verdict. In `contracts.py` it becomes something anyone can build from a bare string — the type
  reduced back to discipline.
- `VERTEX_PERSONAL_DATA_MODEL` / `VERTEX_PERSONAL_DATA_LOCATION`, defaulting to
  **`gemini-2.5-flash@asia-south1`**, version **pinned**. Not flash-lite (measured slower, and a
  cross-border hop for children's data under DPDP). Any flip is gated on re-running §12, never on
  latency.
- `thinking_config(thinking_budget=0)` — CLAUDE.md's empty-response gotcha.
- **5s hard wall-clock + one immediate retry inside the same envelope.** Plus §7's opportunistic
  generation deadline.
- **Its own Vertex context cache**, same fallback semantics as `perception/vertex_cache.py`:
  recreate after a schema rebuild or TTL expiry, and fall back automatically to the full system
  prompt when absent/expired/stale. The static block (nine definitions + the maths-protection
  instructions) is byte-identical every turn and is the largest part of the prompt. A cache
  change re-runs §12.

---

## 14. Context

The call sees **one preceding exchange** (`session["context"][-2:]`), the same as the safety
call. It is the only thing that catches the split disclosure — the tutor asks something and the
child answers *"it's 98765"*, which without context is indistinguishable from an answer and
**must** be left alone.

> **Findings may only name substrings of the current utterance.** Context is evidence, never a
> redaction target. The previous turn has already been through its own sinks, and letting a
> finding reach backwards implies the retro-scrub §8 forbids.

The call is not in Utterance Intake, so ticket 03's pure-of-session rule is not violated.

---

## 15. Types

```python
class IdentifierClass(str, Enum):
    NAME             = "NAME"
    SCHOOL           = "SCHOOL"
    ADDRESS          = "ADDRESS"
    LIVE_LOCATION    = "LIVE_LOCATION"
    PHONE            = "PHONE"
    EMAIL            = "EMAIL"
    CREDENTIAL       = "CREDENTIAL"
    GOVERNMENT_ID    = "GOVERNMENT_ID"
    OTHER_IDENTIFIER = "OTHER_IDENTIFIER"

class VerdictStatus(str, Enum):
    LANDED      = "LANDED"       # the model answered within its envelope
    UNAVAILABLE = "UNAVAILABLE"  # timeout, retry exhausted, or outage

@dataclass(frozen=True)
class IdentifierFinding:
    identifier_class: IdentifierClass
    value: str        # verbatim substring of normalized_text.
                      # IDENTIFIER-BEARING: never serialized, never logged.
                      # __repr__ masks it; there is no asdict path.

@dataclass(frozen=True)
class PersonalDataVerdict:
    utterance_id: str
    status: VerdictStatus
    findings: frozenset[IdentifierFinding]   # always empty when UNAVAILABLE

@dataclass(frozen=True)
class RedactedText:
    text: str                                # placeholders substituted
    classes: tuple[IdentifierClass, ...]     # labels only — the sink payload

def redact(normalized_text: str,
           verdict: PersonalDataVerdict) -> RedactedText | None:
    """The ONLY constructor of RedactedText.

    Returns None when the sink must write no transcript at all:
      - verdict.status is UNAVAILABLE (§8 fail-closed), or
      - a finding's value is not found in normalized_text (§4 fail-closed).
    """
```

---

## 16. Delta from the shipped code

Every row below is **done** as of ticket 13 (2026-08-28) unless marked otherwise.

| Was | Is now |
|---|---|
| **no detector at all**; a grep for `redact` / `PII` / `personal_data` over `cloud_run_service/**` found only safety-log tier labels | a dedicated Gemini call in `cloud_run_service/personal_data/`, dispatched by the Turn Coordinator immediately after Intake |
| `_log_shift` wrote `"question": text` verbatim | takes `RedactedText` or `None`; no `str` overload |
| `_log_nonlearning` redacted **only** when `safety_alert` was set — a privacy-only turn wrote raw text to disk | takes `RedactedText` or `None`; the safety special case is gone, and `log_tier` records which rule withheld the transcript (`safety_withheld` / `privacy_withheld` / `general`) |
| `debug_logger._fan_out` serialized anything to SSE + disk | `_scrub` runs first: a transcript field holds a `RedactedText` or it is withheld |
| the generation prompt was built from the raw turn | built from `GenerationText` — the redacted form when a verdict landed, the raw turn plus an anti-echo instruction when none did (§8 fail-open) |
| nothing distinguished "no identifiers found" from "we never looked" | `VerdictStatus.UNAVAILABLE`, and the sink writes no transcript |
| `PrivacyReading` was a required slot on `UtteranceObservation` (ticket 03) | **deleted** — Intake is model-free and cannot fill it; six readings became five (§17) |

**Added by the implementation, beyond the table above.** §6.3's sink inventory was written
against `tutor_loop`'s line numbers, and by the time it was implemented the live analytics rows
came from **five `interaction_control.log_event` call sites** — the same rows, written from the
post-extraction code. §6.3's own criterion (*a sink is converted if it persists the turn,
streams it, or can speak it back to the child*) covers them, so they were converted too. The
rule followed the rows, not the line numbers.

**The safety case record's `privacy` field is now real.** It was a hardcoded
`"privacy_unavailable"` literal; it now carries `<CLASS>_PRESENT` labels from the landed
verdict, and the literal only when none landed (§9.2).

---

## 17. Amendments this document makes elsewhere

| Artifact | Amendment |
|---|---|
| `.scratch/…/issues/03-define-the-input-observation-contract.md` | `PrivacyReading` slot **deleted**; six required readings become **five**. Stronger than 07's amendment, which kept `safety: SafetySignals` because the lexicon still runs inside Intake — personal data has no deterministic component at all. |
| `docs/architecture/SAFETY_ROUTE_TAXONOMY.md` §2 | the personal-data row points at `PrivacyReading`, a type that no longer exists — repointed here. |
| `docs/architecture/SAFETY_ROUTE_TAXONOMY.md` §14 | the privacy paragraph gains the `privacy_unavailable` stamp and the never-wait rule (§9.2). |
| `.scratch/…/issues/16-write-the-implementation-spec.md` | two bullets were wrong: "redaction sinks **and their order**" (there is no order — there is a four-site conversion list, §6.3) and "the do-not-learn-from-this-turn rule" (there is none, §9.1). |
| `CLAUDE.md` | one short pointer under the gotchas. Not a second safety-sized block. |

**The four-document lockstep rule does not fire.** This contract changes no schema, dataset,
model or store contract owned by `learner_cognitive_state_architecture.md`,
`RAG_upgrade_plan.md`, `model_dataset_architecture_report.md`, or
`complete_architecture_build_plan.md`. The map's standing open item — which lockstep documents
this effort *as a whole* must update, and whether they move out of `docs/archive/` first — stays
with ticket 16, along with the `rag_memory.md` work-log entry.
