"""Stage A deterministic front-door gates: SAFETY + NONSENSE.

`gate()` returns a RouteResult when a gate fires, else None (pass through to the
Gemini route / learning pipeline). It is pure and model-free.

* NONSENSE is kept deliberately CONSERVATIVE: a wrongly-gated real answer ("5",
  "yes", "x=2") is a pedagogy failure, so it fires only on empty / pure-symbol /
  obvious keyboard-mash input and otherwise defers to the model.
* SAFETY here is **the degraded-mode outage net, not the detector**. See below.

--------------------------------------------------------------------------
THE SAFETY INVERSION LANDED (slice 12). `_SAFETY_RE` IS NO LONGER PRIMARY.

`docs/architecture/SAFETY_ROUTE_TAXONOMY.md` (normative) is implemented:
`cloud_run_service/child_safety/` issues a dedicated Gemini call on **every turn,
unconditionally**, and **that call makes the verdict** -- classes and imminence.
This lexicon is demoted to the DEGRADED-MODE OUTAGE NET (§8):

  * it is read by Utterance Intake, which publishes it as `SafetySignals`;
  * it contributes a finding ONLY when the model call failed or timed out;
  * it may emit the axis only -- `{UNSPECIFIED_CONCERN}` / `ELEVATED`, never a
    class, NEVER `CRITICAL`;
  * it is FROZEN: never edited toward the model, never edited by reading a
    missed-corpus row. Its freeze is CI-maintained
    (`eval/corpora/safety/degraded_net.jsonl`).

Why the inversion: `_SAFETY_RE` was measured producing a tier-3 false positive on
`i do not want to die in this level` (negation-blind, subject-blind) while missing
peer-at-risk, online solicitation, threats and `things are bad at home` outright.
A regex is a poor primary detector for a domain whose defining property is that
the highest-risk disclosures are the least lexically explicit.

The "may only add recall, never remove" rule survives, retargeted: nothing may
ever remove a finding, whatever made it. Severity is derived at exactly one site
(`interaction_control/safety_composition.py`) and written by no detector -- which
is why `classify_safety`'s tier/category pair was DELETED here rather than left
as a second, quieter severity author.

The 1.0 SAFETY recall once reported by `eval.perception_eval --gates` is measured
on a 20-phrase corpus that mirrors these patterns -- memorization, not evidence.
Real recall is measured by `eval/safety_eval.py` against blind per-class corpora,
and no aggregate safety number is published anywhere.
--------------------------------------------------------------------------
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


# `classify_safety` was DELETED at the safety inversion (slice 12).
#
# It returned a `(tier, category)` pair, which made this file a second severity
# author -- and the taxonomy's §5 allows exactly one, in the composition step. Its
# tier-3 regex was also much narrower than `_SAFETY_RE`, so 6 of 9 self-harm probes
# landed in the tier-2 catch-all: a measured miscalibration nothing depended on
# except a log line and a dashboard column. Both now read `severity`.
#
# Do not reintroduce a tier here. If you need severity, read the composed
# `SafetyVerdict`; if you need to know whether the net tripped, call `is_safety`.


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


def gate(text_or_observation) -> Optional[RouteResult]:
    """Run the deterministic front-door gates in priority order (SAFETY wins over
    NONSENSE), else return None to pass through.

    Two callers, one priority order in one place:

    * ``gate(text: str)`` — the legacy path, still read by callers that have not
      yet moved to the observation.
    * ``gate(observation: UtteranceObservation)`` — the walking-skeleton path
      (ticket 01): a **pure translation** of the observation's readings. Safety
      reading tripped -> SAFETY; else legibility illegible -> NONSENSE; else None.
      It reads the **textual** axis only — nothing acoustic feeds NONSENSE. That
      ``gate()`` has no detection logic of its own left in it on this path is the
      tell that the Utterance Intake seam landed, not a reason to move it.
    """
    observation = None if isinstance(text_or_observation, str) else text_or_observation
    if observation is not None:
        text = observation.normalized_text
        safety_tripped = observation.safety.tripped
        illegible = observation.legibility.illegible
    else:
        text = text_or_observation or ""
        safety_tripped = is_safety(text)
        illegible = is_nonsense(text)
    if safety_tripped:
        # The gate reports the axis and nothing else. No tier, no category, no
        # severity: the composition step derives severity from the unioned findings
        # at the one site allowed to (§5, §6.5), and this net is not allowed to
        # produce CRITICAL at all (§8).
        if _dbg:
            _dbg.emit(_dbg.L2, "gate_fired", gate="SAFETY", text_len=len(text))
        return RouteResult(
            primary="SAFETY",
            safety_alert=True,
            source="gate",
            reason="degraded-net SAFETY lexicon match",
        )
    if illegible:
        if _dbg:
            _dbg.emit(_dbg.L2, "gate_fired", gate="NONSENSE", text_len=len(text))
        return RouteResult(
            primary="NONSENSE",
            source="gate",
            reason="deterministic NONSENSE gate (empty / symbols / keyboard-mash)",
        )
    if _dbg:
        _dbg.emit(_dbg.L2, "gate_pass", text_len=len(text))
    return None
