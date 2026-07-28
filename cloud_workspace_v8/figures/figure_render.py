"""Deterministic renderer for figure specs (see figure_schema.py).

Two backends, one geometry:
  * ``render_png(spec, theme)``  -> Pillow raster (the Pi / ESP32 raster card path;
    reuses the alphabet game's only image dependency, Pillow),
  * ``render_svg(spec, theme)``  -> hand-rolled SVG string (the web / vector-panel
    path; no extra dependency — drawsvg would be a drop-in if richer SVG is wanted).

No model runs here: a spec in, pixels/markup out, at whatever size and theme the
caller asks for. Coordinates in the spec are VIEW coordinates (maths, y-up); both
backends share one ``_Transform`` so the PNG and the SVG are pixel-identical in
layout.

CLI:
    py -3 -m figures.figure_render SPEC.json --png out.png --svg out.svg --theme light
"""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path

from figures import figure_schema

# ---------------------------------------------------------------------------
# Theme palettes. Tokens resolve to hex per theme so one spec renders correctly
# on a light card and a dark card without edits.
# ---------------------------------------------------------------------------
PALETTES = {
    "light": {
        "ink": "#2B2B2B", "paper": "#FbF8F1", "accent": "#2F6DF0",
        "accent_soft": "#DCE8FF", "accent2": "#E8641E", "muted": "#B9B4A7",
        "good": "#1F9D5B", "warn": "#D14343",
    },
    "dark": {
        "ink": "#EAE6DC", "paper": "#1E1E1E", "accent": "#6FA0FF",
        "accent_soft": "#2C3A57", "accent2": "#FF9A5A", "muted": "#6B675E",
        "good": "#57C98A", "warn": "#FF6B6B",
    },
}

_FONT_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "pi_game" / "alphabet_ui" / "fonts" / "NunitoSans.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("C:/Windows/Fonts/seguisb.ttf"),
]


def _resolve_color(c, pal) -> str:
    if not c or c == "none":
        return "none"
    if c.startswith("#"):
        return c
    return pal.get(c, pal["ink"])


def _fillc(c, pal):
    """Pillow fill/outline: a real colour, or None for 'none' (transparent)."""
    r = _resolve_color(c, pal)
    return None if r == "none" else r


class _Transform:
    """view (maths, y-up) -> canvas pixels (y-down), optionally equal-aspect."""

    def __init__(self, spec: dict):
        cv = spec["canvas"]
        self.w, self.h = int(cv["w"]), int(cv["h"])
        # Padding may be a single `pad` or asymmetric `pad_top/bottom/left/right`,
        # so a scene can reserve a header band for the equation and a footer band
        # for the answer that the plot never draws into.
        pad = int(cv.get("pad", 16))
        pl = int(cv.get("pad_left", pad)); pr = int(cv.get("pad_right", pad))
        pt = int(cv.get("pad_top", pad)); pb = int(cv.get("pad_bottom", pad))
        v = spec["view"]
        vx0, vy0, vx1, vy1 = v["x0"], v["y0"], v["x1"], v["y1"]
        pw, ph = self.w - pl - pr, self.h - pt - pb
        sx = pw / (vx1 - vx0)
        sy = ph / (vy1 - vy0)
        if cv.get("equal_aspect", True):
            s = min(sx, sy)
            sx = sy = s
        # centre the mapped view inside the (asymmetric) padded plot area
        used_w, used_h = sx * (vx1 - vx0), sy * (vy1 - vy0)
        self.ox = pl + (pw - used_w) / 2
        self.oy = pt + (ph - used_h) / 2
        self.sx, self.sy = sx, sy
        self.vx0, self.vy0, self.vy1 = vx0, vy0, vy1

    def px(self, x, y):
        cx = self.ox + (x - self.vx0) * self.sx
        cy = self.oy + (self.vy1 - y) * self.sy   # y-flip
        return (cx, cy)

    def px_frac(self, fx, fy):
        """Canvas-space placement: (0,0)=top-left .. (1,1)=bottom-right. For header/
        footer text that must live OUTSIDE the plot, independent of view coords."""
        return (fx * self.w, fy * self.h)


