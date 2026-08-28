# Decide the cues.py split under the CUE_NAMES constraint

Status: resolved
Type: grilling
Blocked by: 01

## Question

`cognitive_classifier/cues.py` (~550 lines) holds two different things that a naive move
would fuse or break. How is it split?

**Thing one — the feature vector.** `CUE_NAMES` (`cues.py:87`), `cue_features` (`:527`),
`cue_matrix` (`:545`). Imported by `cognitive_classifier/classifier.py:31`,
`policy_shadow/shadow.py:79`, and `eval/behavioral_eval.py:228`. CLAUDE.md, verified gotcha:
*"`CUE_NAMES` length is baked into the shipped logreg widths — adding a cue feature requires
rebuilding BOTH the classifier bank and the policy shadow."* This half belongs to the model
package and must not move.

**Thing two — ~20 standalone runtime predicates**, added over time and explicitly *not* in
`CUE_NAMES`: `is_clarification_request` (`:146`), `is_visualization_request` (`:191`),
`is_purpose_question` (`:218`), `is_animation_request` (`:242`), `is_real_life_request`
(`:265`), `is_learning_request` (`:287`), `extract_topic_request` (`:332`),
`wants_different_topic` (`:376`), `is_bare_topic` (`:400`), `is_answer_attempt` (`:424`),
`is_stop_test_request` (`:476`), `is_test_request` (`:483`), `is_practice_request` (`:489`),
`is_explain_request` (`:495`), `is_pure_ack` (`:501`), `is_question` (`:515`). This half is
Input Layer semantics wearing a model package's coat.

The tangle: `is_answer_attempt` at `:414` calls `is_question`, `is_pure_ack`, `ANSWER_RE`,
`HINT_RE` — and `is_pure_ack` is also a **gold-rule input to the dataset**
(`cognitive_classifier/label_space.py:32-33`: `is_pure_ack(utt) ⇒ ensure acknowledgment ∧
remove confusion/low_confidence`, and `dataset/generate_t2_t3_samples.py:43`). Changing
`is_pure_ack` changes the curated dataset and therefore the shipped bank.

Decisions to close:

- Split the file, move it wholesale, or leave it and re-export from the Input Layer?
- If split: which side owns the shared regexes (`ANSWER_RE`, `HINT_RE`, `NEXT_RE`,
  `SELF_CORRECTION_RE` — `pacing/triage.py:9` imports the raw regex objects, not predicates)?
- What is the rule that stops a future edit to a predicate from silently invalidating the
  bank via `is_pure_ack`? A test? A comment? A hard dependency direction?
- The seven consumers (`tutor_loop`, `interaction_control`, `pedagogy`, `pacing`,
  `session_modes`, `runtime/legacy_adapter`, `wini_server`) — do they migrate to the Input
  Layer's interface, or keep importing predicates directly? The precedent map banned
  cross-module implementation imports.
- Does the Input Layer take a dependency on `numpy`? `cues.py` imports it for `cue_matrix`
  only; a split could keep the Input Layer dependency-free, which matters for ticket 14.

---

## Resolution (2026-08-26, /grilling)

**The answer to "how is it split" is: it isn't.** `cues.py` is not Utterance Intake's
property and never becomes it. The whole file — feature vector and predicates together —
is retired by a **later layer** along with the policy shadow. This effort deletes only
*call sites*; the file itself is not touched.

### Premise corrections (verified against code, 2026-08-26)

Three of this ticket's premises, inherited from ticket 01's manifest, are false. Ticket 01
is deliberately **not** amended (user decision) — the correction of record lives here.

1. **The feature vector is NOT build-time.** `cue_matrix` runs on the hot path every turn:
   `classifier.py:185` calls it inside `classify()`, which `CognitiveAnalyzer.analyze`
   calls at `cognitive_analyzer/analyzer.py:229`; `policy_shadow/shadow.py:79` calls it
   again from `suggest()`, unconditionally, at `tutor_loop.py:2463` — and that second
   result is only *logged*. 01's "build-time only, zero runtime importers" is wrong.
2. **The build scripts are gone.** `cognitive_classifier/build_bank.py`,
   `cognitive_classifier/curate_dataset.py` and `policy_shadow/build_policy.py` were
   deleted by `5b847a1` ("remove root duplicate modules") — but `cloud_run_service/` never
   held copies, so they were lost, not de-duplicated. Recoverable at `5b847a1^`.
   `models/exemplar_classifier` and `models/policy_shadow` are therefore **unreproducible**,
   and CLAUDE.md:124-126 still documents all three as quick commands.
   The recovered `curate_dataset.py:42` confirms the gold-rule set:
   `EXAMPLE_RE, HINT_RE, MODALITY_RE, SIMPLIFY_RE, is_pure_ack, is_question`.
3. **The numpy question is moot.** Utterance Intake imports nothing from
   `cognitive_classifier`, so it is numpy-free by construction (now enforced, see Guards).

### What this effort does

Delete the **call sites** listed in 01's delete set, across the seven consumers. `cues.py`
stays **byte-identical**, leaving `classifier.py`, `shadow.py` and
`dataset/generate_t2_t3_samples.py:43` as its only importers.

Two call-site details the manifest did not name:

