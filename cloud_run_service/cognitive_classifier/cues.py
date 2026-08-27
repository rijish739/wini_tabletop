"""Deterministic surface cues shared by dataset curation and the runtime classifier.

--------------------------------------------------------------------------
FROZEN — OFFLINE TOOLING ONLY (ticket 17, 2026-08-27).
The 9-cue feature vector no longer runs at runtime: `score_matrix()` zero-fills
the cue dims so the shipped logreg keeps working without a re-fit (the rebuild
path was lost in `5b847a1`). `cue_features` / `cue_matrix` below remain for
offline tooling and dataset curation ONLY — do NOT add them back to any runtime
scoring path. A re-fit would require restoring `build_bank.py` from `5b847a1^`
first. PolicyShadow, the vector's only other consumer, is retired from the
runtime. See CLAUDE.md "Known gotchas".
--------------------------------------------------------------------------

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
# NOTE (ticket 17, 2026-08-27): the 9-cue feature vector has been retired from
# the runtime.  classifier.py's score_matrix() zero-fills the cue dims when the
# shipped logreg coef width is wider than the embedding alone, so the heads keep
# running without a re-fit (no rebuild path in the tree — build_bank.py was lost
# in commit 5b847a1).  cue_features / cue_matrix remain in this file for any
# offline tooling that still needs them.  PolicyShadow no longer calls them at
# all (also ticket 17).

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
    r"|still (confused|lost|stuck|do ?n'?t (get|understand))"
    # frustration that the tutor is NOT teaching — keeps asking / not explaining /
    # not answering / not complete. These must re-explain (rule 1b), not re-probe
    # (transcript regression: "you keep asking me questions" -> another question).
    r"|not (explain|answer|teach|telling|saying)(ing)?"
    r"|(keep|keeps|just|only) (asking|questioning|repeating)"
    r"|(asking|same question) (me )?(the same |again )"
    r"|(not|isn'?t|is ?n'?t) (complete|helping|working|teaching)"
    r"|you'?re not (talking|explaining|teaching|answering|helping)"
    r"|\b(different|wrong|random|unrelated|off.?topic) (answer|answers|response|responses)\b",
    re.IGNORECASE,
)


def is_clarification_request(text: str) -> bool:
    """True when the reply is a confusion / 'make it simpler' / 'you are repeating'
    plea rather than an answer attempt. Standalone runtime cue (see CLARIFY_RE)."""
    return bool(CLARIFY_RE.search(text or ""))


# VISUALIZE_RE (standalone, like CLARIFY_RE — no feature-vector / rebuild impact):
# the student cannot form a mental image ("I cannot imagine this", "can't picture
# it", "how does it look?"). This is a representation gap, not generic confusion —
# the tutor must respond with a concrete scene / figure, never another textual
# definition (gemini_tutor_issues.md #3/#4: "I cannot imagine this" was answered
# with a re-definition of triangle sides).
#
# It ALSO catches the DIRECT imperative visual request — "show me the animation",
# "draw a circle", "give me images", "show me a right triangle". These are not the
# "I can't picture it" plea; they are the child ASKING to be shown something, and
# they were the dominant Board-Buddy no-launch cause: wants_visual stayed false, so
# the Visual Benefit Gate only earned a figure when the concept slug happened to be
# visual — never on the ask itself (see the field trace, 2026-07-30). Wiring these
# into wants_visual makes the gate's `remedy` path fire on the explicit request.
VISUALIZE_RE = re.compile(
    r"(can'?t|can ?not|could ?n'?t|do ?n'?t|not able to|unable to|hard to|difficult to) "
    r"(really |quite |even )?(imagine|picture|visuali[sz]e|see (it|this|that))"
    r"|(imagine|picture|visuali[sz]e) (it|this|that)\b.{0,20}(can'?t|not|hard)"
    r"|in my (head|mind)"
    r"|(how|what) (does|do|will|would) (it|this|that|they) look"
    r"|show me (how|what) (it|this|that) looks"
    # a request verb (show/draw/see/give/want/…) shortly followed by a VISUAL-ARTIFACT
    # noun — these words *are* pictures, so the ask is unambiguous ("show me the
    # animation", "give me images", "see a animation", "a good circle animation").
    r"|\b(show|draw|see|give|display|paint|sketch|want|need|like)\b[^.?!]{0,30}"
    r"\b(picture|image|animation|animate|diagram|drawing|figure|graph|chart|"
    r"video|visual|illustration|sketch|painting)s?\b"
    # show/draw/give/want me <a drawable maths shape> ("show me circles", "show me a
    # right triangle", "show me different types of circles", "I want many triangles").
    r"|\b(show|draw|display|paint|sketch|give|want|need)\b( me| us)?[^.?!]{0,40}"
    r"\b(circle|triangle|rectangle|parabola|polygon|quadrilateral|"
    r"cone|cylinder|sphere|cube|hemisphere|frustum)s?\b"
    # "in pictures" / "with images / a diagram / animation" ("explain with images").
    r"|\b(in|with|using|through) (a |an )?(picture|image|diagram|animation|"
    r"visual|drawing|figure|graph|chart)s?\b",
    re.IGNORECASE,
)


def is_visualization_request(text: str) -> bool:
    """True when the student says they cannot picture / imagine the idea, or asks
    what it looks like. Standalone runtime cue (see VISUALIZE_RE)."""
    return bool(VISUALIZE_RE.search(text or ""))


# PURPOSE_RE (standalone): the student asks WHY this is worth learning, what it is
# for, or HOW something just shown connects to the topic — including the complaint
# that their question was not answered. These must be ANSWERED directly, never met
# with another problem or a definition (2026-07-03 transcript: "how is this related
# to quadratic equation" drew a TRANSFER_PROBLEM, then two more deflections).
PURPOSE_RE = re.compile(
    r"why (do|does|should|must|would) (i|we|anyone|one)( even)? "
    r"(have to |need to |got to )?(learn|study|know|care|use|do)"
    r"|why (are we|am i) (learning|studying|doing)"
    r"|what('s| is) the (use|point|purpose|need) of"
    r"|what (do|will|would) (i|we) (ever )?use (it|this|that) for"
    r"|when (will|would|do) (i|we) (ever )?use"
    r"|\bhave to do with\b"
    r"|(how|why) .{0,50}\b(related|connected|linked|relevant)\b"
    r"|(real.?(life|world|time)) (use|application)s?\b|use in real.?(life|world)"
    r"|(did ?n'?t|didn'?t|do ?n'?t|not|never|haven'?t) answer(ed)? (my|the) question"
    r"|answer my question",
    re.IGNORECASE,
)


def is_purpose_question(text: str) -> bool:
    """True for a why-learn-this / what-is-it-for / how-is-this-connected question,
    or an explicit 'you didn't answer my question' complaint. Standalone runtime cue."""
    return bool(PURPOSE_RE.search(text or ""))


