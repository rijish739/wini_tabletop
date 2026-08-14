from __future__ import annotations

import unittest
from types import SimpleNamespace

from runtime.contracts import (
    RealizationReceipt,
    RealizationStatus,
    TurnCommit,
    TurnInput,
    TurnResult,
    DeviceCapabilities,
    TurnBudgets,
)
from runtime.coordinator import (
    LOGICAL_TURN_PHASES,
    CoordinatedTurn,
    LegacyExecution,
    RecoveryAction,
    RecoveryPolicy,
    TurnCoordinator,
)
from runtime.legacy_adapter import LegacyTurnAdapter
from runtime.supervisor import RuntimeHealth, RuntimeSupervisor


class _SuccessfulLegacyAdapter:
    name = "temporary_legacy_turn_adapter"

    def execute(self, turn_input: TurnInput) -> LegacyExecution:
        compatibility = {"answer": "One half.", "display": [{"kind": "text"}]}
        return LegacyExecution(
            result=TurnResult(
                turn_id=turn_input.turn_id,
                learner_id=turn_input.learner_id,
                outcome=compatibility,
                compatibility=compatibility,
                realization=RealizationReceipt(
                    turn_id=turn_input.turn_id,
                    status=RealizationStatus.COMPLETE,
                    delivered=("speech", "display"),
                ),
                commit=TurnCommit(
                    commit_id="legacy-commit",
                    turn_id=turn_input.turn_id,
                    learner_id=turn_input.learner_id,
                    applied_change_ids=(),
                    state_version="state-v1",
                ),
            ),
            completed_phases=LOGICAL_TURN_PHASES,
            measurements={"legacy_adapter_turns": 1},
        )


class TurnCoordinatorTests(unittest.TestCase):
    def test_returns_committed_result_with_exact_compatibility_serialization(self) -> None:
        supervisor = RuntimeSupervisor()
        supervisor.ready()
        coordinator = TurnCoordinator(
            adapter=_SuccessfulLegacyAdapter(), supervisor=supervisor
        )
        turn_input = TurnInput(
            turn_id="turn-1",
            learner_id="learner-1",
            interaction={"text": "What is one half?"},
            device=DeviceCapabilities(),
            budgets=TurnBudgets(total_ms=10_000),
        )

        coordinated = coordinator.run(turn_input)

        self.assertIsInstance(coordinated, CoordinatedTurn)
        self.assertEqual(coordinated.phases, LOGICAL_TURN_PHASES)
        self.assertEqual(
            coordinated.serialize_compatibility(),
            {"answer": "One half.", "display": [{"kind": "text"}]},
        )
        self.assertEqual(coordinated.measurements["legacy_adapter_turns"], 1)
        self.assertEqual(supervisor.snapshot().health, RuntimeHealth.READY)

    def test_unclassified_legacy_failure_is_observable_and_preserves_terminal_error(self) -> None:
        emitted = []

        def legacy_turn(*args, **kwargs):
            emitted.append("provisional-speech")
            raise ValueError("legacy exploded")

        state = SimpleNamespace(data={"learner_id": "learner-1", "session": {}})
        supervisor = RuntimeSupervisor(unavailable_after=2)
        supervisor.ready()
        coordinator = TurnCoordinator(
            adapter=LegacyTurnAdapter(legacy_turn=legacy_turn, state=state),
            supervisor=supervisor,
        )
        turn_input = TurnInput(
            turn_id="turn-failed",
            learner_id="learner-1",
            interaction={"text": "Help me", "answer_budget": None},
            device=DeviceCapabilities(),
            budgets=TurnBudgets(total_ms=10_000),
        )

        with self.assertRaisesRegex(ValueError, "legacy exploded"):
            coordinator.run(turn_input)

        self.assertEqual(emitted, ["provisional-speech"])
        snapshot = supervisor.snapshot()
        self.assertEqual(snapshot.health, RuntimeHealth.DEGRADED)
        self.assertEqual(snapshot.last_failures[0].capability, "legacy_runtime")
        self.assertEqual(snapshot.last_failures[0].cause, "ValueError: legacy exploded")
        self.assertEqual(
            RecoveryPolicy().decide(snapshot.last_failures[0]),
            RecoveryAction.FAIL_CLOSED,
        )

        with self.assertRaises(ValueError):
            coordinator.run(turn_input)
        self.assertEqual(supervisor.snapshot().health, RuntimeHealth.UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
