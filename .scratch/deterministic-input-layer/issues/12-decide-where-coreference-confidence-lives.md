# Decide where coreference confidence lives

Status: resolved
Type: grilling
Blocked by: 03

## Question

Docx §8 and §14 both require that "this"/"that" must not silently inherit the session
concept: *"Do not map ambiguous 'this/that' to INHERIT_CURRENT_CONCEPT without a coreference
confidence check. Ask a short clarification when topic evidence is insufficient."* §8 gives a
three-band policy — **High**: state the assumption and answer narrowly; **Medium**: offer two
short choices; **Low or conflicting**: do not pick a concept, request a small safe fragment.

Today there is no confidence, only a boolean, and it exists twice:

```
_ANAPHORA_RE = re.compile(r"\b(this|that|it|these|those|the same|here)\b", re.I)
# fires when the utterance is <= 12 words and matches
```

— `tutor_loop.py:1357-1366` and, verbatim, `interaction_control/control.py:664`. Its only
consumer is a context-drift guard at `control.py:422-431`, which forces the concept back to
`session["current_concept"]` when the resolved concept differs and is unrelated. That is the
*opposite* of §8: it silently inherits rather than asking.

Separately, the abstain path already inherits without asking:
`perception/interface.py:147-149` fills a missing concept from `session["current_concept"]`
whenever the resolver abstained.

Decisions to close:

- Is coreference **the Input Layer's job at all**? It needs the utterance (deterministic,
  in boundary), the resolved concept (semantic, out of boundary), and session context. That
  mix may put it in `interaction_control` or `perception`, with the Input Layer supplying
  only the anaphora evidence.
- If the Input Layer supplies evidence, what evidence exactly — anaphor present, anaphor
  span, utterance names its own topic, word count? What is the shape (boolean, band, score)?
- Who produces the **three-band confidence**, and from what? A regex cannot produce a band.
- What is the **clarification contract**? §8 Medium requires "two short choices based on
  visible/recent context" — that needs candidate concepts, which the layer does not have.
- The **12-word cutoff** is unexplained and untested. Keep, justify, or replace.
- Does the drift guard at `control.py:422-431` survive? It contradicts §8's "state the
  assumption" requirement by inheriting silently. Whichever way it goes, one owner, one copy.

Note §2's constraint on the answer: "Truth before fluency. The tutor may say 'I am not sure
what you mean yet'; it must not give a polished explanation of an assumed topic."

---

## Resolution (2026-08-27, /grilling)

**Coreference resolution leaves this effort entirely.** It is the **concept resolver's** job —
not the 200-line scorer that exists today, but the layer that name properly denotes: everything
from text cleanup, through scoring, through **reading chat history**, through **asking the
pedagogy layer to put a follow-up question**, involved in deciding which concept the learner is
talking about. That layer does not exist in the code yet; that it is needed is the decision.

Ticket 12 therefore resolves as a **disposition record plus a handover document**, not a design.
The implementable brief is committed at
`cloud_run_service/concept_resolver/CONCEPT_RESOLUTION_HANDOVER.md`; a different team executes
it. This ticket records what was decided about the *current* code and what leaves with the
handover.

### The measurement that reshaped the ticket

Measured 2026-08-27, offline over the frozen hardened run (`eval/perception_eval_raw2.jsonl`,
1019 rows, zero billing):

| Quantity | Value |
|---|---|
| Predicted `concept_id == INHERIT_CURRENT_CONCEPT` | **362 / 1019 = 35.5%** |
| **Gold** `INHERIT_CURRENT_CONCEPT` | **399 / 1019 = 39.2%** |
| Predicted abstains agreeing with gold | 346 / 362 |

Caveat: `exemplar_dataset` test split, not production traffic.

The gold column is the load-bearing number. **The dataset's own contract says the correct answer
for ~2 in 5 utterances is "carry the session's concept"** — they are ordinary mid-topic
follow-ups, not ambiguous references. §14 forbids treating session context as *proof of topic
identity*; it does not claim continuation is usually wrong. So deleting inheritance globally
would break the common case (~35% of turns lose their concept: no visual, no mastery movement,
un-anchored retrieval) to fix a rare one. The task is to *split* those turns, which nothing in
the system can do today — and that split is the handover.

