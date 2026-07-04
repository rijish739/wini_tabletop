# Policy Shadow Model — Evaluation Report

Actions: 14 (canonicalized from 27 raw values; 473 rows dropped)
Features: emb(384) + label_scores(38) + update(10)

| model | test top-1 | test top-2 |
|---|---|---|
| majority class | 0.4053 | - |
| embedding only | 0.6698 | 0.8210 |
| full features **(shipped)** | 0.6800 | 0.8436 |

## Per-action test metrics (shipped)

| action | support | precision | recall | F1 |
|---|---|---|---|---|
| EXPLAIN | 394 | 0.675 | 0.802 | 0.733 |
| REPRESENTATION_TRANSLATION | 214 | 0.834 | 0.822 | 0.828 |
| ENCOURAGE | 92 | 0.684 | 0.565 | 0.619 |
| SOCRATIC_Q | 80 | 0.518 | 0.550 | 0.533 |
| REVIEW | 62 | 0.490 | 0.387 | 0.432 |
| BRIDGE_RECAP | 37 | 0.742 | 0.622 | 0.676 |
| WORKED_EXAMPLE | 20 | 0.636 | 0.350 | 0.452 |
| TRANSFER_PROBLEM | 19 | 0.333 | 0.053 | 0.091 |
| METACOGNITIVE_REFLECT | 18 | 0.471 | 0.444 | 0.457 |
| ANALOGOUS_EXAMPLE | 12 | 0.636 | 0.583 | 0.609 |
| QUIZ | 11 | 0.222 | 0.182 | 0.200 |
| VISUAL_ANALOGY | 8 | 1.000 | 0.125 | 0.222 |
| ISOMORPHIC_PRACTICE | 3 | 0.000 | 0.000 | 0.000 |
| MISCONCEPTION_PROBE | 2 | 0.000 | 0.000 | 0.000 |

Build time: 115s

SHADOW MODE: rules decide; suggestions are logged for comparison (plan Part 5).