# Fix the Input Layer's boundary and name

Status: resolved
Type: grilling
Blocked by: —

## Question

What is this module called, where does it live, and exactly which existing files, functions,
and responsibilities does it absorb?

The coarse boundary is fixed (map, "Boundary"): the deterministic text layer is in, Gemini
perception is out. This ticket turns that into a file-level manifest.

Specific decisions to close:

- **Name.** "Input processor" is already taken by `cognitive_input_processor/`, a package
  that is ~90% dead code. Does the new module reuse that package name (and its directory),
  take a new name, or does `cognitive_input_processor` become an internal of it?
- **Placement.** `cloud_run_service/<name>/`, sibling to `perception/` and
  `interaction_control/`? The precedent map put every Feature Module at that level with a
  single typed public interface and a `tests/` subdirectory.
- **Does it own `cues.py`?** `cognitive_classifier/cues.py` currently lives inside the
  *model* package because `cue_matrix` feeds the shipped logreg. Ticket 04 decides the split
  mechanics; this ticket decides whether the standalone predicates are Input Layer property
  at all.
- **Does it own `session_modes.mode_cues`?** It is a raw-text cue (`session_modes.py:54`)
  consumed by `interaction_control` and `runtime/legacy_adapter.py:99`.
- **Does it own the front gate?** `perception/gates.py` is pure, model-free, and already
  imported into `tutor_loop.py:115` as `_front_gate`. Moving it out of `perception/` splits
  a package that currently reads coherently ("the front door"). Is that the right cut?
- **Is it a Feature Module or a library?** A Feature Module in this repo means: one typed
  public interface, `ModuleOutcome`/`StateChange`/`FailureSignal`, sequenced by
  `TurnCoordinator`, no cross-module implementation imports. A library means: pure functions
  other modules call directly. The answer changes everything downstream — an Input Layer that
  is a coordinator phase gets its own `TurnPhase`; one that is a library does not.

Use `/codebase-design` for the seam placement and `/domain-modeling` to fix the vocabulary
(the repo currently uses "input processor", "front gate", "cue", "perception", and "signal"
with overlapping meanings).

---

## Resolution (2026-08-25, /grilling + /domain-modeling)

**Name.** `Utterance Intake`, package `cloud_run_service/utterance_intake/`. "Input Layer" was
scaffolding vocabulary and does not survive into code — `CONTEXT.md` names capabilities, not
layers, and "Input" collides with `Turn Input`. `cognitive_input_processor/` is deleted, not
renamed. Glossary entries for **Utterance** and **Utterance Intake** are written into
`CONTEXT.md`.

**Shape.** A Feature Module with its own `TurnPhase`, sequenced by `TurnCoordinator`
**before** `PERCEPTION_AND_PRIOR_GRADING`, exposing **one** typed public interface. Perception
consumes its observation instead of computing `normalized_text` / `problem_cue` itself, which
retires the two independent `InputProcessor` constructions
(`cognitive_analyzer/analyzer.py:209`, `perception/gemini_perception.py:149`).
A second, pure-predicate door was considered and rejected: after the cue deletions below, it
has no consumers. It may be reintroduced only if a future layer demands it.

**Organizing rule for the cues.** *The regexes survive as offline model-build infrastructure;
they are deleted from the runtime decision path.* This is what leaves `curate_dataset.py`'s
gold rules and the shipped logreg widths untouched.

### File-level manifest

**Moves into `utterance_intake/`**
- `normalize_input`, `detect_student_problem` -- from `cognitive_input_processor/input_processor.py`
- `is_anaphoric_followup` -- same file (**provisional**: ticket 12 owns coreference)
- `is_safety`, `classify_safety`, `is_nonsense` -- from `perception/gates.py`
- **new:** PII detection (docx S11), STT uncertainty (S9), six-route safety taxonomy (S14)

**Stays in `cognitive_classifier/cues.py`** -- build-time only, zero runtime importers
- `CUE_NAMES`, `cue_features`, `cue_matrix` and their 9 regexes
- `is_question` (called by `cue_features`), `is_pure_ack` (used by
  `dataset/generate_t2_t3_samples.py:43`), `INTERROGATIVE_FIRST`

**Stays in `perception/gates.py`**
- `gate()` -- the `RouteResult` constructor. Reads the intake observation rather than raw
  text. Interaction Control keeps calling it unchanged, preserving precedent ticket 15's
  ownership of the front-gate *decision*. `RouteResult` never enters Utterance Intake's
  vocabulary, so the dependency stays one-way.

