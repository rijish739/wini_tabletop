"""audit_fix_detectors.py
─────────────────────────────────────────────────────────────────────────────
High-precision, text-evidence detectors + a single priority-ordered classifier
derived from the external semantic audits of exemplar_dataset_10000_fixed.json
(audit_fixed_cats_123 / _456 / _789 / _last_100).

GROUND TRUTH is always the STUDENT UTTERANCE TEXT, never the existing
(possibly-wrong) labels/action. Detectors are deliberately tight: a rule fires
only when the utterance clearly evidences the pattern, so we under-correct
rather than inject new errors. Already-correct rows are left untouched
(the classifier only proposes a change when the current action is one the
audit flagged as a contradiction for that pattern).
"""
from __future__ import annotations
import re

VALID_ACTIONS = {
    "EXPLAIN", "REPRESENTATION_TRANSLATION", "ENCOURAGE", "SOCRATIC_Q", "REVIEW",
    "BRIDGE_RECAP", "RESUME_STATE", "WORKED_EXAMPLE", "METACOGNITIVE_REFLECT",
    "QUIZ", "TRANSFER_PROBLEM", "VERBAL_ANALOGY", "REQUEST_HINT",
    "ANALOGOUS_EXAMPLE", "MISCONCEPTION_PROBE", "ISOMORPHIC_PRACTICE",
}

VALID_LABELS = {
    "abstraction_attempt", "algebraic", "answer_attempt", "anxiety",
    "cognitive_overload", "conflict", "confusion", "curiosity", "diagrammatic",
    "disengagement", "environmental_feedback", "example_request", "frustration",
    "graphical", "high_confidence", "hint_dependency", "low_confidence",
    "misconception_clue", "physical", "prerequisite_awareness",
    "prerequisite_weakness", "procedural_focus", "question", "ready_for_next",
    "recurring_error", "representation_shift", "request_hint",
    "request_representation", "self_correction", "self_monitoring",
    "shortcut_seeking", "simplification_request", "skepticism", "tabular",
    "topic_shift", "transfer_attempt", "verbal_analogy",
}


def _has(t: str, *subs: str) -> bool:
    return any(s in t for s in subs)


def _word(t: str, *words: str) -> bool:
    """Word-boundary membership (so 'coin' does not match 'coincident')."""
    return any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", t)
               for w in words)


