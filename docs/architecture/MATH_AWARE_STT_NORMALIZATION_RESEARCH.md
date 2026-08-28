# Math-Aware STT Normalisation & the Auditable Parse (Research)

**Status:** research notes feeding ticket 11 (`.scratch/deterministic-input-layer/issues/11-decide-the-stt-uncertainty-contract.md`)
and ticket 14 (the golden corpora). **This document decides nothing.** Ticket 11 owns the contract.
**Scope:** the four deliverables the ticket names — (a) constrained-grammar approaches for spoken
maths *with their refusal semantics*, (b) what Cloud STT can supply that the current single-float
`stt_confidence` throws away, (c) the homophone cases that must enter ticket 14's golden corpus,
(d) what "auditable parse" means concretely.

**Conventions used throughout:**
- **[S]** = a claim a primary source states. URL given inline.
- **[M]** = a claim **measured in this repo** during this research (probe commands shown). Read-only; no production code changed.
- **[I]** = **my inference / reasoning.** Not asserted by any source.
- Codebase claims carry `file.py:line`.

**Bottom line up front:**

1. `mathtext.py` is a **renderer, not a parser** — it runs maths→text, the wrong direction, and
   cannot be reused as a grammar (`cloud_run_service/mathtext.py:1-26`). **[M]**
2. `math_grade.normalize` **is** the repo's only spoken-maths parser, and it already covers four of
   §9's five named failure classes — but it **always commits, never refuses**, so a misheard word
   surfaces as a confident **wrong** grade rather than a clarification. Measured: the docx's own
   worked example, *"three squared"* against expected `9`, **grades `wrong` today**. **[M]**
3. `normalize_input` is not neutral on maths. Its NFKC step **destroys exponents**: `x²` → `x2`.
   The existing test acknowledges this and asserts around it
   (`cognitive_input_processor/tests/test_input_processor.py:23-29`). **[M]**
4. The STT adapter is **Cloud STT v1** with `language_code="en-US"` — not `en-IN` — and reads only
   `alternatives[0]` (`cloud_run_service/voice/cloud_stt.py:38-80`). AI4Bharat's Svarah benchmark
   measures Google Cloud at **30.0 % WER (US) vs 20.7 % WER (India)** on Indian-accented English. **[S]**
5. Refusal is achievable but the mechanism differs sharply by grammar family: **Earley (lark) can
   *detect* ambiguity and hand you every derivation**; **PEG structurally cannot** — it resolves by
   priority and cannot tell you it did. **[S]**
6. Spoken maths is *inherently* ambiguous, not merely mis-heard: a human study found **32 of 100**
   MATH-dataset problems "potentially ambiguous to humans without visual or text context". **[S]**
   That is the empirical case for §9's "the parser refuses" pass condition.

---

## 1. The requirement, verbatim

