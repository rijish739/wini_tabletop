"""Alphabet lesson content — the single source of what each letter teaches.

Curated by hand, never model-generated: §19 lists "AI-generated lesson content"
as an explicit non-goal, and §14 requires lessons to carry data only. This module
is that data. `gen_assets.py` projects it into assets/letters/<L>/lesson.json plus
the PNG art; nothing at runtime reads this file.

Each entry carries:
  phoneme      the letter's sound as the child should hear it ("ah")
  say          how the robot pronounces that sound aloud (TTS-friendly spelling)
  word         the object word ("Apple")
  art          a flat-shape recipe drawn by gen_assets.draw_art()

The art recipes are deliberately primitive: pastel fills, no gradients, no
outlines heavier than 6 px, so every object reads the same way at a glance
(§2.5 Consistency). Coordinates are on a 420x420 canvas, origin top-left.
"""

from __future__ import annotations

# ---- Palette (§9 Color Palette). Muted only — never pure red/green or neon. --
BG        = "#F8F5EF"   # warm white page
INK       = "#3A3730"   # primary text
INK_SOFT  = "#7A7466"   # secondary text
BLUE      = "#A8C8E8"   # primary   — soft blue
GREEN     = "#B8DDB0"   # accent    — pastel green
ORANGE    = "#E8B583"   # highlight — muted orange
ROSE      = "#E8B0AC"   # muted rose (stands in for red, never #F00)
YELLOW    = "#EFD9A0"
BROWN     = "#B79B7C"
CREAM     = "#EFE7D6"
GREY      = "#C9C4B8"
PLUM      = "#C9AECB"
PLUM_DARK = "#A98BAC"   # separates overlapping grapes without an outline color

# Not a color: a primitive painted with ERASE punches transparency out of the
# canvas instead of filling it. Needed for shapes that are defined by what is
# taken away (the moon's crescent) — filling those with the page color would
# leave an opaque bite that goes wrong the moment the art moves (the letter M
# object is dragged across the robot's face in the feed activity).
ERASE     = "ERASE"

# ---- Shape helpers ---------------------------------------------------------
# Each primitive is a dict consumed by gen_assets.draw_art(). Keeping them as
# plain data (not lambdas) means a lesson stays serialisable end to end.


def ell(x0, y0, x1, y1, fill):
    return {"t": "ellipse", "xy": [x0, y0, x1, y1], "fill": fill}


def rect(x0, y0, x1, y1, fill, r=0):
    return {"t": "rect", "xy": [x0, y0, x1, y1], "fill": fill, "r": r}


def poly(pts, fill):
    return {"t": "poly", "pts": pts, "fill": fill}


def lens(x0, y0, x1, y1, fill, outline=None):
    """A pointed oval — a true leaf/seam silhouette, never a diamond."""
    d = {"t": "lens", "xy": [x0, y0, x1, y1], "fill": fill}
    if outline:
        d["outline"] = outline
    return d


def line(pts, fill, w=8):
    return {"t": "line", "pts": pts, "fill": fill, "w": w}


def arc(x0, y0, x1, y1, start, end, fill, w=10):
    return {"t": "arc", "xy": [x0, y0, x1, y1], "start": start, "end": end,
            "fill": fill, "w": w}


def pie(x0, y0, x1, y1, start, end, fill):
    return {"t": "pie", "xy": [x0, y0, x1, y1], "start": start, "end": end,
            "fill": fill}


# ---- The 26 lessons --------------------------------------------------------
# `say` is what Cloud TTS is asked to pronounce for the bare phoneme. Plain
# letters ("aah") read far better than IPA, which the voice spells out.

