"""Grader eval (Part 12 §7.2) — offline-first.

The mastery gate is decided by five graded items, so the grader is graded here.
This runs the DETERMINISTIC floor (math_grade) over a labeled set of realistic
child answers and asserts the two hard gates:

  * accuracy >= 0.90 exact on correct/wrong for rows the deterministic layer is
    meant to decide (numeric / expression / yes-no), and
  * ZERO non-attempts graded as "wrong" (the standing guardrail — a confusion
    plea / counter-question / "i don't know" must never move mastery).

Rows tagged layer="llm" (verbal/conceptual) are EXPECTED to defer (grade -> None);
they are counted, not gated, offline — the billed LLM rubric pass (§5.4 step 2) is
out of scope here (run it with the perception_eval --collect/--score pattern when
wiring the live grader). Run: python -m eval.grader_eval   (exit 0 = gates met).
"""

from __future__ import annotations

import sys

import math_grade

# (expected, student, gold, layer). gold in {correct, wrong, non_attempt, verbal}.
ROWS = [
    # --- correct, worded several ways / STT-mangled ---
    ("13", "13", "correct", "det"),
    ("13", "thirteen", "correct", "det"),
    ("13", "it is 13", "correct", "det"),
    ("13", "i think the answer is 13", "correct", "det"),
    ("13", "13.0", "correct", "det"),
    ("1/3", "1/3", "correct", "det"),
    ("1/3", "one by three", "correct", "det"),
    ("1/3", "one over three", "correct", "det"),
    ("x = 2 and x = 3", "x = 2 and x = 3", "correct", "det"),
    ("x = 2 and x = 3", "x = 3 and x = 2", "correct", "det"),
    ("x = 2 and x = 3", "2 and 3", "correct", "det"),
    ("sqrt 2", "root two", "correct", "det"),
    ("sqrt 2", "square root of 2", "correct", "det"),
    ("25", "twenty five", "correct", "det"),
    ("yes", "yes", "correct", "det"),
    ("no", "nope", "correct", "det"),
    ("0", "zero", "correct", "det"),
    ("-4", "minus four", "correct", "det"),
    # --- wrong (contradicts expected) ---
    ("13", "14", "wrong", "det"),
    ("13", "the answer is 7", "wrong", "det"),
    ("1/3", "1/2", "wrong", "det"),
    ("x = 2 and x = 3", "x = 5 and x = 6", "wrong", "det"),
    ("yes", "no", "wrong", "det"),
    ("no", "yes it is", "wrong", "det"),
    ("sqrt 2", "3", "wrong", "det"),
    ("25", "twenty six", "wrong", "det"),
    # --- non-attempts (MUST never be graded wrong) ---
    ("13", "i don't know", "non_attempt", "na"),
    ("13", "i dont know", "non_attempt", "na"),
    ("13", "can you repeat the question?", "non_attempt", "na"),
    ("13", "what does that mean?", "non_attempt", "na"),
    ("13", "this is too hard", "non_attempt", "na"),
    ("13", "i'm confused", "non_attempt", "na"),
    ("13", "can we do something else", "non_attempt", "na"),
    ("x = 2 and x = 3", "i forgot how to do this", "non_attempt", "na"),
    ("sqrt 2", "help me", "non_attempt", "na"),
    # --- verbal/conceptual (deterministic layer SHOULD defer) ---
    ("the parabola opens upward", "it goes up", "verbal", "llm"),
    ("because the discriminant is zero", "the roots are equal", "verbal", "llm"),
    ("it represents the rate of change", "how fast it changes", "verbal", "llm"),
]


def main() -> int:
    det_total = det_correct = 0
    na_graded_wrong = 0
    deferred_verbal = deferred_na = 0
    fails = []

    for expected, student, gold, layer in ROWS:
        verdict = math_grade.grade(expected, student)   # correct|wrong|None
        if gold in ("correct", "wrong"):
            det_total += 1
            if verdict == gold:
                det_correct += 1
            else:
                fails.append(f"  {gold!r} expected but got {verdict!r}: "
                             f"({expected!r} vs {student!r})")
        elif gold == "non_attempt":
            if verdict == "wrong":
                na_graded_wrong += 1
                fails.append(f"  NON-ATTEMPT GRADED WRONG: ({expected!r} vs {student!r})")
            elif verdict is None:
                deferred_na += 1
        elif gold == "verbal":
            if verdict is None:
                deferred_verbal += 1
            else:
                fails.append(f"  verbal row not deferred (got {verdict!r}): "
                             f"({expected!r} vs {student!r})")

    acc = det_correct / det_total if det_total else 0.0
    print(f"deterministic accuracy (correct/wrong rows): {det_correct}/{det_total} = {acc:.3f}")
    print(f"non-attempts graded wrong: {na_graded_wrong}  (HARD GATE: must be 0)")
    print(f"non-attempts safely deferred to None: {deferred_na}")
    print(f"verbal rows deferred to LLM: {deferred_verbal}")
    if fails:
        print("\nfailures:")
        print("\n".join(fails))

    gate_acc = acc >= 0.90
    gate_na = na_graded_wrong == 0
    print(f"\nGATE accuracy >= 0.90: {'PASS' if gate_acc else 'FAIL'}")
    print(f"GATE zero non-attempts wrong: {'PASS' if gate_na else 'FAIL'}")
    ok = gate_acc and gate_na and not fails
    print("ALL GREEN" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
