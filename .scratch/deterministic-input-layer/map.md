# Deterministic Input Layer

## Destination

An implementation-ready specification for a single, independently testable **deterministic
Input Layer** module: extracted out of `cloud_run_service/tutor_loop.py` and out of the
`cognitive_classifier` model package, owning every model-free raw-text→structured-observation
step, and satisfying the input-side requirements of the Child-Safe Interaction Specification
(§3 routing order, §9 STT uncertainty, §11 personal data, §14 safety-route split). **Not §14's
coreference row** — ticket 12 handed §8's bands and the "do not use session context as proof of
topic identity" rule to the concept resolver; this effort leaves them unmet by design.

Done when: the seam, the input type, the output contract, the safety/privacy/STT contracts,
the test contract, and the verification gate are all decided, and `spec.md` is `ready-for-agent`.
This map changes no production code.

## Notes

- **Read code before docs.** `docs/architecture/INPUT_LAYER_SEMANTIC_INTENT_RESEARCH.md` is
  useful but has drifted: `InputProcessor` is constructed **twice, independently**
  (`cognitive_analyzer/analyzer.py:209` and `perception/gemini_perception.py:149`), not once.
- Requirements source: `docs/archive/AI_Tutor_Child_Safe_Interaction_Specification.docx`
  (extracted text in the session scratchpad). §3, §8, §9, §11, §12, §14, §15 are the
  input-side sections.
- Skills: `/grilling` + `/domain-modeling` for every HITL ticket; `/codebase-design` when
  placing the seam or shaping the interface (tickets 01, 03, 04, 05); `/research` for 06/08/10.
- Precedent: `.scratch/modular-tutor-runtime/map.md` (28 tickets, all resolved) established
  the deep-module vocabulary, `ModuleOutcome`/`StateChange`/`FailureSignal` contracts, the
  `TurnCoordinator`, and the `baseline_oracle` equivalence harness. Reuse all of it.
- This effort is **not** behavior-preserving. The child-safe upgrades deliberately change
  behavior, so the Baseline Split's equivalence-oracle rule does not transfer unchanged
  (ticket 15).
  > **Refined, ticket 15:** "reuse all of it" does not extend to the `baseline_oracle`
  > harness. Its frozen reference was **never completed** — `reference/metadata.json` records
  > four `capture_limitations` and `verify.py:22` returns `canonical_reference_incomplete`
  > unconditionally, so the oracle has never once run green and performance was never
  > measured. 15 **borrows** its corpus, its required-coverage pattern and its
  > normalization-forbidden-surfaces list, and repairs nothing.
- CLAUDE.md's 4-doc lockstep rule still applies to whatever this effort's spec changes.
  Note the four documents currently sit in `docs/archive/`, not `docs/architecture/`.

### Boundary (fixed by the user, 2026-08-25; **amended by ticket 01** — see its Resolution for the file-level manifest, which supersedes the coarse lists below)

**In:** `cognitive_input_processor/input_processor.py`; `perception/gates.py`;
`cognitive_classifier/cues.py`; the inline raw-text derivations at
`cloud_run_service/tutor_loop.py:2266-2330`; `tutor_loop.py:1359 _is_anaphoric_followup`;
`session_modes.mode_cues`.

**Out:** `perception/gemini_perception.py` and `perception/interface.py` — already modular,
already tested, already migrated (Part 11 Stage 6).

### Ground truth as of 2026-08-25 (verified against code)

> **Stale, ticket 01:** `input_processor.py` is 746 lines (not 651) and now **has** tests —
> uncommitted working-tree changes added `ingest`/`IngestedInput`/`extract_surface_cues`,
> a package `__init__.py`, and `tests/test_input_processor.py`. Treated as a spike and
> superseded; the 9 tests migrate to `utterance_intake/tests/`.

| Piece | Location | Out of `tutor_loop.py`? | Own tests? |
|---|---|---|---|
| `InputProcessor` (651 lines; ~90% dead) | `cognitive_input_processor/input_processor.py` | yes, but built twice | **none** |
| Deterministic SAFETY/NONSENSE gate | `perception/gates.py` | imported as `_front_gate`, `tutor_loop.py:115` | via `perception/tests/` |
| ~20 regex cue predicates + `cue_matrix` | `cognitive_classifier/cues.py` (~550 lines) | yes; 7 consumers | none direct |
| 10 derived booleans from raw text | `tutor_loop.py:2266-2330` | **no** | none |
| `_is_anaphoric_followup` | `tutor_loop.py:1359` **and** `interaction_control/control.py:664` | duplicated | none |

> **Refined, ticket 05:** the `_is_anaphoric_followup` row is off in two ways. The line
> numbers are `tutor_loop.py:1366` and `interaction_control/control.py:669`, and `tutor_loop`'s
> is a **delegate** to `InputProcessor.is_anaphoric_followup`, not a third copy — the verbatim
> duplicate is control.py's static method alone. The "10 derived booleans" row is at
> `tutor_loop.py:2266-2330` but understates the spread: four more partial copies of the same
> fusion exist (`PedagogyObservation`, `ResponsePlanningStateView`,
> `ResponseGenerationStateView`, and `evidence/grading.py:17 obvious_non_attempt`), and they
> disagree. See the ticket's Findings 1-4.

Live methods of `InputProcessor`: `normalize_input`, `detect_student_problem`. Dead:
`process`, `_heuristic_signal_scores`, `_merge_scores`, `_extract_candidate_concepts`,
`_contains_formula`, `HeuristicSemanticClassifier`, `InputSignalScores`, `ProcessedInput`.

Child-safe gaps: **no PII detector exists anywhere** (grep: zero hits); `gates.classify_safety`
gives 3 tiers / 2 categories where §14 demands six distinct routes; `stt_confidence` is one
float defaulting to `1.0` with no N-best and no math grammar (§9); coreference (§8) is a
12-word regex, duplicated.