**Deleted from the runtime path** -- Perception's existing labels are authoritative
- `is_question` -> `question`; `is_pure_ack` -> `acknowledgment`;
  `is_clarification_request` -> `simplification_request`;
  `is_visualization_request` -> `request_representation` / `representation_shift`;
  `is_answer_attempt` -> `answer_attempt`; `wants_different_topic` -> `topic_shift`;
  `HINT_RE` -> `request_hint`; `EXAMPLE_RE` -> `example_request`;
  `SELF_CORRECTION_RE` -> `self_correction`; `NEXT_RE` -> `ready_for_next`

**Promoted to Perception -- 4 new signal labels** (38 -> 42)
- `purpose_question`, `animation_request`, `real_life_request`, `learning_request`

**Promoted to Perception -- `SESSION_CONTROL` route sub-type**, emitted by the Gemini call
- `STOP` / `TEST` / `PRACTICE` / `EXPLAIN`. Deliberately **not** signal labels: a session
  command is not a cognitive state and must not reach `derive_cognitive_update` /
  `derive_state_deltas`. `session_modes.mode_cues` becomes obsolete; `mode_cue=` in
  `InteractionControlDependencies` changes from `text -> mode` to `observation -> mode`.

**Promoted to Perception -- topic phrasing**
- `extract_topic_request` / `is_bare_topic` / `TOPIC_REQUEST_RE` deleted. The structured call
  returns the learner's topic phrasing alongside the resolved concept id. `TOPIC_REQUEST_RE`
  was the only cue carrying a negation guard (`_NEG_BEFORE`) -- the tell that it was already
  a semantic judgment wearing a regex.

**Deleted outright**
- `cognitive_input_processor/` (dead types per ticket 13). The uncommitted working-tree spike
  (`ingest`, `IngestedInput`, `extract_surface_cues`) is superseded; its 9 tests migrate.

### Consequences handed to other tickets

- **Ticket 05** narrows sharply. Of the 10 inline booleans at `tutor_loop.py:2242-2305`, only
  3 are pure raw-text (`wants_why`, `wants_animation`, `wants_real_life`), 2 never touch the
  text (`wants_hint`, `fresh_request`), and 5 are fusions. Utterance Intake owns **pure text
  only**; fusions are consumer work. With the regex arms deleted, the 5 fusions collapse into
  plain perception reads.
- **Ticket 14** must carry the S5.1 assertion *"'stop the test' must not read as a test
  request"*. It is enforced today by check-order in `mode_cues`; with a single-valued enum
  from the model that ordering leaves the code and must become an eval case.
- **Ticket 15** gains a required check: `cue_matrix` output must be **bit-exact** on the
  frozen corpus across this refactor, and per-label recall must be measured where a regex
  arm was deleted (`eval/behavioral_eval.py`).
- **CLAUDE.md 4-doc lockstep is triggered** by the schema change:
  `learner_cognitive_state_architecture.md` is the source of truth for signals, and
  `model_dataset_architecture_report.md` carries the label counts. Rebuild chain:
  `build_perception` -> `vertex_cache --create` -> `perception_eval --build --gates` +
  `behavioral_eval --hardened --run` (billed).
- **New labels have no dataset gold**, so the behavioral eval has no ground truth for the 4
  promoted signals until the dataset is extended.

### Open dependency (accepted risk, not resolved)

The Part 15 Phase B speculative grader pre-gate (`wini_server.py:574`) runs **concurrently
with** the perception call by design, so it structurally cannot read perception labels.
Deleting `is_pure_ack` / `is_question` from it means every armed `pending_check` fires a
billed `judge_answer` call on pure acks and bare questions. User's call (2026-08-25): a future
layer absorbs this. Recorded here as an **open dependency with a cost consequence**, owned by
that layer.

---

## Note from ticket 07 (2026-08-26) — not an amendment

01's boundary held: Utterance Intake still owns safety **detection**, and `gate()` still
stays put. What moved is the **verdict**. Ticket 07 made a dedicated Gemini call in a new
`cloud_run_service/child_safety/` package the primary safety detector, and demoted the regex
lexicon to a degraded-mode outage net. So Intake's safety reading (renamed `SafetySignals`,
lexicon-only) is computed every turn but is **not** the verdict on a healthy turn — it is
consumed only when the model call fails, and by the divergence monitor.

Consequence for 01's manifest: `perception/gates.py` is still in scope and still moves as
planned; `child_safety/` is **new code**, a sibling of `perception/`, and is not part of the
Utterance Intake module. See `docs/architecture/SAFETY_ROUTE_TAXONOMY.md` §1, §8, §16.
