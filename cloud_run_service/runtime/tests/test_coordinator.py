from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from runtime.contracts import (
    RealizationReceipt,
    RealizationStatus,
    TurnCommit,
    TurnInput,
    TurnResult,
    DeviceCapabilities,
    FailureSeverity,
    FailureSignal,
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
            phase_trace=LOGICAL_TURN_PHASES,
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

    def test_maps_returned_failure_signals_into_current_turn_recovery(self) -> None:
        class DegradedAdapter(_SuccessfulLegacyAdapter):
            def execute(self, turn_input):
                execution = super().execute(turn_input)
                signal = FailureSignal(
                    capability="presentation",
                    phase="realization",
                    severity=FailureSeverity.DEGRADED,
                    recoverable=True,
                    cause="display_unavailable",
                    valid_outcome=True,
                )
                return replace(
                    execution,
                    result=replace(
                        execution.result,
                        failures=(signal,),
                        degradation_reasons=("display_unavailable",),
                    ),
                )

        supervisor = RuntimeSupervisor()
        supervisor.ready()
        coordinator = TurnCoordinator(adapter=DegradedAdapter(), supervisor=supervisor)
        turn_input = TurnInput(
            turn_id="turn-degraded",
            learner_id="learner-1",
            interaction={"text": "Show me"},
            device=DeviceCapabilities(),
            budgets=TurnBudgets(total_ms=10_000),
        )

        coordinated = coordinator.run(turn_input)

        self.assertEqual(coordinated.recovery_actions, (RecoveryAction.DEGRADE,))
        self.assertIn("display_unavailable", coordinated.result.degradation_reasons)
        self.assertEqual(supervisor.snapshot().health, RuntimeHealth.DEGRADED)

    def test_retries_one_idempotent_failure_and_uses_the_retry_result(self) -> None:
        class RetryOnceAdapter(_SuccessfulLegacyAdapter):
            def __init__(self):
                self.calls = 0

            def execute(self, turn_input):
                self.calls += 1
                execution = super().execute(turn_input)
                if self.calls == 1:
                    signal = FailureSignal(
                        capability="model_gateway",
                        phase="generation",
                        severity=FailureSeverity.ERROR,
                        recoverable=True,
                        cause="transient_timeout",
                        valid_outcome=False,
                        context={"idempotent": True, "retry_attempt": 0},
                    )
                    return replace(
                        execution,
                        result=replace(execution.result, failures=(signal,)),
                    )
                return execution

        adapter = RetryOnceAdapter()
        supervisor = RuntimeSupervisor()
        supervisor.ready()
        coordinator = TurnCoordinator(adapter=adapter, supervisor=supervisor)
        turn_input = TurnInput(
            turn_id="turn-retry",
            learner_id="learner-1",
            interaction={"text": "Explain"},
            device=DeviceCapabilities(),
            budgets=TurnBudgets(total_ms=10_000),
        )

        coordinated = coordinator.run(turn_input)

        self.assertEqual(adapter.calls, 2)
        self.assertEqual(coordinated.recovery_actions, ())
        self.assertEqual(supervisor.snapshot().health, RuntimeHealth.READY)

    def test_legacy_adapter_does_not_invent_presentation_delivery(self) -> None:
        state = SimpleNamespace(data={"learner_id": "learner-1", "session": {}})
        adapter = LegacyTurnAdapter(
            legacy_turn=lambda *args, **kwargs: {
                "answer": "Look here.",
                "display": [{"kind": "figure"}],
            },
            commit_state=lambda: None,
            state=state,
        )
        turn_input = TurnInput(
            turn_id="turn-presentation",
            learner_id="learner-1",
            interaction={"text": "Show me"},
            device=DeviceCapabilities(),
            budgets=TurnBudgets(total_ms=10_000),
        )

        execution = adapter.execute(turn_input)

        self.assertEqual(execution.result.realization.status, RealizationStatus.PARTIAL)
        self.assertEqual(execution.result.realization.delivered, ())
        self.assertEqual(execution.result.realization.intended, ("speech", "display"))

    def test_unclassified_legacy_failure_is_observable_and_preserves_terminal_error(self) -> None:
        emitted = []

        def legacy_turn(*args, **kwargs):
            emitted.append("provisional-speech")
            raise ValueError("legacy exploded")

        state = SimpleNamespace(data={"learner_id": "learner-1", "session": {}})
        supervisor = RuntimeSupervisor(unavailable_after=2)
        supervisor.ready()
        coordinator = TurnCoordinator(
            adapter=LegacyTurnAdapter(
                legacy_turn=legacy_turn,
                commit_state=lambda: None,
                state=state,
            ),
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

    def test_commit_failure_restores_working_state_and_is_terminal(self) -> None:
        state = SimpleNamespace(
            data={"learner_id": "learner-1", "session": {"mode": "EXPLAIN"}}
        )

        def legacy_turn(*args, **kwargs):
            state.data["session"]["mode"] = "TEST"
            return {"answer": "Question one"}

        def fail_commit():
            raise OSError("durable store unavailable")

        supervisor = RuntimeSupervisor()
        supervisor.ready()
        coordinator = TurnCoordinator(
            adapter=LegacyTurnAdapter(
                legacy_turn=legacy_turn,
                commit_state=fail_commit,
                state=state,
            ),
            supervisor=supervisor,
        )
        turn_input = TurnInput(
            turn_id="turn-commit-failed",
            learner_id="learner-1",
            interaction={"text": "Test me"},
            device=DeviceCapabilities(),
            budgets=TurnBudgets(total_ms=10_000),
        )

        with self.assertRaisesRegex(OSError, "durable store unavailable"):
            coordinator.run(turn_input)

        self.assertEqual(state.data["session"]["mode"], "EXPLAIN")
        self.assertEqual(
            supervisor.snapshot().last_failures[0].capability,
            "state_and_persistence",
        )


if __name__ == "__main__":
    unittest.main()
