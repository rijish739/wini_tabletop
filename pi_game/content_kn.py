"""Kannada swaragalu (ಸ್ವರಗಳು) lesson content — the vowels of the varnamale.

The Kannada twin of ``content.py``. Same contract, same flat-art aesthetic, same
"data only, never model-generated" rule (§14, §19): this module is hand-curated.
``gen_assets.py --lang kn`` projects it into ``assets/kn/letters/<slug>/`` and the
Kannada voice in ``speech.py`` speaks the lines; nothing at runtime reads this
file directly.

Two things differ from the English module and drive the whole design:

* **An akshara is not an ASCII letter.** Each vowel is keyed by an ASCII *slug*
  ("a", "aa", "i"…) so it can be a directory name, a socket field and a log token
  without ever putting Kannada bytes on those paths — exactly the trap the English
  module never had to think about. The akshara itself lives in ``char`` and is
  what the child sees (rendered to PNG) and hears (spoken by the Kannada voice).
* **The object word must genuinely begin with the akshara in Kannada.** Apple
  (ಸೇಬು) begins with ಸ, not ಅ — so the English art can only be reused when a real
  Kannada word for that object starts with the right vowel. Four do (palace→House,
  date-palm→Tree, leaf→Leaf, ice-cream→Ice-cream); the other nine carry new art.

Coverage is the 13 core swaragalu (ಅ–ಔ). The two yogavaahakalu (ಅಂ ಅಃ) are
recited with them but have no word-initial examples, so they are deferred to a
later pass rather than faked. Vyanjanagalu (ವ್ಯಂಜನಗಳು) are the planned phase two.
"""

from __future__ import annotations

# Shape helpers and the muted palette are shared with the English module — one
# aesthetic across both products (§2.5 Consistency). The four reused art recipes
# are pulled straight from there by reference (gen_assets only ever reads them).
from pi_game.content import (
    BG, INK, INK_SOFT, BLUE, GREEN, ORANGE, ROSE, YELLOW, BROWN, CREAM, GREY,
    PLUM, PLUM_DARK, ERASE,
    ell, rect, poly, lens, line, arc, pie,
    LETTERS as EN_LETTERS,
)

# ---- New art recipes (nine objects with no reusable English twin) ----------
# Authored on the same 420x420 canvas, origin top-left, same flat rules: pastel
# fills, no gradients, no outline heavier than 6 px.

_ELEPHANT = [                                   # ಆನೆ  (aane)
    ell(150, 150, 350, 300, GREY),                       # body
    rect(150, 250, 185, 350, GREY, r=10),                # legs
    rect(210, 255, 245, 350, GREY, r=10),
    rect(285, 255, 320, 350, GREY, r=10),
    ell(70, 130, 210, 280, GREY),                        # head
    ell(60, 150, 130, 250, "#B7B2A6"),                   # ear (a touch darker)
    rect(78, 210, 112, 360, GREY, r=16),                 # trunk
    ell(150, 180, 172, 204, INK),                        # eye
]

_MOUSE = [                                       # ಇಲಿ  (ili)
    ell(120, 190, 320, 320, GREY),                       # body
    ell(250, 150, 350, 250, GREY),                       # head
    ell(255, 120, 305, 175, "#B7B2A6"),                  # ears
    ell(300, 120, 350, 175, "#B7B2A6"),
    ell(315, 195, 335, 215, INK),                        # eye
    ell(340, 210, 360, 230, ROSE),                       # nose
    arc(60, 220, 150, 320, 200, 20, INK_SOFT, w=7),      # curling tail
]

_RING = [                                        # ಉಂಗುರ  (ungura)
    ell(120, 150, 300, 330, YELLOW),                     # gold band
    ell(168, 198, 252, 282, ERASE),                      # punch the hole
    poly([(210, 70), (250, 120), (210, 165), (170, 120)], BLUE),  # gemstone
]

_MEAL = [                                        # ಊಟ  (oota) — a served plate
    ell(70, 200, 350, 320, CREAM),                       # plate
    ell(110, 210, 310, 290, "#E6DCC6"),                  # inner rim
    ell(150, 150, 290, 250, CREAM),                      # rice mound
    ell(175, 185, 245, 235, YELLOW),                     # a little dal
    ell(120, 205, 175, 250, ORANGE),                     # curry
    ell(255, 205, 305, 250, GREEN),                      # a vegetable
]

_SAGE = [                                        # ಋಷಿ  (rushi)
    ell(135, 80, 285, 250, CREAM),                       # face
    poly([(135, 170), (285, 170), (255, 330), (165, 330)], "#DDD6C6"),  # beard
    ell(150, 145, 172, 167, INK),                        # eyes
    ell(248, 145, 270, 167, INK),
    line([(205, 110), (205, 145)], ROSE, w=8),           # tilak
    arc(170, 175, 250, 215, 20, 160, INK_SOFT, w=6),     # calm smile
]

