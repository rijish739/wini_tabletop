# Policy Shadow Model — Evaluation Report

Actions: 15 (canonicalized from 27 raw values; 9 rows dropped)
Features: emb(384) + label_scores(37) + update(10)

| model | test top-1 | test top-2 |
|---|---|---|
| majority class | 0.1956 | - |
| embedding only | 0.5386 | 0.7302 |
| full features **(shipped)** | 0.5577 | 0.7452 |

## Per-action test metrics (shipped)

| action | support | precision | recall | F1 |
|---|---|---|---|---|
| REPRESENTATION_TRANSLATION | 195 | 0.707 | 0.805 | 0.753 |
| EXPLAIN | 113 | 0.461 | 0.628 | 0.532 |
| ENCOURAGE | 110 | 0.725 | 0.718 | 0.721 |
| SOCRATIC_Q | 105 | 0.467 | 0.533 | 0.498 |
| WORKED_EXAMPLE | 84 | 0.468 | 0.619 | 0.533 |
| MISCONCEPTION_PROBE | 69 | 0.463 | 0.275 | 0.345 |
| VISUAL_ANALOGY | 68 | 0.479 | 0.338 | 0.397 |
| METACOGNITIVE_REFLECT | 51 | 0.552 | 0.314 | 0.400 |
| TRANSFER_PROBLEM | 41 | 0.647 | 0.537 | 0.587 |
| BRIDGE_RECAP | 38 | 0.424 | 0.368 | 0.394 |
| ANALOGOUS_EXAMPLE | 35 | 0.435 | 0.571 | 0.494 |
| REVIEW | 33 | 0.552 | 0.485 | 0.516 |
| QUIZ | 28 | 0.562 | 0.321 | 0.409 |
| ISOMORPHIC_PRACTICE | 15 | 1.000 | 0.067 | 0.125 |
| SOCRATIC_COUNTEREXAMPLE | 12 | 0.250 | 0.083 | 0.125 |

Build time: 86s

SHADOW MODE: rules decide; suggestions are logged for comparison (plan Part 5).