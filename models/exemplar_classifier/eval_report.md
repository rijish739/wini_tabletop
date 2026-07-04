# Exemplar Cognitive Classifier — Evaluation Report

Dataset: `exemplar_dataset_10000_curated.json` · rows used: 12131 (8002 original + 2131 augmented in train) · canonical labels: 38
Split: train 10133 / val 999 / test 999 (seed 42; test/val 100% original rows)
Embedder: `sentence-transformers/all-MiniLM-L6-v2` (frozen, normalized) · selected scorer = **evidence+logreg** (k=8, m=5) · logreg uses 9 cue features · thresholds: 5-fold OOF, clamp (0.1, 0.9)

## Scorer comparison (thresholds from OOF train; selection by val macro-F1)

| scorer | val micro-F1 | val macro-F1 | test micro-F1 | test macro-F1 |
|---|---|---|---|---|
| knn | 0.7577 | 0.5815 | 0.7558 | 0.5668 |
| evidence | 0.5778 | 0.4027 | 0.5721 | 0.4016 |
| logreg | 0.8303 | 0.7120 | 0.8294 | 0.6943 |
| knn+logreg | 0.8324 | 0.7053 | 0.8325 | 0.6918 |
| evidence+logreg **(shipped)** | 0.8386 | 0.7136 | 0.8318 | 0.6947 |

## Per-label test metrics (shipped scorer)

| label | support | precision | recall | F1 | threshold |
|---|---|---|---|---|---|
| curiosity | 846 | 0.948 | 0.946 | 0.947 | 0.56 |
| question | 749 | 1.000 | 1.000 | 1.000 | 0.48 |
| algebraic | 482 | 0.917 | 0.944 | 0.930 | 0.52 |
| procedural_focus | 273 | 0.874 | 0.861 | 0.867 | 0.60 |
| request_representation | 235 | 0.862 | 0.796 | 0.827 | 0.53 |
| representation_shift | 235 | 0.876 | 0.779 | 0.824 | 0.55 |
| diagrammatic | 230 | 0.886 | 0.883 | 0.885 | 0.52 |
| confusion | 221 | 0.646 | 0.692 | 0.668 | 0.52 |
| self_monitoring | 215 | 0.496 | 0.633 | 0.556 | 0.51 |
| low_confidence | 205 | 0.638 | 0.688 | 0.662 | 0.52 |
| physical | 162 | 0.810 | 0.790 | 0.800 | 0.49 |
| anxiety | 159 | 0.947 | 0.899 | 0.923 | 0.53 |
| abstraction_attempt | 135 | 0.821 | 0.815 | 0.818 | 0.53 |
| cognitive_overload | 118 | 0.691 | 0.644 | 0.667 | 0.50 |
| conflict | 100 | 0.857 | 0.780 | 0.817 | 0.54 |
| recurring_error | 95 | 0.429 | 0.568 | 0.489 | 0.48 |
| answer_attempt | 84 | 0.706 | 0.714 | 0.710 | 0.48 |
| transfer_attempt | 84 | 0.692 | 0.643 | 0.667 | 0.50 |
| shortcut_seeking | 83 | 0.744 | 0.699 | 0.720 | 0.50 |
| environmental_feedback | 77 | 0.823 | 0.662 | 0.734 | 0.50 |
| example_request | 65 | 0.917 | 0.677 | 0.779 | 0.52 |
| graphical | 61 | 0.983 | 0.967 | 0.975 | 0.48 |
| prerequisite_weakness | 57 | 0.625 | 0.614 | 0.619 | 0.49 |
| prerequisite_awareness | 57 | 0.625 | 0.614 | 0.619 | 0.49 |
| frustration | 52 | 0.767 | 0.635 | 0.695 | 0.52 |
| high_confidence | 48 | 0.614 | 0.562 | 0.587 | 0.51 |
| simplification_request | 47 | 1.000 | 1.000 | 1.000 | 0.47 |
| request_hint | 43 | 1.000 | 1.000 | 1.000 | 0.46 |
| disengagement | 33 | 0.875 | 0.636 | 0.737 | 0.47 |
| topic_shift | 30 | 0.704 | 0.633 | 0.667 | 0.45 |
| ready_for_next | 30 | 0.857 | 0.600 | 0.706 | 0.53 |
| verbal_analogy | 18 | 0.636 | 0.389 | 0.483 | 0.49 |
| tabular | 16 | 1.000 | 0.812 | 0.897 | 0.51 |
| skepticism | 10 | 0.100 | 0.100 | 0.100 | 0.41 |
| self_correction | 9 | 0.444 | 0.444 | 0.444 | 0.49 |
| misconception_clue | 9 | 0.125 | 0.111 | 0.118 | 0.50 |
| hint_dependency | 8 | 0.000 | 0.000 | 0.000 | 0.63 |
| acknowledgment | 6 | 0.429 | 0.500 | 0.462 | 0.48 |

Build time: 252s