"""Backward-compatible import aliases for the retired adapter module.

No runtime entrypoint imports this module.  It remains temporarily so older
offline fixtures can migrate without changing their setup in the same commit.
"""

from .turn_runtime import TurnRuntime, TurnRuntimeFailure


class LegacyTurnAdapter(TurnRuntime):
    """Compatibility constructor for pre-contract test fixtures."""

    def __init__(self, *, legacy_turn, commit_state, state):
        super().__init__(
            turn_behavior=legacy_turn,
            commit_state=commit_state,
            state=state,
        )


LegacyAdapterFailure = TurnRuntimeFailure

<<<<<<< HEAD
__all__ = ["LegacyAdapterFailure", "LegacyTurnAdapter"]
=======
    def assessment_request(self, turn_input: TurnInput, interaction):
        from assessment_evidence import AssessmentRequest, AssessmentStateView

        session = self._state.data.get("session") or {}
        return AssessmentRequest(
            turn_input=turn_input,
            state=AssessmentStateView(
                learner_id=str(self._state.data.get("learner_id") or ""),
                pending_assessment=copy.deepcopy(session.get("pending_check")),
                evidence_keys=tuple((self._state.data.get("evidence_index") or {}).keys()),
                hint_progress=copy.deepcopy(session.get("hint_progress") or {}),
            ),
            answer_attempt=bool(getattr(interaction.value, "answer_attempt", False)),
            perception_degraded=bool(
                getattr(interaction.value, "perception_degraded", False)
            ),
            precomputed_grade=turn_input.trusted_observations.get("precomputed_grade"),
        )

    def pedagogy_request(self, turn_input: TurnInput, observation, assessment):
        from cognitive_classifier.cues import (
            is_clarification_request,
            is_learning_request,
            is_pure_ack,
            is_purpose_question,
            is_question,
            is_visualization_request,
        )
        from pedagogy import PedagogyObservation, PedagogyRequest, PedagogyStateView
        from session_modes import mode_cues

        session = copy.deepcopy(self._state.data.get("session") or {})
        # Duplicate concept supplier deleted (ticket 04 / issue 12, site 4):
        # the session fallback was a silent re-inheritance.  concept_id is None
        # when Gemini abstains; callers downstream guard on `if primary`.
        concept_id = observation.concept_id
        concept = (self._state.data.get("concept_states") or {}).get(concept_id) or {}
        mastery_fn = getattr(self._state, "mastery", None)
        transfer_fn = getattr(self._state, "transfer_readiness", None)
        assessment_value = None if assessment is None else assessment.value
        analysis = deep_thaw(observation.analysis)
        normalized = str(analysis.get("normalized_text") or "").strip()
        signals = tuple(observation.signals)
        # ticket 03: analysis["problem_cue"] deleted; read observation.problem
        # (a ProblemReading) instead.
        problem = analysis.get("problem")
        return PedagogyRequest(
            turn_input=turn_input,
            observation=PedagogyObservation(
                normalized_text=normalized,
                concept_id=observation.concept_id,
                signals=signals,
                concept_flags=tuple(
                    (analysis.get("state_deltas") or {}).get("concept_flags") or ()
                ),
                cognitive_update=observation.cognitive_update,
                abstained=bool((analysis.get("concept") or {}).get("abstained")),
                answer_attempt=observation.answer_attempt,
                perception_degraded=observation.perception_degraded,
                acknowledged=is_pure_ack(normalized),
                clarification_requested=(
                    is_clarification_request(normalized)
                    or "simplification_request" in signals
                ),
                visualization_requested=is_visualization_request(normalized),
                purpose_requested=is_purpose_question(normalized),
                learning_requested=is_learning_request(normalized),
                question=is_question(normalized),
                learner_problem=bool(problem and problem.is_directive_problem),
                requested_mode=mode_cues(normalized),
            ),
            state=PedagogyStateView(
                session=session,
                mastery=(
                    float(mastery_fn(concept_id)) if callable(mastery_fn) and concept_id
                    else float(concept.get("mastery", 0.2))
                ),
                transfer_readiness=(
                    float(transfer_fn(concept_id)) if callable(transfer_fn) and concept_id
                    else float(concept.get("transfer_readiness", 0.0))
                ),
                has_active_misconception=any(
                    value.get("status") == "active"
                    for value in (self._state.data.get("misconception_states") or {}).values()
                    if isinstance(value, Mapping)
                ),
            ),
            prior_outcome=(
                assessment_value.grade.outcome
                if assessment_value is not None and assessment_value.grade is not None
                and assessment_value.pending_kind in {"practice", "test", "parallel_retest"}
                else None
            ),
            prior_hints=(0 if assessment_value is None else assessment_value.hints_used),
        )

    def retrieval_request(self, turn_input: TurnInput, observation, pedagogical):
        from retrieval import RetrievalRequest, RetrievalStateView, RetrievalStoreView

        engine = getattr(self._legacy_turn, "__self__", None)
        data = self._state.data
        concept_states = data.get("concept_states") or {}
        mastery = {
            str(concept_id): float(row.get("mastery", 0.2))
            for concept_id, row in concept_states.items() if isinstance(row, Mapping)
        }
        session = data.get("session") or {}
        analysis = deep_thaw(observation.analysis)
        concept = analysis.get("concept") or {}
        # ticket 03: pass the normalized text so retrieval reads the observation
        # instead of interaction["text"].
        normalized_text = str(analysis.get("normalized_text") or "").strip()
        return RetrievalRequest(
            turn_input=turn_input,
            normalized_text=normalized_text,
            concept_id=observation.concept_id,
            concept_confidence=float(concept.get("concept_confidence") or 0.0),
            secondary_concepts=tuple(concept.get("secondary_concepts") or ()),
            pedagogical=pedagogical,
            perception_uncertain=observation.perception_degraded,
            state=RetrievalStateView(
                mastery=mastery,
                measured_concepts=frozenset(
                    concept_id for concept_id, row in concept_states.items()
                    if isinstance(row, Mapping) and row.get("mastery") is not None
                ),
                misconceptions=copy.deepcopy(data.get("misconception_states") or {}),
                representations_known={
                    concept_id: tuple(row.get("representations_known") or ())
                    for concept_id, row in concept_states.items() if isinstance(row, Mapping)
                },
                served_items=tuple(session.get("served_items") or ()),
                bridges_served=tuple(session.get("bridges_served") or ()),
                hint_progress=copy.deepcopy(session.get("hint_progress") or {}),
                hope_rolling=copy.deepcopy(data.get("hope_rolling") or {}),
                concept_metadata=copy.deepcopy(concept_states),
                pending_assessment=bool(session.get("pending_check")),
            ),
            store=RetrievalStoreView(
                concepts=tuple(getattr(engine, "concepts", ()) or ()),
                chunks=tuple(getattr(engine, "chunks", ()) or ()),
                graph=getattr(engine, "graph", None),
                chunk_embeddings=getattr(engine, "chunk_emb", None),
            ),
        )

    def response_planning_request(self, turn_input, observation, pedagogical, retrieval):
        from response_planning import ResponsePlanningRequest, ResponsePlanningStateView

        analysis = deep_thaw(observation.analysis)
        cognitive = observation.cognitive_update
        # Duplicate concept supplier deleted (ticket 04 / issue 12, site 5a).
        concept_id = observation.concept_id
        engine = getattr(self._legacy_turn, "__self__", None)
        graph = getattr(engine, "graph", None)
        node = graph.nodes.get(concept_id, {}) if graph is not None and concept_id else {}
        evidence = retrieval.manifest.evidence
        return ResponsePlanningRequest(
            turn_input=turn_input, pedagogical=pedagogical, retrieval=retrieval,
            concept_id=concept_id,
            state=ResponsePlanningStateView(
                concept_type=node.get("concept_type") or node.get("kind"),
                misconception_targets=tuple(item.id for item in evidence
                                            if item.type == "misconception"),
                representation_targets=tuple(dict.fromkeys(
                    rep for item in evidence
                    for rep in (item.content.get("supports_representation") or ()))),
                cognitive_load=float(cognitive.get("cognitive_load", 0.0)),
                frustration_risk=float(cognitive.get("frustration_risk", 0.0)),
                mastery=float(((self._state.data.get("concept_states") or {})
                               .get(concept_id) or {}).get("mastery", 0.2)),
                clarification="simplification_request" in observation.signals,
            ),
        )

    def response_generation_request(self, turn_input, observation, pedagogical,
                                    retrieval, response_plan):
        from response_generation import ResponseGenerationRequest, ResponseGenerationStateView

        session = self._state.data.get("session") or {}
        engine = getattr(self._legacy_turn, "__self__", None)
        # Duplicate concept supplier deleted (ticket 04 / issue 12, site 5b).
        concept_id = observation.concept_id
        graph = getattr(engine, "graph", None)
        node = graph.nodes.get(concept_id, {}) if graph is not None and concept_id else {}
        proposal = response_plan.assessment_proposal
        deterministic = (proposal.hook.question if pedagogical.action == "TEST_QUESTION"
                         and proposal is not None else None)
        return ResponseGenerationRequest(
            turn_input=turn_input, pedagogical=pedagogical, retrieval=retrieval,
            response_plan=response_plan,
            state=ResponseGenerationStateView(
                history=tuple(copy.deepcopy(session.get("context") or ())[-6:]),
                clarification="simplification_request" in observation.signals,
                figure_on_screen="display" in response_plan.approved_modalities,
                chapter_hint=str(node.get("chapter_name") or "Class 10 Mathematics"),
            ), deterministic_spoken=deterministic,
        )

    def execute(self, turn_input: TurnInput, interaction=None, assessment=None,
                pedagogy=None, retrieval=None, response_plan=None,
                generated_response=None):
        return self._execute(
            turn_input, interaction_outcome=interaction, assessment_outcome=assessment,
            pedagogy_outcome=pedagogy, retrieval_outcome=retrieval,
            response_plan_outcome=response_plan,
            generated_response_outcome=generated_response,
        )

    def _execute(self, turn_input: TurnInput, interaction_outcome=None,
                 assessment_outcome=None, pedagogy_outcome=None,
                 retrieval_outcome=None, response_plan_outcome=None,
                 generated_response_outcome=None):
        # Imported lazily to keep the adapter/coordinator modules acyclic.
        from .coordinator import LOGICAL_TURN_PHASES, LegacyExecution

        interaction = deep_thaw(turn_input.interaction)
        trusted = deep_thaw(turn_input.trusted_observations)
        starting_state = copy.deepcopy(self._state.data)
        try:
            state_changes = (
                () if interaction_outcome is None else interaction_outcome.state_changes
            )
            if assessment_outcome is not None:
                state_changes += assessment_outcome.state_changes
            if pedagogy_outcome is not None:
                state_changes += pedagogy_outcome.state_changes
            if retrieval_outcome is not None:
                state_changes += retrieval_outcome.state_changes
            state_changes = self._apply_state_changes(
                turn_input.learner_id, state_changes
            )
            assessment_value = None
            if assessment_outcome is not None and assessment_outcome.value is not None:
                assessment_value = assessment_outcome.value
            decision = (
                None if interaction_outcome is None else interaction_outcome.value
            )
            if decision is not None and decision.disposition.value == "complete":
                compatibility = deep_thaw(decision.compatibility)
            else:
                controlled_text = (
                    str(interaction["text"])
                    if decision is None
                    else decision.text
                )
                kwargs = {
                    "answer_budget": interaction.get("answer_budget"),
                    "precomputed_analysis": trusted.get("precomputed_analysis"),
                    "precomputed_grade": trusted.get("precomputed_grade"),
                    "stt_confidence": trusted.get("stt_confidence"),
                    "turn_id": turn_input.turn_id,
                    "learner_id": turn_input.learner_id,
                    "_allow_shift": bool(interaction.get("allow_topic_shift", True)),
                }
                if decision is not None:
                    kwargs["precomputed_analysis"] = deep_thaw(decision.analysis)
                    kwargs["_interaction_controlled"] = True
                    kwargs["_perception_degraded"] = decision.perception_degraded
                    kwargs["_perception_uncertain"] = decision.perception_degraded
                    kwargs["_interaction_answer_attempt"] = decision.answer_attempt
                    kwargs["_perception_state_applied"] = any(
                        change.owner == "perception" for change in state_changes
                    )
                if assessment_value is not None:
                    kwargs["_prior_assessment"] = assessment_value
                if pedagogy_outcome is not None:
                    kwargs["_pedagogy_decision"] = pedagogy_outcome.value
                if retrieval_outcome is not None:
                    kwargs["_retrieval_result"] = retrieval_outcome.value
                kwargs["_response_plan"] = (
                    None if response_plan_outcome is None else response_plan_outcome.value
                )
                if generated_response_outcome is not None:
                    kwargs["_generated_response"] = generated_response_outcome.value
                compatibility = dict(self._legacy_turn(controlled_text, **kwargs))
                if decision is not None:
                    continuity_changes = decision.response_state_changes(
                        str(compatibility.get("answer") or "")
                    )
                    state_changes += self._apply_state_changes(
                        turn_input.learner_id, continuity_changes
                    )
        except Exception as exc:
            self._restore(starting_state)
            signal = FailureSignal(
                capability="legacy_runtime",
                phase="legacy_execution",
                severity=FailureSeverity.FATAL,
                recoverable=False,
                cause=f"{type(exc).__name__}: {exc}",
                valid_outcome=False,
                context={"adapter": self.name},
            )
            raise LegacyAdapterFailure(original=exc, signal=signal) from exc

        try:
            self._commit_state()
        except Exception as exc:
            rollback_persisted = self._restore(starting_state)
            signal = FailureSignal(
                capability="state_and_persistence",
                phase="commit",
                severity=FailureSeverity.FATAL,
                recoverable=False,
                cause=f"{type(exc).__name__}: {exc}",
                valid_outcome=False,
                context={
                    "adapter": self.name,
                    "rollback_persisted": rollback_persisted,
                },
            )
            raise LegacyAdapterFailure(original=exc, signal=signal) from exc

        state_version = _state_version(self._state.data)
        material = f"{turn_input.turn_id}\x1f{turn_input.learner_id}\x1f{state_version}"
        commit = TurnCommit(
            commit_id="legacy_commit_" + hashlib.sha256(
                material.encode("utf-8")
            ).hexdigest()[:24],
            turn_id=turn_input.turn_id,
            learner_id=turn_input.learner_id,
            applied_change_ids=tuple(change.change_id for change in state_changes),
            state_version=state_version,
        )
        delivered = []
        if compatibility.get("answer"):
            delivered.append("speech")
        if compatibility.get("display") or compatibility.get("visual"):
            delivered.append("display")
        result = TurnResult(
            turn_id=turn_input.turn_id,
            learner_id=turn_input.learner_id,
            outcome=compatibility,
            compatibility=compatibility,
            realization=RealizationReceipt(
                turn_id=turn_input.turn_id,
                status=RealizationStatus.PARTIAL,
                intended=tuple(delivered),
                delivered=(),
                details={
                    "source": self.name,
                    "observation": "presentation_occurs_after_tutor_loop_facade",
                },
            ),
            commit=commit,
            failures=(
                () if interaction_outcome is None else interaction_outcome.failures
            ),
        )
        generation = (None if generated_response_outcome is None
                      else generated_response_outcome.value)
        return LegacyExecution(
            result=result,
            phase_trace=LOGICAL_TURN_PHASES,
            measurements={
                "legacy_adapter_turns": 1,
                "legacy_adapter_unextracted_phases": len(LOGICAL_TURN_PHASES)
                - (1 if interaction_outcome is not None else 0)
                - (1 if generation is not None else 0),
                "response_generation_model_calls": (
                    0 if generation is None else generation.model_calls
                ),
                "model_client_constructions": (
                    0 if generation is None else generation.client_constructions
                ),
            },
        )

    def _apply_state_changes(self, learner_id: str, changes):
        if not changes:
            return ()
        from state_and_persistence import (
            CapabilityStateAccess,
            WorkingStateProjection,
        )

        access = {
            "interaction_control": CapabilityStateAccess(
                learner_write=(("safety_alerts",),),
                session_write=tuple(
                    (path,) for path in (
                        "current_concept",
                        "pending_shift",
                        "context",
                        "status",
                        "leave_requests",
                        "break_requested",
                        "steer_streak",
                        "safety_alert",
                    )
                ),
            ),
            "assessment_evidence": CapabilityStateAccess(
                learner_read=(("evidence_index",),),
                session_read=(("pending_check",), ("hint_progress",)),
                learner_write=(("evidence_ledger",),),
                session_write=(("pending_check",), ("pending_hope",)),
            ),
            "pedagogy": CapabilityStateAccess(
                session_write=tuple(
                    (path,) for path in (
                        "mode",
                        "test_state",
                        "practice_plan",
                        "practice_state",
                        "pending_mode_offer",
                        "pending_test_resume",
                    )
                ),
            ),
            "perception": CapabilityStateAccess(
                learner_write=(
                    ("global",),
                    ("global_observations",),
                ),
            ),
            "retrieval": CapabilityStateAccess(
                session_write=(("served_items",), ("bridges_served",)),
            ),
        }
        projection = WorkingStateProjection(
            learner_id=learner_id,
            state=self._state.data,
            access=access,
        )
        applied = tuple(change for change in changes if projection.apply(change))
        self._state.data = projection.projected_state()
        return applied

    def _restore(self, starting_state: Mapping[str, Any]) -> bool:
        self._state.data = copy.deepcopy(dict(starting_state))
        save = getattr(self._state, "save", None)
        if not callable(save):
            return False
        try:
            save()
        except Exception:
            return False
        return True
>>>>>>> afk/deterministic-input-layer-20260827
