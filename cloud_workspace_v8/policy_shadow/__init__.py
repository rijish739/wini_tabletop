"""Pedagogy policy shadow model (build plan Part 5, report section 6).

Suggests one of the 15 tutor actions from the analyzed utterance. SHADOW
mode: the rule-based engine stays authoritative; suggestions are logged
beside the rules' choice until the shadow demonstrably wins on real turns.
"""

from .shadow import PolicyShadow, canonicalize_action

__all__ = ["PolicyShadow", "canonicalize_action"]
