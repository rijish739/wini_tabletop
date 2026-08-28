"""Maths Earley grammar parser and refusal classifier."""

from __future__ import annotations

import os
import re
import time
from typing import Optional, Set, Tuple

from lark import Lark, CollapseAmbiguities, ParseError, UnexpectedInput, LarkError

from ..observation import MathParse, ParseOutcome, Span, PASSTHROUGH_PARSE
from .transformer import MathsInterpretationTransformer


GRAMMAR_VERSION = "spoken-maths-v1"
WALL_CLOCK_TIMEOUT_SECONDS = 0.050  # 50ms hard wall-clock cap


MATH_KEYWORDS: Set[str] = {
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
    "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred", "thousand",
    "half", "third", "quarter", "fourth",
    "plus", "minus", "negative", "times", "multiplied", "divided", "over", "upon",
    "squared", "cubed", "cube", "power", "root", "sqrt",
    "equals", "equal",
}

MATH_SYMBOLS = set("0123456789+-−*^/=%√±²³½⅓⅔¼¾(),")


def _has_claimed_maths_span(text: str) -> bool:
    """Returns True if the utterance contains positive evidence of a mathematical answer."""
    cleaned = text.strip().lower()
    if not cleaned:
        return False

    if any(c in MATH_SYMBOLS for c in cleaned):
        return True

    words = re.findall(r"[a-z]+", cleaned)
    math_word_count = sum(1 for w in words if w in MATH_KEYWORDS)
    return math_word_count > 0


class MathsParser:
    """Earley parser wrapper for Class-10 mathematics."""

    def __init__(self, grammar_path: Optional[str] = None):
        if grammar_path is None:
            grammar_path = os.path.join(os.path.dirname(__file__), "maths.lark")
        with open(grammar_path, "r", encoding="utf-8") as f:
            grammar_text = f.read()

        self._lark = Lark(grammar_text, parser="earley", ambiguity="explicit", start="start")
        self._transformer = MathsInterpretationTransformer()
        self._collapser = CollapseAmbiguities()

    def parse(self, text: str) -> MathParse:
        """Parses a normalized text string into a MathParse record."""
        cleaned = text.strip()
        if not cleaned:
            return PASSTHROUGH_PARSE

        if not _has_claimed_maths_span(cleaned):
            return PASSTHROUGH_PARSE

        start_time = time.monotonic()
        try:
            tree = self._lark.parse(cleaned)
            elapsed = time.monotonic() - start_time
            if elapsed > WALL_CLOCK_TIMEOUT_SECONDS:
                return PASSTHROUGH_PARSE

            collapsed_trees = self._collapser.transform(tree)
            if len(collapsed_trees) > 1:
                interpretations = tuple(str(self._transformer.transform(t)) for t in collapsed_trees)
                unique_interps = tuple(dict.fromkeys(interpretations))
                if len(unique_interps) > 1:
                    return MathParse(
                        outcome=ParseOutcome.REFUSE_AMBIGUOUS,
                        span=Span(0, len(cleaned)),
                        interpretation=None,
                        derivation=str(tree),
                        competing=unique_interps,
                        grammar_version=GRAMMAR_VERSION,
                    )

            canonical = str(self._transformer.transform(tree))
            return MathParse(
                outcome=ParseOutcome.ACCEPT,
                span=Span(0, len(cleaned)),
                interpretation=canonical,
                derivation=str(tree),
                grammar_version=GRAMMAR_VERSION,
            )

        except (ParseError, UnexpectedInput, LarkError, Exception):
            elapsed = time.monotonic() - start_time
            if elapsed > WALL_CLOCK_TIMEOUT_SECONDS:
                return PASSTHROUGH_PARSE

            return MathParse(
                outcome=ParseOutcome.REFUSE_OUT_OF_GRAMMAR,
                span=Span(0, len(cleaned)),
                interpretation=None,
                derivation=None,
                grammar_version=GRAMMAR_VERSION,
            )


_PARSER_INSTANCE: Optional[MathsParser] = None


def get_maths_parser() -> MathsParser:
    global _PARSER_INSTANCE
    if _PARSER_INSTANCE is None:
        _PARSER_INSTANCE = MathsParser()
    return _PARSER_INSTANCE


def parse_maths(text: str) -> MathParse:
    """Convenience helper to parse normalized maths text."""
    return get_maths_parser().parse(text)
