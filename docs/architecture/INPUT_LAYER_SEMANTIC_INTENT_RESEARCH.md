# Input Layer & Interaction Control (Layer 1) — Semantic Intent & the Negation Acid Test (Research)

**Status: research (dated; the design decisions this fed are now resolved — ticket 07 decided
the safety detector architecture, ticket 13 retired the SemanticClassifier seam entirely).**
**Scope:** what the regex input layer does, why it is unreliable, whether it is even
in the live path, what MiniLM assets already exist, whether MiniLM can be reused to
give the intent layer *semantic* understanding, and — the acid test — whether any of
this reliably distinguishes **"I do like math"** from **"I do not like math"**.
§7 extends the analysis to **Layer 1 (Interaction Control)** and the four
developer-identified problems there — safety detection, STT-confidence quality, social
short-circuiting, and the fall-through to the learning pipeline.

**Bottom line up front:**
1. The regex layer (`HeuristicSemanticClassifier` + the `_*_RE` patterns) is keyword
   substring matching with **zero negation handling**. It fires identically — and
   wrongly — for "I do like math" and "I do not like math".
2. **It is largely NOT in the live path anymore.** Since Part 11, perception (intent +
   cognitive signals + concept) is one structured **Gemini 2.5 Flash** call. Of the whole
   `InputProcessor`, the live pipeline calls only `normalize_input()` and
   `detect_student_problem()`; the regex/keyword **signal + candidate-concept layer is
   uncalled**.
3. MiniLM (`all-MiniLM-L6-v2`, 384-dim) is already loaded and warm — for retrieval
   `S_rel`, the exemplar cognitive classifier, the concept resolver, and HOPE.
4. **Plain MiniLM embedding + cosine over exemplars will NOT reliably solve negation.**
   This is a well-documented property of sentence embeddings: "I like X" and "I do not
   like X" sit very close in cosine space. What *does* work: a **supervised head trained
   on negated pairs**, an NLI model, or the **Gemini perception call that already runs**
   (an autoregressive model reading the whole sentence at temperature 0 — the current
   live answer).

---

## 1. Current state — what the input layer does, and the negation failure

File: `cloud_run_service/cognitive_input_processor/input_processor.py`.

### 1.1 Two intended layers
The module docstring frames it as (1) deterministic normalization and (2) "multi-signal
semantic tagging" that returns per-signal scores (`input_processor.py:1-18`,
`InputSignalScores` at `:33-49`, `ProcessedInput` at `:52-72`).

### 1.2 The `SemanticClassifier` plug-in seam
There is an explicit pluggable interface — a `Protocol` — precisely so a real semantic
classifier can replace the fallback:

> "In the production stack, this can be implemented with an embedder-backed exemplar
> classifier (for example, MiniLM + cosine over exemplar phrases)."
> — `input_processor.py:80-94`

The default injected implementation is `HeuristicSemanticClassifier`
(`input_processor.py:97-195`, wired as the default in `InputProcessor.__init__` at
`:277-283`). It is self-described as "not a replacement for the real semantic
classifier" (`:98-103`).

### 1.3 What actually decides the signals: substring keyword matching
- `HeuristicSemanticClassifier._score_keywords` returns 0.8 if **any** marker string is a
  substring of the lowercased text (`input_processor.py:173-178`). Marker sets are literal
  word lists: `TRANSFER_MARKERS` includes bare `"like"` (`:121-124`); `CONFUSION_MARKERS`,
  `CURIOUSITY_MARKERS`, etc. are the same shape.
- The parallel regex layer `_heuristic_signal_scores` (`:421-453`) fires fixed scores when a
  `_*_RE` pattern matches. `_TRANSFER_RE` matches bare `like`:
  `\b(similar|same as|like|can i use|another way|instead|previous chapter|previous topic)\b`
  (`input_processor.py:256-259`).
- `_merge_scores` (`:455-474`) takes the **max** of the heuristic and semantic scores, so a
  regex hit alone is enough to raise a signal.
