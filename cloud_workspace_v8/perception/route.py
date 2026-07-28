"""RouteResult: the front-door verdict for one utterance (Part 11 §4.1/§7).

Produced either by a deterministic gate (perception/gates.py) or by the Gemini
perception call (perception/gemini_perception.py). tutor_loop branches on
`.primary`: only LEARNING enters the state-moving pipeline (§3 invariant).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# The eight top-level intents (Part 11 §4.3). Order is documentation only.
INTENTS = [
    "LEARNING",
    "SOCIAL",
    "META_CAPABILITY",
    "OFF_DOMAIN_ACADEMIC",
    "SESSION_CONTROL",
    "EMOTIONAL",
    "SAFETY",
    "NONSENSE",
]
INTENT_SET = set(INTENTS)

# The abstain sentinel shared with the dataset + resolver contract.
INHERIT = "INHERIT_CURRENT_CONCEPT"


@dataclass
class RouteResult:
    primary: str                                  # one of INTENTS
    also_learning: bool = False                   # a non-LEARNING turn that also carries a maths ask
    safety_alert: bool = False                    # deterministic-gate or model safety flag
    answer_attempt: bool = False                  # attempts the open pending_check question
    concept_id: Optional[str] = None              # catalog id or None (INHERIT collapses to current)
    concept_confidence: float = 0.0
    secondary_concepts: list = field(default_factory=list)
    signal_scores: Dict[str, float] = field(default_factory=dict)
    source: str = "gemini"                         # "gate" | "gemini" | "fallback"
    reason: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_learning(self) -> bool:
        return self.primary == "LEARNING"
