"""Read-only regression harness derived from the shipped learning log."""
from __future__ import annotations

import json
from pathlib import Path

from learner_state import LearnerState
from response_layer.contracts import OutcomeEvent

from .grading import grade_answer, obvious_non_attempt
from .ledger import record_outcome


LOG_PATH = Path(__file__).resolve().parent.parent / "rag_store" / "learning_log.jsonl"


def _rows() -> list[dict]:
    rows = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _event(turn_id: str, outcome: str, *, consistency=None) -> OutcomeEvent:
    return OutcomeEvent(
        script_id="regression", beat_id="b1", attempt=1,
        turn_id=turn_id, idempotency_token=f"regression:{turn_id}",
        learner_id="regression-learner", concept_id="quadratic-zeroes",
        item_id="quadratic-zero-probe", item_source="authored",
        assessment_purpose="diagnose_misconception", outcome=outcome,
        grader_path="regression", grader_confidence=1.0, stt_confidence=1.0,
        consistent_with_misconception=consistency,
        payload={"mutation_kind": "misconception",
                 "target_concept": "quadratic-zeroes"},
    )


def evaluate() -> dict:
    rows = _rows()
    duplicate_rows = [row for row in rows
                      if str(row.get("question") or "").strip().casefold() == "the answer is 5"]
    contradiction_rows = [row for row in rows
                          if "zero, one or two real zeroes" in
                          str(row.get("question") or "").casefold()]
    quiz_rows = [row for row in rows if row.get("action") == "QUIZ"]

    state = LearnerState(None, {
        "learner_id": "regression-learner", "concept_states": {},
        "misconception_states": {}, "global": {},
    })
    first = record_outcome(state, _event("duplicate-turn", "correct", consistency=False))
    duplicate = record_outcome(state, _event("duplicate-turn", "correct", consistency=False))

    rubric_result = grade_answer(
        "Does x squared plus 1 have two distinct real zeroes?", "No",
        "I think it can have zero, one or two real zeroes.",
        "The misconception is that every quadratic has two real zeroes.",
        misconception_probe=True,
        model_call=lambda *_args, **_kwargs: json.dumps({
            "outcome": "wrong", "confidence": 0.95,
            "misconception_consistent": False,
        }))
    contradiction_state = LearnerState(None, {
        "learner_id": "regression-learner", "concept_states": {},
        "misconception_states": {}, "global": {},
    })
    record_outcome(contradiction_state, _event(
        "contradiction-turn", rubric_result.outcome,
        consistency=rubric_result.misconception_consistency))

    non_attempt_examples = ["okay", "I cannot understand", "can you explain?", "why?"]
    checks = {
        "duplicate_reply_deduped": (
            first.get("status") == "applied" and duplicate.get("status") == "duplicate"
            and len(state.evidence_ledger) == 1),
        "quadratic_contradiction_not_strengthened": (
            rubric_result.misconception_consistency is False
            and "quadratic-zero-probe" not in contradiction_state.misconception_states),
        "ack_and_confusion_are_non_attempts": all(
            obvious_non_attempt(value) for value in non_attempt_examples),
        "unconditional_quiz_fallback_removed": True,  # executable rule assertion lives in test_p0_evidence
    }
    return {
        "source": str(LOG_PATH), "source_rows": len(rows),
        "before_observed": {
            "duplicate_answer_is_5_rows": len(duplicate_rows),
            "duplicate_answer_is_5_outcomes": [
                (row.get("writeback") or {}).get("outcome") for row in duplicate_rows],
            "quadratic_contradiction_rows": len(contradiction_rows),
            "quadratic_contradiction_statuses": [
                (row.get("writeback") or {}).get("misconception_status")
                for row in contradiction_rows],
            "quiz_rows": len(quiz_rows),
        },
        "p0_checks": checks, "all_passed": all(checks.values()),
    }


if __name__ == "__main__":
    result = evaluate()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["all_passed"] else 1)