- No pattern, marker set, or code path anywhere in the file inspects negation
  (`not`, `n't`, `never`, `don't`) relative to the word it negates. `_CONFUSION_RE` lists
  `don't understand` as a *positive* confusion phrase (`:252-255`) — negation words appear
  only inside fixed idioms, never as scope-flipping operators.

### 1.4 Concrete trace — the acid test
Analysis lowercases the text (`process` at `:308`), then both layers run.

**"I do like math"**
- Regex `_TRANSFER_RE` finds `like` → `transfer_attempt = 0.8` (`:438`).
- `HeuristicSemanticClassifier` finds `"like"` in `TRANSFER_MARKERS` → `transfer_attempt = 0.8`.
- `_QUESTION_RE` also matches `do` (`:240-243`) → `question = 0.7` (`:426-427`).
- Emotional/engagement sentiment: **not detected** (no positive-affect signal exists).

**"I do not like math"**
- Regex `_TRANSFER_RE` still finds `like` → `transfer_attempt = 0.8`. **Identical.**
- Keyword classifier still finds `"like"` → `transfer_attempt = 0.8`. **Identical.**
- `_QUESTION_RE` still matches `do` → `question = 0.7`. **Identical.**
- The dislike / disengagement sentiment: **not detected.**

**Verdict:** the two utterances produce the *same* signal vector, and the one signal they
do fire (`transfer_attempt`) is wrong for both — neither is a transfer attempt; one is
positive affect toward the subject, the other is negative affect. The layer is unreliable
because it matches keywords as substrings with no notion of sentence meaning, sentiment,
or negation scope. This is the failure the user is describing.

### 1.5 One deterministic cue is genuinely robust (and deliberately narrow)
`detect_student_problem` (`input_processor.py:579-611`) is a separate, tighter detector
("did the student bring an instance to be worked out?") built on `_EQUATION_RE` /
`_EXPRESSION_RE` / `_SOLVE_VERB_RE` + numerals (`:561-577`). Its docstring is explicit that
it must stay deterministic and must **not** depend on a model that might score a word
problem as a transfer attempt (`:549-556`). This one is fit for purpose and is retained —
see §2.

---

## 2. Live-path reality — has Gemini perception superseded InputProcessor?

**Yes, for intent and signals.** The regex signal layer is essentially dead code on the
live path.

### 2.1 What the runtime injects
`TutorLoop` builds ONE `GeminiPerception` and injects it as **both** the classifier and the
resolver of `CognitiveAnalyzer` (`cloud_run_service/tutor_loop.py:1258-1261`;
identical in root `tutor_loop.py:1258-1261`). `PERCEPTION_BACKEND=qwen_heads` is retired —
a stale value prints a notice and uses Gemini (`tutor_loop.py:1240-1242`). This matches the
CLAUDE.md mandate (default `PERCEPTION_BACKEND=gemini`, Stage 6, 2026-07-02).

### 2.2 What `CognitiveAnalyzer.analyze()` actually calls
`cognitive_analyzer/analyzer.py:227-250`:
- `self.processor.normalize_input(text)` — the deterministic cleanup half of InputProcessor
  (`:229`).
- `self.classifier.classify(...)` and `self.resolver.resolve(...)` — these are
  **GeminiPerception**'s methods, not the exemplar heads (`:230-231`).
- `self.processor.detect_student_problem(text)` — the one narrow cue kept (`:240`).

The code comment states it directly:

> "This is the one part of InputProcessor the live pipeline still needs (audit D-1) — the
> signal/candidate-concept layer it also computes is Gemini's job since Part 11, and stays
> uncalled." — `analyzer.py:236-239`

So `InputProcessor.process()`, `_heuristic_signal_scores`, `HeuristicSemanticClassifier`,
and `_extract_candidate_concepts` are **not invoked at runtime**. Only `normalize_input`
and `detect_student_problem` are.

