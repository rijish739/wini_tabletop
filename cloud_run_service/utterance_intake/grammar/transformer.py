"""Transformer converting Lark AST into canonical mathematical string representation."""

from __future__ import annotations

from typing import Any, List
from lark import Transformer, Tree, Token


WORD_TO_NUM = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}


class MathsInterpretationTransformer(Transformer):
    """Transforms a parsed maths AST into a clean canonical string for evaluation."""

    def num(self, items: List[Any]) -> str:
        return str(items[0])

    def var(self, items: List[Any]) -> str:
        return str(items[0])

    def const(self, items: List[Any]) -> str:
        val = str(items[0])
        return "pi" if val in ("pi", "π") else val

    def unit(self, items: List[Any]) -> str:
        tok = str(items[0]).lower()
        return str(WORD_TO_NUM.get(tok, tok))

    def teen(self, items: List[Any]) -> str:
        tok = str(items[0]).lower()
        return str(WORD_TO_NUM.get(tok, tok))

    def tens(self, items: List[Any]) -> str:
        tok = str(items[0]).lower()
        return str(WORD_TO_NUM.get(tok, tok))

    def compound_tens(self, items: List[Any]) -> str:
        t1 = str(items[0]).lower()
        t2 = str(items[1]).lower()
        v1 = WORD_TO_NUM.get(t1, 0)
        v2 = WORD_TO_NUM.get(t2, 0)
        return str(v1 + v2)

    def hundred_unit(self, items: List[Any]) -> str:
        tok = str(items[0]).lower()
        v = WORD_TO_NUM.get(tok, 1)
        return str(v * 100)

    def hundred_plain(self, items: List[Any]) -> str:
        return "100"

    def half(self, items: List[Any]) -> str:
        return "1/2"

    def third(self, items: List[Any]) -> str:
        return "1/3"

    def two_thirds(self, items: List[Any]) -> str:
        return "2/3"

    def fourth(self, items: List[Any]) -> str:
        return "1/4"

    def three_fourths(self, items: List[Any]) -> str:
        return "3/4"

    def num_word(self, items: List[Any]) -> str:
        return str(items[0])

    def frac_word(self, items: List[Any]) -> str:
        return str(items[0])

    def neg(self, items: List[Any]) -> str:
        val = str(items[0])
        return f"-{val}"

    def sqrt(self, items: List[Any]) -> str:
        val = str(items[0])
        return f"√{val}"

    def squared(self, items: List[Any]) -> str:
        base = str(items[0])
        return f"{base}^2"

    def cubed(self, items: List[Any]) -> str:
        base = str(items[0])
        return f"{base}^3"

    def pow(self, items: List[Any]) -> str:
        base = str(items[0])
        exp = str(items[1])
        return f"{base}^{exp}"

    def implicit_mul(self, items: List[Any]) -> str:
        coeff = str(items[0])
        var_part = str(items[1])
        return f"{coeff}{var_part}"

    def mul(self, items: List[Any]) -> str:
        a = str(items[0])
        b = str(items[1])
        return f"{a} * {b}"

    def div(self, items: List[Any]) -> str:
        a = str(items[0])
        b = str(items[1])
        if " " in b or "+" in b or "-" in b:
            return f"{a}/({b})"
        return f"{a}/{b}"

    def add(self, items: List[Any]) -> str:
        a = str(items[0])
        b = str(items[1])
        return f"{a} + {b}"

    def sub(self, items: List[Any]) -> str:
        a = str(items[0])
        b = str(items[1])
        return f"{a} - {b}"

    def plus_minus_unary(self, items: List[Any]) -> str:
        val = str(items[0])
        return f"±{val}"

    def eq(self, items: List[Any]) -> str:
        v = str(items[0])
        val = str(items[1])
        return f"{v} = {val}"

    def eq_expr(self, items: List[Any]) -> str:
        lhs = str(items[0])
        rhs = str(items[1])
        return f"{lhs} = {rhs}"

    def conjunction(self, items: List[Any]) -> str:
        left = str(items[0])
        right = str(items[1])
        return f"{left} and {right}"

    def disjunction(self, items: List[Any]) -> str:
        left = str(items[0])
        right = str(items[1])
        return f"{left} or {right}"

    def pair(self, items: List[Any]) -> str:
        left = str(items[0])
        right = str(items[1])
        return f"{left}, {right}"
