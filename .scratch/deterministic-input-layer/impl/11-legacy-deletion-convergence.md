# 11 — Legacy deletion (convergence)

**What to build:** With every consumer now reading the observation (slices 02–07), the legacy channels
and the dead code they fed are removed in one mechanical sweep — so "is there one normalizer in the
runtime" answers yes and "did the change land" is answerable at all. Because every behavior was verified
incrementally in its own slice, this convergence is low-risk deletion, not a big-bang integration.

**Blocked by:** 02, 03, 04, 05, 06, 07.

**Status:** ready-for-agent

- [ ] Both legacy channels deleted: `interaction["text"]` (all six readers migrated) and
  `trusted_observations["stt_confidence"]`. `interaction` keeps `answer_budget` / `allow_topic_shift`.
- [ ] Deleted entire: `cognitive_input_processor/` (incl. `process`, `_heuristic_signal_scores`,
  `_merge_scores`, `_extract_candidate_concepts`, `_contains_formula`, `HeuristicSemanticClassifier`,
  `InputSignalScores`, `ProcessedInput`, `IngestedInput`); the `SemanticClassifier` seam (Protocol,
  heuristic + MiniLM adapters, the two `cognitive_classifier/__init__.py` exports); the dead relatedness
  chain (`concept_relates_to_topic` + `_concept_relates_to_topic` + `_concept_chapters`; rule survives as
  prose in the handover doc).
- [ ] Root `tutor_loop.py` deleted (byte-identical, unimportable twin); `tools/sync_to_pi.py`
  `cognitive_input_processor` entry removed (string reference); the nine spike tests deleted, their cases
  inherited as required coverage in the slice-09 corpora.
- [ ] `interactive_tester.py` rewritten against the typed door only, its private safety keyword list
  deleted; `eval/behavioral_eval.py` + `eval/perception_eval.py` build `Utterance(source=TYPED)` not an
  `InputProcessor`; `pedagogy/tests/test_pedagogy.py` builds `PedagogyObservation` from labels.
- [ ] `cognitive_classifier/cues.py` stays **byte-identical** (call sites removed elsewhere; header-only
  from slice 01); the `cognitive_classifier.cues` import guard and the `sync_to_pi` PACKAGES-resolve
  assertion hold.
- [ ] Standing set stays green throughout; the closed+symmetric expected-diff manifest is complete and
  every listed behavior change accounted for.
