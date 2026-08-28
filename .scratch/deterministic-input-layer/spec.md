# Utterance Intake, Child Safety, and Personal Data — Implementation Specification

Status: ready-for-agent

Supersedes nothing. Synthesizes the resolutions of tickets 01–15 in
`.scratch/deterministic-input-layer/issues/`. Where this document and a resolution differ, the
resolution is the reasoning trail and this document is the contract — except for the two
normative architecture documents named below, which outrank this one on their own subjects.

**Normative documents referenced, never restated:**

- `docs/architecture/SAFETY_ROUTE_TAXONOMY.md` — the safety class list, flags, severity rule,
  composition rule, model call, degraded mode, evaluation floors, write boundary, and types.
- `docs/architecture/PERSONAL_DATA_CONTRACT.md` — the personal-data class list, verdict shape,
  redaction primitive, sinks, deadlines, write boundary, evaluation floors, and types.
- `cloud_run_service/concept_resolver/CONCEPT_RESOLUTION_HANDOVER.md` — coreference and topic
  resolution, owned by a different team.
- `docs/architecture/STT_CAPTURE_CONTRACT.md` — requirements on the STT producer. **Not yet
  written; writing it is a deliverable of this effort (ticket 11).**
- `docs/adr/0001-delete-deterministic-intent-cues.md` — the accepted decision behind the cue
  deletions in the migration manifest.

## Problem Statement

Everything Wini does with a child's words before it understands them is scattered, duplicated,
and largely untested. The raw transcript arrives as a bare string on one channel and its
confidence as a bare float on another, so three modules each invent a different meaning for a
missing number — `0.0` in one place, a fabricated `1.0` in two others, and "no gate" in a
fourth. Normalization, safety screening, nonsense detection, problem detection, and anaphora
detection are spread across a 746-line class that is roughly ninety percent dead, a regex gate
module, a ~550-line cue file whose feature widths are welded to a shipped model, and a block of
inline booleans in the middle of a 2600-line turn function. `InputProcessor` is constructed five
times independently. `_is_anaphoric_followup` exists three times. The judgment that fuses a cue,
a model signal, and session state exists four times, and the copies disagree.

The consequences are not stylistic. A developer cannot change how the system reads a child's
words without reading the whole turn. And the child-safety obligations the product has taken on
are, measured rather than assumed, unmet:

- **Safety recall is unknown and the published figure is false.** The shipped `SAFETY recall 1.0`
  is measured on a 20-phrase corpus that is the same 20 phrases as the lexicon it grades, and the
  promotion gate that asserts it cannot execute at all — the eval imports a package that no longer
  exists at that path. Measured against ordinary disclosures, peer-at-risk and online solicitation
  are total misses, six of nine self-harm probes land in a catch-all tier, and a game sentence
  produces a top-tier false positive.
- **There is no personal-data detector anywhere.** Zero hits repo-wide. Meanwhile two logging
  paths write the child's raw turn to a file that is already committed to a public repository.
- **STT uncertainty is one float that Google itself documents as not a confidence score**,
  averaged across segments so a single mangled word is smoothed away, thresholded at a floor
  whose calibration record (`DEC-044`) was referenced once and never written. There is no N-best,
  no word confidence, and no way for a spoken-maths misreading to be refused rather than silently
  graded wrong.
- **Coreference is a twelve-word regex**, duplicated, with a drift guard that resolves conflicts
  silently in favour of session memory — the exact prohibition the child-safe specification names.

The team needs one named, independently testable capability that owns the raw-text→observation
step; two sibling capabilities that own the two model-backed child-safety obligations; and a
verification gate that says honestly what it does and does not assure.

## Solution

Create **Utterance Intake**, a Feature Module at `cloud_run_service/utterance_intake/`, with its
own `TurnPhase` sequenced before `PERCEPTION_AND_PRIOR_GRADING` and exactly one typed public
interface. It consumes one frozen `Utterance` value — text welded to the transcription evidence
that produced it — and returns one frozen `UtteranceObservation` inside a `ModuleOutcome`. It is
**total** (every `Utterance` yields a valid observation), **write-free**, **pure of session**, and
**detects but never decides**. Its vocabulary is booleans, enums, and spans; no scores, no cue
matrix, no `RouteResult`.

Create two sibling packages that are **not** part of Utterance Intake:
`cloud_run_service/child_safety/` and `cloud_run_service/personal_data/`. Each is a dedicated
Gemini call with its own prompt-of-record, response schema, Vertex context cache, environment
seam, and eval harness. The safety call is the **primary** safety detector on every turn; the
regex lexicon is demoted to the degraded-mode outage net. The personal-data call is the **only**
personal-data detector; there is no lexicon and no outage net, and the sinks fail closed instead.

Delete rather than relocate what has no owner: the runtime cue regexes (Perception's labels are
authoritative), the `SemanticClassifier` seam, the drift guard, the duplicate anaphora predicate,
the duplicate concept suppliers, and the false safety-recall figure at all seven sites where it is
published.

Verify in **three stages over one standing set**, with a closed and symmetric expected-diff
manifest for the two behaviors that legitimately change, and a verbatim statement at the top of
the verification section of what a green run does not mean.

The effort is deliberately **not** behavior-preserving. It changes safety detection, adds personal-
data detection, changes the published normalized form, changes where problem detection reads its
input, and accepts one recorded interim regression in concept drift.

## User Stories

1. As a learner, I want the tutor to hear my words as one thing — the text and the evidence for it
   together — so that no part of the system trusts a transcript more than the recogniser did.
2. As a learner, I want an absent confidence score to mean "we do not know", so that nothing treats
   a missing number as certainty about what I said.
3. As a learner, I want to choose between what the tutor thought it heard when it is unsure, so
   that a misheard answer is corrected by me rather than graded against me.
4. As a learner, I want to be able to say "none of these", so that the tutor does not keep insisting
   on words I never said.
5. As a learner, I want the repair screen to show me at most three choices plus a discard, read
   aloud on one screen, so that correcting the tutor is faster than repeating myself.
6. As a learner, I want the tutor to never auto-pick one of its own guesses for me, so that my
   authorization is the only thing that turns a machine hypothesis into my answer.
7. As a learner, I want nothing to be graded or written about my learning from a transcript I have
   not confirmed, so that a bad microphone moment does not move my mastery.
8. As a learner, I want a transcript I *have* confirmed to be treated as mine, so that a second,
   downstream confidence check cannot suppress the answer I personally chose.
9. As a learner, I want my typed maths notation to survive normalization intact, so that `x²`
   does not become `x2` before anyone reads it.
10. As a learner, I want spoken maths that has two defensible readings to be questioned rather than
    guessed at, so that "three squared" is never silently graded as "3 squared".
11. As a learner, I want a non-maths question with a stray number in it to go straight through, so
    that asking about chapter 3 does not produce an error screen.
12. As a learner, I want a disclosure of harm to be acted on even if the tutor was unsure it heard
    me, so that the worst thing I ever say is the thing least likely to be dropped.
13. As a learner, I want a disclosure to survive even after I tap "none of these", so that a UI tap
    cannot delete a safety signal.
14. As a learner, I want the tutor to answer my maths question first and mention privacy once, so
    that being told not to share my phone number does not replace the help I asked for.
15. As a learner, I want my personal details removed from anything the system stores or says back,
    so that a number I said out loud does not end up in a log file.
16. As a learner, I want the tutor never to claim it deleted something it cannot delete, so that
    what it tells me about my data is true.
17. As a learner, I want the tutor to keep teaching when the safety or privacy model is unreachable,
    so that a cloud outage does not leave me without an answer.
18. As a learner, I want the tutor to keep track of the topic we are on across ordinary follow-up
    questions, so that "why does this work" does not lose the concept.
19. As an Utterance Intake owner, I want one typed public interface and no public string helper, so
    that every consumer comes through the door the tests exercise.
20. As an Utterance Intake owner, I want the module to be total and never fail, so that no consumer
    has to write a fallback for a missing observation.
21. As an Utterance Intake owner, I want the module write-free, so that detection can never quietly
    become a decision with a persistence side effect.
22. As an Utterance Intake owner, I want the module pure of session, so that its output is a
    deterministic function of one `Utterance` and its whole contract is reachable from hand-written
    values.
23. As an Utterance Intake owner, I want each judgment nested with the cue that produced it, so that
    a trace cannot drift away from the finding it explains.
24. As an Utterance Intake owner, I want cue values to be closed enumerations rather than free text,
    so that a corpus can assert on them without asserting on prose.
25. As an Utterance Intake owner, I want exactly one published normalized form, so that the router,
    the readings, and the generator can never disagree about which string was judged.
26. As an Utterance Intake owner, I want every reading computed on the normalized text and none on
    raw, so that a zero-width character cannot defeat a safety match.
27. As an Utterance Intake owner, I want the transcript floor injected as a policy rather than baked
    in as a constant, so that tests reach every authorization branch with no cloud call and no audio
    fixture.
28. As an Utterance Intake owner, I want unauthorized interpretive readings computed and marked
    rather than skipped, so that a consumer ignoring the flag is a visible test failure instead of a
    silent read of a missing field.
29. As an Utterance Intake owner, I want alternates to leave the module only as curated repair
    choices, so that no downstream layer can substitute a hypothesis for what the child said.
30. As a Perception owner, I want to consume Intake's observation instead of building my own input
    processor, so that there is one normalizer in the runtime rather than five.
31. As a Perception owner, I want the four promoted judgments and the session-control action in my
    schema, so that intent classification has one owner rather than a model and a regex voting.
32. As a Perception owner, I want session commands kept out of the signal-label catalog, so that
    "test me" cannot move learner state through the cognitive-state math.
33. As an Interaction Control owner, I want `gate()` to become a pure translation of the observation,
    so that the routing decision stays mine while the detection stops being mine.
34. As an Interaction Control owner, I want one shared composition helper for the safety verdict,
    so that two call sites cannot compose it differently.
35. As an Interaction Control owner, I want the observation on my request as a required field, so
    that no future consumer can fall back to a private regex when it is absent.
36. As a child-safety owner, I want a dedicated model call on every turn in its own package, so that
    safety detection has its own prompt, schema, cache, eval, and release gate.
37. As a child-safety owner, I want the call fired unconditionally rather than gated on a lexicon
    trip, so that the regex cannot silently become the gatekeeper again.
38. As a child-safety owner, I want a hard five-second wall clock with one retry, so that the child
    never waits on a slow verdict.
39. As a child-safety owner, I want a late verdict to still count and still escalate, so that a slow
    answer is not a lost answer.
40. As a child-safety owner, I want severity derived at exactly one site and written by no detector,
    so that no model or regex can fabricate a tier.
41. As a child-safety owner, I want findings to union and never subtract, whatever produced them, so
    that no composition step can remove a disclosure.
42. As a child-safety owner, I want the degraded net restricted to the axis with a single
    unspecified finding and never a critical severity, so that a regex can never fire an emergency
    script.
43. As a child-safety owner, I want the divergence between the net and the model published as
    monitoring only, so that nobody tunes the frozen lexicon toward the model.
44. As a child-safety owner, I want per-class recall against blind corpora and no aggregate number
    published anywhere, so that one figure can never hide two classes at zero.
45. As a personal-data owner, I want a model-only detector with no pattern component, so that the
    measured maths-eating failure mode is not shipped.
46. As a personal-data owner, I want the call fired after Intake, so that redaction can match
    exactly against the published normalized text.
47. As a personal-data owner, I want sinks that take a redacted type with no string overload, so
    that enforcement is a type error rather than a discipline.
48. As a personal-data owner, I want two deadlines — opportunistic for the child's answer, the full
    envelope for the sinks — so that generation is never blocked and persistence is never
    unprotected.
49. As a personal-data owner, I want persistence to fail closed and the child's answer to fail open,
    so that an outage costs a log line rather than a lesson.
50. As a personal-data owner, I want no retro-scrub promised, so that the system does not claim a
    reversal it cannot perform on unrecallable sinks.
51. As a personal-data owner, I want the write boundary on fields rather than turns, so that no
    "do not learn from this turn" flag has to be invented and honoured everywhere.
52. As an Assessment owner, I want the observation on my request, so that I can honour the
    authorization precondition and grade the parsed interpretation instead of re-deriving it.
53. As an Assessment owner, I want to grade the grammar's interpretation only when it was accepted,
    so that a refusal or a passthrough falls back to today's behavior rather than to a guess.
54. As a concept-resolver owner, I want Intake to publish anaphor spans rather than a boolean, so
    that a clarification can name the actual word.
55. As a concept-resolver owner, I want the unmeasured twelve-word cutoff discarded rather than
    inherited, so that I calibrate a band against evidence rather than against an artefact.
56. As a concept-resolver owner, I want a written invariant that a null concept means no learner-
    state write, so that the protection is stated rather than incidental.
57. As a tester, I want assertions and measurements in two lanes that never share a harness, so
    that pass/fail and per-class floors are never fused into one number.
