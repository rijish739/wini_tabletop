"""Cognitive-signal filler banks — slot-grammar data for all 13 banks.

Architecture reference: WINI_FILLER_ARCHITECTURE.md  (v1, 2026-06-23)

Each bank is a three-slot grammar:
    FILLER = LEAD (affect token) + BRIDGE (thinking move) + TEASE (action hint)

Deterministic routing picks the *bank*; stochastic sampling picks the
*fragments* within each slot. ~3-5 LEAD × 4-5 BRIDGE × 4-5 TEASE per bank
yields 48-125 unique utterances per bank — hundreds total across 13 banks.

Safety invariant:
  ✅  May reflect the student's affect / intent (what the classifier gave us).
  ❌  Must NEVER assert correctness — the answer does not exist yet.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Slot fragments per bank
# ---------------------------------------------------------------------------
# Each bank maps to {"lead": [...], "bridge": [...], "tease": [...]}
# Prosody is NOT encoded here — it is a separate lookup at synthesis time.
# ---------------------------------------------------------------------------

BANK_SLOTS: dict[str, dict[str, list[str]]] = {

    # ── EMPATHIC ──────────────────────────────────────────────────────────
    # Routes: anxiety, frustration, cognitive_overload, disengagement,
    #         low_confidence, prerequisite_weakness;
    #         frustration_risk >= 0.6 / cognitive_load >= 0.7 / confidence <= 0.25
    # Tone: slow, warm
    "empathic": {
        "lead": [
            "That's okay —",
            "Hey, no rush —",
            "Take your time —",
            "It's alright —",
            "No worries —",
        ],
        "bridge": [
            "let's take this slowly,",
            "let's work through this together,",
            "I'm right here with you,",
            "we'll figure this out,",
            "let's just ease into it,",
        ],
        "tease": [
            "one step at a time.",
            "we'll get there.",
            "I've got an idea that might help.",
            "let me find a gentler way in.",
            "so let's start small.",
        ],
    },

    # ── HINT ──────────────────────────────────────────────────────────────
    # Routes: request_hint, hint_dependency
    # Tone: light
    "hint": {
        "lead": [
            "Sure —",
            "Okay,",
            "Alright,",
            "Of course —",
            "You got it —",
        ],
        "bridge": [
            "here's a small nudge to get you going,",
            "let me give you a little clue,",
            "I'll point you in the right direction,",
            "let me set you up with something,",
            "here's a little push,",
        ],
        "tease": [
            "see if this helps.",
            "just enough to get the wheels turning.",
            "so you can take the next step.",
            "try this and see what clicks.",
            "a small piece of the puzzle coming.",
        ],
    },

    # ── EXAMPLE ───────────────────────────────────────────────────────────
    # Routes: example_request
    # Tone: engaged
    "example": {
        "lead": [
            "Good idea —",
            "Absolutely —",
            "Yeah —",
            "Sure thing —",
            "Nice call —",
        ],
        "bridge": [
            "let me line up an example for you,",
            "an example should make this click,",
            "let me put a concrete case together,",
            "I'll walk you through one,",
            "let me find something that fits,",
        ],
        "tease": [
            "this should make it clearer.",
            "so you can see it in action.",
            "here it comes now.",
            "something concrete to anchor on.",
            "let's see how it plays out.",
        ],
    },

    # ── REPRESENT ─────────────────────────────────────────────────────────
    # Routes: representation_shift, request_representation, diagrammatic,
    #         graphical, tabular, physical, verbal_analogy
    # Tone: curious
    "represent": {
        "lead": [
            "Okay —",
            "Good thinking —",
            "Interesting —",
            "Let's try that —",
            "Sure —",
        ],
        "bridge": [
            "let me show you this another way,",
            "let me switch up how we look at it,",
            "a different angle might help here,",
            "let me re-frame this for you,",
            "let me put it in a new light,",
        ],
        "tease": [
            "so it clicks.",
            "see if this view works better.",
            "this perspective might land.",
            "coming right up.",
            "let's try a fresh picture.",
        ],
    },

    # ── SIMPLIFY ──────────────────────────────────────────────────────────
    # Routes: simplification_request
    # Tone: calm
    "simplify": {
        "lead": [
            "No problem —",
            "Sure —",
            "Absolutely —",
            "Of course —",
            "Okay —",
        ],
        "bridge": [
            "let's strip it back to the basics,",
            "let me boil it down,",
            "let me take the complexity out,",
            "I'll keep this as simple as I can,",
            "let's peel away the layers,",
        ],
        "tease": [
            "the core idea is straightforward.",
            "just the essentials now.",
            "nice and clean.",
            "so it's easier to hold onto.",
            "one piece at a time.",
        ],
    },

    # ── SHIFT ─────────────────────────────────────────────────────────────
    # Routes: topic_shift
    # Tone: accommodating
    "shift": {
        "lead": [
            "Sure —",
            "Alright —",
            "Sounds good —",
            "Absolutely —",
            "Okay —",
        ],
        "bridge": [
            "let's switch over to that now,",
            "let me pivot to that for you,",
            "let's jump into the new topic,",
            "I'll bring that up for us,",
            "let's move to what you're asking about,",
        ],
        "tease": [
            "here we go.",
            "fresh start on this one.",
            "I'll get that set up.",
            "coming right up.",
            "let me get us there.",
        ],
    },

    # ── ADVANCE ───────────────────────────────────────────────────────────
    # Routes: ready_for_next, high_confidence, transfer_attempt, abstraction_attempt
    # Tone: energetic
    "advance": {
        "lead": [
            "Nice —",
            "Alright —",
            "Okay —",
            "Let's go —",
            "Here we go —",
        ],
        "bridge": [
            "you're ready, let's push ahead,",
            "looks like you've got that down,",
            "time to take it further,",
            "let's build on that momentum,",
            "let's raise the bar a bit,",
        ],
        "tease": [
            "something new coming your way.",
            "the next piece is interesting.",
            "let's see what's next.",
            "ready when you are.",
            "here comes the next challenge.",
        ],
    },

    # ── PROBE ─────────────────────────────────────────────────────────────
    # Routes: misconception_clue, recurring_error; misconception_probability >= 0.5
    # Tone: careful, curious
    "probe": {
        "lead": [
            "Hmm —",
            "Okay,",
            "Mm, alright,",
            "No rush —",
            "Right,",
        ],
        "bridge": [
            "let me check one thing with you,",
            "let me look at this carefully,",
            "I want to be sure here,",
            "there's something I'd like to poke at,",
            "let me trace through that with you,",
        ],
        "tease": [
            "one quick question coming.",
            "something here's worth a look.",
            "let's test it together.",
            "I think this will be useful.",
            "so we're on solid ground.",
        ],
    },

    # ── REFLECT ───────────────────────────────────────────────────────────
    # Routes: self_monitoring, self_correction, prerequisite_awareness
    # Tone: measured
    "reflect": {
        "lead": [
            "Good catch —",
            "Interesting —",
            "Okay —",
            "Right —",
            "Hmm, yeah —",
        ],
        "bridge": [
            "let's step back a second and look,",
            "let me think about what you noticed,",
            "that's worth pausing on,",
            "let me unpack that a bit,",
            "let's revisit that part,",
        ],
        "tease": [
            "there's something important here.",
            "so we can build from it.",
            "I think you're onto something.",
            "let's see where it leads.",
            "your instinct is worth following.",
        ],
    },

    # ── CONSIDER ──────────────────────────────────────────────────────────
    # Routes: skepticism, conflict
    # Tone: thoughtful
    "consider": {
        "lead": [
            "Fair point —",
            "Hmm,",
            "Interesting —",
            "Okay —",
            "Right —",
        ],
        "bridge": [
            "let me think that through with you,",
            "that's worth weighing carefully,",
            "I see where you're coming from,",
            "let me look at both sides,",
            "let's sit with that for a moment,",
        ],
        "tease": [
            "it's a good question to wrestle with.",
            "let me lay it out.",
            "so we can see the full picture.",
            "there's more here than meets the eye.",
            "let's dig into why.",
        ],
    },

    # ── QUESTION ──────────────────────────────────────────────────────────
    # Routes: question
    # Tone: warm
    "question": {
        "lead": [
            "Good question —",
            "Okay —",
            "Ah —",
            "Right —",
            "Mm-hmm —",
        ],
        "bridge": [
            "let me get to that for you,",
            "let me work through that,",
            "I want to answer that well,",
            "that deserves a clear answer,",
            "let me piece this together,",
        ],
        "tease": [
            "here's what I'm thinking.",
            "coming right up.",
            "I think you'll like this.",
            "so it really makes sense.",
            "let me lay it out clearly.",
        ],
    },

    # ── CURIOUS ───────────────────────────────────────────────────────────
    # Routes: curiosity (and confusion < 0.4)
    # Tone: bright
    "curious": {
        "lead": [
            "Ooh —",
            "Oh nice —",
            "I like that —",
            "Interesting —",
            "Great instinct —",
        ],
        "bridge": [
            "let's dig into that,",
            "that's a fun one to explore,",
            "let me pull that thread,",
            "I was hoping you'd ask that,",
            "there's a cool answer here,",
        ],
        "tease": [
            "this is going to be good.",
            "you're going to like this.",
            "let's see what we find.",
            "buckle up.",
            "now we're getting somewhere.",
        ],
    },

    # ── CLARIFY ───────────────────────────────────────────────────────────
    # Routes: confusion (>= 0.4)
    # Tone: reassuring
    "clarify": {
        "lead": [
            "Okay —",
            "Alright —",
            "Right —",
            "No worries —",
            "Fair enough —",
        ],
        "bridge": [
            "let's untangle this together,",
            "let me clear that up for you,",
            "I'll break this down,",
            "let me explain that differently,",
            "let me walk through it step by step,",
        ],
        "tease": [
            "it'll make more sense in a moment.",
            "so it really lands.",
            "I think I can make this click.",
            "let's get to the heart of it.",
            "nice and clear.",
        ],
    },

    # ── THINKING (default) ────────────────────────────────────────────────
    # Routes: algebraic, procedural_focus, answer_attempt, shortcut_seeking,
    #         environmental_feedback, or no fired label
    # Tone: neutral
    "thinking": {
        "lead": [
            "Okay —",
            "Right —",
            "Mm-hmm —",
            "Alright —",
            "Let's see —",
        ],
        "bridge": [
            "let me put this together for you,",
            "give me just a moment,",
            "let me think about the best way to say this,",
            "let me work through this,",
            "I'm lining up my thoughts,",
        ],
        "tease": [
            "here we go.",
            "something's coming.",
            "okay so…",
            "just a moment now.",
            "let me get this right.",
        ],
    },
}


# ---------------------------------------------------------------------------
# Composed reference samples — at least 10 per bank
# ---------------------------------------------------------------------------
# These are concrete examples showing how LEAD + BRIDGE + TEASE combine.
# Used for documentation, test fixtures, and TTS pre-synthesis seeding.
# ---------------------------------------------------------------------------

REFERENCE_SAMPLES: dict[str, list[str]] = {

    "empathic": [
        "That's okay — let's take this slowly, one step at a time.",
        "Hey, no rush — let's work through this together, we'll get there.",
        "Take your time — I'm right here with you, I've got an idea that might help.",
        "It's alright — we'll figure this out, let me find a gentler way in.",
        "No worries — let's just ease into it, so let's start small.",
        "That's okay — I'm right here with you, we'll get there.",
        "Hey, no rush — let's take this slowly, I've got an idea that might help.",
        "Take your time — we'll figure this out, one step at a time.",
        "It's alright — let's just ease into it, let me find a gentler way in.",
        "No worries — let's work through this together, so let's start small.",
        "That's okay — let's just ease into it, one step at a time.",
        "Take your time — let's take this slowly, we'll get there.",
    ],

    "hint": [
        "Sure — here's a small nudge to get you going, see if this helps.",
        "Okay, let me give you a little clue, just enough to get the wheels turning.",
        "Alright, I'll point you in the right direction, so you can take the next step.",
        "Of course — let me set you up with something, try this and see what clicks.",
        "You got it — here's a little push, a small piece of the puzzle coming.",
        "Sure — let me give you a little clue, see if this helps.",
        "Okay, here's a small nudge to get you going, so you can take the next step.",
        "Alright, let me set you up with something, just enough to get the wheels turning.",
        "Of course — I'll point you in the right direction, a small piece of the puzzle coming.",
        "You got it — here's a small nudge to get you going, try this and see what clicks.",
        "Sure — I'll point you in the right direction, just enough to get the wheels turning.",
        "Okay, here's a little push, see if this helps.",
    ],

    "example": [
        "Good idea — let me line up an example for you, this should make it clearer.",
        "Absolutely — an example should make this click, so you can see it in action.",
        "Yeah — let me put a concrete case together, here it comes now.",
        "Sure thing — I'll walk you through one, something concrete to anchor on.",
        "Nice call — let me find something that fits, let's see how it plays out.",
        "Good idea — I'll walk you through one, this should make it clearer.",
        "Absolutely — let me line up an example for you, something concrete to anchor on.",
        "Yeah — let me find something that fits, so you can see it in action.",
        "Sure thing — let me put a concrete case together, let's see how it plays out.",
        "Nice call — an example should make this click, here it comes now.",
        "Good idea — let me put a concrete case together, something concrete to anchor on.",
        "Absolutely — let me find something that fits, this should make it clearer.",
    ],

    "represent": [
        "Okay — let me show you this another way, so it clicks.",
        "Good thinking — let me switch up how we look at it, see if this view works better.",
        "Interesting — a different angle might help here, this perspective might land.",
        "Let's try that — let me re-frame this for you, coming right up.",
        "Sure — let me put it in a new light, let's try a fresh picture.",
        "Okay — let me re-frame this for you, so it clicks.",
        "Good thinking — a different angle might help here, let's try a fresh picture.",
        "Interesting — let me show you this another way, this perspective might land.",
        "Let's try that — let me put it in a new light, see if this view works better.",
        "Sure — let me switch up how we look at it, coming right up.",
        "Okay — a different angle might help here, so it clicks.",
        "Good thinking — let me show you this another way, coming right up.",
    ],

    "simplify": [
        "No problem — let's strip it back to the basics, the core idea is straightforward.",
        "Sure — let me boil it down, just the essentials now.",
        "Absolutely — let me take the complexity out, nice and clean.",
        "Of course — I'll keep this as simple as I can, so it's easier to hold onto.",
        "Okay — let's peel away the layers, one piece at a time.",
        "No problem — let me boil it down, the core idea is straightforward.",
        "Sure — let's strip it back to the basics, nice and clean.",
        "Absolutely — I'll keep this as simple as I can, just the essentials now.",
        "Of course — let's peel away the layers, so it's easier to hold onto.",
        "Okay — let me take the complexity out, one piece at a time.",
        "No problem — I'll keep this as simple as I can, the core idea is straightforward.",
        "Sure — let's peel away the layers, nice and clean.",
    ],

    "shift": [
        "Sure — let's switch over to that now, here we go.",
        "Alright — let me pivot to that for you, fresh start on this one.",
        "Sounds good — let's jump into the new topic, I'll get that set up.",
        "Absolutely — I'll bring that up for us, coming right up.",
        "Okay — let's move to what you're asking about, let me get us there.",
        "Sure — let's jump into the new topic, here we go.",
        "Alright — let's switch over to that now, coming right up.",
        "Sounds good — let me pivot to that for you, I'll get that set up.",
        "Absolutely — let's move to what you're asking about, fresh start on this one.",
        "Okay — I'll bring that up for us, let me get us there.",
        "Sure — I'll bring that up for us, here we go.",
        "Alright — let's move to what you're asking about, I'll get that set up.",
    ],

    "advance": [
        "Nice — you're ready, let's push ahead, something new coming your way.",
        "Alright — looks like you've got that down, the next piece is interesting.",
        "Okay — time to take it further, let's see what's next.",
        "Let's go — let's build on that momentum, ready when you are.",
        "Here we go — let's raise the bar a bit, here comes the next challenge.",
        "Nice — time to take it further, something new coming your way.",
        "Alright — let's build on that momentum, the next piece is interesting.",
        "Okay — you're ready, let's push ahead, here comes the next challenge.",
        "Let's go — let's raise the bar a bit, let's see what's next.",
        "Here we go — looks like you've got that down, ready when you are.",
        "Nice — let's build on that momentum, something new coming your way.",
        "Alright — let's raise the bar a bit, the next piece is interesting.",
    ],

    "probe": [
        "Hmm — let me check one thing with you, one quick question coming.",
        "Okay, let me look at this carefully, something here's worth a look.",
        "Mm, alright, I want to be sure here, let's test it together.",
        "No rush — there's something I'd like to poke at, I think this will be useful.",
        "Right, let me trace through that with you, so we're on solid ground.",
        "Hmm — I want to be sure here, one quick question coming.",
        "Okay, let me check one thing with you, let's test it together.",
        "Mm, alright, let me look at this carefully, so we're on solid ground.",
        "No rush — let me trace through that with you, something here's worth a look.",
        "Right, there's something I'd like to poke at, I think this will be useful.",
        "Hmm — let me look at this carefully, let's test it together.",
        "Okay, there's something I'd like to poke at, one quick question coming.",
    ],

    "reflect": [
        "Good catch — let's step back a second and look, there's something important here.",
        "Interesting — let me think about what you noticed, so we can build from it.",
        "Okay — that's worth pausing on, I think you're onto something.",
        "Right — let me unpack that a bit, let's see where it leads.",
        "Hmm, yeah — let's revisit that part, your instinct is worth following.",
        "Good catch — let me unpack that a bit, there's something important here.",
        "Interesting — let's step back a second and look, let's see where it leads.",
        "Okay — let me think about what you noticed, I think you're onto something.",
        "Right — let's revisit that part, so we can build from it.",
        "Hmm, yeah — that's worth pausing on, your instinct is worth following.",
        "Good catch — that's worth pausing on, let's see where it leads.",
        "Interesting — let's revisit that part, there's something important here.",
    ],

    "consider": [
        "Fair point — let me think that through with you, it's a good question to wrestle with.",
        "Hmm, that's worth weighing carefully, let me lay it out.",
        "Interesting — I see where you're coming from, so we can see the full picture.",
        "Okay — let me look at both sides, there's more here than meets the eye.",
        "Right — let's sit with that for a moment, let's dig into why.",
        "Fair point — I see where you're coming from, let me lay it out.",
        "Hmm, let me think that through with you, so we can see the full picture.",
        "Interesting — let me look at both sides, let's dig into why.",
        "Okay — that's worth weighing carefully, it's a good question to wrestle with.",
        "Right — let's sit with that for a moment, there's more here than meets the eye.",
        "Fair point — let me look at both sides, it's a good question to wrestle with.",
        "Hmm, let's sit with that for a moment, let me lay it out.",
    ],

    "question": [
        "Good question — let me get to that for you, here's what I'm thinking.",
        "Okay — let me work through that, coming right up.",
        "Ah — I want to answer that well, I think you'll like this.",
        "Right — that deserves a clear answer, so it really makes sense.",
        "Mm-hmm — let me piece this together, let me lay it out clearly.",
        "Good question — I want to answer that well, here's what I'm thinking.",
        "Okay — let me get to that for you, so it really makes sense.",
        "Ah — let me work through that, let me lay it out clearly.",
        "Right — let me piece this together, I think you'll like this.",
        "Mm-hmm — that deserves a clear answer, coming right up.",
        "Good question — let me piece this together, here's what I'm thinking.",
        "Okay — I want to answer that well, coming right up.",
    ],

    "curious": [
        "Ooh — let's dig into that, this is going to be good.",
        "Oh nice — that's a fun one to explore, you're going to like this.",
        "I like that — let me pull that thread, let's see what we find.",
        "Interesting — I was hoping you'd ask that, buckle up.",
        "Great instinct — there's a cool answer here, now we're getting somewhere.",
        "Ooh — I was hoping you'd ask that, this is going to be good.",
        "Oh nice — let's dig into that, now we're getting somewhere.",
        "I like that — there's a cool answer here, let's see what we find.",
        "Interesting — let me pull that thread, you're going to like this.",
        "Great instinct — that's a fun one to explore, buckle up.",
        "Ooh — let me pull that thread, this is going to be good.",
        "Oh nice — there's a cool answer here, you're going to like this.",
    ],

    "clarify": [
        "Okay — let's untangle this together, it'll make more sense in a moment.",
        "Alright — let me clear that up for you, so it really lands.",
        "Right — I'll break this down, I think I can make this click.",
        "No worries — let me explain that differently, let's get to the heart of it.",
        "Fair enough — let me walk through it step by step, nice and clear.",
        "Okay — let me explain that differently, it'll make more sense in a moment.",
        "Alright — let's untangle this together, I think I can make this click.",
        "Right — let me clear that up for you, let's get to the heart of it.",
        "No worries — let me walk through it step by step, so it really lands.",
        "Fair enough — I'll break this down, nice and clear.",
        "Okay — I'll break this down, it'll make more sense in a moment.",
        "Alright — let me walk through it step by step, I think I can make this click.",
    ],

    "thinking": [
        "Okay — let me put this together for you, here we go.",
        "Right — give me just a moment, something's coming.",
        "Mm-hmm — let me think about the best way to say this, okay so…",
        "Alright — let me work through this, just a moment now.",
        "Let's see — I'm lining up my thoughts, let me get this right.",
        "Okay — let me work through this, here we go.",
        "Right — let me put this together for you, let me get this right.",
        "Mm-hmm — give me just a moment, okay so…",
        "Alright — I'm lining up my thoughts, something's coming.",
        "Let's see — let me think about the best way to say this, just a moment now.",
        "Okay — I'm lining up my thoughts, here we go.",
        "Right — let me think about the best way to say this, something's coming.",
    ],
}


# ---------------------------------------------------------------------------
# Composition helpers
# ---------------------------------------------------------------------------

def compose(bank: str, exclude_last_n: int = 3,
            _history: dict[str, list[str]] | None = None) -> str:
    """Assemble a filler from slot fragments with anti-repeat.

    Args:
        bank: Bank name (key in BANK_SLOTS).
        exclude_last_n: Number of recent selections per slot to suppress.
        _history: Optional mutable dict tracking per-bank ring buffers.
                  Caller should persist this across turns for anti-repeat.

    Returns:
        A composed filler string (LEAD + BRIDGE + TEASE).
    """
    import random

    if _history is None:
        _history = {}

    slots = BANK_SLOTS[bank]
    parts: list[str] = []

    for slot_name in ("lead", "bridge", "tease"):
        key = f"{bank}:{slot_name}"
        recent = _history.get(key, [])
        options = slots[slot_name]
        # filter out recently used
        available = [o for o in options if o not in recent[-exclude_last_n:]]
        if not available:
            available = options  # fallback: all options if everything is recent
        choice = random.choice(available)
        parts.append(choice)
        # update ring buffer
        recent.append(choice)
        if len(recent) > exclude_last_n:
            recent = recent[-exclude_last_n:]
        _history[key] = recent

    return f"{parts[0]} {parts[1]} {parts[2]}"


# ---------------------------------------------------------------------------
# Deterministic bank routing (WINI_FILLER_ARCHITECTURE.md §5)
# ---------------------------------------------------------------------------
# A priority cascade over the fired MiniLM labels + the section-6.2 aggregates.
# First match wins. Priority encodes pedagogy: emotional safety first, then
# explicit requests, then cognitive content, then the neutral default.
# ---------------------------------------------------------------------------

_EMPATHIC = {"frustration", "anxiety", "cognitive_overload", "disengagement",
             "prerequisite_weakness", "low_confidence"}
_HINT = {"request_hint", "hint_dependency"}
_REPRESENT = {"request_representation", "representation_shift", "diagrammatic",
              "graphical", "tabular", "physical", "verbal_analogy"}
_PROBE = {"misconception_clue", "recurring_error"}
_REFLECT = {"self_monitoring", "self_correction", "prerequisite_awareness"}
_ADVANCE = {"ready_for_next", "high_confidence", "transfer_attempt", "abstraction_attempt"}
_CONSIDER = {"skepticism", "conflict"}


def route_bank(signals, cognitive_update) -> str:
    """Map fired signals + cognitive aggregates to a filler bank (deterministic).

    Args:
        signals: iterable of fired MiniLM label strings (analysis["signals"]).
        cognitive_update: dict of section-6.2 aggregates 0..1 (analysis["cognitive_update"]).
    Returns:
        A bank name (key in BANK_SLOTS); always valid — falls through to "thinking".
    """
    sig = set(signals or [])
    cu = cognitive_update or {}
    def f(k, default=0.0):  # safe float read; absent aggregate => neutral default
        try:
            return float(cu.get(k, default))
        except (TypeError, ValueError):
            return default

    # ── Layer A · AFFECT OVERRIDE ─────────────────────────────────────────
    # confidence defaults to 1.0 (high): it is the one inverted aggregate, so an
    # *absent* confidence must not read as "rock-bottom" and force empathic.
    if (f("frustration_risk") >= 0.6 or f("cognitive_load") >= 0.7
            or (sig & _EMPATHIC) or f("confidence", 1.0) <= 0.25):
        return "empathic"

    # ── Layer B · EXPLICIT REQUEST ────────────────────────────────────────
    if sig & _HINT:
        return "hint"
    if "example_request" in sig:
        return "example"
    if sig & _REPRESENT:
        return "represent"
    if "simplification_request" in sig:
        return "simplify"
    if "topic_shift" in sig:
        return "shift"

    # ── Layer C · COGNITIVE CONTENT ───────────────────────────────────────
    if f("misconception_probability") >= 0.5 or (sig & _PROBE):
        return "probe"
    if sig & _REFLECT:
        return "reflect"
    if sig & _ADVANCE:
        return "advance"
    if sig & _CONSIDER:
        return "consider"
    if "question" in sig:
        return "question"
    if f("curiosity") >= 0.6 and f("confusion") < 0.4:
        return "curious"
    if f("confusion") >= 0.4:
        return "clarify"

    # ── Layer D · DEFAULT ─────────────────────────────────────────────────
    return "thinking"


class FillerComposer:
    """Stateful picker: route a bank from the analysis, compose a filler with
    per-bank/per-slot anti-repeat carried across turns. One instance per session."""

    def __init__(self, exclude_last_n: int = 3) -> None:
        self.exclude_last_n = exclude_last_n
        self._history: dict[str, list[str]] = {}

    def pick(self, analysis) -> tuple[str, str]:
        """analysis: the analyzer dict (or None). Returns (bank, composed_phrase)."""
        analysis = analysis or {}
        bank = route_bank(analysis.get("signals"), analysis.get("cognitive_update"))
        phrase = compose(bank, self.exclude_last_n, self._history)
        return bank, phrase


def get_all_banks() -> list[str]:
    """Return sorted list of all bank names."""
    return sorted(BANK_SLOTS.keys())


def bank_capacity(bank: str) -> int:
    """Return the number of unique compositions possible for a bank."""
    s = BANK_SLOTS[bank]
    return len(s["lead"]) * len(s["bridge"]) * len(s["tease"])


def total_capacity() -> int:
    """Return total unique compositions across all banks."""
    return sum(bank_capacity(b) for b in BANK_SLOTS)