### 2.3 The front door (intent routing)
Intent is decided before the analyzer:
1. Deterministic gates run first — SAFETY + NONSENSE, pure/model-free
   (`perception/gates.py:1-17`, called in `perception/interface.py:100-103`).
2. Otherwise `GeminiPerception.route(text, session)` returns the intent
   (`gemini_perception.py:512-528`; wired via `classifier.route(...)` in
   `tutor_loop.py:2111` and `:2161`). Intents are the eight in `route.py:14-24`.

All of route/classify/resolve share **one memoized Gemini call per utterance**
(`gemini_perception.py:161-197`).

### 2.4 Data-flow summary (live)
```
utterance
  → gates(text)                      # SAFETY / NONSENSE, deterministic, model-free
  → GeminiPerception.route(text)     # intent (8-way)         ── one memoized Gemini call
  → (if LEARNING) CognitiveAnalyzer.analyze():
        normalize_input(text)                       # InputProcessor (kept)
        GeminiPerception.classify(text) → signals   # 38-label signal_scores from Gemini
        GeminiPerception.resolve(text)  → concept   # Gemini pick + §5.5 MiniLM cross-check
        detect_student_problem(text)                # InputProcessor deterministic cue (kept)
  → derive_* / apply_deltas                          # unchanged state math
```
`candidate_concepts` in the *live* flow come from MiniLM anchor similarity **inside**
GeminiPerception (`_concept_candidates`, `gemini_perception.py:216-236`) as hints to the
Gemini prompt — not from `InputProcessor._extract_candidate_concepts`.

**Implication for the user:** the "unreliable regex intent layer" is already replaced on
the live path by a model that reads whole sentences. If the observed unreliability is
coming from production, check whether the deployment is actually on the Gemini path or is
falling back (the `_degraded`/`fallback` route, `interface.py:227-295`,
`gemini_perception.py:407-413`) — a degraded turn yields neutral signals, not regex ones.
The `SemanticClassifier` seam and `HeuristicSemanticClassifier` remain relevant only as (a)
the offline/no-network fallback and (b) the documented slot where a *local* semantic
classifier would go if one is ever wanted without a Gemini round-trip.

---

## 3. MiniLM inventory — what already exists and is warm

**Model:** `sentence-transformers/all-MiniLM-L6-v2`, pinned in one constant reused
everywhere: `cognitive_classifier/classifier.py:34`.
**Dimension:** 384. First-party model card: "Maps sentences & paragraphs to a **384
dimensional** dense vector space"; max input 256 word pieces (training capped at 128); the
vector "captures the semantic information" for "information retrieval, clustering or
sentence similarity" (HuggingFace model card, see Sources). The shipped bank confirms 384
(`classifier.py:4` — `bank_embeddings.npy float32 [n_bank, 384]`).

**One shared instance, warm-loaded once:**
- `GeminiPerception.embedder` is a lazily-loaded, lock-guarded single `SentenceTransformer`
  (`gemini_perception.py:114-133`), explicitly "one model in VRAM," shared with HOPE and the
  chunk index (`:17-18`, and HOPE sharing in `tutor_loop.py:1265-1271`). Cloud Run runs
  `min-instances=1` to keep it warm (CLAUDE.md).

**Current MiniLM jobs:**
| Job | Where | What MiniLM does |
|---|---|---|
| Retrieval relevance `S_rel` | chunk index / `embed()` (`gemini_perception.py:135-144`) | query/chunk embeddings for retrieval |
| Exemplar cognitive classifier | `cognitive_classifier/classifier.py` | 384-dim embeddings + weighted k-NN / evidence / logreg over an exemplar bank → 38 signal labels |
| Concept resolver | `concept_resolver/resolver.py:78-80` | embed utterance, match against anchor + bank embeddings → concept id |
| Concept candidate hints (§5.5) | `gemini_perception.py:216-236` | top-K catalog concepts by anchor cosine, fed to the Gemini prompt |
| §5.5 cross-check resolver | `gemini_perception.py:436-480` | re-uses the shared embedder to confirm Gemini's concept pick |
| HOPE detectors (KI/KT/CT) | `hope_detector/detector.py:21,46-48` | teacher-calibrated detectors on MiniLM embeddings |