58. As a tester, I want the offline lane to run with no credentials and no network in seconds, so
    that it is always safe to run.
59. As a tester, I want any external model behind an injected dependency, so that the offline
    guarantee is a seam rather than an import ban.
60. As a tester, I want corpora authored before the prompts exist, so that blindness is structural
    rather than procedural.
61. As a tester, I want the safety and personal-data corpora generated by a different model family
    from the detector, so that a corpus cannot mirror the detector's own priors.
62. As a tester, I want the generating model to label nothing, so that every number is attributable
    to the detector rather than to a judge.
63. As a tester, I want a corpus-integrity check in the free lane that fails on an empty grid cell,
    so that the coverage grid is a gate rather than a document.
64. As a tester, I want the grammar's refusal rate measured over claimed maths spans rather than
    utterances, so that the denominator cannot be gamed by padding the corpus.
65. As a tester, I want turn-level properties alongside per-row labels, so that a suite cannot be
    green on labels while the turn loses the child's answer.
66. As a tester, I want captured STT responses frozen once and replayed forever, so that no gate
    costs money or varies run to run.
67. As a reviewer, I want a closed and symmetric expected-diff manifest, so that an unlisted change
    fails and a stale claim also fails.
68. As a reviewer, I want every number the gate depends on in a register with its source, date, and
    status, so that a provisional threshold is never read as a measured one.
69. As a reviewer, I want the false safety-recall figure deleted rather than annotated, with a
    retraction manifest naming every site, so that it cannot be re-found and re-cited.
70. As a reviewer, I want the statement of what this gate does not assure placed at the top of the
    verification section, so that it is read as the point rather than as a footnote.
71. As an operator, I want a startup capability assertion naming which doubt signals the current
    producer supplies, so that "the repair screen never fires" is a visible configuration fact.
72. As an operator, I want the billed CI job to prompt a named reviewer with its cost, so that a
    paid run is a deliberate act with a name attached.
73. As an operator, I want the billed jobs to fail loudly on the missing federation secret, so that
    an unconfigured gate never looks like a passing one.
74. As an operator, I want measurement results written as dated records that are never edited, so
    that re-measuring means writing a new record rather than overwriting history.
75. As a repository maintainer, I want the byte-identical root twin of the turn module deleted, so
    that "did the change land" is answerable.
76. As a repository maintainer, I want the device sync manifest asserted against the directories it
    names, so that a rename cannot break a device deploy silently.
77. As a repository maintainer, I want every document that currently states something false about
    this system corrected in one pass, so that the agent implementing this effort is not misled by
    its own context.

## Implementation Decisions

### Modules, boundaries, and dependencies

- **`cloud_run_service/utterance_intake/`** is a Feature Module named **Utterance Intake**. The
  scaffolding term "Input Layer" does not survive into code; `cognitive_input_processor/` is
  deleted, not renamed. `CONTEXT.md` already carries the glossary entries for **Utterance** and
  **Utterance Intake**.
- Intake exposes **one** public interface:
  `UtteranceIntake.observe(UtteranceIntakeRequest) -> ModuleOutcome[UtteranceObservation]`. There is
  **no** public `normalize(text: str) -> str`. A second pure-predicate door was considered and
  rejected: after the cue deletions it has no consumers.
- Intake is sequenced by `TurnCoordinator` in a **new** `TurnPhase.UTTERANCE_INTAKE`, inserted
  **before** `PERCEPTION_AND_PRIOR_GRADING`. This is a real coordinator change:
  `_validate_phase_trace` requires the executed trace to equal `LOGICAL_TURN_PHASES` exactly.
- `UtteranceIntakeRequest` carries `turn_input` **only** — no session, no learner state.
- **Intake's four rules**, which every decision below follows from:
  1. **It reports; it never decides.** It detects a safety trip but never routes one; it reads a
     confidence verdict but never holds the floor. Every decision `gate()` makes today it still
     makes.
  2. **It is total and write-free.** `value` is never `None`; `failures` is always empty;
     `state_changes` is always empty. No new `RecoveryCapability` is added. If a bug raises, it
     propagates — on a child-safety path a crash beats a fabricated "nothing tripped".
  3. **It is pure of session.** The observation is a deterministic function of one `Utterance` and
     an injected transcript policy that is itself a pure function of one `Utterance`.
  4. **Every judgment is welded to the trace that produced it** — nested readings, not flat fields
     beside loose cue strings.
- **`cloud_run_service/child_safety/`** and **`cloud_run_service/personal_data/`** are siblings of
  `perception/`, **not** part of Utterance Intake. Each owns a dedicated Gemini call.
- **Dependency direction is one-way.** `RouteResult` never enters Intake's vocabulary.
  `perception/gates.py` and `interaction_control/` read Intake's observation; Intake reads neither.
- **External libraries and models are permitted in Intake**, subject to the seam rule below. There
  is **no stdlib-only rule**: ticket 04's guard is superseded, because it fails on day one against
  the `lark` grammar and cannot catch a model load anyway.
- **Intake ships with no model call and no network**, forced by the turn topology rather than by
  taste: safety and perception both consume `normalized_text`, so anything Intake waits on is pure
  added wall-clock ahead of two calls that cannot start without it. **No Intake latency ceiling is
  set.**

### Turn topology

- The **safety** call is dispatched **first**; the **perception** call immediately after; both are
  in flight together. **Perception's output is held until the safety verdict has been analyzed**,
  then released. The hold is bounded by the safety call's 5s envelope, after which perception
  releases in **degraded mode** with the `safety_model_unavailable` stamp. Unbounded was rejected —
  a hung safety call would freeze every turn.
- The **personal-data** call fires immediately **after** Intake. The ordering is forced: redaction
  is exact-match against `normalized_text`, which does not exist until Intake returns.
- **Two inherited facts, corrected, that change how `coordinator.run` reads:** Perception executes
  **before** Interaction Control despite the phase tuple's ordering — `LOGICAL_TURN_PHASES` is a
  **trace** contract, not the execution order. And **`gate()` is called inside `Perception.perceive`**,
  not by Interaction Control.

### The input value type

`Utterance`, `UtteranceSource`, `UtteranceProvenance`, and `WordConfidence` live in
**`runtime/contracts.py`**, beside `TurnInput` and `DeviceCapabilities` — they are the runtime's
vocabulary, what a Turn begins with. Defining them inside the Feature Module would invert the
dependency for the sake of a filename.

```python
class UtteranceSource(str, Enum):
    VOICE = "VOICE"
    TYPED = "TYPED"
    REPAIR_SELECTION = "REPAIR_SELECTION"
    REPAIR_DISCARD = "REPAIR_DISCARD"

@dataclass(frozen=True)
class WordConfidence:
    word: str
    confidence: float | None = None
    start_ms: int | None = None
    end_ms: int | None = None

@dataclass(frozen=True)
class UtteranceProvenance:
    utterance_id: str
    captured_at: str
    duration_ms: int | None = None
    recognizer: str | None = None          # model + language; None for TYPED
    repairs: str | None = None             # utterance_id this repairs
    selected_alternate_index: int | None = None

@dataclass(frozen=True)
class Utterance:
    text: str                              # raw, as received; never normalized
    source: UtteranceSource
    provenance: UtteranceProvenance
    confidence: float | None = None        # None = not reported
    alternates: tuple[str, ...] = ()       # recognizer rank order, index 0 == text
    word_confidences: tuple[WordConfidence, ...] = ()
```

- **The organizing rule: evidence travels welded to the text it describes, and absence is never a
  number.** `confidence` is `float | None`; `None` means **not reported** and is not comparable to
  a floor, so every consumer must state what unknown means to it. `TYPED` carries `None`, never a
  fabricated `1.0`.
- `text` is **raw only**; there is no normalized copy on the value type. Normalization exists in
  exactly one place — the observation.
- `alternates` are plain strings. Confidence exists only on the top alternative, so a per-hypothesis
  score field would be permanently `None` — a lie in the type. Rank is sequence order.
- `word_confidences` carry **time** offsets and **no character offsets**. Character offsets would
  index raw text while consumers read normalized text; carrying an alignment map across a rewriting
  step is how provenance quietly becomes false. Locating a word inside normalized text is a
  downstream alignment problem and should be visibly one.
- `provenance` is an opaque handle and **never bytes**. `utterance_id` is deliberately not
  `turn_id`: a repair is a new Turn, and the link between the two is the point.
- **Empty sequences mean "not reported", never "none exist".**
- **Invariants raise, never clamp.** `confidence` outside `[0, 1]` raises; the clamp stays at the
  adapter. **Empty `text` is allowed** — "heard nothing" is a real runtime state and a discard is
  empty text by design. `REPAIR_SELECTION` requires `provenance.repairs` and
  `selected_alternate_index`; `REPAIR_DISCARD` requires `repairs`, empty `text`, and no index;
  non-empty `word_confidences` requires `source is VOICE`. Duplicate hypotheses in `alternates` are
  **allowed** — the recogniser legitimately returns near-duplicates, and rejecting a valid API
  response is worse than carrying a redundant one. Dedupe happens at display time.
- **Production is voice-only.** `TYPED` is an engineering test shortcut (the interactive tester, the
  eval scripts, the HTTP text endpoint). **Exactly one branch on `source` is permitted anywhere in
  the runtime** — the trust policy (`TYPED` → confidence `None` → AUTHORIZED). No pedagogy, grading,
  or safety path may read `source`.
- `REPAIR_SELECTION` exists because the text came from our own N-best rather than the child's mouth;
  a distinct source keeps that authorization auditable instead of laundering a machine hypothesis
  into `TYPED`. `REPAIR_DISCARD` is an `Utterance` with empty text, not a UI event — a discard is the
  most valuable signal we can collect about the recogniser, and as a UI-only control signal it would
  evaporate before any ledger saw it.

**`TurnInput` gains `utterance: Utterance`, and both legacy channels are deleted:**
`interaction["text"]` and `trusted_observations["stt_confidence"]`. `interaction` keeps
`answer_budget` and `allow_topic_shift`. Assembling the `Utterance` inside Intake from the two
existing channels was rejected — it keeps the defect alive and merely relocates the `1.0`
fabrication. Deprecated mirrors were rejected — they guarantee both paths live forever and give the
verification gate two shapes to check.

**Deleting `interaction["text"]` touches six readers**, not the two originally counted:
`assessment_evidence/interface.py`, `interaction_control/control.py` (twice),
`perception/interface.py`, `retrieval/interface.py`, and `runtime/legacy_adapter.py`.

**Cache identity.** The perception memo keys on **`provenance.utterance_id`**, not on normalized
text. Today's memo keys on normalized text while the prompt it caches is built from session state,
so a repeated short utterance takes a cross-turn cache hit carrying a perception computed under a
different session. Keying on utterance identity preserves the memo's actual purpose — one Gemini
round-trip shared by route/classify/resolve/score inside a turn — and ends cross-turn reuse, which
was never its job. It also dissolves the idempotency constraint entirely, which is what makes a
*refusing* maths grammar expressible at all. **The Gemini call-count delta must be measured, not
assumed.**

### The output observation

```python
class Authorization(str, Enum):
    AUTHORIZED = "AUTHORIZED"       # TYPED, REPAIR_SELECTION, or VOICE at/above the floor
    UNAUTHORIZED = "UNAUTHORIZED"   # VOICE below the floor; a repair screen is pending
    DISCARDED = "DISCARDED"         # the learner rejected every hypothesis

@dataclass(frozen=True)
class UtteranceObservation:
    utterance: Utterance            # embedded whole, never flattened
    normalized_text: str            # exactly one published form
    authorization: Authorization
    safety: SafetySignals           # lexicon-only; see SAFETY_ROUTE_TAXONOMY.md §15
    legibility: LegibilityReading
    transcript: TranscriptReading
    problem: ProblemReading
    reference: ReferenceReading
```

- **Five required, non-defaulted readings.** Originally six; the `privacy` slot is **deleted**
  because detection is model-only and Intake is model-free, so a required field that can never be
  filled would be a lie in the type. A slot whose owning contract is unresolved ships reading "not
  evaluated" — honest and visible, rather than absent and invisible.
- `utterance` is **embedded by reference, not flattened**. Flattening re-splits exactly what the
  value type welded. Consumers read `obs.utterance.confidence`.
- **`normalized_text` is NFC + zero-width strip + whitespace collapse. NFKC is deleted.** NFKC was
  measured destroying `x²`→`x2`, rewriting the vulgar fraction, and dropping U+2212. The field served
  two contradictory contracts — fidelity for the prompts and the generator, folding for lexicon
  matching — and the fidelity consumer is the one that cannot be repaired downstream. **Any lossy
  folding a matcher needs is private to that matcher and never published.**
- **Every reading runs on `normalized_text`. None runs on raw. One rule, no exceptions.** What
  separates raw from normalized after the NFKC deletion is zero-width characters, whitespace runs,
  and NFC composition, and no reading should depend on any of them — while one of them is an attack
  surface, since a zero-width character inserted mid-word defeats a raw-text safety lexicon. The
  generator is handed `normalized_text`, so there is still exactly one string and it is the one the
  readings judged.
