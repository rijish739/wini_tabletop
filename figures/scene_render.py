"""Animated *scene* renderer — the dynamic, narration-synced sibling of
figure_render.py.

A static figure spec answers "what does this look like". A **scene spec** answers
"how does this unfold as I explain it": it carries a timeline of **beats**, each beat
revealing or animating a few elements AND carrying the sentence of narration it goes
with. That coupling is the whole trick — the visual and the speech advance on the
*same* boundary, so they stay in sync without word-level timing (see SCENE_SYNC.md).

This module proves the idea by rendering a scene to an **animated GIF** (each beat's
elements fade / draw-on / move over a few frames, then hold). On-device the same scene
spec drives a live player instead of a GIF: the client speaks beat N's narration and
tells the UI to run beat N's animation — the spec that crosses the wire is ~2 KB.

Animation ops (per element, field ``anim``):
  * ``fade``  — opacity 0->1 (default for points/labels),
  * ``draw``  — progressive reveal of a ``curve``/``segment`` (0->full),
  * ``move``  — a dot rides a quadratic ``quad`` from ``x_from`` to ``x_to``.

Adds one primitive over figure_render: ``curve`` (a quadratic ``quad:[a,b,c]`` sampled
over ``domain`` — closed and safe, no expression ``eval``).

CLI:
    py -3 -m figures.scene_render SCENE.json --gif out.gif --theme light
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from figures.figure_render import (
    PALETTES, _Transform, _resolve_color, _fillc, _unit, _FONT_CANDIDATES,
)


def _font(px):
    from PIL import ImageFont
    for fp in _FONT_CANDIDATES:
        if fp.exists():
            try:
                return ImageFont.truetype(str(fp), int(px))
            except OSError:
                continue
    return ImageFont.load_default()


def _quad_y(quad, x):
    a, b, c = quad
    return a * x * x + b * x + c


# Fields each primitive can't be drawn without. A malformed element (an LLM omits
# `at`, say) must SKIP, never crash a turn — same discipline as tutor_loop's T9 path.
_REQUIRED = {
    "curve": ("quad", "domain"), "tracer": ("quad", "x_from", "x_to"),
    "segment": ("pts",), "polygon": ("pts",), "circle": ("at", "r"),
    "point": ("at",), "right_angle": ("at", "from", "to"), "label": ("at", "text"),
}


def _element_layer(size, T, e, pal, ss, progress):
    """Draw ONE element onto its own transparent RGBA layer at full opacity.
    ``progress`` (0..1) drives geometry for draw/move; opacity is applied by the
    caller so fade is uniform across every primitive."""
    from PIL import Image, ImageDraw
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    t = e.get("t")
    missing = [k for k in _REQUIRED.get(t, ()) if k not in e]
    if t is None or missing:
        if missing:
            print(f"[scene] skipping {t!r} element missing {missing}")
        return layer
    d = ImageDraw.Draw(layer)
    w = max(1, int(e.get("w", 2) * ss))

    if t == "axes":
        _draw_axes(d, T, e, pal, ss)
    elif t == "curve":
        pts = _curve_points(T, e, progress if e.get("anim") == "draw" else 1.0)
        if len(pts) >= 2:
            d.line(pts, fill=_resolve_color(e.get("stroke", "accent"), pal),
                   width=w, joint="curve")
    elif t == "segment":
        p0, p1 = e["pts"][0], e["pts"][1]
        if e.get("anim") == "draw":
            p1 = [p0[0] + (p1[0] - p0[0]) * progress, p0[1] + (p1[1] - p0[1]) * progress]
        a, b = T.px(*p0), T.px(*p1)
        col = _resolve_color(e.get("stroke", "ink"), pal)
        if e.get("dash"):
            _dash(d, a, b, col, w)
        else:
            d.line([a, b], fill=col, width=w)
    elif t == "polygon":
        pts = [T.px(*p) for p in e["pts"]]
        d.polygon(pts, fill=_fillc(e.get("fill", "none"), pal),
                  outline=_fillc(e.get("stroke", "ink"), pal), width=w)
    elif t == "point":
        cx, cy = T.px(*e["at"]); rr = e.get("r", 5) * ss
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                  fill=_resolve_color(e.get("fill", "accent"), pal))
    elif t == "tracer":
        x = e["x_from"] + (e["x_to"] - e["x_from"]) * progress
        cx, cy = T.px(x, _quad_y(e["quad"], x)); rr = e.get("r", 6) * ss
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                  fill=_resolve_color(e.get("fill", "accent2"), pal))
    elif t == "right_angle":
        _draw_right_angle(d, T, e, pal, ss)
    elif t == "label":
        _draw_label(d, T, e, pal, ss)
    return layer


def _curve_points(T, e, progress):
    a, b = e["domain"]
    n = int(e.get("samples", 140))
    k = max(2, int(n * max(0.0, min(1.0, progress))))
    return [T.px(a + (b - a) * i / n, _quad_y(e["quad"], a + (b - a) * i / n))
            for i in range(k + 1)]


def _dash(d, p0, p1, col, w):
    seg = max(1, int(math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / 10))
    for i in range(seg):
        if i % 2:
            continue
        u, v = i / seg, (i + 1) / seg
        d.line([(p0[0] + (p1[0]-p0[0])*u, p0[1] + (p1[1]-p0[1])*u),
                (p0[0] + (p1[0]-p0[0])*v, p0[1] + (p1[1]-p0[1])*v)], fill=col, width=w)


def _draw_axes(d, T, e, pal, ss):
    ax0, ay0 = e.get("x0", T.vx0), e.get("y0", T.vy0)
    ax1, ay1 = e.get("x1", T.vx0 + T.w / T.sx), e.get("y1", T.vy1)
    ink, grid = _resolve_color("ink", pal), _resolve_color("muted", pal)
    if e.get("grid"):
        step = e.get("step", 1)
        gx = math.ceil(ax0)
        while gx <= ax1:
            d.line([T.px(gx, ay0), T.px(gx, ay1)], fill=grid, width=max(1, int(ss)))
            gx += step
        gy = math.ceil(ay0)
        while gy <= ay1:
            d.line([T.px(ax0, gy), T.px(ax1, gy)], fill=grid, width=max(1, int(ss)))
            gy += step
    d.line([T.px(ax0, 0), T.px(ax1, 0)], fill=ink, width=max(1, int(2 * ss)))
    d.line([T.px(0, ay0), T.px(0, ay1)], fill=ink, width=max(1, int(2 * ss)))
    for tip, tail in (((ax1, 0), (ax1 - 0.4, 0)), ((0, ay1), (0, ay1 - 0.4))):
        p1, p0 = T.px(*tip), T.px(*tail)
        ang = math.atan2(p1[1]-p0[1], p1[0]-p0[0])
        for da in (math.radians(150), math.radians(-150)):
            d.line([p1, (p1[0]+9*ss*math.cos(ang+da), p1[1]+9*ss*math.sin(ang+da))],
                   fill=ink, width=max(1, int(2 * ss)))


def _draw_right_angle(d, T, e, pal, ss):
    at, a, b = e["at"], _unit(e["at"], e["from"]), _unit(e["at"], e["to"])
    s = e.get("size", 0.4)
    p0 = T.px(at[0]+a[0]*s, at[1]+a[1]*s)
    pc = T.px(at[0]+(a[0]+b[0])*s, at[1]+(a[1]+b[1])*s)
    p2 = T.px(at[0]+b[0]*s, at[1]+b[1]*s)
    d.line([p0, pc, p2], fill=_resolve_color(e.get("stroke", "ink"), pal),
           width=max(1, int(2 * ss)), joint="curve")


def _draw_label(d, T, e, pal, ss):
    f = _font(e.get("size", 18) * ss)
    text = e.get("text", "")
    bbox = d.textbbox((0, 0), text, font=f)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    cx, cy = (T.px_frac(*e["at"]) if e.get("space") == "canvas" else T.px(*e["at"]))
    anchor = e.get("anchor", "center")
    ax = 0 if anchor in ("w", "nw", "sw") else (-tw/2 if anchor in ("n", "s", "center") else -tw)
    ay = 0 if anchor in ("n", "ne", "nw") else (-th/2 if anchor in ("e", "w", "center") else -th)
    d.text((cx+ax-bbox[0], cy+ay-bbox[1]), text, font=f,
           fill=_resolve_color(e.get("color", "ink"), pal))


def render_gif(scene: dict, theme: str = "light", scale: float = 2.0,
               out_path: str = "scene.gif", fps: int = 25):
    """Render a scene spec to an animated GIF and return the narration timeline."""
    from PIL import Image

    pal = PALETTES[theme]
    ss = max(1.0, float(scale))
    big = dict(scene)
    bc = dict(scene["canvas"])
    bc["w"], bc["h"] = int(bc["w"]*ss), int(bc["h"]*ss)
    if "pad" in bc:
        bc["pad"] = int(bc["pad"]*ss)
    big["canvas"] = bc
    T = _Transform(big)
    size = (T.w, T.h)
    W, H = scene["canvas"]["w"], scene["canvas"]["h"]
    paper = _resolve_color("paper", pal)

    frame_ms = 1000 / fps
    frames, durations, timeline = [], [], []

    def base_frame():
        img = Image.new("RGBA", size, paper)
        for e in scene.get("base", []):
            img = Image.alpha_composite(img, _element_layer(size, T, e, pal, ss, 1.0))
        return img

    revealed: list[dict] = []           # elements from completed beats (drawn full)
    for bi, beat in enumerate(scene["beats"]):
        anim_frames = max(1, round(beat.get("anim_ms", 600) / frame_ms))
        hold_frames = max(1, round(beat.get("hold_ms", 800) / frame_ms))
        timeline.append({"beat": bi, "narration": beat.get("narration", ""),
                         "start_ms": round(sum(durations)),
                         "anim_ms": beat.get("anim_ms", 600),
                         "hold_ms": beat.get("hold_ms", 800)})
        for fi in range(anim_frames + hold_frames):
            p = min(1.0, (fi + 1) / anim_frames)
            img = base_frame()
            for e in revealed:
                img = Image.alpha_composite(img, _element_layer(size, T, e, pal, ss, 1.0))
            for e in beat.get("in", []):
                layer = _element_layer(size, T, e, pal, ss, p)
                if e.get("anim", "fade") == "fade" and p < 1.0:
                    a = layer.getchannel("A").point(lambda v: int(v * p))
                    layer.putalpha(a)
                img = Image.alpha_composite(img, layer)
            fr = img.convert("RGB")
            if ss != 1.0:
                fr = fr.resize((W, H), Image.LANCZOS)
            frames.append(fr)
            durations.append(frame_ms)
        revealed.extend(e for e in beat.get("in", []) if e.get("t") != "tracer")

    frames[0].save(out_path, save_all=True, append_images=frames[1:],
                   duration=[int(d) for d in durations], loop=0, optimize=True,
                   disposal=2)
    return timeline


def render_beat_frame(scene: dict, upto_beat: int, theme: str = "light",
                      scale: float = 1.0, out_path: str | None = None):
    """Render the accumulated state AFTER `upto_beat` (base + every beat's `in`
    elements through beat `upto_beat`) as one still PNG. This is the device
    beat-player's per-beat frame: the visual grows one step as each narration
    sentence is spoken, so the picture and the speech stay coupled without the
    per-frame animation the GIF path uses."""
    from PIL import Image
    pal = PALETTES[theme]
    ss = max(1.0, float(scale))
    bc = dict(scene["canvas"])
    bc["w"], bc["h"] = int(bc["w"] * ss), int(bc["h"] * ss)
    for k in ("pad_top", "pad_bottom", "pad_left", "pad_right", "pad"):
        if k in bc:
            bc[k] = int(bc[k] * ss)
    T = _Transform({"canvas": bc, "view": scene["view"]})
    size = (T.w, T.h)
    img = Image.new("RGBA", size, _resolve_color("paper", pal))
    els = list(scene.get("base", []))
    for b in scene["beats"][:upto_beat + 1]:
        els += list(b.get("in", []))
    for e in els:
        img = Image.alpha_composite(img, _element_layer(size, T, e, pal, ss, 1.0))
    out = img.convert("RGB")
    if ss != 1.0:
        out = out.resize((scene["canvas"]["w"], scene["canvas"]["h"]), Image.LANCZOS)
    if out_path:
        out.save(out_path)
    return out


def bench(scene: dict, theme: str = "light") -> None:
    """Measure on-device render cost: per-frame time (scale 1 and 2) + process RSS.
    Run this straight on the Pi: `py -3 -m figures.scene_render SCENE.json --bench`."""
    import time
    from PIL import Image
    pal = PALETTES[theme]
    els = list(scene.get("base", [])) + [e for b in scene["beats"] for e in b.get("in", [])]
    print(f"scene: {len(scene['beats'])} beats, {len(els)} elements")
    for scale in (1.0, 2.0):
        bc = dict(scene["canvas"])
        bc["w"], bc["h"] = int(bc["w"] * scale), int(bc["h"] * scale)
        for k in ("pad_top", "pad_bottom", "pad_left", "pad_right"):
            if k in bc:
                bc[k] = int(bc[k] * scale)
        T = _Transform({"canvas": bc, "view": scene["view"]})
        size = (T.w, T.h)
        for e in els[:2]:
            _element_layer(size, T, e, pal, scale, 1.0)     # warm
        t = time.perf_counter(); N = 30
        for _ in range(N):
            img = Image.new("RGBA", size, pal["paper"])
            for e in els:
                img = Image.alpha_composite(img, _element_layer(size, T, e, pal, scale, 1.0))
            fr = img.convert("RGB")
            if scale != 1.0:
                fr = fr.resize((scene["canvas"]["w"], scene["canvas"]["h"]), Image.LANCZOS)
        print(f"  scale {scale}: {(time.perf_counter()-t)/N*1000:.1f} ms/frame ({size[0]}x{size[1]})")
    rss = None
    try:
        import psutil
        rss = psutil.Process().memory_info().rss
    except ImportError:
        try:                                  # Linux fallback: /proc/self/status
            for ln in Path("/proc/self/status").read_text().splitlines():
                if ln.startswith("VmRSS:"):
                    rss = int(ln.split()[1]) * 1024
                    break
        except OSError:
            pass
    print(f"  process RSS: {rss/1e6:.0f} MB" if rss else "  (RSS unavailable)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Render a scene spec to an animated GIF.")
    ap.add_argument("scene")
    ap.add_argument("--gif", default="scene.gif")
    ap.add_argument("--theme", default="light", choices=list(PALETTES))
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--fps", type=int, default=25)
    ap.add_argument("--bench", action="store_true", help="measure render time + RAM, no GIF")
    args = ap.parse_args()
    scene = json.loads(Path(args.scene).read_text(encoding="utf-8"))
    if args.bench:
        bench(scene, args.theme)
        return 0
    timeline = render_gif(scene, args.theme, args.scale, args.gif, args.fps)
    print(f"gif -> {args.gif}")
    print("narration timeline (beat @ start_ms):")
    for t in timeline:
        print(f"  [{t['start_ms']:>5} ms] {t['narration']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
