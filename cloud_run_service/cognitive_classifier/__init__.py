"""MiniLM exemplar cognitive classifier (architecture Part 1, report section 3).

Frozen all-MiniLM-L6-v2 embeddings + exemplar bank + weighted k-NN label
evidence + per-label calibrated thresholds. No fine-tuning.
"""

from .classifier import ExemplarCognitiveClassifier
from .label_space import canonicalize_labels

__all__ = [
    "ExemplarCognitiveClassifier",
    "canonicalize_labels",
]
