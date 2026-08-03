"""Figure-spec schema for store-generated teaching visuals.

A *figure spec* is a small, closed JSON description of a maths diagram, authored on
a device-agnostic **view** (user maths coordinates) rather than in pixels, so the same
spec renders crisp at any resolution (Pi card now, ESP32 panel next, web dashboard).
The spec is the artifact the store keeps — the pixels are derived on demand
(`figure_render.py`). This is the maths analogue of `pi_game/content.py`'s art recipes,
upgraded so an LLM can author the spec under a `response_schema` constraint.

Design rules that keep it cheap and safe:
  * one closed set of primitive `t` values (no free-form drawing, no code),
  * colours are THEME TOKENS (resolved per light/dark) or literal ``#rrggbb``,
  * coordinates are in the spec's ``view`` box; the renderer maps view->canvas with a
    y-flip so authoring a Cartesian plane reads naturally (y up).

``RESPONSE_SCHEMA`` below is a JSON-Schema that doubles as the Gemini
``response_schema`` for the offline authoring step (Stage B of the plan).
"""

from __future__ import annotations

# Theme colour tokens. A spec may also use a literal "#rrggbb".
COLOR_TOKENS = ("ink", "paper", "accent", "accent_soft", "accent2", "muted",
                "good", "warn")

# The closed primitive vocabulary. Keep this small; add templates, not free drawing.
PRIMITIVES = (
    "axes",         # x/y axes (+ optional integer grid) spanning the view
    "segment",      # straight line between two points (optional dashed)
    "polygon",      # filled/stroked closed shape
    "circle",       # centre + radius (radius in view units)
    "arc",          # bounding-box arc, degrees
    "point",        # a dot, with an optional attached label
    "right_angle",  # small square at a vertex, given the two arm directions
    "label",        # free text anchored at a view point
)

ANCHORS = ("center", "n", "s", "e", "w", "ne", "nw", "se", "sw")

# ---------------------------------------------------------------------------
# JSON-Schema (also usable as a Gemini response_schema). Kept permissive on the
# element payload — a primitive only uses the fields it needs — but strict on the
# closed enums (`t`, colour tokens, anchors), which is exactly the belt that stops
# an LLM inventing an out-of-vocabulary primitive.
# ---------------------------------------------------------------------------
RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["version", "concept_id", "canvas", "view", "elements"],
    "properties": {
        "version": {"type": "integer"},
        "concept_id": {"type": "string"},
        "title": {"type": "string"},
        "canvas": {
            "type": "object",
            "required": ["w", "h"],
            "properties": {
                "w": {"type": "integer"},
                "h": {"type": "integer"},
                "equal_aspect": {"type": "boolean"},
                "pad": {"type": "integer"},
            },
        },
        "view": {
            "type": "object",
            "required": ["x0", "y0", "x1", "y1"],
            "properties": {
                "x0": {"type": "number"}, "y0": {"type": "number"},
                "x1": {"type": "number"}, "y1": {"type": "number"},
            },
        },
        "elements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["t"],
                "properties": {
                    "t": {"type": "string", "enum": list(PRIMITIVES)},
                    "at": {"type": "array", "items": {"type": "number"}},
                    "from": {"type": "array", "items": {"type": "number"}},
                    "to": {"type": "array", "items": {"type": "number"}},
                    "pts": {"type": "array", "items": {
                        "type": "array", "items": {"type": "number"}}},
                    "r": {"type": "number"},
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "text": {"type": "string"},
                    "anchor": {"type": "string", "enum": list(ANCHORS)},
                    "size": {"type": "number"},
                    "w": {"type": "number"},
                    "dash": {"type": "boolean"},
                    "italic": {"type": "boolean"},
                    "grid": {"type": "boolean"},
                    "arrows": {"type": "boolean"},
                    "fill": {"type": "string"},
                    "stroke": {"type": "string"},
                    "color": {"type": "string"},
                    "label": {"type": "string"},
                    "label_anchor": {"type": "string", "enum": list(ANCHORS)},
                },
            },
        },
    },
}


def validate(spec: dict, extra_primitives: tuple | set = ()) -> list[str]:
    """Lightweight structural check (no jsonschema dependency). Returns a list of
    human-readable problems; empty list == valid. Catches the mistakes an LLM or a
    hand-edit actually makes: missing keys, unknown primitive, bad colour token.

    `extra_primitives` lets the animated scene validator admit its extra `t` values
    (`curve`, `tracer`) without polluting the static figure vocabulary."""
    allowed = set(PRIMITIVES) | set(extra_primitives)
    errs: list[str] = []
    for k in ("version", "concept_id", "canvas", "view", "elements"):
        if k not in spec:
            errs.append(f"missing top-level key: {k}")
    if errs:
        return errs
    for k in ("w", "h"):
        if k not in spec["canvas"]:
            errs.append(f"canvas missing {k}")
    for k in ("x0", "y0", "x1", "y1"):
        if k not in spec["view"]:
            errs.append(f"view missing {k}")

    def _color_ok(c) -> bool:
        return isinstance(c, str) and (
            c in COLOR_TOKENS or (c.startswith("#") and len(c) in (4, 7)))

    for i, e in enumerate(spec.get("elements", [])):
        t = e.get("t")
        if t not in allowed:
            errs.append(f"element[{i}] unknown primitive: {t!r}")
            continue
        for key in ("fill", "stroke", "color"):
            if key in e and e[key] not in (None, "none") and not _color_ok(e[key]):
                errs.append(f"element[{i}] bad colour {key}={e[key]!r}")
        if e.get("anchor") and e["anchor"] not in ANCHORS:
            errs.append(f"element[{i}] bad anchor {e['anchor']!r}")
    return errs
