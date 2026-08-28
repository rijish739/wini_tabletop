# Decide the input value type

Status: resolved
Type: grilling
Blocked by: 01

## Question

What does the Input Layer accept — a `str`, or a richer value carrying transcription
uncertainty?

Today every entry point takes a bare string. `stt_confidence` travels separately, as one
float on `TurnInput.trusted_observations`, read at `interaction_control/control.py:248-252`
and defaulted to `1.0` when absent. There is no N-best, no per-word confidence, and no
provenance link back to the audio.

Docx §9 requires the opposite: "Carry confidence and, where feasible, N-best hypotheses
through intent, concept and grading. Never overwrite the original audio/transcript
provenance." Its pass condition is "a low-confidence word that changes an answer produces a
clarification, not a score."

Decisions to close:

- Does the layer accept a `Transcript` value (text + confidence + optional N-best +
  provenance), and does a typed-text turn synthesize a trivial one (confidence 1.0, single
  hypothesis)?
- Do the alternates survive into the output observation, or are they collapsed at the
  boundary?
- Is confidence per-utterance, per-word, or both? Cloud STT gives both; the current gate
  only reads an utterance-level number.
- What happens to the two existing normalizer callers
  (`cognitive_analyzer/analyzer.py:229`, `perception/gemini_perception.py:151`) — do they
  take the new type, or does a string overload stay?
- CLAUDE.md gotcha: the Gemini call is memoized by *normalized* text and
  `normalize_input` must stay idempotent. A richer input type must not break that memo key.

This blocks the output contract (03) and the STT contract (11).

---

## Resolution (2026-08-26, /grilling)

**The layer accepts a typed value, not a `str`.** `Utterance` becomes a frozen dataclass
carrying the text *and* the transcription evidence that produced it. No second noun is
introduced: `Transcript` was rejected because the glossary already owns this concept
(`CONTEXT.md:19`) and because "transcript" is wrong for every non-voice source. The glossary
entry is amended from "the raw learner **text**" to "the raw learner **input** ... with the
transcription evidence that produced it".

The organizing rule behind every decision below: **evidence travels welded to the text it
describes, and absence is never a number.** Today the utterance arrives on two independent
channels (`interaction["text"]` + `trusted_observations["stt_confidence"]`), which is why
three modules each re-default the same missing float differently — `0.0` at
`voice/cloud_stt.py:71`, `1.0` at `interaction_control/control.py:249`, `1.0` again on the
STT-failure path at `wini_server.py:611-614`, and `None`-means-no-gate at
`evidence/ledger.py:197`.

### The type

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

| Field | Decision | Why |
|---|---|---|
| `text` | **raw only**; no normalized copy | Normalization exists in exactly one place — Utterance Intake's output observation (ticket 03). Two normalized copies in two types is how they drift, and docx S9's "never overwrite the original transcript provenance" becomes structural instead of intentional. |
| `confidence` | `float \| None`, **`None` = not reported** | `None` is not comparable to a floor, so every consumer must state what unknown means to *it*. This is what `evidence/ledger.py:197` already does correctly and `control.py:249` does not. TYPED carries `None`, never a fabricated `1.0`. |
| `alternates` | `tuple[str, ...]`, plain strings | Ticket 10: confidence exists **only** on `alternatives[0]`, so a per-hypothesis score field would be permanently `None` — a lie in the type. Rank is sequence order; that is all the API gives. |
| `word_confidences` | word + confidence + **time** offsets, **no character offsets** | This is what `WordInfo` actually returns. Character offsets would index raw text while consumers read normalized text, and ticket 10 proved normalization rewrites characters (NFKC destroys `x²`, folds `½`). Carrying an alignment map across a rewriting step is how provenance quietly becomes false. Locating a word inside normalized text is a downstream alignment problem and should be visibly one. |
| `provenance` | opaque handle: id, timestamp, duration, recognizer, `repairs`, `selected_alternate_index`. **Never bytes.** | No audio store exists and retention is out of scope. `utterance_id` is deliberately **not** `turn_id`: a repair is a new Turn, and the link between the two is the point. |

Empty sequences mean **"not reported"**, never "none exist".

### Source semantics

Production is **voice-only** (no keyboard on the device). `TYPED` is an engineering test
shortcut — `interactive_tester.py`, the eval scripts, `POST /turn {"text": ...}`
(`wini_server.py:886`).

- **Exactly one** branch on `source` is permitted anywhere in the runtime: the trust policy
  (`TYPED` -> confidence `None` -> trusted, no repair flow), owned by ticket 11 and written as
  one line. No pedagogy, grading, or safety path may read `source`. Ticket 14 carries an
  assertion to that effect.
