# Research: math-aware STT normalization with an auditable parse

Status: resolved
Type: research
Blocked by: —

## Question

Docx §9 requires: "Normalise spoken forms only through a **constrained maths grammar** and
the active concept. Keep an **auditable parse**, e.g. 'three squared' → 3^2." Its pass
condition: "The parser **refuses** an ambiguous or out-of-grammar rewrite."

Today `InputProcessor.normalize_input` (`input_processor.py:359-399`) does none of this. It
is pure surface cleanup — NFKC, zero-width strip, whitespace collapse, spacing around
punctuation — and its own docstring is explicit that it must not rewrite meaning. There is no
maths grammar anywhere in the input path. (`mathtext.py` exists at the service root; check
whether it is a rendering utility or a parser before assuming either.)

§9 names the failure cases directly: "'root two' and 'route two', 'factor' and 'fraction',
'x squared' and 'x cube', minus signs, and local-language pronunciation can produce materially
different meanings."

Research targets:

- Spoken-mathematics grammars and speech-to-LaTeX/MathML work: what constrained grammars
  exist, what coverage they claim, how they signal a refusal rather than a guess.
- How Cloud STT surfaces alternates and per-word confidence, and whether phrase hints /
  adaptation can be scoped to an active concept's vocabulary (§9's "and the active concept").
- Homophone handling in numerically-dense ASR; published error rates for maths dictation.
- Indian-English and code-switched maths speech — the deployment context (docx §8 explicitly
  names "ulta U" and local-language equivalents as valid input, not nonsense).
- What "auditable parse" means in practice: what artifact must be retained so a human can see
  why "three squared" became `3^2`.

Deliverable: a Markdown findings file covering (a) viable constrained-grammar approaches with
their refusal semantics, (b) what Cloud STT can supply that the current single-float
confidence discards, (c) the homophone cases that must be in the golden corpus for ticket 14.

Do **not** decide the contract here — ticket 11 owns that. Check `mathtext.py` and
`math_grade.py` in `cloud_run_service/` for anything reusable before recommending new work.

---

## Findings (2026-08-26, /research)

Findings file: `docs/architecture/MATH_AWARE_STT_NORMALIZATION_RESEARCH.md` (804 lines).
Placed beside `INPUT_LAYER_SEMANTIC_INTENT_RESEARCH.md`, matching its structure and citation
style — it outlives the ticket, so it does not belong in `.scratch/`.

Every code claim below was re-verified directly against the code, not taken from the research
agent. Two of its numbers were wrong and are corrected here: `MATHS_PHRASES` holds **30**
entries, not 27; and `½` grades **`None`**, not `wrong` — it defers, because `_values` finds
no parseable digit at all.

**Scope note.** Problems are listed for **Utterance Intake only**, per ticket 01's manifest.
Deliberately excluded as another capability's: `grade()`'s three-valued return semantics and
its deferral to the LLM rubric grader are **Assessment and Evidence** (`math_grade.py:9-12`);
safety-reply and helpline surfaces are response-side. `math_grade.normalize` appears below
**only** because it is de-facto Utterance Intake work sitting in the wrong module (B2).

### Two ticket premises are wrong

1. The ticket states `normalize_input` must not rewrite meaning, and its docstring agrees
   (`input_processor.py:370-388`: *"We do NOT rewrite student meaning"*). **It does.** See A1-A3.
2. The ticket asks whether `mathtext.py` is a renderer or a parser, and states there is "no
   maths grammar anywhere in the input path". `mathtext.py` is a **renderer** — maths→text,
   pure regex chains; `fold_superscripts` turns `x^2` into "x squared", the exact inverse of
   §9. But a spoken-maths grammar **does** exist: `math_grade.normalize`. It is in the wrong
   module, and it cannot refuse.

### A. `normalize_input` changes meaning (the layer's own function)

| # | Problem | Evidence |
|---|---|---|
| A1 | NFKC destroys exponents: `x²` → `x2`. `3x² + 5x` becomes `3x2 + 5x`. | measured; `input_processor.py:394` |
| A2 | NFKC rewrites `½` → `1⁄2` using U+2044 FRACTION SLASH, **not** ASCII `/`. No downstream `[0-9]+/[0-9]+` pattern matches it. | measured |
| A3 | NFKC leaves U+2212 MINUS SIGN unchanged. Every downstream `-?[0-9]+` uses an ASCII hyphen, so the sign is silently dropped. | measured |
| A4 | The test that should catch A1 asserts **around** it. `test_normalization_preserves_math_equations_and_unicode` says "preserves", comments *"# NFKC normalizes superscript 2"*, then asserts only `"3x" in norm`. | `cognitive_input_processor/tests/test_input_processor.py:23-29` |

A1-A3 share one root cause: NFKC is applied as if it were a safe surface operation. It is not
— it is a compatibility fold, and maths notation is exactly where compatibility folds lose data.

### B. No constrained maths grammar in the input path

| # | Problem | Evidence |
|---|---|---|
| B1 | `normalize_input` is surface-only (NFKC, zero-width, whitespace, punctuation spacing). No spoken-maths handling of any kind. | `input_processor.py:369-399` |
| B2 | **Boundary defect.** The repo's real spoken-maths normaliser is `math_grade.normalize`, inside Assessment and Evidence. Utterance Intake work living in a grading module. | `math_grade.py:40-65` |
| B3 | `math_grade.normalize` is an ordered chain of `re.sub` calls producing a **string**. No tree, no derivation, no record of which rule fired. §9's auditable parse **cannot** be met by extending it. | `math_grade.py:46-65` |
| B4 | The grammar is unconstrained by domain or active concept: `"the root cause"` → `"the sqrt cause"`. | measured; `math_grade.py:50` |
| B5 | Ambiguity is resolved silently by rule order. `"one over x plus two"` → `1/x plus 2`, one of three readings, with no signal that a choice was made. | measured; `math_grade.py:52` |
| B6 | **No exponent rule exists at all.** `squared`, `cubed`, `to the power` are untouched — §9's own worked example (`"three squared"` → `3^2`) is unimplemented. | measured |
| B7 | **No refusal path anywhere in the layer.** There is no return value, type, or field by which Utterance Intake can say "ambiguous — ask the learner". | ticket 11 owns the fix |

