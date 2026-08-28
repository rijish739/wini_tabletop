# Define the Input Observation — the layer's single output contract

Status: resolved
Type: grilling
Blocked by: 01, 02

## Question

What single typed value does the Input Layer return, and what is on it?

Today the deterministic layer's output is scattered across four incompatible shapes:

- `ProcessedInput` / `InputSignalScores` (`input_processor.py:33-72`) — the designed
  contract, **dead**; nothing constructs it at runtime.
- `RouteResult` (`perception/route.py:30`) — what `gates.gate()` returns, or `None` on pass.
- `problem_cue` — a bare `dict` returned by `detect_student_problem`, embedded in the
  analyzer's `analysis` dict at `analyzer.py:244`.
- Ten loose booleans computed ad hoc inside the turn body (`tutor_loop.py:2266-2330`) —
  `clarification`, `wants_visual`, `wants_why`, `wants_animation`, `wants_real_life`,
  `answer_try`, `student_problem`, `fresh_request`, `non_attempt`, `acknowledged`.

Decisions to close:

- One observation object, or a small set (a gate verdict vs. a cue reading)? A `None` return
  from `gate()` is currently how "pass through" is expressed — is that still the shape?
- Which fields are **facts about the text** (normalized form, has-question-mark, contains an
  equation, matched cue predicates) versus **interpretations** that need session state
  (`answer_try` depends on whether a check is armed)? Ticket 05 partitions the ten booleans;
  this ticket decides the shape they land in.
- Does the observation carry scores, booleans, or both? The dead `InputSignalScores` was
  float-valued and multi-label; `cues.py` predicates are boolean. The
  `points_to_consider_developer.txt` note is emphatic that the layer must stay multi-label
  and never softmax to one winner.
- Is it frozen/immutable, following `deep_freeze` and the `ModuleOutcome` conventions from
  `runtime/contracts.py`?
- Where does the safety verdict live — on the same observation, or on a separate channel so
  a safety trip can never be lost by a consumer that only reads cues?
- Does it carry a decision trace? `detect_student_problem` already returns a `cue` field
  naming which rule fired, explicitly "for the decision trace". Docx §13 wants every
  context-dependent reply to name its assumption, which needs the trace to survive.

Use `/codebase-design` — this is the module's deep interface, and the field list is where the
depth is won or lost.

---

## Resolution (2026-08-26, /grilling)

**One frozen value, `UtteranceObservation`, returned inside `ModuleOutcome`.** No second
return, no separate safety channel, no `None`-means-something.

Five organizing rules produced every decision below:

1. **Intake reports; it never decides.** It detects a safety trip but never routes one; it
   reads a confidence verdict but never holds the floor. Every decision `gate()` makes today
   it still makes.
2. **Intake is total and write-free.** Every `Utterance` yields a valid observation.
3. **Pure of session.** The observation is a deterministic function of one `Utterance`.
4. **Every judgment is welded to the trace that produced it** — nested readings, not flat
   fields beside loose cue strings.
5. **Unauthorized text may be judged but never acted on — except safety, which is never
   deferred.**

### The type

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
    safety: SafetyReading           # ticket 07 owns the internals
    legibility: LegibilityReading
    transcript: TranscriptReading   # ticket 11 owns the internals
    problem: ProblemReading
    reference: ReferenceReading
