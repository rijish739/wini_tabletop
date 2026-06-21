"""Make local tutor text safe to speak.

The local Qwen answer is written for a reader and can contain LaTeX/markdown
(e.g. ``\\(D > 0\\)``, ``2x^2``, ``**bold**``). Spoken verbatim by any TTS this
comes out as "backslash open paren D greater than zero". This module rewrites
math/markup into words before the text ever reaches the voice layer.

It is deliberately small and deterministic: no model, no network. It only
touches surface form; it must never change the maths.
"""

from __future__ import annotations

import re

# Order matters: strip delimiters first, then operators, then symbols.
_SYMBOL_WORDS = [
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

_GREEK = {
    r"\\alpha": "alpha", r"\\beta": "beta", r"\\theta": "theta",
    r"\\pi": "pi", r"\\Delta": "delta", r"\\delta": "delta",
}


def _superscripts(text: str) -> str:
    # x^2 -> x squared, x^3 -> x cubed, x^n -> x to the power n
    text = re.sub(r"\^2\b", " squared", text)
    text = re.sub(r"\^3\b", " cubed", text)
    text = re.sub(r"\^\{?([0-9a-zA-Z]+)\}?", r" to the power \1", text)
    return text


def sanitize_for_speech(text: str) -> str:
    if not text:
        return ""
    s = text

    # 0. strip a stray micro-check label Qwen sometimes prefixes to its question
    #    ("yes_no: Is D positive?"). Do this BEFORE markdown strip removes the
    #    underscore and hides the label.
    s = re.sub(r"(^|[.!?]\s+)(yes[_ ]?no|own[_ ]?words|next[_ ]?step|try[_ ]?step|answer|question|check)\s*:\s*",
               r"\1", s, flags=re.IGNORECASE)

    # 1. drop LaTeX inline/display delimiters but keep the inside content.
    s = re.sub(r"\\\((.+?)\\\)", r" \1 ", s, flags=re.DOTALL)
    s = re.sub(r"\\\[(.+?)\\\]", r" \1 ", s, flags=re.DOTALL)
    s = s.replace("$", " ")

    # 1b. multiplication asterisk between terms -> "times" (must run BEFORE the
    #     markdown strip below removes '*'); e.g. "4*2*2" -> "4 times 2 times 2".
    s = re.sub(r"(?<=[0-9A-Za-z\)])\s*\*\s*(?=[0-9A-Za-z\(])", " times ", s)

    # 2. markdown emphasis / code / headings.
    s = re.sub(r"[*_`#]+", "", s)

    # 3. greek + superscripts + symbol words.
    for pat, word in _GREEK.items():
        s = re.sub(pat, word, s)
    s = _superscripts(s)
    for pat, word in _SYMBOL_WORDS:
        s = re.sub(pat, word, s)

    # 4. leftover backslashes (stray LaTeX commands) -> drop the command name.
    s = re.sub(r"\\[a-zA-Z]+", " ", s)
    s = s.replace("\\", " ")

    # 5. collapse whitespace and fix spacing around punctuation.
    s = re.sub(r"\s+([,.!?;:])", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


if __name__ == "__main__":
    samples = [
        r"If \(D > 0\), there are two roots. Solve \(2x^2 - 5x + 3 = 0\).",
        r"The discriminant is **b^2 - 4ac**. Is it \(\geq 0\)?",
    ]
    for x in samples:
        print(repr(x), "->", repr(sanitize_for_speech(x)))
