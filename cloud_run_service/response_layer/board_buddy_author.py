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
    """Deterministic fallback layout when the model omits/garbles a position — the brain
    lays out, the model never has to (mirrors scene_author.layout_scene)."""
    y = 80 + index * 115
    return caps.clamp_pos([40, min(y, caps.POS_Y_MAX)]) or [40, 400]


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


_VISUAL_REF_PATTERNS = [
    re.compile(r"\b(?:look at|see|watch|check out)\s+(?:the\s+)?(?:figure|picture|diagram|curve|parabola|graph|chart|drawing|screen|board)\b[^.!?]*[.!?]?", re.IGNORECASE),
    re.compile(r"\b(?:in|on)\s+(?:the\s+)?(?:figure|picture|diagram|curve|parabola|graph|chart|drawing|screen|board)\s+(?:you can see|is|shows?)[^.!?]*[.!?]?", re.IGNORECASE),
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
    return cleaned if cleaned else answer



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
    try:
        from llm_vertex import generate_json
        res = generate_json(_author_prompt(answer, concept_id, context, profile,
                                            want_animation, want_real_life),
                            response_schema=_board_element_schema(),
                            temperature=0.0, max_output_tokens=700)
    except Exception:  # noqa: BLE001 — a drawing failure must never cost the turn
        return None
    if not res.ok or not isinstance(res.data, dict):
        return None
    kept, dropped = validate_board_call(res.data, answer, profile=profile)
    if dropped:
        print(f"[board_buddy] author dropped {len(dropped)} element(s): {dropped[:4]}")
    return kept or None
