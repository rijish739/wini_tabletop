# Utterance Intake

Turns one raw **Utterance** into a screened, normalized, model-free
**Utterance Observation** of what was said. It **observes; it decides nothing.**

## The one public door

```python
UtteranceIntake(transcript_policy=...).observe(UtteranceIntakeRequest(turn_input))
    -> ModuleOutcome[UtteranceObservation]
```

There is **no** public `normalize(text) -> str`. Every consumer comes through the
typed door the tests exercise.

## The four rules

1. **It reports; it never decides.** It detects a safety trip but never routes
   one; it reads a confidence verdict but never holds the floor.
2. **It is total and write-free.** `value` is never `None`; `failures` and
   `state_changes` are always empty. If a bug raises, it propagates.
3. **It is pure of session.** The observation is a deterministic function of one
   `Utterance` and an injected transcript policy.
4. **Every judgment is welded to the trace that produced it** — nested readings,
   not flat fields beside loose cue strings.

## Contract

- Value types (`Utterance`, `UtteranceSource`, `UtteranceProvenance`,
  `WordConfidence`) live in `runtime/contracts.py` — they are the runtime's
  vocabulary, what a Turn begins with.
- Observation types (`UtteranceObservation`, `Authorization`, `SafetySignals`,
  the readings, `TranscriptReading` / `MathParse` / `Span`) live in
  `observation.py`. Booleans, enums, and spans only — **no scores, no cue
  matrix**. Invariants raise, never clamp.

## Walking-skeleton status (ticket 01)

Behaviour is deliberately trivial: `normalized_text` = NFC + zero-width strip +
whitespace collapse (NFKC absent by design); `authorization` from the injected
policy; the real LEXICON safety reading and the real illegibility *decision*
(both honest so `gate()` stays byte-identical); and honest-default problem,
reference, and maths-parse readings that later slices fill in. The grammar,
N-best disagreement, the six-way legibility cue split, problem cues, and anaphor
spans arrive in slices 02–07.

## Tests

`python -m unittest discover -s utterance_intake/tests -v` (run from
`cloud_run_service/`) — free, no credentials, no network, no audio.