- `REPAIR_SELECTION` exists because the text came from **our own N-best**, not from the
  learner's mouth. This ticket forbids any consumer substituting an alternate for the primary
  (see below); this is the one case where the substitution is legitimate *because the learner
  authorized it*, and a distinct source keeps that authorization auditable instead of
  laundering a machine hypothesis into `TYPED`.
- `REPAIR_DISCARD` (the child taps "none of these") is an `Utterance` with empty `text`, not a
  UI event. A discard is the most valuable signal we can collect about the recognizer — *every
  hypothesis we produced was wrong* — and as a UI-only control signal it would evaporate
  before any ledger saw it.

### Invariants (`__post_init__`)

- `confidence` **raises** if outside `[0, 1]`, following `TurnBudgets.__post_init__`
  (`runtime/contracts.py:55-61`). The clamp stays at the adapter (`cloud_stt.py:74`), where it
  belongs. A silent clamp inside the value type is exactly how a bug becomes a confident
  number again.
- **Empty `text` is allowed.** "Heard nothing" is a real runtime state (`cloud_stt.py:48`
  returns `TranscriptionEvidence("", 0.0)`) that the safety/nonsense route must handle as a
  *decision*; a constructor that crashes on it moves the failure somewhere with less context.
- `REPAIR_SELECTION` -> `provenance.repairs` and `selected_alternate_index` both present.
- `REPAIR_DISCARD` -> `provenance.repairs` present, `text` empty, `selected_alternate_index`
  `None`.
- non-empty `word_confidences` -> `source is VOICE`.
- Sequences are `deep_freeze`d per the existing convention.
- Duplicate hypotheses in `alternates` are **allowed** — Google legitimately returns
  near-duplicates, and rejecting a valid API response is worse than carrying a redundant one.
  Dedupe happens at display time.

### Placement and the `TurnInput` shape change

`Utterance`, `UtteranceSource`, `UtteranceProvenance` and `WordConfidence` live in
**`runtime/contracts.py`**, beside `TurnInput` and `DeviceCapabilities`. They are the
runtime's *vocabulary* — what a Turn begins with. Utterance Intake **consumes** `Utterance`
and owns the *observation* it produces (ticket 03); defining the input type inside the Feature
Module would invert the dependency and put `runtime` in violation of the
no-cross-module-implementation-imports rule for the sake of a filename.

`TurnInput` **gains `utterance: Utterance`**, and both legacy channels are **deleted**:

- `interaction["text"]` — gone. `interaction` keeps `answer_budget` and `allow_topic_shift`.
- `trusted_observations["stt_confidence"]` — gone.

Rejected: assembling the `Utterance` inside Intake from the two existing channels.
`deep_freeze` would have carried a frozen dataclass through `trusted_observations` intact
(`runtime/contracts.py:17-25`), so this was a design choice and not a technical constraint —
but it keeps the defect alive: any constructor could still supply text with no evidence, and
the `1.0` fabrication would simply relocate inside Intake. Also rejected: deprecated mirrors,
which guarantee both paths live forever and give ticket 15's gate two shapes to verify.

Blast radius: **one** production construction site (`runtime/compatibility.py:79-96`); the
rest are `interactive_tester.py:190`, `eval/p0_latency.py:46,57`, `test_phase1_client.py:187`
and module tests that ticket 14 rewrites anyway. Consumers that change from a `.get()` to a
typed read: `interaction_control/control.py:248-255` and
`assessment_evidence/interface.py:90-102` — the two places ticket 11's per-consequence gates
will hang.

### Interface: typed door only

Utterance Intake exposes **only** its typed Feature Module interface. There is **no** public
`normalize(text: str) -> str`. The two offline callers (`eval/behavioral_eval.py:229`,
`eval/perception_eval.py:406`) construct `Utterance(text=..., source=TYPED, ...)`.