- **`mode_cues` dies from the inside too.** `ModeController` calls it at
  `session_modes.py:176`, not just the external callers — that call becomes an observation
  read. The other 343 lines of `session_modes.py` survive.
- **The Phase B pre-gate loses its predicates now** (`wini_server.py:574`). 01 parked the
  cost; this ticket spends it. Every armed `pending_check` now fires a billed
  `judge_answer` on pure acks and bare questions. Accepted, 2026-08-26: not this layer's
  problem, revisited by the layer that owns the speculative grader. Consequence: the import
  guard below needs **no allowlist**.

Rejected: pruning the predicates out of `cues.py` (edits the most rebuild-sensitive file in
the repo with no `build_bank.py` left to re-sync the head, for a file that dies anyway), and
deleting the file now (drags the classifier/shadow retirement into this effort —
`analysis["scores"]` feeds `derive_cognitive_update`/`derive_state_deltas`, so that is a
state-math decision, not a cleanup).

### Deferred to the next layer — open, owner TBD

Recorded in **two** places: a new open ticket in this map, and a header comment in
`cues.py` itself (the file an agent will be looking at when it can do damage).

Scope is **narrower than "delete `cognitive_classifier/`"**: the retirement is the **9-cue
vector + the policy shadow**. `classifier.py` survives — `concept_resolver/resolver.py:29`
imports `score_labels_knn`, `hope_detector/detector.py:21` imports `MODEL_NAME`, and
CLAUDE.md keeps both on MiniLM deliberately. That layer must also settle: removing 9 dims
from a head whose weights were fit *with* them requires a re-fit or a zero-fill, and no
build script exists to do it.

### Guards

- **AST import guard**, in `utterance_intake/tests/`, two assertions, no allowlist:
  (1) `utterance_intake` imports stdlib only; (2) no module outside `cognitive_classifier/`
  and `policy_shadow/` imports `cognitive_classifier.cues`.
- **Header comment on `cues.py`**, ~6 lines: frozen, why, rebuild path deleted, recovery
  SHA `5b847a1^`.
- **No golden test** (decided 2026-08-26, against recommendation). Accepted risk, stated
  plainly because the reasoning for it ("let it crash") does not hold: a future edit to a
  cue regex **raises nothing**. The vector keeps its shape, one float changes, the logreg
  head still scores — silently differently, on some turns, in pedagogy decisions. There is
  no crash, no failing test, no log line, and with the build scripts gone no way to re-fit
  the head afterward. The header comment is the only tripwire.

### Tests

`pedagogy/tests/test_pedagogy.py` is rewritten to build `PedagogyObservation` from
Perception labels directly (it already accepts `signals=()`); root `test_session_modes.py`
is deleted with `mode_cues`. Tests are **not** exempt from the import guard — a test suite
is a consumer, and exempting it means the guard does not guard.

### Pre-effort commit (delete-only, before this effort starts)

Root `tutor_loop.py`, `session_modes.py`, `wini_server.py`, `test_session_modes.py` and the
root `Dockerfile`. Not "duplicates" — **provably dead**: the root tree contains none of
`policy_shadow`, `cognitive_classifier`, `perception`, `pacing`, `pedagogy`, `runtime`,
`interaction_control`, while root `tutor_loop.py:48` does a top-level
`from policy_shadow import PolicyShadow`. Root `tutor_loop.py` cannot import; root
`wini_server.py` cannot start; the root `Dockerfile` that runs it (`COPY . .` +
`CMD python -u wini_server.py`, last touched `8343074`, before the `19b3372`
`cloud_run_service` snapshot) builds an unstartable image. The four Python files are
byte-identical to their `cloud_run_service/` twins (`diff -q`, verified).

Root `run_wini_package.sh` is **left in place**: `Wini.desktop` points at
`/home/winipi5/cloud_tutor/cloud-CLI/run_wini_package.sh`, a device checkout whose layout
is not verifiable from here, and unlike the `Dockerfile` it is inert. Flagged in the
deferred ticket.

### Provenance policy

The three lost build scripts stay deleted; the shipped artifacts are recorded as
unreproducible, with `5b847a1^` as the recovery point. Restoring build scripts for a head
that is being retired is motion, not progress. `dataset/generate_t2_t3_samples.py` (the
last non-model importer of `is_pure_ack`) is left alone — it is a one-shot generator whose
800 rows are already in `_fixed.json`; it dies with the file.

### Consequences handed to other tickets

- **Ticket 15:** 01's *"`cue_matrix` must be bit-exact on the frozen corpus"* is **dropped**
  — trivially green, because the file is untouched by design. It is replaced by the import
  guard's second assertion, which can actually fail during this effort. 01's other handoff
  — per-label `behavioral_eval` recall wherever a regex arm was deleted — is unchanged and
  still real work.
- **Ticket 13:** unaffected. The root-duplicate sweep is explicitly *not* 13's (13 is scoped
  to `input_processor.py`'s dead members and the `SemanticClassifier` seam).
- **Ticket 16:** the spec must carry the deferred-layer ticket, the accepted billing
  regression, and the accepted silent-failure risk — none of them are implementation detail.
- **CLAUDE.md:** lines 67-69 and 124-126 document three scripts that no longer exist. Not
  fixed here; the lockstep pass owns it.