### C. What this produces today (measured, not argued)

```
grade("9",  "three squared")  -> wrong    normalize: "3 squared"
grade("27", "three cube")     -> wrong    normalize: "3 cube"
grade("√2", "route two")      -> wrong    normalize: "route 2"
grade("-4", "−4")  (U+2212)   -> wrong    normalize: "−4"   (sign lost)
grade("0.5","½")              -> None     normalize: "½"    (no digit found)
```

Rows 1-4 are **confident false negatives**: the learner is right, the runtime says wrong, no
question is asked, and the verdict feeds Learner State as evidence. §9 exists to make these
refusals instead. Row 5 defers rather than misfires — closer to the wanted behaviour, but it
is reached by accident (nothing parsed), not by detecting ambiguity.

### D. STT uncertainty is degraded before it reaches the layer

| # | Problem | Evidence |
|---|---|---|
| D1 | `stt_confidence` is one float — a **mean across result segments**, so a single mangled word is averaged away. | `cloud_run_service/voice/cloud_stt.py:68-71` |
| D2 | `enable_word_confidence` and `enable_word_time_offsets` are both unset. §9's "low-confidence *word*" and "tap the word" are therefore impossible. One boolean each. | `cloud_stt.py:54-60` |
| D3 | `max_alternatives` unset ⇒ `alternatives[0]` only. The N-best list — the natural source of "root two vs route two" — is discarded at the wire. | `cloud_stt.py:66,131` |
| D4 | **Contradictory defaults for the same missing value.** Absent confidence → `0.0` (distrust everything) at `cloud_stt.py:71`; absent confidence → `1.0` (trust everything) at `interaction_control/control.py:249`. Google documents that confidence is not always populated, so both branches are live. | measured |
| D5 | The two `cloud_stt.py` copies have **diverged**. `cloud_run_service/voice/` extracts confidence; the root `voice/` copy extracts none — transcript only. | `voice/cloud_stt.py:55` vs `cloud_run_service/voice/cloud_stt.py:68` |
| D6 | The streaming path discards confidence entirely, on both copies. | `cloud_stt.py:129-131` |
| D7 | `language_code` is hard-defaulted to **`en-US`** on an Indian-English deployment. Svarah measures Google Cloud at 30.0 % WER (US config) vs 20.7 % (India config) on Indian-accented English — but see §7 of the findings: the configuration difference is **not** documented, so do not credit the gap to `language_code` alone. | `cloud_stt.py:37` |
| D8 | Phrase hints are a **module-level constant of 30 fixed phrases**, quadratics-and-trig only. §9's *"and the active concept"* has a real mechanism — STT v2 accepts an `inlinePhraseSet` per request — which is unused. | `cloud_stt.py:21-28,43` |
| D9 | **Constraint, not a defect.** Google documents that Chirp 2 / Chirp 3 word confidence "isn't truly a confidence score", and that Chirp 2 rejects custom classes. "Move to Chirp for Indian English" and "gate on word confidence" are mutually exclusive. | findings §4 |

### E. Homophones

No lexicon, no concept-scoped disambiguation, and no N-best to compare against (D3). The
findings file carries a **42-row** table for ticket 14, each row marked `[S]` source-backed /
`[M]` measured here / `[R]` reasoned. It includes the production case **"discriminant" →
"railroads"** already recorded in `cloud_stt.py:5-8`, MathSpeech's `sine`→"side" and
`cosine`→"Posing", and Indian-English rows (/v/–/w/ merger, "three"→"tree") grounded in
Wiltshire 2020 but marked `[R]` — no measured pair frequencies were found.

Calibration for ticket 14: Spoken-MQA found **32 of 100** MATH problems ambiguous to humans
without visual context. A near-zero refusal rate is therefore a **failing** result, not a
passing one.

### Handed to ticket 11 (no contract decided here)

- **Refusal is a consequence of the parser choice, not a feature to bolt on.** Lark Earley
  with `ambiguity='explicit'` detects ambiguity structurally, and its competing trees double
  as the learner-facing clarification options. **PEG structurally cannot** — Ford's paper
  states prioritized choice removes ambiguity by construction. LALR reports conflicts at build
  time only. SymPy `parse_expr` uses `eval` (its own security warning) and `parse_latex` "may
  fail silently". Findings §3.3 has the comparison with adoption costs.
- **`math_grade.normalize` is not a grammar with a missing refusal.** It is a replacement chain
  that cannot hold a parse (B3). Ticket 11 chooses: build a real parser beside it, or supersede
  it. Extending it cannot satisfy §9.
- **The auditable-parse artifact** (findings §6.2) needs a shape decision: a derivation record
  vs MathML dual presentation/content annotation. §6.3 names the two existing repo surfaces —
  `trusted_observations` and the evidence ledger — without picking one.

### Could not verify (findings §7 carries all 11)

Two matter before anyone plans around them:

- The `en-IN` feature matrix for **`asia-south1`** is unconfirmed. The captured rows were for
  other regions; Google directs to the Locations API, which was not called. CLAUDE.md pins
  Vertex to `asia-south1`.
- How Svarah configured "Google (US)" vs "Google (India)" — locale, endpoint region, or both.

Also open: whether the diverging `cloud_stt.py` copies (D5) are drift or design — **ticket 13**.
