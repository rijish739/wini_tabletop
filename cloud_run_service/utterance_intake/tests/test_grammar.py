"""Unit and invariant tests for Maths Earley grammar, refusals, and assessment grading (Slice 06)."""

from __future__ import annotations

import unittest
from math_grade import grade
from utterance_intake.grammar import parse_maths, ParseOutcome, get_maths_parser, GRAMMAR_VERSION
from utterance_intake.observation import Span, PASSTHROUGH_PARSE


class MathsGrammarTests(unittest.TestCase):
    """Verifies that the Earley grammar accepts valid Class-10 maths shapes."""

    def test_numbers_and_words(self):
        cases = [
            ("5", "5"),
            ("42", "42"),
            ("3.14", "3.14"),
            ("zero", "0"),
            ("three", "3"),
            ("twelve", "12"),
            ("twenty five", "25"),
            ("hundred", "100"),
            ("two hundred", "200"),
        ]
        for inp, expected in cases:
            with self.subTest(inp=inp):
                p = parse_maths(inp)
                self.assertEqual(p.outcome, ParseOutcome.ACCEPT)
                self.assertEqual(p.interpretation, expected)
                self.assertIsNotNone(p.span)
                self.assertEqual(p.grammar_version, GRAMMAR_VERSION)

    def test_vulgar_fractions(self):
        cases = [
            ("half", "1/2"),
            ("one half", "1/2"),
            ("½", "1/2"),
            ("one third", "1/3"),
            ("⅓", "1/3"),
            ("two thirds", "2/3"),
            ("⅔", "2/3"),
            ("one fourth", "1/4"),
            ("one quarter", "1/4"),
            ("¼", "1/4"),
            ("three fourths", "3/4"),
            ("three quarters", "3/4"),
            ("¾", "3/4"),
        ]
        for inp, expected in cases:
            with self.subTest(inp=inp):
                p = parse_maths(inp)
                self.assertEqual(p.outcome, ParseOutcome.ACCEPT)
                self.assertEqual(p.interpretation, expected)

    def test_fractions_and_division(self):
        cases = [
            ("1/3", "1/3"),
            ("one by three", "1/3"),
            ("one over three", "1/3"),
            ("one upon three", "1/3"),
            ("six divided by two", "6/2"),
        ]
        for inp, expected in cases:
            with self.subTest(inp=inp):
                p = parse_maths(inp)
                self.assertEqual(p.outcome, ParseOutcome.ACCEPT)
                self.assertEqual(p.interpretation, expected)

    def test_exponents(self):
        cases = [
            ("three squared", "3^2"),
            ("3 squared", "3^2"),
            ("3²", "3^2"),
            ("three cubed", "3^3"),
            ("three cube", "3^3"),
            ("3³", "3^3"),
            ("2 to the power 3", "2^3"),
            ("2 to the power of 3", "2^3"),
            ("2 ^ 3", "2^3"),
            ("2 ** 3", "2^3"),
        ]
        for inp, expected in cases:
            with self.subTest(inp=inp):
                p = parse_maths(inp)
                self.assertEqual(p.outcome, ParseOutcome.ACCEPT)
                self.assertEqual(p.interpretation, expected)

    def test_roots(self):
        cases = [
            ("root two", "√2"),
            ("root 2", "√2"),
            ("square root of 2", "√2"),
            ("square root 2", "√2"),
            ("sqrt 2", "√2"),
            ("√2", "√2"),
        ]
        for inp, expected in cases:
            with self.subTest(inp=inp):
                p = parse_maths(inp)
                self.assertEqual(p.outcome, ParseOutcome.ACCEPT)
                self.assertEqual(p.interpretation, expected)

    def test_signs_and_negation(self):
        cases = [
            ("-4", "-4"),
            ("−4", "-4"),
            ("minus four", "-4"),
            ("negative four", "-4"),
            ("+/- 5", "±5"),
            ("±5", "±5"),
            ("plus or minus 5", "±5"),
        ]
        for inp, expected in cases:
            with self.subTest(inp=inp):
                p = parse_maths(inp)
                self.assertEqual(p.outcome, ParseOutcome.ACCEPT)
                self.assertEqual(p.interpretation, expected)

    def test_equations_and_conjunctions(self):
        cases = [
            ("x = 2", "x = 2"),
            ("x equals 2", "x = 2"),
            ("x is equal to 2", "x = 2"),
            ("x is 2", "x = 2"),
            ("2y = 10", "2y = 10"),
            ("x = 2 and x = 3", "x = 2 and x = 3"),
            ("x = 2 or x = -2", "x = 2 or x = -2"),
            ("2, 3", "2, 3"),
        ]
        for inp, expected in cases:
            with self.subTest(inp=inp):
                p = parse_maths(inp)
                self.assertEqual(p.outcome, ParseOutcome.ACCEPT)
                self.assertEqual(p.interpretation, expected)