LETTERS: dict[str, dict] = {
    "A": {
        "phoneme": "ah", "say": "aah", "word": "Apple",
        "art": [
            ell(90, 120, 330, 350, ROSE),                       # body
            rect(198, 78, 222, 140, BROWN, r=10),               # stem
            poly([(222, 100), (300, 70), (270, 128)], GREEN),   # leaf
        ],
    },
    "B": {
        "phoneme": "buh", "say": "buh", "word": "Ball",
        "art": [
            ell(80, 80, 340, 340, BLUE),
            # A vertical seam, not two arcs: paired arcs read as eyes + a mouth,
            # which put a second smiling face right next to the Cat.
            lens(150, 80, 270, 340, CREAM),
            ell(120, 118, 165, 163, "#C7DCEF"),               # soft highlight
        ],
    },
    "C": {
        "phoneme": "kuh", "say": "kuh", "word": "Cat",
        "art": [
            poly([(120, 140), (150, 60), (200, 130)], ORANGE),   # left ear
            poly([(300, 140), (270, 60), (220, 130)], ORANGE),   # right ear
            ell(100, 110, 320, 320, ORANGE),                     # head
            ell(155, 185, 180, 220, INK),                        # eyes
            ell(240, 185, 265, 220, INK),
            ell(198, 235, 222, 253, ROSE),                       # nose
            line([(60, 240), (150, 250)], INK_SOFT, w=5),        # whiskers
            line([(60, 275), (150, 268)], INK_SOFT, w=5),
            line([(360, 240), (270, 250)], INK_SOFT, w=5),
            line([(360, 275), (270, 268)], INK_SOFT, w=5),
        ],
    },
    "D": {
        "phoneme": "duh", "say": "duh", "word": "Drum",
        "art": [
            rect(110, 150, 310, 300, CREAM, r=18),
            rect(110, 150, 310, 178, ORANGE, r=14),
            rect(110, 272, 310, 300, ORANGE, r=14),
            line([(140, 178), (180, 272)], BLUE, w=7),
            line([(210, 178), (210, 272)], BLUE, w=7),
            line([(280, 178), (240, 272)], BLUE, w=7),
            line([(120, 130), (190, 60)], BROWN, w=10),          # sticks
            line([(300, 130), (230, 60)], BROWN, w=10),
            ell(178, 48, 202, 72, BROWN),
            ell(218, 48, 242, 72, BROWN),
        ],
    },
    "E": {
        "phoneme": "eh", "say": "eh", "word": "Egg",
        "art": [
            ell(120, 90, 300, 340, CREAM),
            ell(158, 148, 198, 198, "#F8F3E8"),   # highlight, not a yolk — an
                                                  # intact egg showing its yolk
                                                  # confuses more than it helps
        ],
    },
    "F": {
        "phoneme": "fuh", "say": "fuh", "word": "Fish",
        "art": [
            ell(90, 150, 300, 290, BLUE),                        # body
            poly([(290, 220), (370, 160), (370, 280)], BLUE),    # tail
            ell(130, 195, 152, 217, INK),                        # eye
            arc(150, 180, 260, 260, 20, 160, CREAM, w=8),        # fin
        ],
    },
    "G": {
        "phoneme": "guh", "say": "guh", "word": "Grapes",
        "art": [
            rect(198, 70, 216, 130, BROWN, r=8),
            poly([(216, 92), (285, 68), (258, 118)], GREEN),
            # Each grape carries a darker rim: without it the cluster fuses into
            # one lumpy blob and stops reading as grapes at all.
            {"t": "ellipse", "xy": [162, 132, 238, 208], "fill": PLUM, "outline": PLUM_DARK, "ow": 4},
            {"t": "ellipse", "xy": [116, 178, 188, 250], "fill": PLUM, "outline": PLUM_DARK, "ow": 4},
            {"t": "ellipse", "xy": [212, 178, 284, 250], "fill": PLUM, "outline": PLUM_DARK, "ow": 4},
            {"t": "ellipse", "xy": [164, 224, 236, 296], "fill": PLUM, "outline": PLUM_DARK, "ow": 4},
            {"t": "ellipse", "xy": [208, 264, 272, 328], "fill": PLUM, "outline": PLUM_DARK, "ow": 4},
            {"t": "ellipse", "xy": [128, 264, 192, 328], "fill": PLUM, "outline": PLUM_DARK, "ow": 4},
        ],
    },
    "H": {
        "phoneme": "huh", "say": "huh", "word": "House",
        "art": [
            poly([(200, 70), (350, 190), (50, 190)], ROSE),      # roof
            rect(85, 190, 315, 340, CREAM, r=8),
            rect(170, 250, 230, 340, BROWN, r=6),                # door
            rect(105, 215, 155, 265, BLUE, r=6),                 # windows
            rect(245, 215, 295, 265, BLUE, r=6),
        ],
    },
    "I": {
        "phoneme": "ih", "say": "ih", "word": "Ice cream",
        "art": [
            poly([(140, 210), (280, 210), (210, 370)], ORANGE),  # cone
            ell(140, 130, 220, 215, CREAM),
            ell(200, 130, 280, 215, ROSE),
            ell(170, 80, 250, 165, GREEN),
        ],
    },
    "J": {
        "phoneme": "juh", "say": "juh", "word": "Jug",
        "art": [
            rect(120, 130, 280, 340, BLUE, r=26),
            poly([(255, 150), (330, 130), (330, 165), (270, 190)], BLUE),
            arc(255, 190, 350, 300, 280, 90, BLUE, w=18),        # handle
            rect(120, 130, 280, 165, CREAM, r=16),
        ],
    },
    "K": {
        "phoneme": "kuh", "say": "kuh", "word": "Kite",
        "art": [
            # Blue, not green: K and L sit two lessons apart and a green diamond
            # beside a green leaf is the one confusion this module must not ship.
            poly([(210, 60), (310, 175), (210, 300), (110, 175)], BLUE),
            line([(210, 60), (210, 300)], CREAM, w=5),
            line([(110, 175), (310, 175)], CREAM, w=5),
            line([(210, 300), (200, 350), (240, 380)], BROWN, w=6),
            poly([(190, 336), (222, 344), (196, 362)], ORANGE),
        ],
    },
    "L": {
        "phoneme": "luh", "say": "luh", "word": "Leaf",
        "art": [
            lens(110, 55, 310, 330, GREEN),      # pointed at both ends, not a diamond
            line([(210, 70), (210, 318)], CREAM, w=6),
            line([(210, 150), (155, 188)], CREAM, w=4),
            line([(210, 150), (265, 188)], CREAM, w=4),
            line([(210, 225), (162, 258)], CREAM, w=4),
            line([(210, 225), (258, 258)], CREAM, w=4),
            line([(210, 318), (210, 372)], BROWN, w=8),   # stalk
        ],
    },
    "M": {
        "phoneme": "muh", "say": "muh", "word": "Moon",
        "art": [
            ell(90, 70, 340, 330, YELLOW),
            ell(40, 40, 260, 270, ERASE),                         # crescent bite
        ],
    },
    "N": {
        "phoneme": "nuh", "say": "nuh", "word": "Nest",
        "art": [
            pie(70, 150, 350, 380, 0, 180, BROWN),
            # Rimmed, or three cream eggs on a cream-lit nest vanish into one shape.
            {"t": "ellipse", "xy": [146, 168, 212, 232], "fill": CREAM, "outline": BROWN, "ow": 4},
            {"t": "ellipse", "xy": [208, 168, 274, 232], "fill": CREAM, "outline": BROWN, "ow": 4},
            {"t": "ellipse", "xy": [177, 206, 243, 268], "fill": CREAM, "outline": BROWN, "ow": 4},
            arc(70, 150, 350, 330, 0, 180, BROWN, w=16),
        ],
    },
    "O": {
        "phoneme": "oh", "say": "oh", "word": "Orange",
        "art": [
            ell(85, 110, 335, 355, ORANGE),
            rect(200, 78, 220, 125, BROWN, r=8),
            poly([(220, 96), (295, 70), (268, 120)], GREEN),
        ],
    },
    "P": {
        "phoneme": "puh", "say": "puh", "word": "Pencil",
        "art": [
            rect(160, 90, 260, 300, YELLOW, r=6),
            poly([(160, 300), (260, 300), (210, 370)], CREAM),   # wood tip
            poly([(186, 337), (234, 337), (210, 370)], INK),     # graphite
            rect(160, 90, 260, 130, ROSE, r=6),                  # eraser
            line([(190, 130), (190, 300)], ORANGE, w=5),
        ],
    },
    "Q": {
        "phoneme": "kwuh", "say": "kwuh", "word": "Quilt",
        "art": [
            rect(75, 105, 345, 345, CREAM, r=14),
            rect(75, 105, 210, 225, BLUE, r=10),
            rect(210, 225, 345, 345, BLUE, r=10),
            rect(210, 105, 345, 225, GREEN, r=10),
            rect(75, 225, 210, 345, ORANGE, r=10),
            line([(75, 225), (345, 225)], CREAM, w=6),
            line([(210, 105), (210, 345)], CREAM, w=6),
        ],
    },
    "R": {
        "phoneme": "ruh", "say": "ruh", "word": "Rainbow",
        "art": [
            arc(60, 110, 360, 410, 180, 360, ROSE, w=26),
            arc(92, 142, 328, 378, 180, 360, ORANGE, w=26),
            arc(124, 174, 296, 346, 180, 360, YELLOW, w=26),
            arc(156, 206, 264, 314, 180, 360, GREEN, w=26),
            arc(188, 238, 232, 282, 180, 360, BLUE, w=22),
        ],
    },
    "S": {
        "phoneme": "sss", "say": "sss", "word": "Sun",
        "art": [
            ell(130, 130, 290, 290, YELLOW),
            line([(210, 40), (210, 100)], ORANGE, w=12),
            line([(210, 320), (210, 380)], ORANGE, w=12),
            line([(40, 210), (100, 210)], ORANGE, w=12),
            line([(320, 210), (380, 210)], ORANGE, w=12),
            line([(88, 88), (130, 130)], ORANGE, w=12),
            line([(290, 290), (332, 332)], ORANGE, w=12),
            line([(332, 88), (290, 130)], ORANGE, w=12),
            line([(130, 290), (88, 332)], ORANGE, w=12),
        ],
    },
    "T": {
        "phoneme": "tuh", "say": "tuh", "word": "Tree",
        "art": [
            rect(185, 240, 235, 370, BROWN, r=8),
            ell(95, 70, 325, 275, GREEN),
            ell(70, 150, 210, 280, GREEN),
            ell(210, 150, 350, 280, GREEN),
        ],
    },
    "U": {
        "phoneme": "uh", "say": "uh", "word": "Umbrella",
        "art": [
            pie(60, 90, 360, 390, 180, 360, ROSE),
            pie(60, 90, 360, 390, 200, 250, CREAM),
            pie(60, 90, 360, 390, 290, 340, CREAM),
            rect(202, 240, 218, 360, BROWN, r=6),
            arc(160, 330, 220, 380, 0, 180, BROWN, w=14),
        ],
    },
    "V": {
        "phoneme": "vuh", "say": "vuh", "word": "Van",
        "art": [
            rect(60, 190, 350, 300, BLUE, r=20),
            rect(60, 140, 230, 200, BLUE, r=18),
            rect(80, 155, 155, 195, CREAM, r=8),
            rect(168, 155, 220, 195, CREAM, r=8),
            ell(95, 275, 165, 345, INK_SOFT),
            ell(250, 275, 320, 345, INK_SOFT),
            ell(115, 295, 145, 325, CREAM),
            ell(270, 295, 300, 325, CREAM),
        ],
    },
    "W": {
        "phoneme": "wuh", "say": "wuh", "word": "Window",
        "art": [
            rect(80, 80, 340, 340, BROWN, r=12),
            rect(100, 100, 320, 320, BLUE, r=6),
            rect(200, 100, 220, 320, BROWN),
            rect(100, 200, 320, 220, BROWN),
        ],
    },
    "X": {
        "phoneme": "ks", "say": "ksss", "word": "Xylophone",
        "art": [
            rect(70, 105, 350, 130, ROSE, r=10),
            rect(78, 150, 342, 175, ORANGE, r=10),
            rect(88, 195, 332, 220, YELLOW, r=10),
            rect(98, 240, 322, 265, GREEN, r=10),
            rect(108, 285, 312, 310, BLUE, r=10),
            line([(150, 330), (200, 375)], BROWN, w=8),
            ell(186, 362, 214, 390, BROWN),
        ],
    },
    "Y": {
        "phoneme": "yuh", "say": "yuh", "word": "Yarn",
        "art": [
            ell(90, 90, 330, 330, PLUM),
            arc(120, 120, 300, 300, 200, 20, CREAM, w=8),
            arc(150, 105, 270, 315, 250, 70, CREAM, w=8),
            arc(105, 150, 315, 270, 160, 340, CREAM, w=8),
            line([(320, 250), (380, 330)], PLUM, w=9),
        ],
    },
    "Z": {
        "phoneme": "zzz", "say": "zzz", "word": "Zebra",
        "art": [
            rect(95, 175, 305, 285, CREAM, r=40),                 # body
            ell(255, 110, 355, 200, CREAM),                       # head
            poly([(268, 125), (280, 88), (298, 122)], CREAM),     # ear
            rect(120, 275, 145, 355, CREAM, r=10),                # legs
            rect(170, 275, 195, 355, CREAM, r=10),
            rect(215, 275, 240, 355, CREAM, r=10),
            rect(260, 275, 285, 355, CREAM, r=10),
            line([(135, 180), (145, 280)], INK_SOFT, w=11),       # stripes
            line([(175, 178), (185, 282)], INK_SOFT, w=11),
            line([(215, 178), (225, 282)], INK_SOFT, w=11),
            line([(255, 180), (263, 275)], INK_SOFT, w=11),
            line([(300, 135), (312, 175)], INK_SOFT, w=9),
            ell(318, 140, 338, 160, INK),                         # eye
        ],
    },
}