Per CLAUDE.md, MiniLM stays local/in-container for retrieval + HOPE; only the
*perception* (signal/concept/intent) moved to Gemini.

---

## 4. Can MiniLM be reused for intent? Yes — but not with cosine alone

### 4.1 The honest answer on negation
The approach the user is hoping for — **MiniLM embed + cosine over exemplar phrases** —
will **NOT reliably distinguish "I do like math" from "I do not like math."** This is a
known, measured property of sentence embeddings, not a tuning problem:

- The model is trained with a **contrastive objective for semantic similarity** (model
  card), which rewards putting topically-similar sentences close together. "I like math"
  and "I do not like math" are lexically near-identical and topically identical, so they
  land very close in cosine space; the single scope-flipping word `not` barely moves the
  vector.
- Independent research is blunt about this: adding "not" — flipping the meaning — "barely
  affects similarity scores, with routinely high scores above 0.95 for complete opposites,"
  and for negation/antonym pairs the average cosine similarity is *higher* than for pairs
  that are genuinely semantically similar (see Sources: Nature 2025; arXiv survey).
- Antonyms/negations "appear in similar contexts, thus their word embeddings exhibit high
  similarity" — the same effect at sentence level.

So a cosine-over-exemplars `SemanticClassifier` dropped into the seam would fail the acid
test in the same way the regex does (both would tag the utterance by the shared topic/
keyword, missing the polarity flip). It would be *better* than regex at paraphrase and
synonymy, but not at negation.

### 4.2 What it takes to make MiniLM handle negation
Negation is learnable **on top of** MiniLM if you add a supervised decision boundary and
train it on **minimal negated pairs**:

- **Supervised head on frozen embeddings, trained with negated examples.** The exemplar
  classifier *already* supports a logistic head over the 384-dim embeddings
  (`score_labels_logreg`, `classifier.py:85-88`; live config `scorer: "evidence+logreg"`,
  `thresholds.json:2`). A linear/MLP head can learn that the `not`/`n't` direction in
  embedding space separates the classes — **but only if the training bank contains the
  negated pairs.** MiniLM embeddings do encode the presence of "not" as *some* direction;
  cosine-to-exemplars ignores that direction, a trained head can weight it. This is the
  minimum viable fix that reuses the warm MiniLM.
- Requires: authoring paired exemplars ("I do like math" / "I do not like math",
  "this makes sense" / "this doesn't make sense", …) with opposite labels, adding them to
  the exemplar bank, and rebuilding (`python -m cognitive_classifier.build_bank`).
- Caveat: even trained heads on MiniLM handle negation *imperfectly* (Sources) — good
  enough for coarse sentiment/engagement signals, not a guarantee at the tails.

### 4.3 Alternatives that handle negation natively
- **NLI/entailment model** (e.g. an MNLI cross-encoder): scores "premise ⇒ hypothesis" and
  is trained on contradiction, so "I do not like math" *contradicts* "the student likes
  math." Handles negation far better than bi-encoder cosine, at higher per-call cost.
- **The Gemini perception call already in production.** An autoregressive LLM reading the
  full utterance at `temperature=0` with a response schema (`gemini_perception.py:344-367`)
  handles negation as a matter of course — this is exactly why perception was moved to it.
  It is already wired, warm-client-memoized, and hard-timeout-guarded.

---

## 5. Options comparison

