"""Local, model-free latency microbenchmark for the new P0 boundaries."""
from __future__ import annotations

import json
import statistics
import time

from evidence import record_outcome
from learner_state import LearnerState
from response_layer.contracts import OutcomeEvent
from response_layer.realization import check_realization


def _measure(fn, n: int) -> dict:
    values = []
    for i in range(n):
        start = time.perf_counter()
        fn(i)
        values.append((time.perf_counter() - start) * 1000.0)
    values.sort()
    return {
        "n": n, "mean_ms": round(statistics.fmean(values), 4),
        "p50_ms": round(values[n // 2], 4),
        "p95_ms": round(values[min(n - 1, int(n * 0.95))], 4),
        "max_ms": round(values[-1], 4),
    }


def evaluate() -> dict:
    realization = _measure(lambda _i: check_realization(
        "A grounded explanation using 2 and 3.",
        grounded_text="2 3", max_words=20, max_sentences=2), 5000)

    state = LearnerState(None, {
        "learner_id": "latency-learner", "concept_states": {},
        "misconception_states": {}, "global": {},
    })

    def append(i: int):
        record_outcome(state, OutcomeEvent(
            script_id=f"s{i}", beat_id="b", attempt=1, turn_id=f"t{i}",
            idempotency_token=f"latency:{i}", learner_id="latency-learner",
            concept_id="c1", item_id=f"item-{i}", item_source="authored",
            assessment_purpose="check_independent", outcome="correct",
            grader_path="deterministic", grader_confidence=1.0,
            stt_confidence=1.0,
            payload={"mutation_kind": "practice", "target_concept": "c1"},
        ))

    ledger_append = _measure(append, 1000)
    duplicate_event = OutcomeEvent(
        script_id="s0", beat_id="b", attempt=1, turn_id="t0",
        idempotency_token="latency:0", learner_id="latency-learner",
        concept_id="c1", item_id="item-0", item_source="authored",
        assessment_purpose="check_independent", outcome="correct",
        grader_path="deterministic", grader_confidence=1.0,
        stt_confidence=1.0,
        payload={"mutation_kind": "practice", "target_concept": "c1"},
    )
    duplicate = _measure(lambda _i: record_outcome(state, duplicate_event), 5000)
    return {
        "schema_version": 1,
        "realization_post_stream": realization,
        "ledger_incremental_append_in_memory": ledger_append,
        "duplicate_lookup": duplicate,
        "critical_path_model_calls_before": ["perception", "response_generation"],
        "critical_path_model_calls_after": ["perception", "response_generation"],
        "ttfa_added_ms": 0.0,
        "note": "Realization validation runs after streamed speech; item generation and verification are off-path.",
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