# ANIMATION_RE (standalone, no feature-vector impact): the student wants to SEE THE IDEA
# MOVE — an animation, a real-time graph, or to watch a quantity CHANGE/GROW. This is a
# refinement of the visual ask (VISUALIZE_RE): a static figure is not enough, so the answer
# must describe a CHANGING quantity (name it + its from/to) and the board must carry an
# `animate_param`. It was the dominant reason animation never fired on real turns: the answer
# grounds the board, and a static answer yields a static board (2026-08-01 live trace).
ANIMATION_RE = re.compile(
    r"\banimat(e|ed|ion|ions|ing)\b"
    r"|real.?time|moving (picture|graph|image|diagram)|in motion|make it move"
    r"|watch (it|this|them|the .{0,20}?) (move|change|grow|shrink|increase|decrease)"
    r"|see (it|this|them|how) .{0,25}(move|moving|change|changing|grow|growing)"
    r"|how .{0,30}(change|changes|grow|grows|move|moves|vary|varies) (as|when|over)"
    r"|as .{0,20}(grows|increases|decreases|changes|rises|falls)"
    r"|step.?by.?step animation|dynamic (graph|figure|visual)",
    re.IGNORECASE,
)


def is_animation_request(text: str) -> bool:
    """True when the student wants to SEE the idea MOVE / animate / change over time —
    not just a static picture. Standalone runtime cue (see ANIMATION_RE)."""
    return bool(ANIMATION_RE.search(text or ""))


# REAL_LIFE_RE (standalone, no feature-vector impact): the student asks for a REAL-LIFE /
# everyday EXAMPLE of the concept — where it is used, a practical situation, a day-to-day
# instance. Distinct from PURPOSE_RE's abstract "why learn this": this wants a CONCRETE
# example the tutor should SHOW (stickers of real objects) so the child feels the real-world
# need of the maths, not a verbal justification (user directive 2026-08-01).
REAL_LIFE_RE = re.compile(
    r"real.?(life|world)"
    r"|every.?day( life| example| situation)?|daily life|day.?to.?day"
    r"|(practical|concrete) (example|use|situation|application)"
    r"|example (from|in) (real|daily|everyday|day)"
    r"|where (is|are|do|does|can|would) .{0,25}(use|used|useful|apply|applied|see|find|happen)"
    r"|when (do|would|will) (i|we|you|one) .{0,20}use (it|this|that)"
    r"|use(d)? in (real|daily|everyday|day)",
    re.IGNORECASE,
)