ORDER = [chr(c) for c in range(ord("A"), ord("Z") + 1)]

# The touch stage (§Stage 3) shows four letters. The distractors are the three
# letters that follow in the alphabet, wrapping at Z — deterministic, so a child
# meets the same board every time (§12 "No random branching").


def touch_choices(letter: str) -> list[str]:
    i = ORDER.index(letter)
    picks = [ORDER[(i + k) % 26] for k in (0, 1, 2, 3)]
    return sorted(picks)


# Which objects a robot could plausibly eat. §Stage 6 describes the activity as
# "Feed Apple", and it reads perfectly for the apple — but the SAME wording
# applied to the other 25 letters asks a child to feed Wini a cat, a drum and a
# zebra. The interaction stays identical (drag the object to the robot, §2.5
# Consistency, "only one activity"); only the framing changes: edible objects are
# eaten, everything else is handed over.
EDIBLE = {"A", "E", "G", "I", "O"}


def lesson_dict(letter: str) -> dict:
    """The §14 lesson record for one letter. Data only, no logic."""
    e = LETTERS[letter]
    return {
        "letter": letter,
        "phoneme": e["phoneme"],
        "say": e["say"],
        "objects": [{"name": e["word"], "image": "object.png"}],
        "choices": touch_choices(letter),
        "mini_game": "feed" if letter in EDIBLE else "give",
        "edible": letter in EDIBLE,
        "lines": lesson_lines(letter),
    }


