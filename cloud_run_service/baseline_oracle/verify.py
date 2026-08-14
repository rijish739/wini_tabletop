"""Candidate-to-reference equivalence verification."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .compare import compare_observations
from .reference import load_frozen_reference


def verify_candidate(candidate: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
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
        comparison = compare_observations(reference[case_id], candidate_by_id[case_id])
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
        "status": "pass" if not findings else "fail",
        "cases": len(reference),
        "failed_cases": len(failed_cases),
        "differences": len(findings),
        "findings": findings,
    }