def _anchor_offset(anchor: str, tw: int, th: int):
    ax = {"w": 0, "nw": 0, "sw": 0}.get(anchor, -tw / 2 if anchor in
          ("n", "s", "center") else -tw)
    ay = {"n": 0, "ne": 0, "nw": 0}.get(anchor, -th / 2 if anchor in
          ("e", "w", "center") else -th)
    return ax, ay


# ---------------------------------------------------------------------------
# Pillow (raster) backend
# ---------------------------------------------------------------------------
def render_png(spec: dict, theme: str = "light", scale: float = 1.0,
               out_path: str | None = None):
    """Render to a Pillow image (and save if out_path given). ``scale`` supersamples
    for crisp edges, then downsamples once — cheap antialiasing without a vector step."""
    from PIL import Image, ImageDraw, ImageFont

    pal = PALETTES[theme]
    ss = max(1.0, float(scale))
    # supersample by drawing the transform at ss and shrinking at the end
    big = dict(spec)
    big_canvas = dict(spec["canvas"])
    big_canvas["w"] = int(spec["canvas"]["w"] * ss)
    big_canvas["h"] = int(spec["canvas"]["h"] * ss)
    if "pad" in spec["canvas"]:
        big_canvas["pad"] = int(spec["canvas"]["pad"] * ss)
    big["canvas"] = big_canvas
    T = _Transform(big)

    img = Image.new("RGB", (T.w, T.h), _resolve_color("paper", pal))
    d = ImageDraw.Draw(img)

    def font(px):
        for fp in _FONT_CANDIDATES:
            if fp.exists():
                try:
                    return ImageFont.truetype(str(fp), int(px))
                except OSError:
                    continue
        return ImageFont.load_default()

    def draw_text(text, at, anchor, color, size, italic=False, space="view"):
        f = font(size * ss)
        bbox = d.textbbox((0, 0), text, font=f)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        cx, cy = (T.px_frac(*at) if space == "canvas" else T.px(*at))
        ax, ay = _anchor_offset(anchor, tw, th)
        d.text((cx + ax - bbox[0], cy + ay - bbox[1]), text, font=f,
               fill=_resolve_color(color, pal))

    for e in spec["elements"]:
        t = e["t"]
        if t == "axes":
            _png_axes(d, T, e, pal, ss, font)
        elif t == "segment":
            _png_segment(d, T, e, pal, ss)
        elif t == "polygon":
            pts = [T.px(*p) for p in e["pts"]]
            d.polygon(pts, fill=_fillc(e.get("fill", "none"), pal),
                      outline=_fillc(e.get("stroke", "ink"), pal),
                      width=max(1, int(e.get("w", 2) * ss)))
        elif t == "circle":
            cx, cy = T.px(*e["at"]); rr = e["r"] * T.sx
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                      fill=_fillc(e.get("fill", "none"), pal),
                      outline=_fillc(e.get("stroke", "ink"), pal),
                      width=max(1, int(e.get("w", 2) * ss)))
        elif t == "arc":
            (x0, y0), (x1, y1) = T.px(e["pts"][0][0], e["pts"][1][1]), \
                                 T.px(e["pts"][1][0], e["pts"][0][1])
            d.arc([x0, y0, x1, y1], e.get("start", 0), e.get("end", 360),
                  fill=_resolve_color(e.get("stroke", "ink"), pal),
                  width=max(1, int(e.get("w", 2) * ss)))
        elif t == "point":
            _png_point(d, T, e, pal, ss, draw_text)
        elif t == "right_angle":
            _png_right_angle(d, T, e, pal, ss)
        elif t == "label":
            draw_text(e.get("text", ""), e["at"], e.get("anchor", "center"),
                      e.get("color", "ink"), e.get("size", 18), e.get("italic", False),
                      e.get("space", "view"))

    if ss != 1.0:
        img = img.resize((spec["canvas"]["w"], spec["canvas"]["h"]),
                         Image.LANCZOS)
    if out_path:
        img.save(out_path)
    return img


