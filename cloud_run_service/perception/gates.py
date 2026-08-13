"""Stage A deterministic front-door gates: SAFETY + NONSENSE (Part 11 §4.2).

These run FIRST, before any model call, and short-circuit to a fully scripted
reply. They own their decisions absolutely:

* SAFETY is a high-recall, human-reviewed lexicon. Gemini may *add* a safety
  flag as a secondary recall net but may NEVER downgrade a gate-flagged case
  (§4.2). The child-safety guarantee must never depend on a model being
  available, fast, or correct.
* NONSENSE is kept deliberately CONSERVATIVE: a wrongly-gated real answer ("5",
  "yes", "x=2") is a pedagogy failure, so it fires only on empty / pure-symbol /
  obvious keyboard-mash input and otherwise defers to the model.

`gate()` returns a RouteResult when a gate fires, else None (pass through to the
Gemini route / learning pipeline). It is pure and model-free, so it runs
regardless of PERCEPTION_BACKEND.
"""

from __future__ import annotations

import re
from typing import Optional

from .route import RouteResult

try:
    import debug_logger as _dbg
except ImportError:
    _dbg = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# SAFETY — high recall by design. Child-facing device: over-trigger, never miss.
# Grouped for reviewability; keep phrasing broad (kids paraphrase).
# ---------------------------------------------------------------------------
_SAFETY_PATTERNS = [
    # self-harm / suicidal ideation (cover gerund + oblique phrasings)
    r"\bkill(ing)? myself\b", r"\bkill me\b",
    r"\bend(ing|s)? (my life|it all|things|everything)\b",
    r"\b(want|wanna|going|feel like) to? ?die\b", r"\bi want to die\b",
    r"\bwish i (was|were) dead\b", r"\bwant to be dead\b",
    r"\bdon'?t want to (live|be alive|be here|exist)\b", r"\bno reason to live\b",
    r"\b(want|wanted|feel like) (everything|it all|it|things) to (stop|end)( forever)?\b",
    r"\b(stop|end) (it all |everything )?forever\b", r"\bmake (it|everything) (all )?stop\b",
    r"\bif i (disappeared|was gone|were gone|wasn'?t here|weren'?t here|died|was dead)\b",
    r"\bno[\s-]?(one|body) would (care|miss|notice)\b",
    r"\bhurt(ing)? myself\b", r"\bharm(ing)? myself\b", r"\bcut(ting)? myself\b",
    r"\bself[\s-]?harm\b", r"\bsuicid(e|al)\b", r"\bslit my\b",
    # abuse / someone hurting the child
    r"\b(hit|hits|hitting|beat|beats|beating|hurt|hurts|hurting) me\b",
    r"\bsomeone (hurt|hit|touched|beats?)\b", r"\b(hurts?|hits?|beats?) me at home\b",
    r"\btouch(ed|es|ing)? me\b.{0,40}\b(bad|wrong|private|there|should|not supposed|down)\w*\b",
    r"\btouch(ed|es|ing)? me (where|down there|somewhere|in my|in a)\b",
    r"\b(bad|wrong) touch\b", r"\binappropriate(ly)? touch",
    r"\bafraid (of|to go home)\b", r"\bscared (of|to go home)\b.*\b(dad|mom|father|mother|uncle|home)\b",
    r"\b(my )?(dad|mom|father|mother|uncle|aunt|brother|teacher) (hit|hits|beats?|hurts?) me\b",
    r"\bbeing (abused|bullied|hurt|threatened)\b", r"\bhe hurts me\b", r"\bshe hurts me\b",
    # running away / immediate danger / violence toward others
    r"\brun(ning)? away from home\b", r"\bi'?m in danger\b", r"\bhelp me\b.*\b(scared|hurt|danger)\b",
    r"\bwant to hurt (someone|him|her|them)\b", r"\bkill (him|her|them|everyone)\b",
    r"\bbring a (knife|gun|weapon)\b",
]
_SAFETY_RE = re.compile("|".join(_SAFETY_PATTERNS), re.IGNORECASE)

