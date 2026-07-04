# Audit Second-Pass Fix Summary

- Source/output: `exemplar_dataset_10000_fixed.json` (backup: `exemplar_dataset_10000_fixed.backup_preaudit2.json`)
- Rows total: 10000
- Rows changed: 705
- Action changes: 209
- Label-only changes: 496

## Action changes by rule

- overload->encourage: 48
- everyday->analogous_example: 46
- manipulative->repr_translation: 31
- confusion->explain: 20
- visual->repr_translation: 17
- numeric_example->worked_example: 12
- utility->explain: 11
- advance->resume_state: 8
- giveup->encourage: 6
- prereq->bridge_recap: 6
- advance->transfer_problem: 4

## Label operations

- `-physical`: 325
- `+physical`: 96
- `+confusion`: 73
- `-self_correction`: 40
- `+representation_shift`: 35
- `+request_representation`: 35
- `-curiosity`: 23
- `+example_request`: 16
- `-representation_shift`: 11
- `-request_representation`: 11
- `-verbal_analogy`: 8
- `-high_confidence`: 1

## Action transitions

- EXPLAIN -> ENCOURAGE: 52
- WORKED_EXAMPLE -> ANALOGOUS_EXAMPLE: 41
- EXPLAIN -> REPRESENTATION_TRANSLATION: 39
- SOCRATIC_Q -> EXPLAIN: 20
- REPRESENTATION_TRANSLATION -> EXPLAIN: 11
- EXPLAIN -> WORKED_EXAMPLE: 9
- VERBAL_ANALOGY -> REPRESENTATION_TRANSLATION: 7
- SOCRATIC_Q -> BRIDGE_RECAP: 6
- EXPLAIN -> RESUME_STATE: 6
- SOCRATIC_Q -> ANALOGOUS_EXAMPLE: 5
- SOCRATIC_Q -> WORKED_EXAMPLE: 3
- EXPLAIN -> TRANSFER_PROBLEM: 3
- METACOGNITIVE_REFLECT -> RESUME_STATE: 1
- QUIZ -> TRANSFER_PROBLEM: 1
- QUIZ -> RESUME_STATE: 1
- METACOGNITIVE_REFLECT -> ENCOURAGE: 1
- SOCRATIC_Q -> ENCOURAGE: 1
- SOCRATIC_Q -> REPRESENTATION_TRANSLATION: 1
- QUIZ -> REPRESENTATION_TRANSLATION: 1

## New target_policy_action distribution

- EXPLAIN: 3837
- REPRESENTATION_TRANSLATION: 2208
- ENCOURAGE: 956
- SOCRATIC_Q: 841
- REVIEW: 604
- BRIDGE_RECAP: 352
- RESUME_STATE: 257
- WORKED_EXAMPLE: 209
- METACOGNITIVE_REFLECT: 177
- QUIZ: 133
- TRANSFER_PROBLEM: 118
- VERBAL_ANALOGY: 106
- ANALOGOUS_EXAMPLE: 92
- REQUEST_HINT: 48
- MISCONCEPTION_PROBE: 37
- ISOMORPHIC_PRACTICE: 25