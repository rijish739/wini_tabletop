"""Prior-attempt grading and evidence production behind one public seam."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping, Protocol

from evidence.contracts import GradeResult
from evidence.grading import grade_answer, obvious_non_attempt
from evidence.ledger import make_idempotency_key
from items.authored import from_authored
from runtime.contracts import (
    FailureSeverity,
    FailureSignal,
    ModuleOutcome,
    StateChange,
    StateOperation,
    StateScope,
    TurnInput,
    deep_freeze,
)
from runtime_flags import GRADER_WRITE_CONFIDENCE_MIN


CAPABILITY = "assessment_evidence"


@dataclass(frozen=True)
class AssessmentStateView:
    """Immutable state limited to facts required to assess a prior attempt."""

    learner_id: str
    pending_assessment: Mapping[str, Any] | None
    evidence_keys: tuple[str, ...] = ()
    hint_progress: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "pending_assessment", deep_freeze(
            self.pending_assessment) if self.pending_assessment is not None else None)
        object.__setattr__(self, "evidence_keys", tuple(self.evidence_keys))
        object.__setattr__(self, "hint_progress", deep_freeze(self.hint_progress or {}))


@dataclass(frozen=True)
class AssessmentRequest:
    turn_input: TurnInput
    state: AssessmentStateView
    answer_attempt: bool
    perception_degraded: bool = False
    precomputed_grade: GradeResult | Mapping[str, Any] | str | None = None
    # The Utterance Intake observation — non-None in production; None only in
    # legacy test stubs that predate the field.  Assessment grades and writes
    # only when authorization is AUTHORIZED.
    observation: Any = None


@dataclass(frozen=True)
class AssessmentResult:
    attempted: bool
    grade: GradeResult | None = None
    writeback_status: str | None = None
    pending_item_id: str | None = None
    pending_kind: str | None = None
    hints_used: int = 0


class AssessmentEvidenceInterface(Protocol):
    def evaluate_prior_attempt(
        self, request: AssessmentRequest
    ) -> ModuleOutcome[AssessmentResult]: ...


class AssessmentEvidence:
    """Own grading validity and produce changes for the authoritative writer."""

    def __init__(self, model_call: Callable[..., str] | None = None) -> None:
        self._model_call = model_call

    def evaluate_prior_attempt(
        self, request: AssessmentRequest
    ) -> ModuleOutcome[AssessmentResult]:
        pending = request.state.pending_assessment
        if pending is None:
            return ModuleOutcome(value=AssessmentResult(attempted=False))
        # Ticket 05: Assessment must not grade or write from an unauthorized
        # transcript — reaching here with a non-AUTHORIZED observation is an
        # invariant violation (the coordinator skips assessment on UNAUTHORIZED
        # turns).  Raise so the coordinator's fail-closed path catches it; a
        # silent return here would let a write slip through with no record.
        if request.observation is not None:
            from utterance_intake.observation import Authorization as _Authorization
            if request.observation.authorization is not _Authorization.AUTHORIZED:
                raise AssertionError(
                    "invariant violation: Assessment.evaluate_prior_attempt "
                    f"called with authorization={request.observation.authorization!r}; "
                    "the coordinator must not forward non-AUTHORIZED observations "
                    "to Assessment"
                )
        integrity_failure = self._validate(request, pending)
        if integrity_failure is not None:
            return ModuleOutcome(value=None, failures=(integrity_failure,))

        # Ticket 11: interaction["text"] channel deleted — observation is always non-None
        # in production. Legacy test stubs that predate the observation field fall back
        # to interaction["text"] so they keep working without requiring a full rewrite.
        refused_parse = False
        if request.observation is not None:
            text = request.observation.normalized_text
            parse = request.observation.transcript.parse
            if parse is not None:
                from utterance_intake.observation import ParseOutcome
                if parse.outcome is ParseOutcome.ACCEPT and parse.interpretation:
                    text = parse.interpretation
                elif parse.outcome in (ParseOutcome.REFUSE_AMBIGUOUS, ParseOutcome.REFUSE_OUT_OF_GRAMMAR):
                    refused_parse = True
                elif parse.outcome is ParseOutcome.PASSTHROUGH:
                    text = request.observation.normalized_text
        else:
            # Legacy test stubs that predate the observation field: try utterance.text
            # first (compatibility facade always sets utterance), then interaction["text"].
            _utt = request.turn_input.utterance
            text = str(
                (_utt.text if _utt is not None else None)
                or (request.turn_input.interaction or {}).get("text")
                or ""
            )

        item_id = str(pending.get("item_id") or pending.get("id"))
        key = make_idempotency_key(
            request.turn_input.learner_id, request.turn_input.turn_id, item_id, text
        )
        # Ticket 11: trusted_observations["stt_confidence"] deleted; read from Utterance directly.
        utterance = request.turn_input.utterance
        stt_confidence = utterance.confidence if utterance is not None else None
        if request.perception_degraded or refused_parse:
            grade = GradeResult(
                "not_an_answer", "refused_parse" if refused_parse else "uncertain_perception",
                0.0, None, stt_confidence, key,
            )
        elif not request.answer_attempt or obvious_non_attempt(text):
            grade = GradeResult(
                "not_an_answer", "non_attempt_gate", 1.0, None,
                stt_confidence, key,
            )
        else:
            grade = self._grade(request, pending, text, key, stt_confidence)

        result = AssessmentResult(
            attempted=grade.outcome != "not_an_answer",
            grade=grade,
            writeback_status="not_attempted",
            pending_item_id=item_id,
            pending_kind=pending.get("kind"),
            hints_used=self._hints_used(request.state, pending),
        )
        if grade.outcome not in {"correct", "partial", "wrong"}:
            return ModuleOutcome(value=result)
        if grade.confidence < GRADER_WRITE_CONFIDENCE_MIN:
            return ModuleOutcome(value=replace(result, writeback_status="low_confidence"))

        disarm = StateChange(
            change_id=f"{request.turn_input.turn_id}:assessment:disarm:{item_id}",
            owner=CAPABILITY,
            scope=StateScope.SESSION,
            path=("pending_check",),
            operation=StateOperation.DELETE,
            idempotency_key=f"{key}:disarm",
        )
        if key in request.state.evidence_keys:
            return ModuleOutcome(
                value=replace(result, writeback_status="duplicate"),
                state_changes=(disarm,),
            )
        event = self._event(request, pending, grade, key, item_id)
        evidence = StateChange(
            change_id=f"{request.turn_input.turn_id}:assessment:evidence:{item_id}",
            owner=CAPABILITY,
            scope=StateScope.LEARNER,
            path=("evidence_ledger",),
            operation=StateOperation.APPEND,
            value=event,
            idempotency_key=key,
        )
        return ModuleOutcome(
            value=replace(result, writeback_status="pending"),
            state_changes=(evidence, disarm),
        )

    def prepare_grounded_item(
        self, *, concept_id: str | None, evidence, graph, pedagogical,
        pending_assessment: bool, perception_uncertain: bool,
        practice_candidate: Callable[[str | None], Mapping[str, Any] | None] | None = None,
    ) -> Mapping[str, Any] | None:
        """Govern current-turn assessable-item selection from grounded evidence."""
        if pending_assessment or perception_uncertain:
            return None
        for item in evidence:
            if item["type"] not in {"bridge_diagnostic", "misconception"}:
                continue
            question = item.get("question") or item.get("diagnostic_question")
            if not question:
                continue
            node = graph.nodes.get(item["id"], {})
            kind = "bridge" if item["type"] == "bridge_diagnostic" else "misconception"
            authored = from_authored({
                "id": item["id"], "concept_id": concept_id,
                "question": question, "expected_answer": node.get("expected_answer", ""),
                "rubric": node.get("rubric") or node.get("why_wrong") or "",
                "assessment_purpose": "diagnose_barrier" if kind == "bridge"
                else "diagnose_misconception",
                "response_type": node.get("response_type") or "short_text",
                "reveal_policy": node.get("reveal_policy") or "after_attempt",
                "hint_chain": item.get("hint_chain") or node.get("hint_chain"),
                "verification_provenance": node.get("verification_provenance") or "authored_store",
                "verification_version": node.get("verification_version") or "store-v1",
                "item_source": kind,
                "metadata": {"representations": node.get("supports_representation") or []},
            })
            if authored is not None:
                return {**authored.to_dict(), "kind": kind, "id": authored.item_id,
                        "difficulty": node.get("difficulty")}
        plan = dict(pedagogical.plan or {})
        if pedagogical.mode == "TEST" and plan.get("pending"):
            return plan["pending"]
        if (pedagogical.mode == "PRACTICE" and pedagogical.action in {
                "ISOMORPHIC_PRACTICE", "COMPLETION_STEP", "TRANSFER_PROBLEM"
            } and practice_candidate is not None):
            return practice_candidate(concept_id)
        return None

    def _grade(self, request, pending, text, key, stt_confidence) -> GradeResult:
        if request.precomputed_grade is not None:
            grade = GradeResult.from_value(request.precomputed_grade)
            if grade.idempotency_key in {None, key}:
                return replace(grade, stt_confidence=stt_confidence,
                               idempotency_key=key)
        return grade_answer(
            str(pending["question"]), str(pending.get("expected_answer") or ""), text,
            str(pending.get("rubric") or ""), model_call=self._model_call,
            stt_confidence=stt_confidence, idempotency_key=key,
            misconception_probe=pending.get("kind") == "misconception",
        )

    @staticmethod
    def _validate(request, pending) -> FailureSignal | None:
        context = {"turn_id": request.turn_input.turn_id,
                   "item_id": pending.get("item_id") or pending.get("id")}
        if (
            request.state.learner_id
            and request.turn_input.learner_id
            and request.state.learner_id != request.turn_input.learner_id
        ):
            cause = "assessment_learner_mismatch"
        elif (
            pending.get("item_verified") is False
            or (
                pending.get("verification_status") is not None
                and pending.get("verification_status") not in {"verified", "authored_verified"}
            )
        ):
            cause = "legacy_unverified_pending_assessment"
        elif (
            pending.get("realized_turn_id") is not None
            and pending.get("realized_turn_id") == request.turn_input.turn_id
        ):
            cause = "stale_pending_assessment"
        elif not pending.get("question"):
            cause = "malformed_pending_assessment"
        else:
            return None
        return FailureSignal(
            capability=CAPABILITY,
            phase="prior_attempt_grading",
            severity=FailureSeverity.ERROR,
            recoverable=False,
            cause=cause,
            valid_outcome=False,
            context=context,
        )

    @staticmethod
    def _hints_used(state: AssessmentStateView, pending: Mapping[str, Any]) -> int:
        concept_id = str(pending.get("concept_id") or "")
        item_id = str(pending.get("item_id") or pending.get("id") or "")
        row = state.hint_progress.get(concept_id) or {}
        if row.get("problem_id") != item_id:
            return 0
        try:
            return max(0, int(row.get("hints_used") or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _event(request, pending, grade, key, item_id) -> dict[str, Any]:
        metadata = dict(pending.get("metadata") or {})
        hints_used = AssessmentEvidence._hints_used(request.state, pending)
        return {
            "event_id": f"evt_{key[:24]}",
            "script_id": str(pending["script_id"]),
            "beat_id": str(pending["beat_id"]),
            "attempt": int(pending.get("attempt") or 1),
            "turn_id": request.turn_input.turn_id,
            "idempotency_key": key,
            "assessment_hook_id": pending.get("hook_id"),
            "outcome": grade.outcome,
            "learner_id": request.turn_input.learner_id,
            "concept_id": pending.get("concept_id"),
            "kc_id": pending.get("kc_id") or pending.get("concept_id"),
            "item_id": item_id,
            "item_source": pending.get("item_source"),
            "assessment_purpose": pending.get("assessment_purpose"),
            "grader_path": grade.grader_path,
            "grader_confidence": grade.confidence,
            "stt_confidence": grade.stt_confidence,
            "consistent_with_misconception": grade.misconception_consistency,
            "assistance_offered": hints_used,
            "assistance_consumed": hints_used,
            "delay_days": float(pending.get("delay_days") or 0.0),
            "action": pending.get("action") or "unknown",
            "barrier": pending.get("barrier") or "unknown",
            "mode": pending.get("mode") or "EXPLAIN",
            "payload": {
                "mutation_kind": pending.get("kind"),
                "target_concept": pending.get("concept_id"),
                "target_misconception": pending.get("target_misconception"),
                "difficulty": pending.get("difficulty") or metadata.get("difficulty"),
                "hints_used": hints_used,
                "binary_item": bool(pending.get("binary_item", False)),
                "representations": metadata.get("representations") or [],
            },
        }
