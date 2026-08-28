# 07 — Perception schema promotion + inline-boolean rewire slice

**What to build:** The complete intent-ownership path: the deterministic cue regexes are retired, their
judgments become Perception schema labels, and the inline turn-body booleans stop being regex-fed and
become label-fed in place. Session commands are kept out of the cognitive-state math. One owner for
intent instead of a model and a regex voting.

**Blocked by:** 01, 03 (the inline `student_problem` line reads `observation.problem`).

**Status:** ready-for-agent

- [ ] Runtime cue regexes retired in favour of Perception labels per `docs/adr/0001`; four new signal
  labels (38→42): `purpose_question`, `animation_request`, `real_life_request`, `learning_request` (no
  dataset gold yet — recorded gap).
- [ ] `SESSION_CONTROL` route sub-type (`STOP`/`TEST`/`PRACTICE`/`EXPLAIN`) — **not** signal labels
  (must not reach `derive_cognitive_update`/`derive_state_deltas`); `session_modes.mode_cues` + its
  `ModeController` caller retired; `mode_cue=` changes from `text → mode` to `observation → mode`.
- [ ] Topic phrasing: `extract_topic_request`/`is_bare_topic`/`TOPIC_REQUEST_RE` deleted; the structured
  call returns the learner's topic phrasing alongside the resolved concept id.
- [ ] Inline ten-boolean block rewired **in place** (regex arm → label read) — the one kind of change
  that keeps the diff readable; `answer_try` regex arm deleted (`answer_attempt` authoritative);
  `wants_hint`/`fresh_request`/`non_attempt` untouched but now model-fed. `pacing/triage.py` cue imports
  deleted (reads labels; `stt_uncertain` stays legacy, unwired); `wini_server.py` Phase B pre-gate loses
  `is_pure_ack`/`is_question` (accepted billing regression, recorded); `is_same_problem_followup` inlined
  into `tutor_loop.py`; `evidence/grading.py:obvious_non_attempt` stays, add-only.
- [ ] Two constraints promoted onto Perception and recorded (never softmax; do not strip stop words);
  pronoun normalization deleted with prejudice.
- [ ] Billed **local** rebuild chain run and recorded: `build_perception` → `vertex_cache --create` →
  `perception_eval` + `behavioral_eval` (developer ADC, not the CI billed lane).
- [ ] `student_problem`/`learner_problem` reconciliation explicitly **not** done (future fusion layer).
