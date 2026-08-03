# -*- coding: utf-8 -*-
"""Render shaped text to cached PNGs — the Kannada instruction/word/label surface.

Why this exists: LVGL v9 draws a bitmap font codepoint-by-codepoint with no
complex-script shaping (no conjunct formation, no matra positioning). Kannada
needs all of that — ಅಕ್ಷರ, ನಮಸ್ಕಾರ and ಕ್ರೀಂ come out broken — so we do NOT ship
a Kannada LVGL font. Instead the brain renders Kannada text with Pillow + libraqm
(verified present on the Pi: HAVE_RAQM) which shapes correctly, and the UI shows
the result as an image, exactly like it already shows the akshara glyphs.

English text stays as native LVGL labels; only non-Latin lessons come here. PNGs
are cached on disk keyed by (font, size, colour, wrap, text), the same trick the
TTS cache uses, so a lesson renders each line at most once.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "assets" / "text_cache"

INK = (58, 55, 48, 255)          # #3A3730, the page's primary ink (§9)


def _font(font_path: str, px: int):
    from PIL import ImageFont
    try:
        # RAQM is the shaping layout engine; without it Pillow falls back to the
        # same broken codepoint-order layout LVGL would give us.
        return ImageFont.truetype(font_path, px, layout_engine=ImageFont.Layout.RAQM)
    except Exception:
        return ImageFont.truetype(font_path, px)


def _key(text: str, font_path: str, px: int, color, max_w: int) -> str:
    raw = f"{font_path}|{px}|{tuple(color)}|{max_w}|{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    """Greedy word wrap. Each returned line is shaped on its own at draw time."""
    if not max_w:
        return [text]
    lines: list[str] = []
    cur = ""
    for word in text.split(" "):
        trial = word if not cur else cur + " " + word
        if not cur or draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def render(text: str, font_path: str, px: int = 38, color=INK,
           max_w: int = 540) -> Path:
    """Return a transparent PNG of `text`, shaping+wrapping on a cache miss."""
    from PIL import Image, ImageDraw

    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{_key(text, font_path, px, color, max_w)}.png"
    if out.exists():
        return out

    font = _font(font_path, px)
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    lines = _wrap(probe, text, font, max_w)

    asc, desc = font.getmetrics()
    line_h = asc + desc + round(px * 0.18)
    widths = [probe.textlength(ln, font=font) for ln in lines]
    pad = round(px * 0.28)
    w = int(max(widths)) + 2 * pad
    h = line_h * len(lines) + 2 * pad

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = pad
    for ln, lw in zip(lines, widths):
        d.text(((w - lw) / 2, y), ln, font=font, fill=tuple(color))  # centered
        y += line_h

    # Atomic publish so a half-written PNG can never become a permanent broken
    # line. Format is explicit: the .part suffix hides it from Pillow's inference.
    tmp = out.with_suffix(".part")
    img.save(tmp, format="PNG")
    tmp.replace(out)
    return out
