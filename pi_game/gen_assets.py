"""Render the alphabet module's offline assets from content.py.

Produces, under pi_game/assets/:

    letters/<L>/lesson.json     the §14 lesson record
    letters/<L>/letter_big.png  the lesson letter (glyph ~180 px tall, §9)
    letters/<L>/letter_tile.png the touch-stage tile glyph
    letters/<L>/object.png      the flat object illustration
    common/robot_*.png          the robot face states used by the activity

Run on the Pi (Pillow is in the venv there):

    .venv/bin/python -m pi_game.gen_assets [--lang en|kn] [--letters ABC] [--force]

`--lang` picks which content set to render. English writes the flat
`assets/letters/<A>/`; Kannada writes `assets/kn/letters/<slug>/`, its glyphs
rasterized from a Kannada face and its lesson.json carrying the akshara.

Everything is RGBA with a transparent background: the object art is dragged
across the robot's face in the feed activity, so it can never carry an opaque
page-colored box with it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from pi_game import content, languages
from pi_game.content import ERASE, INK

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"

CANVAS = 420                     # art recipes are authored on 420x420

BIG_GLYPH_H = 180                # §9 Typography — "Letter Size 180 px"
BIG_GLYPH_W = 260                # the panel is only 600 px wide
TILE_GLYPH_H = 96                # four-up touch board
TILE_GLYPH_W = 104               # keeps W/M inside a 160 px tile


# ---------------------------------------------------------------------------
# Art


def _lens_points(xy: list[int], steps: int = 40) -> list[tuple[float, float]]:
    """A pointed oval (leaf/seam) inscribed in `xy`: tips at top and bottom.

    Half-width follows sin(pi*t) so both ends come to a true point — an ellipse
    would read as an egg and a polygon as a diamond, and the diamond is exactly
    what made the leaf indistinguishable from the kite.
    """
    import math
    x0, y0, x1, y1 = xy
    cx, half, h = (x0 + x1) / 2, (x1 - x0) / 2, y1 - y0
    right = [(cx + half * math.sin(math.pi * i / steps), y0 + h * i / steps)
             for i in range(steps + 1)]
    left = [(cx - half * math.sin(math.pi * i / steps), y0 + h * i / steps)
            for i in range(steps, -1, -1)]
    return right + left


def _shape(draw: ImageDraw.ImageDraw, p: dict, fill, stencil: bool = False) -> None:
    """Paint one primitive. `fill` is passed in so ERASE can redirect to a mask."""
    t = p["t"]
    # An outline is only meaningful when actually painting; an ERASE pass wants a
    # solid stencil, and an outline color there would just be a hole with a rim.
    edge = None if stencil else p.get("outline")
    ow = p.get("ow", 4)
    if t == "ellipse":
        draw.ellipse(p["xy"], fill=fill, outline=edge, width=ow)
    elif t == "lens":
        draw.polygon(_lens_points(p["xy"]), fill=fill, outline=edge, width=ow)
    elif t == "rect":
        r = p.get("r", 0)
        if r:
            draw.rounded_rectangle(p["xy"], radius=r, fill=fill, outline=edge, width=ow)
        else:
            draw.rectangle(p["xy"], fill=fill, outline=edge, width=ow)
    elif t == "poly":
        draw.polygon([tuple(q) for q in p["pts"]], fill=fill)
    elif t == "line":
        pts = [tuple(q) for q in p["pts"]]
        # joint="curve" only applies to polylines; a 2-point line rejects it.
        kw = {"joint": "curve"} if len(pts) > 2 else {}
        draw.line(pts, fill=fill, width=p.get("w", 8), **kw)
    elif t == "arc":
        draw.arc(p["xy"], p["start"], p["end"], fill=fill, width=p.get("w", 10))
    elif t == "pie":
        draw.pieslice(p["xy"], p["start"], p["end"], fill=fill)
    else:
        raise ValueError(f"unknown art primitive: {t!r}")


def draw_art(recipe: list[dict], size: int = CANVAS) -> Image.Image:
    """Render a content.py art recipe to a transparent RGBA image."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for p in recipe:
        if p["fill"] != ERASE:
            _shape(draw, p, p["fill"])
            continue
        # Punch a hole: paint the shape white on an L mask, then subtract that
        # mask from the canvas's alpha channel.
        mask = Image.new("L", (size, size), 0)
        _shape(ImageDraw.Draw(mask), p, 255, stencil=True)
        img.putalpha(ImageChops.subtract(img.getchannel("A"), mask))
    return img


# ---------------------------------------------------------------------------
# Letters


def _font(px: int, font_path: str) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(font_path, px)
    try:
        # Nunito Sans ships as a variable font whose DEFAULT instance is
        # ExtraLight — a 180 px hairline that reads as broken on the panel.
        # Pin the Bold instance. A static face (the Kannada Regular) has no named
        # instances and raises here — that is fine, we just use its one weight.
        f.set_variation_by_name("Bold")
    except (AttributeError, OSError) as exc:  # pragma: no cover - platform dep
        print(f"  ! variable-font Bold unavailable ({exc}); using default weight")
    return f