- **Booleans, enums, and spans only. No scores.** The only floats on the observation arrive from
  outside on the embedded `Utterance`. **`cue_matrix` does not become an observation field** — its
  width is welded to the shipped logreg, so publishing it would put a model-package build artifact
  into a runtime contract.
- **Cue values are closed sets of constants, never free text.** `SafetySignals` carries its category
  and **never the matched phrase**; the trace is the **pattern's stable id**.

| Reading | Shape | Notes |
|---|---|---|
| `SafetySignals` | `tripped`, `findings: frozenset[SafetyFinding]`, `caregiver_implicated`, `imminence_cue`, `source=LEXICON` (invariant) | Lexicon-only. Carries **no severity**. Computed every turn, but on a healthy turn it is **not the verdict** — consumed only in degraded mode and by the divergence monitor. |
| `LegibilityReading` | `illegible: bool`, `cue: LegibilityCue` ∈ {`LEGIBLE`, `EMPTY`, `NO_ALPHANUMERIC`, `CHARACTER_RUN`, `NO_LEXICAL_CONTENT`, `KEYBOARD_MASH`} | Today's five nonsense branches collapse into one boolean; this splits the **report**, not the decision. Thresholds unchanged. |
| `TranscriptReading` | see below | The acoustic axis and the maths parse. |
| `ProblemReading` | `is_problem: bool`, `directive: bool`, `cue: ProblemCue` ∈ {`equation`, `expression`, `solve_verb+numerals`} | `detect_student_problem` unchanged in logic, moved from raw to normalized input. |
| `ReferenceReading` | `anaphors: tuple[AnaphorSpan, ...]`, `has_anaphora` as a **derived property** (`bool(anaphors)`) | Evidence only. **`word_count` is dropped** and the 12-word cutoff is discarded. |

**Authorization and the deferral rule.** A transcript below the floor **is not a turn yet — it is a
question to the learner.** Judging text the learner has not authorized produces judgments we do not
believe, which some consumer will read as if we did.

| Reading | Deferred? | Why |
|---|---|---|
| `SafetySignals` | **never** | A marginal transcript that trips the lexicon is a stronger reason to look, not a weaker one. |
| `TranscriptReading` | **never** | It decides whether a repair screen is shown at all; deferring it is circular. |
| `LegibilityReading` | **never** | It is what reports that the utterance was empty in the first place. |
| `ProblemReading`, `ReferenceReading` | **yes** | Judgments about what the child *meant*, worthless on text they have not authorized. |

- **Mechanism: compute and mark, not skip.** Skipping would collide with both "all slots required"
  and "Intake is total"; marking preserves them, makes a consumer that ignores the flag a visible
  test failure, and keeps the unauthorized readings as the calibration telemetry the repair flow
  exists to produce.
- **Intake never compares confidence to a threshold.** `authorization` is filled from an **injected
  transcript policy** — `UtteranceIntake(transcript_policy=...)`, the same dependency-injection seam
  `InteractionControlDependencies` already uses. The policy is a hard construction dependency of
  Intake, which makes `UTTERANCE_INTAKE` the earliest point at which an STT threshold has runtime
  effect.
- **Three authorization states, and the fold is forbidden.** `DISCARDED` cannot collapse into
  `UNAUTHORIZED` with consumers checking `source` for the difference — that would need a second
  `source` branch, and it would show a second repair screen to a child who has already told us we
  cannot hear them.

**`gate()` stays in `perception/` and becomes a pure translation.** Safety reading tripped gives a
SAFETY `RouteResult`; else legibility illegible gives a NONSENSE `RouteResult`; else `None`. The
signature is unchanged. **That `gate()` has no detection logic left in it is the tell that the seam
landed correctly, not a reason to move it.** `gate()` reads the **textual** axis only — **nothing
acoustic feeds NONSENSE.**

**Why textual legibility cannot catch the real voice failure, and what does.** An autoregressive
recogniser's failure mode is not garbage but **fluent, confident English the child never said**;
every legibility cue is a character-class test, so a hallucinated "the answer is seven" passes all of
them. And with production voice-only, `KEYBOARD_MASH` and `CHARACTER_RUN` are calibrated for a threat
model that cannot occur. Hence **two independent axes, never fused**: textual illegibility is a dead
end (the turn produced nothing; `gate()` translates it to NONSENSE), acoustic doubt is recoverable
(the words may be right; the answer is the repair screen). Intake derives an **alternate-disagreement
measure** into `TranscriptReading`, and it runs **before** authorization — under a strictly
post-confirmation rule the detector would be disabled in exactly the case that motivated it.

**Rejected and recorded so they are not re-argued:** a separate safety return channel or
`FailureSignal` (a second return is exactly as ignorable as a field; loss is prevented structurally
by the required non-defaulted field, by `gate()` being a mandatory reader in the very next phase, and
by an assertion); a session-carrying request; and reviving `_contains_formula` / `tokens` /
`contains_numbers` / `has_question_mark` (the first fires on any hyphen, and `ProblemCue` carries
strictly more information than `contains_formula: bool` ever did).

### Safety — seam-level facts; `SAFETY_ROUTE_TAXONOMY.md` is normative

- **A new package, `cloud_run_service/child_safety/`**, sibling of `perception/`, **not** part of
  Utterance Intake. It holds the **primary** detector: a dedicated Gemini call, **every turn,
  unconditionally**, in parallel with perception, with its own prompt-of-record, response schema,
  Vertex context cache, and eval. Seams `VERTEX_SAFETY_MODEL` / `VERTEX_SAFETY_LOCATION`, defaulting
  to `gemini-2.5-flash@asia-south1` **with the version pinned**. `temperature=0`, `response_schema`,
  and **`thinking_budget=0`** are mandatory; empty text with `finish_reason=MAX_TOKENS` is a
  **failure**, never a negative verdict. **5s hard wall-clock plus one immediate retry inside the
  same envelope**, memoized on `utterance_id`.
- **Late verdicts still count** and still escalate. Safety findings may arrive asynchronously.
- **Gating the call on a lexicon trip is forbidden** — it would reinstate the regex as gatekeeper.
  The only cost levers are the context cache and the model id.
- **The lexicon is demoted, not deleted.** It survives **only** as the degraded-mode outage net:
  axis-only, `{UNSPECIFIED_CONCERN}` / `ELEVATED`, **never** `CRITICAL`, never a class — it can never
  fire an emergency script off a regex. **Frozen and CI-maintained**, with its own floor published
  under its own label.
- **The invariant, retargeted and stated as one sentence: nothing may ever remove a finding, whatever
  made it.** Model verdict is the verdict; perception's `safety` bit unions in as a free third net;
  the degraded net contributes only on failure; a late verdict unions; **severity is derived at
  exactly one site and is written by no detector**.
- **The model emits classes and imminence, union-only. Never severity, never `caregiver_implicated`.**
  A precision-seeking model would undo the deliberate over-trigger on `caregiver_implicated`.
- **Intake's slot is `safety: SafetySignals`** — lexicon-only, no severity, `source=LEXICON` enforced
  as an invariant (`MODEL` is unconstructable inside Intake, which runs before any model call).
- **Divergence between the net and the model is published as monitoring only** — never a gate, and
  never a reason to edit the lexicon toward the model.
- **The call sees `session["context"][-2:]`** — one preceding exchange. This is what makes the
  multi-turn review requirement implementable at all; it was not implementable with a stateless
  regex. The finding is still attributed to this turn; history may only add. **The session hands the
  prompt a count and a max severity, never the classes and never any text.**
- **Multi-turn rule:** an utterance's class set is never revised by history; severity **may be raised**
  by history, never lowered (the deterministic session accumulator); the multi-turn *review* is an
  eval requirement on conversation-level fixtures, not a runtime feature.
- **Deletions:** `RouteResult.safety_tier` and `RouteResult.safety_category` (one `safety` field
  replaces them; `safety_alert: bool` stays); the hard-coded
  `"scripted_reply+persisted_alert+supervisor_notify"` literal in `control.py`; and
  `interactive_tester.py`'s invented `tier 1` / `"HARMFUL_CONTENT"` vocabulary, which no producer
  emits.
- **One shared composition helper** in `interaction_control`, called from **both** sites that branch
  on `safety_alert`.
- **A safety trip suppresses the repair screen.** A trip at any confidence produces the response
  path; low confidence stamps `transcript_unconfirmed` and still writes and notifies. A `DISCARDED`
  transcript's finding **survives**, stamped `transcript_discarded` — a UI tap must not delete a
  safety signal. Severity is **not** capped on an unconfirmed or discarded transcript; instead the
  emergency-resource script waits for the direct question.
- **The safety path never reads `authorization` or `TranscriptReading`.** Structurally already true;
  this makes it deliberate, and it is asserted.
- **Evaluation:** per-class recall against **blind corpora** written against the taxonomy's
  definitions, never against the patterns. **No aggregate safety number is permitted anywhere.** Three
  numbers are published separately and never fused: model recall, incremental recall over the net,
  union recall. Own harness, never inside `perception_eval.py`. Floors are cited by reference to
  taxonomy §10.2, not restated here.
- **New standing hazard, named:** safety recall can now change with **no code change** — a prompt
  edit, schema tweak, model-version roll, cache rebuild, or region flip all move it silently.
  Mitigated by pinning the version and making the eval a release gate on every one of those changes.
- **Accepted cost:** a second Gemini call on every turn, roughly doubling perception-tier request
  volume.

### Personal data — seam-level facts; `PERSONAL_DATA_CONTRACT.md` is normative

- **A new package, `cloud_run_service/personal_data/`**, sibling of `perception/` and
  `child_safety/`, **not** part of Utterance Intake. A dedicated Gemini call fired **immediately
  after Intake** — the ordering is forced, because redaction is exact-match on `normalized_text`.
  Own prompt-of-record, schema, context cache, and eval. Seams `VERTEX_PERSONAL_DATA_MODEL` /
  `VERTEX_PERSONAL_DATA_LOCATION`, defaulting to `gemini-2.5-flash@asia-south1` with the version
  pinned, `thinking_budget=0`, **5s hard wall-clock plus one retry**, **two deadlines**:
  opportunistic for generation, the full envelope for the sinks. Context is one preceding exchange.
- **A model is the only detector. There is no regex, no lexicon, and no outage net.** Unlike safety,
  a Vertex outage means **zero detection** — affordable because a disclosed number is not
  safety-critical, and preferable to shipping the measured pattern-detector failure mode (F1 0.379
  on maths dialogue, false redactions clustering in maths-dense regions, because a threshold that
  spares `3825` also misses a spoken phone number). **Fail-closed sinks are what make zero detection
  safe.**
- **The verdict carries verbatim substrings** — not spans (LLM offset arithmetic), not a rewrite
  (licence to alter the maths). The verdict object is **identifier-bearing and never serialized**.
  Fail closed on a substring miss.
- **Redaction is exact-match with typed, uppercase, un-indexed, digit-free placeholders.** An index
  becomes a cross-turn pseudo-identifier the moment someone makes it stable. **There is no threshold
  and no shape rule anywhere**, so the maths is protected by construction.
- **`UtteranceObservation` loses its `privacy` slot**; six required readings become five.
- **Four sinks are converted** to take `RedactedText` and lose their `str` overload: the two
  `learning_log.jsonl` writers (`_log_shift`, `_log_nonlearning`), `debug_logger._fan_out`, and the
  generation prompt. **There is no sink *order*** — there is a four-site conversion list and one
  criterion: *persists / streams / can speak it back*. Grading and perception prompts are exempt
  (Vertex-to-Vertex, no echo); the parent dashboard is protected by construction and gets a rule.
- **`RedactedText` lives in the `personal_data` package, not `runtime/contracts.py`**, so only the
  redactor can construct one.
- **Fail closed on persistence, fail open on the child.** No transcript reaches a log without a
  verdict; generation proceeds unredacted rather than leaving the child unanswered. **No
  retro-scrub** — unrecallable sinks make it a promise we cannot keep.
- **The write boundary lands on fields, not turns.** **There is no do-not-learn-from-this-turn
  flag**; no class label or value enters learner state, and `derive_*` runs normally.
- **The safety case record never waits** on the privacy verdict — it is written stamped
  `privacy_unavailable`, and a late verdict unions in.
- **No separate privacy store.** Class labels go on the analytics row; a privacy-event store would
  itself be a behavioural record of a child with no consumer.
- **Deletion:** `_log_nonlearning`'s `safety_alert`-only redaction special case, which the general
  rule absorbs.
- **Child-facing behavior:** the maths answer first, always; one scripted line, once per session; it
  may never claim deletion. Redaction is unconditional; the spoken correction waits for
  `AUTHORIZED`.
- **Evaluation:** per-class recall and a hard precision gate on a maths-dense corpus, floors cited by
  reference to personal-data §12, blind corpora, **no aggregate number published**.

### The STT uncertainty contract

