# Decide the STT uncertainty contract

Status: resolved
Type: grilling
Blocked by: 02, 10

## Question

How does transcription uncertainty flow through the Input Layer, and what does it forbid
downstream?

Today there is one number and one comparison. `interaction_control/control.py:248-252` reads
`stt_confidence` from `trusted_observations`, defaults it to `1.0` when absent, clamps to
[0,1], and compares to `STT_WRITE_CONFIDENCE_MIN` (0.60). Below the floor,
`_low_confidence_result` (`control.py:670-722`) returns a re-prompt. Above it, uncertainty
vanishes — nothing downstream knows the transcript was marginal.

Two consequences worth naming:

- **In text testing the gate never fires.** No STT means confidence defaults to `1.0`, so
  input "quality" in every text test is judged only by the NONSENSE regex
  (`gates.py:96-121`). The `_low_confidence_result` branch is unreachable without a real
  sub-0.60 value. The path is effectively untested on the input it exists for.
- **Confidence is scalar and global**, so §9's "a low-confidence *word* that changes an
  answer produces a clarification, not a score" cannot be expressed — there is no per-word
  channel.

Decisions to close:

- What are the **consequence gates**? §9 lists four: scoring an answer, changing level,
  recording a misconception, and sending a safety escalation. Each currently has a different
  owner. Does the Input Layer emit one "uncertain" flag, or a set of per-consequence
  permissions? Note `RouteResult.uncertain` already exists (`route.py:37`) with the comment
  "fallback has no state-write authority" — but it means *perception degraded*, not *transcript
  doubtful*. Two different uncertainties currently share one field name. Disambiguate.
- Does the **N-best set** survive into the observation, and who is allowed to consult it?
  §9's accessible-repair requirement ("tap the word") needs alternates at the UI.
- What triggers **confirmation**, and what does the layer hand the confirmation UI? §9's pass
  condition is that the child can "answer yes/no, tap a displayed alternative, or type" —
  that implies the alternate text travels.
- Where does the **maths grammar** from ticket 10 sit: inside `normalize_input`, or as a
  separate parse step that may refuse? Refusal is a new outcome the current normalizer has no
  way to express (it returns `str`).
- **Idempotency.** CLAUDE.md: the Gemini call is memoized by normalized text and
  `normalize_input` must stay idempotent. A grammar-rewriting normalizer must preserve that.
