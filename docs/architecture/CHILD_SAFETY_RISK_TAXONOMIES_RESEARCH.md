# Child-Safety Risk Taxonomies for Input-Side Routing (Research)

**Status:** research notes feeding ticket 06
(`.scratch/deterministic-input-layer/issues/06-research-child-safety-risk-taxonomies.md`).
**This document decides nothing.** Ticket 07 owns the decision on whether — and how — to
split today's single broad SAFETY route into six. This ticket only gathers the evidence
ticket 07 will weigh.
**Scope:** the three deliverables the ticket names — (a) a candidate six-way taxonomy with a
one-line *detectability* verdict per route, (b) the known failure modes of lexical
detection, each with a citation, (c) what each route must carry downstream for a hand-off to
be actionable.

**Conventions used throughout:**
- **[S]** = a claim a primary source states. URL given inline.
- **[M]** = a claim **measured in this repo** during this research (probe/file:line shown).
  Read-only; no production code changed. **No billed evals were run** (see §3, note 1).
- **[I]** = **my inference / reasoning.** Not asserted by any source.
- Codebase claims carry `file.py:line`.

**Bottom line up front:**

1. Today's gate collapses the whole safety domain into **three outcomes across two tiers**,
   decided by **one regex per tier**: tier 3 `urgent_danger`, tier 2 `protected_disclosure`,
   tier 2 `safety_concern` (`cloud_run_service/perception/gates.py:81-93`). The docx §14
   six-way split (personal data, ordinary distress, harassment/threat, abuse/violence,
   imminent danger, uncertain-STT safety) is a **strictly finer** partition than the code
   can currently express. **[M]**
2. Established taxonomies **converge on the same coarse cuts** the docx names — self-harm vs.
   abuse-disclosure vs. peer harassment vs. imminent danger vs. commercial/data risk — but
   they are **case-classification schemes for trained human counsellors**, not detectors.
   Child Helpline International, the 4Cs (Livingstone & Stoilova), Ofcom's Online Safety Act
   content categories, and the Lifeline call-log taxonomy (Turkington et al.) all carve the
   space; **none of them claims the cut is drawable from one utterance.** **[S]**
3. Of the six routes, **at most two are cleanly detectable deterministically from a single
   utterance** (personal-data disclosure; uncertain-STT-flagged safety, which is a
   *metadata* condition not a content one). The other four are **partially** detectable at
   the coarse "something is wrong" level and **not** reliably separable from each other on
   one turn — the distinction abuse-vs-distress-vs-threat routinely needs *who did what to
   whom*, which one utterance often does not carry. **[I]**
4. Lexical detection has **four documented, repeatable failure modes** — indirect/implicit
   disclosure, negation and third-person framing, euphemism/code-switching, and the
   explicit-content dependency — and the peer-reviewed crisis-text literature says the
   **majority of true-positive at-risk users rarely post explicitly**. A lexicon's recall
   ceiling is therefore structural, not a tuning problem. **[S]**
5. The repo's own lexicon was measured at **0.75 recall** with named gerund/oblique misses
   (CLAUDE.md). That number must be **re-measured directly** with
   `python -m eval.perception_eval --gates`, never inferred; I did **not** run it (billed).
   **[S — CLAUDE.md]**
6. What a route must *carry* diverges sharply by route, and the Indian hand-off targets set
   the bar: **ERSS-112** needs an actionable **location + incident category + which
   responder service** (Police/Health/Fire/Women/Children); **Tele-MANAS** is a tiered
   clinical escalation needing **native-language context + risk level + consent**. A tier
   that carries only `(int, str)` — which is all the code carries today
   (`gates.py:81`) — is not enough for either. **[S/I]**

---

## 1. The requirement, and the code as it stands

### 1.1 The docx §14 requirement (as relayed by the ticket)

Docx §14 requires splitting the single broad SAFETY route into six, "each needs different
language and case handling":

| # | Route (docx §14) | One-line intent |
|---|---|---|
| 1 | **personal data** | child volunteers identifying/contact/location info |
| 2 | **ordinary distress** | upset, sad, frustrated — no danger, no third party |
| 3 | **harassment / threat** | child is being targeted (bullying, threats) — or is threatening |
| 4 | **abuse / violence** | someone is hurting the child (or child discloses being hurt) |
| 5 | **imminent danger** | active suicidal intent, someone in immediate physical danger |
| 6 | **uncertain-STT safety** | a *possible* safety hit under low transcription confidence |

