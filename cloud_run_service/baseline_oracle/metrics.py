"""Performance summaries and Baseline Split regression gates."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


def summarize_performance(
    startup: Mapping[str, float | int],
    observations: Sequence[Mapping[str, Any]],
) -> dict[str, float | int]:
    metrics = [row.get("metrics", {}) for row in observations]
    usage = [row.get("model_usage", {}) for row in observations]
    return {
        "startup_ms": float(startup.get("startup_ms") or 0.0),
        "non_model_p95_ms": _p95(metrics, "non_model_ms"),
        "time_to_first_audio_p95_ms": _p95(metrics, "time_to_first_audio_ms"),
        "total_latency_p95_ms": _p95(metrics, "total_ms"),
        "steady_state_model_calls_max": max(
            (int(row.get("model_calls") or 0) for row in usage), default=0
        ),
        "model_client_constructions": int(
            startup.get("model_client_constructions") or 0
        ),
        "presentation_selection_p95_ms": _p95(
            metrics, "presentation_selection_ms"
        ),
    }


def compare_performance(
    reference: Mapping[str, float | int],
    candidate: Mapping[str, float | int],
    *,
    non_model_tolerance: float,
) -> tuple[str, ...]:
    failures: list[str] = []
    for key in ("steady_state_model_calls_max", "model_client_constructions"):
        before, after = int(reference.get(key, 0)), int(candidate.get(key, 0))
        if after > before:
            failures.append(f"{key} increased from {before} to {after}")

    before = float(reference.get("non_model_p95_ms", 0.0))
    after = float(candidate.get("non_model_p95_ms", 0.0))
    if after > before * (1.0 + non_model_tolerance):
        failures.append(
            f"non_model_p95_ms increased from {before:g} to {after:g} "
            f"(tolerance {non_model_tolerance:.0%})"
        )
    return tuple(failures)


def _p95(rows: Sequence[Mapping[str, Any]], key: str) -> float:
    values = sorted(float(row[key]) for row in rows if row.get(key) is not None)
    if not values:
        return 0.0
    return values[max(0, math.ceil(0.95 * len(values)) - 1)]
