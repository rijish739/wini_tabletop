"""Deterministic math-answer grading — the floor under judge_answer (Part 12 §5.4).

Mirrors the safety-gate philosophy: never lean on the LLM for the floor. When five
graded items decide a mastery gate, a weak single-shot LLM grader is not enough. This
module grades the *numeric / expression* shapes a Class-10 answer usually takes —
numbers ("13", "thirteen", "13.0"), fractions ("1/3", "one by three"), root forms
("root two" ≈ "√2"), and unordered pairs ("x = 2 and x = 3") — deterministically.

`grade(expected, student)` returns:
  "correct" | "wrong"  — a confident deterministic verdict, OR
  None                 — cannot decide from surface form; caller defers to the LLM
                         rubric grader (verbal/conceptual answers, §5.4 step 2).

Non-attempts (acks, confusion pleas, counter-questions) are handled UPSTREAM by the
tutor_loop 1a machinery and never reach here — the standing guardrail.
"""

from __future__ import annotations

import re
from fractions import Fraction

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100,
}
_TOL = 1e-6


def _word_number(tok: str):
    """A single number word -> int, else None (multi-word like 'twenty five' is
    handled by the phrase pass in normalize)."""
    return _ONES.get(tok)


def normalize(text: str) -> str:
    """Lowercase + fold STT/spoken math into symbol form.

    'root two' -> 'sqrt 2', 'one by three'/'one over three' -> '1/3',
    'x equals 2' -> 'x = 2', number words -> digits (incl. 'twenty five' -> 25).
    """
    s = (text or "").lower().strip()
    s = s.replace("√", " sqrt ").replace("×", "*").replace("÷", "/")
    s = s.replace("plus or minus", "+/-").replace("±", "+/-")
    s = re.sub(r"\bsquare\s+root\s+of\s+", "sqrt ", s)   # before the bare 'root'
    s = re.sub(r"\broot\s+", "sqrt ", s)
    s = re.sub(r"\b(negative|minus)\s+", "-", s)         # 'minus four' -> -4
    s = re.sub(r"\b(\w+)\s+(?:by|over|upon)\s+(\w+)\b", r"\1/\2", s)   # fractions
    s = re.sub(r"\bequals?\b|\bis equal to\b", "=", s)
    # two-word tens ("twenty five" -> 25)
    def _tens(m):
        a, b = _ONES.get(m.group(1)), _ONES.get(m.group(2))
        if a and b and a % 10 == 0 and a >= 20 and b < 10:
            return str(a + b)
        return m.group(0)
    s = re.sub(r"\b(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)\s+"
              r"(one|two|three|four|five|six|seven|eight|nine)\b", _tens, s)
    # remaining single number words -> digits
    s = re.sub(r"\b[a-z]+\b", lambda m: str(_word_number(m.group(0)))
               if _word_number(m.group(0)) is not None else m.group(0), s)
    return s


def _to_value(tok: str):
    """Parse one token into a comparable float, or None."""
    tok = tok.strip().strip("()")
    if not tok:
        return None
    m = re.fullmatch(r"sqrt\s*([0-9]+(?:\.[0-9]+)?)", tok)
    if m:
        return float(m.group(1)) ** 0.5
    if re.fullmatch(r"-?[0-9]+/[0-9]+", tok):
        try:
            return float(Fraction(tok))
        except (ZeroDivisionError, ValueError):
            return None
    if re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", tok):
        return float(tok)
    return None


def _values(text: str) -> set:
    """Extract the set of numeric values mentioned (drops variable names / prose)."""
    s = normalize(text)
    s = re.sub(r"\b[a-z]\s*=\s*", " ", s)          # strip 'x =' leaving the value
    vals = set()
    for m in re.finditer(r"sqrt\s*[0-9]+(?:\.[0-9]+)?|-?[0-9]+/[0-9]+|-?[0-9]+(?:\.[0-9]+)?", s):
        v = _to_value(m.group(0))
        if v is not None:
            vals.add(round(v, 6))
    return vals


_YES = re.compile(r"\b(yes|yeah|yep|true|correct|right)\b", re.IGNORECASE)
_NO = re.compile(r"\b(no|nope|false|incorrect|wrong)\b", re.IGNORECASE)


def _yesno(text: str):
    y, n = bool(_YES.search(text or "")), bool(_NO.search(text or ""))
    if y and not n:
        return True
    if n and not y:
        return False
    return None


def grade(expected: str, student: str):
    """Deterministic verdict or None (defer to LLM). See module docstring."""
    if not (expected or "").strip() or not (student or "").strip():
        return None

    # yes/no questions
    ey, sy = _yesno(expected), _yesno(student)
    if ey is not None and sy is not None and not _values(expected):
        return "correct" if ey == sy else "wrong"

    ev, sv = _values(expected), _values(student)
    if not ev:
        return None            # expected isn't numeric -> LLM rubric (verbal answer)
    if not sv:
        return None            # student gave no number we can parse -> defer

    def close(a, b):
        return abs(a - b) <= _TOL or (b != 0 and abs(a - b) / abs(b) <= 1e-4)

    def covered(target, pool):
        return any(close(target, p) for p in pool)

    # every expected value must appear in the student's answer (order-free pairs)
    all_hit = all(covered(e, sv) for e in ev)
    any_hit = any(covered(e, sv) for e in ev)
    # no spurious extra value the expected set doesn't contain
    no_extra = all(covered(s, ev) for s in sv)

    if all_hit and no_extra:
        return "correct"
    if not any_hit:
        return "wrong"
    return None                # partial overlap -> let the LLM adjudicate (partial)