| Option | Semantic understanding | Handles negation ("do like" vs "do not like") | Latency / cost | Reuses existing assets | Effort |
|---|---|---|---|---|---|
| **(a) Improved regex/keywords** | No — surface patterns | **No.** Even with `not`-lookarounds it stays brittle per phrase; scope + paraphrase still break it | Fastest, free, local | N/A (this is the thing being replaced) | Low, low payoff |
| **(b) MiniLM embed + cosine over exemplars** | Yes for paraphrase/synonymy | **No — fails the acid test.** "like" vs "not like" cosine ~identical (contrastive-similarity objective) | ~1 embed call, local, warm | Yes — the shipped embedder + bank | Low (drop into `SemanticClassifier` seam) |
| **(c) MiniLM + supervised head trained on negated pairs** | Yes | **Partially yes**, if the bank includes minimal negated pairs; imperfect at tails | ~1 embed + tiny matmul, local, warm | Yes — reuses embedder + existing `logreg` scorer path | Medium (author paired data, rebuild bank) |
| **(d) Reuse Gemini perception layer (live default)** | Yes, strong | **Yes** — LLM reads whole sentence at temp 0 | Network round-trip; hard-timeout + memoized; Cloud Run min-instances=1 | Yes — already the live path | None new (already built) |
| **(e) Small NLI/entailment model** | Yes | **Yes** — trained on contradiction | Heavier local model (cross-encoder); no Gemini dependency | New model to add + host | Medium/High |

---

## 6. Recommendation

Fit to this repo's cloud-Gemini + warm-MiniLM architecture and the `SemanticClassifier`
seam:

1. **For the live intent/signal decision: keep using the Gemini perception call — it
   already passes the acid test and is the current default.** The "unreliable regex layer"
   is not the production intent path; the fix the user wants is largely *already shipped*
   (§2). First action item: confirm the running deployment is on the Gemini route and not
   silently degrading to the neutral fallback (`interface.py:227-295`) — that would explain
   perceived unreliability and is a config/observability problem, not a classifier problem.

2. **Do NOT wire a plain MiniLM-cosine classifier into the `SemanticClassifier` seam
   expecting it to fix negation.** It will not (§4.1). If a *local, no-network* semantic
   classifier is wanted (offline/fallback quality, or to cut Gemini calls on high-volume
   signal tagging), use **option (c): MiniLM + a supervised head trained on minimal negated
   pairs**, reusing the exemplar bank's existing `evidence+logreg` path
   (`classifier.py:85-88`, `thresholds.json`). Author paired exemplars with opposite labels
   for the affect/engagement signals (like/dislike, makes-sense/doesn't-make-sense,
   ready/not-ready), add them to the bank, and rebuild
   (`python -m cognitive_classifier.build_bank`). Then this classifier can back the
   `MiniLMSemanticClassifier` adapter that already exists for the seam
   (`classifier.py:204-217`). Validate specifically on held-out negated pairs, since
   MiniLM heads are only *partially* reliable on negation.

3. **Retain `detect_student_problem` and the deterministic gates as-is** — they are the
   parts of the deterministic layer that are actually fit for purpose (§1.5, §2.3).

4. If, later, a stronger *local* polarity guarantee is needed without Gemini, evaluate a
   small NLI cross-encoder (option e) rather than pushing bi-encoder cosine past its
   documented limits.

**One-line acid-test answer for the user:** the MiniLM-cosine idea will *not* reliably tell
"I do like math" from "I do not like math"; the LLM (Gemini) perception layer already in
this system does, and a MiniLM + supervised head trained on negated pairs is the cheaper
local option — plain cosine over exemplars is not.

---

## 7. Interaction Control (Layer 1) — the four developer-identified problems

Layer 1 is `cloud_run_service/interaction_control/control.py`
(`InteractionControl._control`, `:196-456`). It governs admission, safety, STT-quality,
social/session routing, topic shifts, and hand-off to the learning pipeline. For every
turn it runs, in order:

1. **Deterministic front gate** — `_front_gate` = `perception.gate`, injected as
   `deterministic_route` (`tutor_loop.py:2109`; used at `control.py:223-227`). Pure regex,
   **SAFETY + NONSENSE only**, model-free, runs *before* any model call
   (`perception/gates.py:124-149`).