> **Refined, ticket 11:** and the float itself is not what it claims. Google documents
> `latest_short`'s confidence as **not truly a confidence score** — the same caveat research
> §4.2 found on Chirp 2/3, applying to the model in production **today**. The 0.60 floor is
> also a documented placeholder: `WINI_LAYERED_ARCHITECTURE.md:335` says "start 0.6, calibrate
> per **DEC-044**", and `DEC-044` appears exactly once in the repo — in that sentence. It was
> never written. Also: `pacing/triage.py:33` is a **third** uncertainty channel
> (`stt_uncertain`), wired only from the legacy voice paths and never passed by
> `wini_server.py:652`, so it is permanently `False` in production.

> **Refined, ticket 10:** the `stt_confidence` line understates it. The default is
> **contradictory, not just permissive** — absent → `0.0` at `voice/cloud_stt.py:71`, absent →
> `1.0` at `interaction_control/control.py:249`, and both branches are live because Google does
> not always populate the field. The float is also a **mean across result segments**, so one
> mangled word is averaged away. `enable_word_confidence` / `enable_word_time_offsets` /
> `max_alternatives` are all unset (one boolean each for the first two). And "no math grammar"
> is not quite right: `math_grade.normalize` **is** one — misplaced in Assessment and Evidence,
> and structurally unable to refuse. See the ticket's Findings §A-§E.

> **Refined, ticket 07:** "3 tiers / 2 categories" understates it, and the recall picture is
> worse than the reported number. Measured 2026-08-26: the shipped **1.0 SAFETY recall is
> measured on a 20-phrase corpus that mirrors the lexicon** (`eval/perception_eval.py:120-141`
> and `eval/perception_eval_safety.jsonl` are the same 20 phrases), and the promotion gate
> hard-codes `>= 1.0` against it (`:562`). `python -m eval.perception_eval --gates` does not
> even run from the repo root — it imports `perception.gates` and there is no root
> `perception/` package. **6 of 9 self-harm probes land in the tier-2 catch-all.**
> Peer-at-risk (`my friend said she wants to die`) and online solicitation
> (`a man online asked for my photo`) are **total misses**; so are `he keeps threatening me`
> and `things are bad at home`. `i do not want to die in this level` is a **tier-3 false
> positive**. A model-added flag is silently defaulted to `(2, "safety_concern")`
> (`control.py:856-858`), and `interactive_tester.py:42-44` invents a fourth vocabulary
> (`tier 1` / `"HARMFUL_CONTENT"`) that no producer emits.

## Decisions so far

