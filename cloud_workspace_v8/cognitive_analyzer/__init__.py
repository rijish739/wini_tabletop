"""Cognitive Analyzer (architecture section 6.2, build plan Part 3).

Assembles the Part 1 signal classifier and Part 2 concept resolver into the
per-turn Student Cognitive Update, and applies deterministic learner-state
deltas.
"""

from .analyzer import CognitiveAnalyzer, derive_cognitive_update, derive_state_deltas

__all__ = ["CognitiveAnalyzer", "derive_cognitive_update", "derive_state_deltas"]