**Doubt is evidence, not a decision — and absent evidence is never the absence of doubt.** Intake
publishes everything it knows about the transcript plus exactly **one** decision (`Authorization`).
Per-consequence rules live on the consumers, stated here, never encoded as a permission set. A
four-permission set was rejected: three of the four named consequences are one ledger write behind
one constant, and the fourth may never be gated at all.

```python
class ParseOutcome(str, Enum):
    ACCEPT | PASSTHROUGH | REFUSE_AMBIGUOUS | REFUSE_OUT_OF_GRAMMAR

class DoubtCause(str, Enum):
    UTTERANCE_CONFIDENCE | WORD_CONFIDENCE | ALTERNATE_DISAGREEMENT
    | AMBIGUOUS_PARSE | OUT_OF_GRAMMAR

@dataclass(frozen=True)
class Span:
    start: int                         # token index into normalized_text
    end: int

@dataclass(frozen=True)
class MathParse:
    outcome: ParseOutcome
    span: Span | None                  # the span CLAIMED as mathematical; None on PASSTHROUGH
    interpretation: str | None         # ACCEPT only — e.g. "3^2"
    derivation: str | None             # the audit artifact
    competing: tuple[str, ...] = ()    # REFUSE_AMBIGUOUS only — the rival readings
    grammar_version: str = ""

@dataclass(frozen=True)
class TranscriptReading:
    doubtful: bool
    causes: tuple[DoubtCause, ...]     # empty iff not doubtful
    contested_spans: tuple[Span, ...]
    disagreement: float | None         # None = fewer than 2 hypotheses supplied
    min_word_confidence: float | None  # None = not reported
    repair_choices: tuple[str, ...]    # top-3 distinct, index 0 == primary; () unless doubtful
    parse: MathParse
```

**Three uncertainties, three names.** `RouteResult.uncertain` is renamed **`perception_degraded`**
across all seven sites (`RouteResult`, `PerceptionObservation.uncertain`,
`InteractionControlRequest.perception_uncertain`, `AssessmentRequest.perception_uncertain`,
`PedagogyObservation.uncertain`, and their readers) — it means *the Gemini call fell back*, a
**producer** failure, and its name has been lying since it was written. **The bare word "uncertain"
is banned as a field name** in the new contract. `triage_turn(stt_uncertain=)` is left alone as
legacy with a standing rule: **it is not the new policy's channel and must not be re-wired to it.**

**The doubt verdict.** `doubtful` is a **verdict OR-ed from three signals**, not a float comparison —
because the float is the one Google disclaims as *not truly a confidence score*, and the adapter
averages it across result segments so a single mangled word is smoothed away.

| Signal | Rule | Initial value |
|---|---|---|
| utterance confidence | below floor | **0.60** (unchanged, uncalibrated) |
| minimum word confidence | below floor | **~0.40** — a minimum over words trips far more readily than a mean |
| alternate disagreement | above ceiling | **conservative**: top-3 differing across more than half their aligned positions |

- **OR is the only combination monotone in the safe direction** — more evidence of doubt can only add
  a repair screen, never remove one. A fused score needs weights nobody can justify today, and is not
  monotone. Shipping the disagreement gate disabled was rejected: it puts the whole verdict back on
  the float.
- Three env-backed constants through the existing `runtime_flags.confidence_floor` helper.
  **`STT_WRITE_CONFIDENCE_MIN` is retired as a name** — it names a write gate that no longer exists.
- **All three values are PROVISIONAL and uncalibrated**, with the captured-STT corpus named as the
  instrument. **`DEC-044` is either written or explicitly killed** — not left dangling a third time.
- **The disagreement measure's form:** token-position comparison across the top-3 distinct
  hypotheses, producing both outputs in one pass — `contested_spans` (the positions where they
  disagree) and `disagreement = len(contested_spans) / max_len`. Whitespace tokenisation and
  position-wise comparison suffice, with proper alignment only as the length-mismatch fallback.
  **Computed over `normalized_text`**, so the spans index the published form and no alignment map has
  to survive a rewrite.

**N-best propagation — the boundary rule.** **Alternates are evidence, not text.** They are embedded
on the observation via `Utterance` and are therefore technically reachable, so the rule is stated and
asserted: **`repair_choices` is the one sanctioned export.** No consumer may substitute an alternate
for the primary; nothing re-runs Perception or grading on an alternate; the response layer reads
`repair_choices` and is **forbidden** from reading `utterance.alternates`. Computing a *measure over*
the alternates is not substituting one for the primary. `max_alternatives=5` is requested
**unconditionally** at the capture edge even though choices are only *shown* on doubt — it is
request-time, there is no audio store to re-run against, and hypotheses cannot be asked for
retroactively.

**Grammar refusal semantics.**

- **Engine: `lark` Earley with `ambiguity='explicit'`.** `len(CollapseAmbiguities(tree)) > 1` **is**
  the refusal predicate, and the competing trees are simultaneously the clarification material. PEG
  structurally cannot detect ambiguity (prioritized choice) and LALR reports conflicts at build time
  only. A hand-written conflict table catches only anticipated ambiguities, which is precisely how the
  current `re.sub` chain reached four measured confident false negatives. **`lark` is added to
  `requirements.txt` by this effort.**
- **Placement:** `cloud_run_service/utterance_intake/grammar/` — inside the Feature Module. One
  consumer, no independent lifecycle.
- **The grammar sits *beside* `math_grade.normalize`, not over it.** Superseding it now would put a
  grading behavior change on this effort's critical path. Retiring `math_grade.normalize` is a named
  backlog item; the duplication runs for the duration.
- **v1 scope:** exactly the shapes `math_grade` already grades — numbers and number words, fractions
  ("one over three", "one by three"), roots, signed values, equalities, unordered pairs — **plus
  exponents** ("three squared", "x cubed", "to the power"), which are entirely absent today and are
  the specification's own worked example. A grammar scoped to what the grader can compare is one whose
  refusals mean something.
- **Refusal kinds split by what they need**, which is what keeps Intake pure of session: **R1
  out-of-grammar** and **R2 ambiguous** are properties of the string alone and live in Intake; **R3
  low-confidence span** is not a grammar concern (it is the span tier below); **R4
  concept-inconsistent** needs the active concept and the expected answer and lives in **Assessment**.
  The other half of the "active concept" requirement is met at the **capture edge** via a per-turn
  phrase set: **the concept scopes the recogniser, not the parser.**
- **`PASSTHROUGH` is the common and legitimate outcome, and the burden sits on the claim.** The parser
  claims a span as mathematical only on **positive evidence**; out-of-grammar is a refusal **only**
  when a claimed span then fails to parse. **Only the two REFUSE outcomes set `doubtful`.** There must
  be **no error screen for non-maths input** — a learner may ask about a topic containing no maths at
  all. `span is None` on `PASSTHROUGH` is a **type invariant**, not a convention.
- **The interpretation is consumed, not merely audited.** Assessment grades `MathParse.interpretation`
  **when and only when `outcome is ACCEPT`**, falls back to today's `math_grade` path on
  `PASSTHROUGH`, and never grades on either REFUSE. Without this, Intake would parse "three squared"
  → `3^2`, publish it, and Assessment would independently fold it to `"3 squared"` and grade it
  **wrong** — the specification's own worked example still broken after a whole ticket about it. This
  does not breach the one-published-string rule: `normalized_text` remains the single published
  *transcript*; `interpretation` is a typed reading carrying its own outcome tag and derivation.
- **Idempotency dissolves.** The memo keys on `utterance_id`, NFKC is gone, and the normalizer never
  rewrites maths at all — so `normalized_text` is trivially a fixed point and `interpretation` is
  produced once and never re-parsed.

**Consequence gates, stated per consumer.**

| Consumer | Rule |
|---|---|
| **Safety path** (`child_safety/`, `_record_safety`, the composition helper) | **Never reads `authorization` or `TranscriptReading`.** Runs at every confidence and on every source. Asserted. |
| **Assessment and Evidence** | Grades and writes only on `authorization is AUTHORIZED`. Grades `interpretation` iff `ACCEPT`. Reads `observation.normalized_text`, `observation.authorization`, `observation.transcript` — never `turn_input`. **`AssessmentRequest` gains `observation: UtteranceObservation`.** |
| **Evidence ledger** | The raw-float check is **deleted** and replaced by an `authorization is AUTHORIZED` precondition. The check survives as defence-in-depth but **raises** rather than silently suppressing — reaching `record_outcome` with an unauthorized utterance is a coordinator bug, and a `status="suppressed"` row is how it would hide for months. |
| **Interaction Control** | The `stt_confidence` float read is **deleted**; the LEARNING path gates on `authorization`. |
| **Perception** | Not run at all on an `UNAUTHORIZED` turn — the original turn produces only the repair screen, so a doubtful turn costs **no Gemini call**. |
| **Response layer** | Reads `repair_choices`, never `utterance.alternates`. Renders hypotheses for acoustic doubt and competing readings for ambiguity; that difference is payload, not control flow. |
| **`pacing/triage.py`** | `stt_uncertain` stays legacy and unwired. Must not be re-wired to the new policy. |

**`confidence is None` means *no gate*** — never "trusted", never "distrusted" — stated once here so
three modules stop each deciding it privately.

**The repair flow.** Choices are shown **only below the floor**, never routinely; routine confirmation
trains the child to tap through it. Carry all five hypotheses; display **top-3 distinct after dedupe
plus a discard button = 4 touch targets, one screen, no pagination** — the readback ceiling on a
voice-first e-ink device sets the number, not screen space. **The primary is a button like any other,
index 0**; tapping it produces `REPAIR_SELECTION` with `selected_alternate_index=0`, so a marginal
transcript becomes learner-authorized rather than either discarded or silently trusted. This collapses
the edge cases into one screen: with one surviving hypothesis the same screen degrades to "Did you say
X?" / [that's right] / [no, let me say it again], which is the required yes/no fallback reached by
cardinality rather than by a branch. **The learner always chooses; nothing may auto-select an
alternate.** **One screen for both causes, with the cause recorded** in `causes`, because the fixes are
unrelated — acoustic doubt is a recogniser problem, ambiguity is a grammar problem. The payload carries
the strings **and** the differing spans, so the device can name the contested word instead of reading
three near-identical sentences aloud. `REPAIR_SELECTION` carries `confidence=None` — it came from a
tap, not from acoustics. The repaired turn re-runs the full pipeline from Intake on the new
`Utterance`; `REPAIR_DISCARD` produces a scripted retry and no pipeline.

**Non-voice fallback.** Production hardware has no keyboard; text input exists only at testing time.
The "at least one non-voice path per voice failure" condition is met by tap-selection plus discard.
**"Type it" is recorded as an explicit, reasoned hardware deviation**, available on TYPED harnesses
only, rather than silently dropped.

**The audit record — two artifacts, different owners.** The full parse record lives on
`TranscriptReading` for the turn, where the refusal must be readable to decide the turn at all. A
**minimized** copy goes to the evidence ledger **only when a consequence actually followed**: outcome,
rule identifier, span, `grammar_version`, competing-derivation count — **never the raw transcript**.
Intake is write-free, so the ledger write belongs to whoever owns the consequence.

**The capture edge is a handoff, not an implementation.** STT is being rebuilt as a streaming service
by a different developer; none of the capture-edge changes are implemented in this effort. The artifact
is **`docs/architecture/STT_CAPTURE_CONTRACT.md`**, written as requirements **on the producer** so that
developer can satisfy it without reading Intake's source. Required of the producer:
`max_alternatives=5`; `enable_word_confidence`; `enable_word_time_offsets`; the **`0.0` → `None`
sentinel mapping** (`WordInfo.confidence` documents `0.0` as "was not set", so without this mapping the
"absence is never a number" rule is defeated one level below where it was written); minting
`UtteranceProvenance`; **deleting the `stt_confidence = 1.0` fabrication**; and **removing the
empty-transcript early return**, without which `REPAIR_DISCARD` and the `EMPTY` cue are both dead on
arrival. Three streaming rules: **one `Utterance` per final result, never an interim one**; the
utterance boundary is the recogniser's endpointing; **Intake never runs on a non-final result**, because
a streaming recogniser revises and a turn started on retracted text is a state write against something
the child never said. **No `is_final` field is added** — an unrepresentable state cannot be mishandled;
the producer is constrained instead. Two documented caveats must be stated in the file: `latest_short`'s
confidence is disclaimed by Google, and word confidence is **Preview** (pre-GA terms). Two facts the spec
must never assume: **STT v1 has only US and EU regional endpoints — `asia-south1` is not a v1 region, so
STT and Vertex are not co-located**; and v2's per-model matrix for `asia-south1` is **UNVERIFIED**.
Deferred with owners: the per-turn concept-scoped phrase set, and `en-US` → `en-IN`. **Standing rule:
whoever changes `Utterance` updates this file in the same session.**