```

> **Amended 2026-08-27 by ticket 09.** The `privacy: PrivacyReading` slot is **deleted** and the
> six required readings become **five**. 09 made personal-data detection **model-only** (no
> regex, no lexicon), and Intake is model-free, network-free and pure — so it structurally
> cannot fill the slot, and a required field that can never be filled is a lie in the type.
> The verdict lives on the `personal_data` call's own output, joined to the turn by
> `utterance_id`. This is a stronger amendment than 07's, which *kept* a
> `safety: SafetySignals` slot because the lexicon still runs inside Intake.
> See `docs/architecture/PERSONAL_DATA_CONTRACT.md` §2 and §17.

`UtteranceIntake.observe(UtteranceIntakeRequest) -> ModuleOutcome[UtteranceObservation]`,
sequenced by the `TurnCoordinator` in a new `TurnPhase.UTTERANCE_INTAKE` inserted **before**
`PERCEPTION_AND_PRIOR_GRADING`.

Names: `UtteranceObservation`, not `IntakeObservation`. `PerceptionObservation` is named for
its producer because there is no single noun it observes; Intake has one, and `Utterance` is
already a glossary entry from ticket 02. `IngestedInput` and `ProcessedInput` both die.

### Top-level field decisions

| Field | Decision | Why |
|---|---|---|
| `utterance` | **embedded by reference**, not flattened into `text` / `confidence` / `alternates` | Ticket 02's organizing rule was *evidence travels welded to the text it describes*. Flattening re-splits exactly what 02 welded and re-creates the second-copy problem 02 rejected on `Utterance` itself. Consumers read `obs.utterance.confidence`; ticket 11's per-consequence gates get one address. |
| `normalized_text` | **one published form: NFC, zero-width strip, whitespace collapse. NFKC is deleted.** | Ticket 10 measured NFKC destroying `x²` to `x2`, rewriting the vulgar fraction, dropping U+2212. The field served two contradictory contracts — fidelity (the Gemini prompt, the generator) and folding (lexicon matching) — and the fidelity consumer is the one that cannot be repaired downstream. Any lossy folding a matcher needs is now **private to that matcher** and never published. This closes the question the map listed as unowned between 03 and 11. |
| `normalized_text` placement | **top level, no cue, always a `str`** | It is the substrate the readings are computed from, not a judgment; a cue would imply a trace it does not have. Ticket 11's refusal-capable maths interpretation lands in `TranscriptReading` instead — exactly the slot ticket 02 was pointing at when it said "a refusal is not a `str`". |
| `authorization` | three states, filled from an **injected policy**, never derived by Intake | See "Authorization" below. |

### The readings

**Nested sub-records, one per judgment, each carrying its own cue.** A flat shape puts
`safety_cue` and `problem_cue` side by side with nothing structurally binding a cue to the
judgment it explains — which is precisely how `problem_cue` became a bare `dict` floating in
the analyzer's `analysis`. Nesting makes "a judgment welded to its trace" a *type*, gives each
reading its own `__post_init__` invariants (a `SafetyReading` with a tier but no category
becomes unconstructable), and gives ticket 14 a natural assertion unit.

**All slots are declared here, required and non-defaulted.** Tickets 07 and 11 own only the
*internals* of theirs. (Originally six; ticket 09 deleted the privacy slot -- see the amendment
above -- leaving five.) If a whole reading could appear later, the observation would
not be a contract but a bag that grows, and every consumer written before the addition would
need revisiting. A slot whose ticket is unresolved ships reading "not evaluated" — honest and
visible, rather than absent and invisible.

| Reading | Fields | Notes |
|---|---|---|
| `SafetyReading` | ticket 07 | Detection only. `RouteResult` never enters Intake's vocabulary, so nothing here can short-circuit a turn. **Never deferred.** |
| `LegibilityReading` | `illegible: bool`, `cue: LegibilityCue` — one of `LEGIBLE`, `EMPTY`, `NO_ALPHANUMERIC`, `CHARACTER_RUN`, `NO_LEXICAL_CONTENT`, `KEYBOARD_MASH` | `is_nonsense`'s five branches collapse into one boolean today and map to one scripted reply. `EMPTY` (the microphone heard nothing — `cloud_stt.py:48`, and every `REPAIR_DISCARD`) is operationally a different event from `KEYBOARD_MASH`. Thresholds unchanged; this splits the *report*, not the decision. |
| `TranscriptReading` | ticket 11 | Carries the acoustic axis and the alternate-disagreement measure. **Never deferred** — it decides whether a repair screen is shown, so deferring it until after the repair is circular. |
| `ProblemReading` | `is_problem: bool`, `directive: bool`, `cue: ProblemCue` — one of `equation`, `expression`, `solve_verb+numerals` | `detect_student_problem` unchanged in logic. Deferred until authorized. |
| `ReferenceReading` | `anaphors: tuple[AnaphorSpan, ...]`, `word_count: int` | Evidence only. Deferred until authorized. |
| ~~`PrivacyReading`~~ | **deleted by ticket 09** | Detection is model-only; Intake cannot produce it. Not a reading. |

### Vocabulary: booleans and enums, no scores

Every remaining Intake judgment is structural. The only floats on the observation arrive from
outside (`confidence`, `word_confidences`) and are passed through on the embedded `Utterance`,
never computed here. `points_to_consider_developer.txt`'s "never softmax, always multi-label
continuous scores" rule was written for a layer that ticket 01 dissolved; it is **promoted into
the spec as a constraint on Perception**, which is what actually emits `signal_scores`, and the
file is archived (answering ticket 13's last bullet).

**`cue_matrix` does not become an observation field.** Its width is welded to the shipped logreg
(the CLAUDE.md gotcha), so publishing it would put a model-package build artifact into a runtime
contract, and the first person to add a field would break the bank.

### Which string the readings read

**Every reading runs on `normalized_text`. None runs on raw. One rule, no exceptions.**

`detect_student_problem` runs on raw today, deliberately, so "the router and the generator agree
on exactly one string"; `is_safety` also runs on raw; `is_pure_ack` runs on normalized. Nobody
ever stated a rule. The original argument for raw was that normalization *corrupted* maths — and
the NFKC deletion above removes it. What remains between raw and normalized is zero-width
characters, whitespace runs, and NFC composition, and no reading should depend on any of them.
One of them is an attack surface: a zero-width character inserted mid-word defeats a raw-text
safety lexicon and does not survive normalization. The generator-agreement concern is answered
rather than traded away — the generator is handed `normalized_text`, so there is still exactly
one string, and it is the one the readings judged.

### The trace

Per-reading, not one flat list. `detect_student_problem` already returns `cue` naming the rule
that fired, with the docstring saying it exists "for the decision trace"; that pattern
generalizes. A single `trace: tuple[str, ...]` is rejected because docx §13 needs the assumption
*attached to the judgment being reported*, not a stream to grep at the far end.

**Cue values are closed sets of constants, never free text** — ticket 14 asserts on them, and
free strings make the corpus assert on prose that will drift. `SafetyReading` carries its
category and **never the matched phrase**; `classify_safety` is already redaction-safe and stays
so. `ReferenceReading` needs no separate cue field: the anaphor spans *are* the trace, and
carrying spans rather than a boolean is what lets §8's "state the assumption" name the actual
word.

### Authorization and the deferral rule

A transcript below the floor **is not a turn yet — it is a question to the learner** (ticket 02
already makes the repair a new Turn linked by `provenance.repairs`). Judging text the learner
has not authorized produces judgments we do not believe, which some consumer will read as if we
did.

**Scope of the deferral:**

| Reading | Deferred? | Why |
|---|---|---|
| `SafetyReading` | **never** | The deterministic gate must be near-total *on its own* and nothing may **remove** recall (`gates.py:5-9`, CLAUDE.md §4.2, docx §3). A marginal transcript that trips the lexicon is a stronger reason to look, not a weaker one. What happens next is ticket 07's; being denied the input is not on the table. |
| `TranscriptReading` | **never** | It decides whether a repair screen is shown at all. |
| `LegibilityReading` | **never** | It is what reports that the utterance was empty in the first place. |
| `ProblemReading`, `ReferenceReading` | **yes** | Judgments about what the child *meant*, worthless on text they have not authorized. |

**Mechanism: compute and mark, not skip.** These are regexes over one short string, so the
saving from skipping is near zero and the argument is hygiene, not cost. Skipping would collide
with both "all slots required, non-defaulted" and "Intake is total"; marking preserves them,
makes a consumer that ignores the flag a *visible* failure in ticket 14's assertions rather than
a silent read of a missing field, and keeps the unauthorized readings as telemetry — the
comparison between what we guessed and what the child actually selected is the calibration data
ticket 02 said the repair flow exists to produce.

**Intake never compares confidence to a threshold.** `STT_WRITE_CONFIDENCE_MIN` is ticket 11's
constant, and the same principle that moved the 12-word cutoff out of `ReferenceReading` applies
here: report the evidence, let the owner threshold it. `authorization` is filled from an
**injected transcript policy** — `UtteranceIntake(transcript_policy=...)`, the same
dependency-injection seam `InteractionControlDependencies` already uses for `mode_cue=`. The
policy is itself a pure function of one `Utterance`, so the observation stays deterministic for a
fixed policy and ticket 02's `utterance_id` memo key still holds. Tests stub the policy and get
every branch with no Vertex call and no audio fixture.

**Three authorization states, and the fold is forbidden.** `DISCARDED` cannot collapse into
`UNAUTHORIZED` with consumers checking `source` for the difference: ticket 02 permits **exactly
one** branch on `source` in the entire runtime and ticket 14 asserts it. The state has to be
real — which is right anyway, because the three route differently, and folding would show a
second repair screen to a child who has already told us we cannot hear them. Ticket 02 called
the discard the most valuable signal we can collect about the recognizer; a distinct state is
what stops it being read as "not yet".

### Why the anaphora evidence can live in a session-free module

Ticket 12's §8 requirement needs the previous turn, which Intake cannot see. The split that
resolves it: **detecting** an anaphor is a fact about the text alone (which token, at which span,
in an utterance of N words); **resolving** it — deciding that "this" means the current concept,
with what confidence — needs session state and stays with the module that already holds the
resolved concept. Intake supplies evidence; the next layer binds it. §8's three-band confidence
therefore stays with the only module that can actually produce a band.

Two consequences: `is_same_problem_followup` (it reads `session["context"]` for a prior WINI
reply carrying digits) does **not** come to Utterance Intake — ticket 05 places it. And the
**12-word cutoff leaves Intake entirely**: Intake reports `word_count`, and ticket 12's band
producer applies whatever threshold it can justify by measurement. That answers 12's "keep,
justify, or replace" as *replace with evidence*. `names_own_topic` is dropped: deciding it needs
the concept catalog, so it is Perception's judgment and would smuggle a semantic call into a
model-free layer.

### Failure semantics: Intake is total

**`value` is never `None`. `failures` is always `()`. `state_changes` is always `()`.**

Intake is a pure deterministic function with no I/O, no model, no network. Ticket 02 made empty
`text` legal — "heard nothing" is a runtime state to be *decided* about, not a constructor crash
— and `REPAIR_DISCARD` is empty text by design. Every `Utterance` therefore yields a valid
observation.

- **No new `RecoveryCapability`.** `RecoveryPolicy.decide` falls through to `FAIL_CLOSED` on an
  unrecognized capability (`runtime/coordinator.py:70-88`); that path is never reached from this
  module.
- **If a bug raises, it propagates.** On a child-safety path a crash beats a fabricated "nothing
  tripped".
- **Write-free** keeps rule 1 clean: Intake detects, it never decides, and persisting a safety or
  privacy case is a decision with a policy behind it. The docx §11 "minimised, access-controlled
  case reference" belongs to whoever owns the safety route — the only place that knows whether
  the turn was escalated. Rule 3 means Intake cannot read `learner_state` and so could not compute
  a delta anyway.

### Immutability

Frozen dataclasses throughout, `deep_freeze` on mappings, tuples for sequences, `__post_init__`
invariants that **raise** rather than clamp — the same conventions ticket 02 chose, for the same
reason: a silent clamp inside a value type is how a bug becomes a confident number again.

### `gate()` keeps `None`-means-pass

`gate()` stays in `perception/` per ticket 01 and now reads the observation instead of raw text,
collapsing to a pure translation: safety reading tripped gives a SAFETY `RouteResult`; else
legibility reading illegible gives a NONSENSE `RouteResult`; else `None`. The signature is
unchanged (`Optional[RouteResult]`) — its only caller already branches on exactly that
(`perception/interface.py:104`), the SAFETY-beats-NONSENSE priority stays visible in one place,
and `RouteResult` stays out of Intake's vocabulary so the dependency remains one-way.

Two things to write into the spec: that `gate()` becoming a pure translation with no detection
logic left in it is the **tell that the seam landed correctly**, not a reason to move it; and
that `gate()` reads the **textual** axis only. Nothing acoustic feeds NONSENSE.

### Why textual legibility cannot catch the real voice failure

An autoregressive recognizer's failure mode is not garbage — it is **fluent, well-formed,
confident English the child never said**. Every `LegibilityReading` cue is a character-class
test, so a hallucinated "the answer is seven" passes all of them. And production is voice-only
(ticket 02), so `KEYBOARD_MASH` and `CHARACTER_RUN` are artifacts of a keyboard that does not
exist on the device: `is_nonsense` is calibrated for a threat model that cannot occur and blind
to the one that can.

No text-shaped test fixes this, because the text is fine. The signal is entirely acoustic, and
ticket 02 already put every piece of it on `Utterance` and already specified the response — the
repair screen. Hence:

- **Two independent axes, never fused.** Textual illegibility is a dead end: the turn produced
  nothing, and `gate()` translates it to NONSENSE. Acoustic doubt is *recoverable*: the words may
  be right, and the answer is the repair screen with the learner choosing. Fusing them yields a
  boolean meaning "one of two unrelated things went wrong" — the exact collapse this ticket split
  apart. **No acoustic input reaches `gate()`**, so a hallucination-from-noise turn never gets a
  scripted NONSENSE reply.
- **No `source` branch for the keyboard-only cues.** They are computed unconditionally and are
  simply unreachable from VOICE as a matter of the input distribution, not of control flow.
  Ticket 02's one-branch invariant needs no amendment. They survive for TYPED
  (`interactive_tester.py`, the eval harness) at exactly zero runtime cost. `EMPTY` is the one
  textual cue that carries real production weight, a further argument for having split the cue
  set.
- **Intake derives an alternate-disagreement measure** into `TranscriptReading`; ticket 11 fixes
  its form and any threshold. Five near-identical hypotheses mean the recognizer was confident
  about a real utterance; five divergent ones mean it was inventing. It is a pure function of the
  `Utterance`, so rule 3 puts it here by construction, and ticket 02 already forced
  `max_alternatives=5` unconditionally for this class of reason. **The guard:** computing a
  measure *over* the alternates is not substituting one for the primary — ticket 02's rule (no
  consumer may swap in an alternate, nothing re-runs Perception or grading on one, they are only
  offered to the learner) survives untouched. This is the "consulted as disagreement evidence by
  whoever ticket 11 authorizes" clause it already anticipated.
- **Note the interaction with deferral:** the measure runs *before* authorization, not after. A
  fluent *confident* hallucination never trips the floor and so never shows a repair screen —
  under a strictly post-confirmation rule the detector would be disabled in exactly the case that
  motivated it.

### Rejected, recorded so it is not re-argued

- **A separate safety channel** (a second return value, or a `FailureSignal`). The instinct — a
  trip must never be *lost* — is right, but a second return is exactly as ignorable as a field;
  both are "the consumer did not look". Loss is prevented structurally three other ways: the
  field is required and non-defaulted so no constructor can omit it; `gate()` is a mandatory
  reader in the very next phase; and ticket 14 asserts it. `ModuleOutcome.failures` is the only
  channel the *coordinator* inspects, but a safety disclosure is not a module failure and
  `valid_outcome` would have to lie.
- **A session-carrying request.** `PerceptionRequest` carries `session` and `learner_state`;
  `UtteranceIntakeRequest` carries `turn_input` only.
- **Reviving `_contains_formula`** (ticket 13's open bullet). It is `any(marker in text)` over
  `= + - * / ^` and two logic symbols, so it fires on "well-known", on any dash, on any
  hyphenated word. `_EQUATION_RE` / `_EXPRESSION_RE` inside `ProblemReading` are strictly
  stronger, and `ProblemReading.cue` distinguishing `equation` from `expression` from
  `solve_verb+numerals` carries **more** information than `contains_formula: bool` ever did — so
  the audit's D-1 loss is repaid, not ignored. `tokens` and `contains_numbers` have no consumer
  and would be two more fields for ticket 15 to hold bit-exact for nobody. `has_question_mark` is
  subsumed by Perception's `question` label per ticket 01.

### Correction to an inherited fact

**Ticket 01's manifest is wrong that `cue_matrix` is "build-time only, zero runtime importers".**
`PolicyShadow.suggest` calls it (`policy_shadow/shadow.py:79`) and is invoked **unguarded on
every learning turn** at `tutor_loop.py:2463`, inside `_legacy_turn`. A 9-wide float feature
vector is therefore computed from normalized text on the live path today.

**Disposition (user, 2026-08-26): ticket 04 is NOT reopened.** `PolicyShadow.suggest` gets a new
feature path of its own rather than this becoming a cues-split question. Recorded in the map.

### Consequences handed to other tickets

- **04** — unchanged by the `cue_matrix` finding above; not reopened.
- **05** — `ProblemReading` and `ReferenceReading` are the only inline derivations Intake
  supplies. The five fusions stay consumer work per ticket 01, and `is_same_problem_followup` is
  not Intake's.
- **07** — `SafetyReading` runs at every confidence and on every source. A marginal safety trip
  is 07's to *route*; it is never Intake's to drop. 07 also inherits the §14 sixth-route question
  with the input now guaranteed present.
- ~~**09** — owns `PrivacyReading`'s internals; the slot and its required-ness are fixed here.~~
  **Resolved 2026-08-27: the slot is deleted.** 09 chose model-only detection, which Intake
  cannot host. Six readings become five; see the amendment note above.
- **11** — materially larger. It owns the floor constant, the injected transcript policy, the
  alternate-disagreement measure, the maths refusal (landing in `TranscriptReading`, since
  `normalized_text` is always a plain `str`), and now the **only detector that catches a fluent
  hallucination**.
- **12** — narrowed to "what does Intake's evidence contain". The 12-word cutoff is 12's to
  justify by measurement or discard.
- **13** — answered: `_contains_formula`, `tokens`, `contains_numbers`, `has_question_mark` do
  not return; `points_to_consider_developer.txt` is archived with its still-binding rule promoted
  as a constraint on Perception; the two-instances problem dissolves because Intake is a Feature
  Module.
- **14** — corpora need audio-derived cases that cannot be written as plain strings: a fluent
  **high-confidence** hallucination, a fluent **low-confidence** one, and a divergent-alternates
  set. Plus all three authorization states, the six `LegibilityCue` values, and an assertion that
  no consumer reads an unauthorized `ProblemReading` / `ReferenceReading`.
- **15** — three measurable deltas, none assumable: `detect_student_problem` moving from raw to
  normalized text; the NFKC removal; and the `TurnPhase` insert, which is a real coordinator
  change because `_validate_phase_trace` requires the trace to equal `LOGICAL_TURN_PHASES`
  exactly (`runtime/coordinator.py:385`).

### Flagged, not relitigated

Because `authorization` is filled from ticket 11's injected policy, the transcript floor is
consulted **inside the first phase of the turn**. `UTTERANCE_INTAKE` becomes the earliest point
at which an STT threshold has runtime effect, and 11's policy becomes a hard construction
dependency of Intake. Consistent with everything decided here, but it is the one place where a
later change to ticket 11 reaches back into this module's construction.

### Explicitly not decided here

`SafetyReading` internals and the six-route taxonomy (07); the personal-data contract (09 --
no `PrivacyReading`; the slot is deleted);
`TranscriptReading` internals, the floor value, the disagreement measure's form, and the maths
grammar's refusal outcome (11); the coreference bands and the word-count threshold (12); where
the five fusions and `is_same_problem_followup` land (05); the repair screen's display element
shape (response-side, per ticket 02).

---

## Amended by ticket 07 (2026-08-26)

Ticket 07 inverted the safety architecture: a dedicated Gemini call
(`cloud_run_service/child_safety/`) is now the **primary** safety detector, and the regex
lexicon is the degraded-mode outage net. Three amendments to this contract follow. Everything
else in the Resolution stands unchanged.

1. **`safety: SafetyReading` is renamed `safety: SafetySignals`.** The name `Reading` implied
   a verdict; this slot now carries the **lexicon's signals only** (`source=LEXICON`,
   enforced as an invariant — `MODEL` is unconstructable inside Intake, which runs before any
   model call). It is computed on every turn, but on a healthy turn it is **not the verdict**:
   it is consumed only in degraded mode and by the divergence monitor.

2. **`severity` is not on the reading.** It lives on the composed `SafetyVerdict`, produced
   downstream in `interaction_control`. This is the "one derivation site" rule applied
   consistently: no detector, model or lexicon, ever writes severity. `SafetySignals` carries
   `tripped`, `findings: frozenset[SafetyFinding]`, `caregiver_implicated`, `imminence_cue`.

3. **Rule 5 is unchanged and now load-bearing in a second way.** "Unauthorized text may be
   judged but never acted on — except safety, which is never deferred" still holds; ticket 07
   adds that a **`DISCARDED`** transcript's safety finding also survives (stamped
   `transcript_discarded`), because a UI tap must not be able to delete a safety signal.
   Severity is **not** capped on an unconfirmed or discarded transcript — instead the
   emergency-resource script waits for the docx §12 direct question.

The nested-reading design, the required slots (six, less the privacy slot ticket 09 deleted), the "detects but never decides" rule, the
write-free/total/pure-of-session rules and the redaction rule ("carries its category and
never the matched phrase") are all confirmed by 07 — the trace is now specified as the
**pattern's stable id**, never the matched span.

See `docs/architecture/SAFETY_ROUTE_TAXONOMY.md` §15 (types + invariants) and §9.