Extracted from `docs/archive/AI_Tutor_Child_Safe_Interaction_Specification.docx` (§9, "Speech-to-text
(STT) handling requirements"):

> The transcript is an estimate of speech, not the child's ground truth. Mathematics is especially
> sensitive: 'root two' and 'route two', 'factor' and 'fraction', 'x squared' and 'x cube', minus
> signs, and local-language pronunciation can produce materially different meanings.

| Requirement | Operational rule | Pass condition |
|---|---|---|
| Uncertainty preservation | Carry confidence and, where feasible, N-best hypotheses through intent, concept and grading. Never overwrite the original audio/transcript provenance. | A low-confidence word that changes an answer produces a clarification, not a score. |
| Math-aware normalisation | Normalise spoken forms only through a constrained maths grammar and the active concept. Keep an auditable parse, e.g., 'three squared' -> 3^2. | **The parser refuses an ambiguous or out-of-grammar rewrite.** |
| Confirmation before consequence | Confirm before marking, changing level, recording a misconception, or sending a safety escalation based on uncertain language. | The child can answer yes/no, tap a displayed alternative, or type. |
| Accessible repair | Offer 'say it again', 'tap the word', 'type it', and 'show the question' paths. | Every voice-only failure has a non-voice fallback. |

And the sample repair utterance the docx itself supplies:

> "I heard 'three squared'. Did you mean 3^2? Tap Yes or No. If not, you can say the word again or type it."

§8 is the constraint that bounds any grammar work:

> A child can say 'ulta U', 'that bend thing' or a local-language equivalent. Treat it as an
> invitation to map meanings, not as nonsense.
> […]
> Repair gently: 'I may have heard factors. Did you mean factors or fractions?' A yes/no/tap choice
> is easier than making the child repeat a long sentence.

**[I]** §8 and §9 pull in opposite directions and the pull is the design problem: §9 wants a *narrow*
grammar that refuses; §8 forbids treating out-of-grammar informal speech as nonsense. A refusal must
therefore route to **clarification**, never to the existing `NONSENSE` gate
(`cloud_run_service/perception/gates.py:96-121`, `gate()` at `:124-149`).

---

## 2. Ground truth in the codebase

### 2.1 `normalize_input` is surface-only — and NFKC is not meaning-preserving on maths

`cloud_run_service/cognitive_input_processor/input_processor.py:370-410`. Its docstring is explicit
("We do NOT rewrite student meaning"), and the operations are NFKC (`:395`), zero-width strip
(`:399`), punctuation spacing (`:245`, `:401-403`), whitespace collapse (`:244`, `:405-406`).

But NFKC applies **compatibility** decomposition, which is exactly the class of mapping that folds
maths notation into ordinary digits. Measured on this machine's Python 3.10: **[M]**

```
'3x²'  -> '3x2'      # exponent destroyed — "3x squared" becomes "3x2"
'x³'   -> 'x3'
'½'    -> '1⁄2'      # U+2044 FRACTION SLASH, NOT ASCII '/'
'5−5'  -> '5−5'      # U+2212 MINUS SIGN survives; downstream regexes want ASCII '-'
'√2'   -> '√2'       # unchanged
'5×3'  -> '5×3'      # unchanged
```

Two consequences that matter:

- **`x²` → `x2` is a meaning change**, made by the one function whose contract forbids meaning
  changes. The repo's own test acknowledges it in a comment and then asserts only a weakened
  property: `# NFKC normalizes superscript 2` … `assert "3x" in norm`
  (`cloud_run_service/cognitive_input_processor/tests/test_input_processor.py:23-29`).
- **`mathtext.to_panel_unicode` deliberately emits `²`/`³`** for the display card
  (`cloud_run_service/mathtext.py:215-243`, `PANEL_GLYPHS` at `:194`). **[I]** Any surface where
  panel text is echoed back through the input path (e.g. a child reading the card aloud and the
  system comparing strings, or a typed-answer path fed panel text) silently loses the exponent.
- **§9 names "minus signs" specifically.** U+2212 is *not* folded by NFKC, and every downstream
  numeric regex uses ASCII `-` (`cloud_run_service/math_grade.py:74-84`,
  `cloud_run_service/cognitive_input_processor/input_processor.py:572` `_EQUATION_RE`). **[M]**

**[I]** So the honest statement of the status quo is not "normalize_input does nothing to maths" — it
is "normalize_input does *one* thing to maths, and that one thing is wrong."

### 2.2 `mathtext.py` — a **renderer**, definitively not a parser

Direction is maths-markup → human-readable text, in four surface flavours: `to_spoken`
(`:151-172`), `to_panel` (`:174-189`), `to_panel_unicode` (`:215-243`), `to_question` (`:247-258`).
Its own docstring: *"It only touches surface form; it must never change the maths"*
(`cloud_run_service/mathtext.py:24-25`).

There is no tokenizer, no grammar, no tree, no failure mode — every function is a regex substitution
chain that returns a string. `fold_superscripts` (`:133-138`) goes `x^2` → `"x squared"`: the
**inverse** of what §9 asks for.

**Reuse verdict: [I]** its value to a spoken-maths parser is as a **vocabulary source, not a
component**. `SPOKEN_SYMBOLS` (`:88-101`), `GREEK` (`:103-109`) and `fold_superscripts` enumerate the
exact surface forms the tutor *speaks*, and a grammar that must accept what the child heard the tutor
say should accept precisely that set. Inverting those tables is cheap and gives the grammar its
terminal alphabet for free. The regex machinery itself must not be reused — regex substitution has no
way to express "refuse".

### 2.3 `math_grade.py` — the repo's only spoken-maths parser, and it never refuses

`cloud_run_service/math_grade.py:40-67` (`normalize`) is a real, deliberate spoken-maths folder, and
it was written against §9's own examples:

- `"root two"` → `sqrt 2` (`:49-50`)
- `"one by three"` / `"one over three"` → `1/3` (`:52`)
- `"minus four"` → `-4` (`:51`)
- number words → digits, incl. `"twenty five"` → `25` (`:23-32`, `:54-66`)
- `"equals"` → `=` (`:53`)

And `grade()` (`:111-143`) already has a **three-valued** return — `"correct" | "wrong" | None`,
where `None` means "cannot decide from surface form; caller defers" (`:12-17`). **[I]** That third
value is the closest thing in the repo to a refusal channel, and it is the natural shape for a
grammar's `REFUSE` outcome. But `normalize` itself is total: it always returns a string, always
commits.

**Measured probes** (read-only, `python -c` against `cloud_run_service/`): **[M]**

| Spoken input | `normalize` output | `grade(expected, …)` | Comment |
|---|---|---|---|
| `"root two"` | `sqrt 2` | vs `sqrt 2` → **correct** | §9's good case works |
| `"route two"` | `route 2` | vs `sqrt 2` → **wrong** | §9's homophone. Graded **wrong**, not refused |
| `"three squared"` | `3 squared` | vs `9` → **wrong** | **the docx's own worked example fails** |
| `"three cube"` | `3 cube` | vs `27` → **wrong** | §9's "x squared"/"x cube" pair |
| `"minus four"` | `-4` | vs `-4` → **correct** | |
| `"1⁄2"` (NFKC output of `½`) | `1⁄2` | vs `0.5` → **wrong** | U+2044 not matched by `-?[0-9]+/[0-9]+` (`:78`) |
| `"5−5-0"` (U+2212) | unchanged | vs `-5` → **wrong** | §9's "minus signs" |
| `"x squared"` | `x squared` | vs `9` → **None** | defers — the only refusal-ish outcome observed |
| `"the root cause"` | `the sqrt cause` | — | **over-application**: `\broot\s+` (`:50`) fires on prose |
| `"one over x plus two"` | `1/x plus 2` | — | commits to one of three readings, silently |

The last two are the crux. `"the root cause"` shows the grammar is **not constrained** — it rewrites
outside the maths domain. `"one over x plus two"` is the canonical scope ambiguity (see §5) and the
current code picks a winner with no record that it did.

**Reuse verdict: [I]** `math_grade` is the right seed. Its lexicon (`_ONES`, the root/fraction/minus
rules) is a grammar's terminal set already written and already regression-tested via
`eval/grader_eval.py`. What it lacks is (i) a tree, (ii) a scope-resolution step that can report a
tie, (iii) a domain guard so `root`/`over`/`by` only fire inside a maths span, and (iv) a `REFUSE`
return. It is a **parser core to be lifted**, not a module to be called from the Input Layer as-is —
and note it currently lives at service root and is consumed by grading
(`cloud_run_service/evidence/grading.py:35-36`, `cloud_run_service/tutor_loop.py:859-860`,
`cloud_run_service/items/verify.py:17-18`), i.e. *after* the Input Layer, on the answer path only.

### 2.4 The STT path — v1, `en-US`, top-alternative only

`cloud_run_service/voice/cloud_stt.py` (a near-duplicate of root `voice/cloud_stt.py`; the root copy
lacks `TranscriptionEvidence` and returns bare strings — **the root copy discards confidence
entirely**, confirmed by `diff`).

| What the code does | Where | What is lost |
|---|---|---|
| Imports `google.cloud.speech` (**v1**) | `:15` | v2's `RecognitionFeatures`, inline `PhraseSet`, `CustomClass`, chirp models |
| `language: str = "en-US"` | `:38` | `en-IN`; see §4.4 for the measured cost |
| `model: str = "latest_short"` | `:39` | |
| `speech.SpeechContext(phrases=…, boost=18.0)` | `:43` | v1 legacy hints; superseded by `adaptation` per Google's own docs (§4.3) |
| `MATHS_PHRASES` is a **module-level constant**, 27 fixed phrases | `:21-28` | §9's "and the active concept" — the set is global and never varies by concept |
| reads `r.alternatives[0]` only | `:66`, `:131` | every alternate hypothesis |
| **no** `max_alternatives` | `:55-62` | N-best (v1 allows 0–30) |
| **no** `enable_word_confidence` | `:55-62` | per-word confidence — §9's "a low-confidence *word*" |
| **no** `enable_word_time_offsets` | `:55-62` | word spans — needed for "tap the word" |
| averages per-result confidence into one float | `:68-71` | which segment was doubtful |
| streaming path returns `str`, no confidence at all | `:104-158` | all of the above, on the live path |

The single float then travels as `trusted_observations["stt_confidence"]`
(`cloud_run_service/wini_server.py:607-614`), is compared once against
`STT_WRITE_CONFIDENCE_MIN` at `cloud_run_service/interaction_control/control.py:248-252`, and
vanishes. Two independent places also gate on it —
`cloud_run_service/evidence/ledger.py:197-198` and
`cloud_run_service/assessment_evidence/interface.py:116-117` — so ticket 11's "consequence gates"
question already has three de-facto owners.

The docstring at `cloud_run_service/voice/cloud_stt.py:5-8` records a real observed failure worth
keeping: *"a generic model otherwise mangles ('railroads')"* — i.e. **"discriminant" → "railroads"**,
a production homophone case (see §5).

---

## 3. (a) Constrained-grammar approaches and their refusal semantics

### 3.1 First, what "refuse" can even mean

Four mechanically distinct things get called refusal. **[I]** Ticket 11 should pick which one(s) the
contract means, because they have different costs and different false-refusal profiles:

| # | Refusal kind | Trigger | Mechanism required |
|---|---|---|---|
| R1 | **Out-of-grammar** | no derivation exists | any parser: parse error |
| R2 | **Genuinely ambiguous** | ≥2 distinct derivations | a parser that *enumerates* derivations (Earley/GLR), or an explicit conflict report (LALR) |
| R3 | **Low-confidence span** | the ASR itself was unsure over a token the parse depends on | per-word confidence + N-best from STT (§4) |
| R4 | **Concept-inconsistent** | parse is well-formed but out of the active concept's vocabulary | the "and the active concept" half of §9 |

Only R2 needs a grammar engine with ambiguity reporting. R1 is free. R3 lives entirely in the STT
layer. R4 is a lookup against the concept graph, not a parser feature.

### 3.2 The engines

**Earley + `ambiguity='explicit'` (lark) — the only option that *detects* ambiguity as data.**
Lark's Earley parser is "capable of parsing any context-free grammar at O(n^3), and O(n^2) when the
grammar is unambiguous"
([Parsers — Lark docs](https://lark-parser.readthedocs.io/en/stable/parsers.html)). **[S]** By
default "Lark will choose the best derivation for you", but users can "receive the set of all
possible parse-trees (using `ambiguity='explicit'`)" (same page). **[S]** In that mode ambiguity
surfaces as `_ambig` nodes in the returned tree, with the classic *"fruit flies like bananas"*
worked example
([Handling Ambiguity](https://lark-parser.readthedocs.io/en/stable/examples/fruitflies.html)), and
`CollapseAmbiguities` converts the forest to a list of unambiguous trees. **[S]** Internally it is an
SPPF ([Working with the SPPF](https://lark-parser.readthedocs.io/en/latest/forest.html)). **[S]**

**[I]** This is the single most direct fit for §9's pass condition: `len(trees) > 1` **is** the
refusal predicate, and the multiple trees are simultaneously the material the clarification UI needs
("Did you mean 1/(x+2) or 1/x + 2?").

**PEG / packrat — structurally *cannot* refuse on ambiguity.** Ford's POPL 2004 paper states that
PEGs "solve the ambiguity problem by not introducing ambiguity in the first place", and "Where CFGs
express nondeterministic choice between alternatives, PEGs instead use *prioritized choice*"
([Ford, *Parsing Expression Grammars: A Recognition-Based Syntactic Foundation*](https://bford.info/pub/lang/peg/)). **[S]**
**[I]** A PEG for spoken maths would silently pick whichever reading the author ordered first — which
is exactly today's `math_grade` behaviour dressed up in a grammar. PEG gives you R1 for free and R2
never. If ticket 11 wants R2, PEG is disqualified.

**LALR — refuses at *build* time, not at run time.** Lark's LALR(1) is "incredibly fast and requires
very little memory" and its contextual lexer "uses the parser's lookahead prediction to narrow its
choice of terminals" (same Parsers page). **[S]** **[I]** An LALR grammar surfaces ambiguity as a
shift/reduce or reduce/reduce **conflict when the parser table is generated** — that is, the ambiguity
is reported to the *developer*, and the grammar author must then resolve it (precedence, restructuring)
before the parser will build. At runtime an LALR parser is deterministic and cannot report "this input
was ambiguous". It buys R1 and speed; not R2.

**SymPy `parse_expr` — do not put this on the input path.** SymPy's own docs carry the warning:
"Note that this function uses `eval`, and thus shouldn't be used on unsanitized input"
([SymPy parsing module](https://docs.sympy.org/latest/modules/parsing.html)). **[S]** A child's
transcript is by definition unsanitized. `standard_transformations` is
`lambda_notation, auto_symbol, repeated_decimals, auto_number, factorial_notation`; the optional
`implicit_multiplication` "makes the multiplication operator optional in most cases" and `convert_xor`
"Treats XOR, `^`, as exponentiation, `**`" (same page). **[S]** **[I]** `implicit_multiplication` is
precisely an *ambiguity-resolving* transformation — it commits, it does not report. SymPy remains
useful **downstream of the parse**, as an equivalence oracle over an already-built tree
(`math_grade` currently does that job with floats), but it is not a gate.

`parse_latex` is worse for this purpose: the docs mark it "experimental" with API subject to change,
it needs `antlr4-python3-runtime`, and "The ANTLR parser may fail silently on incomplete expressions
without warnings" (same page). **[S]** Silent failure is the opposite of a refusal.

**Speech Rule Engine (SRE) — the right direction is the wrong direction.** SRE "translate[s] XML
expressions into speech strings according to rules that can be specified in a syntax using Xpath
expressions" and was built for ChromeVox
([Speech-Rule-Engine README](https://github.com/Speech-Rule-Engine/speech-rule-engine)). **[S]** It
ships the full **MathSpeak** and **ClearSpeak** rule sets plus Nemeth for braille, and localisation
lives in a separate repo `sre-l10n` "using a bespoke YAML format for rules"
([speechruleengine.org](https://speechruleengine.org/), rule format at
[sre-l10n yaml docs](https://speech-rule-engine.github.io/sre-l10n/yaml.html)). **[S]** Locales listed
include **Hindi**. **[S]** MathJax ships it and defaults to ClearSpeak with MathSpeak selectable
([MathJax a11y extensions](https://docs.mathjax.org/en/latest/basic/a11y-extensions.html)). **[S]**

The ticket's framing — "SRE is the *inverse* direction but its rule catalogue is the authoritative
enumeration of spoken forms and is directly reusable as a grammar source" — **is only half
confirmed.** Confirmed: it is the inverse direction, and it does carry MathSpeak/ClearSpeak rule
catalogues as data files. **Not confirmed:** speechruleengine.org "does not document an enumerated
catalogue of spoken forms for mathematical symbols" as a standalone artifact; the rules are XPath
transformation rules over a semantic tree, not a symbol→phrase table. **[S/I]** Extracting a terminal
alphabet from `sre-l10n` YAML is plausible but is *engineering*, not a lookup — budget for it.

The underlying styles do have citable specifications: ClearSpeak's design and evaluation is published
as an ETS research report
([Frankel, Brownstein & Soiffer, *Development and Initial Evaluation of the ClearSpeak Style for
Automated Speaking of Algebra*, ETS RR-16-13](https://files.eric.ed.gov/fulltext/ED570857.pdf)). **[S]**

**TalkMaths — the closest working precedent for speech→maths with a grammar.** TalkMaths used Dragon
NaturallySpeaking for ASR and mapped the transcript to notation "using a customized Context-Free
Grammar (CFG), which generated a parse tree that was then converted into the desired markup format"
(MathML or LaTeX)
([TalkMaths project site](https://talkmaths.sourceforge.net/); Kingston University publications). **[S]**
**[I]** This is architecturally exactly §9: ASR → CFG → parse tree → markup. It confirms the shape is
buildable. I could **not** find published refusal semantics or coverage/accuracy numbers for it from a
primary source (see §7).

### 3.3 Comparison for this codebase

| Approach | Refusal semantics | Detects R2 (ambiguity)? | Reuses `math_grade`? | Reuses `mathtext`? | Cost here |
|---|---|---|---|---|---|
| Keep regex folding (status quo) | none — always commits | no | is it | no | zero, but fails §9 outright **[M]** |
| Add an explicit **conflict table** to the regex folder | hand-written: if ≥2 rules match a span → REFUSE | only cases you anticipated | yes, directly | vocabulary only | small; no new dep; no coverage guarantee **[I]** |
| **lark Earley, `ambiguity='explicit'`** | `len(CollapseAmbiguities(tree)) > 1` → REFUSE, and the trees *are* the clarification options | **yes, structurally** | lexicon as terminals | vocabulary as terminals | new pure-Python dep; grammar authoring is the real cost **[S/I]** |
| lark LALR | parse error → REFUSE (R1); R2 caught at grammar-build time only | no (build-time only) | lexicon as terminals | vocabulary | same dep, faster, weaker **[S/I]** |
| PEG (`parsimonious`/`pegen`) | parse error only | **no — prioritized choice hides it** | lexicon | vocabulary | disqualified if R2 is required **[S]** |
| SymPy `parse_expr` | exceptions only; `eval`-based | no | — | — | **security warning in SymPy's own docs** **[S]** |
| LLM post-correction (MathSpeech / Speech-to-LaTeX style) | none native; would need a separate verifier | no | — | — | contradicts the repo's "deterministic floor" doctrine (`math_grade.py:1-3`, `perception/gates.py:5-16`) **[I]** |

**[I]** On import purity (ticket 14's requirement): lark is pure Python with no compiled deps, which
matters because ticket 14 asks whether Input-Layer tests can run with no torch / no Vertex / no
`rag_store`. SymPy and ANTLR runtimes are heavier. This is a fact ticket 11 should weigh but I did not
verify lark's dependency tree from its packaging metadata (see §7).

---

## 4. (b) What Cloud STT can supply that one float discards

### 4.1 Field by field

Every field below is documented on
[RecognitionConfig (v1 REST)](https://docs.cloud.google.com/speech-to-text/docs/reference/rest/v1/RecognitionConfig)
and [speech.recognize (v1 REST)](https://docs.cloud.google.com/speech-to-text/docs/reference/rest/v1/speech/recognize).
**[S]**

| Field | What it gives | Doc wording | Currently used? |
|---|---|---|---|
| `maxAlternatives` | N-best hypotheses | "Maximum number of recognition hypotheses to be returned… Valid values are 0–30. A value of 0 or 1 will return a maximum of one." | **no** (`cloud_stt.py:55-62`) |
| `SpeechRecognitionResult.alternatives[]` | the N-best list | "May contain one or more recognition hypotheses (up to the maximum specified in `maxAlternatives`)" | only `[0]` (`:66`, `:131`) |
| `enableWordConfidence` | per-word confidence | "If true, the top result includes a list of words and the confidence for those words." | **no** |
| `enableWordTimeOffsets` | per-word spans | "If true, the top result includes a list of words and the start and end time offsets (timestamps) for those words." | **no** |
| `WordInfo.confidence` | the per-word float | same 0.0–1.0 description as the alternative-level one | **no** |
| `SpeechRecognitionResult.resultEndTime` | segment end offset | "Time offset when this result portion ends" | **no** |
| `SpeechRecognitionResult.languageCode` | detected language | "The BCP-47 language tag detected as most likely" | **no** |
| `adaptation` (`SpeechAdaptation`) | phrase sets / custom classes | "Speech adaptation configuration improves the accuracy of speech recognition." | **no** — v1 `speechContexts` used instead (`:43`) |

**[I]** `enableWordConfidence` + `enableWordTimeOffsets` together are precisely what §9's "a
low-confidence **word** that changes an answer produces a clarification" and §9's "**tap the word**"
require. Neither is expressible from a single averaged float. Both are one boolean each.

### 4.2 The confidence caveat — this is the important one

Google documents `SpeechRecognitionAlternative.confidence` as: **[S]**

> "The confidence estimate between 0.0 and 1.0. A higher number indicates an estimated greater
> likelihood that the recognized words are correct."

…and, critically, that it is

> "set only for the top alternative of a non-streaming result or, of a streaming result where
> `isFinal=true`"

and

> "is not guaranteed to be accurate and users should not rely on it to be always provided."

([speech.recognize v1 reference](https://docs.cloud.google.com/speech-to-text/docs/reference/rest/v1/speech/recognize))
`WordInfo.confidence` carries the same caveat.

**[I]** Three things follow for ticket 11:
1. Confidence is **only on the top alternative** — so an N-best list does *not* come with per-hypothesis
   scores you can rank by. Ranking alternates for the "tap an alternative" UI needs another signal
   (order, or agreement with the grammar).
2. "Should not rely on it to be always provided" means the current `confidence = … if confidences else 0.0`
   fallback (`cloud_stt.py:71`) maps *absent* to **0.0**, which then reads as maximally untrusted and
   trips the write floor. The absent case and the genuinely-unsure case are conflated. The other
   default in the system does the opposite: `stt_confidence = 1.0 if stt_confidence is None`
   (`interaction_control/control.py:249`) maps absent to **fully trusted**. **Two opposite defaults
   for the same missing value.** **[M]**
3. Ticket 11's observation that "in text testing the gate never fires" is confirmed by that `1.0`
   default — and now has a second cause: the streaming path (`cloud_stt.py:104-158`) returns a bare
   string, so live streaming turns have *no* confidence at all.

**Chirp caveat — a genuine trap.** For Chirp 2, word-level confidence is listed with: "The API returns
a value, but it isn't truly a confidence score. In the case of translation, confidence scores are not
returned." ([Chirp 2 docs](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-2)) **[S]**
Chirp 3 repeats it: "The API returns a value, but it isn't truly a confidence score."
([Chirp 3 docs](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3)) **[S]**
**[I]** So "move to chirp for better Indian-English accuracy" and "gate consequences on word
confidence" are in direct tension. Ticket 11 cannot assume both.

### 4.3 Adaptation, and the "active concept" hook

- v1's `speechContexts` is explicitly superseded: **"When speech adaptation is set it supersedes the
  `speechContexts` field."**
  ([RecognitionConfig](https://docs.cloud.google.com/speech-to-text/docs/reference/rest/v1/RecognitionConfig)) **[S]**
  The repo uses `speechContexts` (`cloud_stt.py:43`).
- `SpeechContext.boost`: "Positive value will increase the probability that a specific phrase will be
  recognized over other similar sounding phrases"; "most use cases are best served with values between
  0 and 20". **[S]** The repo uses `boost=18.0` (`cloud_stt.py:39`) — near the top of that band.
- v2 adaptation: "The practical maximum limit for boost values is 20."
  ([Speech adaptation, v2](https://docs.cloud.google.com/speech-to-text/v2/docs/speech-adaptation)) **[S]**
- **Per-request phrase sets are supported.** v2's `SpeechAdaptation.phraseSets[]` is a union:
  `phraseSet` = "The name of an existing PhraseSet resource" **or** `inlinePhraseSet` = "An inline
  defined PhraseSet"
  ([Recognizer reference, v2](https://docs.cloud.google.com/speech-to-text/v2/docs/reference/rest/v2/projects.locations.recognizers)). **[S]**
  The adaptation guide confirms both deployment modes: "inline_phrase_set in a recognition request"
  vs. creating a persistent `PhraseSet` resource. **[S]**
  **[I] This is the direct mechanism for §9's "and the active concept"** — a per-turn inline phrase set
  built from the current concept card's vocabulary, with no pre-created resource per concept.
- v1 limits per request: **5,000 phrases**, **100 characters per phrase**, **100,000 characters total**
  ([Quotas & limits](https://docs.cloud.google.com/speech-to-text/quotas)). **[S]** **[I]** A
  per-concept vocabulary is two to three orders of magnitude under that ceiling; size is a non-issue.
- **Class tokens** are directly relevant to maths: `$OPERAND` = "A numerical value including whole
  numbers, fractions, and decimals"; `$OOV_CLASS_DIGIT_SEQUENCE` = "A digit sequence of any length";
  `$OOV_CLASS_ALPHA_SEQUENCE` = "A sequence of letters [a-z]"; `$OOV_CLASS_ALPHANUMERIC_SEQUENCE`
  ([Class tokens](https://docs.cloud.google.com/speech-to-text/docs/class-tokens)). **[S]**
  Caveat from the adaptation guide: "Class availability varies by transcription model and language",
  and — a silent-failure trap — "If you use an invalid or malformed class token, Speech-to-Text
  ignores the token without triggering an error but still uses the rest of the phrase for context." **[S]**
- **Chirp 2 does not support class tokens or custom classes**: adaptation is "hints… in the form of
  simple words or phrases… Class tokens or custom classes are not supported."
  ([Chirp 2](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-2)) **[S]**
  Chirp 3 supports "up to 1,000 phrases" for adaptation
  ([Chirp 3](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3)). **[S]**

### 4.4 `en-IN` and the code-switching context

- The adapter is configured `en-US` (`cloud_stt.py:38`), with a comment explaining the choice was made
  to *force English output* after Gemini Live transcribed Indian-accented English into Telugu/Hindi
  script (`cloud_stt.py:1-8`). **[I]** That rationale argues for a fixed language code; it does **not**
  argue for `en-US` over `en-IN` — both force English.
- **Measured cost of that choice.** AI4Bharat's Svarah benchmark (9.6 h, 117 speakers, 65 districts,
  19 states) reports WER on Indian-accented English:
  **Google (US) 30.0 %, Google (India) 20.7 %, Azure (US) 20.9 %, Azure (India) 21.3 %,
  Whisper-large 7.2 %** (vs 2.7 % on LibriSpeech)
  ([Javed et al., *Svarah: Evaluating English ASR Systems on Indian Accents*, arXiv:2305.15760](https://arxiv.org/abs/2305.15760),
  table reproduced at [ar5iv](https://ar5iv.labs.arxiv.org/html/2305.15760) and in the
  [repo README](https://github.com/AI4Bharat/Svarah/blob/master/README.md)). **[S]**
  The paper also notes entity-type content is the hard part: "the data corresponding to everyday use
  cases contains many entities such as brand names, bank names, food items, document IDs, and so on.
  Recognizing such entities when spoken in Indian accents is hard for existing ASR systems." **[S]**
  **[I]** Numerals and maths terms are the same entity class; this is the strongest available proxy
  evidence that maths dictation in `en-IN` is materially harder than the WER headline suggests.
  **[Caveat]** I could not determine from the paper text I read exactly how "Google (US)" vs
  "Google (India)" were configured (locale? endpoint region? both?) — do not translate the 9-point gap
  into "changing `language_code` buys 9 points" without a local A/B.
- **`en-IN` feature support.** The v2 supported-languages table lists `en-IN` with, among others:
  `long` and `short` models supporting **Automatic punctuation, Model adaptation, Word-level
  confidence, Profanity filter, Spoken punctuation, Spoken emoji**; `chirp_2` supporting
  **Automatic punctuation, Model adaptation, Word-level confidence, Profanity filter**; `chirp_3`
  supporting **Automatic punctuation, Speaker diarization, Model adaptation, Profanity filter** (no
  word confidence)
  ([Cloud STT V2 supported languages](https://docs.cloud.google.com/speech-to-text/docs/speech-to-text-supported-languages)). **[S]**
  **[Caveat]** that page is region-filterable and the rows I captured were under `asia-southeast1` /
  `eu`; I did **not** confirm the `asia-south1` (Mumbai) row, which is the region CLAUDE.md names for
  Vertex. Google's docs direct you to the Locations API for the authoritative per-region matrix
  ([Regional availability](https://docs.cloud.google.com/speech-to-text/docs/locations)). **[S]**
  Verify with a live `locations` call before committing.
- **Code-switching.** Published baselines for Hindi–English and Bengali–English code-switched ASR
  (MUCS 2021, ~600 h of Indian-language speech) sit at **28.45 %–34.08 % WER** across GMM-HMM, TDNN
  and end-to-end systems on test/blind sets
  ([Diwan et al., *MUCS 2021*, Interspeech 2021 / arXiv:2104.00235](https://arxiv.org/pdf/2104.00235);
  [ISCA archive](https://www.isca-archive.org/interspeech_2021/diwan21_interspeech.html);
  [dataset, OpenSLR 104](https://www.openslr.org/104/)). **[S]**
  Broader Indian-language ASR benchmarking: IndicSUPERB / Kathbath, 1,684 h across 12 languages
  ([Javed et al., arXiv:2208.11761](https://arxiv.org/pdf/2208.11761),
  [repo](https://github.com/AI4Bharat/IndicSUPERB)). **[S]**
  **[I]** §8's "ulta U" is exactly a code-switched token; at ~30 % WER on code-switched speech, the
  input layer must expect the *Hindi* word itself to be mis-transcribed, not merely unrecognised.

---

## 5. (c) Homophone and ambiguity cases for ticket 14's golden corpus

### 5.1 Published evidence that this is severe

- **MathSpeech** (AAAI 2025) measured commercial/open ASR on 1,101 audio samples (5,583 s, 10 speakers)
  from real maths lectures on MIT OpenCourseWare. **WER on formula speech: Whisper-base 34.7 %,
  Whisper-small 29.5 %, Whisper-largeV2 31.0 %, Whisper-largeV3 33.3 %, Canary-1B 35.2 %.**
  ([Hyeon et al., arXiv:2412.15655](https://arxiv.org/html/2412.15655v1)) **[S]**
- **Speech-to-LaTeX** (66k+ human-annotated audio samples, English + Russian) reports best equation
  CER **27.7–30.0 %** on English, and up to **39.7 %** equation CER inside mathematical sentences;
  **Whisper-Large v3 alone reaches 88 % CER** on equations
  ([arXiv:2508.03542](https://arxiv.org/abs/2508.03542), [HTML](https://arxiv.org/html/2508.03542v1)). **[S]**
- **Spoken-MQA** found that **"32 out of 100 problems are judged to be potentially ambiguous to humans
  without visual or text context"** when sampling from the MATH dataset
  ([Wei, Wang, Kim & Chen, arXiv:2505.15000](https://arxiv.org/html/2505.15000v1)). **[S]**

**[I]** That last number is the single most useful fact in this document. A **third** of spoken maths
is ambiguous *to a human listener*. §9's "the parser refuses" is therefore not a defensive nicety —
any parser that never refuses is provably wrong on roughly a third of the domain. It also sets the
realistic bar for ticket 14: a refusal rate near zero is a **failing** result, not a passing one.

### 5.2 Two distinct ambiguity classes — the corpus needs both

**Class A — homophone / mishearing.** The transcript is simply wrong. Fixed by better ASR, adaptation,
N-best, and R3 confidence gating.

**Class B — scope / structural ambiguity.** The transcript is **correct** and still admits multiple
parses. No amount of ASR improvement helps. Only R2 (grammar-level ambiguity detection) or a
clarification turn resolves it. Documented examples:

| Spoken | Possible readings | Source |
|---|---|---|
| "one over x plus two" | `1/(x+2)`, `1/x + 2` | Speech-to-LaTeX, arXiv:2508.03542 **[S]** |
| "the magnitude of z minus w" | `\|z-w\|`, `\|z\|-w` | Spoken-MQA, arXiv:2505.15000 **[S]** |
| "kappa" | `\kappa` (κ), `\varkappa` (ϰ) | Speech-to-LaTeX **[S]** |
| "minus four squared" | `(-4)^2 = 16`, `-(4^2) = -16` | **[R]** — and `math_grade.normalize` yields `-4 squared`, resolving nothing **[M]** |
| "two x plus one over three" | `(2x+1)/3`, `2x + 1/3` | **[R]** |
| "x to the n plus one" | `x^(n+1)`, `x^n + 1` | **[R]** |
| "sine x squared" | `sin(x^2)`, `(sin x)^2`, `sin^2 x` | **[R]** |

**[I]** Ticket 14's corpus must label these with expected verdict = **REFUSE / clarify**, not with a
"correct" answer. If the corpus assigns a single right answer to a Class-B item, it will train the
implementation to guess.

### 5.3 The confusion-pair table

| # | Heard as | Should be | Evidence | Notes |
|---|---|---|---|---|
| 1 | "route two" | "root two" | **[S]** docx §9 | Today: graded **wrong**, not refused **[M]** |
| 2 | "fraction" | "factor" (and reverse) | **[S]** docx §9 + §8 (`'I may have heard factors. Did you mean factors or fractions?'`) | |
| 3 | "x cube" | "x squared" | **[S]** docx §9 | Today: `3 cube` vs `27` → **wrong** **[M]** |
| 4 | minus sign forms (`-`, `−` U+2212, "minus", "negative") | one canonical minus | **[S]** docx §9 + **[M]** measured NFKC/regex mismatch | |
| 5 | local-language pronunciation | the maths term | **[S]** docx §9 + §8 ("ulta U") | |
| 6 | "railroads" | "discriminant" | **[S]** production observation recorded at `cloud_run_service/voice/cloud_stt.py:5-8` | The reason `MATHS_PHRASES` exists |
| 7 | "side" | "sine" | **[S]** MathSpeech arXiv:2412.15655 (`"cosine of x plus i side of x"`) | |
| 8 | "école" | "equals" | **[S]** MathSpeech | Cross-language substitution — relevant to a multilingual model |
| 9 | "posing" | "cosine" | **[S]** MathSpeech (`"Posing of psi sub i"`) | |
| 10 | "one" (word) | "1" (digit) | **[S]** MathSpeech ("the ASR model outputs it as one") | Semantically equivalent, string-unequal — `math_grade` handles this (`math_grade.py:23-32`) |
| 11 | `\varkappa` | `\kappa` | **[S]** Speech-to-LaTeX | Greek variant forms generally |
| 12 | "sign" | "sine" | **[R]** | True homophone in most accents; the highest-frequency maths homophone |
| 13 | "cos" / "cause" / "cost" | "cos" | **[R]** | |
| 14 | "tan" / "ten" / "than" | "tan" | **[R]** | |
| 15 | "pi" / "pie" | "pi" | **[R]** | |
| 16 | "sum" / "some" | "sum" | **[R]** | |
| 17 | "to" / "two" / "too" | "two" | **[R]** | "x to the two" is a minefield |
| 18 | "for" / "four" / "fore" | "four" | **[R]** | |
| 19 | "eight" / "ate" | "eight" | **[R]** | |
| 20 | "won" / "one" | "one" | **[R]** | |
| 21 | "b" / "p" / "d" / "v" | the variable letter | **[R]** | Voiced/voiceless stop confusion; `b^2 - 4ac` is the tutor's core formula |
| 22 | "x" / "eggs" / "ex" | `x` | **[R]** | |
| 23 | "n" / "and" / "en" | `n` | **[R]** | "a n plus b" vs "a and b" |
| 24 | "over" / "off of" / "of" | `/` | **[R]** | `math_grade.py:52` folds `over`/`by`/`upon` unconditionally |
| 25 | "by" (as multiply, Indian usage) vs "by" (as divide) | ✕ or ÷ | **[R]** | **"3 by 4" means 3/4 in Indian maths register; "3 by 4" can also mean 3×4 in "3 by 4 grid".** `math_grade.py:52` assumes divide always |
| 26 | "route"/"root"/"rout" outside maths | not maths at all | **[M]** `"the root cause"` → `"the sqrt cause"` | Over-application: the grammar must be domain-scoped |
| 27 | "power" / "powder" | "power" | **[R]** | |
| 28 | "cube" / "cubed" / "cubes" | `^3` | **[R]** | Inflection loss; `mathtext.fold_superscripts` (`mathtext.py:133-138`) shows the tutor speaks both |
| 29 | "square" / "squared" / "squares" | `^2` vs the shape | **[R]** | `"three square"` → `3 square` → **wrong** **[M]** |
| 30 | "half" / "have" | `1/2` | **[R]** | |
| 31 | "log" / "lock" / "locke" | `log` | **[R]** | |
| 32 | "mod" / "mode" / "mud" | modulus | **[R]** | |
| 33 | "arc" / "ark" | `arc` (arcsin, arc length) | **[R]** | |
| 34 | "theta" / "beta" / "zeta" | the correct Greek letter | **[R]** | Also 11 above |
| 35 | "vertex" / "vortex" | vertex | **[R]** | `vertex` is in `MATHS_PHRASES` (`cloud_stt.py:27`) |
| 36 | "co-efficient" / "coefficient" / "sufficient" | coefficient | **[R]** | In `MATHS_PHRASES` |
| 37 | "hypotenuse" / "hypothesis" | hypotenuse | **[R]** | Both in scope for a Class-10 tutor |
| 38 | "v" ↔ "w" | the variable / "very" | **[R]** grounded in **[S]** Indian-English phonology: the /v/–/w/ contrast is realised as a single labio-dental approximant [ʋ] in Educated Indian English ([Wiltshire, *Uniformity and Variability in the Indian English Accent*, CUP 2020](https://www.cambridge.org/core/elements/abs/uniformity-and-variability-in-the-indian-english-accent/4B11D2C82EF0D7E7A4E3FA1353634B25)) | |
| 39 | "three" → "tree", "theta" → "teta" | dental fricative as a stop | **[R]** grounded in **[S]** same source (dental fricatives substituted by corresponding stops in Indian English) | **"three"/"tree" hits the §9 worked example directly** |
| 40 | "ulta U" | inverted parabola | **[S]** docx §8 verbatim | Must **not** hit the NONSENSE gate (`perception/gates.py:96-121`) |
| 41 | "lakh"/"crore" numerals | 10^5 / 10^7 | **[R]** | `math_grade._ONES` (`:23-32`) tops out at `hundred` |
| 42 | "½", "⅓", "²", "³" typed/pasted | the maths value | **[M]** `½` → `1⁄2` (U+2044), `x²` → `x2` | Not a homophone but the same failure class |

**[I]** Rows 1–11, 26, 29, 38–40, 42 have hard evidence (spec, paper, production log, or a probe run
in this repo). Rows 12–25, 27–28, 30–37, 41 are reasoned from English phonology, Indian-English
register, and the tutor's own vocabulary (`MATHS_PHRASES` at `cloud_stt.py:21-28`; `SPOKEN_SYMBOLS` at
`mathtext.py:88-101`). Row 25 is the one I would flag hardest to ticket 14: it is a *register*
ambiguity specific to the deployment locale, and `math_grade.py:52` currently resolves it by fiat.

**[I]** A defensible corpus construction rule: **the grammar must accept every spoken form the tutor
itself emits.** `mathtext.to_spoken` (`mathtext.py:151-172`) is the exhaustive list of what the child
hears; anything the tutor can say, the child can say back. That gives the corpus a closed, auditable,
already-in-repo seed set independent of my guesses.

---

## 6. (d) What "auditable parse" means in practice

### 6.1 The precedent: MathML parallel markup

MathML is the standing answer to "keep the meaning alongside the rendering." MathML 4 §6 ("Annotating
MathML: semantics") defines `<semantics>`, `<annotation encoding="…">` and `<annotation-xml>`, and
§6.9 covers **Parallel Markup** — the mechanism that lets an author "maintain multiple representations
simultaneously — such as keeping presentation markup alongside content markup — within a single
document structure" ([W3C MathML 4](https://www.w3.org/TR/mathml4/)). **[S]**
Separately, §5 defines the `intent` attribute, which carries "information about the intended meaning
of the expression, mainly for guiding audio or braille accessible renderings." **[S]**

**[I]** The architectural lesson transfers even if MathML itself is not adopted: the artifact of record
holds **the original surface form and the interpreted form together, with the encoding of each named**,
so a reviewer can diff them. That is the whole of "auditable". It is not a log line.

### 6.2 What a reviewer actually needs to see

**[I] — this section is entirely my reasoning; no source prescribes a field list.**

For a human to reconstruct why *"three squared"* became `3^2`, the retained record must answer five
questions. Anything less and the reviewer is re-deriving, not auditing:

| Question | Field |
|---|---|
| What did the child actually say (as far as we know)? | `raw_transcript` — verbatim, pre-normalisation. §9: "Never overwrite the original audio/transcript provenance." |
| What else might they have said? | `alternatives[]` — the N-best list, with per-word confidence and time offsets where available (§4.1) |
| Which span was rewritten? | `span: [start_char, end_char]` into `raw_transcript` — so the rewrite is localisable, and so the "tap the word" UI has something to attach to |
| By what rule, and was there a competitor? | `derivation` — the rule chain / parse tree, **plus** `competing_derivations[]` when >1 existed. Lark's `_ambig` nodes give this directly **[S]** |
| Under what assumption? | `active_concept` + `grammar_version` — §9's "and the active concept"; the concept scopes the vocabulary, so the same words parse differently under different concepts and the record must say which was assumed |
| What was the outcome? | `outcome: ACCEPT \| REFUSE_AMBIGUOUS \| REFUSE_OUT_OF_GRAMMAR \| REFUSE_LOW_CONFIDENCE \| PASSTHROUGH` — a passthrough (no maths found) is a distinct, common, and legitimate outcome |

**[I]** Three properties the record must have, each of which the current code would violate:

- **Reversible.** `raw_transcript` + `span` + `derivation` must reconstruct the output. Today the
  rewrite is a `re.sub` chain (`math_grade.py:40-67`) with no intermediate state; the original is
  simply gone.
- **Idempotent-compatible.** CLAUDE.md requires `normalize_input` to stay idempotent because the
  Gemini perception call is memoized by normalized text (`perception/gemini_perception.py:151`,
  `:161-197`). A grammar that rewrites `3^2` and then re-parses `3^2` must reach a fixed point. **[I]**
  This is a real hazard for a grammar with both spoken and symbolic terminals, and is worth an explicit
  property test in ticket 14.
- **Refusal is a first-class outcome, not an exception.** `normalize_input` returns `str`
  (`input_processor.py:370`) and has no channel for "I refuse" — ticket 11 names this. `math_grade.grade`
  already models the third value correctly (`"correct" | "wrong" | None`, `math_grade.py:12-17`,
  `:111-143`) and is the shape to copy.

### 6.3 Where the artifact goes

**[I]** Two candidates already exist in the repo and ticket 11 should pick, not invent:
`trusted_observations` (where `stt_confidence` lives today,
`interaction_control/control.py:248`) or the evidence ledger
(`evidence/contracts.py:13`, `evidence/ledger.py:197-198`), which already suppresses writes on low
confidence and is already the audit surface for grading decisions. The ledger is the better fit for
anything a safeguarding lead or subject expert must later review (docx §13 control 3, cited in
ticket 14) — but that is a contract decision, not mine.

---

## 7. Open questions / could not verify

1. **`asia-south1` (Mumbai) feature matrix for `en-IN`.** The supported-languages page I read surfaced
   rows under `asia-southeast1` and `eu`. Google directs callers to the **Locations API** for the
   authoritative per-region matrix ([Regional availability](https://docs.cloud.google.com/speech-to-text/docs/locations)),
   and I could not execute that call. **Verify with a live `locations` call before choosing a model.**
   This matters because CLAUDE.md pins Vertex to `asia-south1`.
2. **How Svarah configured "Google (US)" vs "Google (India)".** The 30.0 % vs 20.7 % gap is real and
   published, but whether it reflects `language_code`, endpoint region, or both is not stated in the
   text I could read. Do not attribute the whole gap to `en-US` → `en-IN`.
3. **v1 deprecation status.** The v2 migration page states only that "Migration from the V1 API to the
   V2 API does not happen automatically. Minimal implementation changes are required." I found **no**
   statement that v1 is deprecated or has an end-of-life date. The only concrete supersession I found is
   at the field level: "When speech adaptation is set it supersedes the `speechContexts` field."
4. **v2 adaptation quota limits.** The quotas page I read gives v1 numbers (5,000 phrases / 100 chars
   per phrase / 100,000 chars total per request). I did **not** find the equivalent v2 limits, nor the
   custom-class item limits.
5. **Whether `WordInfo.confidence` is usable at all on `en-IN` + `latest_short`.** Documented as
   supported for `short`/`long` on `en-IN`, but carrying the "not guaranteed to be accurate… should not
   rely on it to be always provided" caveat, and explicitly degraded on chirp models. **Needs an
   empirical check on real child audio before any consequence gate is built on it.** This is exactly
   ticket 11's "the path is effectively untested on the input it exists for".
6. **SRE as a directly reusable grammar source.** Confirmed: SRE is math→speech, ships MathSpeak and
   ClearSpeak rule catalogues, localises via `sre-l10n` YAML, and includes a Hindi locale. **Not
   confirmed:** that there is an extractable symbol→spoken-form table. The rules are XPath
   transformations over a semantic tree. Treat "reuse SRE's catalogue" as an engineering task of unknown
   size, not a lookup.
7. **TalkMaths refusal semantics and coverage.** Confirmed architecture (Dragon → custom CFG → parse
   tree → MathML/LaTeX). I found **no** primary source stating how it signals refusal, its grammar
   coverage, or measured accuracy. The accessible copies are on academia.edu/ResearchGate, which I did
   not treat as primary.
8. **lark's dependency footprint.** I asserted "pure Python, no compiled deps" as inference from
   general knowledge; I did **not** verify it against lark's packaging metadata. Ticket 14's
   import-purity rule makes this worth a two-minute check.
9. **A published digit-sequence-specific ASR error rate.** I searched for a primary measurement showing
   numerals have higher error rates than ordinary words and did not find one I would cite; the closest
   is Svarah's qualitative entity observation. The maths-specific numbers (MathSpeech, Speech-to-LaTeX)
   are solid and probably sufficient.
10. **Exact MathML 4 subsection numbers.** The fetch reported `<semantics>` at §6.5, `<annotation>` at
    §6.6, `<annotation-xml>` at §6.7, Parallel Markup at §6.9, `intent` at §5. I am confident in the
    top-level structure (§5 intent, §6 semantics/annotation) and less so in the third digit.
11. **Whether the two `voice/cloud_stt.py` copies are supposed to diverge.** They do: the root copy has
    no `TranscriptionEvidence` and returns bare strings, so it discards confidence entirely. This looks
    like drift rather than design, but it is ticket 13's territory (dead code and seam disposition), not
    this ticket's.

---

## 8. Sources

**Repo (file:line) — verified during this research:**
- `cloud_run_service/cognitive_input_processor/input_processor.py` — `normalize_input` `:370-410`
  (NFKC `:395`, zero-width `:399`, punct/space `:401-406`); regex constants `:244-248`; config flag
  `:221`; `detect_student_problem` `:590-624` (`_EQUATION_RE` `:572`, `_EXPRESSION_RE` `:578`);
  `extract_surface_cues` `:670`; `ingest` `:696-704`.
- `cloud_run_service/cognitive_input_processor/tests/test_input_processor.py:23-29` — the test that
  documents and works around the NFKC exponent loss.
- `cloud_run_service/mathtext.py` — module doctrine `:1-26`; primitives `:46-80`; `SPOKEN_SYMBOLS`
  `:88-101`; `GREEK` `:103-109`; `fold_superscripts` `:133-138`; `to_spoken` `:151-172`;
  `to_panel` `:174-189`; `PANEL_GLYPHS` `:194`; `to_panel_unicode` `:215-243`; `to_question` `:247-258`.
- `cloud_run_service/math_grade.py` — doctrine + three-valued contract `:1-17`; `_ONES` `:23-32`;
  `normalize` `:40-67` (sqrt `:49-50`, minus `:51`, fraction `:52`, equals `:53`, tens `:54-66`);
  `_to_value` `:69-84`; `_values` `:86-95`; `grade` `:111-143`.
- `cloud_run_service/voice/cloud_stt.py` — rationale for `en-US` and the "railroads" observation `:1-8`;
  `MATHS_PHRASES` `:21-28`; `TranscriptionEvidence` `:31-35`; ctor defaults `:38-43`;
  `recognize_pcm_evidence` `:49-80` (config `:55-62`, `alternatives[0]` `:66`, averaging `:68-71`);
  shared config `:82-95`; streaming `:104-158`. Root duplicate: `voice/cloud_stt.py` (no confidence).
- `cloud_run_service/wini_server.py:607-614` — where `stt_confidence` is produced; `:629` trusted-input gate.
- `cloud_run_service/interaction_control/control.py:248-252` — the single float gate, `1.0` default;
  `:670-722` `_low_confidence_result`.
- `cloud_run_service/evidence/ledger.py:197-198`, `cloud_run_service/assessment_evidence/interface.py:116-117`
  — the two other consequence gates on the same float.
- `cloud_run_service/perception/gates.py:96-121` `is_nonsense`, `:124-149` `gate()` — what a refusal must
  *not* be routed to (docx §8).
- `cloud_run_service/perception/gemini_perception.py:151`, `:161-197` — normalize-then-memoize, the
  idempotency constraint.
- `math_grade` consumers: `cloud_run_service/evidence/grading.py:35-36`,
  `cloud_run_service/tutor_loop.py:859-860`, `cloud_run_service/items/verify.py:17-18`, `eval/grader_eval.py:78`.
- Requirements source: `docs/archive/AI_Tutor_Child_Safe_Interaction_Specification.docx` §8, §9.
- Sibling tickets: `.scratch/deterministic-input-layer/issues/10`, `/11`, `/14`; `map.md`.

**Google Cloud Speech-to-Text (official docs):**
- Speech adaptation, v2 (PhraseSet/CustomClass, inline vs resource, boost ceiling 20, class-token silent-ignore caveat):
  https://docs.cloud.google.com/speech-to-text/v2/docs/speech-adaptation
- Model adaptation ("Class availability varies by transcription model and language"):
  https://docs.cloud.google.com/speech-to-text/docs/adaptation-model
- Class tokens ($OPERAND, $OOV_CLASS_DIGIT_SEQUENCE, $OOV_CLASS_ALPHA_SEQUENCE, …):
  https://docs.cloud.google.com/speech-to-text/docs/class-tokens
- v2 recognizers reference (`SpeechAdaptation.phraseSets[]`, `phraseSet` vs `inlinePhraseSet`):
  https://docs.cloud.google.com/speech-to-text/v2/docs/reference/rest/v2/projects.locations.recognizers
- v2 RPC reference (`RecognitionFeatures` field list):
  https://docs.cloud.google.com/speech-to-text/v2/docs/reference/rpc/google.cloud.speech.v2
- v1 `RecognitionConfig` (speechContexts superseded by adaptation; boost 0–20; maxAlternatives 0–30;
  enableWordConfidence; enableWordTimeOffsets; model values):
  https://docs.cloud.google.com/speech-to-text/docs/reference/rest/v1/RecognitionConfig
- v1 `speech.recognize` (**the confidence caveat**: "set only for the top alternative… is not guaranteed
  to be accurate and users should not rely on it to be always provided"):
  https://docs.cloud.google.com/speech-to-text/docs/reference/rest/v1/speech/recognize
- Chirp 2 ("Class tokens or custom classes are not supported"; "The API returns a value, but it isn't
  truly a confidence score"): https://docs.cloud.google.com/speech-to-text/docs/models/chirp-2
- Chirp 3 (same confidence caveat; up to 1,000 adaptation phrases):
  https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3
- V2 supported languages (the `en-IN` feature rows):
  https://docs.cloud.google.com/speech-to-text/docs/speech-to-text-supported-languages
- Regional availability / Locations API (the authoritative per-region matrix):
  https://docs.cloud.google.com/speech-to-text/docs/locations
- Quotas & limits (5,000 phrases / 100 chars per phrase / 100,000 chars per request):
  https://docs.cloud.google.com/speech-to-text/quotas
- v1→v2 migration: https://docs.cloud.google.com/speech-to-text/v2/docs/migration

**Grammars and refusal semantics:**
- Lark, Parsers (Earley O(n^3); `ambiguity='explicit'`; LALR + contextual lexer):
  https://lark-parser.readthedocs.io/en/stable/parsers.html
- Lark, Handling Ambiguity (`_ambig` nodes, "fruit flies like bananas"):
  https://lark-parser.readthedocs.io/en/stable/examples/fruitflies.html
- Lark, Working with the SPPF: https://lark-parser.readthedocs.io/en/latest/forest.html
- Bryan Ford, *Parsing Expression Grammars: A Recognition-Based Syntactic Foundation*, POPL 2004
  ("solves the ambiguity problem by not introducing ambiguity in the first place"; "prioritized choice"):
  https://bford.info/pub/lang/peg/ — PDF: https://bford.info/pub/lang/peg.pdf —
  ACM DL: https://dl.acm.org/doi/10.1145/964001.964011
- SymPy parsing module (`parse_expr` **"uses `eval`, and thus shouldn't be used on unsanitized input"**;
  `standard_transformations`; `implicit_multiplication`; `convert_xor`; `parse_latex` experimental and
  "may fail silently on incomplete expressions without warnings"):
  https://docs.sympy.org/latest/modules/parsing.html

**Spoken-mathematics systems and specifications:**
- Speech Rule Engine (README — XML→speech, MathSpeak/ClearSpeak/Nemeth):
  https://github.com/Speech-Rule-Engine/speech-rule-engine
- speechruleengine.org (locales incl. Hindi; `sre-l10n` bespoke YAML rule format):
  https://speechruleengine.org/ — rule format: https://speech-rule-engine.github.io/sre-l10n/yaml.html —
  localisation repo: https://github.com/Speech-Rule-Engine/sre-l10n/
- MathJax accessibility extensions (ClearSpeak default, MathSpeak selectable):
  https://docs.mathjax.org/en/latest/basic/a11y-extensions.html
- Frankel, Brownstein & Soiffer, *Development and Initial Evaluation of the ClearSpeak Style for
  Automated Speaking of Algebra*, ETS Research Report RR-16-13:
  https://files.eric.ed.gov/fulltext/ED570857.pdf
- TalkMaths (ASR → customized CFG → parse tree → MathML/LaTeX): https://talkmaths.sourceforge.net/
- W3C MathML 4 (§5 `intent`; §6 `semantics` / `annotation` / `annotation-xml`; Parallel Markup):
  https://www.w3.org/TR/mathml4/
- W3C SSML 1.1 (`say-as` / `interpret-as`; **no normative maths content** — "It does not enumerate the
  possible values for the attributes"): https://www.w3.org/TR/speech-synthesis11/

**Measured error rates:**
- Hyeon et al., *MathSpeech: Leveraging Small LMs for Accurate Conversion in Mathematical
  Speech-to-Formula* (AAAI 2025) — Whisper/Canary WER 29.5–35.2 % on formula speech; the
  "side"/"école"/"Posing" error examples: https://arxiv.org/html/2412.15655v1 —
  AAAI: https://ojs.aaai.org/index.php/AAAI/article/download/34595/36750
- *Speech-to-LaTeX: New Models and Datasets for Converting Spoken Equations and Sentences* —
  66k+ samples; 27.7–30.0 % equation CER; "one over x plus two" scope ambiguity; kappa/varkappa:
  https://arxiv.org/abs/2508.03542 — HTML: https://arxiv.org/html/2508.03542v1
- Wei, Wang, Kim & Chen, *Towards Spoken Mathematical Reasoning: Benchmarking Speech-based Models over
  Multi-faceted Math Problems* (Spoken-MQA) — **"32 out of 100 problems are judged to be potentially
  ambiguous to humans without visual or text context"**; "the magnitude of z minus w":
  https://arxiv.org/abs/2505.15000 — HTML: https://arxiv.org/html/2505.15000v1
- Javed et al., *Svarah: Evaluating English ASR Systems on Indian Accents* — Google (US) 30.0 %,
  Google (India) 20.7 %, Azure (US) 20.9 %, Azure (India) 21.3 %, Whisper-large 7.2 % WER; the
  entity-recognition observation: https://arxiv.org/abs/2305.15760 —
  https://ar5iv.labs.arxiv.org/html/2305.15760 — https://github.com/AI4Bharat/Svarah
- Diwan et al., *MUCS 2021: Multilingual and Code-Switching ASR Challenges for Low Resource Indian
  Languages* (Interspeech 2021) — Hindi-English / Bengali-English baselines 28.45–34.08 % WER:
  https://arxiv.org/pdf/2104.00235 —
  https://www.isca-archive.org/interspeech_2021/diwan21_interspeech.html —
  dataset: https://www.openslr.org/104/
- Javed et al., *IndicSUPERB: A Speech Processing Universal Performance Benchmark for Indian languages*
  (Kathbath, 1,684 h, 12 languages): https://arxiv.org/pdf/2208.11761 —
  https://github.com/AI4Bharat/IndicSUPERB
- Wiltshire, *Uniformity and Variability in the Indian English Accent*, Cambridge University Press, 2020
  (Indian-English consonant features: /v/–/w/ realised as [ʋ]; dental fricatives as stops):
  https://www.cambridge.org/core/elements/abs/uniformity-and-variability-in-the-indian-english-accent/4B11D2C82EF0D7E7A4E3FA1353634B25
