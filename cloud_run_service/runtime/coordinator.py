"""Feature-neutral sequencing and current-Turn recovery for the tutor runtime."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping, Protocol

from .contracts import FailureSeverity, FailureSignal, TurnInput, TurnResult, deep_thaw
from .turn_runtime import TurnRuntimeFailure
from .supervisor import RuntimeSupervisor

if TYPE_CHECKING:
    from assessment_evidence import AssessmentEvidenceInterface, AssessmentRequest
    from interaction_control import (
        InteractionControlInterface,
        InteractionControlRequest,
    )
    from perception import PerceptionInterface
    from pedagogy import PedagogyInterface
    from retrieval import RetrievalInterface
    from response_planning import ResponsePlanningInterface
    from response_generation import ResponseGenerationInterface
    from presentation import PresentationInterface


class TurnPhase(str, Enum):
    ADMISSION_AND_ROUTING = "admission_and_routing"
    UTTERANCE_INTAKE = "utterance_intake"
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
class TurnExecution:
    """Lifecycle result produced by the canonical Turn runtime."""

    result: TurnResult
    phase_trace: tuple[TurnPhase, ...]
    measurements: Mapping[str, int | float] = field(default_factory=dict)


# Import compatibility for fixtures written before the runtime contract was
# named.  The coordinator itself only uses TurnExecution.
LegacyExecution = TurnExecution


class TurnRuntimePort(Protocol):
    name: str

    def interaction_request(
        self, turn_input: TurnInput
    ) -> "InteractionControlRequest": ...

    def perception_request(self, turn_input: TurnInput): ...

    def assessment_request(self, turn_input: TurnInput, interaction) -> "AssessmentRequest": ...

    def assessment_arming_request(self, turn_input: TurnInput, response_plan,
                                  realization) -> Any: ...

    def pedagogy_request(self, turn_input: TurnInput, observation, assessment): ...

    def retrieval_request(self, turn_input: TurnInput, observation, pedagogical): ...

    def response_planning_request(self, turn_input: TurnInput, observation,
                                  pedagogical, retrieval): ...

    def response_generation_request(self, turn_input: TurnInput, observation,
                                    pedagogical, retrieval, response_plan): ...

    def execute(self, turn_input: TurnInput, interaction, assessment=None,
                pedagogy=None, retrieval=None, response_plan=None,
                generated_response=None, realization=None,
                assessment_arming=None) -> TurnExecution: ...


@dataclass(frozen=True)
class CoordinatedTurn:
    result: TurnResult
    phases: tuple[TurnPhase, ...]
    measurements: Mapping[str, int | float]
    recovery_actions: tuple[RecoveryAction, ...] = ()

    def serialize_compatibility(self) -> dict[str, Any]:
        return deep_thaw(self.result.compatibility)


class TurnCoordinator:
    """Sequence a Turn while leaving tutoring policy behind Module interfaces."""

    def __init__(
        self,
        *,
        runtime: TurnRuntimePort | None = None,
        adapter: TurnRuntimePort | None = None,
        supervisor: RuntimeSupervisor,
        interaction_control: "InteractionControlInterface",
        utterance_intake: Any = None,
        perception: "PerceptionInterface | None" = None,
        assessment_evidence: "AssessmentEvidenceInterface | None" = None,
        pedagogy: "PedagogyInterface | None" = None,
        retrieval: "RetrievalInterface | None" = None,
        response_planning: "ResponsePlanningInterface | None" = None,
        response_generation: "ResponseGenerationInterface | None" = None,
        presentation: "PresentationInterface | None" = None,
        recovery_policy: RecoveryPolicy | None = None,
    ) -> None:
        self._runtime = runtime or adapter
        if self._runtime is None:
            raise TypeError("runtime is required")
        self._supervisor = supervisor
        self._interaction_control = interaction_control
        self._utterance_intake = utterance_intake
        self._perception = perception
        self._assessment_evidence = assessment_evidence
        self._pedagogy = pedagogy
        self._retrieval = retrieval
        self._response_planning = response_planning
        self._response_generation = response_generation
        self._presentation = presentation
        self._recovery_policy = recovery_policy or RecoveryPolicy()

    def run(self, turn_input: TurnInput) -> CoordinatedTurn:
<<<<<<< HEAD
        interaction_request = self._runtime.interaction_request(turn_input)
        perception_failures: tuple[FailureSignal, ...] = ()
        if self._perception is not None:
            perception = self._perception.perceive(
                self._runtime.perception_request(turn_input)
            )
=======
        interaction_request = self._adapter.interaction_request(turn_input)
        # TurnPhase.UTTERANCE_INTAKE — runs before PERCEPTION_AND_PRIOR_GRADING.
        # Total, write-free, session-pure: it can only add a typed observation.
        observation = None
        if self._utterance_intake is not None and turn_input.utterance is not None:
            from utterance_intake import UtteranceIntakeRequest

            observation = self._utterance_intake.observe(
                UtteranceIntakeRequest(turn_input=turn_input)
            ).value
            # Ticket 04: forward the typed observation to Interaction Control so
            # it can read ReferenceReading without falling back to a private regex.
            interaction_request = replace(interaction_request, observation=observation)
        # Ticket 05: perception is NOT run on an UNAUTHORIZED turn —
        # Interaction Control's authorization gate produces the repair screen.
        _skip_perception = False
        if observation is not None:
            from utterance_intake.observation import Authorization as _Authorization
            if observation.authorization is _Authorization.UNAUTHORIZED:
                _skip_perception = True
        perception_failures: tuple[FailureSignal, ...] = ()
        if self._perception is not None and not _skip_perception:
            perception_request = self._adapter.perception_request(turn_input)
            if observation is not None:
                perception_request = replace(
                    perception_request, observation=observation
                )
            perception = self._perception.perceive(perception_request)
>>>>>>> afk/deterministic-input-layer-20260827
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
                self._runtime.assessment_request(turn_input, interaction)
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
                self._runtime.pedagogy_request(
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
        retrieved = None
        if self._retrieval is not None and pedagogical is not None:
            retrieved = self._retrieval.retrieve(
                self._runtime.retrieval_request(
                    turn_input, perception.value, pedagogical.value
                )
            )
            actions = tuple(
                self._recovery_policy.decide(failure)
                for failure in retrieved.failures
            )
            if not retrieved.valid or RecoveryAction.FAIL_CLOSED in actions:
                self._supervisor.observe_turn(retrieved.failures)
                failure = retrieved.failures[0]
                raise RuntimeError(
                    f"Turn failed closed: {failure.capability}/{failure.cause}"
                )
        planned = None
        if (self._response_planning is not None and retrieved is not None
                and not retrieved.failures):
            planned = self._response_planning.plan(
                self._runtime.response_planning_request(
                    turn_input, perception.value, pedagogical.value, retrieved.value
                )
            )
            actions = tuple(self._recovery_policy.decide(failure)
                            for failure in planned.failures)
            if not planned.valid or RecoveryAction.FAIL_CLOSED in actions:
                self._supervisor.observe_turn(planned.failures)
                failure = planned.failures[0]
                raise RuntimeError(
                    f"Turn failed closed: {failure.capability}/{failure.cause}"
                )
        generated = None
        planned_for_execution = planned
        if self._response_generation is not None and planned is not None:
            generated = self._response_generation.generate(
                self._runtime.response_generation_request(
                    turn_input, perception.value, pedagogical.value,
                    retrieved.value, planned.value,
                )
            )
            actions = tuple(self._recovery_policy.decide(failure)
                            for failure in generated.failures)
            if not generated.valid or RecoveryAction.FAIL_CLOSED in actions:
                self._supervisor.observe_turn(generated.failures)
                failure = generated.failures[0]
                raise RuntimeError(
                    f"Turn failed closed: {failure.capability}/{failure.cause}"
                )
            if generated.value is not None and not generated.value.assessing:
                planned_for_execution = replace(
                    planned,
                    value=replace(planned.value, assessment_proposal=None),
                )
        realization = None
        if self._presentation is not None and planned_for_execution is not None and generated is not None:
            from presentation import PresentationRequest
            realization = self._presentation.realize(PresentationRequest(
                turn_input=turn_input,
                response_plan=planned_for_execution.value,
                generated_response=generated.value,
            ))
            actions = tuple(self._recovery_policy.decide(failure)
                            for failure in realization.failures)
            if not realization.valid or RecoveryAction.FAIL_CLOSED in actions:
                self._supervisor.observe_turn(realization.failures)
                failure = realization.failures[0]
                raise RuntimeError(f"Turn failed closed: {failure.capability}/{failure.cause}")
        assessment_arming = None
        if (self._assessment_evidence is not None and planned_for_execution is not None
                and planned_for_execution.value.assessment_proposal is not None):
            assessment_arming = self._assessment_evidence.arm_after_realization(
                self._runtime.assessment_arming_request(
                    turn_input, planned_for_execution.value, realization.value
                    if realization is not None else None
                )
            )
            actions = tuple(self._recovery_policy.decide(failure)
                            for failure in assessment_arming.failures)
            if not assessment_arming.valid or RecoveryAction.FAIL_CLOSED in actions:
                self._supervisor.observe_turn(assessment_arming.failures)
                failure = assessment_arming.failures[0]
                raise RuntimeError(
                    f"Turn failed closed: {failure.capability}/{failure.cause}"
                )
        try:
            execution_kwargs = {}
            if self._presentation is not None:
                execution_kwargs["realization"] = (
                    None if realization is None else realization.value
                )
            if planned is not None:
                execute_kwargs = dict(
                    assessment_arming=assessment_arming,
                )
                execution = self._runtime.execute(
                    turn_input, interaction=interaction, assessment=assessment,
                    pedagogy=pedagogical, retrieval=retrieved,
                    response_plan=planned_for_execution,
                    generated_response=generated,
                    **execute_kwargs,
                    **execution_kwargs,
                )
            elif retrieved is not None:
                execution = self._runtime.execute(
                    turn_input, interaction=interaction, assessment=assessment,
                    pedagogy=pedagogical, retrieval=retrieved,
                )
            elif pedagogical is not None:
                execution = self._runtime.execute(
                    turn_input, interaction=interaction, assessment=assessment,
                    pedagogy=pedagogical,
                )
            elif assessment is not None:
                execution = self._runtime.execute(
                    turn_input, interaction=interaction, assessment=assessment
                )
            else:
                execution = self._runtime.execute(turn_input, interaction=interaction)
        except TurnRuntimeFailure as failure:
            self._supervisor.observe_turn((failure.signal,))
            action = self._recovery_policy.decide(failure.signal)
            if action is not RecoveryAction.FAIL_CLOSED:
                raise RuntimeError(
                    "Turn runtime failures may only use fail-closed recovery"
                ) from failure
            raise failure.original.with_traceback(failure.original.__traceback__)
        self._validate_phase_trace(execution)
        extracted_failures = (
            perception_failures
            + (() if assessment is None else assessment.failures)
            + (() if pedagogical is None else pedagogical.failures)
            + (() if retrieved is None else retrieved.failures)
            + (() if planned is None else planned.failures)
            + (() if generated is None else generated.failures)
            + (() if realization is None else realization.failures)
            + (() if assessment_arming is None else assessment_arming.failures)
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
    def _validate_phase_trace(execution: TurnExecution) -> None:
        if execution.phase_trace != LOGICAL_TURN_PHASES:
            raise RuntimeError("Turn runtime did not traverse the logical phase sequence")
