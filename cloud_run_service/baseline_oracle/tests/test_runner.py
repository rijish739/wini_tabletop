from __future__ import annotations

import hashlib
import json
import unittest

from baseline_oracle.corpus import REQUIRED_BEHAVIOR_TAGS, FrozenCorpus
from baseline_oracle.runner import OracleRunner, RuntimeTurn


def _sha(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


class _RuntimeAdapter:
    name = "canonical-test-adapter"

    def startup(self) -> dict:
        return {"startup_ms": 12.0, "model_client_constructions": 0}

    def run_turn(self, case, state, model_gateway, emit) -> RuntimeTurn:
        perception = model_gateway.call(case["id"], "perception", {"text": case["turn_input"]["text"]})
        emit({"kind": "speech_delta", "sequence": 0, "text": "Quadratics"})
        emit({"kind": "turn_meta", "sequence": 1, "action": "EXPLAIN"})
        emit({"kind": "turn_result", "sequence": 2, "committed": True})
        after = json.loads(json.dumps(state))
        after["session"]["last_action"] = "EXPLAIN"
        result = {"action": "EXPLAIN", "answer": perception["answer"]}
        return RuntimeTurn(
            result=result,
            compatibility={"answer": perception["answer"], "action": "EXPLAIN"},
            state_after=after,
            state_changes=[{"path": "session.last_action", "after": "EXPLAIN"}],
            evidence_events=[],
            assessment_lifecycle={"armed": None, "voided": None},
            manifest={"evidence": [], "bridge_ids": []},
            realization_receipt={"speech": "realized", "visual": "not_requested"},
            failure_signals=[],
            degradation_reasons=[],
            metrics={"non_model_ms": 1.2, "total_ms": 413.7, "presentation_selection_ms": 0.2},
        )


class OracleRunnerTests(unittest.TestCase):
    def test_records_every_observable_surface_and_stream_order(self) -> None:
        request = {"text": "Explain quadratics"}
        corpus = FrozenCorpus.from_data(
            states={"cold_start": {"learner_id": "fixture-learner", "session": {}}},
            cases=[{
                "id": "learning-explain",
                "state": "cold_start",
                "turn_input": request,
                "tags": sorted(REQUIRED_BEHAVIOR_TAGS),
            }],
            recordings=[{
                "case_id": "learning-explain",
                "boundary": "perception",
                "call_index": 0,
                "request_sha256": _sha(request),
                "response": {"answer": "A quadratic has degree two."},
                "finish_state": "STOP",
                "schema": "perception-v2",
                "redactions": ["learner_identity"],
                "latency_ms": 412.5,
            }],
        )

        run = OracleRunner(corpus).run(_RuntimeAdapter())

        observation = run.observations[0]
        self.assertEqual(
            [event["kind"] for event in observation["stream_events"]],
            ["speech_delta", "turn_meta", "turn_result"],
        )
        self.assertEqual(observation["model_usage"]["model_calls"], 1)
        self.assertEqual(observation["state_before"]["session"], {})
        self.assertEqual(observation["state_after"]["session"]["last_action"], "EXPLAIN")
        self.assertIn("realization_receipt", observation)
        self.assertEqual(run.startup["startup_ms"], 12.0)


if __name__ == "__main__":
    unittest.main()
