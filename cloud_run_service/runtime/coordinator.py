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
    from retrieval import RetrievalInterface
    from response_planning import ResponsePlanningInterface
    from response_generation import ResponseGenerationInterface


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

    def retrieval_request(self, turn_input: TurnInput, observation, pedagogical): ...

    def response_planning_request(self, turn_input: TurnInput, observation,
                                  pedagogical, retrieval): ...

    def response_generation_request(self, turn_input: TurnInput, observation,
                                    pedagogical, retrieval, response_plan): ...

    def execute(self, turn_input: TurnInput, interaction, assessment=None,
                pedagogy=None, retrieval=None, response_plan=None,
                generated_response=None, personal_data=None) -> LegacyExecution: ...


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
        utterance_intake: Any = None,
        child_safety: Any = None,
        personal_data: Any = None,
        perception: "PerceptionInterface | None" = None,
        assessment_evidence: "AssessmentEvidenceInterface | None" = None,
        pedagogy: "PedagogyInterface | None" = None,
        retrieval: "RetrievalInterface | None" = None,
        response_planning: "ResponsePlanningInterface | None" = None,
        response_generation: "ResponseGenerationInterface | None" = None,
        recovery_policy: RecoveryPolicy | None = None,
    ) -> None:
        self._adapter = adapter
        self._supervisor = supervisor
        self._interaction_control = interaction_control
        self._utterance_intake = utterance_intake
        self._child_safety = child_safety
        self._personal_data = personal_data
        self._perception = perception
        self._assessment_evidence = assessment_evidence
        self._pedagogy = pedagogy
        self._retrieval = retrieval
        self._response_planning = response_planning
        self._response_generation = response_generation
        self._recovery_policy = recovery_policy or RecoveryPolicy()

    def run(self, turn_input: TurnInput) -> CoordinatedTurn:
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
        # ---------------------------------------------------------------
        # Safety is dispatched FIRST, before perception, on EVERY turn
        # (SAFETY_ROUTE_TAXONOMY.md §7.1). Read the three "no"s in that order:
        #
        #  * no precondition — not a lexicon trip, not a keyword, not a cheap
        #    pre-filter. Gating this would reinstate the regex as gatekeeper,
        #    which is the arrangement the taxonomy inverted;
        #  * no authorization check — invariant 1. It is dispatched *above* the
        #    `_skip_perception` branch precisely so an UNAUTHORIZED turn, where
        #    perception never runs, still gets its safety call. A child whose
        #    microphone was poor is not a child who said nothing;
        #  * no ordering after perception — safety's prompt is small (no ~6k
        #    cached concept block, no MiniLM hints), so its verdict is *expected*
        #    to land first and the hold below is expected to cost nothing.
        # ---------------------------------------------------------------
        safety_dispatch = None
        if self._child_safety is not None:
            safety_dispatch = self._child_safety.dispatch(
                utterance_id=self._utterance_id(turn_input, observation),
                text=self._turn_text(turn_input, observation),
                summary=self._safety_summary(interaction_request.session),
            )
        # ---------------------------------------------------------------
        # Personal data is dispatched IMMEDIATELY AFTER INTAKE
        # (PERSONAL_DATA_CONTRACT.md §2), and immediately after safety —
        # 12's safety-first ordering is preserved, and both are non-blocking.
        #
        # "After Intake" is forced, not preferred: redaction is exact-match
        # against `normalized_text` (§4), and Intake is what produces it.
        # Intake is pure, deterministic and sub-millisecond, so this costs
        # nothing.
        #
        # Dispatched on EVERY turn, including an UNAUTHORIZED one: a repair
        # screen still writes an analytics row, and that row is a persisting
        # sink like any other.
        # ---------------------------------------------------------------
        personal_data_dispatch = None
        if self._personal_data is not None:
            personal_data_dispatch = self._personal_data.dispatch(
                utterance_id=self._utterance_id(turn_input, observation),
                text=self._turn_text(turn_input, observation),
                context=self._personal_data_context(interaction_request.session),
            )
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
        # ---------------------------------------------------------------
        # THE HOLD (invariant 6). Perception's output is assembled above but is
        # not released to Interaction Control until the safety verdict has been
        # analyzed — this call is the only thing standing between the two.
        #
        # It is BOUNDED, and the bound is the design: `await_verdict` waits at
        # most the remainder of the 5s envelope and then returns a TIMEOUT
        # verdict, which is a non-answer rather than a negative one. Unbounded
        # was rejected — a hung safety call would freeze every turn, trading one
        # child's disclosure for every child's lesson. On expiry the turn is
        # released in degraded mode, where the outage net contributes and the
        # record carries `safety_model_unavailable`; the call itself is NOT
        # cancelled, so a late verdict can still union in and escalate (§6.4).
        # ---------------------------------------------------------------
        if safety_dispatch is not None:
            interaction_request = replace(
                interaction_request, safety=safety_dispatch.await_verdict()
            )
        # ---------------------------------------------------------------
        # THE PERSISTING-SINK DEADLINE (PERSONAL_DATA_CONTRACT.md §7).
        #
        # Interaction Control writes the turn's analytics row, so the verdict
        # has to be resolved before it runs. §7 gives persisting sinks the
        # **full 5s envelope**, and that is what `await_verdict` waits — this
        # is the one place the personal-data path is allowed to cost the child
        # wall-clock, and it is bounded.
        #
        # In practice it costs nothing: the call was dispatched right after
        # Intake, its envelope has been running through the whole
        # perception span, and (when safety is wired) the hold above has
        # already consumed the same wall-clock. What lands here is normally a
        # verdict that arrived several hundred milliseconds ago.
        #
        # `turn_redaction` is where the identifier-bearing verdict STOPS. What
        # continues past this line is placeholder text and class labels; the
        # verdict object is dropped and never crosses another seam (§4).
        # ---------------------------------------------------------------
        redaction = None
        if personal_data_dispatch is not None:
            from personal_data import turn_redaction

            redaction = turn_redaction(
                self._turn_text(turn_input, observation),
                personal_data_dispatch.await_verdict(),
            )
        interaction_request = replace(
            interaction_request, personal_data=redaction
        )
        interaction = self._interaction_control.control(interaction_request)
        # `_skip_perception` leaves `perception` unbound, so it must be re-tested
        # here and not only at the dispatch above: an UNAUTHORIZED turn has no
        # perception outcome to merge state changes from, and reaching for one
        # raised UnboundLocalError before the safety path made that turn
        # completable rather than a dead end.
        if self._perception is not None and not _skip_perception and perception.state_changes:
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
        retrieved = None
        if self._retrieval is not None and pedagogical is not None:
            retrieved = self._retrieval.retrieve(
                self._adapter.retrieval_request(
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
                self._adapter.response_planning_request(
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
                self._adapter.response_generation_request(
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
        try:
            # `personal_data` is the same TurnRedaction the Interaction Control
            # request carries — the legacy turn holds the other converted sinks
            # (`_log_shift`, the generation prompt), and both must see one
            # redaction for the turn rather than each redacting for itself.
            if planned is not None:
                execution = self._adapter.execute(
                    turn_input, interaction=interaction, assessment=assessment,
                    pedagogy=pedagogical, retrieval=retrieved,
                    response_plan=planned_for_execution,
                    generated_response=generated,
                    personal_data=redaction,
                )
            elif retrieved is not None:
                execution = self._adapter.execute(
                    turn_input, interaction=interaction, assessment=assessment,
                    pedagogy=pedagogical, retrieval=retrieved,
                    personal_data=redaction,
                )
            elif pedagogical is not None:
                execution = self._adapter.execute(
                    turn_input, interaction=interaction, assessment=assessment,
                    pedagogy=pedagogical, personal_data=redaction,
                )
            elif assessment is not None:
                execution = self._adapter.execute(
                    turn_input, interaction=interaction, assessment=assessment,
                    personal_data=redaction,
                )
            else:
                execution = self._adapter.execute(
                    turn_input, interaction=interaction, personal_data=redaction
                )
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
            + (() if retrieved is None else retrieved.failures)
            + (() if planned is None else planned.failures)
            + (() if generated is None else generated.failures)
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

    # ------------------------------------------------------------------
    # What the safety call is handed — and, by omission, what it is not
    # ------------------------------------------------------------------
    @staticmethod
    def _utterance_id(turn_input: TurnInput, observation: Any) -> str:
        """The memo key (§7.1): an opaque id, never the text.

        Ticket 02 moved the memo off normalized text precisely so a replayed turn
        cannot re-bill and two children saying the same words cannot share a
        verdict. ``turn_id`` is the fallback for the typed legacy path, which has
        no Utterance and therefore no provenance.
        """
        utterance = getattr(observation, "utterance", None) or turn_input.utterance
        provenance = getattr(utterance, "provenance", None)
        return getattr(provenance, "utterance_id", None) or turn_input.turn_id

    @staticmethod
    def _turn_text(turn_input: TurnInput, observation: Any) -> str:
        """The normalized published form when Intake produced one, else the raw
        interaction text. Normalization exists in exactly one place; both model
        calls read its output rather than re-deriving a second form.

        For the safety call this is a preference. For the personal-data call it is
        load-bearing: redaction is exact-match on this exact string
        (PERSONAL_DATA_CONTRACT.md §4), so handing the detector one form and the
        redactor another would fail every turn closed.
        """
        if observation is not None:
            return observation.normalized_text
        return str(turn_input.interaction.get("text") or "")

    @staticmethod
    def _safety_summary(session: Mapping[str, Any]) -> Any:
        """§7.5: a COUNT and a MAX SEVERITY, plus ``session["context"][-2:]``.

        Never classes and never prior text. Class labels are the disclosure
        category the personal-data contract wants minimised, and replaying
        "abuse was disclosed six turns ago" into a later prompt invites the model
        to confirm rather than detect. The type enforces the rule at this call
        site instead of leaving it to be remembered at review time.
        """
        from child_safety import SafetySessionSummary

        accumulator = session.get("safety_accumulator") or {}
        # Thaw BEFORE slicing. A frozen session holds `context` as a tuple of
        # mappingproxies; slicing first hands `deep_thaw` a plain list, which falls
        # through to `copy.deepcopy` and raises "cannot pickle 'mappingproxy'".
        # Thawing first walks the tuple properly and yields plain dicts.
        context = deep_thaw(session.get("context") or ())
        return SafetySessionSummary(
            prior_safety_findings=int(accumulator.get("count", 0) or 0),
            prior_max_severity=accumulator.get("max_severity"),
            recent_context=tuple(context[-2:]),
        )

    @staticmethod
    def _personal_data_context(session: Mapping[str, Any]) -> Any:
        """§14: ``session["context"][-2:]`` — one preceding exchange, and nothing else.

        It is the only thing that catches the split disclosure: the tutor asks
        something and the child answers *"it's 98765"*, which without context is
        indistinguishable from an answer and must be left alone.

        Note what is deliberately absent, and how it differs from ``_safety_summary``
        one method above. The safety prompt gets a count and a max severity; this one
        gets **no session summary at all**. §9 forbids the standing behavioural record
        ("this child disclosed an address on this date") that would be needed to supply
        a prior-disclosure count — building one in the name of privacy is exactly the
        thing DPDP §9(3) bans.
        """
        from personal_data import PersonalDataContext

        # Thaw BEFORE slicing, for the reason spelled out in `_safety_summary`: a
        # frozen session holds `context` as a tuple of mappingproxies, and slicing
        # first hands `deep_thaw` a plain list that falls through to `copy.deepcopy`
        # and raises "cannot pickle 'mappingproxy'".
        context = deep_thaw(session.get("context") or ())
        return PersonalDataContext(recent_context=tuple(context[-2:]))

    @staticmethod
    def _validate_phase_trace(execution: LegacyExecution) -> None:
        if execution.phase_trace != LOGICAL_TURN_PHASES:
            raise RuntimeError("Turn adapter did not traverse the logical phase sequence")
