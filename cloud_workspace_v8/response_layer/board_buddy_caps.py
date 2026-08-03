"""Board Buddy capability manifest — the response layer is tool-AWARE, not tool-blind.

This is the machine-readable description of the frozen Board Buddy v1.0 renderer that
lives on the device (see BOARD_BUDDY_INTEGRATION_PLAN.md §10.1). Every other new module
reads it:

  * ``board_buddy_author`` builds the authoring prompt FROM this manifest, so the model can
    only choose real tools with real params, and
  * the deterministic **belt** (``validate_board_call`` in ``board_buddy_author``) validates
    every produced element against it and DROPS anything off-spec — controlled generation
    stops *invented* values, not *wrong-but-valid* ones, so the manifest is the second gate
    (same rule as perception §5.3 and the ``scene_author`` grounding belt).

Design rules (mirrors ``contracts.py`` / ``scene_author.py`` discipline):
  * Pure data + pure functions. No Vertex, no pygame, no Board Buddy import — this module is
    importable anywhere (tests, cloud brain, tooling) and never renders.
  * Board Buddy is FROZEN v1.0 and already installed on the Pi (§6.8). This manifest is the
    contract we author against; ``MANIFEST_VERSION`` records which deployed renderer it was
    written for, so a future Board Buddy update is a deliberate manifest bump, not a silent
    drift. Reconcile against the deployed ``board_buddy`` package before bumping.
  * A device may ship a SUBSET of the tools/stickers (ESP32 LVGL port, §6.9). The profile
    carries ``board_buddy_tools`` / ``board_buddy_sticker_names`` and the belt honours the
    device's subset via :func:`allowed_tools_for_profile`.

Viewport (§1.2, §10.1): pixel 600x800; +45px scrubber bar at the bottom when a payload
animates (600x845 presented). Positions are clamped to the drawable area.
"""

from __future__ import annotations

from typing import Any

# The Board Buddy release this manifest was authored against. Bump deliberately after
# reconciling against the deployed package (§8 Q4 "record the deployed version").
# Verified 2026-07-29 against the live v1.0 source on winipi5 (~/board_buddy_sandbox/
# board_buddy.py, 1767 lines): every element needs a unique `id`; flat top-level params are
# read (get_param falls back to config); `pos:[x,y]` is normalized to [x,y,w,h]. The tool
# param names below are the REAL ones the renderer reads (not the plan's approximations).
MANIFEST_VERSION = "board_buddy-v1.0"

# ---------------------------------------------------------------------------
# Viewport + coordinate bounds (§10.1)
# ---------------------------------------------------------------------------
VIEWPORT_W = 600
VIEWPORT_H = 800
SCRUBBER_H = 45                       # extra strip shown only for animated payloads
VIEWPORT_H_ANIMATED = VIEWPORT_H + SCRUBBER_H     # 845

# A board is a small, legible set of elements, not a wall of maths (§10.1 "legible").
MAX_ELEMENTS = 12

# An element's anchor position must sit inside the drawable box (leave a margin so a
# label/sticker is not clipped at the far edge). Matches the plan's "0<=x<=580, 0<=y<=780".
POS_X_MIN, POS_X_MAX = 0, 580
POS_Y_MIN, POS_Y_MAX = 0, 780

# ---------------------------------------------------------------------------
# Sticker library + geometry shapes + fraction modes (§10.1)
# ---------------------------------------------------------------------------
# The counting/grouping sticker vocabulary — the REAL 64 self-contained vector icons Board
# Buddy v1.0 ships (verified against its icon library 2026-07-29). Read via the `item` param.
# A device that ships fewer is honoured via the profile subset.
STICKER_NAMES: tuple[str, ...] = (
    "airplane", "apple", "backpack", "ball", "banana", "bee", "bicycle", "bird", "boat",
    "book", "boy", "bus", "butterfly", "cake", "car", "carrot", "cat", "circle_shape",
    "clock", "cloud", "coin", "crescent", "diamond", "dog", "duck", "eraser", "fish",
    "flower", "frog", "girl", "globe", "grape", "heart", "hexagon", "house", "ice_cream",
    "ladybug", "leaf", "lightbulb", "magnifier", "mango", "minus_sign", "moon", "mountain",
    "orange", "pencil", "pentagon", "pizza", "plus_sign", "rabbit", "raindrop", "ruler",
    "scissors", "snowflake", "soccer", "square_shape", "star", "strawberry", "sun", "tree",
    "triangle_shape", "trophy", "watermelon",
)