2. **STT-confidence gate** — numeric `stt_confidence < stt_write_confidence_min` (0.60)
   (`control.py:248-260`, floor at `:150`).
3. **Gemini perception route** — `perception_route` / `perception.route`, the real semantic
   intent classifier (SOCIAL, LEARNING, …) (`control.py:300-304`, `route.py:14-24`).

The unifying finding: **the coarse, unreliable decisions in Layer 1 are the ones made by
steps 1–2 (regex + a numeric threshold) *ahead of*, or *instead of*, the semantic step 3 —
and, in one case (§7.3), a semantic signal Gemini already emits is simply never read.**

### 7.1 Problem 1 — Safety detection is a regex lexicon
**Root cause.** SAFETY is `_SAFETY_PATTERNS`, ~40 hand-written regexes
(`gates.py:35-62`), matched by `is_safety()` (`:76-78`). Anything phrased outside the
lexicon slips the gate. This is the same class of failure as the input layer: keyword/
pattern matching with no whole-sentence semantics.

**Constraint that shapes the fix (do not violate).** The deterministic SAFETY gate must be
**near-total on its own**; a model "may only *add* recall, never remove it"
(`gates.py:5-9`; CLAUDE.md Part 11 §4.2). The child-safety guarantee must not depend on a
model being available, fast, or correct.

**Solution.** Add a semantic safety classifier as an **additive OR layer**, never a
replacement:
`is_safety(text) OR semantic_safety(text) > τ`. Options, cheapest first:
- **MiniLM + a supervised safety head** trained on paraphrased self-harm/abuse/danger
  disclosures — reuses the warm embedder (§3) and the existing `evidence+logreg` path
  (`classifier.py:85-88`); local, no extra network hop. Best fit.
- Lean harder on the **Gemini `safety` flag** already produced by perception
  (`gemini_perception.py` schema, `route.safety_alert`) — but it is a network call and
  already only *adds* recall; a local head is a stronger, always-available net.
- Measure gate recall directly after any change: `python -m eval.perception_eval --gates`
  (the lexicon previously scored 0.75 recall — see CLAUDE.md gotcha).

### 7.2 Problem 2 — STT-confidence quality is untested on real audio
**Root cause.** `control.py:248-252` reads `stt_confidence` from
`turn_input.trusted_observations` and compares to 0.60. In **text testing there is no STT
confidence**, so it defaults to `1.0` (`:249`) and the gate never fires — meaning input
"quality" is, in text mode, judged *only* by the **NONSENSE regex** (`gates.py:96-121`).
That matches the developer's observation ("testing is done for text inputs but that checks
the regex for classifying quality").

**Assessment.** The numeric gate itself is sound; the gap is that the real audio-confidence
path is **never exercised**. The `_low_confidence_result` re-prompt branch
(`control.py:670-722`) is only reachable with a genuine sub-0.60 confidence value.

**Solution.** Build an **audio-confidence test harness** that feeds real STT confidence
values (from Cloud STT word/utterance confidence) through `trusted_observations`, and
assert on the CONFIRM_LOW_CONFIDENCE re-prompt. No production-code change to the gate is
required — this is a test-coverage / observability gap, not a logic defect. (Separately, if
"quality" should also catch *confident-but-garbled* transcripts, that is a semantic check,
not a confidence threshold — candidate for the same NONSENSE/perception path, not the STT
score.)

### 7.3 Problem 3 — "hii, explain area of circle" is dropped as pure social
**Root cause — a genuine bug, confirmed by grep.** Gemini's perception schema *already*
emits an `also_learning` flag — defined as "a non-LEARNING turn that also carries a maths
ask" (`route.py:36`), produced at `gemini_perception.py:354,397,517`. But **`also_learning`
is never read** in `control.py` or the coordinator (grep: only produced in
`perception/*`, never consumed downstream). So a greeting-plus-ask is routed to SOCIAL,
answered by the scripted persona reply in `_nonlearning_reply` (`control.py:933-975`, which
returns `spec["scripted"]` for SOCIAL when present), and **the maths ask is silently
dropped**.

