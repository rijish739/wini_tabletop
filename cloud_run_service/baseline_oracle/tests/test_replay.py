from __future__ import annotations

import hashlib
import json
import unittest

from baseline_oracle.replay import ReplayMismatch, ReplayModelGateway


def _fingerprint(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


class ReplayModelGatewayTests(unittest.TestCase):
    def test_replays_exact_boundary_call_without_constructing_a_client(self) -> None:
        request = {"text": "Explain quadratics", "schema": "perception-v2"}
        gateway = ReplayModelGateway([{
            "case_id": "learning-explain",
            "boundary": "perception",
            "call_index": 0,
            "request_sha256": _fingerprint(request),
            "response": {"intent": "LEARNING", "concept": "quadratics"},
            "finish_state": "STOP",
            "latency_ms": 412.5,
        }])

        response = gateway.call("learning-explain", "perception", request)

        self.assertEqual(response, {"intent": "LEARNING", "concept": "quadratics"})
        self.assertEqual(gateway.usage.model_calls, 1)
        self.assertEqual(gateway.usage.client_constructions, 0)

    def test_rejects_a_request_that_does_not_match_the_recording(self) -> None:
        gateway = ReplayModelGateway([{
            "case_id": "learning-explain",
            "boundary": "generation",
            "call_index": 0,
            "request_sha256": _fingerprint({"prompt": "frozen"}),
            "response": "A quadratic has degree two.",
            "finish_state": "STOP",
        }])

        with self.assertRaises(ReplayMismatch):
            gateway.call("learning-explain", "generation", {"prompt": "changed"})


if __name__ == "__main__":
    unittest.main()