def _png_axes(d, T, e, pal, ss, font):
    col = _resolve_color(e.get("stroke", "muted"), pal)
    ink = _resolve_color("muted", pal)
    x0, y0, x1, y1 = T.vx0, T.vy0, None, T.vy1
    v = e
    ax0, ay0 = v.get("x0", T.vx0), v.get("y0", T.vy0)
    ax1, ay1 = v.get("x1"), v.get("y1")
    ax1 = ax1 if ax1 is not None else _view_x1(T)
    ay1 = ay1 if ay1 is not None else T.vy1
    if e.get("grid", False):
        gcol = _resolve_color("muted", pal)
        step = e.get("step", 1)
        gx = math.ceil(ax0)
        while gx <= ax1:
            p0, p1 = T.px(gx, ay0), T.px(gx, ay1)
            d.line([p0, p1], fill=gcol, width=max(1, int(1 * ss)))
            gx += step
        gy = math.ceil(ay0)
        while gy <= ay1:
            p0, p1 = T.px(ax0, gy), T.px(ax1, gy)
            d.line([p0, p1], fill=gcol, width=max(1, int(1 * ss)))
            gy += step
    axc = _resolve_color("ink", pal)
    d.line([T.px(ax0, 0), T.px(ax1, 0)], fill=axc, width=max(1, int(2 * ss)))
    d.line([T.px(0, ay0), T.px(0, ay1)], fill=axc, width=max(1, int(2 * ss)))
    if e.get("arrows", True):
        _arrow(d, T.px(ax1 - 0.35, 0), T.px(ax1, 0), axc, ss)
        _arrow(d, T.px(0, ay1 - 0.35), T.px(0, ay1), axc, ss)


def _view_x1(T):
    return T.vx0 + (T.w) / T.sx


def _arrow(d, p0, p1, col, ss):
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    L = 9 * ss
    for da in (math.radians(150), math.radians(-150)):
        x = p1[0] + L * math.cos(ang + da)
        y = p1[1] + L * math.sin(ang + da)
        d.line([p1, (x, y)], fill=col, width=max(1, int(2 * ss)))


def _dash_line(d, p0, p1, col, w):
    n = max(1, int(math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / (10)))
    for i in range(n):
        if i % 2:
            continue
        a = (p0[0] + (p1[0] - p0[0]) * i / n, p0[1] + (p1[1] - p0[1]) * i / n)
        b = (p0[0] + (p1[0] - p0[0]) * (i + 1) / n, p0[1] + (p1[1] - p0[1]) * (i + 1) / n)
        d.line([a, b], fill=col, width=w)


def _png_segment(d, T, e, pal, ss):
    p0, p1 = T.px(*e["pts"][0]), T.px(*e["pts"][1])
    col = _resolve_color(e.get("stroke", "ink"), pal)
    w = max(1, int(e.get("w", 2) * ss))
    if e.get("dash"):
        _dash_line(d, p0, p1, col, w)
    else:
        d.line([p0, p1], fill=col, width=w)


def _png_point(d, T, e, pal, ss, draw_text):
    cx, cy = T.px(*e["at"])
    rr = e.get("r", 4) * ss
    col = _resolve_color(e.get("fill", "accent"), pal)
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=col)
    if e.get("label"):
        draw_text(e["label"], e["at"], e.get("label_anchor", "ne"),
                  e.get("color", "ink"), e.get("size", 17))


