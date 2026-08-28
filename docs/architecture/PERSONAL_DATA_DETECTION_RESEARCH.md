# Personal-Data Detection & Redaction for a Children's Maths Tutor (Research)

**Status:** research notes feeding ticket 09 (the detector contract). **This document
decides nothing.** Ticket 09 owns the detector contract, the placeholder schema, and the
implementation choice. This is the reading legwork behind it: *what* identifier classes
the spec obliges us to detect, *how detectable* each is from short conversational STT text,
*what the numeric collision is* (maths numbers vs phone/identifier digits), and *what
"redact before analytics" concretely requires* at each of the five sinks §11 names.

**Scope note.** The requirement under study is spec §11: *"Detect and redact obvious
identifiers before ordinary analytics, telemetry, prompts, screenshots and tutor-visible
summaries."* The codebase currently has **no** such detector (confirmed: no PII/redaction
module exists under `cloud_run_service/`; `stt_confidence` and the evidence ledger are the
only privacy-adjacent surfaces). So every claim here is grounded in external primary
sources, not repo state.

**Conventions used throughout:**
- **[S]** = a claim a primary source states. URL given inline.
- **[I]** = **my inference / reasoning.** Not asserted by any source.
- **[R]** = reasoned from domain knowledge, no single citable source.

**Bottom line up front:**

1. **Three statutes/guidances jointly fix the class list.** India's **DPDP Act 2023 §9**
   bans *tracking and behavioural monitoring of children* outright (not just identifier
   collection) and bans processing "likely to cause any detrimental effect on the
   well-being of a child" **[S]**. **COPPA (16 CFR §312.2)** enumerates the concrete
   identifier classes and — decisively for a *voice* tutor — counts **"a photograph, video,
   or audio file where such file contains a child's image or voice"** and **persistent
   identifiers** as personal information in their own right **[S]**. **UNESCO** frames the
   duty at the point of the learning loop and sets an age-13 floor for independent GenAI use
   **[S]**.
2. **The identifier classes reliably detectable from short conversational text split into
   two tiers.** *Structured* classes (phone, email, government ID, IP, credit-card) are
   regex/validator-detectable with high precision **when a delimiter/format survives**;
   *unstructured* classes (name, school, street address, "where I live now", photo
   reference) need NER/context and are materially less reliable in one short turn **[S]**.
3. **The numeric collision is real and measured.** A maths-tutoring PII benchmark
   (**MathEd-PII**, arXiv:2602.16571) reports **Presidio baseline F1 = 0.379** on maths
   tutoring dialogue, with false redactions clustering in maths-dense regions, because
   "numeric expressions frequently resemble structured identifiers" **[S]**. Domain-aware
   detection lifts F1 to **0.80–0.82** **[S]**.
4. **The collision is designed-around, not designed-out, in production detectors.**
   Presidio's `PhoneRecognizer` assigns a **base score of only 0.4** to a
   `phonenumbers`-validated match and needs nearby **context words** ("call", "number",
   "phone") to clear a usable threshold **[S]**; Google DLP uses the same *positive-context*
   proximity boost and five likelihood buckets **[S]**. A bare `9 x 25 x 17 = 3825` has no
   such context and *should* sit at low likelihood — but a spoken-digit phone number
   ("nine eight seven six...") equally lacks context, so a threshold tuned to spare maths
   will also miss the spoken phone number. That trade-off is the core research finding for
   ticket 09.
5. **Typed redaction is the established way to redact-yet-preserve.** Presidio's default
   `replace` operator substitutes a **typed placeholder** `<ENTITY_TYPE>` (e.g.
   `<PHONE_NUMBER>`) rather than blanking **[S]** — the prior art for a token that a
   downstream maths parser can skip without losing the arithmetic around it.

---

## 1. The requirement, verbatim, and what "identifier" is obliged to mean

