from __future__ import annotations

import unittest

from runtime.contracts import FailureSeverity, FailureSignal
from runtime.coordinator import RecoveryAction, RecoveryPolicy
from runtime.supervisor import RuntimeHealth, RuntimeSupervisor


def _failure(
    capability: str,
    *,
    valid_outcome: bool = False,
    recoverable: bool = False,
    severity: FailureSeverity = FailureSeverity.ERROR,
    context=None,
) -> FailureSignal:
    return FailureSignal(
        capability=capability,
        phase="test",
        severity=severity,
        recoverable=recoverable,
        cause="fixture_failure",
        valid_outcome=valid_outcome,
        context=context or {},
    )


class RecoveryPolicyTests(unittest.TestCase):
    def test_maps_failure_facts_without_feature_policy(self) -> None:
        policy = RecoveryPolicy()

        self.assertEqual(
            policy.decide(_failure("presentation", valid_outcome=True)),
            RecoveryAction.DEGRADE,
        )
        self.assertEqual(
            policy.decide(_failure("retrieval", valid_outcome=True, recoverable=True)),
            RecoveryAction.SAFE_NON_ASSESSING_FALLBACK,
        )
        self.assertEqual(
            policy.decide(_failure("retrieval", recoverable=True)),
            RecoveryAction.FAIL_CLOSED,
        )
        self.assertEqual(
            policy.decide(_failure(
                "model_gateway", recoverable=True,
                context={"idempotent": True, "retry_attempt": 0},
            )),
            RecoveryAction.FAIL_CLOSED,
        )
        self.assertEqual(
            policy.decide(_failure("state_and_persistence", recoverable=True)),
            RecoveryAction.FAIL_CLOSED,
        )


class RuntimeSupervisorTests(unittest.TestCase):
    def test_exposes_startup_degradation_unavailability_and_recovery(self) -> None:
        supervisor = RuntimeSupervisor(unavailable_after=2)
        self.assertEqual(supervisor.snapshot().health, RuntimeHealth.STARTING)

        supervisor.ready()
        self.assertEqual(supervisor.snapshot().health, RuntimeHealth.READY)

        supervisor.observe_turn((_failure("legacy_runtime"),))
        self.assertEqual(supervisor.snapshot().health, RuntimeHealth.DEGRADED)

        supervisor.observe_turn((_failure("legacy_runtime"),))
        self.assertEqual(supervisor.snapshot().health, RuntimeHealth.UNAVAILABLE)

        supervisor.observe_turn(())
        self.assertEqual(supervisor.snapshot().health, RuntimeHealth.READY)

    def test_initialization_failure_is_immediately_unavailable(self) -> None:
        supervisor = RuntimeSupervisor()
        supervisor.initialization_failed(
            _failure("state_and_persistence", severity=FailureSeverity.FATAL)
        )

        self.assertEqual(supervisor.snapshot().health, RuntimeHealth.UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
