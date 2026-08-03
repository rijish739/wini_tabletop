"""Part 11 perception front door (PART11_GEMINI_PERCEPTION_LAYER.md).

Deterministic gates (SAFETY/NONSENSE) run first and model-free; a single
structured Gemini call then does intent routing + cognitive signals + concept
resolution, feeding the UNCHANGED derive_*/apply_deltas state machine.
"""

from .gates import gate, is_nonsense, is_safety
from .route import INHERIT, INTENTS, RouteResult

__all__ = [
    "gate",
    "is_safety",
    "is_nonsense",
    "RouteResult",
    "INTENTS",
    "INHERIT",
    # GeminiPerception is imported lazily by callers to avoid pulling torch/genai
    # into the model-free gate path.
]
