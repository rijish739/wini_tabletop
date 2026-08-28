# Concept Resolution — handover brief

**Status:** decided 2026-08-27 (`/grilling`, ticket 12 of the deterministic-input-layer effort).
**The resolution is NOT implemented and is unowned.** A few preparatory deletions land with that
effort's spec (see §6); the resolution itself is this layer's to build.

**Reasoning trail:** `.scratch/deterministic-input-layer/issues/12-decide-where-coreference-confidence-lives.md`
**Requirements source:** `docs/archive/AI_Tutor_Child_Safe_Interaction_Specification.docx` §8, §14, §16.

Scope rule for this document: **everything found, nothing invented.** It records what the
grilling established about the current code and about the requirement. The design choices it
does not make are listed in §8 — silence here is not permission, it is an open question.

---

## 1. What this layer is

Concept resolution is **everything involved in deciding which curriculum concept the learner is
talking about.** That is broader than the package that exists today. It includes:

- text cleanup for resolution purposes,
- scoring the utterance against the concept catalog,
- **reading conversation history** when the utterance does not name its own topic,
- **asking the pedagogy layer to put a follow-up question to the learner** when history is not
  enough,
- deciding, on the evidence, whether the session concept may be carried forward at all.

Today's `resolver.py` — a stateless MiniLM anchor-similarity + labelled-exemplar kNN scorer —
**is a component inside this layer, not the layer itself.** It sees one string and an optional
`current_concept`; it has no access to `session["context"]`, no way to ask anything, and its
documented low-score behaviour (`resolver.py:9`, *"abstain if max score < tau -> inherit session
concept"*) is precisely the rule §14 prohibits. Do not bolt history-reading onto the scorer;
build the layer around it.

The layer **does not hold the floor itself.** When it needs a clarification it requests one from
the pedagogy layer, which owns what the tutor says and when.

---

## 2. The requirement, verbatim

Docx **§8**, *"When the child says 'this' or 'that' without naming the topic"*:

> Do not silently inherit the last concept merely because it is available in session memory.
> The tutor may use recent on-screen context only when it can state its assumption in the reply.
> If the reference could point to more than one thing, ask one lightweight question.

The three-band policy §8 specifies:

| Context confidence | Tutor action | §8's example |
|---|---|---|
| **High** | State the assumption and answer narrowly. | "Do you mean the second step in the factor tree? That step splits 153 into 3 x 51." |
| **Medium** | Offer two short choices based on visible/recent context. | "Is 'this' the word prime, the tree, or the division step?" |
| **Low or conflicting** | Do not pick a concept. Request a small safe fragment. | "I want to get this right. Please say one word from the question, or paste the sentence. Cover your name or school if it is in a photo." |

Docx **§14**, concept-inheritance row:

> Do not map ambiguous 'this/that' to INHERIT_CURRENT_CONCEPT without a coreference confidence
> check. Ask a short clarification when topic evidence is insufficient.

Docx **§16** checklist item, untouched by any effort so far:

> Add coreference confidence and a clarification UI for 'this/that'; do not use session context
> as proof of topic identity.

Binding constraint from **§2**: *"Truth before fluency. The tutor may say 'I am not sure what you
mean yet'; it must not give a polished explanation of an assumed topic."*

---

## 3. The measurement that shapes this problem

Measured 2026-08-27 against the frozen hardened perception run (`eval/perception_eval_raw2.jsonl`,
1019 rows; offline, zero billing):

| Quantity | Value |
|---|---|
| Rows where the model predicts `concept_id == INHERIT_CURRENT_CONCEPT` | **362 / 1019 = 35.5%** |
| Rows where **gold** is `INHERIT_CURRENT_CONCEPT` | **399 / 1019 = 39.2%** |
| Predicted abstains that agree with gold | 346 / 362 |

Caveat: this is the `exemplar_dataset` test split, not production traffic.

**Read it carefully, because it is why this layer exists rather than a one-line fix.** Roughly
two utterances in five are *designed* not to name their own concept — the dataset's own gold says
the correct answer is "carry the session's". Those are overwhelmingly ordinary mid-topic
follow-ups, not ambiguous references. §14 forbids treating session context as *proof of topic
identity*; it does not claim continuation is usually wrong.

Consequence: **deleting inheritance globally is not a fix, it is a bigger bug.** It would break
the common case — about 35% of turns lose their concept, meaning no visual, no mastery movement,
un-anchored retrieval — in order to address a rare one. The job is to *split* those turns,
ordinary continuation from genuinely ambiguous reference, which is exactly what nothing in the
system can do today.

---

## 4. What the input layer now supplies

The Utterance Intake module (ticket 03 of the deterministic-input-layer effort) publishes a
`ReferenceReading` on its frozen `UtteranceObservation`:

- `anaphors: tuple[AnaphorSpan, ...]` — the anaphoric tokens found, and **where they are**.
- `has_anaphora` — a derived property, `bool(anaphors)`. This is the flag to branch on.

Two rules about it:

1. **Detection is done. Do not re-implement it.** The spans exist so a clarification can name the
   actual word ("what does *this* point to?") rather than issuing a generic re-ask. Three copies
   of an anaphora regex existed before this effort; do not start a fourth.
2. **The flag is evidence, not a verdict.** `has_anaphora` says the utterance contains a pointing
   word. It does not say the reference is ambiguous — most are not. It is the trigger for this
   layer to *decide*, not a decision.

Detection runs on `normalized_text` (NFC, zero-width strip, whitespace collapse; NFKC was deleted
for destroying maths notation). The reading is computed on every turn but marked unauthorized
while an STT repair screen is pending — see ticket 03 for the authorization states.

**The 12-word cutoff is gone.** The previous implementations fired only when the utterance was
`<= 12 words`. That threshold was never measured, never justified, and had no owner. It is
recorded here as an artefact of the old code, **not** as a requirement inherited by this layer.
Word count is no longer published; the layer has the full text and can count words itself if it
can justify doing so.

---

## 5. Every place the current system silently inherits

Five sites, all verified 2026-08-27. Two survive into this layer's ownership; three are deleted
by the input-layer effort.

| # | Site | What it does | Disposition |
|---|---|---|---|
| 1 | `perception/interface.py:151-153` | on `abstained` with no concept, fills `concept_id` from `session["current_concept"]` | **survives — this layer's first deletion** |
| 2 | `perception/interface.py:233-300` (`_degraded`) | on Vertex timeout / bad schema, fabricates `concept_id = current_concept`, `abstained: True`, reason `"degraded fallback inherited session concept"` | **survives — this layer's second deletion** |
| 3 | `interaction_control/control.py:427-436` | the drift guard: forces the concept **back** to `current_concept` when the resolution differs, is unrelated, and the text is anaphoric | **deleted by the input-layer effort** |
| 4 | `runtime/legacy_adapter.py:102` (`pedagogy_request`) | `observation.concept_id or session["current_concept"]` | **deleted** |
| 5 | `runtime/legacy_adapter.py:215` (`response_planning_request`) and `:245` (`response_generation_request`) | the same fallback, twice more | **deleted** |

Sites 3-5 go because they are not resolution decisions: 4 and 5 are hidden duplicate suppliers of
one fact, and 3 is an override that resolves a conflict *in favour of session memory, silently* —
§14's named prohibition, and the exact inverse of §8's "Low **or conflicting**: do not pick a
concept."

Sites 1 and 2 survive deliberately, because of §3's measurement: with no replacement built,
deleting them makes about 35% of turns concept-less. When this layer can tell continuation from
ambiguity, they are the first two lines it removes.

Notes on site 2 specifically, so it is not deleted carelessly: it returns
`ModuleOutcome(value=..., failures=(failure,))` with **no `state_changes`**, its `state_deltas`
are empty by construction, and `assessment_evidence/interface.py:91-95` already forces any
`perception_uncertain` turn to grade `not_an_answer / uncertain_perception`. So the outage inherit
moves no learner state — it anchors retrieval and visuals only.

(Naming note: `RouteResult.uncertain` and the `perception_uncertain` flag are being renamed
`perception_degraded` across 7 sites by the input-layer effort. Code citations in this document
use today's names.)

---

## 6. What the input-layer effort changes, and what it does not

**Changes** (recorded in that effort's verification gate as deliberate behaviour changes, not as
deltas to hold bit-exact):

- The drift guard (site 3) is deleted. **Interim consequence:** a confident resolution to an
  unrelated concept is now *accepted*, and `session["current_concept"]` follows it. The failure
  the guard existed for — an STT mangling sending the resolver into another chapter mid-topic —
  becomes a silent topic jump until this layer lands. A knowing trade, taken because the guard's
  own behaviour was the §14 violation.
- The three adapter fallbacks (sites 4-5) are deleted, so `PedagogyObservation` and both response
  state views take the concept from the observation and from nowhere else.
- `interaction_control/control.py:669`'s verbatim `_is_anaphoric_followup` static method is
  deleted; the `ReferenceReading` reaches Interaction Control on the required
  `InteractionControlRequest.observation` field instead (tickets 05 and 13). **With the drift
  guard gone, nothing in the runtime reads that reading.** It is supplied and unread until this
  layer exists — which is the point: it is here waiting for you, and no consumer can quietly
  fall back to a private regex in the meantime.
- **Invariant added:** when `concept_id` is `None`, no learner-state write and no mastery movement
  may occur. Asserted in the effort's test corpus (ticket 14).

**Does not change:**

- Sites 1 and 2 above.
- The `INHERIT_CURRENT_CONCEPT` sentinel keeps its name. It is baked into the Gemini response
  schema enum, the prompt-of-record, the Vertex context cache, the dataset gold labels and
  `eval/perception_eval.py:64`; renaming it would move frozen eval numbers for no behavioural
  gain. **The name is historical.** It means *the model declined to name a concept*. The
  inheritance that used to follow it is this layer's to replace.
- `_degraded`'s other fabrications — `primary="LEARNING"` and a neutral `cognitive_update`
  (`confidence: 0.5`, `engagement: 0.5`, the rest zeroed) asserted on every outage turn. The same
  category of fiction as an inherited concept, a different owner, unowned today. Flagged, not
  fixed.

---

## 7. Found knowledge worth keeping

**Signals that already exist and cost nothing to consult:**

- `PerceptionObservation.concept_confidence: float` — Gemini's own 0-1 confidence, clamped.
  **Warning:** it scores *"which concept is this text about"*, not *"did I resolve a pronoun
  correctly"*. On the abstain path it is hard-coded `0.0` (`gemini_perception.py:485`,
  `interface.py:154`), which is the exact path §8 is about — so it cannot serve as the coreference
  band without change.
- `PerceptionObservation.secondary_concepts: tuple[str, ...]` — the runner-up concepts Gemini
  considered. The closest thing that exists to §8 Medium's "two short choices".
- `concept["abstained"]` and `resolution_reason` — already published.
- `session["context"]` — the recent exchange as `{role, text}` rows; the generator already
  receives the last four (`tutor_loop.py:2643`). **This is the history the layer must read.**
  Nothing in the runtime reads it for resolution purposes today.
- An armed `session["pending_check"]` / `pending_hope` carries the tutor's own question, which
  defines the referent more strongly than topic continuity does.

**The relatedness rule the deleted drift guard used** (`tutor_loop.py:1402-1410`, dead after the
deletion and disposed of by ticket 13): a newly-resolved concept counts as *related* to the
current topic if they share a `chapter_doc`, or if the current topic's chapter shares a graph edge
with the new concept's chapter (`_concept_chapters` walks both directions, so relatedness is
symmetric). Recorded because the algorithm is useful evidence for a band, even though its use as
an override was wrong.

