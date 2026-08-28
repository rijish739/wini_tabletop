# STT Capture Contract — Producer Handoff

**Status: normative**
**Date: 2026-08-28**
**Authoritative area:** requirements on the STT producer (the streaming transcription service
and its capture-edge adapter) derived from the frozen `Utterance` shape.

**Standing rule:** whoever changes `Utterance` (`cloud_run_service/runtime/contracts.py`)
updates this file **in the same session**. This document is a contract, not a lockstep snapshot;
it does not propagate numbers from other sources, and those sources do not propagate from it.

---

## What this document is, and who it is for

The Utterance Intake layer (`cloud_run_service/utterance_intake/`) is a pure function of
`Utterance`. It makes no STT calls; it never sees the audio; it trusts whatever the producer
delivers. **This file is the complete specification of what the producer must deliver.**

The intended reader is the developer rebuilding the STT service as a streaming Cloud Run
endpoint. You must be able to satisfy this contract **without reading** `utterance_intake/`
source. Everything Intake needs from you is stated here; everything it does with what you
provide is Intake's concern, not yours.

---

## §1 The `Utterance` shape — field-by-field construction contract

```python
# cloud_run_service/runtime/contracts.py

class UtteranceSource(str, Enum):
    VOICE            = "VOICE"
    TYPED            = "TYPED"
    REPAIR_SELECTION = "REPAIR_SELECTION"
    REPAIR_DISCARD   = "REPAIR_DISCARD"

@dataclass(frozen=True)
class WordConfidence:
    word: str
    confidence: float | None = None   # None = not reported; NEVER 0.0 (see §2 R4)
    start_ms: int | None = None
    end_ms: int | None = None

@dataclass(frozen=True)
class UtteranceProvenance:
    utterance_id: str      # required; non-empty
    captured_at: str       # ISO-8601 UTC
    duration_ms: int | None = None
    recognizer: str | None = None   # e.g. "cloud_stt_v1/en-US/latest_short"; None for TYPED
    repairs: str | None = None      # utterance_id this repairs; required for REPAIR_*
    selected_alternate_index: int | None = None  # required for REPAIR_SELECTION

@dataclass(frozen=True)
class Utterance:
    text: str                                    # raw transcript; never normalized
    source: UtteranceSource
    provenance: UtteranceProvenance
    confidence: float | None = None             # None = not reported; NEVER fabricated 1.0
    alternates: tuple[str, ...] = ()            # recognizer rank order; index 0 == text
    word_confidences: tuple[WordConfidence, ...] = ()
```

**Invariants enforced by the dataclass** (violations raise on construction):

| Invariant | What it means for the producer |
|---|---|
| `confidence` ∈ [0.0, 1.0] or `None` | Never pass a value outside this range |
| `word_confidences` only when `source is VOICE` | TYPED, REPAIR_SELECTION, REPAIR_DISCARD carry no word evidence |
| `REPAIR_SELECTION` requires `provenance.repairs` and `provenance.selected_alternate_index` | Set both on any utterance that fixes a prior one |
| `REPAIR_DISCARD` requires `provenance.repairs` and carries `text=""` and no `selected_alternate_index` | Empty text is the only valid discard payload |

---

## §2 Required changes — numbered for traceability

The following seven changes are **required** of the producer. They are changes to existing code
(primarily `wini_server.py` and `cloud_run_service/voice/cloud_stt.py`), but they are specified
here as behavioral requirements, not as code edits, because the streaming rebuild will replace
that code.

**R1 — `max_alternatives=5` (unconditional, request-time)**

Set `max_alternatives=5` in every `RecognitionConfig` (batch) and every
`StreamingRecognitionConfig` (streaming). This is unconditional: do not gate it on a flag.
Intake uses the alternates to compute the disagreement signal (`TranscriptReading.disagreement`)
and to populate the repair screen (`TranscriptReading.repair_choices`, capped at three distinct
values). Confidence stays top-alternative-only regardless of `max_alternatives`; raising it
populates no new scores, but it does supply Intake with rivals to compare.

**R2 — `enable_word_confidence`**

Set `enable_word_confidence=True` in every `RecognitionConfig`. The v1 STT language table
confirms this is supported for the `en-IN` + `latest_short` combination. Intake uses per-word
evidence to compute `TranscriptReading.min_word_confidence` and `TranscriptReading.contested_spans`
— both are permanently `None` and empty while this flag is off.

> **Caveat:** `WordInfo.confidence` is still labeled **Preview** (pre-GA) in Google's
> documentation. Word confidence is a pre-GA signal on a production safety path. This risk is
> recorded; do not rediscover it.

**R3 — `enable_word_time_offsets`**

Set `enable_word_time_offsets=True` in every `RecognitionConfig`. Populate
`WordConfidence.start_ms` and `WordConfidence.end_ms` from `WordInfo.start_time` and
`WordInfo.end_time`. These fields are `int | None`; convert to milliseconds.