def is_real_life_request(text: str) -> bool:
    """True when the student asks for a real-life / everyday example or use of the concept —
    a request to SHOW its real-world need (stickers path). Standalone runtime cue."""
    return bool(REAL_LIFE_RE.search(text or ""))


# LEARN_REQUEST_RE (standalone): the student explicitly asks to be TAUGHT a topic.
# The reply must teach (explain/recap), never open with a cold quiz (2026-07-03
# transcript: "I want to learn about the quadratic equation" -> QUIZ, because the
# perception signals were empty and the deterministic side had no cue).
LEARN_REQUEST_RE = re.compile(
    r"\bi (want|wanted|would like|wish) to (learn|study|know|understand)\b"
    r"|\bteach me\b|\bcan you (teach|explain)\b|\blet'?s (learn|study)\b"
    # imperative teach requests: "explain X", "show me how X", "walk me through X",
    # "how do i solve/find X". Without these a bare "explain the quadratic formula"
    # missed every learning cue and fell to rule 10b QUIZ (2026-07-27 live test).
    r"|\bexplain\b|\bshow me (how|what|why)\b|\bwalk me through\b"
    r"|\bhow do (i|you|we) (solve|find|do|get|work)\b",
    re.IGNORECASE,
)


def is_learning_request(text: str) -> bool:
    """True when the student explicitly asks to learn / be taught something.
    Standalone runtime cue."""
    return bool(LEARN_REQUEST_RE.search(text or ""))


# Topic-shift request extraction (standalone). Two shapes:
#  * explicit — "i asked about X", "i want to learn about X", "switch to X",
#    "teach me X", "let's do X": TOPIC_REQUEST_RE captures the X span so the
#    runtime can resolve the REQUESTED topic (never the negated mention — the
#    2026-07-03 regression resolved "I asked about natural numbers, you are
#    explaining me quadratic equation" to the quadratic concept).
#  * bare — a short noun-phrase turn ("Natural numbers.", "Trigonometry") with no
#    question/answer/ack shape: is_bare_topic. The caller must gate this on "no
#    pending question" because a bare phrase can be a legitimate answer.
_TOPIC_SPAN = r"([a-z][a-z \-']{2,40}?)(?=[,.;!?]| not\b| instead\b| please\b| you\b| na\b|$)"
TOPIC_REQUEST_RE = re.compile(
    r"\bi (?:was )?ask(?:ed|ing)? (?:you )?(?:about|for) " + _TOPIC_SPAN
    + r"|\bi want(?:ed)? to (?:learn|know|study|do|understand) (?:about |more about )?" + _TOPIC_SPAN
    + r"|\b(?:can|shall) we (?:do|learn|study|try|talk about) " + _TOPIC_SPAN
    + r"|\blet'?s (?:do|learn|study|try) " + _TOPIC_SPAN
    + r"|\bswitch (?:to|the topic to) " + _TOPIC_SPAN
    + r"|\bteach me (?:about )?" + _TOPIC_SPAN
    + r"|\btell me about " + _TOPIC_SPAN,
    re.IGNORECASE,
)

# words that mean the captured span is not actually a topic name ("about" appears
# when the span regex backtracks over a too-short pronoun: "learn about it")
_TOPIC_STOP = {"it", "this", "that", "them", "these", "those", "more", "again",
               "something", "anything", "maths", "math", "everything", "about"}

# A negation/complaint immediately BEFORE a request span means the child is naming
# the topic they DON'T want, not the one they do ("only want to teach me quadratic
# equation. I want to learn PARABOLA" → the desire is parabola; "don't teach me X,
# teach me Y" → Y). We scan the short window just before a match and drop the span
# when it trails a negation cue. Anchored at the window end so only a *nearby*
# negation counts (a negation two clauses back is unrelated).
_NEG_BEFORE = re.compile(
    r"(?:\bnot\b|\bnever\b|n'?t\b|\bno\b|\bdont\b|\bbored\b|\btired\b|\bhate\b|"
    r"\bstop\b|\binstead\b|\bonly\b)[\sa-z']*$",
    re.IGNORECASE,
)