def lesson_lines(letter: str) -> dict[str, str]:
    """Every spoken line of the lesson, keyed by stage.

    Kept here (not in the server) so the TTS pre-synthesis step and the runtime
    read exactly the same strings — a mismatch would mean a silent cache miss and
    a cloud round-trip mid-lesson. Wording follows §2.3: the robot is always the
    one being helped, and never judges.
    """
    e = LETTERS[letter]
    word = e["word"]
    say = e["say"]
    article = "an" if word[0].upper() in "AEIOU" else "a"
    lower = word.lower()

    if letter in EDIBLE:
        activity_ask = f"I am hungry. Can you give me the {lower}?"
        activity_ok = "Yummy! Thank you."
    else:
        activity_ask = f"Can you bring me the {lower}?"
        activity_ok = "Thank you! I like it."

    return {
        "intro":        f"Hello. Today we are meeting the letter {letter}.",
        "listen":       f"{letter} says {say}.",
        "touch_ask":    f"Can you touch {letter}?",
        "touch_ok":     "Thank you! I found it.",
        "touch_retry":  "Let's look again, together.",
        "repeat_ask":   f"Can you say {say}?",
        "repeat_ok":    "That was lovely. Thank you.",
        "repeat_retry": f"Let's try together. {say}.",
        # Said when neither attempt matched. §Stage 4 says the robot simply
        # continues — it does NOT say the robot should claim the child was
        # right. Praising a sound that was never heard is what made the feedback
        # feel untrustworthy ("every second time it says it was correct"), and a
        # child who is actually struggling learns nothing from it. Warm, honest,
        # no judgement, and still no failure state.
        "repeat_move_on": f"Thank you for trying. We will say {say} again soon.",
        "assoc":        f"{word} begins with {letter}.",
        "activity_ask": activity_ask,
        "activity_ok":  activity_ok,
        "complete":     f"We learned {letter} today. {letter} for {article} {word.lower()}.",
    }