**R4 — Map `0.0` → `None` on word confidence (sentinel rule)**

Google documents `WordInfo.confidence = 0.0` as a **sentinel meaning "was not set"**, using
the same "not guaranteed to be accurate … should not rely on it to be always provided" wording
as the utterance-level field. A raw `0.0` passed through to `WordConfidence.confidence` defeats
`Utterance`'s "absence is never a number" invariant at the layer immediately below where it was
written.

**Rule:** if `WordInfo.confidence == 0.0`, set `WordConfidence.confidence = None`.
Any other value in [0.0, 1.0] passes through as a `float`.

The same sentinel rule applies to the utterance-level `alternatives[0].confidence`: if the
field is absent or is `0.0`, set `Utterance.confidence = None`.

**R5 — Mint `UtteranceProvenance` on every turn**

The production path at `wini_server.py:607-614` currently returns `TranscriptionEvidence`
(transcript + float). The streaming rebuild replaces this with a full `Utterance`, which
requires a `UtteranceProvenance`. The producer must generate:

- `utterance_id`: a stable, unique identifier for this specific transcription event (e.g.
  `f"stt_{uuid4().hex}"`). It is used as Intake's memo key and as the trace ID in the evidence
  ledger.
- `captured_at`: ISO-8601 UTC timestamp of when the audio segment ended (or was recognized).
- `duration_ms`: the recognizer's segment duration in milliseconds, from the final result's
  `end_time` if available.
- `recognizer`: a human-readable string identifying the model + language, e.g.
  `"cloud_stt_v1/en-US/latest_short"`. Allows offline triage of transcription quality.

**R6 — Delete the `stt_confidence = 1.0` fabrication**

`wini_server.py:613-614` fabricates `stt_confidence = 1.0` on any STT adapter that lacks
`recognize_pcm_evidence`. This value flows into `trusted_observations["stt_confidence"]` and
from there into `InteractionControl`'s floor check. A fabricated `1.0` bypasses the floor check
on every text-mode and adapter-mode turn.

**Rule:** the streaming rebuild must never set `Utterance.confidence = 1.0` unless that value
was actually returned by the recognizer. When the recognizer does not report a confidence,
set `confidence = None`. "No evidence" and "perfect confidence" are different facts.

**R7 — Remove the empty-transcript early return**

`wini_server.py:616-620` returns early — "nothing recognized, don't burn a turn" — when the
transcript is empty. This intercepts two legitimate `Utterance` values:

1. `REPAIR_DISCARD`: an utterance with `text=""` that ticket 02 introduced specifically so a
   learner's rejection of every repair hypothesis reaches the evidence ledger.
2. Any turn where the recognizer produced no speech — a cue that belongs in Intake, not in the
   server loop.

**Rule:** the producer must forward every final result, including final results with empty
transcripts, as an `Utterance` to Intake. The early-return guard is removed in the streaming
rebuild. The server loop may still suppress turns on a **no audio at all** condition (no bytes
received, hardware silence) — this is different from a zero-length transcript.

---

## §3 Streaming rules

These three rules apply to any streaming STT implementation. They follow from Google's
documentation: confidence is set "only for the top alternative of a non-streaming result **or,
of a streaming result where `isFinal=true`**."

1. **One `Utterance` per final result, never from an interim result.** A streaming recognizer
   revises its hypothesis continuously; a turn started on text later retracted is a state write
   against something the learner never said.

2. **The utterance boundary is the recognizer's endpointing.** `UtteranceProvenance.duration_ms`
   and `captured_at` come from the final result's segmentation, not from device-side silence
   detection. The device's silence timeout (if any) is a fallback for stream termination, not
   the canonical boundary.

3. **Intake never runs on a non-final result.** Forward interim results to any speculative UI
   hooks you build, but do not construct an `Utterance` from them and do not call Intake.

**No `is_final` field is added to `Utterance`.** A non-final result must never become an
`Utterance`. Adding an `is_final` field invites a future path that constructs one and branches
on it — the same reasoning ticket 02 used to reject deprecated mirrors. An unrepresentable state
cannot be mishandled.

---

## §4 Documented Google caveats

Both caveats apply to the recognizer in production today (`latest_short`). A producer author
who does not know them will make the wrong tradeoffs.

**C1 — `latest_short` confidence is disclaimed by Google**

Google's latest-models page lists, among features the latest models do *not* support:
*"Confidence scores—The API will return a value, but it is not truly a confidence score."*
This applies to `latest_short`, the model in production. The utterance-level `confidence`
field is therefore an uncalibrated heuristic, not a probability. Intake's thresholds are marked
provisional and are calibrated against a captured corpus (ticket 14), not against an assumption
that the number means what its name says.

Do not represent `latest_short`'s confidence to any consumer as a true probability. Intake does
not; neither should you.

**C2 — Word confidence is Preview (pre-GA)**

