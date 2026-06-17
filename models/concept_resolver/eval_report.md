# Concept Resolver — Evaluation Report

Dataset: `exemplar_dataset_10000_curated.json` · concepts in store: 108 · bank: 5250 explicit train rows (108 concepts seen)
Frozen splits: train 8399 / val 1049 / test 1049 (shared with Part 1)
Shipped: **logreg** (alpha=0.3, k=16, tau=0.02)

| candidate | val combined | test top1(rank) | test top3(rank) | test top1(final) | abstain P | abstain R | abstain F1 |
|---|---|---|---|---|---|---|---|
| blend | 0.8974 | - | - | - | - | - | - |
| logreg **(shipped)** | 0.9081 | - | - | - | - | - | - |

## Shipped-method test metrics

- top-1 accuracy (ranking, explicit rows): **0.8939**
- top-3 accuracy (ranking, explicit rows): **0.9641**
- top-1 after abstain rule: **0.8939**
- abstain on INHERIT rows: P 0.9517 / R 0.9842 / F1 **0.9677**
- combined: **0.9308**
- previously uncovered concepts (Qwen-generated rows, 50 test rows): top-1 **0.8600**

Build time: 138s