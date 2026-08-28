# Deterministic intent cues are deleted in favour of Perception's labels

Status: accepted (2026-08-25)

The runtime carried ~20 regex cue predicates (`cognitive_classifier/cues.py`) that judged
learner intent — "is this a question", "is this an acknowledgment", "is this a request for a
hint" — alongside a Gemini 2.5 Flash perception call that already emits 38 structured signal
labels covering ten of those same judgments. The regexes were a second, weaker classifier
running in parallel with the first, and they carried a known defect class: they cannot handle
negation ("I do like math" vs "I do not like math"). We deleted them from the runtime decision
path and made Perception's labels authoritative, promoting the four judgments Perception had
no label for into its schema, plus session-mode commands as a `SESSION_CONTROL` route sub-type
and topic phrasing alongside the resolved concept.

## The safety and nonsense carve-out is deliberate

`is_safety` / `classify_safety` / `is_nonsense` are **not** part of this deletion and must not
be "cleaned up" for consistency later. Two separate reasons:

- **Safety must not depend on a model being reachable.** `perception/interface.py` has a full
  degraded-fallback path; if the child-safety floor lived in the Gemini call, a Vertex outage
  would silently disable it. CLAUDE.md states the rule directly: the deterministic gate must be
  near-total on its own, and the model's safety flag may only *add* recall, never remove it.
  The documented remedy for the lexicon's measured 0.75 first-pass recall is to broaden it and
  re-measure (`eval/perception_eval --gates`), not to replace it.
- **Nonsense is not a semantic problem.** Empty input, pure symbols, and keyboard mash are a
  character-class question. A model is slower and strictly worse at it.

## Considered and rejected

- **A local supervised head (MiniLM or a classifier trained on negated pairs) inside Utterance
  Intake.** Rejected: it adds a *second* model to duplicate the first model's job, inside the
  one module whose defining property is being model-free — and Utterance Intake runs before
  Perception, so a model there costs either an extra round-trip or torch in the cold-start path
  that `min-instances=1` already exists to absorb.
- **Keeping the regexes as a measured recall-only fallback** ("may only add, never remove",
  the rule already proven on safety). Rejected in favour of outright deletion: the recall the
  fallback arm was buying is a `PERCEPTION_SIGNAL_THRESHOLD` calibration problem, and keeping
  a shadow classifier alive to paper over threshold miscalibration hides the real defect.
- **Putting the four session-mode commands in the signal-label catalog** with `anxiety` and
  `cognitive_overload`. Rejected: a session command is not a cognitive state, and signals flow
  into `derive_cognitive_update` / `derive_state_deltas`, where "test me" has no business
  moving learner state. They became a route sub-type instead.

## Consequences

- **The regexes still exist, offline.** `CUE_NAMES`, `cue_features`, `cue_matrix` and their
  nine regexes stay in `cognitive_classifier/cues.py` as model-build infrastructure: they are
  the gold rules for `curate_dataset.py` and their vector width is baked into the shipped
  logreg. Deleting them from the *runtime* is what leaves the dataset build untouched. Do not
  "finish the job" by removing them from the model package.
- **Recall now rests entirely on `PERCEPTION_SIGNAL_THRESHOLD`.** Per-label recall must be
  measured with `eval/behavioral_eval.py` wherever a regex arm was removed.
- **The four new signal labels have no dataset gold**, so the behavioral eval has no ground
  truth for them until the dataset is extended.
- **The §5.1 rule "'stop the test' must not read as a test request"** was enforced by check
  order in `session_modes.mode_cues`. With a single-valued enum from the model, that ordering
  leaves the code entirely and survives only as an eval assertion.
- **One caller cannot follow this rule.** The Part 15 Phase B speculative grader pre-gate
  (`wini_server.py:574`) runs *concurrently* with the perception call by design, so it cannot
  read perception labels. Until a future layer absorbs it, every armed `pending_check` fires a
  billed `judge_answer` call on pure acks and bare questions.
