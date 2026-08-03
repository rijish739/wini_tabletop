"""Author + GROUND a Board Buddy payload from the tutor's spoken answer.

Two public surfaces (BOARD_BUDDY_INTEGRATION_PLAN.md §3.1, §6.4, §10.1):

  * :func:`validate_board_call` — the deterministic **belt**. Given a Board Buddy payload
    (a flat list of elements) and the answer text, it validates EVERY element against the
    capability manifest (:mod:`board_buddy_caps`) and GROUNDS every number / count / hop /
    numerator against the answer, DROPPING anything off-spec or ungrounded. This is the
    piece the segment orchestrator (§10.2) runs on each ``board_call`` the LLM emits, and
    the piece the fallback author runs on its own output. Pure, headless, fully tested.

  * :func:`author_board_from_answer` — the non-orchestrated FALLBACK author (§3.3): one
    structured Gemini call extracts a board payload FROM the finished answer, then the belt
    grounds+lays it out. Mirrors ``scene_author.author_scene_from_answer`` exactly: the LLM
    only plans (picks tools + copies values from the answer), the brain validates and
    deterministically fills layout. Never raises to the caller.

Grounding discipline (§6.4, hard mandate — "visuals must be text-aware"):
  * a **quantity** param (``stickers.count``, ``fraction.numerator/denominator``, a
    numberline hop's ``from``/``to``, an ``animate_param`` ``from``/``to``) must appear in
    the answer's number set (digits + spelled-out words), single digit included — these are
    the real hallucination surface, and Board Buddy will happily draw 7 apples the tutor
    never mentioned.
  * a **string** param that carries maths (``text``, ``graph.equation``, ``geometry.labels``)
    is grounded with the ``scene_author`` multi-digit rule: a MULTI-digit number the answer
    never states drops the element, but a structural single digit (the 2/4 in b²-4ac) passes.
"""

from __future__ import annotations

import re
from typing import Any

from . import board_buddy_caps as caps
# Reuse the exact grounding primitives the scene author already proved (no divergence).
from .scene_author import _NUM_RE, _answer_number_set

MAX_ELEMENTS = caps.MAX_ELEMENTS       # re-exported for callers; the bound lives in caps

# Common everyday words a child/LLM reaches for that are NOT in Board Buddy's 64-icon library
# -> the closest icon that IS. Keeps a real-life stickers board from dropping to empty just
# because the object named has no exact vector (e.g. "5 marbles" -> 5 balls).
_STICKER_SYNONYMS = {
    "marble": "ball", "marbles": "ball", "bead": "ball", "dice": "ball", "die": "ball",
    "sweet": "cake", "candy": "cake", "chocolate": "cake", "cookie": "cake",
    "crayon": "pencil", "pen": "pencil", "toy": "ball", "coins": "coin", "money": "coin",
    "notebook": "book", "copy": "book", "kite": "airplane",
    "chocolates": "cake", "biscuit": "cake", "sweets": "cake", "candies": "cake",
}

# Conceptual BADGE icons (a header decoration), not the countable real-world object a
# real-life example is about — used to decide whether a real-object sticker still needs adding.
_STICKER_BADGES = frozenset({
    "lightbulb", "star", "trophy", "ruler", "book", "magnifier", "heart", "globe", "clock"})

_SPELLED_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}


