# T2 + T3 supplementary rows

- Source/output: `exemplar_dataset_10000_fixed.json` (backup: `exemplar_dataset_10000_fixed.backup_pret2t3.json`)
- Existing rows: 10000
- Added rows:    800
- New total:     10800

Added rows carry `split: "train"` (per CLAUDE.md: supplementary rows
never enter val/test of the frozen 10k splits).

## Per-label counts

- acknowledgment (T2):       300
- answer_attempt:            100
- self_correction:           100
- high_confidence:           100
- hint_dependency:           100
- representation_shift:      100

## Action distribution on added rows

- METACOGNITIVE_REFLECT: 303
- REQUEST_HINT: 100
- REPRESENTATION_TRANSLATION: 100
- SOCRATIC_Q: 70
- RESUME_STATE: 68
- TRANSFER_PROBLEM: 50
- EXPLAIN: 39
- BRIDGE_RECAP: 38
- REVIEW: 23
- QUIZ: 9