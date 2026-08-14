"""Candidate-to-reference equivalence verification."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .compare import compare_observations
from .metrics import compare_performance, summarize_performance
from .reference import load_frozen_reference, verify_frozen_reference


def verify_candidate(
    candidate: Sequence[Mapping[str, Any]],
    *,
    candidate_startup: Mapping[str, float | int] | None = None,
) -> dict[str, Any]:
    reference_report = verify_frozen_reference()
    startup = dict(candidate_startup or {})
    if reference_report["status"] != "pass":
        return {
            "status": "blocked",
            "reason": "canonical_reference_incomplete",
            "reference_status": reference_report["status"],
            "candidate_startup": startup,
            "performance": {"status": "not_compared"},
            "cases": reference_report["cases"],
            "failed_cases": 0,
            "differences": 0,
            "findings": [],
        }

    diagnosis = diagnose_candidate_differences(candidate)
    findings = list(diagnosis["findings"])
    if not startup:
        return {
            "status": "blocked", "reason": "candidate_startup_missing",
            "reference_status": "pass", "candidate_startup": startup,
            "performance": {"status": "not_compared"},
            **diagnosis,
        }
    candidate_performance = summarize_performance(startup, list(candidate))
    performance_failures = compare_performance(
        reference_report["performance"], candidate_performance,
        non_model_tolerance=0.10,
    )
    performance = {
        "status": "pass" if not performance_failures else "fail",
        "reference": reference_report["performance"],
        "candidate": candidate_performance,
        "failures": list(performance_failures),
    }
    findings.extend({"case_id": "<performance>", "path": "performance",
                     "reason": failure} for failure in performance_failures)
    return {
        "status": "pass" if not findings else "fail",
        "reference_status": "pass",
        "candidate_startup": startup,
        "performance": performance,
        "cases": diagnosis["cases"],
        "failed_cases": diagnosis["failed_cases"],
        "differences": len(findings),
        "findings": findings,
    }


def diagnose_candidate_differences(
    candidate: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Report structural drift without issuing an equivalence verdict."""

    reference = {str(row["case_id"]): row for row in load_frozen_reference()}
    candidate_by_id = {str(row["case_id"]): row for row in candidate}
    findings: list[dict[str, Any]] = []
    failed_cases: set[str] = set()

    for case_id in sorted(set(reference) | set(candidate_by_id)):
        if case_id not in reference:
            findings.append({"case_id": case_id, "path": "", "reason": "unexpected_case"})
            failed_cases.add(case_id)
            continue
        if case_id not in candidate_by_id:
            findings.append({"case_id": case_id, "path": "", "reason": "missing_case"})
            failed_cases.add(case_id)
            continue
        comparison = compare_observations(
            reference[case_id], candidate_by_id[case_id],
            ignore_roots=frozenset({"metrics", "model_usage"}),
        )
        for difference in comparison.differences:
            findings.append({
                "case_id": case_id,
                "path": difference.path,
                "reason": difference.reason,
                "reference": difference.reference,
                "candidate": difference.candidate,
            })
            failed_cases.add(case_id)

    return {
        "cases": len(reference),
        "failed_cases": len(failed_cases),
        "differences": len(findings),
        "findings": findings,
    }