`WordInfo.confidence` is labeled Preview in Google's documentation. It is used by Intake on
the per-word doubt path (R3) and carries pre-GA terms. This means the API surface may change;
validate the field's availability against the language + model combination you deploy before
relying on it. The `en-IN` + `latest_short` combination was verified to support
`enable_word_confidence` as of 2026-08-26.

---

## §5 Facts about STT regions

These facts constrain deployment decisions. Record them; do not rediscover them.

**F1 — STT v1 has no `asia-south1` endpoint**

Cloud Speech-to-Text v1 offers only US and EU regional endpoints. There is no `asia-south1`
region for v1. **STT and Vertex AI are not co-located.** Never assume they are when estimating
latency or designing network topology.

**F2 — STT v2's `asia-south1` availability is UNVERIFIED**

Cloud Speech-to-Text v2 lists `asia-south1` as a location in its documentation, but the
per-model availability matrix for that region has not been verified as of this document's date.
If the streaming rebuild moves to v2, check the Locations API for the `asia-south1` + model
combination before committing to it.

---

## §6 Deferred items — with owners

These items are deferred from this effort. They have owners. They are recorded here, not in a
backlog, because a future producer change that forgets them will silently degrade the system.

**D1 — Concept-scoped phrase set**

Ticket 11 §3 (issue doc) decided: the per-turn concept-scoped phrase set is built at the
**capture edge** (which holds the session and therefore the active concept), not in Utterance
Intake. This satisfies §9's "active concept scopes the recognizer" requirement without breaking
Intake's session-purity invariant (ticket 03 rule 3).

The implementation requires: a concept card's vocabulary is fetched at turn start; an
`inlinePhraseSet` (v2 API) or a boosted `SpeechContext` (v1 API) is constructed from it and
included in the per-turn `RecognitionConfig`. A v1 vs. v2 API decision is required before this
can be implemented.

**Owner:** STT producer developer. **Blocked by:** v1-vs-v2 API decision; concept card
vocabulary access from the capture edge.

**D2 — `en-US` → `en-IN` migration**

The production recognizer runs `en-US`. Ticket 11 noted this as a genuine accuracy question
that changes every transcript in the system and deserves its own measurement. It is deferred
with the understanding that any migration requires a controlled experiment on a representative
corpus, not a flag flip.

**Owner:** STT producer developer + evaluation lead. **Not blocking** this effort.

---

## §7 Verification

The captured-STT-response corpus (ticket 14 fixture family) is the instrument for calibrating
the three doubt thresholds in `TranscriptReading`:

| Signal | Threshold | Status |
|---|---|---|
| `Utterance.confidence` | 0.60 (retained from prior implementation) | **provisional** — calibrate against captured corpus |
| `WordConfidence.confidence` minimum | ~0.40 | **provisional** — calibrate against captured corpus |
| Alternate disagreement | conservative (>½ aligned positions differ, top-3 distinct) | **provisional** — loosen only with evidence |

The corpus must include at minimum:
- One fluent, high-confidence hallucination (recognizer is confident; the word is wrong)
- One fluent, low-confidence transcription
- One set of divergent alternates

These three cases cannot be synthesized — they must be captured from real STT responses.

**No live STT call in the verification gate**, regardless of budget. A gate that costs money
and varies run to run stops being run.

---

## §8 What Intake does with what you provide — informational only

This section exists so the producer understands how their output is consumed. It imposes no
additional requirements; §§1–7 are the complete contract.

- `Utterance.confidence` and `WordConfidence.confidence` feed `TranscriptReading.doubtful`
  (the verdict), `TranscriptReading.causes`, and `TranscriptReading.min_word_confidence`. The
  verdict is `Authorization.UNAUTHORIZED`, which triggers the repair screen.
- `Utterance.alternates` feeds `TranscriptReading.repair_choices` (top-3 distinct, deduplicated)
  and `TranscriptReading.disagreement`. The alternates themselves **do not leave Intake**; no
  downstream layer reads `utterance.alternates` directly.
- `WordConfidence.start_ms` / `end_ms` feed `TranscriptReading.contested_spans` — the positions
  where alternates disagree, used by the response layer to highlight the contested word.
- `UtteranceProvenance.utterance_id` is Intake's memo key for the per-turn Gemini perception
  call (ticket 02) and the trace ID in the evidence ledger.

---

## §9 What this document does not decide

- The repair screen's display-element shape: response-side (ticket 02).
- The doubt thresholds' calibrated values: ticket 14's captured corpus is the instrument.
- The maths grammar's scope and v1 grammar version: ticket 11 (resolved); the grammar lives in
  `utterance_intake/grammar/`, not on the capture edge.
- The streaming STT service's internal architecture, cloud topology, or latency targets beyond
  the hard constraint that one final `Utterance` per endpointed segment reaches Intake.
- Safety routing, personal-data detection: both run independently of `Utterance.confidence` and
  `Authorization`. The safety path **never reads** `authorization` or `TranscriptReading`.
