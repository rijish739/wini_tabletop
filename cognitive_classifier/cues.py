"""Deterministic surface cues shared by dataset curation and the runtime classifier.

Two consumers:
  1. curate_dataset.py uses the regexes as GOLD RULES for the three
     rule-governed labels (question, request_hint, simplification_request),
     making their gold deterministic and therefore consistent.
  2. build_bank.py / classifier.py append the binary cue vector to the MiniLM
     embedding for the logistic head. Mean-pooled sentence embeddings dilute
     signals carried by 1-2 tokens ("wait,", "just give hint") under 20 tokens
     of louder content; these features re-surface them.

Any change here changes gold semantics — rebuild the curated dataset AND the
bank together.
"""

from __future__ import annotations

import re

import numpy as np

INTERROGATIVE_FIRST = {
    "what", "why", "how", "when", "where", "which", "who", "whom",
    "is", "are", "am", "was", "were", "do", "does", "did",
    "can", "could", "should", "would", "will", "shall", "may", "might",
    "have", "has", "had", "dont", "don't", "isnt", "isn't", "cant", "can't",
}

HINT_RE = re.compile(
    r"\b(hint|clue|nudge)\b"
    r"|how (do|to|should) i (start|begin)"
    r"|where (do|should) i (start|begin)"
    r"|\bfirst step\b"
    r"|can'?t (even )?start|cannot start"
    r"|just tell( me)?\b|just give\b"
    r"|(tell|give) me the (answer|steps|formula)"
    r"|what'?s the answer|what is the answer"
    r"|i('| a)?m stuck|i am stuck",
    re.IGNORECASE,
)

SIMPLIFY_RE = re.compile(
    r"\bsimpl(er|e|ify|y)\b|easy (words|way|language)|\beasier\b"
    r"|plain (words|language)|less confusing"
    r"|(another|different|other) way"
    r"|once more|one more time|explain (it |this )?again|again slowly|\bslowly\b",
    re.IGNORECASE,
)

EXAMPLE_RE = re.compile(
    r"\bexamples?\b|with numbers|actual (problem|sum|question)"
    r"|show me (a|one|some) (sum|problem|question)|a solved",
    re.IGNORECASE,
)

MODALITY_RE = re.compile(
    r"\bdraw(ing)?\b|picture|diagram|graph|chart|visual|video|audio"
    r"|animation|moving|blocks|real life|hands",
    re.IGNORECASE,
)

SELF_CORRECTION_RE = re.compile(
    r"\bwait\b|\bactually\b|i was wrong|my bad|\boh no\b|hold on"
    r"|\bi mean\b|maybe not|no wait|sorry,? i (think|did|wrote)"
    r"|i did (it|something) wrong|i confused myself",
    re.IGNORECASE,
)

ANSWER_RE = re.compile(
    r"i think (the answer|it is|it'?s|its)|my answer|\bi got\b|is it \d"
    r"|answer is|i guessed|i ?a?m guessing|\bi wrote\b|=\s*-?\d",
    re.IGNORECASE,
)

NEXT_RE = re.compile(
    r"next (chapter|topic|thing|one)|move (on|to next)|done with this"
    r"|we finished|completed this",
    re.IGNORECASE,
)

CONFIDENT_RE = re.compile(
    r"\b(so |too |very )?easy\b|i know this|i can do (this|it)|already know"
    r"|\bi get it\b|this is simple for me",
    re.IGNORECASE,
)

CUE_NAMES = [
    "q_form", "hint_ask", "simplify_ask", "example_ask", "modality_ask",
    "self_corr", "answer_try", "move_next", "confident",
]
# NOTE: CUE_NAMES length is baked into the shipped logreg widths (classifier +
# policy shadow). Extend it only with a full rebuild of both.

# Standalone cue (NOT part of the feature vector): the student confirms they
# understood the previous explanation. Used by tutor_loop rules so an
# acknowledgment never triggers a re-explanation. Reason-bearing replies such
# as "yes because ..." are not pure acks; the pacing layer keeps them as
# student evidence.
ACK_RE = re.compile(
    r"\b(yes|ya|yeah|ok(ay)?|got it|understood|i (have |had )?understood"
    r"|makes sense|that helps|it (helped|explained)|clear now|all clear"
    r"|i get it|thanks|thank you)\b",
    re.IGNORECASE,
)

_WH_RE = re.compile(r"\b(what|why|how|which|where|when|who)\b", re.IGNORECASE)

