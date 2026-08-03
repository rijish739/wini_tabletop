"""One home for "make maths readable" — shared by every surface that renders it.

Before this module there were THREE independent implementations of the same job,
each with different coverage, and they drifted exactly as you would expect
(audit B-5):

* ``voice/sanitize.py:sanitize_for_speech`` — the SPOKEN path. Stripped
  ``\\command`` names but not braces, so ``\\frac{63}{x}`` was spoken as
  "63 x": not a mispronunciation but a **different quantity** (B-1).
* ``tutor_loop._plainify_math`` — generated quiz questions, which are both
  spoken and printed on the card. Stripped braces; did not fold ``\\frac``.
* ``wini_client/display_sinks._delatex`` — the panel. Handled ``\\frac``;
  no spoken-word folding (correct for it — a card should read ``x = 5``, not
  "x equals 5").

The three outputs SHOULD differ: a TTS needs "63 over x" where a display card
wants "63/x". What must not differ is the parsing underneath. So the primitives
(delimiter stripping, fraction expansion, macro table, superscripts, brace
cleanup) live here once, and the three surface renderers are thin compositions
of them with one test suite covering all of them (``python mathtext.py``).

Deliberately small and deterministic: no model, no network. It only touches
surface form; it must never change the maths.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------

#: inline/display math delimiters — the content inside is kept
_DELIM_INLINE = re.compile(r"\\\((.+?)\\\)", re.DOTALL)
_DELIM_DISPLAY = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)

#: \frac / \dfrac / \tfrac with brace-delimited, brace-free arguments. Nesting is
#: handled by re-running the substitution (innermost binds first).
_FRAC = re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")

#: \sqrt{...} with a brace-delimited argument
_SQRT_ARG = re.compile(r"\\sqrt\s*\{([^{}]*)\}")


def strip_delimiters(s: str) -> str:
    """Drop ``\\(..\\)``, ``\\[..\\]`` and ``$`` but keep what was inside them."""
    s = _DELIM_INLINE.sub(r" \1 ", s)
    s = _DELIM_DISPLAY.sub(r" \1 ", s)
    return s.replace("$", " ")


def expand_fracs(s: str, joiner: str) -> str:
    """``\\frac{a}{b}`` -> ``a<joiner>b``. `joiner` is " over " for speech, "/"
    for a display card.

    This MUST run before any pass that drops bare ``\\command`` names: dropping
    "\\frac" and leaving the braces is what turned "63 over x" into "{63}{x}".
    """
    for _ in range(4):                      # nested fractions; bound stops runaway
        s, n = _FRAC.subn(r"\1" + joiner + r"\2", s)
        if not n:
            break
    return s


def strip_braces(s: str) -> str:
    """Remove leftover grouping braces. They carry no sound and no meaning once
    the command that owned them is gone — and silently gluing two numbers
    together is the worst possible failure on a maths tutor."""
    return s.replace("{", " ").replace("}", " ")


def tidy(s: str) -> str:
    """Collapse whitespace and close up space before punctuation."""
    # `(?!=)` keeps the space in "a != 0": '!' is punctuation everywhere else,
    # but "!=" is an OPERATOR and gluing it to the term ahead reads as "a!= 0".
    s = re.sub(r"\s+([,.!?;:])(?!=)", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


# --------------------------------------------------------------------------
# macro tables
# --------------------------------------------------------------------------

#: spoken forms. Order matters: longer macros first, and delimiters before
#: operators before bare symbols.
SPOKEN_SYMBOLS = [
    (r"\\geq|>=|≥", " greater than or equal to "),
    (r"\\leq|<=|≤", " less than or equal to "),
    (r"\\neq|!=|≠", " not equal to "),
    (r">", " greater than "),
    (r"<", " less than "),
    (r"\\times|×", " times "),
    (r"\\div|÷", " divided by "),
    (r"\\pm|±", " plus or minus "),
    (r"\\sqrt", " square root of "),
    (r"√", " square root of "),
    (r"\\cdot|·", " times "),
    (r"=", " equals "),
]

GREEK = {
    r"\\alpha": "alpha", r"\\beta": "beta", r"\\theta": "theta",
    r"\\pi": "pi", r"\\Delta": "delta", r"\\delta": "delta",
}

#: panel forms — symbolic, not verbal. A card should show "x = 5", not
#: "x equals 5". Longer macros FIRST: a sequential replace would turn \neq
#: into "!=q".
PANEL_MACROS = {
    r"\pi": "pi", r"\times": "x", r"\cdot": ".", r"\div": "/", r"\theta": "theta",
    r"\sqrt": "sqrt", r"\degree": "deg", r"\leq": "<=", r"\geq": ">=",
    r"\neq": "!=",
    r"\le": "<=", r"\ge": ">=", r"\ne": "!=",
    r"\approx": "~", r"\left": "", r"\right": "", r"\,": " ", r"\;": " ",
}

#: quiz-question forms — the text is BOTH spoken and printed, so operators stay
#: symbolic while powers fold into words (a TTS reads "x^2" as "x caret two").
#: longer macros FIRST (same trap as PANEL_MACROS): with "\ge" ahead of "\geq",
#: a sequential replace turns "\geq 0" into ">= q 0". The pre-refactor
#: _plainify_math carried exactly that bug — dicts keep insertion order, so the
#: ordering here IS the fix.
QUESTION_MACROS = {
    "\\times": " times ", "\\div": " divided by ", "\\cdot": " times ",
    "\\geq": " >= ", "\\leq": " <= ", "\\neq": " not equal to ",
    "\\ge": " >= ", "\\le": " <= ",
    "\\sqrt": " square root of ", "\\pi": " pi ", "\\%": " percent ",
}


def fold_superscripts(s: str, words_only: bool = False) -> str:
    """``x^2`` -> "x squared", ``x^3`` -> "x cubed", ``x^n`` -> "x to the power n"."""
    s = re.sub(r"\^2\b", " squared", s)
    s = re.sub(r"\^3\b", " cubed", s)
    pat = r"\^\{?(\d+)\}?" if words_only else r"\^\{?([0-9a-zA-Z]+)\}?"
    return re.sub(pat, r" to the power \1", s)


# --------------------------------------------------------------------------
# surface renderers
# --------------------------------------------------------------------------

#: a stray micro-check label the generator sometimes prefixes to its question
_LABEL = re.compile(
    r"(^|[.!?]\s+)(yes[_ ]?no|own[_ ]?words|next[_ ]?step|try[_ ]?step|answer|question|check)\s*:\s*",
    re.IGNORECASE)


def to_spoken(text: str) -> str:
    """Full verbal rendering for the TTS. Every symbol becomes a word."""
    if not text:
        return ""
    s = text
    # strip the label BEFORE markdown removal hides the underscore
    s = _LABEL.sub(r"\1", s)
    s = strip_delimiters(s)
    # multiplication asterisk between terms, before markdown eats '*'
    s = re.sub(r"(?<=[0-9A-Za-z\)])\s*\*\s*(?=[0-9A-Za-z\(])", " times ", s)
    s = expand_fracs(s, " over ")
    s = _SQRT_ARG.sub(r" square root of \1 ", s)
    s = re.sub(r"[*_`#]+", "", s)                       # markdown emphasis/code
    for pat, word in GREEK.items():
        s = re.sub(pat, word, s)
    s = fold_superscripts(s)
    for pat, word in SPOKEN_SYMBOLS:
        s = re.sub(pat, word, s)
    s = re.sub(r"\\[a-zA-Z]+", " ", s)                  # leftover \command
    s = s.replace("\\", " ")
    return tidy(strip_braces(s))


def to_panel(text: str) -> str:
    """Symbolic plain text for the display card: keeps ``=``, ``^``, ``/``."""
    if not text:
        return ""
    s = text
    for d in ("$", r"\(", r"\)", r"\[", r"\]"):
        s = s.replace(d, "")
    s = expand_fracs(s, "/")
    for k, v in PANEL_MACROS.items():
        s = s.replace(k, v)
    s = re.sub(r"([\^_])\{([^{}]*)\}", r"\1\2", s)      # x^{2} -> x^2
    s = strip_braces(s)
    s = re.sub(r"\\([a-zA-Z]+)", r"\1", s)              # unknown macro: keep the word
    return s.replace("\\", "")


#: Glyphs the LVGL panel fonts actually carry (wini_ui/fonts/*.c were built with
#: `--range 0x20-0x7E --symbols ²³×÷−√≤≥°±πΔθ→←↑↓●○◐✓…—–‘’“”·⅓½¼`). Anything
#: outside this set renders as a blank box, so `to_panel_unicode` only ever emits
#: symbols listed here — that is why ≠ and ≈ stay as "!=" and "~".
PANEL_GLYPHS = set("²³×÷−√≤≥°±πΔθ→←↑↓●○◐✓…—–‘’“”·⅓½¼")

#: caret/macro forms -> the real glyph. Longer keys first (same trap as
#: PANEL_MACROS: "\le" ahead of "\leq" turns "\geq 0" into ">= q 0").
_UNICODE_MACROS = [
    (r"\\[dt]?frac", "/"), (r"\\times", "×"), (r"\\cdot", "·"),
    (r"\\div", "÷"), (r"\\sqrt", "√"), (r"\\pm", "±"),
    (r"\\degree|\^\\?circ", "°"), (r"\\pi", "π"), (r"\\theta", "θ"),
    (r"\\Delta|\\delta", "Δ"), (r"\\geq|>=", "≥"), (r"\\leq|<=", "≤"),
    (r"\\neq", "!="), (r"\\ge\b", "≥"), (r"\\le\b", "≤"), (r"\\ne\b", "!="),
    (r"\\approx", "~"), (r"\\left|\\right", ""), (r"\\,|\\;", " "),
]

#: "x squared" / "(-2) cubed" -> "x²" / "(-2)³". The generator writes powers as
#: WORDS (its prompt is spoken-first), which is right for the TTS and clumsy on a
#: card. Only a single trailing term folds, so prose like "the area is squared"
#: is left alone.
_SQUARED_WORD = re.compile(r"(?<=[0-9A-Za-z\)\]])\s+squared\b")
_CUBED_WORD = re.compile(r"(?<=[0-9A-Za-z\)\]])\s+cubed\b")


def to_panel_unicode(text: str) -> str:
    """Panel text rendered with REAL maths glyphs: ``x^2`` -> ``x²``,
    ``\\sqrt{a}`` -> ``√a``, ``<=`` -> ``≤``, ``a * b`` -> ``a × b``.

    `to_panel` predates the panel fonts carrying maths glyphs, so it emits the
    ASCII stand-ins (``^2``, ``sqrt``, ``<=``) a child then has to decode while
    studying. This renderer is the display-only successor; `to_panel` stays for
    ASCII-only surfaces (logs, the console sink). It changes surface form ONLY —
    never the maths.
    """
    if not text:
        return ""
    s = text
    for d in ("$", r"\(", r"\)", r"\[", r"\]"):
        s = s.replace(d, "")
    s = expand_fracs(s, "/")
    s = _SQRT_ARG.sub(r"√\1", s)
    for pat, glyph in _UNICODE_MACROS:
        s = re.sub(pat, glyph, s)
    # multiplication asterisk between terms, BEFORE markdown emphasis eats '*'
    s = re.sub(r"(?<=[0-9A-Za-z\)])\s*\*\s*(?=[0-9A-Za-z\(])", " × ", s)
    s = re.sub(r"[*`#]+", "", s)                        # markdown emphasis/code
    s = re.sub(r"([\^_])\{([^{}]*)\}", r"\1\2", s)      # x^{2} -> x^2
    s = strip_braces(s)
    s = re.sub(r"\^2(?![0-9a-zA-Z])", "²", s)
    s = re.sub(r"\^3(?![0-9a-zA-Z])", "³", s)
    s = _SQUARED_WORD.sub("²", s)
    s = _CUBED_WORD.sub("³", s)
    s = re.sub(r"\\([a-zA-Z]+)", r"\1", s)              # unknown macro: keep the word
    return tidy(s.replace("\\", ""))


def to_question(text: str) -> str:
    """A generated quiz question: spoken by the TTS AND printed on the card, so
    operators stay symbolic while powers fold into words."""
    if not text:
        return ""
    s = strip_delimiters(text)
    s = expand_fracs(s, "/")
    for k, v in QUESTION_MACROS.items():
        s = s.replace(k, v)
    s = fold_superscripts(s, words_only=True)
    s = strip_braces(s)
    s = re.sub(r"\\[a-zA-Z]+", " ", s)                  # any leftover \command
    return tidy(s)


if __name__ == "__main__":
    # One suite for all three surfaces. The \frac cases are the B-1 regression:
    # before the fix the spoken column read "{63}{x}".
    samples = [
        r"If \(D > 0\), there are two roots. Solve \(2x^2 - 5x + 3 = 0\).",
        r"The discriminant is **b^2 - 4ac**. Is it \(\geq 0\)?",
        r"Time is $\frac{63}{x}$ hours.",
        r"x = $\frac{378}{9}$ = 42",
        r"Area is $\sqrt{\frac{a}{b}}$ units.",
        r"The area is \(\pi r^2\) and the ratio is \frac{a}{b}.",
    ]
    for x in samples:
        print("IN      :", repr(x))
        print("  spoken:", repr(to_spoken(x)))
        print("  panel :", repr(to_panel(x)))
        print("  glyph :", repr(to_panel_unicode(x)))
        print("  quiz  :", repr(to_question(x)))
