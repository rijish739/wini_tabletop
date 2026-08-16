"""Feature-neutral sequencing and current-Turn recovery for the tutor runtime."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping, Protocol

from .contracts import FailureSeverity, FailureSignal, TurnInput, TurnResult, deep_thaw
from .legacy_adapter import LegacyAdapterFailure
from .supervisor import RuntimeSupervisor

if TYPE_CHECKING:
    from assessment_evidence import AssessmentEvidenceInterface, AssessmentRequest
    from interaction_control import (
        InteractionControlInterface,
        InteractionControlRequest,
    )
    from perception import PerceptionInterface
    from pedagogy import PedagogyInterface


class TurnPhase(str, Enum):
    ADMISSION_AND_ROUTING = "admission_and_routing"
    PERCEPTION_AND_PRIOR_GRADING = "perception_and_prior_grading"
    STATE_PROJECTION_AND_PEDAGOGY = "state_projection_and_pedagogy"
    GROUNDED_RETRIEVAL = "grounded_retrieval"
    RESPONSE_PLANNING = "response_planning"
    RESPONSE_GENERATION = "response_generation"
    PRESENTATION_AND_REALIZATION = "presentation_and_realization"
    ASSESSMENT_ARMING_AND_COMMIT = "assessment_arming_and_commit"
    FINAL_RESULT = "final_result"


LOGICAL_TURN_PHASES = tuple(TurnPhase)


class RecoveryAction(str, Enum):
    DEGRADE = "degrade"
    SAFE_NON_ASSESSING_FALLBACK = "safe_non_assessing_fallback"
    FAIL_CLOSED = "fail_closed"


class RecoveryCapability(str, Enum):
    IDENTITY = "identity"
    SAFETY_INTEGRITY = "safety_integrity"
    STATE_AND_PERSISTENCE = "state_and_persistence"
    ASSESSMENT_EVIDENCE = "assessment_evidence"
    RETRIEVAL = "retrieval"
    RESPONSE_GENERATION = "response_generation"


class RecoveryPolicy:
    """Feature-neutral current-Turn decisions over reported failure facts."""

    _FAIL_CLOSED_CAPABILITIES = frozenset({
        RecoveryCapability.IDENTITY,
        RecoveryCapability.SAFETY_INTEGRITY,
        RecoveryCapability.STATE_AND_PERSISTENCE,
        RecoveryCapability.ASSESSMENT_EVIDENCE,
    })
    _SAFE_FALLBACK_CAPABILITIES = frozenset({
        RecoveryCapability.RETRIEVAL,
        RecoveryCapability.RESPONSE_GENERATION,
    })

    def decide(self, failure: FailureSignal) -> RecoveryAction:
        try:
            capability = RecoveryCapability(failure.capability)
        except ValueError:
            capability = None
        if (
            failure.severity is FailureSeverity.FATAL
            or capability in self._FAIL_CLOSED_CAPABILITIES
        ):
            return RecoveryAction.FAIL_CLOSED
        if capability in self._SAFE_FALLBACK_CAPABILITIES:
            return (
                RecoveryAction.SAFE_NON_ASSESSING_FALLBACK
                if failure.valid_outcome
                else RecoveryAction.FAIL_CLOSED
            )
        if failure.valid_outcome:
            return RecoveryAction.DEGRADE
        return RecoveryAction.FAIL_CLOSED


@dataclass(frozen=True)
class LegacyExecution:
    """Measurable result from the temporary, explicitly removable legacy seam."""

    result: TurnResult
    phase_trace: tuple[TurnPhase, ...]
    measurements: Mapping[str, int | float] = field(default_factory=dict)


class TemporaryLegacyAdapter(Protocol):
    name: str

    def interaction_request(
        self, turn_input: TurnInput
    ) -> "InteractionControlRequest": ...

    def perception_request(self, turn_input: TurnInput): ...

    def assessment_request(self, turn_input: TurnInput, interaction) -> "AssessmentRequest": ...

    def pedagogy_request(self, turn_input: TurnInput, observation, assessment): ...

    def execute(self, turn_input: TurnInput, interaction, assessment=None,
                pedagogy=None) -> LegacyExecution: ...


@dataclass(frozen=True)
class CoordinatedTurn:
    result: TurnResult
    phases: tuple[TurnPhase, ...]
    measurements: Mapping[str, int | float]
    recovery_actions: tuple[RecoveryAction, ...] = ()

    def serialize_compatibility(self) -> dict[str, Any]:
        return deep_thaw(self.result.compatibility)


class TurnCoordinator:
    """Sequence a Turn while leaving all tutoring policy behind adapter interfaces."""

    def __init__(
        self,
        *,
        adapter: TemporaryLegacyAdapter,
        supervisor: RuntimeSupervisor,
        interaction_control: "InteractionControlInterface",
        perception: "PerceptionInterface | None" = None,
        assessment_evidence: "AssessmentEvidenceInterface | None" = None,
        pedagogy: "PedagogyInterface | None" = None,
        recovery_policy: RecoveryPolicy | None = None,
    ) -> None:
        self._adapter = adapter
        self._supervisor = supervisor
        self._interaction_control = interaction_control
        self._perception = perception
        self._assessment_evidence = assessment_evidence
        self._pedagogy = pedagogy
        self._recovery_policy = recovery_policy or RecoveryPolicy()

    def run(self, turn_input: TurnInput) -> CoordinatedTurn:
        interaction_request = self._adapter.interaction_request(turn_input)
        perception_failures: tuple[FailureSignal, ...] = ()
        if self._perception is not None:
            perception = self._perception.perceive(
                self._adapter.perception_request(turn_input)
            )
            perception_failures = perception.failures
            perception_actions = tuple(
                self._recovery_policy.decide(failure)
                for failure in perception_failures
            )
            if (
                not perception.valid
                or RecoveryAction.FAIL_CLOSED in perception_actions
            ):
                self._supervisor.observe_turn(perception.failures)
                failure = perception.failures[0]
                raise RuntimeError(
                    f"Turn failed closed: {failure.capability}/{failure.cause}"
                )
            interaction_request = replace(
                interaction_request, perception=perception.value
            )
        interaction = self._interaction_control.control(interaction_request)
        if self._perception is not None and perception.state_changes:
            interaction = replace(
                interaction,
                state_changes=perception.state_changes + interaction.state_changes,
            )
        if interaction.failures:
            actions = tuple(
                self._recovery_policy.decide(failure)
                for failure in interaction.failures
            )
            if not interaction.valid or RecoveryAction.FAIL_CLOSED in actions:
                self._supervisor.observe_turn(interaction.failures)
                failure = interaction.failures[0]
                if failure.capability == RecoveryCapability.IDENTITY.value:
                    raise PermissionError(failure.cause)
                raise RuntimeError(
                    f"Turn failed closed: {failure.capability}/{failure.cause}"
                )
        assessment = None
        if self._assessment_evidence is not None:
            assessment = self._assessment_evidence.evaluate_prior_attempt(
                self._adapter.assessment_request(turn_input, interaction)
            )
            actions = tuple(
                self._recovery_policy.decide(failure)
                for failure in assessment.failures
            )
            if not assessment.valid or RecoveryAction.FAIL_CLOSED in actions:
                self._supervisor.observe_turn(assessment.failures)
                failure = assessment.failures[0]
                raise RuntimeError(
                    f"Turn failed closed: {failure.capability}/{failure.cause}"
                )
        pedagogical = None
        continuing_learning = (
            interaction.value is not None
            and getattr(interaction.value.disposition, "value", "") == "continue_learning"
        )
        if self._pedagogy is not None and continuing_learning:
            if self._perception is None or perception.value is None:
                raise RuntimeError("Pedagogy requires a validated Perception observation")
            pedagogical = self._pedagogy.decide(
                self._adapter.pedagogy_request(
                    turn_input, perception.value, assessment
                )
            )
            actions = tuple(
                self._recovery_policy.decide(failure)
                for failure in pedagogical.failures
            )
            if not pedagogical.valid or RecoveryAction.FAIL_CLOSED in actions:
                self._supervisor.observe_turn(pedagogical.failures)
                failure = pedagogical.failures[0]
                raise RuntimeError(
                    f"Turn failed closed: {failure.capability}/{failure.cause}"
                )
        try:
            if pedagogical is not None:
                execution = self._adapter.execute(
                    turn_input, interaction=interaction, assessment=assessment,
                    pedagogy=pedagogical,
                )
            elif assessment is not None:
                execution = self._adapter.execute(
                    turn_input, interaction=interaction, assessment=assessment
                )
            else:
                execution = self._adapter.execute(turn_input, interaction=interaction)
        except LegacyAdapterFailure as failure:
            self._supervisor.observe_turn((failure.signal,))
            action = self._recovery_policy.decide(failure.signal)
            if action is not RecoveryAction.FAIL_CLOSED:
                raise RuntimeError(
                    "temporary legacy failures may only use fail-closed recovery"
                ) from failure
            raise failure.original.with_traceback(failure.original.__traceback__)
        self._validate_phase_trace(execution)
        extracted_failures = (
            perception_failures
            + (() if assessment is None else assessment.failures)
            + (() if pedagogical is None else pedagogical.failures)
        )
        if extracted_failures:
            execution = replace(
                execution,
                result=replace(
                    execution.result,
                    failures=extracted_failures + execution.result.failures,
                ),
            )
        recovery_actions = tuple(
            self._recovery_policy.decide(failure)
            for failure in execution.result.failures
        )
        self._supervisor.observe_turn(execution.result.failures)
        if RecoveryAction.FAIL_CLOSED in recovery_actions:
            failure = execution.result.failures[
                recovery_actions.index(RecoveryAction.FAIL_CLOSED)
            ]
            raise RuntimeError(
                f"Turn failed closed: {failure.capability}/{failure.cause}"
            )
        result = execution.result
        explicit_degradations = tuple(
            failure.cause
            for failure, action in zip(result.failures, recovery_actions)
            if action in {
                RecoveryAction.DEGRADE,
                RecoveryAction.SAFE_NON_ASSESSING_FALLBACK,
            }
            and failure.cause not in result.degradation_reasons
        )
        if explicit_degradations:
            result = replace(
                result,
                degradation_reasons=result.degradation_reasons + explicit_degradations,
            )
        return CoordinatedTurn(
            result=result,
            phases=execution.phase_trace,
            measurements=dict(execution.measurements),
            recovery_actions=recovery_actions,
        )

    @staticmethod
    def _validate_phase_trace(execution: LegacyExecution) -> None:
        if execution.phase_trace != LOGICAL_TURN_PHASES:
            raise RuntimeError("Turn adapter did not traverse the logical phase sequence")