def extract_topic_request(text: str):
    """Return the requested-topic span for an explicit topic request / correction
    ("i asked about NATURAL NUMBERS", "teach me TRIANGLES"), else None. The span is
    capped at 6 words; pronouns and empty fillers return None.

    When a turn carries MORE than one request span, return the LAST one that is not
    negated — the most-recent stated desire. This fixes the complaint shape "only
    want to teach me quadratic equation. I want to learn parabola", which previously
    returned the disliked topic ("quadratic equation") from the first clause and so
    re-locked the child onto it (the exact 2026-07-26 topic-lock bug)."""
    t = text or ""
    best = None
    for m in TOPIC_REQUEST_RE.finditer(t):
        span = next((g for g in m.groups() if g), "").strip()
        words = span.split()[:6]
        if not words:
            continue
        joined = " ".join(words)
        if joined.lower() in _TOPIC_STOP or words[0].lower() in _TOPIC_STOP:
            continue
        pre = t[max(0, m.start() - 24):m.start()]
        if _NEG_BEFORE.search(pre):
            continue                      # span names the un-wanted topic — skip it
        best = joined                     # keep the last surviving desire
    return best


# The child wants to LEAVE the current topic without naming a specific new one
# ("explain something different", "I don't want to learn this", "I'm bored of this",
# "change the topic", "anything else"). Distinct from a topic REQUEST (which names a
# target) and from SESSION_CONTROL (which wants to stop/pause). When this fires and
# no concrete catalog topic is groundable, the tutor must offer a menu of OTHER
# chapters rather than silently re-grounding on the concept the child just refused.
DIFFERENT_TOPIC_RE = re.compile(
    r"\bsomething (?:else|different|new|other)\b"
    r"|\banything else\b"
    r"|\b(?:a )?(?:different|another|new|other) (?:topic|chapter|subject|thing|concept)\b"
    r"|\bchange (?:the )?(?:topic|subject|chapter)\b"
    r"|\b(?:i'?m|i am|im) bored (?:of|with)\b"
    r"|\b(?:i )?(?:do\s*n'?t|do not|dont) want to (?:learn|study|do|continue)\b",
    re.IGNORECASE,
)


def wants_different_topic(text: str) -> bool:
    """True when the child asks to move off the current topic without naming a new
    one. Standalone runtime cue (no classifier/policy rebuild — same contract as the
    other *_RE cues)."""
    return bool(DIFFERENT_TOPIC_RE.search(text or ""))


# A bare topic is a NOUN-PHRASE label ("Natural numbers", "Trigonometry"), never
# an imperative or a plea. These tokens mark a command/request directed at the
# tutor ("GIVE ME a challenge", "HELP ME", "EXPLAIN THIS", "TELL ME MORE", "I WANT
# to study", "LET ME try"); any of them disqualifies the phrase as a topic name.
# Without this guard the broad letters-and-spaces match hijacked ordinary requests
# into a bogus topic shift (test_results.md Bug 1, 2026-07-17). Chosen so none of
# them appears in an NCERT Class-10 topic title (note: "some" is deliberately
# excluded — "Some Applications of Trigonometry" is a real chapter).
_NONTOPIC_TOKENS = frozenset({
    "i", "im", "me", "my", "mine", "we", "us", "our", "you", "your",
    "this", "that", "it", "them", "these", "those",
    "please", "help", "give", "gimme", "tell", "show", "let", "lemme",
    "want", "wanna", "explain", "teach", "do", "try", "start", "make",
    "ask", "say", "more", "again", "another", "challenge",
})


def is_bare_topic(text: str) -> bool:
    """True for a short bare noun-phrase turn that looks like a topic label
    ("Natural numbers.", "Trigonometry"). Deliberately narrow: no question form,
    no answer/ack/hint cue, no digits or operators, and no imperative/request token
    (so "give me a challenge" / "please explain" are NOT read as topics). The caller
    must additionally require that no diagnostic/micro question is open."""
    t = (text or "").strip().rstrip(".!").strip()
    if not t or "?" in text:
        return False
    words = t.split()
    if not (1 <= len(words) <= 4):
        return False
    if re.search(r"[\d=+*/^<>]", t):
        return False
    if is_question(t) or is_pure_ack(t) or ANSWER_RE.search(t) or HINT_RE.search(t):
        return False
    if re.match(r"^(yes|yeah|ya|yep|no|nope|nah|ok|okay|hmm+|uh+|um+)\b", t, re.IGNORECASE):
        return False
    # imperative/plea, not a noun-phrase label — reject if any word is a request token
    if any(re.sub(r"[^a-z']", "", w.lower()) in _NONTOPIC_TOKENS for w in words):
        return False
    return bool(re.fullmatch(r"[a-zA-Z][a-zA-Z \-']*", t))