# The geometry shape names the renderer branches on (read via `shape` OR `shape_type`).
GEOMETRY_SHAPES: tuple[str, ...] = (
    "triangle", "equilateral_triangle", "isosceles_triangle", "right_triangle",
    "rectangle", "square", "pentagon", "hexagon", "circle",
)

# Fraction display style (the `visual_type` param). "bar" is the default; a 2D area/grid is
# produced by giving numerator/denominator as [rows, cols] (fraction multiplication).
FRACTION_VISUAL_TYPES: tuple[str, ...] = ("bar", "grid", "circle")

# The animated-parameter placeholder format-spec suffixes Board Buddy substitutes in a
# ``{var}`` / ``{var:2f}`` token (verified: substitute_item handles int|d|0f|1f|2f + $var).
VAR_FORMAT_SPECS: tuple[str, ...] = ("int", "d", "0f", "1f", "2f")

# ---------------------------------------------------------------------------
# The 8 tool schemas (§1.2, §4, §10.1)
# ---------------------------------------------------------------------------
# Each entry: required params, optional params (with defaults where the renderer has one),
# and a short teaching note used to build the authoring prompt. ``grounded`` lists the
# numeric params that MUST be traceable to the spoken answer (the belt drops the element
# otherwise — §6.4 text-aware mandate).
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "text": {
        "note": "A LaTeX-capable text line (formula / definition / worked step). "
                "Board Buddy auto-detects maths (\\frac, ^, _, {}) and renders it.",
        "required": ["text", "pos"],
        # size is a preset (small/medium/large/xlarge) OR an int point size.
        "optional": {"size": "medium", "color": None},
        "grounded": [],                # text is grounded by its STRING content, not a scalar
        "grounded_text": ["text"],
    },
    "stickers": {
        "note": "Counting / grouping: draw `count` copies of an icon (`item`). count is an "
                "int (a row) or [rows, cols] for a grid.",
        "required": ["item", "count", "pos"],
        "optional": {"size": "medium", "label": None},
        "grounded": ["count"],
        "grounded_text": ["label"],
    },
    "geometry": {
        "note": "A shape (triangle/right_triangle/rectangle/square/circle/pentagon/hexagon) "
                "for shapes, angles, area. Optional explicit `vertices` and side `labels`.",
        "required": ["shape", "pos"],
        "optional": {"size": "medium", "labels": None, "vertices": None, "color": None,
                     "title": None, "radius": None},
        "grounded": [],
        "grounded_text": ["labels", "title"],
    },
    "graph": {
        "note": "Plot y=f(x) from an equation STRING (parabola/line; use ^ for powers, x as "
                "the variable). Give x_range/y_range as [lo, hi].",
        "required": ["equation"],
        "optional": {"pos": [40, 60], "x_range": [-6, 6], "y_range": [-6, 6],
                     "size": "medium", "color": None, "title": None},
        "grounded": [],
        "grounded_text": ["equation", "title"],
    },
    "numberline": {
        "note": "Addition/subtraction as hops on a line. min/max are the axis window "
                "(default 0..10); hops=[{start,end}] are the moves.",
        "required": ["hops"],          # min/max default + accept start/end aliases in the belt
        "optional": {"min": 0, "max": 10, "pos": [40, 400], "step": 1,
                     "size": "medium", "title": None},
        # min/max are the axis window (structural), NOT stated quantities; each hop's
        # start/end IS a stated quantity, grounded per-hop by the belt.
        "grounded": [],
    },
    "fraction": {
        "note": "A fraction bar/grid. numerator/denominator are ints (a bar) or [rows,cols] "
                "(a 2D area grid, e.g. fraction multiplication).",
        "required": ["numerator", "denominator", "pos"],
        "optional": {"visual_type": "bar", "size": "medium", "color": None, "label": None},
        "grounded": ["numerator", "denominator"],
        "grounded_text": ["label"],
    },
    "animate_param": {
        "note": "Morph a {var} placeholder (in another element's text/equation) from `from` "
                "to `to` over `duration` seconds. Only for a value the answer actually varies.",
        "required": ["var", "from", "to", "duration"],
        "optional": {},
        "grounded": ["from", "to"],
    },
    "animation": {
        "note": "Move a target element from one position to another. `target` is another "
                "element's id; `motion` = slide|hop|bounce.",
        "required": ["target", "to"],
        "optional": {"from": None, "motion": "slide", "duration_ms": 1200},
        "grounded": [],
    },
}

