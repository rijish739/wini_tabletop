from __future__ import annotations

import unittest
from dataclasses import dataclass

from runtime.contracts import (
    DeviceCapabilities,
    FailureSignal,
    FailureSeverity,
    ModuleOutcome,
    ProvisionalOutput,
    RealizationReceipt,
    RealizationStatus,
    StateChange,
    StateOperation,
    StateScope,
    TurnBudgets,
    TurnCommit,
    TurnContext,
    TurnInput,
    TurnResult,
)


class LifecycleContractTests(unittest.TestCase):
    def test_turn_input_and_context_are_deeply_immutable(self) -> None:
        @dataclass(frozen=True)
        class PerceptionContext:
            route: str

        source = {"transcript": "show me fractions", "samples": [1, 2]}
        turn_input = TurnInput(
            turn_id="turn-1",
            learner_id="learner-1",
            interaction=source,
            device=DeviceCapabilities(speech=True, display=False),
            budgets=TurnBudgets(total_ms=8_000, first_output_ms=900),
            trusted_observations={"stt": {"confidence": 0.96}},
        )
        source["samples"].append(3)

        self.assertEqual(turn_input.interaction["samples"], (1, 2))
        with self.assertRaises(TypeError):
            turn_input.interaction["transcript"] = "changed"  # type: ignore[index]

        context = TurnContext.start(turn_input).advance(
            phase="perception", state=PerceptionContext(route="learning")
        )
        self.assertEqual(context.phase, "perception")
        self.assertEqual(context.state.route, "learning")
        self.assertIsNone(TurnContext.start(turn_input).state)

    def test_failure_output_and_receipt_reject_invalid_lifecycle_values(self) -> None:
        signal = FailureSignal(
            capability="presentation",
            phase="realize",
            severity=FailureSeverity.DEGRADED,
            recoverable=True,
            cause="display_unavailable",
            valid_outcome=True,
            context={"mode": "speech_only"},
        )
        output = ProvisionalOutput(
            turn_id="turn-1", sequence=0, kind="speech", payload={"text": "Hello"}
        )
        receipt = RealizationReceipt(
            turn_id="turn-1",
            status=RealizationStatus.DEGRADED,
            intended=("speech", "display"),
            delivered=("speech",),
            failures=(signal,),
        )

        self.assertTrue(signal.valid_outcome)
        self.assertEqual(output.payload["text"], "Hello")
        self.assertEqual(receipt.delivered, ("speech",))
        with self.assertRaises(ValueError):
            ProvisionalOutput(turn_id="turn-1", sequence=-1, kind="speech")
        with self.assertRaises(ValueError):
            FailureSignal(
                capability="presentation", phase="realize", severity="unknown",  # type: ignore[arg-type]
                recoverable=False, cause="bad severity", valid_outcome=False,
            )

    def test_state_change_commit_and_result_are_feature_neutral(self) -> None:
        change = StateChange(
            change_id="change-1",
            owner="interaction_control",
            scope=StateScope.SESSION,
            path=("current_concept",),
            operation=StateOperation.SET,
            value="fractions",
        )
        commit = TurnCommit(
            commit_id="commit-1",
            turn_id="turn-1",
            learner_id="learner-1",
            applied_change_ids=(change.change_id,),
            state_version="version-2",
        )
        receipt = RealizationReceipt(
            turn_id="turn-1", status=RealizationStatus.COMPLETE, delivered=("speech",)
        )
        result = TurnResult(
            turn_id="turn-1",
            learner_id="learner-1",
            outcome={"answer": "One half."},
            compatibility={"answer": "One half."},
            realization=receipt,
            commit=commit,
        )

        self.assertEqual(result.commit.applied_change_ids, ("change-1",))
        self.assertEqual(result.compatibility["answer"], "One half.")
        with self.assertRaises(ValueError):
            StateChange(
                change_id="bad",
                owner="interaction_control",
                scope=StateScope.SESSION,
                path=(),
                operation=StateOperation.SET,
                value="fractions",
            )

    def test_module_outcome_keeps_feature_payload_typed_and_lifecycle_metadata_common(self) -> None:
        change = StateChange(
            change_id="mode-1", owner="pedagogy", scope=StateScope.SESSION,
            path=("mode",), operation=StateOperation.SET, value="PRACTICE",
        )
        outcome = ModuleOutcome(
            value=("typed", "pedagogy", "decision"), state_changes=(change,)
        )

        self.assertEqual(outcome.value[1], "pedagogy")
        self.assertEqual(outcome.state_changes, (change,))
        self.assertTrue(outcome.valid)
        with self.assertRaises(ValueError):
            StateChange(
                change_id="bad-operation",
                owner="interaction_control",
                scope=StateScope.SESSION,
                path=("current_concept",),
                operation="merge",  # type: ignore[arg-type]
                value="fractions",
            )


if __name__ == "__main__":
    unittest.main()