def _singular(word: str) -> str:
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("ses") or word.endswith("xes") or word.endswith("ches"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def stickers_from_answer(answer: str, profile: dict | None = None) -> list[dict]:
    """Deterministic real-life sticker board from the answer: find the first "<n> <object>"
    (n in 1..12, object a library sticker or a known synonym) and draw that many icons + a
    label. Both the count and the object come straight from the answer, so it is grounded by
    construction. Empty when the answer names no countable everyday object."""
    allowed = set(caps.allowed_stickers_for_profile(profile))
    pat = re.compile(
        r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
        r"([a-z]{3,})\b", re.IGNORECASE)
    for m in pat.finditer(str(answer or "")):
        num_s, word = m.group(1).lower(), m.group(2).lower()
        n = int(num_s) if num_s.isdigit() else _SPELLED_NUM.get(num_s, 0)
        if not (1 <= n <= 12):
            continue
        item = _STICKER_SYNONYMS.get(_singular(word), _singular(word))
        if item in allowed and item not in _STICKER_BADGES:
            return [
                {"id": "rl_title", "type": "text", "text": f"{n} {word}", "pos": [40, 50],
                 "size": "large", "color": "#1B69B6"},
                {"id": "rl_stickers", "type": "stickers", "item": item, "count": n,
                 "pos": [40, 130], "size": "large"},
            ]
    return []


# ---------------------------------------------------------------------------
# Grounding predicates
# ---------------------------------------------------------------------------
def _num_str(v: Any) -> str | None:
    """Canonical digit-string for a numeric value ('3', '3.5'), or None if not numeric."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):     # NaN / inf
        return None
    return str(int(f)) if f == int(f) else str(f)


def _quantity_grounded(v: Any, grounded: set[str]) -> bool:
    """A stated quantity must be in the answer's number set (single digits enforced)."""
    s = _num_str(v)
    if s is None:
        return False
    # a decimal like 3.5 grounds if the answer states 3.5; integers compare directly
    return s in grounded or (s.endswith(".0") and s[:-2] in grounded)


def _text_grounded(text: str, grounded: set[str]) -> bool:
    """A maths string is ungrounded only when it shows a MULTI-digit number the answer never
    stated (scene_author._ground_lines rule — keeps structural single-digit constants)."""
    risky = {n for n in _NUM_RE.findall(str(text or "")) if len(n.replace(".", "")) >= 2}
    return not (risky - grounded)


# Unicode maths glyphs the frozen v1.0 mathtext font renders as tofu -> LaTeX/ASCII equivalents.
_UNICODE_MATH = {
    "\u2212": "-", "\u00d7": r"\times ", "\u00f7": r"\div ", "\u00b7": r"\cdot ",
    "\u2264": r"\leq ", "\u2265": r"\geq ", "\u2260": r"\neq ", "\u00b1": r"\pm ",
    "\u221a": r"\sqrt", "\u03c0": r"\pi ", "\u00b2": "^2", "\u00b3": "^3",
}
# amsmath macros matplotlib mathtext cannot parse -> its supported equivalents (memory note).
_LATEX_FIX = {r"\implies": r"\Rightarrow", r"\iff": r"\Leftrightarrow",
              r"\impliedby": r"\Leftarrow"}


def _sanitize_math_text(s: str) -> str:
    r"""Clean a DISPLAY string (text.text / any title) for the frozen Board Buddy LaTeX path.

    Board Buddy auto-detects + wraps maths itself, so it wants the BARE expression: strip the
    model's `$$..$$`/`$..$` delimiters (they render as literal source), unwrap `\text{}`/`\mathrm{}`
    (mathtext support is flaky), drop a leading "Graph of"/"Plot of" prose that fuses in mathmode,
    turn literal ` * ` into implicit multiplication, map amsmath arrows + unicode maths glyphs to
    supported forms. Never touches a graph `equation` (Board Buddy parses that)."""
    s = str(s or "").strip()
    while len(s) >= 4 and s[:2] == "$$" and s[-2:] == "$$":
        s = s[2:-2].strip()
    while len(s) >= 2 and s[:1] == "$" and s[-1:] == "$":
        s = s[1:-1].strip()
    for k, v in _LATEX_FIX.items():
        s = s.replace(k, v)
    s = re.sub(r"\\(?:text|mathrm|mathbf|mathit|operatorname)\s*\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"^\s*(?:graph|plot|figure)\s+of\s*[:\-]?\s*", "", s, flags=re.IGNORECASE)
    for k, v in _UNICODE_MATH.items():
        s = s.replace(k, v)
    s = re.sub(r"\s*\*\s*", " ", s)          # "1 * x^2" -> "1 x^2" (implicit mult reads clean)
    return re.sub(r"\s{2,}", " ", s).strip()


# ---------------------------------------------------------------------------
# Per-tool validation (the belt)
# ---------------------------------------------------------------------------
def _default_pos(index: int) -> list[int]:
    """Provisional slot for an element the model gave no usable position for.

    This is only a PLACEHOLDER: `_layout_payload` runs after the belt and re-flows the whole
    board with real element heights. Kept flat (and clamped) so an element always carries a
    valid `pos` even if the layout pass is skipped.
    """
    y = 80 + index * 115
    return caps.clamp_pos([40, min(y, caps.POS_Y_MAX)]) or [40, 400]


# ---------------------------------------------------------------------------
# Height-aware layout (BOARD_BUDDY_REGRESSION_AUDIT.md BUG-6 / 6b / 7)
# ---------------------------------------------------------------------------
# Nominal RENDERED heights, read off the frozen Board Buddy v1.0 renderer
# (board_buddy.py `size_presets` per elem_type, verified 2026-08-03). The old layout used a
# flat 115 px pitch for every tool, so a 200 px graph or a 140 px rectangle overlapped the
# next element, and past index 6 everything clamped onto y=780 in one pile.
_TEXT_FONT_PX = {"small": 16, "sm": 16, "medium": 22, "md": 22,
                 "large": 28, "lg": 28, "xlarge": 36, "xl": 36}

# (w, h) box presets for the tools the renderer draws into a fixed viewport.
_BOX_PRESETS: dict[str, dict[str, tuple[int, int]]] = {
    "graph":      {"small": (220, 160), "sm": (220, 160), "medium": (280, 200),
                   "md": (280, 200), "large": (350, 250), "lg": (350, 250),
                   "xlarge": (450, 320), "xl": (450, 320)},
    "fraction":   {"small": (220, 120), "sm": (220, 120), "medium": (280, 160),
                   "md": (280, 160), "large": (350, 200), "lg": (350, 200),
                   "xlarge": (450, 250), "xl": (450, 250)},
    "numberline": {"small": (220, 100), "sm": (220, 100), "medium": (280, 120),
                   "md": (280, 120), "large": (350, 150), "lg": (350, 150),
                   "xlarge": (450, 180), "xl": (450, 180)},
}
_BOX_DEFAULT = {"graph": (280, 200), "fraction": (280, 160), "numberline": (280, 120)}
_STICKER_PX = {"small": 24, "sm": 24, "medium": 32, "md": 32,
               "large": 48, "lg": 48, "xlarge": 64, "xl": 64}

# Elements that carry no geometry — control records, never laid out.
_CONTROL_TYPES = frozenset({"animate_param", "animation"})

# Board-author retry budget (BUG-9a). Deliberately small: this runs after generation with
# the answer audio already streaming, so a couple of seconds is hidden — but it must never
# become an open-ended stall on the turn.
_AUTHOR_ATTEMPTS = 2
_AUTHOR_BACKOFF_S = 1.5

# Output budget for the board-authoring call. ROOT CAUSE of BUG-9a, found 2026-08-03 once
# JsonResult started reporting WHY a structured call failed: the live log said
# `reason='max-tokens (raise max_output_tokens)'` on every decline. At 700 the structured
# JSON for a full board (up to 12 elements, each with pos/size/colour/ranges, plus schema
# overhead) truncates mid-object, so `_extract_json` returns None and the whole board is
# thrown away — which is why a real turn silently degraded to a one-sentence prose card
# while the same call succeeded on short answers in isolation. This is NOT the classic
# thinking-budget trap (llm_vertex already sets thinking_budget=0); the VISIBLE output
# simply did not fit.
#
# Raising the cap is close to free: Vertex bills the tokens actually produced, not the
# ceiling, and a board that genuinely needs fewer still stops early.
_AUTHOR_MAX_TOKENS = 2048

_LAYOUT_LEFT = 40          # left margin; text is drawn from this x rightwards
_LAYOUT_TOP = 40           # first element's top edge
_LAYOUT_GUTTER = 22        # vertical breathing room between elements
_LABEL_PAD = 26            # room for a tool's own caption/labels


def _text_height(el: dict) -> int:
    """Font size x wrapped line count. The renderer wraps at (width - x - 20)."""
    raw = el.get("size")
    if isinstance(raw, (int, float)):
        font = int(raw)
    else:
        font = _TEXT_FONT_PX.get(str(raw).lower(), 22) if raw else 22
    body = str(el.get("text") or el.get("title") or "")
    usable_px = max(200, caps.VIEWPORT_W - _LAYOUT_LEFT - 20)
    # average glyph advance ~0.55 em for this font stack
    per_line = max(8, int(usable_px / max(1.0, font * 0.55)))
    lines = max(1, -(-len(body) // per_line))          # ceil division
    return font * lines + 10


def _box_height(el: dict, kind: str) -> int:
    raw = el.get("size")
    presets = _BOX_PRESETS[kind]
    if isinstance(raw, (int, float)):
        # renderer treats a bare number as the major axis; keep the preset ratio
        w0, h0 = _BOX_DEFAULT[kind]
        return max(60, int(float(raw) * h0 / w0))
    if raw and str(raw).lower() in presets:
        return presets[str(raw).lower()][1]
    return _BOX_DEFAULT[kind][1]


def _element_height(el: dict) -> int:
    """Nominal rendered height in px for one validated element."""
    t = el.get("type")
    if t in _CONTROL_TYPES:
        return 0
    if t == "text":
        return _text_height(el)
    if t in _BOX_PRESETS:
        return _box_height(el, t) + _LABEL_PAD
    if t == "stickers":
        raw = el.get("size")
        icon = int(raw) if isinstance(raw, (int, float)) \
            else _STICKER_PX.get(str(raw).lower(), 32) if raw else 32
        return icon + _LABEL_PAD
    if t == "geometry":
        verts = el.get("vertices") or _CANON_VERTS.get(str(el.get("shape") or "").lower())
        if verts:
            ys = [float(v[1]) for v in verts if isinstance(v, (list, tuple)) and len(v) == 2]
            if ys:
                return int(max(ys) - min(ys)) + _LABEL_PAD
        return 160 + _LABEL_PAD
    if t == "tree":
        # title(28) + root circle(44) + one child row per branch level(70) + radius(20)
        branches = el.get("branches")
        levels = max(1, len(branches) if isinstance(branches, list) else 1)
        return 28 + 44 + 70 * levels + 20
    return 100                                          # unknown but positioned: be generous


def _boxes_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def _element_width(el: dict) -> int:
    t = el.get("type")
    if t in _BOX_PRESETS:
        raw = el.get("size")
        presets = _BOX_PRESETS[t]
        if raw and str(raw).lower() in presets:
            return presets[str(raw).lower()][0]
        return _BOX_DEFAULT[t][0]
    if t == "geometry":
        verts = el.get("vertices") or _CANON_VERTS.get(str(el.get("shape") or "").lower())
        if verts:
            xs = [float(v[0]) for v in verts if isinstance(v, (list, tuple)) and len(v) == 2]
            if xs:
                return int(max(xs) - min(xs)) + 40
        return 260
    return caps.VIEWPORT_W - _LAYOUT_LEFT - 20          # text/stickers wrap to the margin


def _model_layout_is_sane(els: list[dict]) -> bool:
    """True if the MODEL's own positions already fit and do not collide.

    Worth checking: when the model lays the board out well (a title top-left, a badge
    sticker top-right) that reads better than a forced single column. We only re-flow when
    its layout is actually broken — which, live, it usually is.
    """
    boxes = []
    for el in els:
        if el.get("type") in _CONTROL_TYPES:
            continue
        pos = el.get("pos")
        if not (isinstance(pos, (list, tuple)) and len(pos) == 2):
            return False                                # unpositioned (e.g. graph) -> re-flow
        x, y = int(pos[0]), int(pos[1])
        w, h = _element_width(el), _element_height(el)
        if y + h > caps.VIEWPORT_H or x + w > caps.VIEWPORT_W or x < 0 or y < 0:
            return False                                # overflows the panel
        boxes.append((x, y, w, h))
    return not any(_boxes_overlap(boxes[i], boxes[j])
                   for i in range(len(boxes)) for j in range(i + 1, len(boxes)))


def _layout_payload(els: list[dict]) -> tuple[list[dict], list[str]]:
    """Re-flow the board into a single non-overlapping column, dropping what will not fit.

    Replaces the flat 115 px pitch. Three defects this closes:
      * BUG-6  a 200 px graph / 140 px rectangle overlapped the element after it;
      * BUG-6b `graph` (and `numberline`) have no `pos` in their schema, so the brain never
               positioned them and the renderer drew them over whatever WAS positioned;
      * BUG-7  past index 6 every element clamped onto y=780 in a single pile.

    Overflow is DROPPED rather than clamped: an element stacked on another is worse than an
    absent one, and the drop is recorded so telemetry can see the board was trimmed.
    """
    if _model_layout_is_sane(els):
        return els, []

    out: list[dict] = []
    dropped: list[str] = []
    y = _LAYOUT_TOP
    for el in els:
        if el.get("type") in _CONTROL_TYPES:
            out.append(el)                              # no geometry; keep as-is
            continue
        h = _element_height(el)
        if y + h > caps.POS_Y_MAX:
            dropped.append(f"layout-overflow:{el.get('type')}")
            continue
        el["pos"] = [_LAYOUT_LEFT, int(y)]
        out.append(el)
        y += h + _LAYOUT_GUTTER
    return out, dropped


# Board Buddy's OWN canonical relative-vertex sets (mirror of board_buddy.py's geometry
# defaults, verified 2026-07-30). For these named shapes we emit NO `vertices` so the frozen
# renderer draws its canonical form — the right-angle indicator is hard-drawn at vertex index
# 1 and the hypotenuse across 0..2, which is ONLY correct for this ordering, and arbitrary
# model vertices can also exceed the canvas and trip the renderer's auto-scaler (which does
# not scale label positions, so the letters drift off the corners). We seat labels on these
# same coordinates. A shape absent here keeps the model's own vertices.
_CANON_VERTS: dict[str, list[list[float]]] = {
    "triangle": [[0, 150], [220, 150], [220, 0]],
    "right_triangle": [[0, 150], [220, 150], [220, 0]],
    "equilateral_triangle": [[0, 160], [220, 160], [110, 22]],
    "isosceles_triangle": [[0, 150], [220, 150], [110, 0]],
    "rectangle": [[0, 0], [220, 0], [220, 140], [0, 140]],
    "square": [[0, 0], [160, 0], [160, 160], [0, 160]],
    "diamond": [[80, 0], [160, 80], [80, 160], [0, 80]],
    "rhombus": [[80, 0], [160, 80], [80, 160], [0, 80]],
    "pentagon": [[80, 0], [156, 55], [127, 145], [33, 145], [4, 55]],
    "hexagon": [[40, 0], [120, 0], [160, 70], [120, 140], [40, 140], [0, 70]],
}


def _seat_labels(texts: list[str], verts: list[list[float]] | None) -> list[dict]:
    """Position vertex labels ON the polygon corners. Board Buddy places a label at
    ``[bx+pos[0], shape_origin_y+pos[1]]`` — the SAME transform it applies to a vertex ``v``
    — so a label whose ``pos`` equals ``v`` lands on that corner. We nudge each outward from
    the shape centroid so the glyph clears the edge. With no vertices (e.g. a circle) we fall
    back to a legible stacked column."""
    texts = [t for t in texts if str(t).strip()]
    if not verts:
        return [{"text": t, "pos": [20, 24 + i * 28]} for i, t in enumerate(texts)]
    cx = sum(v[0] for v in verts) / len(verts)
    cy = sum(v[1] for v in verts) / len(verts)
    seated: list[dict] = []
    for i, t in enumerate(texts):
        v = verts[i % len(verts)]
        ox = 8 if v[0] >= cx else -22
        oy = 4 if v[1] >= cy else -20
        seated.append({"text": str(t)[:24], "pos": [int(v[0] + ox), int(v[1] + oy)]})
    return seated


def _grounded_ok(value: Any, grounded: set[str]) -> bool:
    """A grounded quantity is OK if the scalar is stated, or (for a [rows, cols] matrix) if
    every member is stated. Board Buddy accepts int OR [rows, cols] for count/numerator."""
    if isinstance(value, (list, tuple)):
        return bool(value) and all(_quantity_grounded(v, grounded) for v in value)
    return _quantity_grounded(value, grounded)


def _coerce_count(value: Any) -> Any:
    """int, or a 2-element [rows, cols] grid — Board Buddy's real count/numerator forms."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return [int(float(value[0])), int(float(value[1]))]
    return int(float(value))


def _size_ok(value: Any) -> Any:
    """size is a preset name or an int point size (both valid in v1.0)."""
    if isinstance(value, str) and value.lower() in (
            "small", "sm", "medium", "md", "large", "lg", "xlarge", "xl"):
        return value.lower()
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return "medium"


def _validate_element(el: Any, index: int, grounded: set[str],
                      allowed_tools: tuple[str, ...],
                      allowed_stickers: tuple[str, ...],
                      animated_vars: frozenset[str] = frozenset()) -> tuple[dict | None, str]:
    """Return (clean_element, "") on keep, or (None, reason) on drop. The output uses the
    REAL Board Buddy v1.0 keys (verified against the deployed source) and carries a unique
    `id` (load_json SKIPS any element without one)."""
    if not isinstance(el, dict):
        return None, "not-an-object"
    ttype = str(el.get("type") or "").strip()
    if ttype not in caps.TOOL_SCHEMAS:
        return None, f"unknown-tool:{ttype or '<empty>'}"
    if ttype not in allowed_tools:
        return None, f"tool-not-on-device:{ttype}"
    schema = caps.TOOL_SCHEMAS[ttype]
    out: dict[str, Any] = {"id": el.get("id") or f"el{index}", "type": ttype}

    # required params present (pos is filled deterministically, never a drop reason)
    for req in schema["required"]:
        if req == "pos":
            continue
        if el.get(req) in (None, "", [], {}):
            return None, f"missing-required:{ttype}.{req}"

    # ground every quantity param (scalar or matrix)
    for gp in schema.get("grounded", []):
        val = el.get(gp)
        if val is None:
            continue
        if ttype == "stickers" and gp == "count" and val in (1, [1, 1], "1"):
            continue  # single icon sticker badge is a structural UI element
        if not _grounded_ok(val, grounded):
            return None, f"ungrounded-quantity:{ttype}.{gp}={val!r}"

    # ground every maths-string param
    for gt in schema.get("grounded_text", []):
        val = el.get(gt)
        strings = val if isinstance(val, list) else [val]
        for s in strings:
            if s is None:
                continue
            if not _text_grounded(s, grounded):
                return None, f"ungrounded-text:{ttype}.{gt}"

    # tool-specific structural checks + coercions -> REAL v1.0 keys
    if ttype == "stickers":
        item = str(el.get("item") or el.get("sticker") or el.get("name") or "").lower()
        item = _STICKER_SYNONYMS.get(item, item)     # map common kid words to a library icon
        if item not in allowed_stickers:
            return None, f"unknown-sticker:{item or '<empty>'!r}"
        out["item"] = item          # Board Buddy reads `item` to pick the icon (required)
        cnt_raw = el.get("count")
        if cnt_raw is None:
            cnt_raw = 1
        out["count"] = _coerce_count(cnt_raw)
        if isinstance(out["count"], int) and out["count"] <= 0:
            return None, "sticker-count<=0"
        if el.get("label"):
            out["label"] = str(el["label"])[:60]
    elif ttype == "geometry":
        shape = str(el.get("shape") or el.get("shape_type") or "").lower()
        if shape in ("line", "segment", "straight_line", "ray"):
            shape = "rectangle"
        if shape not in caps.GEOMETRY_SHAPES:
            return None, f"unknown-shape:{shape or '<empty>'!r}"
        out["shape"] = shape
        # Vertices: prefer Board Buddy's OWN canonical set (emit none, let the renderer draw
        # it) so the right-angle box / hypotenuse land correctly and the shape can't overflow
        # the canvas; keep the model's vertices only for a free-form shape with no canonical
        # form. `verts` (either source) is what we seat the labels on.
        verts = _CANON_VERTS.get(shape)
        if verts is None and isinstance(el.get("vertices"), list) and len(el["vertices"]) >= 3:
            verts = [[float(p[0]), float(p[1])] for p in el["vertices"]
                     if isinstance(p, (list, tuple)) and len(p) == 2] or None
            if verts is not None:
                out["vertices"] = [[int(x), int(y)] for x, y in verts]
        if isinstance(el.get("labels"), list) and el["labels"]:
            # Board Buddy geometry labels are POSITIONED dicts ({"text","pos"}); seat them ON
            # the corners (not stacked in the top-left) so "A/B/C" read as vertex labels.
            texts = [(lbl.get("text") if isinstance(lbl, dict) else lbl)
                     for lbl in el["labels"][:6]]
            out["labels"] = _seat_labels(texts, verts)
        if el.get("title"):
            out["title"] = str(el["title"])[:60]
        if shape == "circle" and el.get("radius") is not None:
            try:
                out["radius"] = int(float(el["radius"]))
            except (TypeError, ValueError):
                pass
    elif ttype == "graph":
        out["equation"] = str(el.get("equation"))
        for rng in ("x_range", "y_range"):
            r = el.get(rng, schema["optional"][rng])
            if isinstance(r, (list, tuple)) and len(r) == 2:
                out[rng] = [float(r[0]), float(r[1])]
            else:
                out[rng] = list(schema["optional"][rng])
        if el.get("title"):
            out["title"] = str(el["title"])[:60]
        else:
            # With no title Board Buddy AUTO-titles the graph "Graph of <equation>" in mathmode,
            # which fuses the prose ("Graphof...") and shows the parser's literal `*`. Give it a
            # clean equation title instead (sanitized below strips the `*`).
            eq = out["equation"].strip()
            out["title"] = eq if eq[:1].lower() == "y" else f"y = {eq}"
    elif ttype == "numberline":
        hops_clean, ok = _clean_hops(el.get("hops"), grounded, animated_vars)
        if not ok:
            return None, "numberline-hops-ungrounded-or-empty"
        # accept min/max or start/end aliases from the model; emit the real min/max
        lo = el.get("min", el.get("start"))
        hi = el.get("max", el.get("end"))
        out["min"] = int(float(lo)) if lo is not None else 0
        out["max"] = int(float(hi)) if hi is not None else 10
        out["hops"] = hops_clean
        if el.get("step") is not None:
            out["step"] = max(1, int(float(el.get("step"))))
        if el.get("title"):
            out["title"] = str(el["title"])[:60]
    elif ttype == "fraction":
        out["numerator"] = _coerce_count(el.get("numerator"))
        out["denominator"] = _coerce_count(el.get("denominator"))
        den = out["denominator"]
        if (isinstance(den, int) and den == 0) or (isinstance(den, list) and 0 in den):
            return None, "fraction-denominator-0"
        vt = el.get("visual_type")
        out["visual_type"] = vt if vt in caps.FRACTION_VISUAL_TYPES else "bar"
        if el.get("label"):
            out["label"] = str(el["label"])[:60]
    elif ttype == "text":
        out["text"] = str(el.get("text"))[:200]
        # Board Buddy's default text color is an RGB TUPLE, which its matplotlib LaTeX path
        # rejects (needs a hex string) — so a math line with no explicit color silently
        # falls back to plain text. Default a readable hex so \frac/^/sqrt render as LaTeX
        # (parchment-theme ink; a caller/theme may override via `color`).
        if el.get("color") is None:
            out["color"] = "#271F18"
    elif ttype == "tree":
        out["root"] = str(el.get("root") or "").strip()[:40]
        if isinstance(el.get("branches"), list):
            clean_b = []
            for b in el["branches"][:6]:
                if isinstance(b, dict):
                    parent = str(b.get("parent") or "").strip()
                    children = [str(c).strip() for c in (b.get("children") or []) if str(c).strip()][:4]
                    clean_b.append({"parent": parent, "children": children})
            out["branches"] = clean_b
        if el.get("title"):
            out["title"] = str(el["title"])[:60]
    elif ttype == "animate_param":
        out["var"] = str(el.get("var")).replace("{", "").replace("}", "").strip()
        out["from"] = float(el.get("from"))
        out["to"] = float(el.get("to"))
        out["duration"] = max(0.2, min(10.0, float(el.get("duration"))))
    elif ttype == "animation":
        out["target"] = str(el.get("target"))
        to = el.get("to")
        if not (isinstance(to, (list, tuple)) and len(to) == 2):
            return None, "animation-to-not-a-point"
        out["to"] = [int(float(to[0])), int(float(to[1]))]
        if isinstance(el.get("from"), (list, tuple)) and len(el["from"]) == 2:
            out["from"] = [int(float(el["from"][0])), int(float(el["from"][1]))]
        out["motion"] = el.get("motion") if el.get("motion") in (
            "slide", "hop", "bounce", "line", "linear") else "slide"
        if el.get("duration_ms") is not None:
            out["duration_ms"] = int(float(el["duration_ms"]))

    # size (preset or int) + color pass-through where the tool takes them
    if el.get("size") is not None and ttype in (
            "text", "stickers", "geometry", "graph", "numberline", "fraction"):
        out["size"] = _size_ok(el.get("size"))
    if el.get("color") is not None and "color" not in out:
        out["color"] = str(el.get("color"))

    # position: clamp the model's or lay one out (pos [x,y] -> Board Buddy normalizes to bounds)
    if "pos" in schema["required"] or el.get("pos") is not None:
        out["pos"] = caps.clamp_pos(el.get("pos")) or _default_pos(index)

    # DISPLAY hygiene (verified against live renders 2026-08-01): the model wraps text/titles
    # in `$$..$$`, uses `\text{}` and unicode `−`/`×` glyphs the frozen v1.0 mathtext font
    # can't paste (renders as raw source or tofu boxes). Sanitize the DISPLAY strings only
    # (never the graph `equation`, which Board Buddy PARSES) so maths renders cleanly.
    if isinstance(out.get("text"), str):
        out["text"] = _sanitize_math_text(out["text"])[:200]
    if isinstance(out.get("title"), str):
        out["title"] = _sanitize_math_text(out["title"])[:60]

    return out, ""


# A whole-string Board Buddy placeholder: "{hop}" / "{hop:int}" / "{a:2f}". The var is
# captured; Board Buddy's substitution engine replaces the exact string with the animated
# value (an int for :int) at render time.
_PLACEHOLDER_RE = re.compile(r"^\{([A-Za-z_]\w*)(?::\w+)?\}$")


def _placeholder_var(v: Any) -> str | None:
    """The variable name if ``v`` is a whole-string placeholder ("{hop:int}" -> "hop"), else None."""
    if not isinstance(v, str):
        return None
    m = _PLACEHOLDER_RE.match(v.strip())
    return m.group(1) if m else None


def _clean_hops(hops: Any, grounded: set[str],
                animated_vars: frozenset[str] = frozenset()) -> tuple[list, bool]:
    """Clean a numberline's hops. Two kept forms:

      * a grounded ``{start,end}`` hop (both endpoints stated in the answer) — a fixed arc;
      * a whole-string placeholder like ``"{hop:int}"`` whose var is driven by an
        ``animate_param`` in this payload — Board Buddy substitutes it to the current hop
        length each frame, so the arc GROWS as the value animates (its from/to are grounded
        on the animate_param element, not here).

    Anything else (ungrounded endpoints, a placeholder with no matching animation) is
    dropped; if nothing survives the numberline is meaningless (False)."""
    if not isinstance(hops, list) or not hops:
        return [], False
    kept: list = []
    for h in hops:
        # A bare var name ("hop") that an animate_param drives -> normalize to the
        # placeholder Board Buddy substitutes ("{hop:int}"), so the arc GROWS with the value
        # instead of being dropped as a non-dict, non-placeholder string.
        if isinstance(h, str) and _placeholder_var(h) is None and h.strip() in animated_vars:
            h = "{" + h.strip() + ":int}"
        var = _placeholder_var(h)
        if var is not None:
            if var in animated_vars:
                kept.append(h)          # keep the placeholder string for the device
            continue
        if not isinstance(h, dict):
            continue
        a = h.get("start", h.get("from"))
        b = h.get("end", h.get("to"))
        if not (_quantity_grounded(a, grounded) and _quantity_grounded(b, grounded)):
            continue
        hop = {"start": float(a), "end": float(b)}
        if h.get("label"):
            hop["label"] = str(h["label"])[:24]
        kept.append(hop)
    return kept, bool(kept)


def _animated_vars(payload: list) -> frozenset[str]:
    """Var names driven by an animate_param element in this payload (brace-stripped)."""
    return frozenset(
        str(el.get("var")).strip("{}").strip()
        for el in payload
        if isinstance(el, dict) and el.get("type") == "animate_param" and el.get("var"))


# ---------------------------------------------------------------------------
# Public belt
# ---------------------------------------------------------------------------
def validate_board_call(payload: Any, answer: str, *,
                        profile: dict | None = None) -> tuple[list[dict], list[str]]:
    """Ground + capability-check a Board Buddy payload against the answer + device profile.

    Returns ``(kept_payload, dropped_reasons)``. ``kept_payload`` is a flat list of clean,
    grounded Board Buddy elements ready for the wire; ``dropped_reasons`` records every
    rejection for telemetry/self-heal (§6.8). Never raises — a malformed element is a drop,
    not a crash. The payload may be a bare list or a ``{"elements":[...]}`` wrapper.
    """
    if isinstance(payload, dict):
        payload = payload.get("elements") or payload.get("payload") or []
    if not isinstance(payload, list):
        return [], ["payload-not-a-list"]
    grounded = _answer_number_set(answer)
    allowed_tools = caps.allowed_tools_for_profile(profile)
    allowed_stickers = caps.allowed_stickers_for_profile(profile)
    animated_vars = _animated_vars(payload)
    kept: list[dict] = []
    dropped: list[str] = []
    for i, el in enumerate(payload[:MAX_ELEMENTS]):
        clean, reason = _validate_element(el, len(kept), grounded,
                                          allowed_tools, allowed_stickers, animated_vars)
        if clean is not None:
            kept.append(clean)
        else:
            dropped.append(reason)
    for _ in payload[MAX_ELEMENTS:]:
        dropped.append("over-element-budget")
    # Height-aware re-flow (BUG-6/6b/7). Runs AFTER per-element validation so it only ever
    # lays out elements that survived the belt, and only re-flows when the model's own
    # positions actually collide or overflow.
    kept, layout_dropped = _layout_payload(kept)
    dropped.extend(layout_dropped)
    _brace_animated_vars(kept)
    try:
        import debug_logger as _dbg
        if _dbg:
            _dbg.emit(_dbg.L6, "board_buddy_validate",
                      total_elements=len(payload),
                      kept_count=len(kept),
                      dropped_count=len(dropped),
                      dropped_reasons=dropped,
                      tools_used=list({e.get("tool") for e in kept if isinstance(e, dict) and e.get("tool")}),
                      stickers_used=[e.get("name") for e in kept if isinstance(e, dict) and e.get("tool") == "stickers"])
    except Exception:  # noqa: BLE001
        pass
    return kept, dropped


def _brace_animated_vars(kept: list[dict]) -> None:
    """Board Buddy only substitutes `{var}`/`{var:2f}` placeholders from animate_param values
    (its pre-render substitution engine). The LLM often writes the bare variable instead —
    e.g. a graph `equation:"a*x^2"` with an `animate_param var:"a"` — so nothing substitutes
    and the curve evaluates undefined (flat/broken). Wrap bare occurrences of each animated
    var in the string params that Board Buddy substitutes (graph equation/title, numberline
    title) so the animation actually drives the drawing. Idempotent: an already-braced `{a}`
    or a `{a:2f}` is left untouched, and a var fused into a word (the `a` in `ax`) is skipped."""
    import re
    anim_vars = sorted({str(el.get("var")) for el in kept
                        if el.get("type") == "animate_param" and el.get("var")},
                       key=len, reverse=True)
    if not anim_vars:
        return

    def brace(s: str) -> str:
        for v in anim_vars:
            s = re.sub(r"(?<![\w{])" + re.escape(v) + r"(?![\w}:])", "{" + v + "}", s)
        return s

    for el in kept:
        if el.get("type") == "graph" and isinstance(el.get("equation"), str):
            el["equation"] = brace(el["equation"])
        for key in ("title",):
            if isinstance(el.get(key), str) and "{" not in el[key]:
                el[key] = brace(el[key])


def payload_has_animation(payload: list[dict]) -> bool:
    """True if any kept element animates (drives the +45 scrubber / T_max on the device)."""
    return any(el.get("type") in ("animate_param", "animation") for el in payload or [])


def tmax_hint(payload: list[dict]) -> float:
    """A T_max HINT for the wire (the device recomputes authoritatively in Board Buddy's
    load_json). Max of any animate_param/animation duration, else 0 for a static payload."""
    best = 0.0
    for el in payload or []:
        if el.get("type") == "animate_param":
            try:
                best = max(best, float(el.get("duration") or 0.0))
            except (TypeError, ValueError):
                pass
        elif el.get("type") == "animation":
            try:
                best = max(best, float(el.get("duration") or 2.0))
            except (TypeError, ValueError):
                pass
    return round(best, 3)


# ---------------------------------------------------------------------------
# Fallback author (structured Gemini call) — §3.3
# ---------------------------------------------------------------------------
def _board_element_schema():
    from google.genai import types
    S, T = types.Schema, types.Type
    num = S(type=T.NUMBER)
    return S(
        type=T.OBJECT,
        properties={
            "elements": S(type=T.ARRAY, items=S(
                type=T.OBJECT,
                properties={
                    "type": S(type=T.STRING, enum=list(caps.ALL_TOOLS)),
                    "pos": S(type=T.ARRAY, items=num),
                    "size": S(type=T.STRING), "color": S(type=T.STRING),
                    "text": S(type=T.STRING),
                    "item": S(type=T.STRING), "count": S(type=T.INTEGER),
                    "label": S(type=T.STRING),
                    "shape": S(type=T.STRING),
                    "labels": S(type=T.ARRAY, items=S(type=T.STRING)),
                    "vertices": S(type=T.ARRAY, items=S(type=T.ARRAY, items=num)),
                    "title": S(type=T.STRING), "radius": num,
                    "equation": S(type=T.STRING),
                    "x_range": S(type=T.ARRAY, items=num),
                    "y_range": S(type=T.ARRAY, items=num),
                    "min": S(type=T.INTEGER), "max": S(type=T.INTEGER),
                    "step": S(type=T.INTEGER),
                    "hops": S(type=T.ARRAY, items=S(
                        type=T.OBJECT,
                        properties={"start": num, "end": num, "label": S(type=T.STRING)})),
                    "numerator": S(type=T.INTEGER), "denominator": S(type=T.INTEGER),
                    "visual_type": S(type=T.STRING),
                    "root": S(type=T.STRING),
                    "branches": S(type=T.ARRAY, items=S(
                        type=T.OBJECT,
                        properties={"parent": S(type=T.STRING), "children": S(type=T.ARRAY, items=S(type=T.STRING))}
                    )),
                    "var": S(type=T.STRING), "from": num, "to": num, "duration": num,
                    "target": S(type=T.STRING), "motion": S(type=T.STRING),
                    "duration_ms": num,
                },
                required=["type"],
            )),
        },
        required=["elements"],
    )


def _author_prompt(answer: str, concept_id: str | None, context: str | None,
                   profile: dict | None, want_animation: bool = False,
                   want_real_life: bool = False) -> str:
    tools = caps.allowed_tools_for_profile(profile)
    stickers = caps.allowed_stickers_for_profile(profile)
    ctx = (f"CONTEXT (recent conversation — identify the specific example under "
           f"discussion, if any):\n{context[:600]}\n\n") if context else ""
    # The turn's EXPLICIT ask (child said "animate it" / "real-life example"). The answer was
    # already steered to describe motion / countable objects, so these directives just tell the
    # author which grounded tool to reach for — the belt still drops anything ungrounded.
    intent = ""
    if want_animation:
        intent += (
            "STUDENT EXPLICITLY ASKED TO SEE IT MOVE: you MUST include an `animate_param` on "
            "the ONE quantity the answer says changes (its from/to are stated there) AND write "
            "that variable as a `{var}` placeholder in the tool it drives (graph equation, "
            "numberline hops ['{hop:int}'], or a fraction numerator). A static board is a "
            "FAILURE here.\n")
    if want_real_life:
        intent += (
            "STUDENT EXPLICITLY ASKED FOR A REAL-LIFE EXAMPLE: lead with a `stickers` group of "
            "the everyday objects the answer names (apple, coin, car, book, pencil, ball, "
            "banana, orange...), `count` grounded in the answer's small numbers, so the child "
            "SEES the real objects the maths is about.\n")
    if intent:
        intent = "\n=== THIS TURN'S EXPLICIT REQUEST (obey exactly) ===\n" + intent + "\n"
    return (
        "You are an expert master teacher laying out a 600x800 digital blackboard.\n"
        "Your goal is to build a beautiful, crystal-clear, pedagogical visual representation of the tutor's spoken answer.\n\n"
        "=== MASTER TEACHER 3-BEAT LAYOUT FRAMEWORK ===\n"
        "Structure the board into 3 visual vertical bands across the 600x800 canvas:\n"
        "1. BEAT 1 — HEADER (Top, Y=40..100):\n"
        "   - Include a clear Title `text` element (size='large' or 'xlarge', color='#1B69B6', pos=[40, 40]).\n"
        "   - Include ONE conceptual badge `stickers` icon (pos=[480, 40], item='lightbulb' for insights, 'star' for rules, 'trophy' for results, 'ruler' for geometry, 'book' for concepts, 'apple'/'coin' for counting).\n\n"
        "2. BEAT 2 — MAIN VISUAL DIAGRAM (Center, Y=140..480):\n"
        "   - The primary math visual (`geometry`, `graph`, `numberline`, `fraction`, or `stickers` grid).\n"
        "   - Use sharp, harmonious colors (#1B69B6 royal blue, #D9381E crimson, #2D7D46 forest green, #E67E22 warm amber).\n"
        "   - Add side/vertex `labels` (e.g. vertex letters 'A', 'B', 'C' for geometry, curve titles for graphs).\n"
        "   - DYNAMIC ANIMATION: When the concept involves growth, progression, parameter change, or moving hops, ALWAYS include an `animate_param` element (e.g., var:'a', from:1, to:3, duration:2.5) AND write the target variable as a `{var}` placeholder in the element text/equation!\n"
        "     * A GRAPH whose shape changes: `equation:'{a}*x^2'` + animate_param var:'a'.\n"
        "     * A NUMBER LINE hop that grows / skip-counts: set `hops:['{hop:int}']` + animate_param var:'hop' from:1 to:4 (the arc lengthens as hop rises).\n"
        "     * A FRACTION grid filling up: numerator:['{r:int}', cols] + animate_param var:'r'.\n"
        "     Only the CHANGING quantity becomes a {var}; a value the answer fixes once stays a plain number.\n\n"
        "3. BEAT 3 — STEP-BY-STEP TAKEAWAY (Bottom, Y=500..740):\n"
        "   - 1 to 3 sequential LaTeX/step `text` lines (size='medium', pos=[40, 520], [40, 570], [40, 620]) showing the exact formula, worked steps, or key takeaways from the tutor's spoken answer.\n"
        "   - TEXT DISCIPLINE: a `text`/`title` is a SHORT label or a BARE formula ('y = x^2 - 5x + 6', 'Roots'), NEVER a prose sentence that also contains a formula — a maths symbol (^, _, \\frac) makes the WHOLE line render in maths mode and fuses the words together. Do NOT wrap maths in $$...$$ and do NOT use \\text{}.\n\n"
        "Pick the tool that fits the teaching:\n" + caps.routing_lines() + "\n\n"
        "Available tools and their params (use ONLY these):\n"
        + caps.tool_help_block(tools) + "\n\n"
        f"Sticker names you may use: {', '.join(stickers)}.\n"
        "HARD RULES:\n"
        "- Copy every number, count, hop endpoint, numerator and denominator FROM THE "
        "ANSWER. Introduce NO value the answer does not state — an ungrounded value is "
        "dropped.\n"
        f"- At most {MAX_ELEMENTS} elements; keep the board legible, structured, and beautiful.\n"
        "- DEDUPLICATION & DIVERSITY RULE: Never emit identical duplicate `text` elements. Output at most 1 title `text` line and at most 3 step `text` lines.\n"
        "- GRAPH ANIMATION RULE: When animating a graph (e.g. `y = a*x^2`), emit EXACTLY ONE `graph` element with `{a}*x^2` and ONE `animate_param` element for `a`. Do NOT emit repeated `text` lines.\n"
        "- If the answer has no maths worth drawing, return an empty elements list.\n"
        + intent +
        f"\n{ctx}ANSWER:\n{answer[:2000]}\n"
    )


# Deictic references to an on-screen visual (BUG-8 rewrite, 2026-08-03).
#
# The previous pair was destructive. It allowed a bare "see" and then consumed `[^.!?]*` to
# the end of the sentence, so an ordinary tutoring line —
#     "you can see the graph is a parabola with its vertex at the origin."
# — was deleted whole, taking the mathematics with it. That is the same failure class as the
# sanitizer that silently destroyed fractions (tutor_loop §5 comment).
#
# Rules now: only IMPERATIVE/deictic openers ("look at", "watch", "check out", "as you can
# see"), never a bare "see"; the match stops at the visual noun plus a short trailing
# prepositional tail, so it removes the POINTER and leaves any claim after it intact.
_VISUAL_NOUNS = (r"(?:figure|picture|diagram|drawing|chart|graph|curve|parabola|"
                 r"screen|board|image)")
_VISUAL_REF_PATTERNS = [
    # "look at the figure on the screen", "watch the curve", "check out the diagram below"
    re.compile(rf"\b(?:look at|have a look at|watch|check out)\s+(?:the\s+|this\s+|that\s+)?"
               rf"{_VISUAL_NOUNS}(?:\s+(?:on|in|at)\s+(?:the\s+)?"
               rf"(?:screen|board|right|left|top|bottom))?\s*[,.!?]?", re.IGNORECASE),
    # "as you can see in the figure,"  /  "as you can see on the screen"
    re.compile(rf"\bas\s+you\s+can\s+see\s*(?:(?:in|on)\s+(?:the\s+)?{_VISUAL_NOUNS})?"
               rf"\s*[,.!?]?", re.IGNORECASE),
    # "in the figure you can see" -> drop only the pointer clause, keep what follows
    re.compile(rf"\b(?:in|on)\s+(?:the\s+)?{_VISUAL_NOUNS}\s+you\s+can\s+see\s*[,.]?",
               re.IGNORECASE),
]


def sync_speech_with_visuals(answer: str, payload: list | None) -> str:
    """Ensure spoken answer never promises a visual ('look at the figure...') if the board
    contains only text elements or no visual diagram/graph/geometry/stickers/tree/fraction/numberline."""
    if not answer:
        return ""
    has_real_visual = False
    if payload:
        for el in payload:
            if isinstance(el, dict) and el.get("type") in ("geometry", "graph", "numberline", "fraction", "tree", "animation", "animate_param"):
                has_real_visual = True
                break
            elif isinstance(el, dict) and el.get("type") == "stickers":
                if el.get("count", 1) > 1 or el.get("item") not in _STICKER_BADGES:
                    has_real_visual = True
                    break
    if has_real_visual:
        return answer
    cleaned = answer
    for pat in _VISUAL_REF_PATTERNS:
        cleaned = pat.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    # Removing a leading pointer ("As you can see in the diagram, ") leaves the sentence
    # starting lower-case; restore sentence case so TTS prosody stays natural.
    cleaned = re.sub(r"^[,;:\s]+", "", cleaned)
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned if cleaned else answer



def progressive_segments(payload: list[dict]) -> list[dict]:
    """Turn one finished board into a BUILD-UP sequence the device can step through.

    Real-pipeline fix 2026-08-03. The compiler used to emit a single segment containing the
    whole board, so the device drew the completed figure on frame 1 and nothing ever changed
    while Wini talked — reported as "stuck on the first beat". Board Buddy is a pure
    executor: it renders exactly what it is handed, so a board only changes if we hand it a
    new payload. This produces those payloads deterministically (no extra LLM calls) by
    revealing one element at a time, cumulatively, in author order — which is already the
    order the answer works through.

    Contract kept by design:
      * the LAST segment equals the full ``payload``, so the finished board is unchanged;
      * an ANIMATED board stays a single segment — the animation is itself the motion, and
        restarting it per element would stutter it;
      * control records (``animate_param``/``animation``) ride along in every segment that
        contains the element they drive, so a partial board is never mid-animation-less.
    """
    renderable = [e for e in payload if e.get("type") not in _CONTROL_TYPES]
    controls = [e for e in payload if e.get("type") in _CONTROL_TYPES]

    # Nothing to build up, or an animation owns the timeline -> one segment (today's shape).
    if len(renderable) <= 2 or controls or payload_has_animation(payload):
        return [{"payload": payload, "tmax": tmax_hint(payload),
                 "animated": payload_has_animation(payload), "speech": None}]

    segments: list[dict] = []
    for i in range(1, len(renderable) + 1):
        step = renderable[:i]
        segments.append({"payload": step, "tmax": 0.0, "animated": False, "speech": None})
    return segments


def author_board_from_answer(answer: str, concept_id: str | None = None,
                             context: str | None = None,
                             profile: dict | None = None,
                             want_animation: bool = False,
                             want_real_life: bool = False) -> list[dict] | None:
    """Fallback pipeline: one structured Gemini call -> belt -> a grounded Board Buddy
    payload, or None when there is nothing math-worthy to draw / the call failed (the caller
    then degrades to a crop / speech-only). ``context`` only helps the model pick the right
    example; it never adds ungrounded content (the belt still runs). ``want_animation`` /
    ``want_real_life`` carry the turn's explicit ask into the authoring directive."""
    if not answer or len(answer.split()) < 6:
        return None

    # RETRY + BACKOFF (BOARD_BUDDY_REGRESSION_AUDIT.md BUG-9a). Measured live on winipi5
    # 2026-08-03: this call succeeds 4/4 in isolation but returns ok=False under the Vertex
    # call volume of a real turn (perception + generation + grader + scene author + this),
    # and the caller then silently degrades to the conservative scene->payload translation —
    # a one-sentence prose card instead of the graph. So which board a child sees depended on
    # transient API pressure. One short retry recovers the common transient case; it runs off
    # the time-to-first-audio path (answer audio is already streaming), so the cost is hidden.
    #
    # Every exit now says WHY. The previous bare `except Exception: return None` with no log
    # is what made this invisible for so long.
    import time

    prompt = _author_prompt(answer, concept_id, context, profile,
                            want_animation, want_real_life)
    schema = _board_element_schema()
    res = None
    for attempt in range(_AUTHOR_ATTEMPTS):
        # ESCALATING budget: a max-tokens decline is not transient — retrying at the SAME
        # ceiling just truncates in the same place. Longer answers produce longer boards
        # (the schema is a union over all tools, so the model fills many fields per
        # element), so the retry doubles the ceiling instead of merely waiting.
        budget = _AUTHOR_MAX_TOKENS * (2 ** attempt)
        try:
            from llm_vertex import generate_json
            res = generate_json(prompt, response_schema=schema,
                                temperature=0.0, max_output_tokens=budget)
        except Exception as e:  # noqa: BLE001 — a drawing failure must never cost the turn
            print(f"[board_buddy] author call raised (attempt {attempt + 1}"
                  f"/{_AUTHOR_ATTEMPTS}): {type(e).__name__}: {e}")
            res = None
        if res is not None and res.ok and isinstance(res.data, dict):
            break
        if attempt < _AUTHOR_ATTEMPTS - 1:
            # A max-tokens decline needs a bigger ceiling, not a pause — retry immediately.
            truncated = "max-tokens" in str(getattr(res, "reason", ""))
            delay = 0.0 if truncated else _AUTHOR_BACKOFF_S * (attempt + 1)
            print(f"[board_buddy] author declined (ok={getattr(res, 'ok', None)}, "
                  f"reason={getattr(res, 'reason', '?')!r}, budget={budget}); "
                  f"retrying at {budget * 2} tokens"
                  + (f" after {delay:.1f}s" if delay else " immediately"))
            if delay:
                time.sleep(delay)

    if res is None or not res.ok or not isinstance(res.data, dict):
        print(f"[board_buddy] author gave up after {_AUTHOR_ATTEMPTS} attempt(s) "
              f"(reason={getattr(res, 'reason', '?')!r}) "
              f"-> degrading to the scene translation / speech-only")
        return None

    kept, dropped = validate_board_call(res.data, answer, profile=profile)
    if dropped:
        print(f"[board_buddy] author dropped {len(dropped)} element(s): {dropped[:4]}")
    if not kept:
        print("[board_buddy] author produced no groundable element -> degrading")
        return None
    return kept