This measurement **reversed a recommendation made earlier in the same session** (delete all five
inherit sites). It is the reason the ticket asked for the number before writing anything.

### The five silent-inherit sites, and their disposition

| # | Site | Disposition |
|---|---|---|
| 1 | `perception/interface.py:151-153` — abstain fills concept from `session["current_concept"]` | **survives**; handed over |
| 2 | `perception/interface.py:233-300` `_degraded` — outage fabricates `concept_id = current` | **survives**; handed over; **not touched at all** |
| 3 | `interaction_control/control.py:427-436` — the drift guard | **deleted** |
| 4 | `runtime/legacy_adapter.py:102` (`pedagogy_request`) | **deleted** |
| 5 | `runtime/legacy_adapter.py:215` / `:245` (the two response state views) | **deleted** |

3-5 go because none of them is a resolution decision: 4 and 5 are hidden duplicate suppliers of
one fact — and they mean that deleting site 1 alone would have been **cosmetic**, since the
adapter re-inherits immediately downstream — while 3 is an override that resolves a conflict *in
favour of session memory, silently*, which is §14's named prohibition and the exact inverse of
§8's "Low **or conflicting**: do not pick a concept."

1 and 2 survive because of the measurement: with no replacement built, deleting them is the
bigger bug. Site 2 additionally moves **no learner state** — it returns no `state_changes`, its
`state_deltas` are empty by construction, and `assessment_evidence/interface.py:91-95` already
forces `perception_uncertain` turns to `not_an_answer / uncertain_perception` — so un-anchoring
it would only make an already-impaired outage turn answer groundlessly as well. (`RouteResult.uncertain`
and the `perception_uncertain` flag are renamed `perception_degraded` by ticket 11; the code
citations here are today's names.)

### What this effort changes

- **Site 3 deleted.** Interim consequence, taken knowingly: a confident resolution to an
  unrelated concept is now accepted and `session["current_concept"]` follows it, so an STT
  mangling can silently jump chapters until the new layer lands. Ticket 15 records this as a
  **deliberate behaviour change**, not a delta to hold bit-exact.
- **Sites 4 and 5 deleted.** One supplier of the concept, no downstream re-inheritance.
- **`control.py:669`'s verbatim `_is_anaphoric_followup` deleted** (already ticket 05's call);
  Interaction Control reads Intake's `ReferenceReading` off ticket 13's **required**
  `InteractionControlRequest.observation`. The supplier swap should be bit-identical and *is* a
  ticket 15 delta. **Note the interaction with site 3's deletion:** with the drift guard gone,
  Interaction Control has no remaining consumer of `ReferenceReading` at all. The field is
  supplied and unread until the concept resolver exists — deliberately, because 13 made
  `observation` required precisely so no consumer can `getattr`-fallback to a private regex.
- **New invariant: `concept_id is None` ⇒ no learner-state write and no mastery movement.** The
  existing protection is incidental — scattered `if primary` checks written for other reasons —
  and `legacy_adapter.py:102` is proof of how casually a `None` gets filled in. Ticket 14 asserts
  it. Note this now bites rarely (site 1 survives), essentially only at session start.
- **Dead after the deletion:** `concept_relates_to_topic` on `InteractionControlDependencies`
  (`control.py:139`), its wiring (`tutor_loop.py:2112`), and `_concept_relates_to_topic` +
  `_concept_chapters` (`tutor_loop.py:1402-1410`). Ticket 13 disposes; the **rule** survives as
  prose in the handover doc, because it is useful evidence for a band even though its use as an
  override was wrong.

### What this effort does not change

- **`INHERIT_CURRENT_CONCEPT` keeps its name.** It is welded into the Gemini response-schema
  enum, the prompt-of-record, the Vertex context cache, the dataset gold and
  `eval/perception_eval.py:64`. Renaming moves frozen eval numbers for zero behavioural gain.
  The name is **historical**: it means *the model declined to name a concept*, and the
  inheritance that used to follow it is the new layer's to replace. Recorded in the handover doc
  and in CLAUDE.md so the next reader does not treat the name as a contract.