Spec §11: *"Detect and redact obvious identifiers before ordinary analytics, telemetry,
prompts, screenshots and tutor-visible summaries."* The spec says **"obvious identifiers"**
but does not enumerate them. The enumerations that legally bind a children's product in the
two relevant jurisdictions are below; §2 turns them into a class list.

**[I]** Two structural facts shape everything downstream:
- The tutor's input is **STT output of a child's speech**. Spoken identifiers arrive as
  *words or digit-words*, not as formatted strings — "eight nine seven six five..." not
  "89765...". This defeats the delimiter/format assumptions that make structured-PII regex
  precise (§3).
- The tutor is a **maths** tutor, so numeric-dense turns are the *norm*, not the exception —
  the opposite of the enterprise-document setting these detectors were tuned on (§4).

---

## 2. (a) The identifier classes the spec obliges us to handle, each tied to its source

### 2.1 India — DPDP Act 2023 §9 and DPDP Rules 2025

The Act does not enumerate identifier *types*; it defines **personal data** broadly and then
imposes **conduct** limits on children's data. A "child" is anyone **under 18**
(DPDP Act §2(f)) **[S]**, and personal data is "any data about an individual who is
identifiable by or in relation to such data" (§2(t)) **[S]** — i.e. the obligation is not
keyed to a fixed identifier list at all.

