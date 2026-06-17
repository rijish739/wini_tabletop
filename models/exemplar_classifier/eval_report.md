# Exemplar Cognitive Classifier — Evaluation Report

Dataset: `exemplar_dataset_10000_curated.json` · rows used: 11331 (8002 original + 1331 augmented in train) · canonical labels: 37
Split: train 9333 / val 999 / test 999 (seed 42; test/val 100% original rows)
Embedder: `sentence-transformers/all-MiniLM-L6-v2` (frozen, normalized) · selected scorer = **knn+logreg** (k=8, m=3) · logreg uses 9 cue features · thresholds: 5-fold OOF, clamp (0.1, 0.9)

## Scorer comparison (thresholds from OOF train; selection by val macro-F1)

| scorer | val micro-F1 | val macro-F1 | test micro-F1 | test macro-F1 |
|---|---|---|---|---|
| knn | 0.7183 | 0.5582 | 0.6995 | 0.5267 |
| evidence | 0.5131 | 0.3563 | 0.5188 | 0.3465 |
| logreg | 0.7768 | 0.6302 | 0.7691 | 0.6168 |
| knn+logreg **(shipped)** | 0.7883 | 0.6435 | 0.7747 | 0.6177 |
| evidence+logreg | 0.7809 | 0.6381 | 0.7647 | 0.6094 |

## Per-label test metrics (shipped scorer)

| label | support | precision | recall | F1 | threshold |
|---|---|---|---|---|---|
| question | 773 | 1.000 | 0.994 | 0.997 | 0.51 |
| confusion | 402 | 0.752 | 0.821 | 0.785 | 0.38 |
| low_confidence | 245 | 0.796 | 0.702 | 0.746 | 0.42 |
| procedural_focus | 196 | 0.657 | 0.724 | 0.689 | 0.36 |
| curiosity | 177 | 0.746 | 0.831 | 0.786 | 0.33 |
| request_representation | 172 | 0.875 | 0.814 | 0.843 | 0.36 |
| frustration | 155 | 0.675 | 0.845 | 0.751 | 0.32 |
| anxiety | 137 | 0.667 | 0.701 | 0.683 | 0.33 |
| skepticism | 132 | 0.683 | 0.735 | 0.708 | 0.29 |
| shortcut_seeking | 125 | 0.638 | 0.648 | 0.643 | 0.36 |
| physical | 111 | 0.912 | 0.937 | 0.924 | 0.34 |
| disengagement | 100 | 0.653 | 0.660 | 0.657 | 0.32 |
| cognitive_overload | 96 | 0.618 | 0.708 | 0.660 | 0.29 |
| conflict | 86 | 0.764 | 0.791 | 0.777 | 0.26 |
| self_monitoring | 82 | 0.677 | 0.512 | 0.583 | 0.23 |
| topic_shift | 79 | 0.551 | 0.544 | 0.548 | 0.23 |
| transfer_attempt | 71 | 0.647 | 0.775 | 0.705 | 0.24 |
| graphical | 65 | 0.726 | 0.692 | 0.709 | 0.41 |
| diagrammatic | 61 | 0.618 | 0.689 | 0.651 | 0.35 |
| ready_for_next | 61 | 0.745 | 0.623 | 0.679 | 0.29 |
| simplification_request | 54 | 1.000 | 1.000 | 1.000 | 0.45 |
| verbal_analogy | 50 | 0.729 | 0.700 | 0.714 | 0.28 |
| example_request | 47 | 0.944 | 0.723 | 0.819 | 0.41 |
| request_hint | 41 | 1.000 | 1.000 | 1.000 | 0.45 |
| abstraction_attempt | 41 | 0.606 | 0.488 | 0.541 | 0.22 |
| misconception_clue | 38 | 0.576 | 0.500 | 0.535 | 0.29 |
| representation_shift | 36 | 0.390 | 0.639 | 0.484 | 0.26 |
| high_confidence | 21 | 0.444 | 0.381 | 0.410 | 0.30 |
| self_correction | 19 | 0.409 | 0.474 | 0.439 | 0.15 |
| environmental_feedback | 19 | 0.538 | 0.368 | 0.438 | 0.38 |
| hint_dependency | 18 | 0.533 | 0.444 | 0.485 | 0.32 |
| recurring_error | 11 | 0.143 | 0.182 | 0.160 | 0.10 |
| prerequisite_weakness | 9 | 0.200 | 0.333 | 0.250 | 0.15 |
| answer_attempt | 7 | 0.500 | 0.143 | 0.222 | 0.24 |
| algebraic | 7 | 0.200 | 0.143 | 0.167 | 0.23 |
| prerequisite_awareness | 4 | 0.182 | 0.500 | 0.267 | 0.10 |
| tabular | 4 | 0.333 | 0.500 | 0.400 | 0.18 |

Build time: 200s