| Ticket | Title | Type | Status | Resolution Summary |
| --- | --- | --- | --- | --- |
| [01](issues/01-fix-input-layer-boundary-and-name.md) | Fix the Input Layer's boundary and name | grilling | resolved | `Utterance Intake` at `cloud_run_service/utterance_intake/`: a Feature Module with its own pre-Perception `TurnPhase` and one typed interface. Owns normalization, student-problem detection, safety/nonsense **detection**, and the new PII/STT contracts. Runtime cue regexes deleted in favour of Perception's labels; 8 judgments + topic phrasing promoted to the Gemini schema; `gate()` and `cue_matrix` stay put. |
| [02](issues/02-decide-the-input-value-type.md) | Decide the input value type | grilling | resolved | A frozen `Utterance` value (text + `source` + `provenance` + `confidence: float|None` + `alternates` + `word_confidences`) replaces the bare string; `TurnInput` gains it and both `interaction["text"]` and `trusted_observations["stt_confidence"]` are deleted. Absence is `None`, never a fabricated `1.0`. Typed door only -- no public `normalize(str)->str`. Perception memoizes on `utterance_id`, not normalized text. `max_alternatives=5` at the capture edge; low-confidence repair screen shows top-3 distinct + discard, learner always chooses. |
| [03](issues/03-define-the-input-observation-contract.md) | Define the Input Observation | grilling | resolved | One frozen `UtteranceObservation` -- embedded `Utterance` + one meaning-preserving `normalized_text` + `authorization` + **five required nested readings** (safety, legibility, transcript, problem, reference -- originally six; ticket 09 deleted `privacy`) -- returned as `ModuleOutcome[UtteranceObservation]` from a new `TurnPhase.UTTERANCE_INTAKE` before `PERCEPTION_AND_PRIOR_GRADING`. Intake is **total** (never `value=None`, no `FailureSignal`s), **write-free** (`state_changes=()`), **pure of session**, and **detects but never decides**. Booleans/enums only -- no scores, no `cue_matrix`. **NFKC deleted**; every reading runs on normalized text, none on raw. Safety/legibility/transcript readings are **never deferred**; the interpretive readings are computed but marked unauthorized until the learner authorizes the transcript (3 states: AUTHORIZED / UNAUTHORIZED / DISCARDED, filled from ticket 11's injected policy). Textual legibility **cannot** catch a fluent STT hallucination -- that axis is acoustic and lives in `TranscriptReading`, never feeding `gate()`. |
| [10](issues/10-research-math-aware-stt-normalization.md) | Research: math-aware STT normalization | research | resolved | Findings in `docs/architecture/MATH_AWARE_STT_NORMALIZATION_RESEARCH.md`. `mathtext.py` is a **renderer** (the inverse of §9); the real spoken-maths normaliser is `math_grade.normalize` — in the wrong module, and a `re.sub` chain that cannot hold a parse, so §9's audit + refusal cannot be met by extending it. `normalize_input` **does** rewrite meaning (NFKC destroys `x²`→`x2`, `½`→U+2044, drops U+2212 sign) despite its docstring. 4 measured confident false negatives incl. §9's own `"three squared"` example. Refusal is a parser-choice consequence: Earley can, PEG structurally cannot. 42-row homophone table for ticket 14. |
| [06](issues/06-research-child-safety-risk-taxonomies.md) | Research: child-safety risk taxonomies | research | resolved | Findings in `docs/architecture/CHILD_SAFETY_RISK_TAXONOMIES_RESEARCH.md`. Established taxonomies (CHI, 4Cs, Ofcom, Lifeline call logs) converge on the same coarse cuts §14 names, but all are **case-classification schemes for trained counsellors in a conversation** — none claims the cut is drawable from one utterance. At most two of the six routes are cleanly detectable deterministically; the four affective/relational ones are defined by facts outside the utterance (who did what to whom, past/ongoing/threatened). Four documented lexical failure modes, and the finding that **the highest-risk disclosures are systematically the least lexically explicit** — so a lexicon's recall ceiling is structural, not tuning debt. |
| [07](issues/07-decide-the-safety-route-taxonomy.md) | Decide the safety route taxonomy | grilling | resolved | **The architecture inverted.** Normative output: `docs/architecture/SAFETY_ROUTE_TAXONOMY.md`. A dedicated Gemini call in a new `child_safety/` package becomes the **primary** detector (every turn, parallel to perception, own prompt/schema/cache/eval, `flash@asia-south1`, 5s + one retry, late verdicts still count); the regex lexicon survives **only** as the degraded-mode outage net (axis-only, `{UNSPECIFIED_CONCERN}`/`ELEVATED`, never `CRITICAL`, frozen, CI-maintained). "May only add" is retargeted: **nothing may ever remove a finding, whatever made it.** Taxonomy = 6 classes + `UNSPECIFIED_CONCERN` as a **frozenset**, never a winner, plus two orthogonal flags (`caregiver_implicated` over-triggers by design, `imminence_cue`); `int` tier dies for a 2-value `SafetySeverity` derived at **one** site. Personal data and ordinary distress leave the safety axis entirely; uncertain-STT is a composition rule, not a class. Per-class blind-corpus floors (axis 0.95 / class 0.80 / net 0.90), **no aggregate number permitted anywhere**. |
| [04](issues/04-decide-the-cues-split.md) | Decide the cues.py split | grilling | resolved | **No split.** `cues.py` is not Utterance Intake's property and never becomes it; the whole file (vector + predicates) retires with the policy shadow in new ticket 17. This effort deletes **call sites only**, leaving the file byte-identical. Three of ticket 01's premises corrected: `cue_matrix` is on the **hot runtime path** (every turn, via `classify()` and `PolicyShadow.suggest`), the three build scripts were **lost** in `5b847a1` (artifacts unreproducible), and numpy is moot. Phase B pre-gate predicates deleted now, billing regression accepted. Guards = AST import guard (no allowlist) + a header comment; **no golden test**, silent-failure risk accepted. |
| [11](issues/11-decide-the-stt-uncertainty-contract.md) | Decide the STT uncertainty contract | grilling | resolved | Intake emits **evidence + one decision**, never a permission set: `TranscriptReading` (doubt verdict, `causes`, `contested_spans`, `repair_choices`, `MathParse`) plus ticket 03's `Authorization`; per-consequence rules live on the **consumers**, in the spec. `RouteResult.uncertain` -> **`perception_degraded`** (7 sites). Doubt is a **verdict OR-ed from three signals** (utterance confidence, min word confidence, alternate disagreement) because Google documents `latest_short`'s confidence as **not a true confidence score** — the 0.60 floor has always been uncalibrated and `DEC-044` was never written. Both downstream float checks **deleted** for an `authorization` precondition; safety **never** reads authorization. Maths grammar = **lark Earley** in Intake for R1/R2, **R4 in Assessment**; the concept scopes the *recognizer*, not the parser; `interpretation` is **graded**, not merely audited. Alternates **never leave Intake** — `repair_choices` is their one sanctioned export. Capture edge becomes a **handoff document**, not code: STT is being rebuilt as a streaming service by another developer. Ships **starved** (two of three signals absent), made visible by a startup capability assertion. |
| [05](issues/05-partition-the-inline-turn-derivations.md) | Partition the inline turn-body derivations | grilling | resolved | **A disposition record, not a design decision** — the fusion left this effort (user, 2026-08-26): Perception owns `answer_attempt`, a **future layer** owns `LearnerAsk` / the `non_attempt` derivation / the ten fusions, the response layer owns its own rules. The fusion already exists **four times and the copies disagree** (inline, `PedagogyObservation`, and two response-side state views with fields declared and never filled); a **fourth** non-attempt rule (`evidence/grading.py:17`) is the one actually protecting grading. `non_attempt` is **not** a fifth schema promotion. This effort rewires `tutor_loop.py:2266-2330` **in place** (regex arm -> label read, nothing moves module), deletes `analysis["problem_cue"]`, and deletes `control.py`'s verbatim `_is_anaphoric_followup` — Interaction Control reads Intake's `ReferenceReading` via a new `InteractionControlRequest` field and keeps the drift decision. Both logged regressions become ticket 14 corpus cases now. |

| [08](issues/08-research-personal-data-detection.md) | Research: personal-data detection | research | resolved | Findings in `docs/architecture/PERSONAL_DATA_DETECTION_RESEARCH.md`. DPDP §9 + COPPA §312.2 + UNESCO jointly fix the class list; COPPA counts the child's **audio itself** as personal information. The numeric collision is **measured**: MathEd-PII reports **Presidio F1 = 0.379** on maths-tutoring dialogue with false redactions clustering in maths-dense regions, vs **0.80–0.82** for domain-aware LLM prompting. Production detectors survive the collision only via *context proximity* (Presidio phone base score 0.4), which STT strips — so a threshold that spares `3825` also misses a spoken phone number. Typed placeholders (`<PHONE_NUMBER>`) are the prior art for redact-preserving-utility. `CREDENTIAL` has **no** detector class anywhere. |
| [09](issues/09-decide-the-personal-data-contract.md) | Decide the personal-data contract | grilling | resolved | Normative output: `docs/architecture/PERSONAL_DATA_CONTRACT.md`. **A model is the only detector — no regex, no lexicon, no outage net** (a disclosed number is not safety-critical, so lateness and zero-detection-on-outage are affordable; a pattern detector is not, because F1 0.379 means eating the maths). Own package `cloud_run_service/personal_data/`, own call fired right after Intake, own cache/eval, `flash@asia-south1` pinned, 5s + one retry, **two deadlines** (opportunistic for generation, full envelope for sinks). The verdict carries **verbatim substrings**, is identifier-bearing, and is never serialized; redaction is exact-match with typed **un-indexed** placeholders, so there is **no threshold or shape rule anywhere** and the maths is protected by construction. **Fail closed on persistence, fail open on the child; no retro-scrub.** Four sinks converted to a `RedactedText` type with no `str` overload. **`PrivacyReading` is deleted** from `UtteranceObservation` (Intake is model-free) — six readings become five. **No do-not-learn flag**: the §3 boundary lands on fields, not turns. No separate privacy store (it would itself be a DPDP §9(3) behavioural record). 9 classes, floors on **both** axes (per-class recall ≥ 0.80, maths-corpus FP ≤ 1%), blind corpora, no aggregate number. |
| [13](issues/13-decide-dead-code-and-seam-disposition.md) | Decide the dead-code and SemanticClassifier-seam disposition | grilling | resolved | **The seam dies entire** (`SemanticClassifier`, `HeuristicSemanticClassifier`, and the `MiniLMSemanticClassifier` adapter + its `cognitive_classifier/__init__` exports): both stated purposes are filled elsewhere -- the offline fallback is 07's lexicon outage net, and a local classifier's slot is on Perception, not on a booleans-and-enums Intake. **13's own manifest was wrong**: `build_default_input_processor`/`process`/`ingest` have a live caller (`interactive_tester.py`), `is_anaphoric_followup`/`is_same_problem_followup` have live `tutor_loop` delegates, `InputProcessor` is built **five** times not two, and three consumers were in no inventory (`tools/sync_to_pi.py:56` by **string**, the coupling report's *"Ideal Deep Module"* claim, and a **byte-identical root `tutor_loop.py`**). 13 is a **manifest for 16**, not a change -- only two things land now: commit the spike as superseded (untracked, otherwise unrecoverable), then delete the seam. The cut: delete code with **no** replacement now, defer code whose replacement does not exist yet. `is_anaphoric_followup` confirmed **not provisional** (03 made `ReferenceReading` required), so 13 does not block on 12; `is_same_problem_followup` **inlines** into `tutor_loop.py` (reads session, so 03 rule 3 bars it from Intake). `InteractionControlRequest` gains a **required** `observation` -- deliberately unlike the `perception: ... | None` beside it, because Intake is total and an optional field invites a `getattr` fallback to the deleted regex. Root `tutor_loop.py` **deleted** (unimportable since `5b847a1`); the rest of the root cluster is out of scope and **explicitly not endorsed**. The 9 spike tests are **deleted, not migrated** (amends 01) -- one of them asserts *around* the NFKC bug 03 removed; 14 inherits the cases. `points_to_consider_developer.txt` archived, rules dispositioned individually: 2 promoted as Perception constraints (into 18's document), chunking promoted as an **eval question**, pronoun-normalization **deleted with prejudice**. `docs/archive/` is **never touched**. |
| [14](issues/14-define-the-test-contract-and-corpora.md) | Define the test contract and the golden corpora | grilling | resolved | **Two lanes, one manifest, and a construction order.** Assertions are `unittest` (free, automatic CI, credential-less: contracts, the six inherited invariants, corpus integrity); measurements are `eval/*.py` (billed, approval-prompted, per-class, never aggregated) -- and they never share a harness. **Import purity is dead** (user, 2026-08-27): ticket 04's stdlib-only guard fails on day one against 11's `lark` (pure-Python != stdlib, and it is in neither `requirements.txt` nor the env), and an import guard cannot catch a MiniLM load anyway. Replaced by a **seam rule** -- any external model sits behind an injected dependency, so the suite stays offline with `GOOGLE_APPLICATION_CREDENTIALS` unset -- plus the finding that Intake ships model-free **because the topology forces it**: safety fires first, perception immediately after, perception's output **held until the safety verdict is analyzed** (bounded by the 5s envelope, then degraded), so anything Intake waits on is pure added wall-clock ahead of both. **No CI existed** (`.github/` absent); this effort adds one workflow -- offline job automatic, billed job behind a GitHub Environment with required reviewers that **prompts the developer with the cost**, no path-based auto-skip. WIF deferred to its own ticket, the job ships failing loudly. **Corpora: construction split from gating.** 14 owns the manifest/schema/harness, builds the Intake + legacy-20 + degraded-net sets, and **authors the safety per-class + FP corpora now** (blindness maximal before any prompt exists) though they gate `child_safety/`, not this effort. **Test-first is the method**; corpora are LLM-generated from a **reviewable grid** (class x directness x register x code-switching x euphemism) with an empty-cell integrity failure, >=40% indirect rows per safety class, and a **different generator family for safety/PII only** -- TDD defeats prompt mirroring, not model mirroring. **The LLM generates; it never judges** (the row's label is the ground truth). `safety_eval.py` mirrors the existing `--collect`/`--score` cache split, one billed collect per prompt version, mixing caches is a test failure. In-repo, public, synthetic-only. **Of docx S15's six sets only ambiguity/STT is Intake's** -- 01 moved purpose/why and representation to Perception, privacy is 09's, safeguarding is 07's -- and its bars are exact-match legibility/authorization coverage, the 42-row homophone table, and the grammar's two-sided criterion with the refusal **band 5-15% measured over claimed maths spans, never utterances**. Sign the **grid and a sample**, not 300 rows; unreviewed numbers publish under that label but block no cutover. **The negation acid test and the `learning_log` regressions leave this layer entirely** (user, 2026-08-27: the grader layer's, no code, no test) -- reversing ticket 05's *"both logged regressions become ticket 14 corpus cases now"*. |
| [12](issues/12-decide-where-coreference-confidence-lives.md) | Decide where coreference confidence lives | grilling | resolved | **Coreference leaves this effort entirely** (user, 2026-08-27): it is the **concept resolver's** job -- not today's stateless scorer, but the layer that name denotes (cleanup -> scoring -> **reading chat history** -> **asking pedagogy to put a follow-up question**), which does not exist yet. Output is a committed brief, `cloud_run_service/concept_resolver/CONCEPT_RESOLUTION_HANDOVER.md`, executed by a different team. **The measurement reversed the obvious answer:** 35.5% of the frozen hardened run predicts `INHERIT_CURRENT_CONCEPT` and **gold says 39.2% should** -- the dataset's own contract makes "carry the session's concept" *correct* for ~2 in 5 utterances, so deleting inheritance globally breaks the common case to fix a rare one. Of **five** silent-inherit sites (the ticket knew of one), **three are deleted**: the drift guard (`control.py:427-436`) and the adapter's two duplicate suppliers (`legacy_adapter.py:102`, `:215`/`:245`) -- which also means deleting the abstain inherit alone would have been **cosmetic**. **Two survive and are handed over**: `interface.py:151-153` and `_degraded` (untouched; it moves no learner state). Drift-suppression dies rather than becoming a silent override; the interim silent topic-jump is accepted. `ReferenceReading` = spans + derived `has_anaphora`, `word_count` and the **12-word cutoff discarded** as unmeasured and unowned. `INHERIT_CURRENT_CONCEPT` keeps its name (welded to schema/cache/gold/eval); it now means **abstain**. New invariant: `concept_id is None` => no learner-state write. |
| [15](issues/15-decide-the-no-regression-verification-gate.md) | Decide the no-regression verification gate | grilling | resolved | **No equivalence gate — three staged gates over one standing set.** Stage 1 Utterance Intake (free lane only, no billed run); Stage 2 `child_safety/` cutover; Stage 3 `personal_data/` — 2 and 3 **blocked on the WIF ticket**, and ordered safety-first because PD §9.2's `privacy_unavailable` stamp makes the interim honest. Equivalence partitions into **Tier A** byte-identical (`gate()` NONSENSE + terse real answers), **Tier B** expected-diff against a **closed, symmetric** manifest (`normalize_input`'s NFKC removal, `detect_student_problem`'s raw→normalized move — an unlisted diff fails *and* a stale manifest row fails), and **Tier C** unconstrained. `baseline_oracle` is **borrowed, not reused**: its frozen reference has never run green (`verify.py:22` returns `canonical_reference_incomplete`). Four turn-level properties in `runtime/tests/` answer the Part 11 trap in its general form; LLM-authored tests allowed on a local approval prompt. Perf: no budget — a grammar wall-clock cap plus a CI-only p95 > 3x regression guard. **The shipped `SAFETY recall 1.0` is deleted from all seven sites, including the never-executable `>= 1.0` criterion at `eval/perception_eval.py:562`.** Evals move to `cloud_run_service/eval/`; results are dated records; the gate lives in `spec.md` with the CI workflow as its executable form. Docx §15 mapping carries a verbatim **what-green-does-not-mean** statement at the top. No rollback path by decision — nothing releases below floor. |
| [16](issues/16-write-the-implementation-spec.md) | Write the implementation spec | task | resolved | **`spec.md` is written and `ready-for-agent`.** Synthesizes 01-15 into one implementation-facing document: Utterance Intake at `cloud_run_service/utterance_intake/` with one typed door and a new pre-Perception `TurnPhase`; `Utterance` / `UtteranceObservation` as typed definitions; the file-by-file migration manifest (moves, byte-identical `cues.py`, the cue deletions, the four schema promotions, the seam deletion, the twelve rewired consumers); `SAFETY_ROUTE_TAXONOMY.md` and `PERSONAL_DATA_CONTRACT.md` **referenced, never restated**, with only the seam-level facts and the *nothing may ever remove a finding* invariant in the spec's own voice; the STT contract's per-consumer consequence gates, the `repair_choices`-is-the-only-export N-best rule, and the grammar's refusal semantics; coreference named **out of scope and unmet**, owned by the concept resolver's handover; the two-lane test contract with the six corpora and the six invariants; and the three-stage verification gate with Tier A/B/C, the numbers register, the seven-site retraction manifest, and the what-green-does-not-mean statement verbatim at the top. **Not yet discharged:** the eleven-row documentation pass (headed by `CLAUDE.md`, plus the new `STT_CAPTURE_CONTRACT.md` and the `rag_memory.md` log entry), which the spec states as a precondition of implementation rather than a follow-up. |
| [18](issues/18-rewrite-the-architecture-document-set.md) | Rewrite the architecture document set | documentation | open | **The 4-doc lockstep rule dies.** Raised by 13 on the user's finding that the set is contaminated. One **normative** architecture document, written fresh on `WINI_LAYERED_ARCHITECTURE.md`'s L0-L9 + X1/X2 skeleton -- which is archived rather than revised, because it is dated 2026-08-05 and **contradicts ticket 07 in a mandate sentence** (*"Model usage: NONE by mandate"*, *"do not implement a model-based safety classifier as the primary gate"*), still cites the never-written `DEC-044`, and has **zero** occurrences of `Utterance Intake`/`UtteranceObservation`/`Feature Module`/`TurnPhase`/`child_safety`. The store plan and dataset report become **dated measurement records**, not chapters: a four-way manual propagation obligation is what rotted them, and records carry no such obligation. The two current contracts (`SAFETY_ROUTE_TAXONOMY.md`, `PERSONAL_DATA_CONTRACT.md`) are **cited, never absorbed**. `CLAUDE.md`'s lockstep block becomes a source-of-truth block with a precedence line; **`CONTEXT.md` is not touched** (it is the vocabulary, already current, and upstream of the architecture doc). Every `docs/architecture/` file gets a normative/research/explainer header; `FINAL_WINI_PEDAGOGICAL_ARCHITECTURE_PLAN.md` archived (it reviews a commit on a **different repository**). **Nothing blocks on it** -- if 18 gated 16, a doc rewrite would gate the implementation spec, which is how four contaminated documents got written. |