**Machinery that already exists for asking and waiting.** Interaction Control has three working
precedents for "hold the floor, ask, consume the answer next turn" — each `COMPLETE` + scripted
reply + no learning write:

- `TOPIC_SHIFT_CONFIRM`: parks `session["pending_shift"]` (`control.py:659`), consumed at the top
  of the next turn by `_consume_pending_shift` (`control.py:754-788`) with a yes/no match.
- `CONFIRM_LOW_CONFIDENCE`: `control.py:249-260`, the STT floor path.
- `_consume_pending_mode_control`: the same shape for mode changes.

A clarification does not need new machinery invented — it needs one more pending record and a
route to pedagogy.

**§8's High example is out of representational reach today.** "Do you mean the second step in the
factor tree?" refers to a *step*, not a concept. The session dict holds `context`,
`current_concept`, `pending_*`, `safety_alert`, `status`, `steer_streak`; `display[]` is image
metadata only (`{image_path, alt_text}`). Nothing names a displayed step. A concept-keyed band
therefore scores step-level ambiguity — step 2 versus step 3 of one worked example — as **High**
and answers confidently about the wrong step. Either accept that, or introduce a board-state
representation, which no effort has done.

**Two constraints that bound any design here:**

- §14's rule is about *evidence provenance*: session continuity may not be treated as proof of
  topic identity. A band that can reach its top level on continuity alone does not implement §14 —
  it re-implements the silent inherit with extra steps.
