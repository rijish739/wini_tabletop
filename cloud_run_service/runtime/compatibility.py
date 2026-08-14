"""Caller-stable TutorLoop Turn façade over the typed coordinator."""

from __future__ import annotations

import uuid
from typing import Any, Callable, Mapping

from .contracts import DeviceCapabilities, TurnBudgets, TurnInput
from .coordinator import TurnCoordinator
from .legacy_adapter import LegacyTurnAdapter
from .supervisor import RuntimeHealthSnapshot, RuntimeSupervisor


class TutorLoopCompatibilityFacade:
    """Construct typed Turn Input and serialize only the committed compatibility result."""

    def __init__(
        self,
        *,
        legacy_turn: Callable[..., Mapping[str, Any]],
        commit_state: Callable[[], None],
        state: Any,
        interaction_control: Any,
    ) -> None:
        self._supervisor = RuntimeSupervisor()
        self._coordinator = TurnCoordinator(
            adapter=LegacyTurnAdapter(
                legacy_turn=legacy_turn,
                commit_state=commit_state,
                state=state,
            ),
            interaction_control=interaction_control,
            supervisor=self._supervisor,
        )
        self._state = state
        self._supervisor.ready()

    @property
    def runtime_health(self) -> RuntimeHealthSnapshot:
        return self._supervisor.snapshot()

    def turn(
        self,
        text: str,
        answer_budget: dict | None = None,
        precomputed_analysis: dict | None = None,
        precomputed_grade: dict | str | None = None,
        stt_confidence: float | None = None,
        turn_id: str | None = None,
        learner_id: str | None = None,
        _allow_shift: bool = True,
    ) -> dict[str, Any]:
        resolved_turn_id = turn_id or f"turn_{uuid.uuid4().hex}"
        resolved_learner_id = (
            learner_id
            or self._state.data.get("learner_id")
            or "local_single_learner"
        )
        turn_input = TurnInput(
            turn_id=resolved_turn_id,
            learner_id=resolved_learner_id,
            interaction={
                "text": text,
                "answer_budget": answer_budget,
                "allow_topic_shift": _allow_shift,
            },
            device=DeviceCapabilities(),
            # The legacy API has no lifecycle deadline. This sentinel is descriptive
            # only; the adapter preserves all existing timeout behavior unchanged.
            budgets=TurnBudgets(total_ms=2_147_483_647),
            trusted_observations={
                "precomputed_analysis": precomputed_analysis,
                "precomputed_grade": precomputed_grade,
                "stt_confidence": stt_confidence,
            },
        )
        return self._coordinator.run(turn_input).serialize_compatibility()
