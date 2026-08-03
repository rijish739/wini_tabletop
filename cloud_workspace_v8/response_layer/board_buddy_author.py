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


# ---------------------------------------------------------------------------
# Per-tool validation (the belt)
# ---------------------------------------------------------------------------
def _default_pos(index: int) -> list[int]:
    """Deterministic fallback layout when the model omits/garbles a position — the brain
    lays out, the model never has to (mirrors scene_author.layout_scene)."""
    y = 80 + index * 130
    return caps.clamp_pos([caps.VIEWPORT_W // 2, min(y, caps.POS_Y_MAX)]) or [300, 400]


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
        if el.get(gp) is None:
            continue
        if not _grounded_ok(el.get(gp), grounded):
            return None, f"ungrounded-quantity:{ttype}.{gp}={el.get(gp)!r}"

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
        if item not in allowed_stickers:
            return None, f"unknown-sticker:{item or '<empty>'!r}"
        out["item"] = item
        out["count"] = _coerce_count(el.get("count"))
        if isinstance(out["count"], int) and out["count"] <= 0:
            return None, "sticker-count<=0"
        if el.get("label"):
            out["label"] = str(el["label"])[:60]
    elif ttype == "geometry":
        shape = str(el.get("shape") or el.get("shape_type") or "").lower()
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
                   profile: dict | None) -> str:
    tools = caps.allowed_tools_for_profile(profile)
    stickers = caps.allowed_stickers_for_profile(profile)
    ctx = (f"CONTEXT (recent conversation — identify the specific example under "
           f"discussion, if any):\n{context[:600]}\n\n") if context else ""
    return (
        "You lay out a small teaching BOARD (a pixel canvas "
        f"{caps.VIEWPORT_W}x{caps.VIEWPORT_H}) that MIRRORS on screen the maths a tutor is "
        "speaking aloud right now. Choose the RIGHT visual tool for the idea and fill it "
        "ONLY with values the tutor's answer actually states.\n\n"
        "Pick the tool that fits the teaching:\n" + caps.routing_lines() + "\n\n"
        "Available tools and their params (use ONLY these):\n"
        + caps.tool_help_block(tools) + "\n\n"
        f"Sticker names you may use: {', '.join(stickers)}.\n"
        "HARD RULES:\n"
        "- Copy every number, count, hop endpoint, numerator and denominator FROM THE "
        "ANSWER. Introduce NO value the answer does not state — an ungrounded value is "
        "dropped.\n"
        f"- At most {MAX_ELEMENTS} elements; keep the board legible, not a wall of maths.\n"
        "- Positions are pixels; if unsure, omit pos and it will be laid out for you.\n"
        "- ANIMATE when the answer describes a value that GROWS, INCREASES, CHANGES, or is "
        "stepped through ('grows from 1 to 3', 'increases', 'as x rises', 'watch it "
        "change'): add an `animate_param` element for that variable AND write the variable "
        "as a {var} PLACEHOLDER inside the tool it drives — e.g. a graph `equation` "
        "'{a}*x^2' with animate_param var 'a' from 1 to 3. For a HOP on a number line that "
        "grows/skip-counts, set the numberline `hops` to ['{hop:int}'] with animate_param "
        "var 'hop' from 1 to 4 (the arc lengthens as hop rises). A value the answer fixes "
        "once stays a plain number; only the changing quantity becomes {var}+animate_param.\n"
        "- If the answer has no maths worth drawing, return an empty elements list.\n\n"
        f"{ctx}ANSWER:\n{answer[:2000]}\n"
    )


def author_board_from_answer(answer: str, concept_id: str | None = None,
                             context: str | None = None,
                             profile: dict | None = None) -> list[dict] | None:
    """Fallback pipeline: one structured Gemini call -> belt -> a grounded Board Buddy
    payload, or None when there is nothing math-worthy to draw / the call failed (the caller
    then degrades to a crop / speech-only). ``context`` only helps the model pick the right
    example; it never adds ungrounded content (the belt still runs)."""
    if not answer or len(answer.split()) < 6:
        return None
    try:
        from llm_vertex import generate_json
        res = generate_json(_author_prompt(answer, concept_id, context, profile),
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