_LADDER = [                                      # ಏಣಿ  (eeni)
    rect(140, 70, 168, 360, BROWN, r=8),                 # rails
    rect(252, 70, 280, 360, BROWN, r=8),
    rect(150, 120, 270, 140, BROWN, r=6),                # rungs
    rect(150, 185, 270, 205, BROWN, r=6),
    rect(150, 250, 270, 270, BROWN, r=6),
    rect(150, 315, 270, 335, BROWN, r=6),
]

_CAMEL = [                                       # ಒಂಟೆ  (onte)
    ell(110, 200, 330, 300, "#D8B98C"),                  # body
    arc(150, 150, 300, 260, 180, 360, "#D8B98C", w=44),  # hump
    rect(115, 270, 145, 355, "#D8B98C", r=8),            # legs
    rect(160, 275, 190, 355, "#D8B98C", r=8),
    rect(255, 275, 285, 355, "#D8B98C", r=8),
    rect(295, 275, 325, 355, "#D8B98C", r=8),
    rect(300, 90, 330, 220, "#D8B98C", r=14),            # neck
    ell(300, 70, 370, 140, "#D8B98C"),                   # head
    ell(345, 95, 363, 113, INK),                         # eye
]

_EARRING = [                                     # ಓಲೆ  (oale)
    arc(150, 90, 270, 210, 0, 360, YELLOW, w=16),        # hoop
    ell(198, 205, 222, 229, YELLOW),                     # bead
    lens(190, 225, 230, 330, ROSE),                      # teardrop pendant
    ell(203, 250, 217, 275, "#F0C0BC"),                  # highlight
]

_MEDICINE = [                                    # ಔಷಧ  (aushadha) — a bottle
    rect(150, 150, 270, 340, BLUE, r=18),                # bottle body
    rect(168, 110, 252, 158, CREAM, r=8),                # cap
    rect(150, 175, 270, 215, CREAM, r=6),                # label band
    rect(203, 240, 217, 300, ROSE),                      # cross (vertical)
    rect(188, 262, 232, 278, ROSE),                      # cross (horizontal)
]


# ---- The 13 swaragalu ------------------------------------------------------
# `say` is what the Kannada voice is asked to pronounce for the bare vowel — the
# akshara itself reads correctly ("ಅ" -> a). `word` MUST start with `char` in
# Kannada. `art` is either one of the nine recipes above or a reused English one.

LETTERS: dict[str, dict] = {
    "a":  {"char": "ಅ", "say": "ಅ", "word": "ಅರಮನೆ", "art": EN_LETTERS["H"]["art"]},   # palace
    "aa": {"char": "ಆ", "say": "ಆ", "word": "ಆನೆ",   "art": _ELEPHANT},                # elephant
    "i":  {"char": "ಇ", "say": "ಇ", "word": "ಇಲಿ",   "art": _MOUSE},                   # mouse
    "ii": {"char": "ಈ", "say": "ಈ", "word": "ಈಚಲು",  "art": EN_LETTERS["T"]["art"]},   # date palm
    "u":  {"char": "ಉ", "say": "ಉ", "word": "ಉಂಗುರ", "art": _RING},                    # ring
    "uu": {"char": "ಊ", "say": "ಊ", "word": "ಊಟ",    "art": _MEAL},                    # meal
    "ru": {"char": "ಋ", "say": "ಋ", "word": "ಋಷಿ",   "art": _SAGE},                    # sage
    "e":  {"char": "ಎ", "say": "ಎ", "word": "ಎಲೆ",   "art": EN_LETTERS["L"]["art"]},   # leaf
    "ee": {"char": "ಏ", "say": "ಏ", "word": "ಏಣಿ",   "art": _LADDER},                  # ladder
    "ai": {"char": "ಐ", "say": "ಐ", "word": "ಐಸ್ ಕ್ರೀಂ", "art": EN_LETTERS["I"]["art"]},  # ice cream
    "o":  {"char": "ಒ", "say": "ಒ", "word": "ಒಂಟೆ",  "art": _CAMEL},                   # camel
    "oo": {"char": "ಓ", "say": "ಓ", "word": "ಓಲೆ",   "art": _EARRING},                 # earring
    "au": {"char": "ಔ", "say": "ಔ", "word": "ಔಷಧ",   "art": _MEDICINE},                # medicine
}

