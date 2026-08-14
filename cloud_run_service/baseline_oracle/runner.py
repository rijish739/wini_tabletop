"""Public runner seam for capturing comparable runtime observations."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from .corpus import FrozenCorpus
from .replay import ReplayModelGateway


@dataclass(frozen=True)
class RuntimeTurn:
    result: Mapping[str, Any]
    compatibility: Mapping[str, Any]
    state_after: Mapping[str, Any]
    state_changes: Sequence[Mapping[str, Any]]
    evidence_events: Sequence[Mapping[str, Any]]
    assessment_lifecycle: Mapping[str, Any]
    manifest: Mapping[str, Any]
    realization_receipt: Mapping[str, Any]
    failure_signals: Sequence[Mapping[str, Any]]
    degradation_reasons: Sequence[str]
    metrics: Mapping[str, float | int]


class RuntimeAdapter(Protocol):
    name: str

    def startup(self) -> Mapping[str, float | int]: ...

    def run_turn(
        self,
        case: Mapping[str, Any],
        state: Mapping[str, Any],
        model_gateway: ReplayModelGateway,
        emit: Any,
    ) -> RuntimeTurn: ...


@dataclass(frozen=True)
class OracleRun:
    adapter: str
    startup: Mapping[str, float | int]
    observations: tuple[Mapping[str, Any], ...]


class OracleRunner:
    def __init__(self, corpus: FrozenCorpus):
        self._corpus = corpus

    def run(self, adapter: RuntimeAdapter) -> OracleRun:
        self._corpus.validate()
        startup = dict(adapter.startup())
        gateway = ReplayModelGateway(self._corpus.recordings)
        observations: list[Mapping[str, Any]] = []

        for case in self._corpus.cases:
            state_before = copy.deepcopy(self._corpus.states[str(case["state"])])
            working_state = copy.deepcopy(state_before)
            stream_events: list[Mapping[str, Any]] = []
            before_usage = gateway.usage
            turn = adapter.run_turn(case, working_state, gateway, stream_events.append)
            after_usage = gateway.usage
            observations.append({
                "case_id": case["id"],
                "tags": list(case.get("tags", [])),
                "result": copy.deepcopy(dict(turn.result)),
                "compatibility": copy.deepcopy(dict(turn.compatibility)),
                "state_before": state_before,
                "state_after": copy.deepcopy(dict(turn.state_after)),
                "state_changes": copy.deepcopy(list(turn.state_changes)),
                "evidence_events": copy.deepcopy(list(turn.evidence_events)),
                "assessment_lifecycle": copy.deepcopy(dict(turn.assessment_lifecycle)),
                "manifest": copy.deepcopy(dict(turn.manifest)),
                "realization_receipt": copy.deepcopy(dict(turn.realization_receipt)),
                "stream_events": copy.deepcopy(stream_events),
                "failure_signals": copy.deepcopy(list(turn.failure_signals)),
                "degradation_reasons": list(turn.degradation_reasons),
                "metrics": dict(turn.metrics),
                "model_usage": {
                    "model_calls": after_usage.model_calls - before_usage.model_calls,
                    "client_constructions": (
                        after_usage.client_constructions - before_usage.client_constructions
                    ),
                    "recorded_latency_ms": (
                        after_usage.recorded_latency_ms - before_usage.recorded_latency_ms
                    ),
                },
            })

        return OracleRun(str(adapter.name), startup, tuple(observations))