- **`_degraded` is not edited.** Its other fabrications — `primary="LEARNING"` and a neutral
  `cognitive_update` (`confidence: 0.5`, `engagement: 0.5`) asserted on every outage turn — are
  the same category of fiction as an inherited concept, but they are Perception's outage
  contract, owned by nobody, and pulling them in turns a scoped deletion into an open-ended
  redesign. Flagged in the doc and the map, not fixed.
- **No documentation edit is owed.** Checked: `learner_cognitive_state_architecture.md:262`
  ("a failed Gemini call degrades to gates + inherit-concept + neutral signals") and
  `resolver.py:9` ("abstain -> inherit session concept") both describe sites **1 and 2**, which
  survive — so both remain true. §6.3 never documented inheritance at all. The obligation
  transfers to the new layer, to be paid when it deletes those two sites. (Ticket 18 retires the
  4-doc lockstep rule and rewrites the set regardless; this ticket owes it nothing either way.)

### What Utterance Intake supplies

`ReferenceReading` keeps ticket 03's shape minus one field:

- `anaphors: tuple[AnaphorSpan, ...]` — the data.
- `has_anaphora` — a **derived property**, `bool(anaphors)`. The user asked for a flag the
  resolver branches on; a derived property gives one without a second field that can disagree
  with the first.
- `word_count` — **dropped.**

Spans rather than a bare boolean because a clarification that can name the actual word ("what
does *this* point to?") is the difference between §8's lightweight question and an irritating
one — and because detection being done once, publicly, is what stops a fourth private regex.

**The 12-word cutoff is discarded**, answering the ticket's "keep, justify, or replace" as
*replace with nothing*. It was never measured, never justified, had no owner, and after site 3's
deletion has no consumer. It is recorded in the handover doc as an artefact of the old code,
explicitly **not** as an inherited requirement.

### Rejected, recorded so it is not re-argued

- **Perception producing the band** (a new Gemini schema field). Out of this map's boundary, no
  dataset gold, and — decisively — §14's rule is about *evidence provenance*, which a
  composition can enforce structurally and a prompt can only request. `concept_confidence` is
  not a substitute either: it scores "which concept is this text about", not "did I resolve a
  pronoun", and it is hard-coded `0.0` on exactly the abstain path §8 is about.
- **Naming today's `concept_resolver/` as the owner as-is.** It is a stateless scorer with no
  history access and no way to ask; the handover doc says explicitly that it becomes a
  *component inside* the expanded layer, or the next team bolts history-reading onto a
  similarity function.
- **Keeping site 3 as a non-forcing annotation** ("resolution is unrelated to session topic",
  recorded but not applied). That is the band in miniature — an evidence-composition decision
  this ticket handed away — and it would ship a field with no consumer, the pattern ticket 05
  found four copies of.
- **An interim scripted reply on a concept-less turn.** That is §8's Low band, re-imported
  without the band that decides when to use it.
- **A separate ADR in `docs/adr/`.** The handover doc *is* the decision record; a second copy is
  another thing to keep in lockstep for no reader.

### Consequences handed to other tickets

- **13** — inherits the dead relatedness chain above (`concept_relates_to_topic` dependency +
  wiring + the two `tutor_loop` helpers).
- **14 (already resolved — these are additions to its manifest)** — evidence-level cases only, in
  the offline `unittest` lane: given `"why does this work"`, the observation carries one anaphor
  span and `has_anaphora` true; plus the `concept_id is None` ⇒ no-state-write assertion. Nothing
  asserts a band, because there is none, and nothing is measured, so the billed lane is untouched.
  No case pins site 3's behaviour — it is deleted, not preserved.
- **15** — three deliberate behaviour changes (site 3, sites 4-5) and one delta expected
  bit-identical (the `_is_anaphoric_followup` supplier swap). The 35.5% figure is the context for
  judging the blast radius.
- **16** — the spec carries the disposition table, the new no-state-write invariant, and an
  explicit compliance line: **§8's three bands and §14's coreference row are OUT OF SCOPE for
  this effort and unmet by it**, owned by the concept resolver per
  `cloud_run_service/concept_resolver/CONCEPT_RESOLUTION_HANDOVER.md`. The map's destination
  sentence is trimmed to name only the §14 rows this effort actually closes.
