"""Unit tests for the standalone cognitive input processor module."""

import pytest
from cognitive_input_processor.input_processor import (
    InputProcessor,
    InputProcessorConfig,
    IngestedInput,
    build_default_input_processor,
)


@pytest.fixture
def processor() -> InputProcessor:
    return build_default_input_processor()


def test_normalization_whitespace_and_punctuation(processor: InputProcessor) -> None:
    raw = "  Hello ,  can   you explain   ( x + 2 ) ?  "
    norm = processor.normalize_input(raw)
    assert norm == "Hello, can you explain (x + 2)?"


def test_normalization_preserves_math_equations_and_unicode(processor: InputProcessor) -> None:
    raw = "solve  3x² + 5x - 2 = 0"
    norm = processor.normalize_input(raw)
    # NFKC normalizes superscript 2
    assert "3x" in norm and "= 0" in norm
    assert norm.startswith("solve")


def test_normalization_preserves_negation(processor: InputProcessor) -> None:
    # Deterministic normalization must preserve polarity words perfectly
    pos = "I do like math"
    neg = "I do not like math"
    assert processor.normalize_input(pos) == "I do like math"
    assert processor.normalize_input(neg) == "I do not like math"


def test_detect_student_problem_equations(processor: InputProcessor) -> None:
    # Explicit equations brought by student
    res = processor.detect_student_problem("solve x^2 - 5x + 6 = 0")
    assert res["is_problem"] is True
    assert res["cue"] == "equation"
    assert res["directive"] is True

    # Equation without solve verb
    res_no_verb = processor.detect_student_problem("2y = 10")
    assert res_no_verb["is_problem"] is True
    assert res_no_verb["cue"] == "equation"
    assert res_no_verb["directive"] is False


def test_detect_student_problem_expressions(processor: InputProcessor) -> None:
    # Arithmetic expressions
    res = processor.detect_student_problem("what is 63 / x")
    assert res["is_problem"] is True
    assert res["cue"] == "expression"
    assert res["directive"] is True


def test_detect_student_problem_solve_verb_with_numerals_vs_conceptual(processor: InputProcessor) -> None:
    # Solve verb + numerals -> problem instance
    res1 = processor.detect_student_problem("A train travels 63 km in 2 hours. Find the speed.")
    assert res1["is_problem"] is True
    assert res1["cue"] == "solve_verb+numerals"
    assert res1["directive"] is True

    # Conceptual request without numerals -> NOT a problem instance (should route to EXPLAIN)
    res2 = processor.detect_student_problem("find the area of a circle")
    assert res2["is_problem"] is False


def test_is_anaphoric_followup(processor: InputProcessor) -> None:
    assert processor.is_anaphoric_followup("solve this with graph") is True
    assert processor.is_anaphoric_followup("why is that a parabola?") is True
    assert processor.is_anaphoric_followup("what about it") is True

    # Long sentence is not treated as anaphoric follow-up
    long_text = "this is a very long question where the student actually explains a brand new topic completely and names several other things in detail"
    assert processor.is_anaphoric_followup(long_text) is False

    # Empty
    assert processor.is_anaphoric_followup("") is False


def test_is_same_problem_followup(processor: InputProcessor) -> None:
    history = [
        {"role": "student", "text": "how to solve this?"},
        {"role": "wini", "text": "For 3825, we factor 3 x 3 x 5 x 5 x 17 = 3825."},
    ]
    # Follow-up asking for another way on the same problem
    assert processor.is_same_problem_followup("explain this again", history, is_followup=True) is True

    # Asking for a DIFFERENT example should NOT reuse the same problem numbers
    assert processor.is_same_problem_followup("give me another example", history, is_followup=True) is False

    # Student bringing fresh numbers (>= 2 digits) should NOT reuse old numbers
    assert processor.is_same_problem_followup("what about 4500 and 12", history, is_followup=True) is False


def test_ingest_pipeline(processor: InputProcessor) -> None:
    raw = "   can we calculate 2 * 4   now ? "
    ingested = processor.ingest(raw)
    assert isinstance(ingested, IngestedInput)
    assert ingested.raw_text == raw
    assert ingested.normalized_text == "can we calculate 2 * 4 now?"
    assert ingested.problem_cue["is_problem"] is True
    assert ingested.surface_cues["is_question"] is True