def _png_right_angle(d, T, e, pal, ss):
    at = e["at"]
    a = _unit(at, e["from"])
    b = _unit(at, e["to"])
    s = e.get("size", 0.5)   # in view units
    p0 = T.px(at[0] + a[0] * s, at[1] + a[1] * s)
    p2 = T.px(at[0] + b[0] * s, at[1] + b[1] * s)
    corner = T.px(at[0] + (a[0] + b[0]) * s, at[1] + (a[1] + b[1]) * s)
    col = _resolve_color(e.get("stroke", "ink"), pal)
    d.line([p0, corner, p2], fill=col, width=max(1, int(2 * ss)), joint="curve")


def _unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy) or 1.0
    return (dx / n, dy / n)


# ---------------------------------------------------------------------------
# SVG backend (hand-rolled — no dependency; drawsvg is a drop-in if desired)
# ---------------------------------------------------------------------------
def render_svg(spec: dict, theme: str = "light", out_path: str | None = None) -> str:
    pal = PALETTES[theme]
    T = _Transform(spec)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{T.w}" height="{T.h}" '
           f'viewBox="0 0 {T.w} {T.h}">']
    out.append(f'<rect width="{T.w}" height="{T.h}" fill="{_resolve_color("paper", pal)}"/>')

    def c(name, default="ink"):
        return _resolve_color(name if name is not None else default, pal)

    for e in spec["elements"]:
        t = e["t"]
        if t == "axes":
            out += _svg_axes(T, e, pal)
        elif t == "segment":
            p0, p1 = T.px(*e["pts"][0]), T.px(*e["pts"][1])
            dash = ' stroke-dasharray="6 5"' if e.get("dash") else ""
            out.append(f'<line x1="{p0[0]:.1f}" y1="{p0[1]:.1f}" x2="{p1[0]:.1f}" '
                       f'y2="{p1[1]:.1f}" stroke="{c(e.get("stroke"))}" '
                       f'stroke-width="{e.get("w",2)}"{dash} stroke-linecap="round"/>')
        elif t == "polygon":
            pts = " ".join(f"{T.px(*p)[0]:.1f},{T.px(*p)[1]:.1f}" for p in e["pts"])
            fill = e.get("fill", "none")
            out.append(f'<polygon points="{pts}" fill="'
                       f'{c(fill) if fill not in (None,"none") else "none"}" '
                       f'stroke="{c(e.get("stroke"))}" stroke-width="{e.get("w",2)}" '
                       f'stroke-linejoin="round"/>')
        elif t == "circle":
            cx, cy = T.px(*e["at"]); rr = e["r"] * T.sx
            fill = e.get("fill", "none")
            out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{rr:.1f}" fill="'
                       f'{c(fill) if fill not in (None,"none") else "none"}" '
                       f'stroke="{c(e.get("stroke"))}" stroke-width="{e.get("w",2)}"/>')
        elif t == "point":
            cx, cy = T.px(*e["at"]); rr = e.get("r", 4)
            out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{rr}" '
                       f'fill="{c(e.get("fill","accent"))}"/>')
            if e.get("label"):
                out.append(_svg_text(T, e["label"], e["at"], e.get("label_anchor", "ne"),
                                     c(e.get("color", "ink")), e.get("size", 17)))
        elif t == "right_angle":
            at, a, b = e["at"], _unit(e["at"], e["from"]), _unit(e["at"], e["to"])
            s = e.get("size", 0.5)
            p0 = T.px(at[0] + a[0]*s, at[1] + a[1]*s)
            pc = T.px(at[0] + (a[0]+b[0])*s, at[1] + (a[1]+b[1])*s)
            p2 = T.px(at[0] + b[0]*s, at[1] + b[1]*s)
            out.append(f'<polyline points="{p0[0]:.1f},{p0[1]:.1f} {pc[0]:.1f},{pc[1]:.1f} '
                       f'{p2[0]:.1f},{p2[1]:.1f}" fill="none" stroke="{c(e.get("stroke"))}" '
                       f'stroke-width="2"/>')
        elif t == "label":
            out.append(_svg_text(T, e.get("text", ""), e["at"], e.get("anchor", "center"),
                                 c(e.get("color", "ink")), e.get("size", 18),
                                 e.get("italic", False)))
    out.append("</svg>")
    svg = "\n".join(out)
    if out_path:
        Path(out_path).write_text(svg, encoding="utf-8")
    return svg