**The day-one degraded state, stated so a green run is not misread.** With the capture edge deferred,
the producer supplies `alternates=()` and `word_confidences=()`, so `disagreement` and
`min_word_confidence` are both `None`, **two of the three doubt signals are permanently absent**, and
the repair screen can fire only on the float — today's behavior exactly. It ships, but the degradation
is made measurable: a **startup capability assertion** logs, and the health endpoint reports, which of
the three doubt signals the current producer actually supplies. And the gate is handed an
**expectation, not a test**: on the current producer, **this layer's delta on the repair path is
predicted to be approximately zero**, written down in advance so a green run is not misread as evidence
the feature works.

### Coreference — where confidence lives, and what Intake supplies

- **Coreference and topic resolution leave this effort entirely.** The owner is the **concept
  resolver** — not today's stateless MiniLM scorer, but the layer that name denotes: cleanup →
  scoring → **reading chat history** → **asking the pedagogy layer to put a follow-up question**. That
  layer does not exist yet; that it is needed is the decision. The implementable brief is
  `cloud_run_service/concept_resolver/CONCEPT_RESOLUTION_HANDOVER.md`, executed by a different team.
  Today's `resolver.py` becomes a *component inside* it.
- **Compliance line, stated plainly: the three coreference-confidence bands, the "do not use session
  context as proof of topic identity" row, and the clarification-UI item are OUT OF SCOPE for this
  effort and UNMET by it.** Do not describe the system as satisfying them.
- **The measurement that reversed the obvious answer, and the number any future work should start
  from:** on the frozen hardened run (1019 rows, offline), **35.5% of utterances are predicted
  `INHERIT_CURRENT_CONCEPT` and gold says 39.2% should be.** "Carry the session's concept" is the
  *correct* answer for roughly two in five utterances. Deleting inheritance globally would break the
  common case to fix a rare one.
- **`INHERIT_CURRENT_CONCEPT` keeps its name.** It is welded into the Gemini response-schema enum, the
  prompt-of-record, the Vertex context cache, the dataset gold, and the eval. The name is
  **historical**: it means *the model declined to name a concept*. Renaming moves frozen eval numbers
  for zero behavioural gain.
- **Five silent-inherit sites; three deleted, two survive on purpose.** Deleted: the drift guard in
  `control.py`, and the adapter's two duplicate suppliers (`pedagogy_request` and the two response
  state views) — which is also why deleting the abstain site alone would have been **cosmetic**, since
  the adapter re-inherits immediately downstream. Surviving and handed over: `perception/interface.py`'s
  abstain fill and `_degraded`. **`_degraded` is not edited at all** — its other fabrications
  (`primary="LEARNING"`, a neutral cognitive update) are Perception's outage contract, owned by nobody,
  and pulling them in turns a scoped deletion into an open-ended redesign. Flagged, not fixed.
- **Interim regression, accepted knowingly:** with the drift guard deleted, a confident resolution to
  an unrelated concept is accepted and the session's current concept follows it, so an STT mangling can
  silently jump chapters mid-topic until the new layer lands. This is a **deliberate behavior change**,
  not a delta to hold identical — the guard's own behaviour was the violation it was asked about, and
  drift-suppression dies rather than becoming a silent override.
- **What Intake supplies:** `ReferenceReading` = `anaphors: tuple[AnaphorSpan, ...]` plus the derived
  `has_anaphora`. **Spans rather than a boolean**, because a clarification that can name the actual
  word is the difference between a lightweight question and an irritating one, and because detection
  done once, publicly, is what stops a fourth private regex.
- **The 12-word cutoff is discarded** — never measured, never justified, no owner, and after the drift
  guard's deletion, no consumer. Recorded in the handover doc as an artefact, explicitly **not** as an
  inherited requirement.
- **`ReferenceReading` is produced and unread** after the drift guard goes. It ships supplied-and-waiting
  on the required `InteractionControlRequest.observation`, which is exactly what stops a future consumer
  from `getattr`-falling back to a private regex.
- **New invariant: `concept_id is None` ⇒ no learner-state write and no mastery movement.** The existing
  protection is incidental — scattered `if primary` checks written for other reasons. Asserted.

### The migration manifest

**Moves into `utterance_intake/`**

| From | What |
|---|---|
| `cognitive_input_processor/input_processor.py` | `normalize_input` (NFKC deleted), `detect_student_problem` (raw → normalized input), `is_anaphoric_followup` (becomes `ReferenceReading`) |
| `perception/gates.py` | `is_safety`, `classify_safety`, `is_nonsense` (become `SafetySignals` and `LegibilityReading`) |
| **new** | the transcript policy seam, the alternate-disagreement measure, the `lark` grammar at `utterance_intake/grammar/` |

**Stays exactly where it is**

- `perception/gates.py` keeps **`gate()`** — the `RouteResult` constructor, now reading the
  observation. Unchanged signature, unchanged caller, SAFETY-beats-NONSENSE priority still visible in
  one place.
- `cognitive_classifier/cues.py` stays **byte-identical**. `cue_matrix` runs on the hot path today
  (inside `classify()` and again inside `PolicyShadow.suggest`), its width is welded to the shipped
  logreg, and the three build scripts that could re-fit it were **lost** in `5b847a1` — so
  `models/exemplar_classifier` and `models/policy_shadow` are **unreproducible**, recovery point
  `5b847a1^`. This effort deletes **call sites only**. Pruning predicates out of the file was rejected:
  it edits the most rebuild-sensitive file in the repo with no way to re-sync the head, for a file that
  dies anyway. It gets a ~6-line header comment (frozen, why, rebuild path deleted, recovery SHA) and
  **no golden test** — an accepted, stated risk, because a future edit to a cue regex **raises
  nothing**: the vector keeps its shape, one float changes, the head still scores, silently differently.

**Deleted from the runtime path** — Perception's labels become authoritative (see
`docs/adr/0001-delete-deterministic-intent-cues.md`)

`is_question` → `question`; `is_pure_ack` → `acknowledgment`; `is_clarification_request` →
`simplification_request`; `is_visualization_request` → `request_representation` /
`representation_shift`; `is_answer_attempt` → `answer_attempt`; `wants_different_topic` →
`topic_shift`; `HINT_RE` → `request_hint`; `EXAMPLE_RE` → `example_request`; `SELF_CORRECTION_RE` →
`self_correction`; `NEXT_RE` → `ready_for_next`.

**Promoted to Perception's schema**

- **Four new signal labels** (38 → 42): `purpose_question`, `animation_request`, `real_life_request`,
  `learning_request`.
- **A `SESSION_CONTROL` route sub-type**: `STOP` / `TEST` / `PRACTICE` / `EXPLAIN`. Deliberately **not**
  signal labels — a session command is not a cognitive state and must not reach
  `derive_cognitive_update` / `derive_state_deltas`. `session_modes.mode_cues` becomes obsolete,
  including its internal caller in `ModeController`; the rest of `session_modes.py` survives.
  `mode_cue=` on `InteractionControlDependencies` changes from `text → mode` to `observation → mode`.
- **Topic phrasing**: `extract_topic_request` / `is_bare_topic` / `TOPIC_REQUEST_RE` deleted; the
  structured call returns the learner's topic phrasing alongside the resolved concept id.
  `TOPIC_REQUEST_RE` was the only cue carrying a negation guard — the tell that it was already a
  semantic judgment wearing a regex.
- **Rebuild chain after the schema change:** `build_perception` → `vertex_cache --create` →
  `perception_eval` + `behavioral_eval` (billed).
- **Known gap, owner TBD:** the four promoted labels have **no dataset gold**, so `behavioral_eval` has
  no ground truth for them until the dataset is extended.

**Deleted outright**

- `cognitive_input_processor/` entire — including the dead members `process`,
  `_heuristic_signal_scores`, `_merge_scores`, `_extract_candidate_concepts`, `_contains_formula`,
  `HeuristicSemanticClassifier`, `InputSignalScores`, `ProcessedInput`, `IngestedInput`.
- **The `SemanticClassifier` seam entire**: the `SemanticClassifier` Protocol,
  `HeuristicSemanticClassifier`, the `MiniLMSemanticClassifier` adapter, and its two
  `cognitive_classifier/__init__.py` export lines. Both of the seam's stated purposes are filled
  elsewhere — the offline fallback is the safety lexicon outage net, and a local classifier's slot is
  on **Perception**, not on a booleans-and-enums Intake. *Recorded so the option is not lost:* if a
  local no-network semantic classifier is ever wanted, the recipe is MiniLM plus a supervised head
  trained on **minimal negated pairs**, not cosine over exemplars — and it would back Perception, so it
  would not want this interface anyway.
- `control.py`'s verbatim static `_is_anaphoric_followup`.
- The drift guard and the two duplicate concept suppliers in `legacy_adapter.py`.
- `analysis["problem_cue"]` — **deleted, not mirrored**. Its two consumers read `observation.problem`
  instead. Two suppliers of one fact is precisely the pattern that produced four disagreeing copies.
- The dead relatedness chain: `concept_relates_to_topic` on `InteractionControlDependencies`, its
  wiring, and `_concept_relates_to_topic` + `_concept_chapters` in `tutor_loop.py`. The **rule**
  survives as prose in the handover doc.
- **Root `tutor_loop.py`** — byte-identical to `cloud_run_service/tutor_loop.py`, unimportable since
  `5b847a1` (it imports a root `policy_shadow` that no longer exists), and a byte-identical 2600-line
  twin makes "did the change land" unanswerable.
- The nine spike tests in `cognitive_input_processor/tests/` — **deleted, not migrated**. Ticket 03
  changed the contract underneath every one of them, and a rewritten test that keeps its old name and
  shape is the likeliest place for an accommodating assertion to survive: one already is, commenting
  *"NFKC normalizes superscript 2"* and then asserting only that `"3x"` is present. The **cases** are
  inherited as required coverage — the maths-preservation case in particular, now asserting that `x²`
  survives.

**Migrated, not deleted**

- `interactive_tester.py` is rewritten **against the typed door only** — no private-function pokes. It
  is the only manual REPL against the pipeline and the corpora are not a substitute for typing at it.
  Its private safety keyword list is **deleted rather than migrated**: a second, drifting safety
  lexicon inside a dev tool is exactly what the safety inversion eliminated.
- `eval/behavioral_eval.py` and `eval/perception_eval.py` construct
  `Utterance(text=..., source=TYPED, ...)` instead of building an `InputProcessor`.
- `tools/sync_to_pi.py` — the `cognitive_input_processor` entry is removed. This consumer references
  the package **by string**, so no import guard would ever see it.
- `is_same_problem_followup` **inlines** into `tutor_loop.py` as a private method — it reads
  `session["context"]`, so purity bars it from Intake. The response layer relocates it later; the field
  it belongs in (`ResponseGenerationStateView.same_problem`) is already declared and unfilled.
- `pedagogy/tests/test_pedagogy.py` is rewritten to build `PedagogyObservation` from Perception labels
  directly.

**Consumers that must be rewired**

| Consumer | Change |
|---|---|
| `cognitive_analyzer/analyzer.py` | reads the observation; stops constructing an `InputProcessor` |
| `perception/gemini_perception.py` | reads the observation; stops constructing an `InputProcessor`; memo keys on `utterance_id` |
| `perception/interface.py` | reads the observation instead of `interaction["text"]` |
| `interaction_control/control.py` | reads the observation (two sites); `InteractionControlRequest` gains a **required, non-defaulted** `observation` |
| `assessment_evidence/interface.py` | reads the observation; `AssessmentRequest` gains `observation` |
| `retrieval/interface.py` | reads the observation instead of `interaction["text"]` |
| `runtime/legacy_adapter.py` | reads the observation; the three inherit sites deleted |
| `runtime/compatibility.py` | the **one** production construction site of `TurnInput`; mints TYPED provenance with `recognizer=None` |
| `evidence/ledger.py`, `assessment_evidence/interface.py` | both downstream float checks replaced by the `authorization` precondition |
| `wini_server.py` (Phase B pre-gate) | loses `is_pure_ack` / `is_question` |
| `pacing/triage.py` | all five cue imports deleted; reads Perception labels |

**Why `InteractionControlRequest.observation` is required and non-defaulted** — deliberately unlike the
`perception: PerceptionObservation | None = None` beside it. Perception is optional because a degraded
turn legitimately has none; **Intake is total** and its phase runs before Perception in every turn, so
`| None` would describe an impossible state and the first `if request.observation is None:` written
against it would be dead code guarding an impossibility. Concretely: an optional field invites a
`getattr(..., None)` fallback to the regex this effort is deleting.

### The inline turn-body derivations

The design question — who owns the fusion of cue, model signal, and session state — **left this effort**.
Perception owns `answer_attempt`; a **future layer, owner TBD**, owns `LearnerAsk`, the `non_attempt`
derivation, and the rest of the ten; the response layer owns its own rules. What lands here is a
disposition and an in-place rewire.

**The fusion already exists four times and the copies disagree** — the inline block, `PedagogyObservation`,
`ResponsePlanningStateView` (three fields declared and never filled), and `ResponseGenerationStateView`
(one field declared and never filled). And there is a **fourth non-attempt rule**,
`evidence/grading.py:obvious_non_attempt`, which is the one actually protecting the grading writeback,
while the inline `non_attempt` gates only HOPE probe scoring.

