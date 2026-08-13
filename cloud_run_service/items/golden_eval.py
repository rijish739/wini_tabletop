"""Human-checkable generated-item verification golden set.

Run from ``cloud_run_service`` with ``python -m items.golden_eval``. The 98%
gate is measured over explicit accept/reject judgments; no model call is made.
"""
from __future__ import annotations

import json

from .contracts import CandidateItem
from .verify import verify


# question, proposed key, independently derived key, human expected acceptance
GOLDEN_CASES = [
    ("What is 2 plus 3?", "5", "5", True),
    ("What is 7 plus 8?", "15", "15", True),
    ("What is 9 minus 4?", "5", "5", True),
    ("What is 12 minus 7?", "5", "5", True),
    ("What is 6 times 7?", "42", "42", True),
    ("What is 8 times 9?", "72", "72", True),
    ("What is 56 divided by 7?", "8", "8", True),
    ("What is 81 divided by 9?", "9", "9", True),
    ("What is the square of 11?", "121", "121", True),
    ("What is the square root of 144?", "12", "12", True),
    ("Solve x plus 4 equals 9. What is x?", "5", "5", True),
    ("Solve 2 times x equals 14. What is x?", "7", "7", True),
    ("What is 25 percent of 80?", "20", "20", True),
    ("What is one half of 18?", "9", "9", True),
    ("What is three quarters of 20?", "15", "15", True),
    ("A triangle has angles 50 and 60 degrees. What is the third angle?", "70", "70", True),
    ("A rectangle is 5 cm by 4 cm. What is its area in square cm?", "20", "20", True),
    ("A square has side 6 cm. What is its perimeter in cm?", "24", "24", True),
    ("What is the HCF of 12 and 18?", "6", "6", True),
    ("What is the LCM of 4 and 6?", "12", "12", True),
    ("What is 3 cubed?", "27", "27", True),
    ("What is 100 minus 37?", "63", "63", True),
    ("What is 15 plus 27?", "42", "42", True),
    ("What is 13 times 5?", "65", "65", True),
    ("What is 96 divided by 12?", "8", "8", True),
    ("What is 2 plus 3?", "6", "5", False),
    ("What is 7 plus 8?", "14", "15", False),
    ("What is 9 minus 4?", "4", "5", False),
    ("What is 12 minus 7?", "6", "5", False),
    ("What is 6 times 7?", "41", "42", False),
    ("What is 8 times 9?", "81", "72", False),
    ("What is 56 divided by 7?", "7", "8", False),
    ("What is 81 divided by 9?", "8", "9", False),
    ("What is the square of 11?", "22", "121", False),
    ("What is the square root of 144?", "14", "12", False),
    ("Solve x plus 4 equals 9. What is x?", "13", "5", False),
    ("Solve 2 times x equals 14. What is x?", "12", "7", False),
    ("What is 25 percent of 80?", "25", "20", False),
    ("What is one half of 18?", "8", "9", False),
    ("What is three quarters of 20?", "12", "15", False),
    ("A triangle has angles 50 and 60 degrees. What is the third angle?", "80", "70", False),
    ("A rectangle is 5 cm by 4 cm. What is its area in square cm?", "18", "20", False),
    ("A square has side 6 cm. What is its perimeter in cm?", "36", "24", False),
    ("What is the HCF of 12 and 18?", "3", "6", False),
    ("What is the LCM of 4 and 6?", "24", "12", False),
    ("What is 3 cubed?", "9", "27", False),
    ("What is 100 minus 37?", "73", "63", False),
    ("What is 15 plus 27?", "41", "42", False),
    ("What is 13 times 5?", "60", "65", False),
    ("What is 96 divided by 12?", "12", "8", False),
]


def evaluate() -> dict:
    disagreements = []
    for index, (question, proposed, independent, expected_accept) in enumerate(
            GOLDEN_CASES, start=1):
        item = verify(CandidateItem(
            concept_id="golden::arithmetic", question=question,
            expected_answer=proposed), independent_answer=independent, cache=False)
        actual_accept = item is not None
        if actual_accept != expected_accept:
            disagreements.append({
                "case": index, "question": question, "proposed": proposed,
                "independent": independent, "expected_accept": expected_accept,
                "actual_accept": actual_accept,
            })
    total = len(GOLDEN_CASES)
    agreement = (total - len(disagreements)) / total if total else 0.0
    return {
        "schema_version": 1, "cases": total,
        "agreements": total - len(disagreements),
        "agreement": round(agreement, 4), "required_gate": 0.98,
        "gate_met": agreement >= 0.98, "disagreements": disagreements,
    }


if __name__ == "__main__":
    result = evaluate()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["gate_met"] else 1)
