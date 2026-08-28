# Decide the dead-code and SemanticClassifier-seam disposition

Status: resolved
Type: grilling
Blocked by: 01, 03

## Question

`input_processor.py` is 651 lines of which two methods are live. What survives?

**Live:** `normalize_input` (`:359`) — called at `cognitive_analyzer/analyzer.py:229` and
`perception/gemini_perception.py:151`; `detect_student_problem` (`:579`) — called at
`analyzer.py:240`, gates `SOLVE_STUDENT_PROBLEM`, deliberately narrow and deliberately not a
model (`:549-556`).

**Dead at runtime:** `process` (`:289`), `_heuristic_signal_scores` (`:421`), `_merge_scores`
(`:455`), `_extract_candidate_concepts` (`:476`), `_loose_match` (`:522`), `_contains_formula`
(`:542`), `HeuristicSemanticClassifier` (`:97`), `InputSignalScores` (`:33`), `ProcessedInput`
(`:52`), `build_default_input_processor` (`:619`), the nine `_*_RE` signal patterns
(`:240-275`), and the `MiniLMSemanticClassifier` adapter at
`cognitive_classifier/classifier.py:204-217` that exists only to fill the seam.

Decisions to close:

- **Delete or keep?** `docs/architecture/INPUT_LAYER_SEMANTIC_INTENT_RESEARCH.md` §2
  recommends keeping the `SemanticClassifier` Protocol seam (`:80-94`) as (a) an offline /
  no-network fallback and (b) the documented slot for a future local semantic classifier.
  Against that: the regex implementation behind it is demonstrably wrong — it scores
  "I do like math" and "I do not like math" identically, firing `transfer_attempt = 0.8` on
  both, which is wrong for both. A fallback that is confidently wrong is worse than no
  fallback on a child-facing device.
- If the seam stays, **what fills it**, and what stops the broken heuristic being the default
  again? It is the default today (`InputProcessor.__init__:283`).
- **Two instances, one normalizer.** The analyzer and `GeminiPerception` each construct their
  own `InputProcessor` lazily. Does the Input Layer expose a single shared instance, a module
  function, or stay per-caller? Affects the memoization gotcha (normalized text is the
  Gemini memo key).
- **`detect_student_problem`'s home.** It is the one deterministic cue everyone agrees is fit
  for purpose. Does it move to the Input Layer, and does its `dict` return become part of the
  ticket-03 observation?
- **`_contains_formula`** is dead but its metadata was flagged as a real loss in the earlier
  audit (`docs/archive/BRAIN_ARCHITECTURE_AUDIT.md`, D-1). Revive as an observation field, or
  confirm `detect_student_problem` fully supersedes it?