def parse_labels(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def join_labels(labels) -> str:
    return ", ".join(sorted(set(labels)))


# ── Real-world analogy / utility markers (these are NOT manipulatives) ───────
_REALWORLD = [
    "real life", "real-life", "in real life", "real world", "real-world",
    "daily life", "everyday life", "height of", "tall building", "a building",
    "buildings", "a tree", "a ladder", "wheel", "tyre", "tire", "scale model",
    "scale models", "where do we use", "where is this used", "used in real",
    "what is the use", "what's the use", "use case", "why do we learn",
    "why are we learning", "why we learn", "what is the point",
]

# ── Classroom manipulatives (hands-on objects the student handles) ──────────
# Matched with WORD BOUNDARIES (so 'coin' != 'coincident', 'block' != 'blocked').
_MANIP_NOUNS = [
    "block", "blocks", "clay", "plasticine", "dough", "marble", "marbles",
    "matchstick", "matchsticks", "toothpick", "toothpicks", "bead", "beads",
    "dice", "die", "coin", "coins", "protractor", "compass", "set square",
    "magnet", "magnets", "sandpit", "scissors", "scissor",
]
_MANIP_PHRASES = [
    "cut out", "cutout", "cut it out", "cut them out", "cut two", "cut a circle",
    "cut a paper", "paper cut", "cut the paper", "cutting it", "cutting paper",
    "fold paper", "paper folding", "folding paper", "fold it", "fold the",
    "sand pit", "with my hands", "with hands", "with my own hands", "hands-on",
    "hands on", "touch and feel", "touch and see", "touch and move", "touch it",
    "touch them", "i need to touch", "need to touch", "want to touch", "feel it",
    "can touch", "hold it", "i can hold", "something i can hold", "hold in my hand",
    "make a model", "build a model", "make models for", "models to see",
    "models to understand", "actual model", "actual models", "a model or",
    "small model", "have models", "use models", "with a model", "craft model",
    "make something physical", "something physical", "make it with",
    "build this", "build it", "stack blocks", "stack them", "stacking",
    "roll a dice", "roll the dice", "roll a die", "roll two dice", "rolling a dice",
    "rolling the dice", "toss coins", "tossing coins", "toss a coin", "flip a coin",
    "move things around", "real things", "actual things", "things we can touch",
    "things i can touch", "physical objects", "actual objects", "real objects",
    "with objects", "manipulate", "print them and cut", "printouts of",
    "print two", "bend a wire", "bend the wire",
]


def is_manipulative_request(text: str) -> bool:
    """True only for genuine hands-on / tactile manipulative requests."""
    t = text.lower()
    if _word(t, *_MANIP_NOUNS):
        return True
    if _has(t, *_MANIP_PHRASES):
        return True
    # string/thread/wire/rope used as a manipulative (paired with handling verb)
    if _word(t, "string", "strings", "thread", "wire", "rope") and \
            _word(t, "pin", "pins", "trace", "bend", "measure", "stretch"):
        return True
    # ruler used to draw/check/measure on paper (physical), not "rule of thumb"
    if _word(t, "ruler") and _word(t, "draw", "check", "measure", "coin", "circle"):
        return True
    # paper as a manipulative
    if _word(t, "paper") and _word(t, "cut", "fold", "plot", "circle"):
        return True
    # pizza / circle paper for sectors
    if _word(t, "pizza") and _word(t, "cut", "slice", "piece"):
        return True
    return False


def has_any_physical_cue(text: str) -> bool:
    """Broader: would a `physical` label be at all justified by the text?

    Permissive on purpose (when in doubt we KEEP the label), but uses word
    boundaries for short ambiguous tokens so 'coincident' is not a physical cue.
    """
    t = text.lower()
    if is_manipulative_request(t):
        return True
    if _has(t, "touch", "feel", "hold", "hands", "build", "model", "physical",
            "blocks", "clay", "paper", "draw", "cut", "fold", "compass",
            "protractor", "ruler", "string", "thread", "pizza"):
        return True
    return _word(t, "coin", "coins", "dice", "die", "stick", "sticks", "marble",
                 "marbles", "magnet", "magnets", "wire", "rope", "object",
                 "objects", "toy", "toys")


# ── Visual translation request (animation / moving / drawing) ───────────────
def is_visual_translation_request(text: str) -> bool:
    t = text.lower()
    if _has(t, "animation", "animate", "animated"):
        return True
    if _has(t, "moving thing", "moving diagram", "moving visual", "show it moving",
            "show me moving", "turning line", "a moving"):
        return True
    if _has(t, "picture or a moving", "picture or moving", "see a picture",
            "show me a picture", "like a picture"):
        return True
    # explicit "make this into a drawing" / "draw it for me"
    if _has(t, "make this into a drawing", "make it a drawing", "into a drawing",
            "make a drawing", "draw it out", "show it as a drawing"):
        return True
    return False


# ── Example requests ────────────────────────────────────────────────────────
def is_everyday_example_request(text: str) -> bool:
    """Asks for an everyday / real-world / non-math analogy or example."""
    t = text.lower()
    if "example" not in t and "analogy" not in t:
        return False
    return _has(t, "everyday example", "real life example", "real-life example",
                "real world example", "real-world example", "real life problem",
                "everyday", "daily life", "outside of math", "outside math",
                "outside the math", "not from math", "example not math",
                "non-math", "non math", "like a real", "real life situation",
                "from real life", "in real life")


def is_numeric_example_request(text: str) -> bool:
    """Asks the tutor to SHOW an actual worked sum / numbers / a solved problem.

    Must be a request (not a description of a book's example, and not the
    complaint "i only see numbers"), and not an everyday-analogy request.
    """
    t = text.lower()
    if is_everyday_example_request(t):
        return False
    # descriptive / source-conflict framings are not requests for a new example
    if _has(t, "in the book", "book has", "the example sum in", "you taught",
            "my teacher", "only see numbers", "i see numbers and"):
        return False
    request = _has(t, "show me", "give me", "can we", "can you", "could you",
                   "let's", "lets do", "i want to see", "want to see", "just see",
                   "can i see", "wanna see", "do an example", "do a example",
                   "just do")
    # Only unambiguous worked-example phrasings. Bare "sum"/"sums" is deliberately
    # excluded: in this dataset it usually means "a math problem" or the concept
    # name "sum of n terms", which are advance/conceptual, not worked-example, reqs.
    numeric = _has(t, "an example sum", "example sum", "example sums",
                   "an actual problem", "actual numbers", "with actual numbers",
                   "with numbers", "with real numbers", "see some numbers",
                   "see numbers", "a solved example", "solved problem",
                   "solve one example", "numerical example", "number example",
                   "example with numbers", "example with just numbers",
                   "an example with", "show steps with", "do an example",
                   "do a example", "see an example", "one full sum")
    return request and numeric


# ── Pure overload / need-a-break / passing-intent (emotional, no ask) ───────
def _overload_signal(text: str) -> bool:
    t = text.lower()
    return _has(t,
        "brain is melting", "brain melting", "brain is fried", "brain fried",
        "brain is full", "brain is frozen", "brain just stopped", "brain stopped",
        "brain not working", "brain is not working", "brain will explode",
        "brain is going to explode", "head is full", "my head is full", "head full",
        "head is paining", "head is aching", "head is melting", "my head will burst",
        "take a break", "want a break", "need a break", "can we please take a break",
        "too much for one day", "too much theory for one day", "too much for today",
        "too much for my head", "too much for my brain", "can't take any more",
        "can't take in any more", "cant take any more", "can't take in new info",
        "can't process anymore", "cannot process", "too much stress",
        "don't wanna do this today", "dont wanna do this today",
        "don't want to do this today", "so much to remember",
        "too much to remember", "this is too much for me")


def _constructive_request(text: str) -> bool:
    """Does the student ask for a concrete alternative (example/visual/simpler)?"""
    t = text.lower()
    if is_numeric_example_request(t) or is_everyday_example_request(t):
        return True
    if is_visual_translation_request(t) or is_manipulative_request(t):
        return True
    return _has(t, "flowchart", "flow chart", "diagram", "draw", "chart", "picture",
                "simpler words", "simple words", "simple language", "in short",
                "summary", "summarize", "main points", "break it down", "bullet",
                "a list", "small list", "point wise", "point-wise", "word problem",
                "an example", "step by step", "step-by-step",
                # factual / selection / procedural asks deserve a concrete answer
                "which one", "which method", "when to use", "how to choose",
                "how do i know when", "what topics", "what formulas",
                "most important", "focus on", "tell me the steps",
                "give me the steps", "steps to solve")


def is_pure_overload(text: str) -> bool:
    t = text.lower()
    return (_overload_signal(t) and not _constructive_request(t)
            and not is_syllabus_exam_query(t) and not is_shortcut_steps(t))


def is_passing_intent(text: str) -> bool:
    t = text.lower()
    return _has(t, "just want to pass", "just need to pass", "i want to pass",
                "only want to pass", "don't need to understand everything",
                "dont need to understand everything", "not become a mathematician",
                "don't want to become") and not _constructive_request(t)


# ── Give-up / self-doubt (emotional → ENCOURAGE) ────────────────────────────
def is_give_up_self_doubt(text: str) -> bool:
    t = text.lower()
    return _has(t,
        "i give up", "i just give up", "want to give up", "should just give up",
        "maybe i should give up", "i should give up", "feel like giving up",
        "math is not for me", "maths is not for me", "not made for math",
        "not smart enough", "don't have the brain", "dont have the brain",
        "not good at math", "not good at maths", "i'm just not good",
        "im just not good", "i will never get", "never get good marks",
        "ever get good marks", "i think i'll fail", "i think i will fail",
        "i will fail", "everyone else understands", "everyone understands it so fast",
        "i am just so slow", "i am so slow", "i'm so slow", "leave this chapter",
        "i will leave this", "just not for me")


# ── Source / answer-key conflict needing factual resolution ─────────────────
def is_source_conflict(text: str) -> bool:
    t = text.lower()
    has_src = _has(t, "teacher said", "teacher says", "sir said", "sir says",
                   "mam said", "ma'am said", "maam said", "tuition teacher",
                   "tuition sir", "notes say", "notes says", "answer key",
                   "textbook says", "book says", "you write", "you are doing",
                   "different from", "my teacher")
    asks = _has(t, "are you sure", "which is correct", "which is right",
                "is this the right way", "right way", "what's the diff",
                "what is the diff", "difference between", "i am confused",
                "which style", "is it necessary", "wrong only", "is wrong")
    return has_src and asks


# ── Syllabus / boards / exam / grading factual queries ──────────────────────
def is_syllabus_exam_query(text: str) -> bool:
    t = text.lower()
    if not _has(t, "board", "boards", "exam", "exams", "syllabus", "marks", "paper"):
        return False
    return _has(t, "important for board", "important for exam", "come in board",
                "comes in board", "come in exam", "comes in exam", "in boards",
                "for boards", "for board exam", "in the board", "aata hai",
                "yaad karna", "enough for board", "enough for exam", "enough na",
                "for full marks", "lose marks", "get marks", "will i get marks",
                "3-mark", "3 mark", "mark question", "what kind of questions",
                "what format", "which topics", "less important for", "most imp",
                "most important for", "allowed in board", "allowed in the board",
                "required for board", "do i need to show", "need to show all",
                "show all the steps", "show whole table", "will they ask",
                "come in paper", "in the paper", "in board paper", "board exam",
                "for the exam", "for exams", "what topics", "focus on",
                "should i focus", "topics should i", "important questions")


# ── Shortcut: "just tell me steps/formula/rule, don't need the why" ─────────
def is_shortcut_steps(text: str) -> bool:
    t = text.lower()
    wants = _has(t, "just tell me the steps", "just give me the steps",
                 "tell me the steps", "give me the steps", "just the steps",
                 "just tell me the formula", "just give me the formula",
                 "tell me the formula", "give me the formula", "i just need the rule",
                 "just need the rule", "need the rule", "what to write",
                 "steps i need to follow", "steps to solve", "steps to get the answer",
                 "to follow to get")
    refuses = _has(t, "don't need the why", "dont need the why", "don't want to know why",
                   "dont want to know why", "no need for derivation", "no need to explain",
                   "don't get the why", "dont get the why", "don't need to know why",
                   "dont need to know why", "without the why", "no need to know why",
                   "no need to understand", "skip the derivation", "memoriz", "memoris")
    return wants and refuses


# ── Prerequisite weakness: forgot prereq + asks to go back / recap ──────────
def is_prereq_recap_request(text: str) -> bool:
    t = text.lower()
    forgot = _has(t, "don't even remember", "dont even remember", "don't remember what",
                  "dont remember what", "i don't remember", "i dont remember",
                  "i forgot", "i forget", "keep forgetting", "don't recall")
    goback = _has(t, "go back to", "recap", "review the basics", "review basics",
                  "remind me", "go back first", "quickly clarify", "go back",
                  "review first", "revise", "brush up")
    # explicit "how will i do current if i forgot prereq"
    blocks_current = forgot and _has(t, "how will i", "how do i", "how to do",
                                     "how can i", "before this", "before we", "first")
    return (forgot and goback) or blocks_current


# ── Ready-for-next mastery advance ──────────────────────────────────────────
def _mastery_cue(text: str) -> bool:
    t = text.lower()
    return _has(t, "i know this", "i know the", "i know how", "i got this",
                "i got it", "is easy", "so easy", "so simple", "is so simple",
                "is clear", "i'm good with", "im good with", "i am good with",
                "i'm good", "very well", "mostly i get it", "i understand this",
                "done with this", "are we done", "we are done", "i already know")


def is_advance_request(text: str):
    """Returns 'transfer' (wants harder problems), 'next' (topic shift), or None."""
    t = text.lower()
    if not _mastery_cue(t):
        return None
    if _has(t, "harder problem", "harder question", "tricky problem", "tricky question",
            "harder ones", "tougher", "the converse", "some problems", "do problems",
            "wanna practice", "want to practice", "challenging"):
        return "transfer"
    if _has(t, "next topic", "what's next", "whats next", "what is next",
            "go to next", "go to the next", "move to", "move on", "sum of n terms now",
            "elimination now", "next part", "next chapter", "ahead"):
        return "next"
    return None


# ── Stuck / calculation error / answer-not-matching ─────────────────────────
def is_stuck_calc_error(text: str) -> bool:
    t = text.lower()
    return _has(t, "not matching", "answer is still not matching", "still not matching",
                "calculation is always off", "calculation mistake", "calculation is off",
                "silly mistake", "silly mistakes", "it's all wrong", "its all wrong",
                "tried but it's all wrong", "what am i doing wrong", "doing wrong",
                "get different answer", "answer is diff", "answer is different",
                "keep making silly", "always make calculation", "i can't find it",
                "answer is not matching", "not coming right", "keep getting it wrong")


# ── self_correction noise ───────────────────────────────────────────────────
_SELF_CORRECTION_CUES = [
    "actually", "wait", "no wait", "i mean", "i meant", "sorry", "oh no",
    "i think i was wrong", "i made a mistake", "let me redo", "scratch that",
    "i changed my mind", "earlier i", "before i said", "i was saying",
    "i realise", "i realize", "now i think", "hmm no", "oops", "my bad",
    "i take that back", "correction",
    # revised-belief phrasings ("i thought X, not Y" / "i thought ... but now")
    "i thought", "i had thought", "thought it was", "thought that", "thought i",
    "i assumed", "i used to think", "i believed", "i was thinking it",
]


def has_self_correction_cue(text: str) -> bool:
    t = text.lower()
    return any(c in t for c in _SELF_CORRECTION_CUES)


# ── strong confusion cue (for high_confidence removal) ──────────────────────
def has_strong_confusion_cue(text: str) -> bool:
    t = text.lower()
    return _has(t, "blur", "hazy", "nothing is clear", "all a jumble",
                "don't understand anything", "didn't understand anything",
                "didnt understand anything", "i don't understand", "i dont understand",
                "so confusing", "totally confused", "completely lost", "i'm lost",
                "im lost", "not making sense", "doesn't make sense", "no idea",
                "don't get it", "dont get it", "can't understand")


def is_simplify_request(text: str) -> bool:
    """Asks for a simpler / kid-level rephrasing."""
    t = text.lower()
    return _has(t, "simpler words", "simpler way", "simple words", "simple language",
                "easy words", "easy language", "for a 5th grader", "for a kid",
                "for a small kid", "like for a child", "like im 5", "like i am 5",
                "dumb it down", "more simply", "in simple terms", "baby steps",
                "layman", "very basic terms", "explain simply", "rephrase it",
                "simple english", "simpler english")


def is_utility_bigpicture(text: str) -> bool:
    """Conceptual 'why/what's-the-point/big-picture' utility question (wants a
    verbal explanation, not a visual representation)."""
    t = text.lower()
    if (is_manipulative_request(t) or is_visual_translation_request(t)
            or is_numeric_example_request(t) or is_everyday_example_request(t)):
        return False
    return _has(t, "what is the point of learning", "whats the point of learning",
                "point of learning this", "what is this all leading",
                "what is this leading", "where is the main idea", "the big picture",
                "get the big picture", "dont get the big picture", "what is this for",
                "why do we even learn", "why are we even learning",
                "what is the main idea", "what is the use of learning")


def is_affect_dominant(text: str) -> bool:
    """Negative-affect / frustration / avoidance that calls for ENCOURAGE, not a
    factual EXPLAIN, even if a syllabus keyword is present."""
    t = text.lower()
    if is_give_up_self_doubt(t) or is_stuck_calc_error(t) or _overload_signal(t):
        return True
    return _has(t, "i hate", "i'll just skip", "i will just skip", "just skip this",
                "want to cry", "i can't do this", "i cant do this", "i just can't",
                "i just cant", "so frustrated", "fed up", "i hate this")


def has_explicit_dont_understand(text: str) -> bool:
    t = text.lower()
    return _has(t, "i don't understand", "i dont understand", "don't get this",
                "dont get this", "i don't get it", "i dont get it",
                "i just don't understand", "not understanding", "i can't understand")