def _svg_text(T, text, at, anchor, color, size, italic=False):
    cx, cy = T.px(*at)
    ta = {"w": "start", "nw": "start", "sw": "start",
          "e": "end", "ne": "end", "se": "end"}.get(anchor, "middle")
    # crude vertical anchoring; SVG dominant-baseline gives us the rest
    db = {"n": "hanging", "ne": "hanging", "nw": "hanging",
          "s": "auto", "se": "auto", "sw": "auto"}.get(anchor, "middle")
    style = ' font-style="italic"' if italic else ""
    return (f'<text x="{cx:.1f}" y="{cy:.1f}" fill="{color}" font-size="{size}" '
            f'font-family="Nunito Sans, DejaVu Sans, Arial, sans-serif" '
            f'text-anchor="{ta}" dominant-baseline="{db}"{style}>'
            f'{html.escape(text)}</text>')


def _svg_axes(T, e, pal):
    lines = []
    ax0, ay0 = e.get("x0", T.vx0), e.get("y0", T.vy0)
    ax1, ay1 = e.get("x1", _view_x1(T)), e.get("y1", T.vy1)
    ink = _resolve_color("ink", pal)
    grid = _resolve_color("muted", pal)
    if e.get("grid", False):
        step = e.get("step", 1)
        gx = math.ceil(ax0)
        while gx <= ax1:
            p0, p1 = T.px(gx, ay0), T.px(gx, ay1)
            lines.append(f'<line x1="{p0[0]:.1f}" y1="{p0[1]:.1f}" x2="{p1[0]:.1f}" '
                         f'y2="{p1[1]:.1f}" stroke="{grid}" stroke-width="1"/>')
            gx += step
        gy = math.ceil(ay0)
        while gy <= ay1:
            p0, p1 = T.px(ax0, gy), T.px(ax1, gy)
            lines.append(f'<line x1="{p0[0]:.1f}" y1="{p0[1]:.1f}" x2="{p1[0]:.1f}" '
                         f'y2="{p1[1]:.1f}" stroke="{grid}" stroke-width="1"/>')
            gy += step
    xa0, xa1 = T.px(ax0, 0), T.px(ax1, 0)
    ya0, ya1 = T.px(0, ay0), T.px(0, ay1)
    lines.append(f'<line x1="{xa0[0]:.1f}" y1="{xa0[1]:.1f}" x2="{xa1[0]:.1f}" '
                 f'y2="{xa1[1]:.1f}" stroke="{ink}" stroke-width="2"/>')
    lines.append(f'<line x1="{ya0[0]:.1f}" y1="{ya0[1]:.1f}" x2="{ya1[0]:.1f}" '
                 f'y2="{ya1[1]:.1f}" stroke="{ink}" stroke-width="2"/>')
    return lines


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Render a figure spec to PNG and/or SVG.")
    ap.add_argument("spec")
    ap.add_argument("--png")
    ap.add_argument("--svg")
    ap.add_argument("--theme", default="light", choices=list(PALETTES))
    ap.add_argument("--scale", type=float, default=2.0,
                    help="raster supersample factor (crisper edges)")
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    errs = figure_schema.validate(spec)
    if errs:
        print("SPEC INVALID:")
        for e in errs:
            print("  -", e)
        return 2
    if args.png:
        render_png(spec, args.theme, scale=args.scale, out_path=args.png)
        print(f"png  -> {args.png}")
    if args.svg:
        render_svg(spec, args.theme, out_path=args.svg)
        print(f"svg  -> {args.svg}")
    if not (args.png or args.svg):
        print("nothing to do: pass --png and/or --svg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
