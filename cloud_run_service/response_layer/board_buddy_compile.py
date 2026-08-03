"""Fallback translator: a ``figures.scene_render`` scene spec -> a Board Buddy payload.

Used on the NON-orchestrated path (BOARD_BUDDY_INTEGRATION_PLAN.md §3.3): a turn that
already produced an authored/generated scene (``scene_author`` or an on-disk ``.scene.json``)
but is rendering on a Board-Buddy device. The happy path authors Board Buddy JSON directly
(``board_buddy_author``); this exists so an existing scene still lights up the richer
renderer without a second Gemini call.

The mapping is the conservative subset of §4 that is safe to translate deterministically:

    label (fractional canvas ``at``)      -> text   (pixel ``pos``)
    curve ``quad:[a,b,c]`` over ``domain`` -> graph  (equation string + x/y ranges from view)
    axes                                   -> dropped (Board Buddy graph draws its own)
    tracer                                 -> dropped (no native dot-on-curve — §4)
    point (data-space root marker)         -> dropped (lives in the graph's own pixel space)

The scene is already text-grounded upstream by ``scene_author``; pass ``answer`` to
re-run the belt as a second guard, else the translated payload is returned as-is.
"""

from __future__ import annotations

from typing import Any

from . import board_buddy_caps as caps
from .board_buddy_author import validate_board_call

# scene semantic color names -> concrete-ish names Board Buddy understands; unknowns pass
_COLOR = {"accent": "blue", "accent2": "orange", "ink": "black",
          "muted": "gray", "": "black"}


def _label_to_text(el: dict, view: dict | None) -> dict | None:
    text = str(el.get("text") or "").strip()
    at = el.get("at")
    if not text or not isinstance(at, (list, tuple)) or len(at) != 2:
        return None
    space = el.get("space") or "canvas"
    if space == "canvas":
        px = caps.frac_to_px(float(at[0]), "x")
        py = caps.frac_to_px(float(at[1]), "y")
    else:                                   # data space: map through the scene view box
        v = view or {"x0": 0, "y0": 0, "x1": 1, "y1": 1}
        fx = (float(at[0]) - v["x0"]) / (v["x1"] - v["x0"] or 1)
        fy = 1 - (float(at[1]) - v["y0"]) / (v["y1"] - v["y0"] or 1)   # y up -> pixels down
        px = caps.frac_to_px(fx, "x")
        py = caps.frac_to_px(fy, "y")
    out = {"type": "text", "text": text[:120],
           "pos": caps.clamp_pos([px, py]) or [300, 400]}
    if el.get("size"):
        out["size"] = int(el["size"])
    out["color"] = _COLOR.get(el.get("color"), el.get("color") or "black")
    if el.get("anchor"):
        out["anchor"] = el["anchor"]
    return out


def _fmt_eq(a: float, b: float, c: float) -> str:
    """'y = a*x^2 + b*x + c' with 0-terms dropped (Board Buddy re-parses this string)."""
    parts = []
    if abs(a) > 1e-9:
        parts.append(f"{a:g}*x^2")
    if abs(b) > 1e-9:
        parts.append(("+ " if b > 0 and parts else "") + f"{b:g}*x")
    if abs(c) > 1e-9:
        parts.append(("+ " if c > 0 and parts else "") + f"{c:g}")
    return "y = " + (" ".join(parts) if parts else "0")


def _curve_to_graph(el: dict, view: dict | None) -> dict | None:
    quad = el.get("quad")
    if not isinstance(quad, (list, tuple)) or len(quad) != 3:
        return None
    a, b, c = float(quad[0]), float(quad[1]), float(quad[2])
    dom = el.get("domain")
    v = view or {}
    if isinstance(dom, (list, tuple)) and len(dom) == 2:
        x_range = [float(dom[0]), float(dom[1])]
    else:
        x_range = [float(v.get("x0", -6)), float(v.get("x1", 6))]
    y_range = [float(v.get("y0", -6)), float(v.get("y1", 6))]
    return {"type": "graph", "equation": _fmt_eq(a, b, c),
            "x_range": x_range, "y_range": y_range, "color": "blue"}


def scene_to_payload(scene: dict | None) -> list[dict]:
    """Translate a scene spec's base + beat elements into a flat Board Buddy payload.

    Deterministic and total: an unmappable primitive is silently skipped (it degrades to
    fewer elements, never an error). Positions are clamped inside the viewport."""
    if not isinstance(scene, dict):
        return []
    view = scene.get("view")
    payload: list[dict] = []

    def _emit(el: dict) -> None:
        t = el.get("t")
        if t == "label":
            m = _label_to_text(el, view)
        elif t == "curve":
            m = _curve_to_graph(el, view)
        else:                                  # axes / tracer / point / segment / polygon...
            m = None                           # not translated on the fallback path (§4)
        if m is not None:
            m["id"] = f"el{len(payload)}"      # Board Buddy load_json requires a unique id
            payload.append(m)

    for el in scene.get("base") or []:
        _emit(el)
    for beat in scene.get("beats") or []:
        for el in beat.get("in") or []:
            _emit(el)
    return payload[:caps.MAX_ELEMENTS]


def compile_scene_to_board(scene: dict | None, *, answer: str | None = None,
                           profile: dict | None = None) -> list[dict]:
    """Public entry: scene -> Board Buddy payload, optionally re-grounded against ``answer``
    (the scene is already grounded upstream; this is a belt-and-suspenders second pass and
    also enforces the device's tool subset)."""
    payload = scene_to_payload(scene)
    if not payload:
        return []
    if answer is not None:
        kept, _ = validate_board_call(payload, answer, profile=profile)
        return kept
    # No answer to ground against: still honour the device tool subset.
    allowed = set(caps.allowed_tools_for_profile(profile))
    return [el for el in payload if el.get("type") in allowed]