## Not yet specified

- ~~Whether any deterministic cue predicate needs a negation guard.~~ **Resolved by ticket
  01:** moot. Every cue whose correctness depended on negation handling is deleted from the
  runtime path or promoted to Perception. What remains in Utterance Intake is structural
  (normalization, numeral/equation detection, character-class nonsense) or lexicon-based
  safety, where the documented remedy is broaden-and-measure (ticket 07), not a model.
- ~~Which of the four lockstep documents this effort must update, and whether they move back
  out of `docs/archive/` first.~~ **Resolved by ticket 13, handed to new ticket 18**
  (user, 2026-08-27): none of them. The lockstep set is contaminated and the **rule itself
  dies** — one normative architecture document replaces it, the store plan and dataset
  report are demoted to dated measurement records, and `CLAUDE.md` gets a source-of-truth
  block instead of a propagation obligation. They stay in `docs/archive/`.
- ~~Multi-turn safety review (docx §15: "review the entire multi-turn conversation, not only
  the first reply"). Session-scoped, so probably not this layer's — revisit after 07.~~
  **Resolved by ticket 07.** Three parts: an utterance's class set is never revised by
  history; severity **may be raised** by history, never lowered (the deterministic session
  accumulator); and §15's multi-turn *review* is an **eval requirement** on ticket 14's
  corpora (conversation-level fixtures), not a runtime feature. The safety model call also
  sees `session["context"][-2:]` — one preceding exchange — which is what makes §15
  implementable at all; it was not implementable with a stateless regex.
- ~~Whether `session_modes.mode_cues` and `pacing/triage.py`'s direct cue imports become
  Input Layer consumers or keep their own copies.~~ **Resolved by ticket 01:** neither.
  `mode_cues` is obsolete (mode detection becomes a Gemini-emitted `SESSION_CONTROL`
  sub-type); all five of `pacing/triage.py`'s imports are in the delete set and it reads
  Perception labels instead. Ticket 04 keeps only the `cognitive_classifier` split mechanics.
- **New (ticket 01):** the 4 promoted signal labels have **no dataset gold**, so
  `behavioral_eval` has no ground truth for them until the dataset is extended. Owner TBD.
- **New (ticket 01, accepted risk):** the Part 15 Phase B speculative grader pre-gate
  (`wini_server.py:574`) runs concurrently with perception and cannot read its labels.
  Deleting its predicates bills a `judge_answer` call on every pure ack and bare question.
  Deferred to a future layer by user decision, 2026-08-25.
- **New (ticket 10, narrowed by ticket 02):** `normalize_input`'s NFKC step is **not**
  meaning-preserving on maths notation, and the test that should catch it asserts around it
  (`tests/test_input_processor.py:23-29`). Whether NFKC survives at all in Utterance Intake,
  and in what restricted form, is still unowned — it sits between ticket 03's contract and
  ticket 11's. Ticket 02 removed one dependent: `word_confidences` carry **time** offsets and
  no character offsets, so no raw->normalized alignment map has to survive the rewrite. Ticket
  02 also removed the idempotency constraint (the memo now keys on `utterance_id`), so this is
  a correctness question only, no longer a caching one.
- ~~**New (ticket 10, unverified):** the `en-IN` feature matrix for **`asia-south1`**.~~
  **Answered by ticket 11, differently than expected:** STT **v1 has only US and EU regional
  endpoints** — `asia-south1` is not a v1 region at all, so STT and Vertex are **not**
  co-located and nothing in the spec may assume they are. v2 *does* list `asia-south1`, but its
  per-model matrix remains **UNVERIFIED** (needs the Locations API) and becomes the streaming
  rebuild's problem if it moves to v2.
  Related constraint: Chirp 2/3 word confidence is documented as not a true confidence score,
  and Chirp 2 rejects custom classes — so "Chirp for Indian English" and "gate on word
  confidence" cannot both hold.
- **New (ticket 02):** the repair screen needs a **new display element type** — a tappable
  text choice. `display[]` is metadata-only today (`{image_path, alt_text}` stable image IDs,
  `wini_server.py:47`). Response-side, so out of this map's scope; ticket 02 fixed only its
  cardinality (top-3 distinct + discard, one screen).
- ~~**New (ticket 02):** `enable_word_confidence` is not turned on until ticket 11 verifies
  `WordInfo.confidence` on `latest_short`/`en-IN`.~~ **Resolved by ticket 11:** verified
  **supported** for `en-IN` + `latest_short` in the v1 language table, so it is turned on — but
  it is **Preview** (pre-GA terms), `WordInfo.confidence` documents `0.0` as a *sentinel for
  "not set"* (the adapter must map it to `None`), and the latest-models page disclaims true
  confidence scores for this model family. Enabling it is now a **handoff requirement**, not
  this effort's code.
- **New (ticket 03) — `PolicyShadow.suggest` needs a new feature path.** Ticket 01's manifest
  says `cue_matrix` is "build-time only, zero runtime importers". **That is wrong.**
  `PolicyShadow.suggest` calls `cue_matrix` (`policy_shadow/shadow.py:79`) and is invoked
  **unguarded on every learning turn** at `tutor_loop.py:2463`, inside `_legacy_turn` — so a
  9-wide float feature vector is computed from normalized text on the live path today.
  **Disposition (user, 2026-08-26): ticket 04 is NOT reopened and its scope is unchanged.**
  `PolicyShadow.suggest` gets a **new feature path of its own**, designed separately, rather
  than this becoming a cues-split question. Owner and design TBD; it is the one live consumer
  that ticket 03's "no `cue_matrix` on the observation" rule leaves without a supplier.
- **New (ticket 03):** `normalize_input`'s NFKC step is **deleted** — the published
  `normalized_text` is NFC + zero-width strip + whitespace collapse, and any lossy folding a
  matcher needs is private to that matcher. This closes the item above that ticket 10 left
  "unowned between 03 and 11". Ticket 11 still owns the maths grammar; its refusal lands in
  `TranscriptReading`, not in the normalizer.
- **New (ticket 03):** the four promoted signal labels and the dataset-gold gap (ticket 01) are
  unaffected, but **ticket 14 now also needs audio-derived corpora** — a fluent
  high-confidence STT hallucination, a fluent low-confidence one, and a divergent-alternates
  set. None can be written as a plain string, so the harness question ticket 11 flagged can no
  longer be deferred.
- **New (ticket 03, sequencing):** `authorization` is filled from ticket 11's **injected
  transcript policy**, so the STT floor is consulted inside the *first* phase of the turn.
  `UTTERANCE_INTAKE` becomes the earliest point at which an STT threshold has runtime effect,
  and 11's policy is a hard construction dependency of Intake.
- **New (ticket 04):** the 9-cue vector and `PolicyShadow` outlive this effort — see new
  ticket [17](issues/17-retire-the-cue-vector-and-policy-shadow.md), owner TBD. Retirement
  scope is the **cue vector + shadow**, not `cognitive_classifier/` (`concept_resolver` and
  `hope_detector` still import `classifier.py`, and `classify()`'s scores feed the state
  math). Dropping the 9 dims needs a re-fit or a zero-fill, and no build script exists.
- **New (ticket 04, accepted risk):** the Phase B speculative pre-gate
  (`wini_server.py:574`) loses `is_pure_ack` / `is_question` in **this** effort, so every
  armed `pending_check` bills a `judge_answer` on pure acks and bare questions. 01 parked
  the cost; 04 spends it. Owned by ticket 17.
- **New (ticket 04, accepted risk):** `cues.py` gets a header warning and **no test**. An
  edit to a cue regex changes the feature vector fed to a head fit against the old regex —
  no crash, no failing test, no log line, and no rebuild path to re-sync it.
- **New (ticket 04):** `models/exemplar_classifier` and `models/policy_shadow` are
  **unreproducible** — `curate_dataset.py`, `build_bank.py` and `build_policy.py` were
  deleted by `5b847a1` ("remove root duplicate modules") though `cloud_run_service/` never
  had copies. Recovery point `5b847a1^`. CLAUDE.md:67-69, 124-126 still document them.
- **New (ticket 04):** a **delete-only pre-effort commit** removes root `tutor_loop.py`,
  `session_modes.py`, `wini_server.py`, `test_session_modes.py` and the root `Dockerfile`.
  These are not duplicates but dead code: the root tree holds none of `policy_shadow`,
  `cognitive_classifier`, `perception`, `pacing`, `pedagogy`, `runtime`,
  `interaction_control`, while root `tutor_loop.py:48` imports `policy_shadow` at top level.
- **New (ticket 05) — the future fusion layer, owner TBD.** The judgments that fuse a
  deterministic cue, a model signal and session state left this effort by user decision
  (2026-08-26) and are owned by a layer that does not exist yet. It inherits, in one list so the
  pieces are not orphaned across four resolutions:
  - the ten inline booleans at `tutor_loop.py:2266-2330`, left in place and now model-fed;
  - `LearnerAsk` — whether the ten become one named record at all, and where it lives;
  - the `non_attempt` derivation (from labels Perception already emits — **not** a schema field);
  - reconciling `student_problem` (`is_problem AND (directive OR not answer_try)`) with
    `PedagogyObservation.learner_problem` (`is_problem AND directive`), which have disagreed
    since the modular split. Recorded target: the legacy rule;
  - `PolicyShadow.suggest`'s new feature path (map, ticket 03; retirement is ticket 17);
  - the Part 15 Phase B speculative pre-gate's billing regression (ticket 01, spent by 04).
- **New (ticket 05) — two inherited facts corrected.** **Perception executes *before*
  Interaction Control** (`runtime/coordinator.py:169` vs `:188`); `LOGICAL_TURN_PHASES` is a
  **trace** contract, not the execution order. And **`gate()` is called inside
  `Perception.perceive`** (`perception/interface.py:102`), not by Interaction Control — ticket
  01's manifest is loose about the caller, ticket 03 has it right. Neither changes a decision;
  both change what "the front door runs first" means when reading `coordinator.run`.
- **New (ticket 07) — the safety architecture inverted, so five new work items exist**, all
  owner TBD and all outside this map's decide-only scope:
  1. **`cloud_run_service/child_safety/`** — the new package: prompt-of-record, response
     schema, Vertex context cache, `VERTEX_SAFETY_MODEL`/`VERTEX_SAFETY_LOCATION` seam, 5s
     bound + one retry, late-verdict delivery.
  2. **`eval/safety_eval.py`** — its own harness (never inside `perception_eval.py`), per
     class, no aggregate, plus the billed one-time cutover gate.
  3. **The safeguarding case store** — move `safety_alerts` out of the learner state document
     (it currently sits beside `evidence_ledger`, `legacy_adapter.py:441`), support
     **asynchronous updates** to an open record, and carry the self-contained review fields.
  4. **Honest `handled`** — delete the hard-coded
     `"scripted_reply+persisted_alert+supervisor_notify"` literal at `control.py:860` and
     derive it from real outcomes. Touches §15's stop-ship gate.
  5. **Template library requirements** for `PEER_AT_RISK` and `UNSAFE_CONTACT` — two new
     classes with no docx §12 row and no script, plus the "never name a parent by default"
     safe-adult rule.
- **New (ticket 07, accepted cost):** a second Gemini call on **every** turn (parallel to
  perception, small prompt). Roughly doubles perception-tier request volume. Gating it on a
  lexicon trip is **forbidden** — that would reinstate the regex as gatekeeper. The only cost
  levers are the context cache and the model id.
- **New (ticket 07, new hazard class):** **safety recall can now change with no code change** —
  a prompt edit, schema tweak, model-version roll, cache rebuild or region flip all move it
  silently. Mitigated by pinning the model version and by making the eval a release gate, but
  it is a standing operational risk a regex did not have.
- **New (ticket 07):** ticket 03's `SafetyReading` is renamed **`SafetySignals`** and is
  lexicon-only; `severity` moves off it onto the composed `SafetyVerdict`. Intake still
  computes it every turn, but on a healthy turn it is **not the verdict** — it is consumed
  only in degraded mode and by the divergence monitor.
- **New (ticket 11) — `docs/architecture/STT_CAPTURE_CONTRACT.md` is not yet written.** It is
  the ticket's one remaining artifact: requirements *on the producer*, covering the `Utterance`
  construction contract, the seven required capture-edge changes, the three streaming rules, the
  two Google caveats, the deferred items, and how to verify. **Whoever changes `Utterance`
  updates it in the same session.**
- **New (ticket 11) — the streaming STT service, owner: a different developer.** The current
  capture edge is HTTP POST/GET; it is being rebuilt as streaming (user decision, 2026-08-26).
  Outside this map; the handoff document is the entire interface. `Utterance` is unchanged by it
  — the *producer* is constrained (one `Utterance` per **final** result, never an interim one).
- **New (ticket 11), deferred with no owner assigned:** the per-turn concept-scoped
  `inlinePhraseSet` (§9's "active concept" at the recognizer), and `en-US` → `en-IN` — a real
  accuracy question that changes every transcript in the system and deserves its own measurement.
- **New (ticket 11) — `DEC-044` must be written or explicitly killed.** All three doubt
  thresholds ship **provisional and uncalibrated**; the captured-STT corpus (ticket 14) is the
  named instrument. On the current producer the repair path's delta is **predicted to be ≈ zero**
  — written down as a prediction so a green run is not misread as evidence the feature works.
- **New (ticket 11) — correction to ticket 02.** Deleting `interaction["text"]` touches **six**
  readers, not the two ticket 02 names: `assessment_evidence/interface.py:85`, `control.py:219`
  and `:682`, `perception/interface.py:101`, `retrieval/interface.py:303`,
  `legacy_adapter.py:305`. And `AssessmentRequest` carries **no observation**, so ticket 11
  requires it gain `observation: UtteranceObservation`; the other five rewires are ticket 16's.
  Third inherited undercount this map has had to catch — after ticket 01's `cue_matrix` claim
  and ticket 10's `stt_confidence` line.
- **New (ticket 11) — new ticket, owner TBD:** retire `math_grade.normalize` in favour of the
  grammar, closing ticket 10's finding **B2** (Utterance Intake work living in a grading
  module). Knowingly deferred; the duplication runs for the duration.
- **New (ticket 11) — CLAUDE.md gotchas to add:** `latest_short`'s confidence is not a true
  confidence score; `DEC-044` never existed; STT v1 has no `asia-south1`. Plus the retired
  `STT_WRITE_CONFIDENCE_MIN` name and the new `lark` dependency.
- Post-spec implementation backlog (the tickets that would actually move the code).

- **New (ticket 12) — coreference and topic resolution left this effort.** Owner: the
  **concept resolver**, expanded to what the name denotes (cleanup, scoring, **chat-history
  reading**, and **requesting a follow-up question from the pedagogy layer**). It does not exist
  yet; today's `concept_resolver/resolver.py` is a stateless scorer that becomes a *component*
  inside it. The implementable brief is committed at
  `cloud_run_service/concept_resolver/CONCEPT_RESOLUTION_HANDOVER.md` and is executed by a
  different team. Docx §8's three bands, §14's coreference row and §16's "coreference confidence
  and a clarification UI" item are **out of scope for this effort and unmet by it**.
- **New (ticket 12, accepted interim regression):** with the drift guard deleted, a confident
  resolution to an unrelated concept is **accepted** and `session["current_concept"]` follows it.
  An STT mangling can silently jump chapters mid-topic until the new layer lands. Deliberate:
  the guard's own behaviour was the §14 violation it was asked about.
- **New (ticket 12):** `ReferenceReading` is **produced and unread** after the drift guard goes —
  Interaction Control has no other consumer of it. It ships supplied-and-waiting on ticket 13's
  required `InteractionControlRequest.observation`, which is what stops a future consumer
  `getattr`-falling back to a private regex.
- **New (ticket 12), unowned:** `_degraded` also fabricates `primary="LEARNING"` and a neutral
  `cognitive_update` (`confidence: 0.5`, `engagement: 0.5`, rest zeroed) on every outage turn —
  the same category of fiction as an inherited concept, on Perception's outage contract, owned by
  nobody. Flagged by 12, not fixed.
- **New (ticket 12), measured:** the abstain rate is **35.5%** predicted / **39.2%** gold on the
  frozen hardened run (`eval/perception_eval_raw2.jsonl`, 1019 rows, offline). Any future work
  that touches concept inheritance should start from this number, not from intuition about how
  rare "this/that" is.

## Out of scope

- `perception/gemini_perception.py` / `interface.py` internals — the semantic layer.
  Boundary call, 2026-08-25. Its **interface** may constrain this map (ticket 07's
  "model may only add recall" rule), but its implementation is not touched.
- Consuming `route.also_learning` so a greeting-plus-maths-ask is not dropped. Confirmed
  real bug (produced in `perception/*`, zero consumers), but the missing consumer is
  `interaction_control/control.py:356-371` — a downstream module, not the input layer.
  **Disposition (ticket 01):** an implementation of this already sits uncommitted in the
  working tree (`control.py`, `perception/interface.py`). Split it out and commit it on its
  own *before* this effort starts, so ticket 15's gate does not have to account for a
  behavior change it does not own.
- ~~Replacing the regex/keyword layer with a local MiniLM semantic classifier, or a supervised
  head trained on negated pairs (research doc §4-6, options b/c/e).~~ **Superseded by ticket 01
  (2026-08-25).** No *new* model is added. The runtime cue regexes are **deleted**, and the
  judgments they made move to the Gemini call that already runs — 10 to existing labels, 4 to
  new labels, 4 to a `SESSION_CONTROL` route sub-type, plus topic phrasing. This deliberately
  puts a **Perception schema change on this effort's critical path**, which the original
  boundary excluded.
- The safety **reply** template library, locale/helpline registry, and output verifier
  (docx §12, §13, §14, §16). Response-side.
- Age assurance, consent, retention, jurisdiction review (docx §11). Not code.