| # | Boolean | Where the judgment lands | What this effort does to the line |
|---|---|---|---|
| 1 | `clarification` | `simplification_request` label | rewrite the regex arm as a label read |
| 2 | `wants_visual` | `request_representation` / `representation_shift` | same; the OR collapses to a plain label read |
| 3 | `wants_why` | new `purpose_question` label | rewrite arm; its only consumer is a debug line |
| 4 | `wants_animation` | new `animation_request` label | rewrite arm |
| 5 | `wants_real_life` | new `real_life_request` label | rewrite arm |
| 6 | `answer_try` | Perception `answer_attempt`, authoritative | delete the regex arm; the first two arms were already the same fact |
| 7 | `student_problem` | Intake `ProblemReading` + a fusion the future layer owns | read `observation.problem`; delete `analysis["problem_cue"]` |
| 8 | `wants_hint` | `request_hint` + concept flags | untouched |
| 9 | `fresh_request` | labels only | untouched |
| 10 | `non_attempt` | derived downstream from existing labels | untouched |

**The block is rewired in place; nothing moves module.** Everything in the "untouched" column stays
verbatim, now model-fed rather than regex-fed, for the future layer to lift out intact. **This effort's
diff on that block is exactly one kind of change — regex arm becomes label read — which is what keeps the
measurement readable.**

**`non_attempt` is not a fifth schema promotion.** It is built from labels that already exist or are
already being promoted. Making it its own schema field would add a fifth promotion with no dataset gold
and a full billed rebuild behind it. `evidence/grading.py:obvious_non_attempt` **stays** as grading's own
text-only floor and is **add-only** — it may add a refusal to grade, never remove one. It has to survive
independently because the Phase B speculative grader runs concurrently with perception and structurally
cannot read a label.

**Open and explicitly not reconciled here:** `student_problem` (`is_problem AND (directive OR not
answer_try)`) and `PedagogyObservation.learner_problem` (`is_problem AND directive`) have disagreed on
every non-directive problem with no answer attempt since the modular split. The reconciliation is the
future layer's. **Recorded target: the legacy rule**, which is the one the two logged incidents were
fixed against; the adapter's is a silent narrowing. This effort changes neither copy.

### The future fusion layer's inheritance (owner TBD, named so nothing is orphaned)

- The ten inline booleans, left in place and now model-fed.
- `LearnerAsk` — whether the ten become one named record at all, and where it lives.
- The `non_attempt` derivation.
- Reconciling `student_problem` with `PedagogyObservation.learner_problem`.
- `PolicyShadow.suggest`'s **new feature path**. This is the one live consumer that the
  "no `cue_matrix` on the observation" rule leaves without a supplier — `suggest` calls `cue_matrix`
  unguarded on every learning turn today, and its result is **only logged**. Owner and design TBD; it is
  explicitly **not** a cues-split question.
- **The accepted billing regression**: with `is_pure_ack` / `is_question` gone from the Phase B
  speculative pre-gate, **every armed pending check now bills a grading call on pure acks and bare
  questions.** The pre-gate runs concurrently with perception by design and structurally cannot read a
  label. Accepted; owned by the layer that absorbs the speculative grader.

### Constraints promoted onto Perception (not Intake's, filed as a pointer)

`points_to_consider_developer.txt` is archived. Two of its rules are **promoted as constraints on
Perception** and land in the new architecture document: **never softmax — independent per-label
thresholds**, and **do not strip stop words**. Compound-utterance chunking is promoted as an **open
question for Perception's eval**, not as a rule — a turn that both explains and asks currently gets one
signal set, which is a real gap but has no measurement behind it. **Pronoun normalization is deleted with
prejudice**: it was written for a bi-encoder that needed the substitution to score at all, and doing it
now would overwrite the learner's actual words before every downstream reader — the mirror image of the
NFKC defect, and a direct contradiction of Intake detecting anaphor spans and never resolving them.

## Testing Decisions

### What makes a good test here

- **Assert external behavior through the module's one public interface**, never a private helper, a
  file layout, or an incidental intermediate structure. Intake is a pure function of one `Utterance`
  plus an injected policy, so its entire contract is reachable from hand-written values with no network,
  no credentials, and no audio.
- **Assertions and measurements are different things and never share a harness.** A corpus yields
  per-class numbers with floors; a contract yields pass/fail. Fusing them is how one aggregate number
  came to hide two classes at zero.
- **Test-first is the method.** No model-backed detector is built before its corpus exists — a corpus
  written before the prompt exists cannot mirror it.
- **Every corpus is authored or synthetic. No row is ever copied from production**, including from
  `learning_log.jsonl`.
- **This layer is graded only on the judgments it still makes.** Most of the original test-set list moved
  to Perception; grading Intake on them measures nothing.

### The two lanes

| Lane | Runner | Cost | When | Proves |
|---|---|---|---|---|
| **Assertions** | `python -m unittest discover -s utterance_intake/tests -v`, run from `cloud_run_service/` | free | every push, automatic | contracts, invariants, corpus integrity |
| **Measurements** | `python -m eval.safety_eval` and siblings, from `cloud_run_service/` | billed | on developer approval | per-class recall/precision against floors |

- **`unittest`, not pytest** — the nine module READMEs are the convention; the spike's pytest tests are
  rewritten, not ported.
- **Commands run from `cloud_run_service/`, and this effort's evals live in `cloud_run_service/eval/`** —
  where the modules they import actually live, so the two lanes never disagree about what imports. Root
  `eval/` is left alone as the legacy record; **its `--gates` / `--score` / `--run` paths are broken and
  this effort does not repair them** (backlog).
- **The spec's command block carries only commands that have been executed once and observed to run.**

### Import purity is dead; a seam rule replaces it

- **There is no stdlib-only rule.** External libraries and models are permitted in Intake when they buy
  accuracy at acceptable latency. `lark` is added to `requirements.txt`.
- **Seam rule:** any external model or network call in Intake sits behind an **injected dependency**.
  Enforced by a runtime assertion that the whole suite passes with `GOOGLE_APPLICATION_CREDENTIALS`
  unset and no network.
- The surviving half of the old guard **stays**: no module outside `cognitive_classifier/` and
  `policy_shadow/` imports `cognitive_classifier.cues`.

### CI

One GitHub Actions workflow, **three jobs**: `offline`, `billed-safety`, `billed-personal-data` —
separate rather than one parameterized job, so an approval approves exactly one cost against one corpus
set and the Actions history says which.

- **`offline`** runs automatically on every push: `unittest discover` across every
  `cloud_run_service/*/tests`, plus corpus integrity, the legacy-20 regression, and the degraded-net
  freeze check.
- **The billed jobs sit behind a GitHub Environment with required reviewers, managed org-side.** The
  developer is **prompted with the cost of the run**; that is the whole mechanism. **No path-based
  auto-skip** — every typo fix blocking on a paid run makes people click approve reflexively, which is
  the same failure as forgetting.
- **Credentials: Workload Identity Federation is the correct mechanism and is deferred to its own
  ticket.** This effort ships both billed jobs wired to a `WIF_PROVIDER` secret that does not yet exist,
  so they **fail loudly as unconfigured rather than pretending they ran**.
- **Binding rule: every check named in this spec's pass sets corresponds to a job step in the workflow. A
  check with no step is a spec bug.**

### The six corpora

14 owns the **manifest**, the **schema**, and the **harness**; construction splits by subject.

| # | Corpus | Constructed by | Gates |
|---|---|---|---|
| 1 | **Intake readings** — legibility cues, authorization states, homophones, problem cues, the frozen input set | this effort | this effort (Stage 1) |
| 2 | **Legacy 20** (`eval/perception_eval_safety.jsonl`) — adopted as-is, **permanent regression suite** | this effort | this effort; **never the recall measurement** |
| 3 | **Degraded-net** — the frozen outage lexicon, axis floor per taxonomy §10 | this effort | this effort, in the **free** lane |
| 4 | **Safety per-class** (6 classes + `UNSPECIFIED_CONCERN`) **+ safety FP corpus** | **authored now** by this effort | `child_safety/` at cutover (Stage 2), **not** this effort |
| 5 | **PII per-class** (9 classes) **+ maths-dense precision** (≥500 rows) | `personal_data`; this effort **reserves the path and schema** and supplies the maths-dense rows from the golden set | `personal_data/` (Stage 3) |
| 6 | **Captured-STT fixtures** — one-time capture, frozen and replayed forever | this effort | this effort, **replay only; never a live STT call** |

The safety corpora are authored **now, before any prompt exists**, because that is when blindness is at
its maximum. Their floors gate the package that lands later.

**Manifest fields, per corpus:** `name`, `authoring_rule`, `size_floor`, `schema`, `gate`, `owner`,
`path`, `reviewed_by`, `reviewed_at`, `review_scope`, `record_path`.

**Fixture format: one JSONL schema, superset-shaped, one file per corpus** — matching the existing eval
convention and staying diff-readable in a public repo, so the integrity test is one validator instead of
six.

| Field | Required | Notes |
|---|---|---|
| `id` | yes | stable |
| `text` | yes | |
| `label` | yes | the ground truth for exact-match scoring |
| `source` | yes | `authored` / `generated:<model-id>` / `captured` |
| `grid_cell` | yes | the coverage assertion's key |
| `context` | no | ordered prior turns — a bare string cannot express the one-preceding-exchange the safety call sees |
| `stt` | no | the captured recogniser response (`alternatives`, `confidence`, word info) |

**Captured-STT rows stay in their own file** — they carry a provenance and consent story the others do
not.

**Construction rules.**

- **Corpora are LLM-generated from a written, structured grid** — (class × directness × register ×
  code-switching × euphemism). **The grid is the reviewable deliverable; 300 generated rows are not.**
  The integrity test **fails on any empty grid cell**, which is what turns the grid from a document into
  a gate.
- **≥ 40% indirect/euphemistic rows per safety class.** The measured holes are all indirect, and the
  established finding is precisely that controlled-dataset recall is not protection.
- **A different generator family for the safety and PII corpora only.** Test-first ordering defeats
  *prompt* mirroring; it does not defeat *model* mirroring. A corpus generated by the same model family
  as the detector contains the phrasings that model already recognises and would report good recall
  before any prompt exists. Every row carries `source: generated:<model-id>`, and the integrity test
  asserts **no safety or PII corpus row was generated by the model named in `VERTEX_SAFETY_MODEL`**.
  Everything else may be generated by any model — those detectors are deterministic code, so there is no
  shared prior to correlate with.
- **The LLM generates; it never judges.** Scoring is exact comparison against the row's label, because
  the label *is* the ground truth. A judge would add a second model whose errors are indistinguishable
  from the detector's, making every number unattributable. (An LLM judge **is** legitimate for
  open-ended response templates, clarification wording, and the repair prompt — that is response-side.)

**The billed loop.** `eval/safety_eval.py` **mirrors the existing `--collect` / `--score` split
exactly**: `--collect` is billed, resumable, one call per uncached row, appending to a cache;
`--score` is offline and re-derives every metric from that cache. The rule the perception eval learned
the hard way and records in its own source: **a prompt change invalidates the cache.** So each prompt
iteration is exactly **one** full billed collect, the cache is keyed by prompt hash, and **mixing caches
across prompt versions is a test failure**, not a footnote.

**Storage: in-repo, public, synthetic.** Publishing is acceptable because the corpora measure a **model**,
not a filter — unlike a regex lexicon, publishing them does not tell anyone how to evade them — and the
blind-authoring rule already forbids editing the lexicon from corpus rows. Out-of-repo storage was
rejected: it puts a credential in the free lane and kills the "always safe to run" property.

> **Flagged, not this effort's:** `cloud_run_service/rag_store/learning_log.jsonl` — 306 entries of raw
> child turns — is already committed to a public repo. Personal-data territory.

### The six invariant assertions

| # | Invariant | Form |
|---|---|---|
| 1 | The safety path reads **neither** `authorization` **nor** `TranscriptReading` | source guard |
| 2 | **Exactly one** branch on `Utterance.source` exists in the whole runtime — the trust policy. No pedagogy, grading, or safety path reads it | source guard |
| 3 | **No consumer reads `utterance.alternates`** — only `repair_choices` | source guard |
| 4 | For `source is VOICE`, `authorization is UNAUTHORIZED` **iff** `transcript.doubtful` | behavioural |
| 5 | A raw personal-data value appears in **no** `__str__` / `__repr__` of the redaction type | source guard |
| 6 | **Perception's output is never released before the safety verdict is analyzed** — bounded by the 5s envelope, then degraded with the `safety_model_unavailable` stamp | behavioural |

Plus the surviving `cognitive_classifier.cues` import guard, the `sync_to_pi.py` PACKAGES-resolve
assertion, and the `concept_id is None` ⇒ no-state-write assertion.

