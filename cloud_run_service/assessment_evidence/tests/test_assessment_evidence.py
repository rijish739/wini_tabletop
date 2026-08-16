from __future__ import annotations

import unittest

from assessment_evidence import (
    AssessmentEvidence,
    AssessmentRequest,
    AssessmentStateView,
)
from runtime.contracts import (
    DeviceCapabilities,
    StateOperation,
    TurnBudgets,
    TurnInput,
)


def _turn(text: str = "5", *, turn_id: str = "turn-2") -> TurnInput:
    return TurnInput(
        turn_id=turn_id,
        learner_id="learner-1",
        interaction={"text": text},
        device=DeviceCapabilities(),
        budgets=TurnBudgets(total_ms=10_000),
    )


def _pending(**changes):
    value = {
        "id": "item-1",
        "item_id": "item-1",
        "script_id": "script-1",
        "beat_id": "beat-1",
        "hook_id": "hook-1",
        "question": "What is 2 plus 3?",
        "expected_answer": "5",
        "concept_id": "addition",
        "kind": "practice",
        "item_verified": True,
        "verification_status": "verified",
        "verification_token": "verified-token",
        "realized_turn_id": "turn-1",
    }
    value.update(changes)
    return value


class AssessmentEvidenceTests(unittest.TestCase):
    def request(self, *, text="5", pending=None, precomputed_grade=None,
                hint_progress=None):
        return AssessmentRequest(
            turn_input=_turn(text),
            state=AssessmentStateView(
                learner_id="learner-1",
                pending_assessment=_pending() if pending is None else pending,
                evidence_keys=(),
                hint_progress=hint_progress,
            ),
            answer_attempt=True,
            precomputed_grade=precomputed_grade,
        )

    def test_correct_attempt_proposes_authoritative_evidence_and_disarms(self):
        outcome = AssessmentEvidence().evaluate_prior_attempt(self.request())

        self.assertTrue(outcome.valid)
        self.assertEqual(outcome.value.grade.outcome, "correct")
        self.assertEqual(outcome.value.writeback_status, "pending")
        self.assertEqual(len(outcome.state_changes), 2)
        evidence, disarm = outcome.state_changes
        self.assertEqual(evidence.path, ("evidence_ledger",))
        self.assertEqual(evidence.operation, StateOperation.APPEND)
        self.assertEqual(evidence.value["outcome"], "correct")
        self.assertEqual(disarm.path, ("pending_check",))
        self.assertEqual(disarm.operation, StateOperation.DELETE)

    def test_assessment_state_view_is_deeply_immutable(self):
        pending = _pending(metadata={"representations": ["number_line"]})
        view = AssessmentStateView(
            learner_id="learner-1", pending_assessment=pending, evidence_keys=()
        )
        pending["metadata"]["representations"].append("array")
        self.assertEqual(
            view.pending_assessment["metadata"]["representations"],
            ("number_line",),
        )
        with self.assertRaises(TypeError):
            view.pending_assessment["question"] = "changed"

    def test_incorrect_attempt_uses_deterministic_floor(self):
        outcome = AssessmentEvidence().evaluate_prior_attempt(self.request(text="4"))
        self.assertEqual(outcome.value.grade.outcome, "wrong")
        self.assertEqual(outcome.value.grade.grader_path, "deterministic")
        self.assertEqual(len(outcome.state_changes), 2)

    def test_hint_usage_is_preserved_in_authoritative_evidence(self):
        outcome = AssessmentEvidence().evaluate_prior_attempt(self.request(
            hint_progress={
                "addition": {"problem_id": "item-1", "hints_used": 2}
            }
        ))
        event = outcome.state_changes[0].value
        self.assertEqual(event["assistance_consumed"], 2)
        self.assertEqual(outcome.value.hints_used, 2)

    def test_non_attempt_preserves_pending_assessment(self):
        request = self.request(text="I don't understand")
        request = AssessmentRequest(
            turn_input=request.turn_input,
            state=request.state,
            answer_attempt=False,
        )

        outcome = AssessmentEvidence().evaluate_prior_attempt(request)

        self.assertEqual(outcome.value.grade.outcome, "not_an_answer")
        self.assertEqual(outcome.state_changes, ())

    def test_partial_model_grade_is_accepted_above_threshold(self):
        grade = {
            "outcome": "partial", "grader_path": "rubric_model",
            "confidence": 0.9,
        }
        outcome = AssessmentEvidence().evaluate_prior_attempt(
            self.request(text="partly five", precomputed_grade=grade)
        )
        self.assertEqual(outcome.value.grade.outcome, "partial")
        self.assertEqual(len(outcome.state_changes), 2)

    def test_low_confidence_grade_preserves_pending_assessment(self):
        grade = {
            "outcome": "partial", "grader_path": "rubric_model",
            "confidence": 0.2,
        }
        outcome = AssessmentEvidence().evaluate_prior_attempt(
            self.request(text="maybe five", precomputed_grade=grade)
        )
        self.assertEqual(outcome.value.writeback_status, "low_confidence")
        self.assertEqual(outcome.state_changes, ())

    def test_duplicate_evidence_only_disarms_the_stale_pending_copy(self):
        first = AssessmentEvidence().evaluate_prior_attempt(self.request())
        key = first.value.grade.idempotency_key
        request = self.request()
        request = AssessmentRequest(
            turn_input=request.turn_input,
            state=AssessmentStateView(
                learner_id="learner-1",
                pending_assessment=_pending(),
                evidence_keys=(key,),
            ),
            answer_attempt=True,
        )
        duplicate = AssessmentEvidence().evaluate_prior_attempt(request)
        self.assertEqual(duplicate.value.writeback_status, "duplicate")
        self.assertEqual(len(duplicate.state_changes), 1)
        self.assertEqual(duplicate.state_changes[0].operation, StateOperation.DELETE)

    def test_unverified_and_stale_assessments_fail_closed(self):
        for pending, cause in (
            (_pending(item_verified=False, verification_status="legacy_unverified"),
             "legacy_unverified_pending_assessment"),
            (_pending(realized_turn_id="turn-2"), "stale_pending_assessment"),
        ):
            with self.subTest(cause=cause):
                outcome = AssessmentEvidence().evaluate_prior_attempt(
                    self.request(pending=pending)
                )
                self.assertIsNone(outcome.value)
                self.assertFalse(outcome.valid)
                self.assertEqual(outcome.failures[0].cause, cause)
                self.assertEqual(outcome.failures[0].capability, "assessment_evidence")


if __name__ == "__main__":
    unittest.main()