# ---------------------------------------------------------------------------
# NONSENSE — conservative. Only fires on clearly-empty / non-lexical input.
# ---------------------------------------------------------------------------
_ALNUM_RE = re.compile(r"[a-z0-9]", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z]{2,}", re.IGNORECASE)
# 'y' counts as a vowel here so real words like "myth"/"rhythm"/"gym" are never
# mistaken for a keyboard mash (keyboard mashes almost never contain vowels).
_VOWEL_RE = re.compile(r"[aeiouy]", re.IGNORECASE)
# a single long run of one character ("aaaaaa", "!!!!!", "?????")
_RUN_RE = re.compile(r"^(.)\1{4,}$")


def is_safety(text: str) -> bool:
    """High-recall child-safety trip. Broad on purpose."""
    return bool(_SAFETY_RE.search(text or ""))


def classify_safety(text: str) -> tuple[int, str] | None:
    """Return a redaction-safe tier/category; never retain the matched phrase."""
    value = text or ""
    if not is_safety(value):
        return None
    if re.search(r"\b(?:kill(?:ing)? myself|suicid|slit my|end(?:ing)? my life|"
                 r"want to die|i'?m in danger|bring a (?:knife|gun|weapon)|"
                 r"kill (?:him|her|them|everyone))\b", value, re.I):
        return 3, "urgent_danger"
    if re.search(r"\b(?:abused|bad touch|wrong touch|touch(?:ed|es|ing)? me|"
                 r"hit(?:s|ting)? me|beat(?:s|ing)? me|hurt(?:s|ing)? me)\b", value, re.I):
        return 2, "protected_disclosure"
    return 2, "safety_concern"


def is_nonsense(text: str) -> bool:
    """True only for empty / pure-symbol / keyboard-mash input.

    Deliberately narrow so a terse real answer is never gated: any token with a
    vowel, any digit, or any recognizable short word passes through to the model.
    """
    t = (text or "").strip()
    if not t:
        return True
    if not _ALNUM_RE.search(t):          # pure punctuation / emoji / symbols
        return True
    if _RUN_RE.match(t):                 # "aaaaaa", "!!!!!"
        return True
    words = _WORD_RE.findall(t)
    has_digit = bool(re.search(r"\d", t))
    # No digits and no alphabetic word at all (e.g. "µ", stray marks) -> nonsense.
    if not words and not has_digit:
        return True
    # Keyboard mash: with no digits, if every substantial (>=4-char) word is
    # vowel-less it is a mash ("sdfghjk", "asdkfj qptz"). Requiring a long word and
    # ALL long words vowel-less keeps real terse answers safe ("cos", "x=2", "why").
    if not has_digit:
        long_words = [w for w in words if len(w) >= 4]
        if long_words and all(not _VOWEL_RE.search(w) for w in long_words):
            return True
    return False


def gate(text: str) -> Optional[RouteResult]:
    """Run the deterministic gates in priority order. Returns a RouteResult if a
    gate fires (SAFETY wins over NONSENSE), else None to pass through."""
    if is_safety(text):
        tier, category = classify_safety(text) or (2, "safety_concern")
        if _dbg:
            _dbg.emit(_dbg.L2, "gate_fired", gate="SAFETY", text_len=len(text or ""))
        return RouteResult(
            primary="SAFETY",
            safety_alert=True,
            safety_tier=tier,
            safety_category=category,
            source="gate",
            reason="deterministic SAFETY lexicon match",
        )
    if is_nonsense(text):
        if _dbg:
            _dbg.emit(_dbg.L2, "gate_fired", gate="NONSENSE", text_len=len(text or ""))
        return RouteResult(
            primary="NONSENSE",
            source="gate",
            reason="deterministic NONSENSE gate (empty / symbols / keyboard-mash)",
        )
    if _dbg:
        _dbg.emit(_dbg.L2, "gate_pass", text_len=len(text or ""))
    return None