# Canonical recitation order of the swaragalu — deterministic, no branching (§12).
ORDER = ["a", "aa", "i", "ii", "u", "uu", "ru", "e", "ee", "ai", "o", "oo", "au"]

# The two objects a robot could plausibly eat (ಊಟ meal, ಐಸ್‌ಕ್ರೀಂ ice cream); the
# rest are handed over, exactly as in the English module. Keyed by slug.
EDIBLE = {"uu", "ai"}


def touch_choices(slug: str) -> list[str]:
    """Four tiles for the touch stage: this vowel plus the next three, wrapping.

    Same deterministic rule as the English board (§12 "No random branching"), so a
    child meets the same four aksharas for a given vowel every time. Sorted by the
    canonical order rather than ASCII, so the board reads left-to-right the way the
    varnamale is recited.
    """
    i = ORDER.index(slug)
    picks = [ORDER[(i + k) % len(ORDER)] for k in (0, 1, 2, 3)]
    return sorted(picks, key=ORDER.index)


def lesson_dict(slug: str) -> dict:
    """The §14 lesson record for one vowel. Data only, no logic.

    `letter` stays the ASCII slug (the id used for asset paths, the socket and
    logs); `char` is the akshara the child sees and hears.
    """
    e = LETTERS[slug]
    return {
        "letter": slug,
        "char": e["char"],
        "phoneme": e["say"],
        "say": e["say"],
        "objects": [{"name": e["word"], "image": "object.png"}],
        "choices": touch_choices(slug),
        "mini_game": "feed" if slug in EDIBLE else "give",
        "edible": slug in EDIBLE,
        "lines": lesson_lines(slug),
    }


def lesson_lines(slug: str) -> dict[str, str]:
    """Every spoken line of the lesson in Kannada, keyed by stage.

    Kept here (not in the server) so the TTS pre-synthesis step and the runtime
    read exactly the same strings — a mismatch is a silent cache miss and a cloud
    round-trip mid-lesson. Wording follows §2.3: Wini is always the one being
    helped and never judges. Warm, unhurried, no failure state.
    """
    e = LETTERS[slug]
    char = e["char"]
    say = e["say"]
    word = e["word"]

    if slug in EDIBLE:
        activity_ask = f"ನನಗೆ ಹಸಿವಾಗಿದೆ. {word} ಕೊಡಬಲ್ಲೆಯಾ?"
        activity_ok = "ರುಚಿ! ಧನ್ಯವಾದ."
    else:
        activity_ask = f"{word} ನನಗೆ ತಂದುಕೊಡಬಲ್ಲೆಯಾ?"
        activity_ok = "ಧನ್ಯವಾದ! ನನಗೆ ಇಷ್ಟವಾಯಿತು."

    return {
        "intro":        f"ನಮಸ್ಕಾರ. ಇಂದು ನಾವು {char} ಅಕ್ಷರವನ್ನು ಭೇಟಿಯಾಗೋಣ.",
        "listen":       f"{char} ಹೀಗೆ ಶಬ್ದ ಮಾಡುತ್ತದೆ: {say}.",
        "touch_ask":    f"{char} ಅಕ್ಷರವನ್ನು ಮುಟ್ಟಬಲ್ಲೆಯಾ?",
        "touch_ok":     "ಧನ್ಯವಾದ! ನಾನು ಅದನ್ನು ಕಂಡುಕೊಂಡೆ.",
        "touch_retry":  "ಪುನಃ ಒಟ್ಟಿಗೆ ನೋಡೋಣ.",
        "repeat_ask":   f"{say} ಎಂದು ಹೇಳಬಲ್ಲೆಯಾ?",
        "repeat_ok":    "ತುಂಬಾ ಚೆನ್ನಾಗಿತ್ತು. ಧನ್ಯವಾದ.",
        "repeat_retry": f"ಒಟ್ಟಿಗೆ ಪ್ರಯತ್ನಿಸೋಣ. {say}.",
        # Said when neither attempt matched: honest, warm, still no failure state.
        # Deliberately NOT the "lovely" line — praising a sound never heard is what
        # made the English feedback feel untrustworthy (see content.py).
        "repeat_move_on": f"ಪ್ರಯತ್ನಿಸಿದ್ದಕ್ಕೆ ಧನ್ಯವಾದ. ನಾವು ಇನ್ನೊಮ್ಮೆ {say} ಎಂದು ಹೇಳೋಣ.",
        "assoc":        f"{word} — {char} ಇಂದ ಪ್ರಾರಂಭವಾಗುತ್ತದೆ.",
        "activity_ask": activity_ask,
        "activity_ok":  activity_ok,
        "complete":     f"ಇಂದು ನಾವು {char} ಕಲಿತೆವು. {char} — {word}.",
    }
