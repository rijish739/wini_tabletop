"""Backward-compatible import aliases for the retired adapter module.

No runtime entrypoint imports this module.  It remains temporarily so older
offline fixtures can migrate without changing their setup in the same commit.
"""

from .turn_runtime import TurnRuntime, TurnRuntimeFailure


class LegacyTurnAdapter(TurnRuntime):
    """Compatibility constructor for pre-contract test fixtures."""

    def __init__(self, *, legacy_turn, commit_state, state):
        super().__init__(
            turn_behavior=legacy_turn,
            commit_state=commit_state,
            state=state,
        )


LegacyAdapterFailure = TurnRuntimeFailure

__all__ = ["LegacyAdapterFailure", "LegacyTurnAdapter"]