- Is there a **non-voice fallback** contract the layer must support (§9: "Every voice-only
  failure has a non-voice fallback")?

Also settle the test question: what does an audio-confidence test harness feed, and does it
belong in ticket 14's corpora?

---

## Rulings handed down by ticket 07 (2026-08-26)

07 answered the safety half of 11's "consequence gates" question. 11 still owns the other
three consequences (scoring, level change, misconception), the N-best contract, the maths
grammar and the confirmation UI.

**Safety escalation is not gated by the transcript floor.** Docx §9 lists "sending a safety
escalation" among the things needing confirmation, and §12 says pause and ask directly. They
reconcile: the safety **response** — acknowledge, pause, ask the one direct question — *is*
§9's confirmation step expressed in §12's language. It is not one of §9's four state/external
consequences.

Therefore:

- A safety trip at **any** confidence, from **any** source, produces the safety response
  path. Never deferred, never downgraded.
- A low-confidence transcript stamps the case record `transcript_unconfirmed` and carries the
  alternates — and the record is **still written and still notified**. Withholding a real
  disclosure because the microphone was poor is the failure the axis exists to prevent.
- `Authorization.DISCARDED` (learner rejected every hypothesis) does **not** delete the
  finding; it stamps `transcript_discarded`.
- **Severity is never capped** by transcript quality — capping is a downgrade. Instead,
  `CRITICAL`'s emergency-resource script is **withheld until the §12 direct question is
  answered**, while the acknowledgement and the pause run immediately.
- The ticket-02 repair screen is **suppressed** on a safety trip: never replay or quote a
  safety phrase back to the child.

Note also that 07 disambiguated the `RouteResult.uncertain` collision 11 flagged from the
other side: `safety_tier`/`safety_category` are deleted from `RouteResult` and replaced by one
`safety` field carrying the composed verdict, whose transcript stamps are explicit fields
rather than an overloaded boolean.

See `docs/architecture/SAFETY_ROUTE_TAXONOMY.md` §9.

---

## Resolution (2026-08-26, /grilling)

**Doubt is evidence, not a decision — and absent evidence is never the absence of doubt.**
Utterance Intake publishes everything it knows about the transcript and exactly *one*
decision (`Authorization`). Every per-consequence rule is stated on the consumer, in the
spec, not encoded as a permission field. The floor stops being a number three modules each
re-check and becomes a verdict computed once from three independent signals.

### Eleven premises corrected before anything was decided

1. **Three uncertainty channels exist, not two.** Besides `RouteResult.uncertain` and
   `stt_confidence`, `pacing/triage.py:33` takes `stt_uncertain: bool` and hard-routes to
   `state_policy="no_write", route="clarify"`. It is wired from `voice_hybrid_runner.py:137`
   and `voice/live_tools.py:63` (legacy ROS paths) — but `wini_server.py:652` calls
   `before_turn(transcript, self.tutor)` with no `stt_uncertain`, so **on the production
   Cloud Run path it is permanently `False`**.
2. `RouteResult.uncertain` propagates into four further names:
   `PerceptionObservation.uncertain` (`perception/interface.py:64`),
   `InteractionControlRequest.perception_uncertain` (`control.py:50`),
   `AssessmentRequest.perception_uncertain` (`assessment_evidence/interface.py:49`),
   `PedagogyObservation.uncertain` (`pedagogy/interface.py:38`). A 7-site rename, not a 1-site one.
3. **§9's four consequences do not have four owners here — they have two, and one does not
   exist.** Marking (`assessment_evidence/interface.py:113-118`), recording a misconception
   (`evidence/ledger.py:197`) and mastery movement are **the same write path behind the same
   constant**. There is no "level": `query.py` derives a ZPD difficulty band *from* mastery,
   downstream of the ledger write. Safety escalation is **already exempt** — `_record_safety`
   fires at `control.py:229` and `:310`, both *before* the floor check at `:248`.
4. The floor gates the **LEARNING path only** (`control.py:248` sits after the non-learning
   return at `:229`).
5. "In text testing the gate never fires" was already fixed by ticket 02 — TYPED carries
   `confidence=None`, and `None` is not comparable to a floor. What survives is a different
   question: what `None` means to each consumer.
6. **§9's "and the active concept" contradicts ticket 03's rule 3** (Intake is pure of
   session). Unowned until this ticket.
7. **The 0.60 floor is a documented placeholder for a decision record that was never
   written.** `WINI_LAYERED_ARCHITECTURE.md:335` specifies it as *"start 0.6, calibrate per
   DEC-044"*. `DEC-044` appears **once** in the entire repository — in that sentence.
8. **Google documents `latest_short`'s confidence as not a true confidence score.** The
   latest-models page lists, among features the latest models do *not* support: "Confidence
   scores—The API will return a value, but it is not truly a confidence score." This is the
   same caveat research §4.2 found on Chirp 2/3 and framed as a future trap. It is not future;
   it applies to the model in production today. **The 0.60 floor has always thresholded an
   uncalibrated, self-disclaimed, mean-averaged number.**
9. **Streaming STT is dead code.** `CloudStt.recognize_stream` has zero callers; production
   goes through `recognize_pcm_evidence` (`wini_server.py:607-611`). Ticket 10's D6 is
   therefore **not** blocking.
10. **`EMPTY` never reaches Intake today.** `wini_server.py:616-620` early-returns on an empty
    transcript — *"nothing recognized … don't burn a turn"*. Ticket 02 made empty text legal
    and ticket 03 gave it a `LegibilityCue`, both reasoning about a state the capture edge
    intercepts one layer up.
11. **Ticket 02 undercounted the `interaction["text"]` blast radius three-fold.** It names two
    changing consumers; there are **six** readers: `assessment_evidence/interface.py:85`,
    `control.py:219` and `:682`, `perception/interface.py:101`, `retrieval/interface.py:303`,
    `legacy_adapter.py:305`. And `AssessmentRequest` (`:44-50`) carries **no observation**, so
    Assessment structurally cannot reach `normalized_text`, `authorization` or
    `TranscriptReading` — which three decisions below require it to.

### Facts verified against Google's primary documentation (2026-08-26)

| Fact | Consequence |
|---|---|
| `enable_word_confidence` **is** supported for `en-IN` + `latest_short` (v1 language table) | Resolves the call ticket 02 deferred here: turn it on |
| `WordInfo.confidence` documents `0.0` as a **sentinel for "was not set"**, with the same "not guaranteed to be accurate … should not rely on it to be always provided" wording as the utterance-level field | The adapter must map `0.0` → `None`, or ticket 02's "absence is never a number" rule is defeated one level below where it was written |
| The word-confidence how-to is still labeled **Preview** (pre-GA terms) | A child-safety gate resting on a pre-GA signal — stated as a risk, not discovered later |
| `max_alternatives` range is **0–30**; confidence stays top-alternative-only regardless | Ticket 02's choice of 5 holds unchanged; raising it populates no new scores |
| **v1 STT offers only US and EU regional endpoints**; `asia-south1` is not a v1 region | STT and Vertex are **not** co-located. Never assume it in the spec |
| v2 lists `asia-south1` as a location, but the per-model matrix for it came back **UNVERIFIED** | If the streaming rebuild moves to v2, that matrix must be checked via the Locations API |

### The vocabulary: three uncertainties, three names

- `RouteResult.uncertain` → **`perception_degraded`**, renamed across all 7 sites. It means
  *the Gemini call fell back* (`gemini_perception.py:412`) — a **producer** failure, not an
  input one, and its name has been lying since it was written.
- The bare word **"uncertain" is banned as a field name** in the new contract. Transcript
  doubt is named for what it is at every level (`transcript_doubtful`, `DoubtCause`, …).
- `triage_turn(stt_uncertain=)` is left alone as legacy, with a spec rule: **it is not the new
  policy's channel and must not be re-wired to it.** Its `route="clarify"` collapse is exactly
  the one-flag design this ticket replaces.

### The gating model: evidence plus one decision, never a permission set

The ticket asked "one `uncertain` flag, or a set of per-consequence permissions?" **Neither.**
A four-permission set would invent structure with no distinct owner (premise 3): three of §9's
four consequences are one ledger write, and the fourth may never be gated at all. One flag is
what we have and cannot express §9's pass condition.

- **Intake emits evidence** (`TranscriptReading`) **plus exactly one decision**
  (`Authorization`, ticket 03's three states).
- **Per-consumer rules live in the spec**, enumerated per consumer, not as fields.
- **Two tiers with genuinely different inputs.** *Tier 1, utterance-level*: doubt →
  `UNAUTHORIZED` → repair screen, no turn. *Tier 2, span-level*: a contested span →
  clarification instead of a score. Tier 2 cannot be Intake's decision because §9's trigger is
  "a low-confidence word **that changes an answer**", and whether a span changes the answer
  needs the pending item, which rule 3 forbids Intake from seeing. **Intake publishes
  contested spans; the consequence owner decides load-bearing.**
- **Hard invariant, asserted by ticket 14: the safety path never reads `authorization` or
  `TranscriptReading`.** It is already structurally exempt (premise 3); this makes the
  exemption deliberate instead of incidental, and consistent with `gates.py:5-9`'s "may only
  add recall, never remove it".
- **`confidence is None` means *no gate*** — never "trusted", never "distrusted". Matches
  `ledger.py:197`, corrects `control.py:249`, and is stated **once** so three modules stop
  each deciding it privately.

### `TranscriptReading`

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

- **`repair_choices` is the one sanctioned export of the alternates.** The response layer reads
  this curated, deduped, top-3 list and is **forbidden** from reading `utterance.alternates`,
  which ticket 03 embedded whole and which is therefore technically reachable. A separate field
  is what turns the alternates rule into something ticket 14 can assert.
- **`span is None` on `PASSTHROUGH` by construction** — the non-maths guard as a type
  invariant rather than a convention.
- **`causes` is a tuple, not one value.** Several signals can fire at once, and knowing *which*
  is what makes the provisional thresholds correctable.

### The doubt verdict and its thresholds

`transcript_doubtful` is a **verdict**, not a float comparison — because the float is the one
Google disclaims (premise 8) and `cloud_stt.py:68-71` averages it across result segments, so a
single mangled word is smoothed away (ticket 10's D1). Three signals, **OR-ed**:

| Signal | Threshold | Initial value |
|---|---|---|
| utterance confidence | below floor | **0.60**, unchanged |
| minimum word confidence | below floor | **~0.40** — it is a *minimum over words* and trips far more readily than a mean |
| alternate disagreement | above ceiling | **conservative**: top-3 differing across more than half their aligned positions |

- **OR is the only combination monotone in the safe direction** — more evidence of doubt can
  only *add* a repair screen, never remove one. Same discipline `gates.py:5-9` imposes on
  safety, applied to a second axis. A fused score needs weights nobody can justify today.
- Three env-backed constants through the existing `runtime_flags.confidence_floor` helper.
- **`STT_WRITE_CONFIDENCE_MIN` is retired as a name.** It names a write gate that no longer
  exists; leaving the name attached to a repair-screen trigger guarantees someone re-derives
  the old meaning from it.
- **All three values are marked provisional and uncalibrated in the spec**, with the captured
  corpus (below) named as the instrument. The disagreement threshold ships **conservative
  rather than disabled**: disabled puts us back on the float alone, which is what this section
  rejects; loose shows repair screens on good turns and trains the child to tap through them,
  which ticket 02 rejected. Conservative-and-loosenable is the only direction correctable by
  evidence.
- **DEC-044 is either written or explicitly killed** — not left dangling a third time.

**The disagreement measure's form** (ticket 03 handed it here): token-position comparison
across the top-3 distinct hypotheses, producing both outputs in one pass — `contested_spans`
(the positions where they disagree) and `disagreement = len(contested_spans) / max_len`.
Alternates from one recognizer over one clip are near-parallel, so whitespace tokenization and
position-wise comparison suffices, with proper alignment only as the length-mismatch fallback.
**Computed over `normalized_text`**, per ticket 03's one-string rule, so the spans index the
published form and stay valid — the mirror of ticket 02's refusal to carry character offsets
*across* normalization. These spans are computed after it, so no alignment map has to survive a
rewrite and the provenance stays honest.

### The maths grammar

**Split by refusal kind, which resolves premise 6 without breaking rule 3.** Research §3.1's
four refusal kinds fall cleanly on either side of the session-purity line:

| Kind | Where | Why |
|---|---|---|
| **R1** out-of-grammar | Intake | a property of the string alone |
| **R2** ambiguous | Intake | a property of the string alone |
| **R3** low-confidence span | not a grammar concern | it is Tier 2 above |
| **R4** concept-inconsistent | **Assessment** | needs the active concept *and* the expected answer |

The **other** half of §9's "active concept" is satisfied without touching Intake at all: the
per-turn `inlinePhraseSet` (research §4.3) is built at the **capture edge**, which already holds
the session. **The concept scopes the recognizer, not the parser.**

- **Engine: lark Earley with `ambiguity='explicit'`.** `len(CollapseAmbiguities(tree)) > 1`
  **is** the refusal predicate, and the competing trees are simultaneously the clarification
  material. Research §3.2 establishes PEG structurally cannot detect R2 (prioritized choice)
  and LALR reports conflicts at build time only. Pure Python, so ticket 14's import purity
  survives. A hand-written conflict table catches only anticipated ambiguities, which is
  precisely how `math_grade` reached four measured confident false negatives.
- **Placement:** `cloud_run_service/utterance_intake/grammar/` — inside the Feature Module per
  ticket 01. One consumer, no independent lifecycle.
- **The grammar sits *beside* `math_grade.normalize`, not over it.** Superseding it puts a
  grading behaviour change on this effort's critical path for no gain this ticket needs.
- **v1 scope:** exactly the shapes `math_grade` already grades — numbers and number words,
  fractions ("one over three", "one by three"), roots ("root two", "square root of two"),
  signed values, equalities ("x equals 2"), unordered pairs — **plus exponents** ("three
  squared", "x cubed", "to the power"), which ticket 10 measured as entirely absent and which
  is §9's own worked example. A grammar scoped to what the grader can compare is one whose
  refusals mean something.
- **Acceptance is two-sided and both halves are measured:** the four measured confident false
  negatives must stop being confident — each becomes a correct parse or a refusal, never a
  silent wrong — **and** the refusal rate on a clean-utterance corpus must stay under a stated
  ceiling. Only the second stops a grammar that refuses everything from passing the first
  trivially. Calibration note from research §5.1: Spoken-MQA found **32 of 100** MATH problems
  ambiguous to humans without visual context, so a near-zero refusal rate is a **failing**
  result.

**`PASSTHROUGH` is the common and legitimate outcome, and the burden sits on the claim.** The
parser claims a span as mathematical only on **positive evidence**; out-of-grammar is a refusal
**only** when a claimed span then fails to parse. Otherwise "i don't know" — or a topic
question carrying a stray numeral ("what is chapter 3 about?") — shows a repair screen for a
non-maths utterance. **Only the two REFUSE outcomes set `doubtful`.** (User decision,
2026-08-26: a new method may be added for maths-term checking, but there must be no error
screen for non-maths input, because a learner may ask about a topic containing no maths at all.)

**The interpretation is consumed, not merely audited.** Assessment grades
`MathParse.interpretation` **when and only when `outcome is ACCEPT`**, falls back to today's
`math_grade` path on `PASSTHROUGH`, and never grades on either REFUSE (the turn is
`UNAUTHORIZED` by then anyway — belt and braces). Without this, Intake would correctly parse
"three squared" → `3^2`, publish it, and Assessment would independently fold it to `"3 squared"`
and grade it **wrong** — §9's own worked example still broken after a whole ticket about it,
and all four measured false negatives surviving the effort. This does **not** breach ticket 03's
one-published-string rule: `normalized_text` remains the single published *transcript*, while
`interpretation` is a typed reading carrying its own outcome tag and derivation — the opposite
of a floating second copy. **R4 then applies to `interpretation`**, which is what made it
Assessment's in the first place: it finally has a tree-derived reading to check the concept
against.

**Idempotency (the ticket's fifth decision) dissolves.** Ticket 02 moved the perception memo to
`utterance_id`; ticket 03 deleted NFKC and fixed `normalized_text` as NFC + zero-width strip +
whitespace collapse. **The normalizer never rewrites maths at all**, so `normalized_text` is
trivially a fixed point, and `interpretation` is produced once and never re-parsed. Research
§6.2's fixed-point hazard cannot arise.

### The repair flow

- **Alternates never leave Utterance Intake.** No downstream layer consults them. The learner
  selects a choice or taps "none of these". This satisfies §9's "clarification, not a score"
  more directly than a downstream gate would: a confirmed transcript is **learner-authorized**
  before anything scores it, so no score is ever computed on unconfirmed text.
- **One screen for both causes, with the cause recorded.** Acoustic doubt and an ambiguous
  parse share the flow — same `doubtful`, same `UNAUTHORIZED`, same three-choices-plus-discard
  shape from ticket 02. For the child the experience is identical, and a second screen type is
  a second thing to build, test and read aloud on e-ink. But `TranscriptReading.causes` records
  **which** fired, because the fixes are unrelated: acoustic doubt is a recognizer problem, R2
  is a grammar problem, and a spec that blurs them cannot tell you which to work on. The
  rendered choices differ by cause — hypotheses for acoustic doubt, competing readings for
  ambiguity — but that is payload, not control flow.
- **The payload carries the strings *and* the differing spans**, which Intake gets free from
  the disagreement measure. Without them a voice-first device reads three near-identical full
  sentences aloud — the readback ceiling ticket 02 used to set the number 3. §9's own script
  names the contested word: *"I may have heard factors. Did you mean factors or fractions?"*
- **The original turn produces only the screen** — no perception call, no grading, no state
  write. That is what `UNAUTHORIZED` at phase 1 is *for*, and it also means a doubtful turn
  costs **no Gemini call**. The repaired turn re-runs the full pipeline from Intake on the new
  `REPAIR_SELECTION` utterance. `REPAIR_DISCARD` produces a scripted retry and no pipeline.
- **`REPAIR_SELECTION` carries `confidence=None`** — it came from a tap, not from acoustics;
  `provenance.selected_alternate_index` carries the traceback. Ticket 02 left this open.
- **Both downstream float checks are deleted.** `evidence/ledger.py:197` and
  `assessment_evidence/interface.py:113-118` are replaced by an `authorization is AUTHORIZED`
  precondition. A raw-float re-check downstream would **suppress a write the child personally
  confirmed** — §9's failure mode running backwards. The ledger's check survives as
  defence-in-depth but **raises** rather than silently suppressing: reaching `record_outcome`
  with an unauthorized utterance is a coordinator bug, and `status="suppressed"` is how it
  would hide for months.

**Non-voice fallback (§9's pass condition).** Production hardware has no keyboard (ticket 02);
text input exists only at testing time. The contract requires **at least one non-voice path per
voice failure**, met by tap-selection plus the discard button. **"Type it" is recorded as an
explicit, reasoned hardware deviation** from §9's enumeration — available on TYPED harnesses
only — rather than silently dropped. Intake's own obligation is narrow: mark the turn
repair-eligible and hand over the choices; which surfaces are offered is response-side.

### The policy seam

`transcript_policy: (Utterance, TranscriptReading) -> Authorization`, injected per ticket 03.
It needs the utterance for `source` (ticket 02's single permitted `source` branch — TYPED →
AUTHORIZED) and the reading for the verdict. Ticket 03's testability argument survives intact:
stub the policy, reach every branch, no Vertex and no audio fixture, thresholds injectable
rather than baked.

**`authorization` and `doubtful` both stay, and the redundancy is *checked*.** They are
different statements: `doubtful` is a **finding** ("the evidence says we may have misheard");
`authorization` is a **decision** ("this text may have consequences"), with a third state,
`DISCARDED`, that no finding produces. Collapsing them puts the decision back inside the
detector — the inversion ticket 03's rule 1 forbids. Instead, ticket 14 asserts the relation as
an invariant: **for `source is VOICE`, `authorization is UNAUTHORIZED` iff
`transcript.doubtful`.** A policy that drifts from its own evidence fails a test instead of
shipping.

### The audit record

**Two artifacts, different content, different owners.**

- **The full parse record lives on `TranscriptReading` for the turn.** That is where the
  refusal must be readable to decide the turn at all.
- **A minimized copy goes to the evidence ledger, and only when a consequence actually
  followed**: outcome, rule identifier, span, `grammar_version`, competing-derivation count.
  **Never the raw transcript** — docx §11 plus the existing redaction discipline at
  `tutor_loop.py:1884`.

Two reasons for the split: an audit record for a turn that changed nothing is volume with no
reviewer, and ticket 03 made Intake **write-free**, so the ledger write belongs to whoever owns
the consequence — the only module that knows one happened.

### The capture edge: a handoff, not an implementation

**User decision, 2026-08-26:** none of the capture-edge changes are implemented in this effort.
The STT layer is being rebuilt as a **streaming service** by a different developer (the current
code is HTTP POST/GET, not streaming), and doing the work once is cheaper than doing it twice.
This ticket therefore produces **requirements**, not code.

| Disposition | Items |
|---|---|
| **Required of the producer** (handoff) | `max_alternatives=5`; `enable_word_confidence`; `enable_word_time_offsets`; the `0.0` → `None` sentinel mapping; minting `UtteranceProvenance`; **deleting the `stt_confidence = 1.0` fabrication at `wini_server.py:613`**; **removing the empty-transcript early return at `wini_server.py:616-620`** |
| **Deferred with an owner** | the per-turn concept phrase set (needs the concept card's vocabulary and a v1-vs-v2 `inlinePhraseSet` decision; §9's "active concept" is already half-satisfied by the R1/R2/R4 split); `en-US` → `en-IN` (a genuine accuracy question that changes every transcript in the system and deserves its own measurement) |
| **Closed as resolved** | streaming STT's confidence loss (dead code, zero callers); the diverged `cloud_stt.py` copies (ticket 13's) |

The empty-transcript removal is **required, not optional**: ticket 02 made `REPAIR_DISCARD` an
empty-text `Utterance` precisely so a discard reaches the ledger as recognizer evidence, and
ticket 03 gave `EMPTY` a cue. Both are dead on arrival while the server swallows empty
transcripts one layer up — the same class of defect as `wini_server.py:652` silently never
passing `stt_uncertain`.

**`Utterance` survives the streaming rebuild unchanged; the producer is constrained instead.**
Google documents confidence as set "only for the top alternative of a non-streaming result **or,
of a streaming result where `isFinal=true`**", so a streaming recognizer can satisfy the whole
contract — from final results, and only those. Three handoff requirements follow:

1. **One `Utterance` per final result, never from an interim one.**
2. The utterance boundary is the recognizer's **endpointing**; `provenance.duration_ms` and
   `captured_at` come from its segmentation.
3. **Intake never runs on a non-final result.** A streaming recognizer *revises*, and a turn
   started on text later retracted is a state write against something the child never said.

**No `is_final` field is added.** A non-final result must never become an `Utterance` at all,
and a field for it invites someone to construct one and branch — the same reasoning ticket 02
used to reject deprecated mirrors. An unrepresentable state cannot be mishandled.

**The handoff artifact:** one Markdown file at **`docs/architecture/STT_CAPTURE_CONTRACT.md`**,
beside the two research docs because it outlives the ticket. Written as **requirements on the
producer**, not as a description of the consumer — the other developer must be able to satisfy
it without reading Utterance Intake's source. Contents: the `Utterance` construction contract
field by field with the sentinel rules stated as rules (`0.0` → `None`, absent → `None`, **never
a fabricated `1.0`**); the seven required changes above as numbered requirements; the three
streaming rules; the two documented Google caveats (a producer author who does not know
`latest_short`'s confidence is disclaimed will make the wrong tradeoffs); the deferred items with
their owners; and a verification section pointing at the captured corpus. It is a **contract
document, not a lockstep document** — it does not join CLAUDE.md's four. The rule that keeps it
true: **whoever changes `Utterance` updates this file in the same session.**

### The day-one degraded state

With the capture edge deferred, this layer ships **correct and starved**: the producer supplies
`alternates=()` and `word_confidences=()`, so `disagreement` and `min_word_confidence` are both
`None`, two of the three doubt signals are permanently absent, and the repair screen can fire
only on the float — today's behaviour exactly. The ticket opened by complaining that the
low-confidence path "is effectively untested on the input it exists for"; deferring the capture
edge reproduces that condition.

**It ships, but the degradation is made measurable — absent evidence must never be silently
equivalent to "no doubt".**

- A **startup capability assertion** logs, and the health endpoint reports, which of the three
  doubt signals the current producer actually supplies. "The repair screen never fires" becomes
  a visible configuration fact rather than a behaviour discovered in six months.
- Ticket 15 is handed an **expectation, not a test**: on the *current* producer, this layer's
  delta on the repair path is expected to be approximately **zero**, and that is written down
  as the predicted result. Otherwise a green run reads as evidence the feature works — precisely
  the trap the shipped "SAFETY recall 1.0" fell into.

### Tests

- **Hand-authored `Utterance` values for the contract tests.** Ticket 03 made Intake a pure
  function of `Utterance`, so the whole contract is reachable with no network, no credentials,
  no audio — and that property is worth defending.
- **Plus a one-time captured-STT-response corpus**, frozen as JSON and replayed forever after.
  It is the only way to get realistic numbers for the three cases ticket 03 demanded (a fluent
  high-confidence hallucination, a fluent low-confidence one, a divergent-alternates set);
  inventing them means every threshold in this ticket is calibrated against fiction.
- **No live STT or LLM call in the verification gate, regardless of budget.** A gate that costs
  money and varies run to run stops being run.
- It belongs in **ticket 14** as a distinct fixture family, not a new ticket.

### Rejected, recorded so it is not re-argued

- **A four-permission set, one per §9 consequence.** Three of the four are one ledger write
  behind one constant, and the fourth may never be gated. Four fields, two owners, and the
  first person to add a fifth consequence would have to guess.
- **Assessment grading the alternates to test verdict stability** (proposed and dropped, user,
  2026-08-26). It would have satisfied §9's pass condition using material ticket 02 already
  forces us to carry, at zero marginal cost — but the repair screen satisfies it *earlier* and
  more directly, by making the child the authority instead of the grader. Alternates stop at
  Intake's boundary, and one boundary is easier to assert than a licensing rule.
- **A fused doubt score.** Needs weights nobody can justify today, and is not monotone in the
  safe direction.
- **Shipping the disagreement gate disabled** until calibrated. It puts the whole verdict back
  on the float Google disclaims.
- **Amending `Utterance` for streaming** (an `is_final` field). Constrain the producer instead.
- **Collapsing `authorization` into `doubtful`.** They are a decision and a finding; and
  `DISCARDED` has no corresponding finding.
- **Letting the grammar supersede `math_grade.normalize` now.** A grading behaviour change on
  this effort's critical path for no gain this ticket needs. It gets its own ticket instead.
- **`MathParse.interpretation` as audit-only.** It would make this ticket's headline deliverable
  ornamental: §9's own worked example would parse correctly and still be graded wrong.

### Consequences handed to other tickets

- **07** — unchanged and reinforced: `SafetyReading` runs at every confidence, on every source,
  and the safety path **never reads `authorization` or `TranscriptReading`**. Ticket 14 asserts it.
- **09** — resolved 2026-08-27, and it **deleted** the `PrivacyReading` slot (detection is
  model-only, which Intake cannot host). 11 stays unaffected: no privacy reading means no
  deferral question for one, and the `authorization` states are untouched.
- **12** — unaffected. `contested_spans` and `AnaphorSpan` are independent evidence on the same
  observation; nothing here forecloses the three-band coreference policy.
- **13** — `RouteResult.uncertain`'s 7-site rename joins its disposition list. The dead
  `triage_turn(stt_uncertain=)` parameter is **not** deleted, but is fenced by a spec rule.
- **14** — inherits: the captured-STT corpus as a distinct fixture family; the six
  `LegibilityCue` values and three authorization states (ticket 03); the **invariant that for
  `source is VOICE`, `authorization is UNAUTHORIZED` iff `transcript.doubtful`**; an assertion
  that no consumer reads `utterance.alternates` (only `repair_choices`); an assertion that the
  safety path reads neither `authorization` nor `TranscriptReading`; the grammar's **two-sided**
  acceptance criterion (false negatives fixed **and** refusal rate under a ceiling); and the
  42-row homophone table from ticket 10.
- **15** — inherits four measurable deltas and **one predicted non-delta**: the
  `perception_degraded` rename; the deletion of both downstream float checks; the
  `AssessmentRequest` shape change; the grammar's effect on the four measured false negatives;
  and — stated as a *prediction*, not a passing test — **the repair path's delta on the current
  producer is expected to be ≈ zero** because two of three doubt signals are absent.
- **16** — the spec must reference `STT_CAPTURE_CONTRACT.md`, carry the per-consumer
  consequence rules (which this ticket states rather than encodes), and rewire the five
  remaining `interaction["text"]` readers.
- **New ticket (owner TBD)** — retire `math_grade.normalize` in favour of the grammar, closing
  ticket 10's finding B2 (Utterance Intake work living in a grading module). Knowingly deferred;
  the duplication runs for the duration.
- **CLAUDE.md** — three gotchas to add (premises 7, 8 and the v1 region fact), plus the retired
  `STT_WRITE_CONFIDENCE_MIN` name and the new `lark` dependency. The 4-doc lockstep propagation
  stays with whoever resolves the map's open "which of the four documents" item; this ticket
  does not adopt an obligation the map has deliberately left unowned.
- **`AssessmentRequest` gains `observation: UtteranceObservation`** — decided here because the
  authorization precondition, the `repair_choices` boundary and grading `interpretation` are all
  unimplementable without it. Assessment reads `observation.normalized_text`,
  `observation.authorization` and `observation.transcript`, never `turn_input`.

### Explicitly not decided here

The repair screen's display-element shape (response-side, per ticket 02); the six-route safety
taxonomy (07); the personal-data contract (09 -- no `PrivacyReading`; the slot is deleted); the
coreference bands and word-count threshold
(12); the concept phrase set's design and the `en-US` → `en-IN` migration (deferred, owners
named above); the streaming STT service itself (different developer,
`STT_CAPTURE_CONTRACT.md` is the interface); and the calibrated values of all three thresholds,
which are provisional by construction until the captured corpus exists.
