"""Deterministic model-boundary replay with exact request matching."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class ReplayMismatch(LookupError):
    pass


@dataclass(frozen=True)
class ModelUsage:
    model_calls: int
    client_constructions: int
    recorded_latency_ms: float


class ReplayModelGateway:
    """A zero-network adapter for frozen external model responses."""

    def __init__(self, recordings: Sequence[Mapping[str, Any]]):
        self._recordings = {
            (str(row["case_id"]), str(row["boundary"]), int(row["call_index"])): row
            for row in recordings
        }
        self._next: dict[tuple[str, str], int] = {}
        self._calls = 0
        self._latency_ms = 0.0

    @property
    def usage(self) -> ModelUsage:
        return ModelUsage(self._calls, 0, self._latency_ms)

    def call(self, case_id: str, boundary: str, request: Any) -> Any:
        ordinal_key = (case_id, boundary)
        call_index = self._next.get(ordinal_key, 0)
        key = (case_id, boundary, call_index)
        row = self._recordings.get(key)
        if row is None:
            raise ReplayMismatch(f"no recording for {case_id}/{boundary} call {call_index}")

        actual = _fingerprint(request)
        expected = str(row.get("request_sha256") or "")
        if actual != expected:
            raise ReplayMismatch(
                f"request mismatch for {case_id}/{boundary} call {call_index}: "
                f"expected {expected}, got {actual}"
            )

        self._next[ordinal_key] = call_index + 1
        self._calls += 1
        self._latency_ms += float(row.get("latency_ms") or 0.0)
        if row.get("finish_state") == "TIMEOUT":
            raise TimeoutError(str(row.get("error") or "recorded model timeout"))
        return row.get("response")


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
