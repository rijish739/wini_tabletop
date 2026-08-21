# Policy Shadow Model — Evaluation Report

Actions: 14 (canonicalized from 27 raw values; 473 rows dropped)
Features: emb(384) + label_scores(38) + update(10)

| model | test top-1 | test top-2 |
|---|---|---|
| majority class | 0.4053 | - |
| embedding only | 0.6708 | 0.8220 |
| full features **(shipped)** | 0.6831 | 0.8416 |

## Per-action test metrics (shipped)

| action | support | precision | recall | F1 |
|---|---|---|---|---|
| EXPLAIN | 394 | 0.689 | 0.794 | 0.738 |
| REPRESENTATION_TRANSLATION | 214 | 0.833 | 0.818 | 0.825 |
| ENCOURAGE | 92 | 0.693 | 0.565 | 0.623 |
| SOCRATIC_Q | 80 | 0.500 | 0.550 | 0.524 |
| REVIEW | 62 | 0.471 | 0.387 | 0.425 |
| BRIDGE_RECAP | 37 | 0.706 | 0.649 | 0.676 |
| WORKED_EXAMPLE | 20 | 0.692 | 0.450 | 0.545 |
| TRANSFER_PROBLEM | 19 | 0.600 | 0.158 | 0.250 |
| METACOGNITIVE_REFLECT | 18 | 0.421 | 0.444 | 0.432 |
| ANALOGOUS_EXAMPLE | 12 | 0.667 | 0.667 | 0.667 |
| QUIZ | 11 | 0.222 | 0.182 | 0.200 |
| VISUAL_ANALOGY | 8 | 1.000 | 0.250 | 0.400 |
| ISOMORPHIC_PRACTICE | 3 | 0.000 | 0.000 | 0.000 |
| MISCONCEPTION_PROBE | 2 | 0.000 | 0.000 | 0.000 |

Build time: 78s

SHADOW MODE: rules decide; suggestions are logged for comparison (plan Part 5).