- **`points_to_consider_developer.txt`** sits in the package as unversioned design intent
  (the MiniLM exemplar-bank plan, the "do not softmax / do not strip stop words / do not bake
  subject matter into exemplars" rules). Promote the still-binding rules into the spec, or
  archive the file?

---

## Resolution (2026-08-27, /grilling)

**The seam dies, the sweep is wider than this ticket described, and almost none of it lands
as code here.** 13 produces a *manifest* consumed by ticket 16, plus two deletions that can
stand alone because they remove code with no replacement.

Two organizing rules produced everything below:

1. **Delete code that has no replacement now; defer code whose replacement does not exist
   yet.** This is the cut between what 13 lands and what it hands to 16, and it is the only
   cut that keeps every intermediate commit importable.
2. **A partial sweep must say what it did not sweep**, or the remainder reads as endorsed.

### Correction of record: the ticket's own manifest was wrong

The Question above lists as "dead at runtime" three things that have live callers. 01's and
the map's inventories inherit the same errors. Corrected here; **01 is deliberately not
amended**, following ticket 04's precedent — the correction of record lives in the ticket
that measured it.

| Claimed dead | Actual caller |
|---|---|
| `build_default_input_processor`, `process` | `interactive_tester.py:16,111,181` |
| `ingest` (working-tree spike) | `interactive_tester.py:180` |
| `is_anaphoric_followup`, `is_same_problem_followup` | `tutor_loop.py:1366-1375`, reached from `:2628` |

And `InputProcessor` is constructed **five** times, not two: `cognitive_analyzer/analyzer.py:209`,
`perception/gemini_perception.py:149`, `tutor_loop.py:1361`, `eval/behavioral_eval.py:221`,
`eval/perception_eval.py:401`.

Three consumers appear in no prior inventory: **`tools/sync_to_pi.py:56`** syncs the package
to the device *by string*, so no import guard would ever see it;
**`CODEBASE_ARCHITECTURE_AND_COUPLING_REPORT.md:31,53`** holds the package up as the repo's
*"Ideal Deep Module Metric"*; and root **`tutor_loop.py`** is byte-identical to
`cloud_run_service/tutor_loop.py` (`diff` exit 0), so every edit here is otherwise a two-file
edit.

### The seam: deleted entire

`SemanticClassifier` (Protocol), `HeuristicSemanticClassifier`, the `MiniLMSemanticClassifier`
adapter (`cognitive_classifier/classifier.py:204-217`) and its two `cognitive_classifier/__init__.py`
export lines all go.

The research doc kept the seam for two stated purposes and both are now filled by something
else: the **offline/no-network fallback** is ticket 07's frozen lexicon outage net, and the
**slot for a local semantic classifier** is a slot on Perception, not on a model-free Intake —
ticket 03 fixed Intake's vocabulary as booleans and enums, and `score(text, labels) -> Dict[str, float]`
has no home in that type. The seam was a hole shaped like a classifier we decided not to build.

The adapter goes with it rather than surviving in `cognitive_classifier/`: its docstring says it
exists to implement "the InputProcessor SemanticClassifier protocol", it has zero callers, and an
exported adapter to a deleted interface is an invitation to re-derive the interface.

**Recorded so the option is not lost:** if a local, no-network semantic classifier is ever wanted,
the recipe is the research doc's option (c) — MiniLM + a supervised head trained on **minimal
negated pairs**, validated on held-out negated pairs — not plain cosine over exemplars, which
fails the "I do like math" / "I do not like math" acid test by construction. Such a classifier
would back **Perception**, so it would not want this interface anyway.

### Disposition of every consumer

| Consumer | Disposition | Owner |
|---|---|---|
| `cognitive_analyzer/analyzer.py:209` | reads the observation | 16 |
| `perception/gemini_perception.py:149` | reads the observation | 16 |
| `eval/behavioral_eval.py:221`, `eval/perception_eval.py:401` | construct `Utterance(source=TYPED)` (already fixed by 02) | 16 |
| `tutor_loop.py:1358` `processor` property | deleted with its two delegates | 16 |
| `tutor_loop.py:1366` `is_anaphoric_followup` | Intake's `ReferenceReading` | 16 |
| `tutor_loop.py:1370` `is_same_problem_followup` | **inlined** as a private method | 16, then 05 |
| `control.py:669` static `_is_anaphoric_followup` | deleted; reads `observation.reference.anaphors` | 16 |
| `interactive_tester.py` | rewritten against the typed door | 16 |
| `tools/sync_to_pi.py:56` | entry removed | 16 |
| root `tutor_loop.py` | **file deleted** | 16 |
| `CODEBASE_ARCHITECTURE_AND_COUPLING_REPORT.md` | corrected | 16 |
| the two research docs | dated header note, findings untouched | 16 |
| `docs/archive/*` (5 files) | **never touched** | — |

**`is_anaphoric_followup` is not provisional.** 01 hedged it pending ticket 12, but 03 made
`ReferenceReading` a required, non-defaulted slot — Intake must emit anaphor spans on day one
whatever 12 decides about confidence bands. So the detection half has a confirmed home and 13's
deletion does **not** block on 12. `is_same_problem_followup` cannot come: it reads
`session["context"]` and would violate 03's rule 3 (pure of session). It inlines into
`tutor_loop.py` and 05 relocates it from there.

**`control.py` gets a required field.** `InteractionControlRequest` gains
`observation: UtteranceObservation` — **required and non-defaulted**, deliberately diverging from
the `perception: PerceptionObservation | None = None` precedent beside it. `perception` is
optional because a degraded turn legitimately has none; Intake is **total** by ticket 03 and its
phase runs before Perception in every turn, so `| None` would describe an impossible state, and
the first `if request.observation is None:` written against it would be dead code guarding an
impossibility. It also matters here specifically: an optional field invites a
`getattr(..., None)` fallback to the regex this ticket is deleting.

**The dev tester is a migration site, not a casualty.** `interactive_tester.py` is the only
manual REPL against the pipeline and ticket 14's corpora are not a substitute for typing at it.
Two constraints: it goes through the **typed door only** (no private-function pokes), and its
private safety keyword list (`:35-38`) is **deleted rather than migrated** — a second, drifting
safety lexicon inside a dev tool is exactly what ticket 07 spent a ticket eliminating, and the
map already records it inventing a fourth tier vocabulary no producer emits.

### Root duplication: one file, and a stated boundary

Ticket 04 verified (`04:138-149`) that `5b847a1` deleted root `policy_shadow/`, `perception/`,
`runtime/` and `interaction_control/` while `cloud_run_service/` never held the build scripts —
so root `tutor_loop.py` **cannot import at all**, and neither can its seven importers
(`wini_server.py`, `voice_cloud_tutor.py`, `voice_hybrid_runner.py`, `wini_ui_server.py`,
`smoke_test_phase5.py`, `tools/rl_integration_check.py`, `voice/latency_probe.py`). Nothing at
repo root has been runnable since that commit. Confirmed here: none of those four root packages
exists.

**13 deletes root `tutor_loop.py` and nothing else at root** (user, 2026-08-27 — no new ticket;
04 already flagged the cluster and the developer owns it). The remaining byte-identical
duplicates (`wini_server.py`, `session_modes.py`, `math_grade.py`, `learner_state.py`), the seven
orphaned importers and the root `Dockerfile` are **out of scope and explicitly not endorsed**:
that set is a *deploy-surface* decision — the root `Dockerfile` is the artifact a Cloud Run build
would produce, and calling it garbage rather than stale-but-intended needs evidence 13 does not
have. Root `tutor_loop.py` is different only because 13 was already editing it and because a
byte-identical 2600-line twin makes ticket 15's "did the change land" unanswerable.

### `points_to_consider_developer.txt`

Archived to `docs/archive/` with a header naming this ticket. Its rules are dispositioned
individually rather than as a block:

| Rule | Disposition |
|---|---|
| Never softmax / independent per-label thresholds | **Promoted** as a constraint on Perception |
| Do not strip stop words | **Promoted** as a constraint on Perception |
| Chunk compound utterances | **Promoted as an open question for Perception's eval**, not a rule |
| Do not bake subject matter into exemplars | Dies with the exemplar bank (ticket 17) |
| Normalize context-heavy pronouns | **Deleted with prejudice** |

The two promotions land in ticket 18's new architecture document (see below), *not* in
`learner_cognitive_state_architecture.md` as originally recommended — that file is being
archived. Ticket 16's spec carries a pointer and no restatement: they constrain **Perception**,
and filing a Perception constraint inside Utterance Intake's spec puts it where the next person
to change the Gemini schema will not look.

**Compound-utterance chunking is a real gap, not a dead rule** — a turn that both explains and
asks currently gets one signal set — but it is a Gemini-prompt question with no measurement
behind it, so it is filed as an eval question rather than promoted as a rule.

**Pronoun normalization is deleted with prejudice**, reason recorded: it was written for a
bi-encoder that needed the substitution to score at all. Doing it now would overwrite the
learner's actual words before every downstream reader — the mirror image of the NFKC defect
ticket 10 measured and ticket 03 removed. It also contradicts 03 directly: Intake detects
anaphor spans and never resolves them.

### The nine spike tests: deleted, not migrated

**Amends ticket 01's manifest**, which said the 9 tests migrate to `utterance_intake/tests/`.
Ticket 03 changed the contract underneath every one of them — `detect_student_problem` moves
from raw to normalized text, NFKC is gone, and the `dict` return becomes `ProblemReading` — so
each would need rewriting regardless. A rewritten test that keeps its old name and shape is the
likeliest place for an accommodating assertion to survive unnoticed, and one already is:
`test_normalization_preserves_math_equations_and_unicode` comments *"# NFKC normalizes
superscript 2"* and then asserts only `"3x" in norm` (ticket 10, finding A4) — a test written to
accommodate the defect 03 deleted.

13 hands ticket 14 the **cases** as required coverage — the maths-preservation case in
particular, now asserting `x²` survives — and 14 authors the assertions against the new contract.

### What lands now, and in what order

13 is a **manifest**, with two exceptions that land as their own commits, in this order:

1. **Commit the spike as superseded.** `ingest`, `IngestedInput`, `extract_surface_cues`, the
   package `__init__.py`, `tests/test_input_processor.py` and `interactive_tester.py` are
   untracked or uncommitted — they exist only in the working tree and would be unrecoverable.
   One commit buys a permanent record of the design attempt that tickets 01 and 03 were reacting
   against; without it, the reasoning in three resolved tickets points at code that exists
   nowhere.
2. **Delete the seam** (`SemanticClassifier`, `HeuristicSemanticClassifier`,
   `MiniLMSemanticClassifier`, the two `__init__.py` lines).

Everything else waits for `utterance_intake` to exist. The tell that this is the right cut: the
two exceptions delete code with **no** replacement; everything else deletes code with one.

### Handed to ticket 15 — two assertions, deliberately different in kind

1. **Extend ticket 04's AST import guard** with five dead names — `cognitive_input_processor`,
   `SemanticClassifier`, `ProcessedInput`, `InputSignalScores`, `IngestedInput`. Same mechanism,
   no new machinery, same accepted silent-failure risk.
2. **A real runtime assertion that every entry in `sync_to_pi.py`'s `PACKAGES` resolves to a
   directory that exists.** Worth more than its size: a sync manifest naming a deleted directory
   is a *device deploy* failure that no test under `cloud_run_service/` could catch, and it is the
   only consumer in this sweep that references the package by string rather than by import.

### Consequences handed to other tickets

- **01** — manifest amended twice: the 9 tests are deleted rather than migrated, and
  `is_anaphoric_followup` is confirmed (not provisional). Not edited; correction lives here.
- **05** — inherits `is_same_problem_followup` inlined in `tutor_loop.py` rather than in a
  deleted package. 05 already deletes `control.py`'s duplicate; 13 supplies the required
  `InteractionControlRequest` field it reads through.
- **12** — inherits a caller (`control.py`'s drift guard) with **no threshold**, since the
  12-word cutoff leaves with the deleted static method per 03. That is the honest state.
- **14** — inherits the 9 deleted tests as required *cases*, including the maths-preservation
  case now asserting `x²` survives.
- **15** — the two assertions above.
- **16** — inherits the whole manifest, the two promoted Perception rules (as a pointer to 18's
  document), and the consolidated documentation debt below.
- **18 (new)** — the architecture document set; the two promoted rules land there.

### The documentation debt, consolidated — owner: ticket 16

Four resolved tickets each queued a documentation fix as a scattered bullet. They share one
property that makes them dangerous apart and safe together: each is a document that currently
states something **false**, and `CLAUDE.md` is loaded into every session's context, so a stale
gotcha there actively misleads the agent that implements this effort. One section, one owner,
one pass — discharged as a **precondition** of marking `spec.md` `ready-for-agent`, not as a
follow-up.

| Source | Debt |
|---|---|
| 02 | Rewrite the memoization gotcha: no public `normalize_input`, memo keys on `utterance_id` |
| 04 | `CLAUDE.md:67-69, 124-126` document three build scripts deleted by `5b847a1` |
| 11 | Four gotchas to add: `latest_short` confidence is not a confidence score; `DEC-044` never existed; STT v1 has no `asia-south1`; the retired `STT_WRITE_CONFIDENCE_MIN` name and the new `lark` dependency |
| 13 | The coupling report's false *"Ideal Deep Module"* claim; the archived seam; the two promoted Perception rules |
| 18 | The 4-doc lockstep block is replaced by a source-of-truth block |

### Explicitly not decided here

The content of the new architecture document (18); where the five fusions land (05); the
coreference bands (12); the corpus assertions (14); the remaining root-duplicate cluster and the
root `Dockerfile` (out of scope, stated above, owned by the developer).
