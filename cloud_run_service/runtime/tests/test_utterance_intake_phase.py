"""Walking-skeleton turn properties for the UTTERANCE_INTAKE phase (ticket 01).

Free lane, no model calls. Asserts the phase insertion, that Perception is
handed the Intake observation and reads its normalized_text, and turn-level
property #1: a terse real answer survives the full Intake -> gate() path.
"""

from __future__ import annotations

import unittest

from interaction_control import (
    InteractionControlRequest,
    InteractionDecision,
    InteractionDisposition,
)
from perception import PerceptionRequest
from perception.gates import gate
from runtime.contracts import (
    DeviceCapabilities,
    ModuleOutcome,
    RealizationReceipt,
    RealizationStatus,
    TurnBudgets,
    TurnCommit,
    TurnInput,
    TurnResult,
    Utterance,
    UtteranceProvenance,
    UtteranceSource,
)
from runtime.coordinator import (
    LOGICAL_TURN_PHASES,
    LegacyExecution,
    TurnCoordinator,
    TurnPhase,
)
from runtime.supervisor import RuntimeSupervisor
from utterance_intake import UtteranceIntake


def _turn_input(text: str) -> TurnInput:
    utterance = Utterance(
        text=text, source=UtteranceSource.TYPED,
        provenance=UtteranceProvenance(utterance_id="t1", captured_at="t"),
    )
    return TurnInput(
        turn_id="t1", learner_id="L1",
        interaction={"text": text}, device=DeviceCapabilities(),
        budgets=TurnBudgets(total_ms=1000), utterance=utterance,
    )


class _CapturingPerception:
    """Records the observation it was handed and gates on it, as production does."""

    def __init__(self) -> None:
        self.seen_observation = None
        self.gate_result = "unset"

    def perceive(self, request):
        self.seen_observation = request.observation
        self.gate_result = gate(request.observation)
        from types import SimpleNamespace

        return ModuleOutcome(value=SimpleNamespace(source="fake"), failures=())


class _Adapter:
    name = "fake"

    def interaction_request(self, turn_input):
        return InteractionControlRequest(turn_input=turn_input, session={})

    def perception_request(self, turn_input):
        return PerceptionRequest(turn_input=turn_input, session={})

    def execute(self, turn_input, interaction=None, **_):
        result = TurnResult(
            turn_id=turn_input.turn_id, learner_id=turn_input.learner_id,
            outcome={"answer": "ok"}, compatibility={"answer": "ok"},
            realization=RealizationReceipt(
                turn_id=turn_input.turn_id, status=RealizationStatus.PARTIAL),
            commit=TurnCommit(
                commit_id="c1", turn_id=turn_input.turn_id,
                learner_id=turn_input.learner_id, applied_change_ids=(),
                state_version="v1"),
        )
        return LegacyExecution(result=result, phase_trace=LOGICAL_TURN_PHASES)


class _InteractionControl:
    def control(self, request):
        return ModuleOutcome(value=InteractionDecision(
            disposition=InteractionDisposition.COMPLETE,
            text="x", compatibility={"answer": "ok"}))


class UtteranceIntakePhaseTests(unittest.TestCase):
    def test_phase_inserted_before_perception(self) -> None:
        self.assertIn(TurnPhase.UTTERANCE_INTAKE, LOGICAL_TURN_PHASES)
        self.assertLess(
            LOGICAL_TURN_PHASES.index(TurnPhase.UTTERANCE_INTAKE),
            LOGICAL_TURN_PHASES.index(TurnPhase.PERCEPTION_AND_PRIOR_GRADING),
        )
        self.assertEqual(
            LOGICAL_TURN_PHASES.index(TurnPhase.UTTERANCE_INTAKE),
            LOGICAL_TURN_PHASES.index(TurnPhase.ADMISSION_AND_ROUTING) + 1,
        )

    def _run(self, text: str) -> _CapturingPerception:
        perception = _CapturingPerception()
        coordinator = TurnCoordinator(
            adapter=_Adapter(), supervisor=RuntimeSupervisor(),
            interaction_control=_InteractionControl(),
            utterance_intake=UtteranceIntake(), perception=perception,
        )
        coordinator.run(_turn_input(text))
        return perception

    def test_perception_receives_the_intake_observation(self) -> None:
        perception = self._run("5")
        self.assertIsNotNone(perception.seen_observation)
        self.assertEqual(perception.seen_observation.normalized_text, "5")

    def test_terse_real_answer_survives_intake_to_gate_path(self) -> None:
        # Turn-level property #1: 5 / x=3 / no all pass through gate() unchanged.
        for text in ("5", "x=3", "no"):
            with self.subTest(text=text):
                perception = self._run(text)
                self.assertIsNone(
                    perception.gate_result,
                    f"{text!r} must survive Intake -> gate() as a pass-through",
                )


if __name__ == "__main__":
    unittest.main()