def is_answer_attempt(text: str) -> bool:
    """True when the reply carries a surface cue of actually attempting an answer
    ('i think it is...', 'the answer is', '= 5', 'is it 0'). Standalone runtime cue
    used to protect genuine attempts from the non-attempt guard."""
    return bool(ANSWER_RE.search(text or ""))


# ---------------------------------------------------------------------------
# Part 12 — session pedagogy mode requests (standalone cues; NOT feature-vector
# entries, so NO classifier/policy rebuild — same contract as CLARIFY_RE etc.).
# These let the ModeController switch EXPLAIN/PRACTICE/TEST on an explicit ask
# (§5.1). Order matters at the call site: STOP_TEST is checked before TEST so
# "stop the test" exits to EXPLAIN rather than starting one.
# ---------------------------------------------------------------------------
STOP_TEST_RE = re.compile(
    r"\bstop (the )?(test|quiz|testing|quizzing)\b"
    r"|\b(end|quit|finish|cancel|leave) (the )?(test|quiz)\b"
    r"|no more (test|quiz|question)s?\b"
    r"|\b(i )?do ?n'?t want (to (do |take )?(a )?)?(test|quiz|to be tested)\b"
    r"|\bstop (practis|practic)ing\b|no more practice\b"
    r"|\b(i )?do ?n'?t want to practi[cs]e\b",
    re.IGNORECASE,
)

TEST_REQUEST_RE = re.compile(
    r"\b(test|quiz) me\b|\bquiz\b"
    r"|(can|could|shall|let'?s|will) (we|you|i) (do|take|try|start|have|give me) (a )?(test|quiz)"
    r"|\bgive me (a )?(test|quiz)\b|\b(i )?want (a )?(test|quiz)\b"
    r"|\btake (a |the )?(test|quiz)\b|check (how much|what) i (know|learned|learnt)"
    r"|\btest my (knowledge|understanding)\b|\bexam me\b",
    re.IGNORECASE,
)

PRACTICE_REQUEST_RE = re.compile(
    r"\b(let'?s |can we |i want to |i wanna |lemme |let me )?practi[cs]e\b"
    r"|give me (a |some )?(problem|sum|question|exercise|example)s?( to (solve|do|try))?"
    r"|(more|another|some) (problem|sum|question|exercise|practice)s?\b"
    r"|(let me|can i|i want to|i wanna) (try|solve|do) (a |some |the )?(problem|sum|question|one)"
    r"|work (on )?(some |a few )?(problem|sum|question|example)s?\b"
    r"|\blet'?s (do|try) (some |a few )?(problem|sum|question|example|practice)s?\b",
    re.IGNORECASE,
)

EXPLAIN_REQUEST_RE = re.compile(
    r"\b(go |get |take (me )?)?back to (learning|explaining|the lesson|explanation|teaching)\b"
    r"|just (explain|teach)\b|\bexplain (it |this )?(again|more|properly)\b"
    r"|\b(i )?want to (go back to )?learn(ing)?\b(?! .*\b(test|quiz|practi[cs]e)\b)"
    r"|stop (the )?(problem|question|exercise)s?\b|no more (problem|sum|exercise)s?\b",
    re.IGNORECASE,
)


def is_stop_test_request(text: str) -> bool:
    """True when the student wants to leave TEST/PRACTICE mode but keep learning
    (NOT a session-control 'bye'). Exits to EXPLAIN (§5.1). Check BEFORE the
    test/practice cues so 'stop the test' does not start one."""
    return bool(STOP_TEST_RE.search(text or ""))


def is_test_request(text: str) -> bool:
    """True for an explicit request to be quizzed/tested ('test me', 'quiz me',
    'can we do a test'). Standalone runtime cue -> ModeController switches to TEST."""
    return bool(TEST_REQUEST_RE.search(text or ""))


def is_practice_request(text: str) -> bool:
    """True for an explicit request to practice / get problems to solve ('let's
    practice', 'give me a problem'). Standalone runtime cue -> switch to PRACTICE."""
    return bool(PRACTICE_REQUEST_RE.search(text or ""))


def is_explain_request(text: str) -> bool:
    """True for an explicit request to return to plain explanation / learning
    ('explain it again', 'back to learning', 'just explain'). -> switch to EXPLAIN."""
    return bool(EXPLAIN_REQUEST_RE.search(text or ""))


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