**Invariant 4 exists because `authorization` and `doubtful` are different statements** — a decision and a
finding, with a third state (`DISCARDED`) that no finding produces. Collapsing them would put the decision
back inside the detector. Asserting the relation instead means **a policy that drifts from its own
evidence fails a test instead of shipping.**

### Set 3's pass bars — exact-match, per case, never aggregated

- **Six `LegibilityCue` values and three `Authorization` states**: full coverage, no empty grid cell,
  exact-match against the authored label.
- **The 42-row homophone table**: one expected outcome per row.
- **The grammar's two-sided acceptance, both halves measured:**
  - the **four measured confident false negatives** must each become a correct parse **or** a refusal —
    never a silent wrong;
  - **refusal rate is measured over claimed maths spans, never over utterances**, and the bar is a
    **band: 5%–15%**.
- **The denominator is the part that silently breaks.** Measured over utterances, the rate is dominated
  by how many non-maths turns happen to be in the corpus, so any target could be hit by adding topic
  questions. A **band** rather than a ceiling because both ends fail: above ~15% the grammar is refusing
  real answers and the repair screen becomes noise a child learns to dismiss; below ~5% it is claiming
  certainty on genuinely ambiguous spoken maths — a published study found 32 of 100 maths problems
  ambiguous to humans without visual context, so **a near-zero refusal rate is a failing result.** Both
  numbers are **calibration targets with a re-measure obligation**, not frozen gates.

### The integration tier

Four things resist a unit test at this layer and live in **`runtime/tests/`** — because the coordinator
tests already live there, they run offline, and putting turn-sequencing assertions in
`utterance_intake/tests/` would make a module test depend on the coordinator:

- the low-confidence re-prompt path;
- the **repair round-trip** — `REPAIR_SELECTION` / `REPAIR_DISCARD` are a *second* `Utterance`
  referencing the first, which one observation cannot express. The test asserts the `provenance.repairs`
  link explicitly, because **that link is the entire audit trail for substituting a machine hypothesis
  for what the child said**;
- the `TurnPhase.UTTERANCE_INTAKE` insertion;
- invariant 6, which is a coordinator property.

Still `unittest`, still free, still in the automatic lane. **The money is only ever in `eval/`.**

### The four turn-level properties, and the trap they answer

The historic promotion-gate failure was **grading a component on labels instead of on the trajectory it
produces**. Blind authoring, test-first ordering, the different-generator rule, and exact-match scoring
defend against *corpus* mirroring; they do **not** defend against this. Two live instances: an Intake
suite 100% green on legibility labels while the repair loop still loses the child's answer; and a safety
detector at 0.97 axis recall whose findings never reach a case record because the release path drops
them. Both are pass-on-labels, fail-in-turn.

**Four properties in `runtime/tests/`, free lane, no model calls** (injected stub verdicts): the repair
round-trip preserves `provenance.repairs`; a stubbed `CRITICAL` verdict reaches the case record with
perception held; a stubbed 5s timeout releases in degraded mode with the `safety_model_unavailable`
stamp; a terse real answer survives the full Intake→`gate()` path.

**Plus a written rule: no per-row label number is ever cited as evidence that the turn behaves
correctly.**

**Stubs are local hand-written fakes in `runtime/tests/`** — no shared testing package (it becomes the
dependency by which the offline guarantee eventually breaks) and **no `mock` patching** (a patched test
passes while the real injection point moves). **The fakes and tests may be LLM-authored**, on a local
developer approval prompt: generation happens at authoring time and the output is committed static code,
so nothing calls a model at run time. Each generated file carries a one-line header naming the generating
model and date. The different-generator-family rule does **not** apply — it exists to stop a safety corpus
mirroring the safety model's priors, and test code has no such prior. **The GitHub Environment stays
reserved for spend**; conflating "may I generate this file" with "may I spend money" is how a cost prompt
becomes reflexive.

### Prior art reused

`baseline_oracle`'s corpus seeds the frozen input set; its **required-coverage assertion pattern** and its
**normalization-forbidden-surfaces list** are borrowed. The existing `--collect` / `--score` and
`--probes` / `--replay` cache splits in `perception_eval` and `behavioral_eval` are the model for
`safety_eval`. The nine module `unittest` suites are the convention. **Nothing in `baseline_oracle` is
repaired** — see below.

### Sign-off

- **Sign the grid and a sample, not 300 rows.** The manifest carries `reviewed_by`, `reviewed_at`,
  `review_scope` per corpus.
- **An unreviewed corpus may be run** and its numbers published **under an "unreviewed" label** — but
  **no `child_safety/` cutover happens on unreviewed numbers.**
- **The named safeguarding owner is org-owned and is named as unanswered here**, not answered.

## The verification gate

> **A green run of this gate means the code does what these specifications say, measured on corpora we
> wrote ourselves. It is not evidence that any child was protected. This gate does not cover:
> subject-matter review of tutoring content or deterministic checks on numerical answers; a named
> safeguarding owner, staffed escalation rota, incident playbook, after-hours plan or drill evidence; a
> data map, age/consent review, retention and deletion design, access control, vendor review, or
> per-jurisdiction legal sign-off; an independent red team, accessibility review, or usability study with
> children or educators; production dashboards for false negatives and positives, a fast pause path for a
> harmful response path, or a versioned template and resource registry. Until the Safety-operations gate
> has a named, staffed owner, the product must not claim that it monitors safety or alerts adults.**

That statement is at the **top** of this section deliberately. A caveat under a table of passing checks is
read as a footnote; this one is the point. Its last sentence is the stop-ship condition, carried verbatim.

**There is no equivalence gate, because there is no single change to be equivalent to.** The effort lands
in three stages, each with its own entry gate, over one **standing set** that is never allowed to go red
at any stage.

### The three stages

| Stage | Unit | Lane | Prerequisite | Gate |
|---|---|---|---|---|
| **1** | Utterance Intake — contracts, grammar, coordinator phase | **free only, no billed run at all** | none | below |
| **2** | `child_safety/` cutover | billed, team-approved | **the WIF ticket has landed** | taxonomy §10.5 + floors |
| **3** | `personal_data/` | billed, team-approved | **the WIF ticket has landed**, Stage 2 complete | personal-data §12 floors + two structural assertions |

Stage 1 needs no credential of any kind. **Stages 2 and 3 are blocked on the Workload Identity Federation
ticket** — stated on the stage entry line, not in a footnote, so it is not discovered on cutover day.

**Stages 2 and 3 are ordered safety-first.** The safety case record is a *consumer* of the personal-data
verdict but **never waits** for it — it is written stamped `privacy_unavailable`. Between the two cutovers
that stamp is permanent rather than transient, which is a **true** statement about a system whose PII
detector does not exist yet. The reverse order would ship a PII detector whose most sensitive consumer is
unbuilt.

**Stage 1 pass set** — `unittest discover` green across every `cloud_run_service/*/tests`; Tier A
byte-identical; Tier B every diff row matching the closed manifest; the `TurnPhase.UTTERANCE_INTAKE`
insert passing `_validate_phase_trace`; the six source guards plus the `cognitive_classifier.cues` import
guard; the four turn-level properties; corpus integrity green over **all** corpora, including those
authored now for Stages 2–3; the tier-3 exception list measured and closed; the perf baseline recorded;
the grammar's refusal rate measured over claimed maths spans and recorded.

**Stage 2 pass set** — standing set green; the union cutover gate (billed once, stop-ship): **the union
must trip on every utterance today's lexicon trips on** — a model that misses a disclosure the shipped
system catches does not ship; model axis recall and per-class recall against their floors; incremental
recall and union recall published as **separate** numbers; no mixed prompt-hash caches; corpora reviewed.

**Stage 3 pass set** — standing set green; per-class recall and the maths-dense FP rate against their
floors; and the two structural assertions that are the actual contract: **`RedactedText` is
unconstructable without a landed verdict**, and **no raw identifier value appears in any `__str__` /
`__repr__`**.

**A class below its floor does not block the cutover.** It stays out of the enum, and the compensating
control is that it is **named in the release record and in the not-covered statement**, not only filed in
a backlog. Blocking on all seven would keep today's measurably worse lexicon in production while we wait —
a class at 0.75 beats a class at 0.0 — but a held-out class is invisible downstream, indistinguishable
from "this never happens", so it must be visible where a human reads it.

**The standing set, never red at any stage:** `unittest discover`; Tier A; corpus integrity; the source
guards; the legacy 20; the phase-trace assertion; the degraded net's **freeze**; the perf regression
guard. **A red standing-set check on `main` stops the effort** — the standing set is regression-only, so
red there means something that used to work no longer does, which is never a tuning question.

**The legacy 20 are written against the composition function from day one.** The test calls the union
entry point — the shared helper in `interaction_control` — whose implementation is the lexicon reading
plus perception's bit until `child_safety` lands, and which gains the model verdict at cutover. **The test
file is never edited at the cutover; the thing under it changes.** This also exercises the composition
seam months before it matters, which is where composition bugs are cheap.

### What stays identical, what may change

| Tier | Contents | Rule |
|---|---|---|
| **A — byte-identical** | `gate()`'s NONSENSE decisions over the 9-row probe **and** the terse-real-answer set (`5`, `x=3`, `no`, `½`) | asserted; any difference is a failure |
| **B — expected diff** | `normalize_input` (NFKC removal) and `detect_student_problem` (raw → normalized input) | every diff row matches the **closed** manifest, **and** every manifest row produces a diff |
| **C — unconstrained** | everything downstream of the two new model calls | measured by the Stage 2/3 floors, never by equivalence |

**Byte-equality is only meaningful where nothing was meant to move**, and after the observation contract
that is a very small set. Pretending otherwise is how an equivalence harness becomes a rubber stamp.

**The safety lexicon's trip-set is not Tier A here** — it is Stage 2's cutover gate; duplicating it into
Stage 1 would gate Intake on a package that does not exist.

**The expected-diff manifest** is `utterance_intake/tests/fixtures/expected_diffs.jsonl`, rows
`{id, function, input_id, before, after, reason, ticket}`. **Closed** = committed before the comparison
first runs. **Symmetric:** an unlisted diff fails, *and* a manifest row that produces no diff fails. The
manifest is a claim about exactly which behaviors change; both halves are checkable, so both are checked.
An asymmetric manifest was rejected — the stale row is the one that hides drift from what was authorized.

**The frozen input corpus** is authored fresh under `utterance_intake/tests/fixtures/`, **≥150 rows**,
seeded from `baseline_oracle/fixtures/corpus.json`'s 27 Turn Inputs and extended against what this effort
actually changes (the 27 were written to exercise a *turn*, not a normalizer). It **must** include: the
maths typography NFKC destroyed (`x²`, `½`, U+2212, U+00A0, zero-width joiners); the four measured
confident false negatives; the terse-real-answer set; the 9 nonsense-probe rows; the 42 homophone rows;
and equation / expression / solve-verb+numerals rows for each `ProblemCue`. Same JSONL schema as every
other corpus.

**Deliberate behavior changes, recorded as changes rather than as deltas to hold:** the drift guard's
deletion (a confident resolution to an unrelated concept is now accepted); the two duplicate concept
suppliers' deletion; the safety architecture inversion; the addition of personal-data detection.

**Measurable deltas, none assumable:** `detect_student_problem` moving from raw to normalized text; the
NFKC removal; the `TurnPhase` insert; the `perception_degraded` rename across seven sites; the deletion of
both downstream float checks; the `AssessmentRequest` shape change; the grammar's effect on the four
measured false negatives; the `TurnInput` shape change (one production construction site); and **the
Gemini call-count delta from the memo-key change**. Plus **one predicted non-delta**, stated as a
prediction rather than as a passing test: **on the current producer, the repair path's delta is expected to
be ≈ zero**, because two of three doubt signals are absent.

### No end-to-end equivalence oracle

**`baseline_oracle` is borrowed, not reused, and is not repaired by this effort.** Its frozen reference
was **never completed** — the metadata records four capture limitations and `verify.py` returns
`canonical_reference_incomplete` unconditionally, so **the oracle has never once run green** and its
performance was never measured. This is stated explicitly so the next reader does not see a
`baseline_oracle/` in the tree and assume coverage that has never run. **Repairing it is backlog.** The
Tier A/B comparison is a small offline characterization runner over frozen JSONL in
`utterance_intake/tests/`, in the free lane.

### Performance

**No absolute latency budget.** There is no measured per-turn total to regress against, and inventing one
would violate the project's re-measure rule. Two concrete guards instead:

1. **A hard per-utterance wall-clock cap on the grammar.** Exceeded ⇒ `PASSTHROUGH`, the same outcome as a
   refusal, so a pathological input degrades instead of hanging. Earley is the only unbounded-cost
   component in Intake. The cap's value is **PROVISIONAL** until the captured-STT corpus exists.
