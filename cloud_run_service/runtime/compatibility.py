"""Caller-stable TutorLoop Turn façade over the typed coordinator."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .contracts import (
    DeviceCapabilities,
    TurnBudgets,
    TurnInput,
    Utterance,
    UtteranceProvenance,
    UtteranceSource,
)
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
        perception: Any = None,
        assessment_evidence: Any = None,
        pedagogy: Any = None,
        retrieval: Any = None,
        response_planning: Any = None,
        response_generation: Any = None,
    ) -> None:
        if assessment_evidence is None:
            from assessment_evidence import AssessmentEvidence

            assessment_evidence = AssessmentEvidence()
        if response_planning is None and retrieval is not None:
            from response_planning import ResponsePlanning

            response_planning = ResponsePlanning()
        from utterance_intake import UtteranceIntake

        self._supervisor = RuntimeSupervisor()
        self._coordinator = TurnCoordinator(
            adapter=LegacyTurnAdapter(
                legacy_turn=legacy_turn,
                commit_state=commit_state,
                state=state,
            ),
            interaction_control=interaction_control,
            utterance_intake=UtteranceIntake(),
            perception=perception,
            assessment_evidence=assessment_evidence,
            pedagogy=pedagogy,
            retrieval=retrieval,
            response_planning=response_planning,
            response_generation=response_generation,
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
        # The one production construction site of the typed Utterance. This text
        # path is TYPED (an engineering test shortcut); TYPED carries confidence
        # None, never a fabricated 1.0, with recognizer=None.
        # Ticket 11: interaction["text"] and trusted_observations["stt_confidence"] deleted.
        utterance = Utterance(
            text=text,
            source=UtteranceSource.TYPED,
            provenance=UtteranceProvenance(
                utterance_id=resolved_turn_id,
                captured_at=datetime.now(timezone.utc).isoformat(),
                recognizer=None,
            ),
        )
        turn_input = TurnInput(
            turn_id=resolved_turn_id,
            learner_id=resolved_learner_id,
            interaction={
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
                # stt_confidence removed (ticket 11): confidence lives on Utterance.confidence.
            },
            utterance=utterance,
        )
        return self._coordinator.run(turn_input).serialize_compatibility()