def render_letter(ch: str, glyph_h: int, font_path: str, max_w: int | None = None,
                  color: str = INK) -> Image.Image:
    """Render one glyph tight-cropped to `glyph_h` pixels tall, plus padding.

    The font size that yields a given glyph height is font-specific, so measure
    the real ink box once at a reference size and scale from that rather than
    guessing a ratio.
    """
    ref = 200
    f = _font(ref, font_path)
    probe = Image.new("L", (ref * 2, ref * 2), 0)
    ImageDraw.Draw(probe).text((ref // 2, ref // 2), ch, font=f, fill=255)
    box = probe.getbbox()
    if not box:
        raise RuntimeError(f"glyph {ch!r} rendered empty")
    ink_h = box[3] - box[1]
    size = max(8, round(ref * glyph_h / ink_h))

    f = _font(size, font_path)
    big = Image.new("RGBA", (size * 3, size * 3), (0, 0, 0, 0))
    ImageDraw.Draw(big).text((size, size), ch, font=f, fill=color)
    crop = big.crop(big.getbbox())
    # Normalising on height alone makes W and M far wider than the touch tile
    # they have to sit in, so cap the width too and let those letters be shorter.
    if max_w and crop.width > max_w:
        crop = crop.resize((max_w, round(crop.height * max_w / crop.width)),
                           Image.LANCZOS)
    pad = max(6, glyph_h // 12)
    out = Image.new("RGBA", (crop.width + pad * 2, crop.height + pad * 2), (0, 0, 0, 0))
    out.paste(crop, (pad, pad), crop)
    return out


# ---------------------------------------------------------------------------
# Robot face (the feed activity's only other actor)

FACE = "#EFE7D6"
FACE_EDGE = "#C9C4B8"


def robot_face(mouth: str) -> Image.Image:
    """Wini's face at 420x420. `mouth` is "open" | "happy" | "idle"."""
    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([40, 50, 380, 370], radius=70, fill=FACE, outline=FACE_EDGE, width=6)
    if mouth == "happy":
        # Eyes curve into a smile — the only "expression" change, no animation.
        d.arc([120, 150, 190, 210], 200, 340, fill=INK, width=12)
        d.arc([230, 150, 300, 210], 200, 340, fill=INK, width=12)
    else:
        d.ellipse([132, 150, 178, 205], fill=INK)
        d.ellipse([242, 150, 288, 205], fill=INK)
    if mouth == "open":
        d.ellipse([160, 240, 260, 330], fill=content.ROSE)
    elif mouth == "happy":
        d.arc([155, 225, 265, 320], 20, 160, fill=INK, width=12)
    else:
        d.line([(175, 285), (245, 285)], fill=INK, width=12)
    return img


# ---------------------------------------------------------------------------


def build(lang: languages.Language, ids: list[str], force: bool) -> None:
    mod = lang.module
    letters_root = ASSETS / lang.asset_root / "letters"

    # The robot faces are language-neutral and shared from assets/common — the
    # feed activity looks identical whichever alphabet is being taught.
    (ASSETS / "common").mkdir(parents=True, exist_ok=True)
    for name in ("open", "happy", "idle"):
        out = ASSETS / "common" / f"robot_{name}.png"
        if force or not out.exists():
            robot_face(name).save(out)
    print(f"common: 3 robot faces -> {ASSETS / 'common'}")

    # The start-screen language toggle shows each non-Latin language's name in
    # its own script; LVGL can't shape that, so pre-render it to a static image
    # (matches how textimg renders the runtime lines). English stays a text label.
    if lang.code != "en":
        from pi_game import textimg
        import shutil
        label_png = textimg.render(lang.label, lang.font_path, px=46,
                                   color=(122, 116, 102, 255))   # ALPHA_TEXT_MUTED
        dest = ASSETS / "common" / f"label_{lang.code}.png"
        if force or not dest.exists():
            shutil.copyfile(label_png, dest)
        print(f"common: toggle label {lang.label} -> {dest.name}")

    for lid in ids:
        entry = mod.LETTERS[lid]
        glyph = entry.get("char", lid)          # akshara for kn, the letter for en
        d = letters_root / lid
        d.mkdir(parents=True, exist_ok=True)

        if force or not (d / "object.png").exists():
            draw_art(entry["art"]).save(d / "object.png")
        if force or not (d / "letter_big.png").exists():
            render_letter(glyph, BIG_GLYPH_H, lang.font_path, BIG_GLYPH_W).save(
                d / "letter_big.png")
        if force or not (d / "letter_tile.png").exists():
            render_letter(glyph, TILE_GLYPH_H, lang.font_path, TILE_GLYPH_W).save(
                d / "letter_tile.png")

        (d / "lesson.json").write_text(
            json.dumps(mod.lesson_dict(lid), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"  {lid}  {glyph}  {entry['word']}")

    print(f"\n{len(ids)} lessons written under {letters_root}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lang", default="en", choices=sorted(languages.LANGS),
                    help="which alphabet to render (default: en)")
    ap.add_argument("--letters", help="subset of ids, e.g. ABC or 'a aa i' "
                    "(default: the whole set)")
    ap.add_argument("--force", action="store_true", help="redraw existing PNGs")
    args = ap.parse_args()

    lang = languages.get(args.lang)
    mod = lang.module

    if args.letters:
        # English ids are single capitals ("ABC"); Kannada ids are multi-char
        # slugs, so accept a whitespace/comma list there ("a aa i").
        raw = args.letters.replace(",", " ")
        ids = raw.split() if " " in raw or lang.code != "en" else list(raw.upper())
    else:
        ids = list(mod.ORDER)

    unknown = [c for c in ids if c not in mod.LETTERS]
    if unknown:
        print(f"unknown ids for {lang.code}: {' '.join(unknown)}", file=sys.stderr)
        return 2

    build(lang, ids, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