ALL_TOOLS: tuple[str, ...] = tuple(TOOL_SCHEMAS.keys())

# ---------------------------------------------------------------------------
# Pedagogical tool routing (§10.1) — concept/answer shape -> the tool that FITS
# ---------------------------------------------------------------------------
# Ordered hints the authoring prompt surfaces so the model picks the tool that teaches the
# idea, not just "some picture". Keys are coarse concept/answer families; the model still
# decides, the belt still validates.
TOOL_ROUTING: tuple[tuple[str, str], ...] = (
    ("counting / grouping / how many", "stickers"),
    ("addition / subtraction / hops / take away", "numberline"),
    ("fraction / part of a whole / multiply fractions", "fraction"),
    ("quadratic / parabola / plot y = f(x) / graph of", "graph"),
    ("shape / angle / triangle / rectangle / area of a figure", "geometry"),
    ("formula / definition / worked steps / rule", "text"),
    ("a value that grows or changes / as x increases", "animate_param"),
)


# ---------------------------------------------------------------------------
# Profile-subset helpers (§10.1, §6.9)
# ---------------------------------------------------------------------------
def allowed_tools_for_profile(profile: dict | None) -> tuple[str, ...]:
    """The tools this device actually ships. A profile that omits ``board_buddy_tools``
    is assumed to ship the full v1.0 set; an explicit list is intersected with ALL_TOOLS
    (an unknown reported tool is dropped, never trusted)."""
    listed = (profile or {}).get("board_buddy_tools")
    if not listed:
        return ALL_TOOLS
    return tuple(t for t in ALL_TOOLS if t in set(listed))


def allowed_stickers_for_profile(profile: dict | None) -> tuple[str, ...]:
    listed = (profile or {}).get("board_buddy_sticker_names")
    if not listed:
        return STICKER_NAMES
    return tuple(s for s in STICKER_NAMES if s in set(listed))


def supports_board_buddy(profile: dict | None) -> bool:
    """The device can run the pygame/matplotlib Board Buddy surface. Defaults False for a
    profile that never reported it (belt-and-suspenders: an ESP32/unknown device degrades to
    crop/formula-text, §6.9), True only when explicitly reported."""
    return bool((profile or {}).get("supports_board_buddy", False))


# ---------------------------------------------------------------------------
# Geometry helpers shared by author + compile
# ---------------------------------------------------------------------------
def clamp_pos(pos: Any) -> list[int] | None:
    """Coerce a ``[x, y]`` to ints clamped inside the drawable box, or None if not a pair."""
    if not isinstance(pos, (list, tuple)) or len(pos) != 2:
        return None
    try:
        x = int(round(float(pos[0])))
        y = int(round(float(pos[1])))
    except (TypeError, ValueError):
        return None
    x = max(POS_X_MIN, min(POS_X_MAX, x))
    y = max(POS_Y_MIN, min(POS_Y_MAX, y))
    return [x, y]


def frac_to_px(fx: float, axis: str) -> int:
    """Map a fractional 0..1 canvas coord to a Board Buddy pixel (for the scene translator)."""
    span = VIEWPORT_W if axis == "x" else VIEWPORT_H
    return max(0, min(span - 1, int(round(fx * span))))


def routing_lines() -> str:
    """The tool-routing table as prompt text (one 'family -> tool' line each)."""
    return "\n".join(f"  - {family} -> `{tool}`" for family, tool in TOOL_ROUTING)


def tool_help_block(tools: tuple[str, ...] | None = None) -> str:
    """Human/LLM-readable per-tool param help, built FROM the manifest so the prompt can
    never advertise a tool or param the renderer doesn't have."""
    tools = tools or ALL_TOOLS
    out = []
    for t in tools:
        s = TOOL_SCHEMAS[t]
        req = ", ".join(s["required"])
        opt = ", ".join(f"{k}={v!r}" for k, v in s["optional"].items())
        out.append(f"* `{t}` — {s['note']}\n    required: {req}"
                   + (f"\n    optional: {opt}" if opt else ""))
    return "\n".join(out)
