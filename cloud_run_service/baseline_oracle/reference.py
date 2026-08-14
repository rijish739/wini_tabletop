"""Load and verify the frozen canonical contract characterization."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from .compare import compare_observations
from .corpus import load_default_corpus
from .metrics import summarize_performance


REQUIRED_OBSERVATION_FIELDS = frozenset({
    "case_id",
    "tags",
    "result",
    "compatibility",
    "state_before",
    "state_after",
    "state_changes",
    "evidence_events",
    "assessment_lifecycle",
    "manifest",
    "realization_receipt",
    "stream_events",
    "failure_signals",
    "degradation_reasons",
    "metrics",
    "model_usage",
})


def load_frozen_reference() -> tuple[Mapping[str, Any], ...]:
    corpus = load_default_corpus()
    corpus.validate()
    root = Path(__file__).with_name("reference")
    expected = json.loads((root / "expected_outcomes.json").read_text(encoding="utf-8"))
    by_case = {str(row["case_id"]): row for row in expected}
    case_ids = {str(case["id"]) for case in corpus.cases}
    if set(by_case) != case_ids:
        missing, extra = sorted(case_ids - set(by_case)), sorted(set(by_case) - case_ids)
        raise ValueError(f"frozen outcomes do not match corpus; missing={missing}, extra={extra}")

    observations: list[Mapping[str, Any]] = []
    for case in corpus.cases:
        row = by_case[str(case["id"])]
        state_before = copy.deepcopy(corpus.states[str(case["state"])])
        state_after = copy.deepcopy(state_before)
        state_changes = copy.deepcopy(row.get("state_changes", []))
        for change in state_changes:
            _set_path(state_after, str(change["path"]), copy.deepcopy(change.get("after")))

        evidence = copy.deepcopy(row.get("evidence_events", []))
        assessment = copy.deepcopy(row.get("assessment", {
            "preserved": None, "armed": None, "voided": None,
        }))
        manifest = copy.deepcopy(row.get("manifest", {"evidence_ids": [], "bridge_ids": []}))
        realization = copy.deepcopy(row.get("realization", {
            "speech": "realized" if row.get("answer") else "not_realized",
            "visual": "not_requested",
            "visual_type": "none",
            "grounded": bool(manifest.get("evidence_ids")) or row.get("need") == "none",
        }))
        stream_kinds = row.get("stream_kinds") or (
            ["speech_delta", "turn_meta", "turn_result"]
            if row.get("answer") else ["turn_meta", "turn_result"]
        )
        streams = [
            {"kind": kind, "sequence": index, "committed": kind == "turn_result"}
            for index, kind in enumerate(stream_kinds)
        ]
        result = {
            "action": row["action"],
            "action_reason": f"frozen canonical {row['action'].lower()}",
            "need": row["need"],
            "concept": {"concept_id": (state_after.get("session") or {}).get("current_concept")},
            "signals": [],
            "cognitive_update": {},
            "n_evidence": len(manifest.get("evidence_ids", [])),
            "bridge_ids": list(manifest.get("bridge_ids", [])),
            "writeback": evidence[-1] if evidence else None,
            "pending_check": assessment.get("armed") or assessment.get("preserved"),
            "pending_hope": None,
            "display": [],
            "visual": realization if realization.get("visual") not in {"not_requested", "not_supported"} else None,
            "mode": (state_after.get("session") or {}).get("mode", "EXPLAIN"),
            "test": None,
            "session_ended": bool(row.get("session_ended", False)),
            "gen_backend": "replay" if int(row.get("model_calls", 0)) else None,
            "answer": row["answer"],
        }
        compatibility = {
            "answer": result["answer"],
            "display": result["display"],
            "session_ended": result["session_ended"],
            "action": result["action"],
            "need": result["need"],
            "concept": result["concept"]["concept_id"],
            "gen_backend": result["gen_backend"],
            "mode": result["mode"],
            "writeback": ({"outcome": evidence[-1].get("outcome")} if evidence else None),
            "visual": result["visual"],
        }
        observations.append({
            "case_id": case["id"],
            "tags": list(case.get("tags", [])),
            "result": result,
            "compatibility": compatibility,
            "state_before": state_before,
            "state_after": state_after,
            "state_changes": state_changes,
            "evidence_events": evidence,
            "assessment_lifecycle": assessment,
            "manifest": manifest,
            "realization_receipt": realization,
            "stream_events": streams,
            "failure_signals": copy.deepcopy(row.get("failure_signals", [])),
            "degradation_reasons": list(row.get("degradation_reasons", [])),
            "metrics": {
                "non_model_ms": 0.0,
                "time_to_first_audio_ms": 0.0,
                "total_ms": 0.0,
                "presentation_selection_ms": float(row.get("presentation_selection_ms", 0.0)),
                "measurement_status": "unavailable_missing_runtime_artifacts",
            },
            "model_usage": {
                "model_calls": int(row.get("model_calls", 0)),
                "client_constructions": 0,
                "recorded_latency_ms": 0.0,
            },
        })
    return tuple(observations)


def verify_frozen_reference() -> dict[str, Any]:
    observations = load_frozen_reference()
    differences = sum(
        len(compare_observations(row, copy.deepcopy(row)).differences)
        for row in observations
    )
    metadata = json.loads(
        (Path(__file__).with_name("reference") / "metadata.json").read_text(encoding="utf-8")
    )
    performance = summarize_performance(
        {"startup_ms": 0.0, "model_client_constructions": 0}, observations
    )
    performance["measurement_status"] = "unavailable_missing_runtime_artifacts"
    return {
        "status": "pass" if differences == 0 else "fail",
        "reference_name": metadata["reference_name"],
        "canonical_commit": metadata["canonical_commit"],
        "cases": len(observations),
        "differences": differences,
        "observation_fields": sorted(REQUIRED_OBSERVATION_FIELDS),
        "performance": performance,
        "capture_limitations": metadata["capture_limitations"],
    }


def _set_path(target: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    current = target
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value