Section 9, verbatim
([DPDP Act §9, dpdpa.com](https://www.dpdpa.com/dpdpa2023/chapter-2/section9.html);
[Indian Kanoon](https://indiankanoon.org/doc/98869575/)) **[S]**:

- **§9(1):** "The Data Fiduciary shall, before processing any personal data of a child ...
  obtain verifiable consent of the parent ... in such manner as may be prescribed."
- **§9(2):** "A Data Fiduciary shall not undertake such processing of personal data that is
  likely to cause any **detrimental effect on the well-being of a child**."
- **§9(3):** "A Data Fiduciary shall not undertake **tracking or behavioural monitoring of
  children** or targeted advertising directed at children."

**[I]** §9(3) is the provision that matters most for §11's *analytics/telemetry* sinks: it
bans the behaviour, not merely the storage of a name. A per-child behavioural analytics
stream *is* "behavioural monitoring." So "redact before analytics" is, for India, a floor,
not the ceiling — the harder DPDP question is whether the analytics should exist per-child
at all. §9(2)'s "detrimental effect" is the standard the whole pipeline is measured against.

**DPDP Rules 2025** (notified **13 November 2025**
([Bar & Bench](https://www.barandbench.com/view-point/meity-notifies-final-digital-personal-data-protection-rules-2025))) **[S]**.
- **Rule 10** requires "appropriate technical and organisational measures to ensure that
  verifiable consent of the parent is obtained before the processing of any personal data of
  a child," with adult/guardian verification via reliable identity+age details or a virtual
  token from an authorised entity (incl. Digital Locker)
  ([Rule 10, dpdpa.com](https://www.dpdpa.com/dpdparules/rule10.html)) **[S]**.
- **Fourth Schedule** carves out limited exemptions from §9(1)/§9(3). For an
  **Educational Institution**, "Processing is restricted to tracking and behavioural
  monitoring: **for the educational activities** of such institution; or **in the interests
  of safety** of children enrolled" and Part B permits processing "**to the extent
  necessary** ... for ensuring that information likely to cause any detrimental effect on the
  well-being of a child is not accessible to her"
  ([Fourth Schedule, dpdpa.com](https://www.dpdpa.com/schedule/schedule4.html)) **[S]**.

**[I]** This exemption is narrow and does **not** dissolve §11. It permits *educational*
tracking and *safety* monitoring "to the extent necessary" — it does not permit leaking a
child's phone number, home address, or a classmate's name into analytics/prompts/
screenshots. §11's redact-at-the-sink duty survives the exemption intact; the exemption only
addresses the *pedagogical* tracking the tutor does by design, not the *incidental
identifiers* §11 targets.

### 2.2 United States — COPPA, 16 CFR §312.2

COPPA enumerates the classes directly. "Personal information" means individually
identifiable information collected online, including
([16 CFR §312.2, eCFR](https://www.ecfr.gov/current/title-16/chapter-I/subchapter-C/part-312/section-312.2);
text mirrored at [govregs](https://www.govregs.com/regulations/title16_chapterI_part312_section312.2)) **[S]**:

| # | COPPA class (§312.2) | Verbatim | Spoken-turn relevance |
|---|---|---|---|
| 1 | Name | "A first and last name" | child says own/classmate name |
| 2 | Address | "A home or other physical address including street name and name of a city or town" | "I live on ..." |
| 3 | Online contact info | "an email address or any other substantially similar identifier that permits direct contact ... including ... instant messaging user identifier, a voice over Internet Protocol (VOIP) identifier, ... or a mobile telephone number" | child reads out an email/handle |
| 4 | Screen/user name | "A screen or user name where it functions in the same manner as online contact information" | a gamertag |
| 5 | Telephone number | "A telephone number" | **spoken digits — the collision case** |
| 6 | Government ID | "A government-issued identifier, such as a Social Security, State identification card, birth certificate, or passport number" | Aadhaar/ID read aloud |
| 7 | Persistent identifier | "A persistent identifier that can be used to recognize a user over time and across different websites or online services" | device/session IDs in telemetry |
| 8 | **Photo/video/audio** | "A photograph, video, or **audio file where such file contains a child's image or voice**" | **the raw STT audio itself** |
| 9 | Geolocation | "Geolocation information sufficient to identify street name and name of a city or town" | "I'm at ..." / live location |
| 10 | Biometric | "A biometric identifier that can be used for the automated or semi-automated recognition of an individual" | voiceprint from the audio |
| 11 | Combined info | information about the child/parents the operator collects online and combines with an identifier above | any of the above + a session key |

**[I]** Classes 8 and 10 are the ones a text-only PII detector forgets: **the child's voice
recording is itself personal information under COPPA, before a single word is transcribed.**
That reframes §11's "screenshots" and "telemetry" sinks — an audio clip or a waveform
attached to a telemetry event is COPPA personal information regardless of transcript
redaction. (FTC has a standing enforcement-policy statement specifically on the collection
and use of children's **voice recordings**, confirming audio is treated as PII, not merely
its transcript
([FTC 16 CFR Part 312 voice-recordings enforcement policy](https://www.ftc.gov/policy/federal-register-notices/16-cfr-part-312-enforcement-policy-statement-regarding-applicability)) **[S]**.)

### 2.3 UNESCO — the duty at the learning loop

UNESCO's *Guidance for generative AI in education and research* (2023) puts the obligation at
the point of collection in the learning interaction. It states that "The absence of national
regulations on GenAI in most countries leaves the **data privacy of users unprotected** and
educational institutions largely unprepared to validate the tools"
([UNESCO article](https://www.unesco.org/en/articles/guidance-generative-ai-education-and-research)) **[S]**,
and its regulatory steps include "mandating the protection of data privacy" and "setting an
age limit for the independent conversations with GenAI platforms," proposing **age 13** as
the minimum for classroom use of GenAI **[S]** (also reported at
[UN News](https://news.un.org/en/story/2023/09/1140477)).

**[I]** UNESCO does not enumerate identifier types — it is not that kind of instrument. Its
contribution to §11 is *where*: the redaction duty attaches inside the tutoring loop, before
data leaves the child's turn for any secondary use, and the age-13 floor tells us the data
subjects are squarely children (Wini targets school-age maths learners), so the strict
COPPA/DPDP-child regimes both apply rather than the general-population baseline.

### 2.4 The consolidated class list §11 must cover

**[I]** Merging the three, the classes an "obvious identifier" detector is *obliged* to
consider — the union, tagged with the strongest source:

| Class | Obliged by | Detectable from one short STT turn? (see §3) |
|---|---|---|
| Full/first name (self or classmate) | COPPA §312.2(1); DPDP personal data | Hard — NER, low precision on one turn |
| School / institution name | COPPA (physical-org identifier) [I]; DPDP | Hard — NER + gazetteer |
| Home/physical address | COPPA §312.2(2) | Medium — cue words + NER |
| Live/geo-location ("where I am now") | COPPA §312.2(9) | Medium — cue words |
| Phone number | COPPA §312.2(5) | **Structured but collides with maths digits** |
| Email address | COPPA §312.2(3) | Easy — `@`/domain regex survives STT poorly |
| Password / access code / OTP | COPPA (combined) [I]; DPDP | **Hard — a bare digit/letter string, indistinguishable from an answer** |
| Government ID (Aadhaar, passport) | COPPA §312.2(6); DPDP Rule 10 | Structured (checksum) but collides with digits |
| Persistent identifier / device id | COPPA §312.2(7) | In telemetry, not speech — infra concern |
| Photo reference / the audio itself | COPPA §312.2(8),(10) | Not a transcript class — a *sink* concern (§5) |

---

## 3. (b) Detectability of each class from short conversational STT text

### 3.1 The two-tier reality

Presidio (Microsoft's reference PII toolkit) documents the split explicitly: **structured,
high-format** entities use **pattern/regex + validation (checksum)**; **unstructured**
entities (person, location, org) use **NER** and context
([Presidio supported entities](https://presidio.dataprivacystack.org/supported_entities/)) **[S]**.
Google DLP's built-in detectors combine "pattern matching, checksum validation, machine
learning, and context analysis"
([Google DLP infoTypes](https://docs.cloud.google.com/sensitive-data-protection/docs/concepts-infotypes)) **[S]**.

**[I]** Two properties of *this* input break the structured tier's usual precision:
- **STT strips the format.** A phone number spoken as digit-words has no dashes, no
  parentheses, no country prefix — the very features `phonenumbers` validates on. Email `@`
  becomes the word "at"; a slash becomes "over" (cf. the maths-STT research). So the *high
  precision* the structured tier enjoys on typed documents is **not transferable** to a
  spoken-digit transcript without an STT-normalisation step first.
- **Short turns starve NER of context.** The unstructured tier (name/school/address) leans
  on surrounding words; a one-clause child utterance gives little.

### 3.2 Per-class detectability

| Class | Primary method | Detectability from one STT turn | Evidence |
|---|---|---|---|
| **Email** | regex `@`+TLD | High *if* symbols survive STT; STT usually renders "at"/"dot" as words → **needs reconstruction** | Presidio EMAIL_ADDRESS is pattern-based **[S]** |
| **Phone** | `phonenumbers` validate + context | **Low base confidence by design** (SCORE 0.4); needs context words → **the collision, §4** | Presidio PhoneRecognizer **[S]** |
| **Government ID** | regex + checksum (Luhn/Verhoeff) | Medium — checksum helps *if* digit run is clean; spoken digits mis-transcribe | Presidio validators; DLP checksum **[S]** |
| **Password / code / OTP** | — | **Effectively undetectable in isolation** — a bare token is shape-identical to a maths answer | **[R]**; no detector class exists for "a secret" |
| **Name** | NER (PERSON) | Low–medium on one turn; false negatives on rare/Indian names | Presidio PERSON is NER **[S]**; NER degrades on short text **[R]** |
| **School / org** | NER (ORG) + gazetteer | Low — ORG NER is the weakest common class | **[R]** grounded in Presidio ORG being NER **[S]** |
| **Address** | NER (LOCATION) + cue words | Medium with "live on/at" cues | Presidio LOCATION is NER **[S]** |
| **Live location** | cue words + LOCATION | Medium; "where I am right now" is a cue, not a pattern | **[R]** |
| **Persistent id / audio / photo** | n/a for transcript | Not a transcript-detection problem — a **sink** problem (§5) | COPPA §312.2(7),(8) **[S]** |

### 3.3 Published precision/recall — lexical (regex) vs model (NER), and on maths text

**General PII (not maths):** the field-wide pattern is that **regex/pattern detectors are
high-recall, lower-precision** on numeric/structured classes (they fire on anything
digit-shaped), while **NER detectors trade recall for precision** on named entities and are
the weak link on org/location. Presidio's own design encodes this: it *lowers* a raw
pattern hit's confidence unless context confirms it (phone base score **0.4**), rather than
trusting the regex
([Presidio PhoneRecognizer source, `SCORE = 0.4`](https://github.com/microsoft/presidio/blob/main/presidio-analyzer/presidio_analyzer/predefined_recognizers/generic/phone_recognizer.py)) **[S]**.

**On maths text specifically** — the directly on-point measurement:

> **MathEd-PII** (Zhou, Vanacore, ... Kizilcec, arXiv:2602.16571): *"the first benchmark
> dataset for PII detection in math tutoring dialogues."* Numeric expressions "frequently
> resemble structured identifiers," causing generic PII detection to **over-redact**
> educational content. Reported **F1**: **Presidio baseline 0.379**; math-aware LLM prompting
> **0.802**; segment-aware LLM prompting **0.821**. False redactions "cluster in math-dense
> text regions."
> ([arXiv abstract](https://arxiv.org/abs/2602.16571) / [PDF](https://arxiv.org/pdf/2602.16571)) **[S]**

**[I]** The Presidio-baseline **F1 = 0.379 on maths dialogue** is the single most important
number for ticket 09: an off-the-shelf detector is worse than a coin-flip's-worth of useful
here, and the failure mode is precisely the one §11 must avoid — **eating the maths**. The
2× jump to ~0.82 comes only from making the detector *domain-aware* (knowing it is looking at
maths), which is a design constraint on the detector contract, not a tuning knob.

### 3.4 The numeric-collision problem, concretely

**The mechanism.** Structured-identifier detectors (phone, SSN, credit-card) are, at core,
"a run of N digits, maybe with separators." A maths turn is *made of* digit runs:
- `63 km in 3 hours` — two short digit runs.
- `9 x 25 x 17 = 3825` — a four-digit run (`3825`) that is exactly telephone/PIN-shaped.
- `x = 2` — trivial, but `x = 91234` is a 5-digit run.
- A spoken product like "nine hundred and eighty-seven thousand..." STT-renders as a long
  digit string that a phone regex will match.

**Why detectors *mostly* survive this on normal text but not here.** Both Presidio and
Google DLP defend precision with **positive context / proximity**:
- Presidio's `LemmaContextAwareEnhancer` *raises* a match's score by
  `context_similarity_factor = 0.35` **only** when a context lemma (e.g. "phone", "call",
  "number") appears within `context_prefix_count = 5` words; the phone base score is **0.4**,
  and the floor with context is `min_score_with_context_similarity = 0.4`
  ([Presidio LemmaContextAwareEnhancer defaults](https://github.com/microsoft/presidio/blob/main/presidio-analyzer/presidio_analyzer/context_aware_enhancers/lemma_context_aware_enhancer.py)) **[S]**.
- Google DLP: "*Positive context* is when the inclusion of certain characters, words, or
  phrases in proximity to a potentially matched pattern indicates ... that a match to the
  pattern is more likely," scored across five buckets VERY_UNLIKELY→VERY_LIKELY
  ([DLP infoTypes](https://docs.cloud.google.com/sensitive-data-protection/docs/concepts-infotypes)) **[S]**.

**[I] The trap this creates for a maths tutor is symmetric and unavoidable at the digit
level:**
- `9 x 25 x 17 = 3825` has **no** phone context word nearby → both detectors leave `3825` at
  **low likelihood** → correctly *not* redacted. Good.
- **But a child reciting a real phone number** ("my number is nine eight seven...") *also*
  arrives with little reliable context after STT, and the digits are the same shape. A
  threshold set high enough to spare `3825` will, on the identical evidence, **miss** the
  spoken phone number. A threshold set low enough to catch the phone number will **eat the
  maths** (the F1 = 0.379 outcome).
- The only signals that break the tie are **outside the digit run**: (i) an explicit lexical
  cue ("my number is", "call me on"), (ii) **length/structure priors** (a validated
  10-digit Indian mobile starting 6–9 vs. a 4-digit product), (iii) **the active maths
  concept** (if the turn is a rate/word problem, digit runs are answers), and (iv) STT
  **N-best/confidence** on the digit span. **[I]** This is why the literature's winning
  approach is *segment-aware* — decide first whether a span is a maths span or a
  conversational span, then apply identifier detection only to the latter.

**[R]** A concrete precision hazard worth flagging to ticket 09: Indian mobile numbers are
10 digits beginning 6/7/8/9, and `phonenumbers` with region `IN` (a Presidio default region)
*will* validate a clean 10-digit run — so `1234567890`-shaped maths answers (rare but
possible in place-value / large-number lessons) are exactly the false-positive class, while
digit runs broken by "x"/"="/"km" are exactly the true-negatives a naive regex would still
grab.

---

## 4. (c) What "redact before analytics" means at each of the five §11 sinks

§11 names five sinks. **[I]** They differ in *what* leaks, *what redaction preserves*, and
*whether the raw audio (COPPA class 8) is implicated*, so the redaction contract is not one
operation applied five times.

### 4.1 The redaction primitive: typed placeholder, not blanking

The established prior art for "redact but keep the sentence usable" is **typed replacement**.
Presidio's default `replace` anonymizer, given no explicit value, substitutes the entity's
**type in angle brackets**:

> `return f"<{params.get('entity_type')}>"` — Presidio `Replace` operator
> ([replace.py](https://github.com/microsoft/presidio/blob/main/presidio-anonymizer/presidio_anonymizer/operators/replace.py)) **[S]**

So "call me on 987..." → "call me on `<PHONE_NUMBER>`", not "call me on ▮▮▮". Presidio also
ships `redact` (delete), `mask` (partial `****`), `hash`, and `encrypt` operators
([Presidio anonymizers](https://presidio.dataprivacystack.org/)) **[S]**, and the MathEd-PII
work's whole thesis is that **utility preservation** (not deleting the maths) is the metric
that matters in this domain **[S]**.

**[I]** For a maths tutor the typed-token choice is load-bearing: a downstream maths parser
(cf. the repo's `math_grade` normaliser) can be taught to treat `<PHONE_NUMBER>` as an opaque
non-number and skip it, whereas a blank or a `****` re-introduces an ambiguous token into the
arithmetic. The *design* of that placeholder (typed? span-preserving? reversible under a
key?) is ticket 09's call — this document only records that typed-over-blanked is the
standing prior art and why it fits maths.

### 4.2 Sink-by-sink

| Sink (§11) | What leaks if unredacted | What redaction must preserve | Audio (COPPA cl.8) implicated? |
|---|---|---|---|
| **1. Ordinary analytics** | Per-child identifiers entering aggregate metrics — and, under **DPDP §9(3)**, the *behavioural stream itself* | Aggregability: counts/rates must survive; the maths signal (correctness, concept) must not be redacted away | Only if raw clips are logged as events |
| **2. Telemetry** | Identifiers + **persistent ids** (COPPA cl.7) in event payloads; crash logs quoting the transcript | Debuggability: shape/length of the turn, error context | **Yes** — waveforms/clips attached to telemetry are PII pre-transcript |
| **3. Prompts** | The child's raw turn sent to Gemini/Vertex carries names, phone, address into a third-party LLM | Pedagogical meaning: the maths content and the *intent* must reach the model intact | No (text prompt), but a voice-in model would ingest the audio |
| **4. Screenshots** | On-panel echo of the transcript, or a displayed number the child dictated; **the panel image itself** | Legibility of the maths on the card | **Yes** — an image is COPPA cl.8 the same as audio if it shows identifying content |
| **5. Tutor-visible summaries** | A human tutor/teacher seeing "Riya, phone 987..., struggles with fractions" — re-identification of the child to a person | The *pedagogical* summary (what concept, what misconception) — which is exactly what a tutor needs | No |

**[I]** Three cross-cutting points ticket 09 will need to weigh:

1. **Analytics/telemetry (sinks 1–2) are the DPDP §9(3) pressure point**, not just a
   redaction target. Redacting a name out of a per-child behavioural time-series does not
   make the *time-series* compliant if it constitutes "behavioural monitoring." Redaction is
   necessary but may not be sufficient for these two sinks. **[S]** (§9(3)).
2. **Prompts (sink 3) are the one sink where over-redaction directly breaks the product** —
   strip too much and the model cannot tutor. This is where the F1 = 0.379 over-redaction
   failure is most costly, and where *segment-aware* (maths-span-preserving) redaction is not
   optional. **[S]** (MathEd-PII).
3. **Screenshots and telemetry (sinks 2, 4) can carry COPPA class-8 media** (audio clip,
   panel image) that a *transcript* redactor never sees. §11's "redact before ... screenshots
   ... " therefore implies a media-handling rule (do not attach raw audio/child-identifying
   images to secondary sinks), distinct from text redaction. **[S]** (16 CFR §312.2(8)).

### 4.3 Ordering ("before")

**[I]** §11's word is *before*. The detector must run **at the boundary of each secondary
use**, on the already-STT-normalised turn, and *after* the maths-span segmentation that
protects the arithmetic — i.e. redaction sits between "we understood the turn for tutoring"
and "we copied any part of it into a sink." Placing it before segmentation reproduces the
0.379 over-redaction; placing it after any sink defeats §11. The exact placement in the
pipeline is ticket 09's contract to draw.

---

## 5. Open questions / could not fully verify from primary sources

1. **No published *digit-run* false-positive rate isolated for phone-vs-maths.** The
   MathEd-PII F1 figures are the closest primary measurement and are maths-tutoring-specific,
   but I did not find a source isolating "phone regex FP rate as a function of digit-run
   length in maths text." Ticket 09 should measure this locally against the repo's own maths
   corpus (ticket 14's golden set is the natural substrate).
2. **eCFR served behind bot-protection.** The §312.2 verbatim text is quoted from the eCFR
   via a mirror ([govregs](https://www.govregs.com/regulations/title16_chapterI_part312_section312.2));
   the class wording matches the FTC's own rule text and the 2025 amended Rule. Re-verify
   against [ecfr.gov](https://www.ecfr.gov/current/title-16/chapter-I/subchapter-C/part-312/section-312.2)
   directly before quoting in a compliance artefact.
3. **DPDP Fourth Schedule wording** is quoted from dpdpa.com's reproduction, not the Gazette
   PDF (MeitY). The substance (education/safety-limited exemption, "to the extent necessary")
   is consistent across the secondary analyses read, but the authoritative text is the
   13 Nov 2025 Gazette notification — verify there before relying on exact phrasing.
4. **UNESCO age-13 and data-privacy passages** are quoted from the official UNESCO *article*
   page; the full 2023 Guidance PDF (UNESDOC ark:/48223/pf0000386693) returned 403/binary on
   fetch, so I could not pull page-level quotes from the primary PDF. The age-13 recommendation
   is corroborated by [UN News](https://news.un.org/en/story/2023/09/1140477).
5. **Whether Presidio's phone base score / context defaults are still current** — quoted from
   `main` branch source on GitHub (2026-08). Pin a release tag before citing exact constants
   in an implementation doc.
6. **"Password/OTP" has no detector class anywhere** — Presidio, DLP, and spaCy do not ship a
   "secret/credential in free text" recognizer; a bare code is shape-identical to a maths
   answer. **[R]** This is flagged as a genuine detection gap, not a solved class — ticket 09
   should treat "child dictates a password/OTP" as detectable only via lexical cue ("my
   password is"), never via the token's shape.

---

## 6. Sources

**Primary — statute / regulation / official guidance:**
- **DPDP Act 2023 §9** (verifiable consent; detrimental-effect ban §9(2); tracking &
  behavioural-monitoring ban §9(3)): https://www.dpdpa.com/dpdpa2023/chapter-2/section9.html
  and https://indiankanoon.org/doc/98869575/ — authoritative on India's *conduct* limits for
  children's data.
- **DPDP Rules 2025, Rule 10** (technical/organisational measures for verifiable parental
  consent; adult verification): https://www.dpdpa.com/dpdparules/rule10.html — notified
  13 Nov 2025 (https://www.barandbench.com/view-point/meity-notifies-final-digital-personal-data-protection-rules-2025).
- **DPDP Rules 2025, Fourth Schedule** (education/safety-limited exemptions from §9(1)/(3);
  "to the extent necessary"): https://www.dpdpa.com/schedule/schedule4.html — defines the
  narrow ed-tech carve-out and its limits.
- **COPPA, 16 CFR §312.2 "Personal information"** (the enumerated identifier classes,
  incl. audio-with-child's-voice, persistent identifier, geolocation, biometric):
  https://www.ecfr.gov/current/title-16/chapter-I/subchapter-C/part-312/section-312.2
  (text mirror: https://www.govregs.com/regulations/title16_chapterI_part312_section312.2) —
  the authoritative *enumeration* of identifier types for a US-facing children's product.
- **FTC enforcement-policy statement on children's voice recordings** (audio treated as PII):
  https://www.ftc.gov/policy/federal-register-notices/16-cfr-part-312-enforcement-policy-statement-regarding-applicability
- **UNESCO, *Guidance for generative AI in education and research* (2023)** (data-privacy
  duty in the learning loop; age-13 floor):
  https://www.unesco.org/en/articles/guidance-generative-ai-education-and-research
  (corroboration: https://news.un.org/en/story/2023/09/1140477) — authoritative on *where* the
  privacy duty attaches for GenAI in education.

**Primary — technical detection / redaction (docs, source, benchmark):**
- **MathEd-PII benchmark** (Zhou et al., arXiv:2602.16571) — Presidio baseline F1 0.379 vs
  domain-aware 0.80–0.82 on maths tutoring dialogue; the numeric-collision failure mode:
  https://arxiv.org/abs/2602.16571 — the on-point measured evidence for maths-vs-identifier
  collision.
- **Microsoft Presidio — supported entities** (which classes are regex vs NER):
  https://presidio.dataprivacystack.org/supported_entities/
- **Presidio `PhoneRecognizer` source** (`phonenumbers` library; base `SCORE = 0.4`; context
  words; default regions incl. IN):
  https://github.com/microsoft/presidio/blob/main/presidio-analyzer/presidio_analyzer/predefined_recognizers/generic/phone_recognizer.py
  — authoritative on how a production detector deliberately *distrusts* a bare digit match.
- **Presidio `LemmaContextAwareEnhancer` source** (context boost 0.35, prefix window 5, min
  score 0.4): https://github.com/microsoft/presidio/blob/main/presidio-analyzer/presidio_analyzer/context_aware_enhancers/lemma_context_aware_enhancer.py
- **Presidio `Replace` anonymizer source** (typed placeholder `<ENTITY_TYPE>`):
  https://github.com/microsoft/presidio/blob/main/presidio-anonymizer/presidio_anonymizer/operators/replace.py
  — the prior art for redact-preserving-utility.
- **Google Cloud Sensitive Data Protection (DLP) — infoTypes & detection** (positive-context
  proximity boost; five likelihood buckets; pattern+checksum+ML+context):
  https://docs.cloud.google.com/sensitive-data-protection/docs/concepts-infotypes — a second
  independent production detector confirming the context-dependence of numeric-identifier
  precision.