### 1.2 What the code does today

`classify_safety` (`cloud_run_service/perception/gates.py:81-93`) is a two-stage regex over
the text that first fired the high-recall `_SAFETY_RE` (`:35-62`):

- **tier 3 `urgent_danger`** — matches `kill(ing) myself | suicid | slit my | ending my
  life | want to die | i'm in danger | bring a (knife|gun|weapon) | kill (him|her|them|
  everyone)` (`:86-89`). **[M]**
- **tier 2 `protected_disclosure`** — matches `abused | bad touch | wrong touch |
  touch(ed) me | hit(s) me | beat(s) me | hurt(s) me` (`:90-92`). **[M]**
- **tier 2 `safety_concern`** — the catch-all: fired the outer lexicon but neither inner
  regex (`:93`). **[M]**

The docstring is explicit that this is **redaction-safe** ("never retain the matched
phrase", `:82`) and that the gate **owns its decision absolutely** — "Gemini may *add* a
safety flag … but may NEVER downgrade a gate-flagged case" (`gates.py:5-9`). **[M]**

**[I]** Mapping the code's 3 outcomes onto the docx's 6 routes:
`urgent_danger` ⊇ imminent-danger **and** part of self-harm; `protected_disclosure` ≈
abuse/violence; `safety_concern` is an undifferentiated bucket that today absorbs distress,
harassment, and everything else. **Personal-data** and **uncertain-STT** have **no route at
all** in `gates.py` — the gate is content-only and has no access to `stt_confidence` (which
lives downstream at `interaction_control/control.py:248`, per the sibling STT research doc).
So two of the docx's six routes are not merely coarse today — they are **absent**.

---

## 2. (a) The candidate six-way taxonomy, with detectability verdicts

Detectability verdict scale (mine, **[I]**):
**DET** = deterministically separable from *one* utterance with acceptable precision;
**PARTIAL** = the *presence* of a safety concern is detectable, but *which* route is not
reliably separable from a single turn; **NOT** = not determinable from utterance content
alone (needs metadata, dialogue history, or evidence the child has not yet given).

| # | Route | Verdict | Why (evidence) |
|---|---|---|---|
| 1 | **personal data** | **DET** | Identifiers are lexically regular — phone/email/address/school-name/full-name patterns are the one safety class that is genuinely a pattern-match, not an inference. This is the "protect children's data and privacy" requirement UNICEF names as a standalone child-centred requirement ([UNICEF, *Policy guidance on AI for children 2.0*](https://www.unicef.org/innocenti/reports/policy-guidance-ai-children)). **[S/I]** No content-model needed; the risk is *disclosure itself*, independent of sentiment. |
| 2 | **ordinary distress** | **PARTIAL** | "I'm sad / I hate this / I'm frustrated" is lexically detectable as *affect*, but the boundary distress↔crisis is exactly where lexicons fail: the crisis-text literature shows self-reference + negation + isolation cues appear in **both** ordinary low mood and genuine suicidality ([JMIR, *Explainable AI Text Classifier for Suicidality in Youth Crisis Text Line Users*](https://pmc.ncbi.nlm.nih.gov/articles/PMC11822322/)). **[S]** A one-utterance rule can say "distress present," not "distress *only*, safely." |
| 3 | **harassment / threat** | **PARTIAL** | Two sub-cases with opposite subjects. Child-as-*target* ("they keep messaging me / won't leave me alone") is the 4Cs **Contact/Conduct** case, defined by *role* not keyword ([CO:RE, *4Cs of online risk*, Livingstone & Stoilova](https://core-evidence.eu/posts/4-cs-of-online-risk)). **[S]** Child-as-*aggressor* ("I'll hurt him") is what the current tier-3 `kill (him\|her\|them)` regex catches (`gates.py:88`) **[M]** — but disambiguating target from aggressor needs the subject, which short utterances drop. |
| 4 | **abuse / violence** | **PARTIAL** | Detectable *when disclosed directly* — the `hit me / touched me / bad touch` regexes fire (`gates.py:90-92`) **[M]**. But abuse disclosure is overwhelmingly *indirect and partial* by nature; PFA's core instruction is that you must **not** press for the details that would confirm the route ([WHO/WTF/WVI PFA, see §4.2 below]). The child who says "I don't want to go home" has disclosed route-4 risk without a single route-4 keyword. **[S/I]** |
| 5 | **imminent danger** | **PARTIAL** | The *high-lethality direct* case ("I want to die", "kill myself") is the one lexicons catch best and is the current tier-3 bucket (`gates.py:86-89`) **[M]**. But "imminent" is a *temporal/intent* judgement (plan, means, timeframe) that clinical triage makes from a **conversation**, not a word — and the literature shows the highest-risk disclosures are often the least explicit (§4.1). Presence: yes. "Imminent vs. ideation": not from one turn. **[S/I]** |
| 6 | **uncertain-STT safety** | **NOT (from content); DET (from metadata)** | This is not a content route at all — it is the condition "a safety pattern *maybe* matched, but transcription confidence is low." It is deterministically detectable, but only if the gate is given `stt_confidence` / N-best, which today it is **not** (`gates.py` is pure text; confidence lives at `interaction_control/control.py:248`, per `MATH_AWARE_STT_NORMALIZATION_RESEARCH.md` §2.4). **[M/I]** The docx frames this exactly: STT is "an estimate of speech, not the child's ground truth," and consequences must be **confirmed before** acting on uncertain language (docx §9, quoted in the sibling STT research doc). **[S]** |

**[I] Summary of the partition problem.** Personal-data (DET) and uncertain-STT (DET on
metadata) are clean. The four "affective/relational" routes (2–5) share one property fatal
to a one-utterance splitter: **the route is defined by facts outside the utterance** — who
the actor is (self vs. other vs. third party), whether harm is past/ongoing/threatened, and
intent/timeframe. Every established taxonomy in §3 encodes exactly these axes, and every one
of them assumes a *counsellor in a conversation* supplies them.

---

## 3. Established taxonomies — how each carves the space, and what evidence each tier assumes

**Note 1 (billed evals):** per the ticket and CLAUDE.md, the repo lexicon's recall must be
measured with `python -m eval.perception_eval --gates`; I did **not** run it. CLAUDE.md
records the last measured value as **0.75 recall** with missed gerunds ("ending my life" vs
"end my life") and oblique phrasings. **[S — CLAUDE.md]**

### 3.1 UNICEF, *Policy guidance on AI for children 2.0* — the requirement frame

UNICEF's guidance sets **child-centred requirements** an AI system for children must meet;
the ones bearing on a safety router are **"Ensure safety for children,"** **"Protect
children's data and privacy,"** **"Ensure non-discrimination and fairness,"** and
**"Provide transparency, explainability and accountability"**
([UNICEF Innocenti report page](https://www.unicef.org/innocenti/reports/policy-guidance-ai-children);
[full PDF](https://www.unicef.org/innocenti/media/1341/file/UNICEF-Global-Insight-policy-guidance-AI-children-2.0-2021.pdf)). **[S]**
**[I]** Two of these map onto docx routes directly: "data and privacy" is route 1's whole
justification, and "transparency/accountability" is why the tier must carry an **auditable,
redaction-safe** record (which `gates.py:82` already gestures at). The guidance is a
*requirement set*, not a risk taxonomy — it tells you the router must be safe and auditable,
not how to cut the categories.

### 3.2 WHO / War Trauma Foundation / World Vision, *Psychological First Aid: Guide for
field workers* — what a first responder may and may **not** do

**Caveat on sourcing:** the WHO IRIS PDF and several mirrors returned HTTP 403 to my
fetcher; I could not decode the official PDF directly. The action-principle wording below is
corroborated across the WHO publication record and secondary training materials, cited
inline; treat the *verbatim* "do not pressure" bullet as **[S via secondary]** until read
against the guide PDF.

- The action principles are **Prepare → Look → Listen → Link**; under **Look**, "Safety is
  of primary importance … If it is not safe for you to be there, then do not go"
  ([WHO PFA publication](https://www.who.int/publications/i/item/9789241548205);
  [Project HOPE summary](https://www.projecthope.org/news-stories/story/what-is-psychological-first-aid/)). **[S]**
- **Listen** entails "active and empathetic listening … while respecting their willingness
  to speak and express themselves" — i.e. **PFA is not forced disclosure**; Project HOPE
  states PFA involves "respecting their willingness to speak" *rather than pressuring people
  to discuss traumatic events" ([Project HOPE](https://www.projecthope.org/news-stories/story/what-is-psychological-first-aid/)). **[S]**
  The guide's own well-known bullet is "**Do not pressure the person to talk**" / do not
  force them to tell their story (WHO PFA guide; **[S via secondary]**).
- PFA **is not** professional counselling and does **not** require pressing for details of
  what happened ([Project HOPE](https://www.projecthope.org/news-stories/story/what-is-psychological-first-aid/)). **[S]**

**[I] What this forbids a first-response classifier from doing.** The route's downstream
*language* must not interrogate. A router that, on a route-4 (abuse) hit, replies with "who
touched you? where? when?" to raise its confidence is doing exactly what PFA prohibits. This
is the strongest argument in the evidence base for keeping the **input-side** decision
**coarse and high-recall** and pushing *disambiguation* to a human/clinical tier that is
allowed to (gently) gather more — never to the child via probing. It also means the tier
must be **actionable without the child confirming the worst detail**, which raises the bar
on what metadata (not content) the route carries (§5).

### 3.3 Child Helpline International — counselling vs. non-counselling, and concern axes

CHI classifies contacts into **counselling** vs **non-counselling** (silent, abusive, test,
info-request, missed) and aggregates counselling contacts **"by concern or rights
violated"** — with **violence** (physical violence a top global concern), **family
relationships**, and **mental health** (suicidal thoughts/attempts a major reason) as
recurring top categories
([CHI, *Voices of Children & Young People*, 2022 global data](https://childhelplineinternational.org/wp-content/uploads/2023/10/VCYP-2022-Global-Data.pdf);
[CHI standards](https://childhelplineinternational.org/standards-for-child-helplines/)). **[S]**
**[I]** Note CHI's first split is **not** by risk topic at all — it is
*counselling vs. non-counselling* (is this even a real help-seeking contact?). That maps
onto the repo's **NONSENSE / test-input** gate (`gates.py:96-121`) as much as onto SAFETY,
and is a reminder that "abusive/test call" is a real, common, non-safety class.

### 3.4 The 4Cs (Livingstone & Stoilova, for CO:RE / EU Kids Online) — role, not keyword

The 4Cs classify online risk as **Content** (child *exposed to* harmful material),
**Contact** (child *targeted by* a harmful interaction), **Conduct** (child *witnesses,
participates in, or is a victim of* harmful behaviour), **Contract** (child *party to /
exploited by* a harmful commercial agreement); crossed with **aggressive / sexual / value /
commercial** risk types and **cross-cutting** privacy, health and fairness risks
([CO:RE, *4Cs of online risk*](https://core-evidence.eu/posts/4-cs-of-online-risk);
[MDPI open-access analysis](https://www.mdpi.com/2227-9067/10/8/1415);
[NSPCC summary](https://learning.nspcc.org.uk/news/2023/september/4-cs-of-online-safety)). **[S]**
**[I]** The load-bearing insight for ticket 07: the 4Cs distinguish cases by the **child's
role** (recipient / target / participant / victim / party-to), *not* by vocabulary. Docx
route 3 (harassment/threat) is precisely a Contact/Conduct case whose route depends on
whether the child is target or actor — the axis a single utterance most often omits.

### 3.5 Ofcom / UK Online Safety Act — statutory tiers and their evidence bar

Ofcom's children's-safety duties sort content into **primary priority** (pornography;
content **promoting or providing instructions for suicide, self-harm, or eating
disorders**), **priority** (abuse/hate on protected characteristics; **bullying**; violent
content; dangerous-stunt instructions), and **non-designated** content
([Ofcom, *Protecting people from illegal harms online*](https://www.ofcom.org.uk/online-safety/illegal-and-harmful-content/statement-protecting-people-from-illegal-harms-online);
[Ofcom, *New priority offences: serious self-harm and cyberflashing*](https://www.ofcom.org.uk/online-safety/illegal-and-harmful-content/statement-new-priority-offences-serious-self-harm-and-cyberflashing)). **[S]**
**[I]** Two things transfer. (1) The regulator's own top cut is **self-harm/suicide** as a
class of its own, separate from **abuse** and separate from **bullying/harassment** — the
same three-way split the docx makes among routes 3/4/5, from an independent authority. (2)
Ofcom's scheme is about *content the platform hosts*, and even there it is graded by
severity and legality, not detectability — it presumes moderation systems and human review,
not a single-utterance trip.

### 3.6 Turkington et al. (Lifeline call logs) — a data-driven presenting-reason taxonomy

Analysing a Northern Ireland crisis helpline's call logs, Turkington et al. derived **two**
taxonomies of presenting reasons — a **fine-grained** one and a coarser **ICD-10** mapping —
and cross-tabulated each against the call's **suicide-risk rating**
([Turkington et al., 2020, *Health Informatics Journal*, DOI 10.1177/1460458220913429](https://journals.sagepub.com/doi/10.1177/1460458220913429);
[open-access full text, Ulster](https://pure.ulster.ac.uk/ws/files/78803040/Why_do_people_call_crisis_helplines_Identifying_taxonomies_of_presenting_reasons_and_discovering_associations_between_these_reasons.pdf)). **[S]**
In the granular taxonomy the largest categories were **Suicide Ideation** (~71,055 calls,
highest mean risk ~6.27), **Anxiety**, **Mental Health**, **Alcohol**, and **Depression**
([PubMed record](https://pubmed.ncbi.nlm.nih.gov/32306837/)). **[S]**
**[I]** Empirical corroboration of two design facts: (1) **suicide ideation is both the
single most common and the highest-risk presenting reason** — it earns its own top tier
(docx route 5 / code tier 3). (2) The *taxonomy was learned from human-coded call logs*,
i.e. from counsellors who had a whole conversation. It is evidence that these categories are
real and separable **in a dialogue**, not evidence that they are separable in one utterance.

---

## 4. (b) Known failure modes of lexical detection — each with a citation

The unifying finding across the crisis-text-classification literature: **the highest-risk
disclosures are systematically the least lexically explicit.** A regex lexicon's recall
ceiling is therefore a property of the domain, not of the word list.

### 4.1 Indirect / implicit disclosure — the structural ceiling

People experiencing suicidal ideation or self-harm thoughts "are often circumspect, may use
indirect language or test the waters, and may express thoughts through implications, tone,
and patterns rather than direct statements," and **"the majority of true positive suicidal
users rarely posted content that directly referred to suicide ideation"**
([JMIR, *Explainable AI Text Classifier for Suicidality*](https://pmc.ncbi.nlm.nih.gov/articles/PMC11822322/);
consistent with the CLPsych shared-task framing that evidence must be *highlighted at the
span level* precisely because it is diffuse — [CLPsych 2024 overview](https://aclanthology.org/2024.clpsych-1.15/)). **[S]**
**[I]** This is the empirical basis for the repo's **0.75** lexicon recall (CLAUDE.md): the
missed 25% is not tuning debt, it is the indirect-disclosure tail the domain guarantees
exists. A finer six-way split does not raise recall — if anything, splitting the same recall
across more buckets *lowers* per-route recall unless each route's lexicon is separately
hardened.

### 4.2 Negation and third-person framing — false positives and false negatives together

The linguistic-features literature finds **negation** and **self-reference** are core
markers of genuine suicidality (JMIR, above) — which is the trap: the same tokens appear in
**negated** ("I do **not** want to die") and **third-person** ("my friend wants to die",
"a character in my game kills himself") utterances that a keyword regex fires on identically.
Specialised systems maintain hand-built negation lexicons ("no, not, never, unable" plus
phrases like "no longer") precisely because raw keyword presence is unreliable
([JMIR](https://pmc.ncbi.nlm.nih.gov/articles/PMC11822322/); negation-handling in suicide-note
emotion work, [Hybrid model for emotion in suicide notes](https://pmc.ncbi.nlm.nih.gov/articles/PMC3409477/)). **[S]**
**[M/I]** The repo lexicon is subject-blind: `r"\b(want|wanna|going|feel like) to? ?die\b"`
(`gates.py:39`) fires on "my brother wanted to die in the game" as readily as on a
first-person disclosure. The gate is **deliberately** high-recall/over-trigger by design
(`gates.py:32-33`), so this is a *precision* cost the current design accepts — but a
six-way split that needs to route *distress vs. imminent-danger* cannot absorb it, because
the third-person case should not be tier-3 at all.

### 4.3 Euphemism, code-switching, and local-language framing

Harmful intent is routinely expressed through evolving **euphemism** that fixed lexicons
miss by construction; automated euphemism detection exists precisely because moderation
keyword lists cannot keep up
([Zhu et al., *Self-Supervised Euphemism Detection and Identification for Content
Moderation*, arXiv:2103.16808](https://arxiv.org/pdf/2103.16808)). **[S]**
For this deployment, **code-switching compounds it**: the sibling STT research doc records
Hindi–English code-switched ASR at ~28–34% WER
(`MATH_AWARE_STT_NORMALIZATION_RESEARCH.md` §4.4, citing
[MUCS 2021, arXiv:2104.00235](https://arxiv.org/pdf/2104.00235)) **[S]**, so a child's
Hindi/regional euphemism for self-harm or abuse may be **mis-transcribed before** it ever
reaches the lexicon — a route-6 (uncertain-STT) condition riding on top of a route-4/5
content miss.

### 4.4 The explicit-content dependency (and CLAUDE.md's measured misses)

CLAUDE.md records the deployed lexicon at **0.75 recall**, having missed **gerund** forms
("ending my life" vs "end my life") and **oblique** phrasings — the exact indirect-disclosure
failure mode §4.1 predicts. **[S — CLAUDE.md]** The current pattern set has since been
broadened to cover several gerund/oblique forms
(`gates.py:37-47`, e.g. `end(ing|s)? (my life|it all|things|everything)`,
`no reason to live`, `if i (disappeared|was gone|…)`) **[M]** — **but recall on the
*current* patterns is unmeasured in this document.** Per CLAUDE.md and the ticket, recall
must be measured directly (`python -m eval.perception_eval --gates`), never inferred; I did
not run it (billed). **[S — CLAUDE.md]** The CLPsych/JMIR evidence (§4.1) says any lexical
approach has a hard ceiling well below 1.0, which is *why* `gates.py:5-9` treats the model as
an **additive** recall net that may never downgrade the gate — the architecture already
concedes the lexicon cannot be complete.

**[I] Cross-cutting consequence for a six-way split.** Every failure mode above degrades
*precision of the route*, not just recall of "safety-ness." Indirect disclosure and
negation/third-person mean the *same* surface text is compatible with distress (route 2),
abuse (route 4), and imminent danger (route 5). So the failure modes are not merely "we miss
some hits" — they are the direct evidence that **routes 2/4/5 are not cleanly separable from
one utterance**, which is the §2 verdict restated from the literature side.

---

## 5. (c) What each route must carry downstream for an actionable hand-off

The Indian hand-off targets define the floor. Two are relevant and they need **different**
payloads:

- **ERSS-112** (national emergency response) forwards "genuine, actionable calls … with
  **complete incident data** to a **Dispatcher** of Police/Health/Fire/Disaster/**Women**/
  **Children**/Railways," and its first job is to **identify the caller's location** and
  **assess the situation to gather the necessary information to dispatch help**
  ([MHA, *Emergency Response Support System (ERSS)*](https://www.mha.gov.in/en/commoncontent/emergency-response-support-system-erss);
  [112.gov.in](https://112.gov.in/)). **[S]** So an *imminent-danger* (route 5) hand-off is
  actionable only if it can carry, or trigger the collection of, **(location, incident
  category, which responder service)**.
- **Tele-MANAS** (national tele-mental-health) is a **tiered clinical escalation**: Tier-1
  counsellors give "immediate psychological first aid, active listening, and distress
  de-escalation **in the caller's native language**"; cases with "**suicidal ideation**" or
  severe trauma are **escalated** to psychologists/psychiatrists, with **consent** required
  before a video consult, and **follow-up** for high-risk callers
  ([Tele-MANAS coverage, *BJPsych*, Cambridge](https://www.cambridge.org/core/journals/the-british-journal-of-psychiatry/article/indias-telemanas-evolution-early-outcomes-and-a-scalable-blueprint-for-digital-public-mental-health/38D78E091B3B7BBD57D4B87217184690)). **[S]**
  So a *distress/self-harm* (route 2/5) hand-off needs **native-language context + a risk
  level + consent state**, not a location.

**[I] The carry-requirements table** (mine; no single source prescribes fields for *this*
system — this synthesises PFA §4.2, the hand-off targets above, and the UNICEF
accountability requirement §3.1):

| Route | Downstream owner (illustrative) | Must carry | Must NOT carry / do |
|---|---|---|---|
| 1 personal data | redaction + guardian/loop policy | the *fact* of disclosure, the **class** of identifier (phone/address/school/name), redaction-safe | the raw identifier in any retained/logged field — UNICEF privacy requirement **[S]** |
| 2 ordinary distress | in-loop empathetic reply (no escalation) | affect signal + "no third party / no danger detected" confidence | must **not** probe for causes (PFA: do not pressure) **[S]** |
| 3 harassment/threat | safeguarding review; distinguish target vs. actor | **role** (child target vs. child aggressor), target identity class, whether ongoing | assume aggressor from ambiguous subject **[S — 4Cs role axis]** |
| 4 abuse/violence | mandated-reporting / safeguarding lead | disclosure present + redaction-safe record + **that details were not solicited** | interrogate the child for who/where/when — PFA prohibition **[S]** |
| 5 imminent danger | crisis escalation → ERSS-112 / Tele-MANAS | **risk level**, self vs. other, and the **location/incident-category** ERSS needs (or a path to collect it), **consent** state for Tele-MANAS | mark/act on *uncertain* language without confirmation — docx §9 **[S]** |
| 6 uncertain-STT safety | confirmation turn, then re-route | the **original transcript + confidence/N-best**, the *candidate* route, and "unconfirmed" flag | commit any consequence before the child confirms (docx §9: confirm before consequence) **[S]** |

**[I]** The gap to today's code: `classify_safety` returns `tuple[int, str]`
(`gates.py:81`) — a tier and a category label, redaction-safe but **field-poor**. None of
the carry-requirements above (role, self-vs-other, location-collectability, consent state,
confidence/N-best, identifier class) exist in that return. Route 6 in particular is
*structurally* impossible in the current gate because the gate never sees `stt_confidence`.
Whether to enrich the tuple, add routes, or leave the split to a downstream layer is a
**ticket-07 contract decision**, not one this document makes.

---

## 6. Open questions / could not verify

1. **WHO PFA guide, verbatim "do not pressure to talk" bullet.** The official WHO IRIS PDF
   and several mirrors returned HTTP 403 to my fetcher, and local PDF rendering was
   unavailable (`pdftoppm`/poppler not installed). I corroborated Look/Listen/Link and the
   "respect willingness to speak / not forced disclosure / not professional counselling"
   framing across the WHO publication page and Project HOPE, but I did **not** read the exact
   guide sentence. Verify against the guide PDF
   ([WHO 9789241548205](https://www.who.int/publications/i/item/9789241548205)) before
   quoting it as verbatim primary.
2. **The full granular Turkington taxonomy list.** I have the top-5 categories and the
   two-taxonomy (granular + ICD-10) structure from the abstract/PubMed record, but the
   Sagepub full text and the Ulster open-access PDF would not decode in my fetcher (403 /
   binary). The complete category list is worth pulling if ticket 07 wants an
   externally-validated category set.
3. **CHI's complete formal contact-reason taxonomy.** CHI's annual *Voices* reports give the
   top concern categories and the counselling/non-counselling split, but I did not locate a
   single canonical document enumerating every category and sub-category with definitions.
   The `VCYP-2022-Global-Data.pdf` is the closest primary artefact.
4. **A published single-utterance (vs. whole-conversation) recall number for route
   *separation*.** All the crisis-classification numbers I found (CLPsych low/moderate/high;
   JMIR accuracy 0.79 / AUC 0.89) are **conversation- or post-level**, not single-utterance,
   and measure *risk-level* classification, not *route* separation. I found **no** primary
   source measuring how separable abuse-vs-distress-vs-threat is from one turn — which is
   itself evidence for the §2 "PARTIAL/NOT" verdicts, but means those verdicts are **[I]**,
   reasoned from adjacent data, not a cited measurement.
5. **The repo lexicon's *current* recall.** Unmeasured here by design (billed eval). Ticket
   07 / implementation must run `python -m eval.perception_eval --gates` on the current
   `gates.py` patterns; CLAUDE.md's 0.75 predates the `:37-47` broadening.
6. **Ofcom codes as a routing spec.** Ofcom's categories are for *platform content
   moderation with human review*, not first-response utterance routing; I treated them as
   corroboration of the *cuts* (self-harm ≠ abuse ≠ bullying), not as a detectability source.
