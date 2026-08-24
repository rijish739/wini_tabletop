"""Caller-stable TutorLoop Turn façade over the typed coordinator."""

from __future__ import annotations

import uuid
from typing import Any, Callable, Mapping

from .contracts import DeviceCapabilities, TurnBudgets, TurnInput
from .coordinator import TurnCoordinator
from .turn_runtime import TurnRuntime
from .supervisor import RuntimeHealthSnapshot, RuntimeSupervisor


class TutorLoopCompatibilityFacade:
    """Construct typed Turn Input and serialize only the committed compatibility result."""

    def __init__(
        self,
        *,
        turn_behavior: Callable[..., Mapping[str, Any]] | None = None,
        legacy_turn: Callable[..., Mapping[str, Any]] | None = None,
        commit_state: Callable[[], None],
        state: Any,
        interaction_control: Any,
        perception: Any = None,
        assessment_evidence: Any = None,
        pedagogy: Any = None,
        retrieval: Any = None,
        response_planning: Any = None,
        response_generation: Any = None,
        presentation: Any = None,
    ) -> None:
        if assessment_evidence is None:
            from assessment_evidence import AssessmentEvidence

            assessment_evidence = AssessmentEvidence()
        if response_planning is None and retrieval is not None:
            from response_planning import ResponsePlanning

            response_planning = ResponsePlanning()
        self._supervisor = RuntimeSupervisor()
        behavior = turn_behavior or legacy_turn
        if behavior is None:
            raise TypeError("turn_behavior is required")
        self._coordinator = TurnCoordinator(
            runtime=TurnRuntime(
                turn_behavior=behavior,
                commit_state=commit_state,
                state=state,
            ),
            interaction_control=interaction_control,
            perception=perception,
            assessment_evidence=assessment_evidence,
            pedagogy=pedagogy,
            retrieval=retrieval,
            response_planning=response_planning,
            response_generation=response_generation,
            presentation=presentation,
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
            # The caller-compatible API has no lifecycle deadline. This sentinel
            # is descriptive only; the runtime preserves existing timeout behavior.
            budgets=TurnBudgets(total_ms=2_147_483_647),
            trusted_observations={
                "precomputed_analysis": precomputed_analysis,
                "precomputed_grade": precomputed_grade,
                "stt_confidence": stt_confidence,
            },
        )
        return self._coordinator.run(turn_input).serialize_compatibility()
