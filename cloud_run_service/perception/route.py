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


# Allowed session-control sub-type values (slice 07, 2026-08-28).
# These are NOT signal labels — they must NOT reach derive_cognitive_update /
# derive_state_deltas.  Populated only when primary == "SESSION_CONTROL".
SESSION_CONTROL_MODES = ("STOP", "TEST", "PRACTICE", "EXPLAIN")
SESSION_CONTROL_MODE_SET = set(SESSION_CONTROL_MODES)


@dataclass
class RouteResult:
    primary: str                                  # one of INTENTS
    also_learning: bool = False                   # a non-LEARNING turn that also carries a maths ask
    safety_alert: bool = False                    # deterministic-gate or model safety flag
    safety_tier: int | None = None                # 1 concern, 2 protected, 3 urgent
    safety_category: str | None = None             # redacted human-review category
    perception_degraded: bool = False             # fallback has no state-write authority
    answer_attempt: bool = False                  # attempts the open pending_check question
    concept_id: Optional[str] = None              # catalog id or None (INHERIT collapses to current)
    concept_confidence: float = 0.0
    secondary_concepts: list = field(default_factory=list)
    signal_scores: Dict[str, float] = field(default_factory=dict)
    source: str = "gemini"                         # "gate" | "gemini" | "fallback"
    reason: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)
    # Slice 07 (2026-08-28): SESSION_CONTROL sub-type — not a signal label.
    # One of SESSION_CONTROL_MODES or None.  Only set when primary == "SESSION_CONTROL"
    # and the turn is explicitly requesting a mode change (not a generic "bye"/pause).
    session_control_mode: Optional[str] = None
    # Slice 07 (2026-08-28): the learner's raw topic phrasing when they name or
    # request a specific topic ("teach me natural numbers", "let's do trigonometry").
    # Replaces extract_topic_request / is_bare_topic in the interaction-control layer.
    topic_phrasing: Optional[str] = None

    @property
    def is_learning(self) -> bool:
        return self.primary == "LEARNING"
