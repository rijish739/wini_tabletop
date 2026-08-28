# 01 — Frozen contract + walking skeleton + CI (the tracer bullet)

**What to build:** The thinnest possible complete turn — a plain typed `"5"` goes `Utterance` →
`UtteranceIntake.observe()` → `TurnPhase.UTTERANCE_INTAKE` → `gate()` → one real consumer → a green
free-lane CI run — with the **entire observation contract frozen** and backed by a shared golden-fixture
conformance suite. This slice proves every seam connects and makes the contract the one thing everything
else builds against. Its behavior is deliberately trivial (normalize + authorize + honest default
readings); every later slice fills in one reading against this frozen shape.

**Blocked by:** None — can start immediately. (First commit is the docs truth pass, below, for context
hygiene.)

**Status:** ready-for-agent

**This slice is what makes the other slices safe. It must deliver all three enablers:**

- [ ] **Contract frozen (anti-mismatch).** All value + observation types land as final shapes:
  `Utterance`/`UtteranceSource`/`UtteranceProvenance`/`WordConfidence` in `runtime/contracts.py`;
  `UtteranceObservation` + `Authorization` + `SafetySignals` + `Legibility/Problem/Reference` readings +
  `TranscriptReading`/`MathParse`/`ParseOutcome`/`DoubtCause`/`Span` with their construction invariants
  (raise-not-clamp; five required non-defaulted readings; `span is None` iff `PASSTHROUGH`;
  `interpretation` iff `ACCEPT`; `source=LEXICON` on `SafetySignals`; no float fields except on the
  embedded `Utterance`). No `privacy` slot; no `cue_matrix` field.
- [ ] **Shared golden fixtures + conformance harness (anti-mismatch).** A `(Utterance → expected
  UtteranceObservation)` JSONL fixture file plus a conformance test that any `observe()` implementation
  must pass **and** that any consumer imports to build stub observations from hand values. Later slices
  add rows; nobody hand-rolls an observation shape.
- [ ] **Composition helper frozen from day one (anti-mismatch).** The shared safety-verdict composition
  entry point in `interaction_control` exists now — its body is the lexicon reading ∪ perception's bit —
  and the legacy-20 regression test calls it. Slice 12 changes the body to add the model verdict; **the
  test file is never edited at cutover.**
- [ ] **Minimal real `observe()`.** One public door
  `UtteranceIntake.observe(UtteranceIntakeRequest) -> ModuleOutcome[UtteranceObservation]`; NFC +
  zero-width strip + whitespace collapse (NFKC absent from day one); `authorization` from an injected
  transcript policy; all other readings return their honest defaults (`LEGIBLE`, not-a-problem, no
  anaphors, `PASSTHROUGH`). Total, write-free, session-pure.
- [ ] **Walking skeleton wired (anti-late-verification).** `TurnPhase.UTTERANCE_INTAKE` inserted before
  `PERCEPTION_AND_PRIOR_GRADING`, `_validate_phase_trace` green; `TurnInput.utterance` added;
  `runtime/compatibility.py` mints TYPED provenance; `gate()` reads the observation (pure translation,
  trivial path); **one** consumer proven end-to-end (perception reads `observation.normalized_text`).
  Legacy `interaction["text"]` / `stt_confidence` still present and read by everyone else.
- [ ] **CI `offline` job green from day one (anti-late-verification).** One GitHub Actions job runs
  `unittest discover` across `cloud_run_service/*/tests`, the conformance suite, the corpus-integrity
  validator shell, and the empty-but-live expected-diff manifest mechanism. The "what a green run does
  not mean" statement sits at the **top** of the verification doc, stop-ship sentence verbatim.
- [ ] **Docs truth pass (first commit).** Correct the false/stale `CLAUDE.md` gotchas and delete the
  `SAFETY recall 1.0` figure at all seven retraction-manifest sites (prose→pointer, tables/code→removed);
  `cues.py` frozen header; `gates.py` docstring notice; open the `rag_memory.md` work-log entry.
- [ ] **Turn-level property #1:** a terse real answer (`5`, `x=3`, `no`, `½`) survives the full
  Intake→`gate()` path (Tier-A byte-identical, in the skeleton's CI).