# Standalone cues (NOT part of the feature vector, like ACK_RE above) used only
# by the tutor_loop runtime — adding them does NOT change gold semantics or the
# logreg widths, so no classifier/policy rebuild is required.
#
# CLARIFY_RE: the student is signalling "I did not understand / this is too hard /
# you are repeating yourself / make it simpler" — a meta-confusion or simplification
# plea, NOT an attempt at any pending diagnostic. The exemplar classifier often
# misreads these as curiosity/high_confidence (see learning_log regression: an
# overwhelmed "how can i learn in an easy manner" scored curiosity 0.67), so this
# deterministic cue must be available to outrank it in the pedagogy rules.
CLARIFY_RE = re.compile(
    r"(can'?t|can ?not|could ?n'?t|do ?n'?t|did ?n'?t|not able to|unable to) "
    r"(really |quite |fully |even )?(understand|get it|get this|follow|grasp|make sense of)"
    r"|did ?n'?t (understand|get|follow)|not (clear|getting|understanding)"
    r"|what (do|did|does) (you|u|that|this) mean"
    r"|i('?m| am)? (so |really |totally |very |a bit )?(confused|lost)"
    r"|\b(scary|too hard|too difficult|too confusing|too complicated)\b"
    r"|(so|too|very) (hard|difficult|confusing|complicated|tough)"
    r"|makes? no sense|does ?n'?t make sense|not making sense"
    r"|\brepeat(ing|ed)?\b|same (answer|thing|question|reply)|again and again"
    r"|(easy|easier|simple|simpler) (manner|way)|in (a |an )?easy"
    r"|\b(simpler|more simply|simply put|in simple (words|terms))\b"
    r"|explain (it |this )?(again|differently|another way|in a simpler)"
    r"|say (it|that) again|one more time|once more"
    r"|still (confused|lost|stuck|do ?n'?t (get|understand))",
    re.IGNORECASE,
)


def is_clarification_request(text: str) -> bool:
    """True when the reply is a confusion / 'make it simpler' / 'you are repeating'
    plea rather than an answer attempt. Standalone runtime cue (see CLARIFY_RE)."""
    return bool(CLARIFY_RE.search(text or ""))


def is_answer_attempt(text: str) -> bool:
    """True when the reply carries a surface cue of actually attempting an answer
    ('i think it is...', 'the answer is', '= 5', 'is it 0'). Standalone runtime cue
    used to protect genuine attempts from the non-attempt guard."""
    return bool(ANSWER_RE.search(text or ""))


def is_pure_ack(text: str) -> bool:
    """True only when the message is an acknowledgment with NO fresh ask.

    The exemplar classifier systematically misreads acknowledgments as
    confusion (the dataset has almost no positive-confirmation utterances, and
    MiniLM embeds "makes sense now" next to "not making sense now"), so this
    deterministic cue must outrank the classifier in the pedagogy rules —
    same philosophy as the question rule. "yes but what about..." is NOT a
    pure ack: any question mark, WH-word, 'but', or reason marker disqualifies it.
    """
    return bool(ACK_RE.search(text)) and "?" not in text \
        and not _WH_RE.search(text) and not re.search(r"\b(but|because|since|as)\b", text, re.IGNORECASE)


def is_question(text: str) -> bool:
    """Deterministic interrogative rule — the gold rule for `question`."""
    if "?" in text:
        return True
    stripped = text.strip().lower()
    first = re.split(r"[\s,]+", stripped, maxsplit=1)[0] if stripped else ""
    if first in INTERROGATIVE_FIRST:
        return True
    # Indian-English tag questions without a question mark: "...this is correct na"
    return bool(re.search(r"\b(na|right)\W*$", stripped))


def cue_features(text: str) -> np.ndarray:
    """Binary cue vector appended to the embedding for the logistic head."""
    return np.array(
        [
            1.0 if is_question(text) else 0.0,
            1.0 if HINT_RE.search(text) else 0.0,
            1.0 if SIMPLIFY_RE.search(text) else 0.0,
            1.0 if EXAMPLE_RE.search(text) else 0.0,
            1.0 if MODALITY_RE.search(text) else 0.0,
            1.0 if SELF_CORRECTION_RE.search(text) else 0.0,
            1.0 if ANSWER_RE.search(text) else 0.0,
            1.0 if NEXT_RE.search(text) else 0.0,
            1.0 if CONFIDENT_RE.search(text) else 0.0,
        ],
        dtype=np.float32,
    )


def cue_matrix(texts) -> np.ndarray:
    return np.vstack([cue_features(t) for t in texts])