Consequence, recorded not re-argued: **CLAUDE.md's memo gotcha must be rewritten.** It is
currently phrased as a property of `normalize_input` ("the Gemini call is memoized by
*normalized* text and `normalize_input` must stay idempotent"); that function no longer exists
as a public door, and the memo key changes below.

### Cache identity

**The perception memo keys on `provenance.utterance_id`, not on normalized text.**

`_perceive` currently keys its LRU on normalized text alone
(`perception/gemini_perception.py:163-165`) while the prompt it caches is built from **session
state** — `current_concept`, `last_tutor_action`, `pending_check.question`
(`gemini_perception.py:263-272`). A repeated short utterance ("yes", "what?", "i don't know")
therefore takes a cross-turn cache hit carrying a perception computed under a *different*
session. That bug predates this effort; a value type that also carries confidence into the
call would have made it worse.

Keying on utterance identity preserves the memo's actual purpose — one Gemini round-trip
shared by `route`/`classify`/`resolve`/`score_matrix` **inside** a turn — and ends cross-turn
reuse, which was never its job and is currently unsound. It also dissolves the idempotency
constraint entirely: correctness stops depending on normalization being a perfect fixed point,
which is what makes ticket 11's *refusing* maths grammar expressible at all. Ticket 15 must
**measure** the Gemini call-count delta rather than assume it is zero.

### Capture-edge changes

- Provenance is minted **at the capture edge** (`wini_server.py`, the only place that ever
  sees audio); `runtime/compatibility.py` mints it for TYPED with `recognizer=None`. Intake
  must never invent provenance for something it did not witness.
- **`max_alternatives=5`** on the `RecognitionConfig` (`cloud_stt.py:55-62`, currently unset).
  Alternates must be requested **unconditionally** even though they are only *shown* on low
  confidence: `max_alternatives` is request-time, there is no audio store to re-run against,
  and you cannot retroactively ask for hypotheses after seeing a bad score. No extra billing,
  no meaningful latency.
- `enable_word_confidence` stays **ticket 11's** call — it depends on that ticket verifying
  `WordInfo.confidence` on `latest_short`/`en-IN` (ticket 10 open item #5).

### The repair contract (cardinality only)

- Repair choices are shown **only below the confidence floor**, never routinely. Routine
  confirmation is annoying and trains the child to tap through it.
- Carry all 5 hypotheses; display **top 3 distinct after dedupe + a discard button = 4 touch
  targets**, one screen, **no pagination**. E-ink repaints a full screen per page, and the
  options are also *read aloud* on a voice-first device — three short near-identical sentences
  is tolerable, five is not. That readback ceiling, not screen space, sets the number.
- The **primary is a button like any other**, index 0. Tapping it produces `REPAIR_SELECTION`
  with `selected_alternate_index=0` — a marginal transcript becomes *learner-authorized*
  rather than either discarded or silently trusted. This collapses the edge cases into one
  screen instead of three: with one surviving hypothesis the same screen degrades to "Did you
  say X?" [that's right] [no, let me say it again], which is exactly docx S9's required yes/no
  fallback, reached by cardinality rather than by a branch.
- **The learner always chooses.** Nothing in the system may auto-select an alternate, and the
  repair screen is the only place an alternate becomes text.

### The rule that travels with the alternates

**Alternates are evidence, not text.** They survive into Intake's output observation
(ticket 03), but:

- no consumer may substitute an alternate for the primary;
- nothing re-runs Perception or grading on an alternate (one Gemini call per turn is a budget,
  not a habit);
- they may only be *offered* to the learner as repair choices, or *consulted* as disagreement
  evidence by whoever ticket 11 authorizes.

A separate channel for alternates (parallel to isolating the safety verdict) was rejected: the
argument for isolating safety is that a trip must never be *lost*, whereas alternates being
ignored is harmless.

### Consequences handed to other tickets

- **Ticket 03** — the observation carries the primary text, the normalized text, the confidence
  and the alternates forward (Perception reads text *and* confidence). The field list and the
  safety-channel question remain 03's.
- **Ticket 11** — inherits: the `TYPED` trust line; a confidence floor that now has a
  calibration path (`selected_alternate_index` plus the discard rate give the full outcome
  distribution of every repair shown); `enable_word_confidence`; the maths grammar, which
  **cannot** live inside normalization because a refusal is not a `str`; and the
  disambiguation of `RouteResult.uncertain` (perception degraded) from transcript doubt.
- **Ticket 12** — coreference evidence rides the same observation; nothing here forecloses it.
- **Ticket 14** — corpora must cover: absent confidence (`None`) vs. low confidence vs. TYPED;
  empty transcript; the `source`-branch assertion; and the repair-screen degradation at
  cardinality 1.
- **Ticket 15** — gate additions: the `TurnInput` shape change has exactly one production
  construction site, and the Gemini call-count delta from the memo-key change must be measured,
  not assumed.
- **CLAUDE.md** — the memoization gotcha is rewritten (utterance-id key, no public
  `normalize_input`).
- **Response layer (out of scope, flagged)** — the repair screen needs a **new display element
  type**. Today `display[]` is metadata-only, `{image_path, alt_text}` stable image IDs
  (`wini_server.py:47`, `wini_client/README.md:90`); there is no text-choice element. Its shape
  is response-side; only its cardinality is decided here.

### Explicitly not decided here

Threshold values and the per-consequence gates, the grammar's refusal outcome (11); the
observation's field list (03); the display element's shape (response-side); audio retention
(out of scope, not code).