class AmbiguityAndRefusalTests(unittest.TestCase):
    """Verifies that ambiguous and out-of-grammar maths trigger explicit refusals."""

    def test_ambiguous_spoken_fractions_refused_with_competing_trees(self):
        p = parse_maths("one over x plus two")
        self.assertEqual(p.outcome, ParseOutcome.REFUSE_AMBIGUOUS)
        self.assertIsNone(p.interpretation)
        self.assertIsNotNone(p.derivation)
        self.assertGreater(len(p.competing), 1)
        self.assertIn("1/x + 2", p.competing)
        self.assertIn("1/(x + 2)", p.competing)

    def test_out_of_grammar_claimed_maths_refused(self):
        # Claimed maths (contains math keyword / symbols) but not in grammar
        cases = [
            "route two",            # homophone / non-grammar word
            "solve x^2 = 4",        # solve verb prefix
            "what is 63 / 9",       # question prefix
            "the answer is seven",  # prose wrapper around number
        ]
        for inp in cases:
            with self.subTest(inp=inp):
                p = parse_maths(inp)
                self.assertEqual(p.outcome, ParseOutcome.REFUSE_OUT_OF_GRAMMAR)
                self.assertIsNone(p.interpretation)
                self.assertIsNotNone(p.span)

    def test_non_maths_prose_passthrough_with_none_span(self):
        cases = [
            "I do not know",
            "can you explain this please",
            "what chapter are we on",
            "thank you",
        ]
        for inp in cases:
            with self.subTest(inp=inp):
                p = parse_maths(inp)
                self.assertEqual(p.outcome, ParseOutcome.PASSTHROUGH)
                self.assertIsNone(p.span)
                self.assertIsNone(p.interpretation)


class FourMeasuredFalseNegativesTests(unittest.TestCase):
    """Asserts that the 4 measured confident false negatives become correct parses or refusals — never silent wrongs."""

    def test_false_negative_1_three_squared(self):
        p = parse_maths("three squared")
        self.assertEqual(p.outcome, ParseOutcome.ACCEPT)
        self.assertEqual(p.interpretation, "3^2")
        self.assertEqual(grade("9", p.interpretation), "correct")

    def test_false_negative_2_three_cube(self):
        p = parse_maths("three cube")
        self.assertEqual(p.outcome, ParseOutcome.ACCEPT)
        self.assertEqual(p.interpretation, "3^3")
        self.assertEqual(grade("27", p.interpretation), "correct")

    def test_false_negative_3_route_two(self):
        p = parse_maths("route two")
        # Explicit refusal -> never graded -> never a silent false negative
        self.assertIn(p.outcome, (ParseOutcome.REFUSE_OUT_OF_GRAMMAR, ParseOutcome.ACCEPT))
        self.assertNotEqual(p.outcome, ParseOutcome.PASSTHROUGH)

    def test_false_negative_4_unicode_minus_four(self):
        p = parse_maths("−4")
        self.assertEqual(p.outcome, ParseOutcome.ACCEPT)
        self.assertEqual(p.interpretation, "-4")
        self.assertEqual(grade("-4", p.interpretation), "correct")

    def test_false_negative_5_vulgar_fraction_half(self):
        p = parse_maths("½")
        self.assertEqual(p.outcome, ParseOutcome.ACCEPT)
        self.assertEqual(p.interpretation, "1/2")
        self.assertEqual(grade("0.5", p.interpretation), "correct")


if __name__ == "__main__":
    unittest.main()
