"""MiniLM concept resolver (architecture section 6.3, build plan Part 2).

Maps a student utterance to curriculum concept(s) with confidence, or
abstains so the session's current concept is inherited.
"""

from .resolver import ConceptResolver

__all__ = ["ConceptResolver"]