- The trigger is broader than "this/that". §8's heading names pronouns, but §14's normative
  sentence is about `INHERIT_CURRENT_CONCEPT`, and site 1 fires on *every* abstain: "explain more",
  "why", "another one", a bare fragment. Answering confidently about an assumed topic is the harm;
  a pointing word is one route to it, not the only one.

---

## 8. Open questions this document deliberately does not answer

None of these were decided. Silence in the sections above is not license.

1. **What produces the three-band confidence, and from what evidence.** A regex cannot produce a
   band; `concept_confidence` measures the wrong thing; the evidence is split across the utterance,
   the model's output, and session history.
2. **Whether session continuity alone can ever reach High** (see §7's provenance constraint). The
   answer determines whether §14 is met or merely gestured at.
3. **The clarification contract**: what the layer returns when it cannot resolve, how it requests a
   question from pedagogy, what the pending record looks like, how the learner's answer is consumed
   on the following turn, and what happens if they answer something else entirely.
4. **Where §8 Medium's "two short choices" come from.** `secondary_concepts` is the obvious
   candidate but was never validated for this use.
5. **The referent space**: concepts only, or concepts plus an on-screen artefact (see §7's
   step-level blind spot).
6. **When sites 1 and 2 are deleted**, and what replaces each.
7. **Whether the layer needs its own eval**, and what corpus would measure "resolved the reference
   correctly" as distinct from "picked the right concept".
8. `_degraded`'s fabricated intent and neutral affect (§6) — adjacent, but not this layer's by any
   decision taken so far.