2. **A microbenchmark in the free lane** publishing Intake p50/p95 over the frozen corpus, failing on
   **p95 > 3× the recorded baseline** and **asserting only in CI** (on a developer machine the numbers
   print, the assertion is skipped). Baseline committed at
   `utterance_intake/tests/fixtures/intake_perf_baseline.json`, updated only by a deliberate commit; every
   run also writes a dated record. **The risk being guarded is Earley blowup — orders of magnitude, not
   percentages**; a 20% threshold would be a flake generator that teaches people to re-run until green.

The turn-level latency risk is covered by invariant 6 and its 5s bound, which is an assertion, not a
benchmark.

### The measurement commands

Run from `cloud_run_service/`:

```bash
python -m unittest discover -s utterance_intake/tests -v
```

```bash
python -m unittest discover -s runtime/tests -v
```

```bash
python -m eval.safety_eval --collect
```

```bash
python -m eval.safety_eval --score
```

```bash
python -m eval.personal_data_eval --collect
```

```bash
python -m eval.personal_data_eval --score
```

Rebuild chain after the Perception schema change (billed at the last two steps):

```bash
python -m perception.build_perception
```

```bash
python -m perception.vertex_cache --create
```

**`spec.md` carries no measured number it did not itself produce.** Every floor is cited by reference —
taxonomy §10.2, personal-data §12 — never restated as a figure.

### The numbers register

One row per number the gate depends on: `value | source doc+section | measured-on date | status`, where
status is `MEASURED`, `PROVISIONAL — calibrate against <corpus>`, or `UNMEASURED`. **A register row with
no source is a spec bug.**

Rows that enter as **PROVISIONAL**, calibrated against the captured-STT corpus: the utterance-confidence
floor (0.60), the minimum-word-confidence floor (~0.40), the alternate-disagreement ceiling, the grammar's
5%–15% refusal band, and the grammar wall-clock cap. Rows that enter as **UNMEASURED**: the Stage 1 perf
baseline, until its first run. **The grammar band and the degraded-net floor do not block Stage 1** — both
are calibration targets, so Stage 1 gates on *measured and recorded*; out-of-band triggers re-calibration,
not a red build. What the net **is** gated on is **freeze**: its trip-set over the corpora must be
byte-stable.

### Where results live

**Results are dated measurement records** at `cloud_run_service/eval/records/<gate>-<YYYY-MM-DD>.md`,
**never edited after writing**: a number lives in exactly one place, and re-measuring means writing a new
record. This **conflicts with taxonomy §10.3**, which requires passing numbers to be written into §11 of
that document; **resolved in favour of records**, and raised as an amendment rather than quietly
contradicted — §11 and the corpus manifest carry a **pointer to the current record**, and what stays in
the taxonomy is the part that is a contract rather than a measurement (the pinned model id and prompt
version). **Case records keep their embedded numbers unchanged** — a case record is a snapshot by design.

**The gate's definition is this section; the CI workflow is its executable form.** There is no fourth
document: a standalone `VERIFICATION.md` would be a second authority that drifts, which is exactly the
failure mode diagnosed in the archived lockstep set.

### Approval and rollback

**Approving the Stage 2 billed job *is* the attestation** that the tier-3 exception list is closed and the
corpora are reviewed — which turns an honour-system rule into a click with a name attached. Completing
that exception list is a **free, offline Stage 1 deliverable**, so Stage 2 never waits on it.

**There is no rollback design and no kill switch, by decision.** If a safety number breaks, the developer
fixes it, and nothing is released before it reaches its floor. Red never reaches production, so a
post-merge rollback story would be designing for a state this process does not produce. **The absence of a
fast pause path stays on the not-covered list above**, where the Monitoring gate can see it.

### The retraction manifest

The shipped `SAFETY recall 1.0` is false — measured on a 20-phrase corpus that mirrors the lexicon it
grades, by a code path that cannot execute — and is **deleted, not annotated**. Seven sites:

| Site | Action |
|---|---|
| `CLAUDE.md:37` | delete the figure; add *"safety recall is measured per-class against blind corpora; see `SAFETY_ROUTE_TAXONOMY.md` §10"* |
| `docs/runbooks/CLOUD_VOICE_STATUS_AND_GOTCHAS.md:285` | same |
| `eval/perception_eval_report.md:13, 60, 79` | delete the rows outright |
| `cloud_run_service/eval/perception_stress_report.md:39-40` | delete the rows outright |
| `eval/perception_eval.py:562` | **delete the `safety_recall` criterion now**, not at Stage 2 — it guards nothing, because the code path cannot run |
| `eval/perception_eval.py:518` | delete the reported field; `no_false_gate` and the NONSENSE row stay |
| `.scratch/deterministic-input-layer/map.md` ticket-07 refinement block | **keep** — it quotes the number *as a finding*; deleting it would erase the evidence that the number was wrong |

Prose sites get a pointer (they are read as current truth, and a silent gap invites re-filling); table rows
and code lose the figure outright (a measurement table with a pointer where a number was is just a slower
way to write the number). **This manifest is the only place the string survives.** Superseded banners on
the dated eval reports were rejected.

## Out of Scope

- **Coreference confidence bands, the "session context is not proof of topic identity" rule, and the
  clarification UI.** Owned by the concept resolver per its handover document. **Unmet by this effort, by
  design.**
- **The safety reply template library, the locale/helpline registry, and the output verifier.**
  Response-side. Two classes (`PEER_AT_RISK`, `UNSAFE_CONTACT`) have no template row and no script, and
  the "never name a parent by default" safe-adult rule is a requirement handed to that library.
- **The safeguarding case store** — moving safety alerts out of the learner state document, supporting
  asynchronous updates to an open record, and carrying the self-contained review fields. Backlog; it sits
  on the stop-ship gate.
- **Honest `handled`** — deriving the outcome literal from real outcomes rather than hard-coding it.
  Backlog; it also sits on the stop-ship gate.
- **The streaming STT service itself.** Different developer; `STT_CAPTURE_CONTRACT.md` is the entire
  interface.
- **The capture-edge code changes.** Requirements only, in that document.
- **The per-turn concept-scoped phrase set, and `en-US` → `en-IN`.** Deferred with owners named; the
  language change alters every transcript in the system and deserves its own measurement.
- **Retiring the 9-cue vector and the policy shadow**, and `PolicyShadow.suggest`'s new feature path.
  Separate ticket, owner TBD. Scope is the vector and the shadow, **not** `cognitive_classifier/` —
  `classifier.py` survives because the concept resolver and the HOPE detector import from it and its
  scores feed the state math.
- **Retiring `math_grade.normalize`** in favour of the grammar. Separate ticket; the duplication runs for
  the duration.
- **The future fusion layer** — `LearnerAsk`, the ten booleans, the `non_attempt` derivation, and the
  `student_problem` / `learner_problem` reconciliation.
- **Workload Identity Federation** for the billed CI jobs. Separate ticket, with Stages 2 and 3 as named
  dependents.
- **Repairing `baseline_oracle`'s frozen reference**, and repairing root `eval/`'s broken import path.
  Backlog.
- **`_degraded`'s other fabrications** — `primary="LEARNING"` and the neutral cognitive update asserted on
  every outage turn. Same category of fiction as an inherited concept, on Perception's outage contract,
  owned by nobody. Flagged, not fixed.
- **The grading prompt's logged output quoting the learner response** — a one-line fix, backlog.
- **The remaining root-duplicate cluster and the root `Dockerfile`.** Only root `tutor_loop.py` is deleted
  here. The rest is a *deploy-surface* decision needing evidence this effort does not have, and is
  **explicitly not endorsed** — a partial sweep must say what it did not sweep, or the remainder reads as
  approved.
- **The negation acid test and the `learning_log` grading regressions.** Handed to the grader layer; no
  fixture, no assertion, no code change here. Recorded as handed on rather than silently dropped.
- **The architecture document rewrite.** Ticket 18, and **nothing blocks on it** — if it gated this spec,
  a doc rewrite would gate the implementation, which is how four contaminated documents got written.
- **Age assurance, consent, retention, and jurisdiction review.** Not code.

## Further Notes

### Documentation obligation

**The four-document lockstep rule does not fire, because it is being retired.** The set is contaminated:
the layered architecture document is dated before this effort, **contradicts the safety decision in a
mandate sentence** (*"Model usage: NONE by mandate"*, *"do not implement a model-based safety classifier
as the primary gate"*), still cites the never-written `DEC-044`, and contains **zero** occurrences of
`Utterance Intake`, `UtteranceObservation`, `Feature Module`, `TurnPhase`, or `child_safety`. The four
documents stay in `docs/archive/`; **none of them is updated by this effort.** Ticket 18 replaces the rule
with one normative architecture document plus dated measurement records, and `CLAUDE.md`'s lockstep block
becomes a source-of-truth block with a precedence line. **`CONTEXT.md` is not touched** — it is the
vocabulary, already current, and upstream of the architecture document.

**Documents this effort must update — one pass, one owner, discharged as a precondition of implementation
rather than as a follow-up.** Each of these currently states something **false**, and `CLAUDE.md` is
loaded into every session's context, so a stale gotcha there actively misleads the agent implementing this
spec.

| Document | What must change |
|---|---|
| `CLAUDE.md` — memoization gotcha | No public `normalize_input`; the memo keys on `utterance_id`, not normalized text |
| `CLAUDE.md:67-69, 124-126` | Three quick-command build scripts (`curate_dataset.py`, `build_bank.py`, `build_policy.py`) were deleted by `5b847a1` and do not exist; the two model artifacts are unreproducible, recovery point `5b847a1^` |
| `CLAUDE.md` — new gotchas | `latest_short`'s confidence is documented by Google as **not** a true confidence score; `DEC-044` was never written; **STT v1 has no `asia-south1` region**, so STT and Vertex are not co-located; `STT_WRITE_CONFIDENCE_MIN` is retired as a name; `lark` is a new dependency |
| `CLAUDE.md:37` + `docs/runbooks/CLOUD_VOICE_STATUS_AND_GOTCHAS.md:285` | The safety-recall retraction (see the retraction manifest) |
| `CLAUDE.md` — concept-inheritance note | `INHERIT_CURRENT_CONCEPT` is a **historical name** meaning *the model declined to name a concept*; it is not a contract |
| `docs/architecture/CODEBASE_ARCHITECTURE_AND_COUPLING_REPORT.md:31,53` | Corrects the *"Ideal Deep Module Metric"* claim about a package being deleted |
| `docs/architecture/INPUT_LAYER_SEMANTIC_INTENT_RESEARCH.md`, `MATH_AWARE_STT_NORMALIZATION_RESEARCH.md` | Dated header note; findings untouched |
| **`docs/architecture/STT_CAPTURE_CONTRACT.md`** | **Written new.** Requirements on the STT producer |
| `cloud_run_service/cognitive_classifier/cues.py` | ~6-line frozen header |
| `cloud_run_service/perception/gates.py` | Docstring notice: the lexicon is no longer the primary detector |
| `docs/archive/rag_memory.md` | **Log this effort's work**, per the project's work-log convention: what changed, what was measured, and the gotchas discovered |

**Ownership boundary between the two documentation efforts:** this effort edits `CLAUDE.md`'s
**Quick-commands block** and its gotchas; ticket 18 owns the lockstep→source-of-truth block. They do not
overlap textually, and neither "tidies" the other's territory.

### Vocabulary

This specification uses the project glossary: **Utterance**, **Utterance Intake**, **Perception**,
**Turn**, **Turn Coordinator**, **Turn Input**, **Turn Phase**, **Feature Module**, **Module Outcome**,
**State Change**, **Failure Signal**, **Learner State**, **Session State**. The scaffolding term "Input
Layer" is retired and must not reappear in code, tests, or documents.

### Standing hazards this effort creates, named so they are not discovered later

1. **Safety recall can change with no code change.** A prompt edit, schema tweak, model-version roll,
   cache rebuild, or region flip all move it silently. A regex never had this property. Mitigated by
   pinning the model version and making the per-class eval a release gate on every one of those changes —
   not eliminated.
2. **A second Gemini call on every turn**, roughly doubling perception-tier request volume, plus a third
   for personal data. Gating either on a cheap precondition is forbidden.
3. **`cues.py` has a header warning and no test.** An edit to a cue regex shifts the feature vector fed to
   a head fit against the old regex — no crash, no failing test, no log line, and no rebuild path to
   re-sync it.
4. **The Phase B speculative pre-gate now bills a grading call on every pure ack and bare question** with
   an armed pending check.
5. **A confident resolution to an unrelated concept is now accepted** and the session concept follows it,
   until the concept resolver lands.
6. **Personal-data detection is zero during a Vertex outage.** The fail-closed sinks are the whole of the
   mitigation.
7. **Two of three doubt signals are absent on the current producer**, so the repair screen can fire only
   on a float Google disclaims. Made visible by the startup capability assertion.

### The rule that keeps this document honest

**No number in this document was copied.** Floors are cited by reference to their normative document;
provisional thresholds are labelled `PROVISIONAL` in the register with the corpus that will calibrate
them; and the one figure this effort found to be false is deleted at all seven of its sites, with the
retraction manifest as its only surviving record.