Note: the *classification* is Gemini's (semantic), not a keyword match — but the
user-visible outcome is exactly the "found a greeting, ignored the rest" behaviour the
developer describes, because the layer discards the part of Gemini's verdict that captures
the rest of the sentence.

**Solution.** Consume `also_learning` in the routing decision (`control.py:356-371`, the
`route.primary != "LEARNING"` branch): when `primary in {SOCIAL, EMOTIONAL}` **and**
`also_learning` is true, emit a brief social acknowledgement *and* fall through to the
learning pipeline (or split the turn: short social preface + `CONTINUE_LEARNING`). This
needs **no new model** — the semantic signal is already computed; the layer just has to
honour it. Add an interaction-control test for "greeting + maths ask" (see existing
patterns in `interaction_control/tests/test_interaction_control.py`).

### 7.4 Problem 4 — Non-keyword sentences fall through to Phase 2 (learning)
**Root cause.** By design: when no gate fires, `gate()` returns `None`
(`gates.py:139-149`) and the turn passes to `GeminiPerception.route`, then (if LEARNING)
into the analyzer. This is the **correct** contract — the deterministic gates are
deliberately narrow (SAFETY high-recall, NONSENSE conservative) so a terse real answer
("5", "x=2") is never mis-gated (`gates.py:8-16`, `:96-121`).

**Assessment.** This is a problem only *because* of §7.1 and §7.3: the gate's upstream
decisions are too coarse (safety) or the semantic verdict is under-used (social). Fixing
§7.1 (semantic safety net) and §7.3 (honour `also_learning`) makes the fall-through behave
correctly; no change to the fall-through itself is warranted.

### 7.5 Layer-1 recommendation
| # | Problem | Root cause | Fix | Effort |
|---|---|---|---|---|
| 3 | Social short-circuit drops maths ask | `also_learning` produced but never consumed (`control.py`) | Read `also_learning`; social ack + fall through to learning | **Low — highest value** (signal already exists) |
| 1 | Safety = regex lexicon | `_SAFETY_PATTERNS` (`gates.py:35-62`) | Additive semantic safety net (MiniLM + safety head); never downgrade the deterministic floor; re-measure `--gates` recall | Medium |
| 2 | STT quality untested on audio | numeric gate never exercised in text tests (`control.py:248-252`) | Audio-confidence test harness feeding real `stt_confidence` | Low (test-only) |
| 4 | Fall-through to learning | intended (`gates.py:139-149`) | No change; resolves once #1/#3 land | None |

Ordering rationale: **#3 first** — it is a real bug whose fix uses a signal the system
already computes; **#1 next** — highest safety value, but constrained by the
"never-downgrade" rule; **#2** is test coverage; **#4** is emergent and needs no direct
change.

---

## 8. Sources

**Repo (file:line):**
- Regex/keyword input layer: `cloud_run_service/cognitive_input_processor/input_processor.py`
  — `SemanticClassifier` Protocol `:80-94`; `HeuristicSemanticClassifier` `:97-195`
  (`_score_keywords` `:173-178`); `TRANSFER_MARKERS` incl. bare "like" `:121-124`;
  `_TRANSFER_RE` `:256-259`; `_QUESTION_RE` `:240-243`; `_heuristic_signal_scores` `:421-453`;
  `_merge_scores` `:455-474`; `detect_student_problem` `:579-611` (patterns `:561-577`;
  rationale `:549-556`); default classifier wiring `:277-283`.
- Live analyzer path: `cloud_run_service/cognitive_analyzer/analyzer.py:227-250` (esp. the
  "stays uncalled" comment `:236-239`).
