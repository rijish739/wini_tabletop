"""HOPE detectors (build plan Part 4, report section 5).

Local ordinal scorers (0-3) for the KI / KT / CT learning signals, trained on
the human-reviewed HOPE gold set. All-local: MiniLM embeddings + a per-signal
ordinal head; no LLM at inference.
"""

from .detector import HopeDetector

__all__ = ["HopeDetector"]