- Gemini perception (one memoized call; classify/resolve/route/embed; MiniLM embedder;
  candidate hints; §5.5 cross-check; schema; fallback):
  `cloud_run_service/perception/gemini_perception.py` — embedder `:114-144`;
  `_perceive` memo `:161-197`; `_concept_candidates` `:216-236`; schema `:344-367`;
  `_validate`/`_fallback` `:370-413`; `classify` `:416-421`; `resolve` `:482-509`;
  `route` `:512-528`.
- Front door + gates: `cloud_run_service/perception/gates.py:1-40`;
  `cloud_run_service/perception/interface.py:96-128` (gate-first), `:227-295` (degraded);
  `cloud_run_service/perception/route.py:14-24` (8 intents).
- Runtime wiring: `cloud_run_service/tutor_loop.py:1240-1271` (inject GeminiPerception,
  share MiniLM), `:2111`, `:2161` (`classifier.route`).
- MiniLM constant + exemplar classifier: `cloud_run_service/cognitive_classifier/classifier.py:34`
  (`all-MiniLM-L6-v2`), `:1-21` (bank is 384-dim), `:85-88` (`score_labels_logreg`),
  `:204-217` (`MiniLMSemanticClassifier` adapter); concept resolver embedder
  `cloud_run_service/concept_resolver/resolver.py:78-80`; HOPE
  `cloud_run_service/hope_detector/detector.py:21,46-48`.
- Live signal label space (38 labels) + scorer: `cloud_run_service/models/exemplar_classifier/label_space.json`;
  `cloud_run_service/models/exemplar_classifier/thresholds.json` (`scorer: "evidence+logreg"`).
- Architecture context: `docs/architecture/model_dataset_architecture_report.md:165-248`
  (MiniLM exemplar classifier, `all-MiniLM-L6-v2` at `:203`, logreg/MLP head at `:211`).
- Project mandate: `CLAUDE.md` (perception → Gemini 2.5 Flash, default
  `PERCEPTION_BACKEND=gemini`; MiniLM stays local for `S_rel` + HOPE).

**Interaction Control / Layer 1 (§7) — repo (file:line):**
- Layer-1 module: `cloud_run_service/interaction_control/control.py` — `_control` flow
  `:196-456`; front-gate use `:223-227`; STT-confidence gate `:248-260` (floor `:150`);
  `_low_confidence_result` re-prompt `:670-722`; perception route use `:300-304`;
  non-LEARNING branch `:356-371`; `_nonlearning_reply` scripted persona `:933-975`.
- Deterministic gates: `cloud_run_service/perception/gates.py` — `_SAFETY_PATTERNS`
  `:35-62`; `is_safety` `:76-78`; `classify_safety` `:81-93`; `is_nonsense` `:96-121`;
  `gate()` `:124-149`; "never downgrade" doctrine `:5-16`.
- `also_learning` produced but unconsumed: defined `perception/route.py:36`; produced
  `cloud_run_service/perception/gemini_perception.py:354,397,517`; **no consumer** in
  `interaction_control/` or `runtime/` (grep, 2026-08-25).
- Runtime wiring of ports: `cloud_run_service/tutor_loop.py:2109-2148`
  (`deterministic_route=_front_gate`, `perception_route=…`, `stt_write_confidence_min`).
- Layer-1 tests (patterns to extend): `cloud_run_service/interaction_control/tests/test_interaction_control.py`.

**External primary sources:**
- all-MiniLM-L6-v2 model card (384-dim, contrastive-similarity training, intended use):
  https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
- Negation degrades embedding similarity (measured): "Computation of sentence similarity
  score through hybrid deep learning with a special focus on negation sentence," *Scientific
  Reports* (Nature), 2025: https://www.nature.com/articles/s41598-025-34084-2
- Antonyms/negation cluster close in embedding space (survey): "Revisiting Word Embeddings
  in the LLM Era," arXiv:2502.19607 https://arxiv.org/html/2502.19607v1
- Compositional AND/OR/NOT limits of embeddings: arXiv:2105.08585
  https://arxiv.org/pdf/2105.08585
