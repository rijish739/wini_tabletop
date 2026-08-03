import os
import io
import math
import json
import re
import time
from PIL import Image, ImageDraw, ImageFont

# Matplotlib LaTeX Math Engine
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except Exception:
    MATPLOTLIB_AVAILABLE = False

def sanitize_text(text):
    """
    Normalizes all whitespace to single spaces — collapses internal runs, tabs,
    newlines, and carriage returns, and strips leading/trailing whitespace.

    Uses ' '.join(text.split()) — str.split() with no args splits on ANY whitespace
    (space, tab, \n, \r, \f) and collapses runs, making regex unnecessary.

    DESIGN INTENT: Emoji are deliberately NOT stripped here.
    DejaVu fonts cannot render emoji — they appear as tofu boxes (□).
    This is intentional: a tofu box on screen is a passive visual debug signal
    that the AI agent passed emoji in a text field instead of using draw_stickers().
    It costs nothing and immediately tells a developer the system prompt needs tightening.
    """
    if not text:
        return ""
    return " ".join(text.split())


# Superscript unicode so a plain answer like "x^2" renders inline in the normal
# font instead of being force-routed to a giant, space-collapsed LaTeX image.
_SUP = {"0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶",
        "7": "⁷", "8": "⁸", "9": "⁹", "+": "⁺", "-": "⁻", "n": "ⁿ"}


def _to_display_text(s):
    """Plain-text math prettifier used for NON-LaTeX board text: 'x^2' -> 'x²',
    '*' -> '×'. Crucially it keeps ALL word spacing — LaTeX math mode does not,
    which is what merged 'Solve x' into 'Solvex'. Only simple single-token
    exponents are converted; everything else is left verbatim and readable."""
    if not s:
        return ""
    import re as _re

    def _sup(m):
        return "".join(_SUP.get(ch, "^" + ch) for ch in m.group(1))

    s = _re.sub(r"\^\{?(-?[0-9]+|[a-zA-Z])\}?", _sup, s)
    return s.replace("\\times", "×").replace("\\cdot", "·").replace("*", "×")


def _looks_like_latex(s, mode=""):
    """True only for GENUINE LaTeX the math engine should rasterise: an explicit
    math mode, a '$...$' span, or a backslash command. A stray '^' or '=' in an
    otherwise plain sentence is NOT LaTeX — routing those to LaTeX is what made
    titles huge and collapsed their inter-word spaces."""
    if mode in ("math", "latex"):
        return True
    if not s:
        return False
    return ("$" in s) or ("\\" in s)


def _safe_int(value, default=0):
    """int() that never raises. An UNSUBSTITUTED animation placeholder (e.g.
    '{num_r:int}' when a payload with animated vars is rendered as a static frame),
    None, or any garbage degrades to `default` instead of crashing the whole board
    render. 'Produce a static image' must always beat 'crash'."""
    try:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        return int(round(float(str(value).strip())))
    except (TypeError, ValueError):
        return default


# A leftover Board Buddy placeholder carrying a format spec — "{num_r:int}",
# "{a:2f}" — that no animation var resolved (static render, or a var the payload
# never defined). Only the SPEC form is matched when embedded: a spec is something
# LaTeX groups (\frac{a}{b}, x^{2}) never use, so we never corrupt real maths.
_LEFTOVER_SPEC_PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_]\w*:\w+\}")


def _resolve_leftover_placeholder(s):
    """Turn an UNRESOLVED placeholder into a safe value so it never reaches int()/
    float() downstream (the animated-payload static-render crash). A whole-string
    placeholder becomes typed 0 (int for :int/:d, else 0.0); an embedded spec token
    is replaced by '0'. Plain strings and LaTeX ('\\frac{a}{b}') pass through."""
    whole = re.fullmatch(r"\s*\{[A-Za-z_]\w*(?::(\w+))?\}\s*", s)
    if whole:
        spec = (whole.group(1) or "").lower()
        return 0 if spec in ("", "int", "d", "0f") else 0.0
    if ":" in s and "{" in s:
        return _LEFTOVER_SPEC_PLACEHOLDER_RE.sub("0", s)
    return s

# Cross-platform font resolution. The old code hard-coded a Linux-only DejaVu
# path; on Windows and on the lean Cloud Run image that file does not exist, so
# every ImageFont.truetype() raised and PIL fell back to its FIXED-SIZE bitmap
# default. That default ignores the requested point size and has no real metrics —
# which is exactly why board text rendered tiny, cramped and unaligned regardless
# of the "large"/"medium" size. Resolve a real scalable TTF once (matplotlib ships
# DejaVu with the package, so it is a reliable last resort even in a bare image)
# and cache both the file path and the sized ImageFont objects.
_FONT_FILE_CACHE = {}
_FONT_OBJ_CACHE = {}


def _resolve_font_file(bold=True):
    key = bool(bold)
    if key in _FONT_FILE_CACHE:
        return _FONT_FILE_CACHE[key]
    names = (["DejaVuSans-Bold.ttf", "arialbd.ttf", "seguisb.ttf"]
             if bold else ["DejaVuSans.ttf", "arial.ttf", "segoeui.ttf"])
    dirs = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu",
            "C:/Windows/Fonts", "/Library/Fonts",
            "/System/Library/Fonts/Supplemental"]
    # matplotlib bundles DejaVu inside the package — present whenever it imported.
    if MATPLOTLIB_AVAILABLE:
        try:
            dirs.insert(0, os.path.join(matplotlib.get_data_path(), "fonts", "ttf"))
        except Exception:
            pass
    for d in dirs:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                _FONT_FILE_CACHE[key] = p
                return p
    _FONT_FILE_CACHE[key] = None
    return None


def _load_font(size, bold=True):
    size = max(9, int(round(size)))
    key = (bool(bold), size)
    if key in _FONT_OBJ_CACHE:
        return _FONT_OBJ_CACHE[key]
    path = _resolve_font_file(bold)
    font = None
    if path:
        try:
            font = ImageFont.truetype(path, size)
        except Exception:
            font = None
    if font is None:
        font = ImageFont.load_default()
    _FONT_OBJ_CACHE[key] = font
    return font


def get_fitted_font(text, max_width, initial_size=22, bold=True):
    """Largest scalable font (down to 9pt) whose rendered width fits max_width."""
    size = max(9, int(round(initial_size)))
    while size > 9:
        font = _load_font(size, bold=bold)
        try:
            bbox = font.getbbox(text or "")
            if (bbox[2] - bbox[0]) <= max_width:
                return font
        except Exception:
            return font
        size -= 1
    return _load_font(9, bold=bold)

def ease_in_out_cubic(t):
    t = max(0.0, min(1.0, t))
    return 4 * t * t * t if t < 0.5 else 1.0 - math.pow(-2 * t + 2, 3) / 2.0

def render_latex_to_pil(latex_str, font_size=18, color="#000000", max_width=520, dpi=140):
    """Renders explicit LaTeX math expression to RGBA PIL Image and auto-scales down if image width exceeds max_width."""
    if not MATPLOTLIB_AVAILABLE:
        return None
    try:
        clean_str = latex_str.strip()
        if not clean_str.startswith("$") and not clean_str.endswith("$"):
            clean_str = f"${clean_str}$"

        fig = plt.figure(figsize=(0.1, 0.1), dpi=dpi)
        fig.patch.set_alpha(0.0)
        fig.text(0, 0, clean_str, fontsize=font_size, color=color, usetex=False)
        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.04, transparent=True, dpi=dpi)
        plt.close(fig)
        buf.seek(0)
        img = Image.open(buf).convert("RGBA")

        # Auto-Scaling Engine for LaTeX Images: Scale down if image width exceeds max_width
        if max_width and img.width > max_width:
            scale_factor = float(max_width) / float(img.width)
            new_w = int(max_width)
            new_h = int(img.height * scale_factor)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        return img
    except Exception as e:
        print(f"[BoardBuddy] Safe Fallback - LaTeX render error for '{latex_str}': {e}")
        return None
    finally:
        plt.close('all')

def measure_latex_width(latex_str, font_size=18, dpi=140):
    """Helper to measure exact pixel width of any LaTeX prefix string."""
    img = render_latex_to_pil(latex_str, font_size=font_size, color="#000000", max_width=None, dpi=dpi)
    return img.width if img else 0

# ==============================================================================
# 🎨 LIGHTWEIGHT NORMALIZED VECTOR STICKERS ENGINE (100x100 Bounding Box Model)
# 60+ Self-Contained Vector Icons — 100% Zero External File Dependencies
# ==============================================================================
VECTOR_STICKERS = {
    # --- CLASSIC ITEMS (6) ---
    "apple": [
        ("ellipse", [12, 20, 88, 92], "#EB281E", "#B4140A", 2),
        ("ellipse", [22, 30, 48, 52], "#FF786E", None, 0),
        ("polygon", [(50, 20), (75, 5), (55, 12)], "#2DB437", "#1E7823", 2),
        ("line", [(50, 20), (45, 5)], "#643214", 3)
    ],
    "star": [
        ("polygon", [(50,5), (63,35), (95,38), (71,60), (78,92), (50,75), (22,92), (29,60), (5,38), (37,35)], "#FFD700", "#D28C00", 2),
        ("polygon", [(50,20), (58,40), (80,42), (63,56), (68,78), (50,66), (32,78), (37,56), (20,42), (42,40)], "#FFF28C", None, 0)
    ],
    "soccer": [
        ("ellipse", [10, 10, 90, 90], "#FFFFFF", "#1E1E1E", 2),
        ("polygon", [(50, 28), (68, 40), (61, 62), (39, 62), (32, 40)], "#1E1E1E", None, 0),
        ("line", [(50, 28), (50, 10)], "#1E1E1E", 2),
        ("line", [(68, 40), (88, 32)], "#1E1E1E", 2),
        ("line", [(61, 62), (76, 80)], "#1E1E1E", 2),
        ("line", [(39, 62), (24, 80)], "#1E1E1E", 2),
        ("line", [(32, 40), (12, 32)], "#1E1E1E", 2)
    ],
    "ball": [
        ("ellipse", [10, 10, 90, 90], "#FFFFFF", "#1E1E1E", 2),
        ("polygon", [(50, 28), (68, 40), (61, 62), (39, 62), (32, 40)], "#1E1E1E", None, 0),
        ("line", [(50, 28), (50, 10)], "#1E1E1E", 2),
        ("line", [(68, 40), (88, 32)], "#1E1E1E", 2),
        ("line", [(61, 62), (76, 80)], "#1E1E1E", 2),
        ("line", [(39, 62), (24, 80)], "#1E1E1E", 2),
        ("line", [(32, 40), (12, 32)], "#1E1E1E", 2)
    ],
    "car": [
        ("rectangle", [10, 45, 90, 75], "#DC2626", "#961414", 2),
        ("polygon", [(20, 45), (35, 20), (65, 20), (80, 45)], "#29B6F6", "#145A96", 2),
        ("ellipse", [20, 65, 40, 85], "#1E1E1E", "#CCCCCC", 3),
        ("ellipse", [60, 65, 80, 85], "#1E1E1E", "#CCCCCC", 3)
    ],
    "coin": [
        ("ellipse", [10, 10, 90, 90], "#FFD700", "#B48C00", 3),
        ("ellipse", [22, 22, 78, 78], None, "#C89600", 2),
        ("line", [(42, 32), (58, 32)], "#7E5109", 3),
        ("line", [(42, 44), (58, 44)], "#7E5109", 3),
        ("line", [(50, 32), (50, 70)], "#7E5109", 3)
    ],
    "tree": [
        ("rectangle", [42, 55, 58, 92], "#6E3C14", "#46230A", 2),
        ("polygon", [(15, 60), (50, 25), (85, 60)], "#2E7D32", "#1B5E20", 2),
        ("polygon", [(25, 38), (50, 10), (75, 38)], "#4CAF50", "#2E7D32", 2)
    ],

    # --- ANIMALS (10) ---
    "cat": [
        ("ellipse", [15, 30, 85, 85], "#FF9800", "#E65100", 2),
        ("polygon", [(18, 35), (32, 10), (42, 32)], "#FF9800", "#E65100", 2),
        ("polygon", [(58, 32), (68, 10), (82, 35)], "#FF9800", "#E65100", 2),
        ("ellipse", [30, 48, 42, 60], "#212121", None, 0),
        ("ellipse", [58, 48, 70, 60], "#212121", None, 0),
        ("polygon", [(46, 62), (54, 62), (50, 68)], "#E91E63", None, 0),
        ("line", [(15, 60), (35, 62)], "#212121", 2),
        ("line", [(85, 60), (65, 62)], "#212121", 2)
    ],
    "dog": [
        ("ellipse", [20, 25, 80, 80], "#8D6E63", "#4E342E", 2),
        ("ellipse", [10, 30, 30, 65], "#5D4037", "#3E2723", 2),
        ("ellipse", [70, 30, 90, 65], "#5D4037", "#3E2723", 2),
        ("ellipse", [32, 42, 42, 52], "#212121", None, 0),
        ("ellipse", [58, 42, 68, 52], "#212121", None, 0),
        ("ellipse", [43, 56, 57, 68], "#212121", None, 0)
    ],
    "fish": [
        ("ellipse", [15, 25, 75, 75], "#FF7043", "#D84315", 2),
        ("polygon", [(70, 50), (92, 30), (92, 70)], "#FF7043", "#D84315", 2),
        ("ellipse", [28, 40, 36, 48], "#212121", None, 0),
        ("arc", [40, 35, 65, 65], 270, 90, "#D84315", 2)
    ],
    "bird": [
        ("ellipse", [20, 30, 70, 75], "#29B6F6", "#0288D1", 2),
        ("polygon", [(65, 45), (88, 50), (65, 58)], "#FFB74D", "#F57C00", 2),
        ("ellipse", [45, 40, 53, 48], "#212121", None, 0),
        ("polygon", [(15, 55), (35, 40), (25, 75)], "#0288D1", None, 0)
    ],
    "butterfly": [
        ("ellipse", [15, 15, 48, 48], "#EC407A", "#C2185B", 2),
        ("ellipse", [52, 15, 85, 48], "#EC407A", "#C2185B", 2),
        ("ellipse", [20, 48, 45, 78], "#AB47BC", "#7B1FA2", 2),
        ("ellipse", [55, 48, 80, 78], "#AB47BC", "#7B1FA2", 2),
        ("rectangle", [46, 20, 54, 80], "#212121", "#000000", 1)
    ],
    "rabbit": [
        ("ellipse", [25, 40, 75, 85], "#E0E0E0", "#9E9E9E", 2),
        ("ellipse", [30, 10, 45, 48], "#E0E0E0", "#9E9E9E", 2),
        ("ellipse", [55, 10, 70, 48], "#E0E0E0", "#9E9E9E", 2),
        ("ellipse", [38, 52, 46, 60], "#212121", None, 0),
        ("ellipse", [54, 52, 62, 60], "#212121", None, 0),
        ("ellipse", [46, 64, 54, 70], "#EC407A", None, 0)
    ],
    "duck": [
        ("ellipse", [20, 45, 75, 82], "#FBC02D", "#F57F17", 2),
        ("ellipse", [45, 20, 75, 50], "#FBC02D", "#F57F17", 2),
        ("polygon", [(70, 32), (92, 36), (70, 44)], "#FB8C00", "#E65100", 2),
        ("ellipse", [58, 28, 64, 34], "#212121", None, 0)
    ],
    "frog": [
        ("ellipse", [15, 35, 85, 80], "#66BB6A", "#388E3C", 2),
        ("ellipse", [22, 20, 42, 42], "#66BB6A", "#388E3C", 2),
        ("ellipse", [58, 20, 78, 42], "#66BB6A", "#388E3C", 2),
        ("ellipse", [28, 26, 36, 34], "#212121", None, 0),
        ("ellipse", [64, 26, 74, 34], "#212121", None, 0),
        ("arc", [35, 50, 65, 70], 0, 180, "#1B5E20", 2)
    ],
    "bee": [
        ("ellipse", [20, 30, 80, 75], "#FFD54F", "#FFB300", 2),
        ("rectangle", [38, 30, 46, 75], "#212121", None, 0),
        ("rectangle", [56, 30, 64, 75], "#212121", None, 0),
        ("ellipse", [25, 12, 48, 34], "#E0F7FA", "#80DEEA", 2),
        ("ellipse", [52, 12, 75, 34], "#E0F7FA", "#80DEEA", 2)
    ],
    "ladybug": [
        ("ellipse", [20, 25, 80, 85], "#E53935", "#B71C1C", 2),
        ("ellipse", [38, 12, 62, 32], "#212121", None, 0),
        ("line", [(50, 30), (50, 85)], "#212121", 3),
        ("ellipse", [30, 42, 40, 52], "#212121", None, 0),
        ("ellipse", [60, 42, 70, 52], "#212121", None, 0),
        ("ellipse", [34, 64, 44, 74], "#212121", None, 0),
        ("ellipse", [56, 64, 66, 74], "#212121", None, 0)
    ],

    # --- FRUITS & FOOD (10) ---
    "banana": [
        ("arc", [15, 15, 85, 85], 30, 160, "#FFEB3B", 14),
        ("polygon", [(15, 45), (12, 40), (20, 42)], "#795548", None, 0)
    ],
    "orange": [
        ("ellipse", [15, 15, 85, 85], "#FFA726", "#FB8C00", 2),
        ("ellipse", [45, 10, 55, 18], "#4CAF50", None, 0)
    ],
    "strawberry": [
        ("polygon", [(20, 25), (80, 25), (50, 90)], "#E53935", "#C62828", 2),
        ("ellipse", [35, 15, 65, 30], "#4CAF50", None, 0),
        ("ellipse", [35, 40, 40, 46], "#FFEB3B", None, 0),
        ("ellipse", [60, 40, 65, 46], "#FFEB3B", None, 0),
        ("ellipse", [48, 60, 53, 66], "#FFEB3B", None, 0)
    ],
    "grape": [
        ("ellipse", [35, 30, 55, 50], "#8E24AA", None, 0),
        ("ellipse", [50, 30, 70, 50], "#8E24AA", None, 0),
        ("ellipse", [25, 48, 45, 68], "#8E24AA", None, 0),
        ("ellipse", [42, 48, 62, 68], "#8E24AA", None, 0),
        ("ellipse", [58, 48, 78, 68], "#8E24AA", None, 0),
        ("ellipse", [42, 66, 62, 86], "#8E24AA", None, 0),
        ("line", [(50, 10), (50, 30)], "#5D4037", 3)
    ],
    "watermelon": [
        ("arc", [10, 10, 90, 90], 0, 180, "#2E7D32", 6),
        ("polygon", [(15, 50), (85, 50), (50, 85)], "#E53935", None, 0),
        ("ellipse", [35, 60, 40, 66], "#212121", None, 0),
        ("ellipse", [60, 60, 65, 66], "#212121", None, 0),
        ("ellipse", [48, 72, 53, 78], "#212121", None, 0)
    ],
    "carrot": [
        ("polygon", [(30, 25), (70, 25), (50, 92)], "#FB8C00", "#EF6C00", 2),
        ("polygon", [(40, 25), (30, 8), (50, 20)], "#4CAF50", None, 0),
        ("polygon", [(50, 25), (70, 8), (60, 20)], "#4CAF50", None, 0)
    ],
    "mango": [
        ("ellipse", [20, 20, 80, 85], "#FFB300", "#F57F17", 2),
        ("ellipse", [45, 12, 55, 22], "#4CAF50", None, 0)
    ],
    "pizza": [
        ("polygon", [(15, 20), (85, 20), (50, 88)], "#FFB74D", "#E65100", 2),
        ("polygon", [(20, 26), (80, 26), (50, 82)], "#FBC02D", None, 0),
        ("ellipse", [35, 38, 48, 51], "#D32F2F", None, 0),
        ("ellipse", [55, 45, 68, 58], "#D32F2F", None, 0),
        ("ellipse", [42, 62, 52, 72], "#D32F2F", None, 0)
    ],
    "cake": [
        ("rectangle", [20, 45, 80, 82], "#F8BBD0", "#C2185B", 2),
        ("rectangle", [20, 45, 80, 55], "#FFFFFF", None, 0),
        ("rectangle", [46, 20, 54, 45], "#E0E0E0", None, 0),
        ("ellipse", [45, 10, 55, 22], "#FF9800", None, 0)
    ],
    "ice_cream": [
        ("polygon", [(30, 45), (70, 45), (50, 92)], "#D7CCC8", "#8D6E63", 2),
        ("ellipse", [25, 18, 75, 52], "#F48FB1", "#AD1457", 2),
        ("ellipse", [44, 8, 56, 20], "#D32F2F", None, 0)
    ],

    # --- SCHOOL & LEARNING (10) ---
    "pencil": [
        ("polygon", [(40, 15), (60, 15), (60, 70), (40, 70)], "#FFCA28", "#FF8F00", 2),
        ("polygon", [(40, 70), (60, 70), (50, 92)], "#FFE0B2", "#D7CCC8", 1),
        ("polygon", [(47, 85), (53, 85), (50, 92)], "#212121", None, 0),
        ("rectangle", [40, 15, 60, 25], "#EC407A", None, 0)
    ],
    "book": [
        ("rectangle", [15, 25, 85, 75], "#42A5F5", "#1565C0", 2),
        ("rectangle", [22, 30, 78, 70], "#FFFFFF", None, 0),
        ("line", [(50, 25), (50, 75)], "#1565C0", 2)
    ],
    "ruler": [
        ("rectangle", [10, 35, 90, 65], "#FFE082", "#FF8F00", 2),
        ("line", [(20, 35), (20, 48)], "#212121", 2),
        ("line", [(35, 35), (35, 48)], "#212121", 2),
        ("line", [(50, 35), (50, 52)], "#212121", 2),
        ("line", [(65, 35), (65, 48)], "#212121", 2),
        ("line", [(80, 35), (80, 48)], "#212121", 2)
    ],
    "scissors": [
        ("ellipse", [15, 60, 40, 85], "#E53935", None, 0),
        ("ellipse", [60, 60, 85, 85], "#E53935", None, 0),
        ("line", [(30, 65), (65, 20)], "#B0BEC5", 4),
        ("line", [(70, 65), (35, 20)], "#B0BEC5", 4)
    ],
    "backpack": [
        ("rectangle", [22, 28, 78, 85], "#5C6BC0", "#283593", 2),
        ("rectangle", [32, 50, 68, 75], "#3F51B5", "#1A237E", 2),
        ("arc", [35, 12, 65, 35], 180, 360, "#283593", 3)
    ],
    "magnifier": [
        ("ellipse", [15, 15, 65, 65], "#E0F7FA", "#00838F", 4),
        ("line", [(52, 52), (85, 85)], "#424242", 8)
    ],
    "eraser": [
        ("polygon", [(20, 40), (55, 20), (80, 50), (45, 70)], "#EF5350", "#C62828", 2),
        ("polygon", [(45, 70), (80, 50), (70, 62), (35, 82)], "#B0BEC5", "#37474F", 2)
    ],
    "globe": [
        ("ellipse", [20, 20, 80, 80], "#4FC3F7", "#0288D1", 2),
        ("ellipse", [35, 35, 65, 65], "#81C784", None, 0),
        ("arc", [12, 10, 88, 90], 210, 30, "#795548", 4),
        ("line", [(50, 85), (50, 98)], "#795548", 4)
    ],
    "clock": [
        ("ellipse", [10, 10, 90, 90], "#FFFFFF", "#37474F", 3),
        ("line", [(50, 50), (50, 25)], "#212121", 3),
        ("line", [(50, 50), (70, 50)], "#E53935", 2),
        ("ellipse", [46, 46, 54, 54], "#212121", None, 0)
    ],
    "lightbulb": [
        ("ellipse", [25, 15, 75, 65], "#FFEB3B", "#FBC02D", 2),
        ("rectangle", [38, 62, 62, 80], "#B0BEC5", "#37474F", 2),
        ("rectangle", [42, 80, 58, 88], "#78909C", None, 0)
    ],

    # --- MATH & SHAPES (10) ---
    "heart": [
        ("polygon", [(50, 88), (15, 48), (20, 25), (42, 22), (50, 38), (58, 22), (80, 25), (85, 48)], "#E91E63", "#AD1457", 2)
    ],
    "diamond": [
        ("polygon", [(50, 10), (90, 50), (50, 90), (10, 50)], "#AB47BC", "#6A1B9A", 2)
    ],
    "hexagon": [
        ("polygon", [(50, 10), (85, 30), (85, 70), (50, 90), (15, 70), (15, 30)], "#26A69A", "#00695C", 2)
    ],
    "pentagon": [
        ("polygon", [(50, 10), (90, 40), (75, 90), (25, 90), (10, 40)], "#FFA726", "#EF6C00", 2)
    ],
    "crescent": [
        ("ellipse", [15, 15, 85, 85], "#FFCA28", "#FF8F00", 2),
        ("ellipse", [32, 10, 95, 85], "#F7EBD9", None, 0)
    ],
    "triangle_shape": [
        ("polygon", [(50, 12), (90, 88), (10, 88)], "#42A5F5", "#1565C0", 3)
    ],
    "square_shape": [
        ("rectangle", [15, 15, 85, 85], "#66BB6A", "#2E7D32", 3)
    ],
    "circle_shape": [
        ("ellipse", [12, 12, 88, 88], "#EC407A", "#AD1457", 3)
    ],
    "plus_sign": [
        ("rectangle", [42, 15, 58, 85], "#26C6DA", "#00838F", 1),
        ("rectangle", [15, 42, 85, 58], "#26C6DA", "#00838F", 1)
    ],
    "minus_sign": [
        ("rectangle", [15, 42, 85, 58], "#FF7043", "#D84315", 1)
    ],

    # --- NATURE & ENVIRONMENT (8) ---
    "sun": [
        ("ellipse", [30, 30, 70, 70], "#FFD700", "#F57F17", 2),
        ("line", [(50, 8), (50, 24)], "#FFB300", 3),
        ("line", [(50, 76), (50, 92)], "#FFB300", 3),
        ("line", [(8, 50), (24, 50)], "#FFB300", 3),
        ("line", [(76, 50), (92, 50)], "#FFB300", 3)
    ],
    "moon": [
        ("ellipse", [20, 15, 85, 85], "#FFF176", "#FBC02D", 2),
        ("ellipse", [38, 10, 95, 85], "#F7EBD9", None, 0)
    ],
    "cloud": [
        ("ellipse", [15, 45, 85, 80], "#E0F7FA", "#80DEEA", 2),
        ("ellipse", [25, 30, 55, 60], "#E0F7FA", None, 0),
        ("ellipse", [45, 25, 75, 60], "#E0F7FA", None, 0)
    ],
    "raindrop": [
        ("polygon", [(50, 10), (80, 60), (50, 88), (20, 60)], "#29B6F6", "#0288D1", 2)
    ],
    "flower": [
        ("ellipse", [32, 12, 68, 48], "#EC407A", None, 0),
        ("ellipse", [32, 52, 68, 88], "#EC407A", None, 0),
        ("ellipse", [12, 32, 48, 68], "#EC407A", None, 0),
        ("ellipse", [52, 32, 88, 68], "#EC407A", None, 0),
        ("ellipse", [35, 35, 65, 65], "#FFD54F", "#FFB300", 2)
    ],
    "leaf": [
        ("polygon", [(20, 80), (30, 20), (80, 30)], "#66BB6A", "#2E7D32", 2),
        ("line", [(20, 80), (60, 40)], "#2E7D32", 2)
    ],
    "snowflake": [
        ("line", [(50, 10), (50, 90)], "#80DEEA", 3),
        ("line", [(10, 50), (90, 50)], "#80DEEA", 3),
        ("line", [(22, 22), (78, 78)], "#80DEEA", 3),
        ("line", [(78, 22), (22, 78)], "#80DEEA", 3)
    ],
    "mountain": [
        ("polygon", [(10, 85), (45, 20), (80, 85)], "#78909C", "#37474F", 2),
        ("polygon", [(35, 38), (45, 20), (55, 38)], "#FFFFFF", None, 0)
    ],

    # --- TRANSPORT & REWARDS (6) ---
    "bus": [
        ("rectangle", [15, 20, 85, 70], "#FFCA28", "#FF8F00", 2),
        ("rectangle", [22, 30, 45, 45], "#E0F7FA", None, 0),
        ("rectangle", [55, 30, 78, 45], "#E0F7FA", None, 0),
        ("ellipse", [25, 62, 40, 77], "#212121", None, 0),
        ("ellipse", [60, 62, 75, 77], "#212121", None, 0)
    ],
    "bicycle": [
        ("ellipse", [15, 45, 45, 75], None, "#37474F", 3),
        ("ellipse", [55, 45, 85, 75], None, "#37474F", 3),
        ("line", [(30, 60), (50, 35)], "#E53935", 3),
        ("line", [(50, 35), (70, 60)], "#E53935", 3)
    ],
    "airplane": [
        ("polygon", [(10, 50), (80, 45), (92, 50), (80, 55)], "#ECEFF1", "#607D8B", 2),
        ("polygon", [(45, 48), (30, 15), (55, 48)], "#CFD8DC", "#607D8B", 2),
        ("polygon", [(45, 52), (30, 85), (55, 52)], "#CFD8DC", "#607D8B", 2)
    ],
    "boat": [
        ("polygon", [(15, 55), (85, 55), (75, 80), (25, 80)], "#8D6E63", "#4E342E", 2),
        ("polygon", [(50, 15), (78, 48), (50, 48)], "#FFFFFF", "#B0BEC5", 2),
        ("line", [(50, 15), (50, 55)], "#3E2723", 2)
    ],
    "house": [
        ("rectangle", [22, 45, 78, 85], "#FFE0B2", "#E65100", 2),
        ("polygon", [(15, 45), (50, 15), (85, 45)], "#E53935", "#B71C1C", 2),
        ("rectangle", [42, 60, 58, 85], "#8D6E63", None, 0)
    ],
    "trophy": [
        ("polygon", [(25, 15), (75, 15), (65, 55), (35, 55)], "#FFD700", "#FF8F00", 2),
        ("rectangle", [44, 55, 56, 75], "#FFB300", None, 0),
        ("rectangle", [30, 75, 70, 88], "#795548", "#3E2723", 2)
    ],
    # --- PEOPLE & KIDS (MINIMAL MODERN STYLE) ---
    "boy": [
        ("ellipse", [30, 8, 70, 48], "#F5C29B", "#D39E77", 2),  # Head
        ("polygon", [(28, 20), (38, 5), (62, 5), (72, 20), (50, 14)], "#2C3E50", None, 0),  # Hair
        ("rectangle", [32, 48, 68, 74], "#3498DB", "#2980B9", 2),  # Blue T-shirt
        ("line", [(32, 52), (14, 64)], "#F5C29B", 4),  # Left Arm
        ("line", [(68, 52), (86, 64)], "#F5C29B", 4),  # Right Arm
        ("rectangle", [34, 74, 48, 88], "#2C3E50", None, 0),  # Left Pants
        ("rectangle", [52, 74, 66, 88], "#2C3E50", None, 0),  # Right Pants
        ("ellipse", [30, 86, 48, 96], "#ECF0F1", "#BDC3C7", 1),  # Left Sneaker
        ("ellipse", [52, 86, 70, 96], "#ECF0F1", "#BDC3C7", 1),  # Right Sneaker
        ("ellipse", [40, 24, 46, 30], "#2C3E50", None, 0),  # Left Eye
        ("ellipse", [54, 24, 60, 30], "#2C3E50", None, 0),  # Right Eye
        ("arc", [42, 32, 58, 42], 0, 180, "#E74C3C", 2)  # Smile
    ],
    "girl": [
        ("ellipse", [30, 8, 70, 48], "#F5C29B", "#D39E77", 2),  # Head
        ("polygon", [(28, 20), (50, 6), (72, 20), (50, 14)], "#2C3E50", None, 0),  # Hair
        ("ellipse", [12, 22, 28, 38], "#2C3E50", None, 0),  # Left Pigtail
        ("ellipse", [72, 22, 88, 38], "#2C3E50", None, 0),  # Right Pigtail
        ("rectangle", [34, 48, 66, 66], "#E74C3C", "#C0392B", 2),  # Coral Top
        ("line", [(34, 52), (16, 64)], "#F5C29B", 4),  # Left Arm
        ("line", [(66, 52), (84, 64)], "#F5C29B", 4),  # Right Arm
        ("polygon", [(30, 66), (70, 66), (78, 86), (22, 86)], "#2980B9", "#1B4F72", 2),  # Denim Skirt
        ("ellipse", [32, 86, 46, 96], "#ECF0F1", "#BDC3C7", 1),  # Left Sneaker
        ("ellipse", [54, 86, 68, 96], "#ECF0F1", "#BDC3C7", 1),  # Right Sneaker
        ("ellipse", [40, 24, 46, 30], "#2C3E50", None, 0),  # Left Eye
        ("ellipse", [54, 24, 60, 30], "#2C3E50", None, 0),  # Right Eye
        ("arc", [42, 32, 58, 42], 0, 180, "#E74C3C", 2)  # Smile
    ]
}

class BoardBuddyCanvas:
    def __init__(self, width=600, height=800, theme="whiteboard"):
        self.width = width
        self.height = height
        self.theme = theme
        self.title = "Board Buddy Canvas"
        self.elements = []

    def clear(self, theme=None):
        if theme:
            self.theme = theme
        self.elements = []
        print(f"[BoardBuddy] Canvas cleared (Theme: {self.theme})")

    def add_element(self, element_id, element_type, bounds, config):
        self.elements = [e for e in self.elements if e["id"] != element_id]
        element = {
            "id": element_id,
            "type": element_type,
            "bounds": bounds,
            "config": config
        }
        self.elements.append(element)
        print(f"[BoardBuddy] Added element '{element_id}' ({element_type}) at {bounds}")

    def load_json(self, json_data):
        """
        Public API: Ingests raw JSON payload (string or list of dicts) directly into canvas state.
        Supports flat minimal schemas (pos, item, count, size, label) and legacy nested config schemas.
        Returns a non-intrusive diagnostic feedback dictionary indicating execution status.
        """
        response = {
            "status": "success",
            "loaded_count": 0,
            "element_ids": [],
            "warnings": [],
            "errors": []
        }
        self.clear()

        try:
            if isinstance(json_data, str):
                try:
                    elements_list = json.loads(json_data)
                except Exception as e:
                    response["status"] = "error"
                    response["errors"].append(f"JSON Parse Error: {str(e)}")
                    print(f"[BoardBuddy] JSON Parse Error: {e}")
                    return response
            elif isinstance(json_data, (list, tuple)):
                elements_list = json_data
            elif isinstance(json_data, dict):
                elements_list = [json_data]
            else:
                response["status"] = "error"
                response["errors"].append(f"Invalid payload format: expected list or dict, got {type(json_data).__name__}")
                return response

            valid_types = {"stickers", "text", "geometry", "animation", "animate_param", "graph", "numberline", "fraction"}

            for elem in elements_list:
                if not isinstance(elem, dict):
                    response["warnings"].append(f"Skipped non-dict item in payload: {elem}")
                    continue

                elem_id = elem.get("id")
                elem_type = elem.get("type")

                if not elem_id or not elem_type:
                    response["warnings"].append(f"Element missing required 'id' or 'type': {elem}")
                    continue

                if elem_type not in valid_types:
                    response["warnings"].append(f"Unknown element type '{elem_type}' for id '{elem_id}'")

                raw_bounds = elem.get("bounds") or elem.get("pos") or [0, 0]
                config = elem.get("config", {})

                # Normalize 2-element [x, y] position into full 4-element [x, y, w, h] bounds
                if isinstance(raw_bounds, (list, tuple)) and len(raw_bounds) == 2:
                    x, y = raw_bounds[0], raw_bounds[1]
                    font_sz = elem.get("font_size") or config.get("font_size", 22)
                    bounds = [x, y, max(20, self.width - x - 20), font_sz + 25]
                else:
                    bounds = raw_bounds

                elem_copy = dict(elem)
                elem_copy["bounds"] = bounds
                if "config" not in elem_copy:
                    elem_copy["config"] = {}

                self.elements = [e for e in self.elements if e["id"] != elem_id]
                self.elements.append(elem_copy)
                response["element_ids"].append(elem_id)

            # Compute maximum animation duration T_max (in seconds)
            max_dur = 0.0
            for e in self.elements:
                etype = e.get("type")
                if etype in ["animation", "animate_param"]:
                    cfg = e.get("config", {})
                    dur_val = e.get("duration") or e.get("duration_sec") or cfg.get("duration") or cfg.get("duration_sec")
                    if dur_val is not None:
                        try:
                            max_dur = max(max_dur, float(dur_val))
                        except Exception:
                            pass
                    else:
                        dur_ms = e.get("duration_ms") or cfg.get("duration_ms")
                        if dur_ms is not None:
                            try:
                                max_dur = max(max_dur, float(dur_ms) / 1000.0)
                            except Exception:
                                pass
                        else:
                            max_dur = max(max_dur, 3.0)
            self.max_anim_duration = max_dur
            self.current_scrub_time = None

            response["loaded_count"] = len(response["element_ids"])
            if response["errors"]:
                response["status"] = "error"
            elif response["warnings"]:
                response["status"] = "partial_success"

            print(f"[BoardBuddy] Loaded {response['loaded_count']} elements from JSON payload (status: {response['status']}, max_anim_duration: {self.max_anim_duration:.1f}s).")
            return response

        except Exception as general_err:
            response["status"] = "error"
            response["errors"].append(f"Unexpected load_json error: {str(general_err)}")
            print(f"[BoardBuddy] Unexpected load_json error: {general_err}")
            return response

    def get_max_duration(self):
        """Returns the maximum animation duration in seconds (0.0 if static payload)."""
        return getattr(self, "max_anim_duration", 0.0)

    def has_animation(self):
        """Returns True if the current payload contains animation elements."""
        return getattr(self, "max_anim_duration", 0.0) > 0.0

    def set_scrub_time(self, t_seconds):
        """Sets the current scrubbed animation time in seconds."""
        max_d = getattr(self, "max_anim_duration", 0.0)
        if max_d > 0.0:
            self.current_scrub_time = max(0.0, min(max_d, float(t_seconds)))
            return self.current_scrub_time / max_d
        return 1.0

    def handle_touch_scrub(self, x, y):
        """
        Hit-tests touch input for the bottom scrubber control bar (Y >= 800).
        Returns scrubbed time in seconds if touched, or None if touch was outside scrubber bar.
        """
        max_d = getattr(self, "max_anim_duration", 0.0)
        if max_d > 0.0 and y >= self.height:
            track_x1 = 65
            track_x2 = 490
            track_w = track_x2 - track_x1
            clamped_x = max(track_x1, min(track_x2, x))
            ratio = float(clamped_x - track_x1) / float(track_w)
            scrubbed_t = ratio * max_d
            self.set_scrub_time(scrubbed_t)
            return scrubbed_t
        return None

    def annotate_text(self, text, pos=[40, 40], font_size=22, color="#333333", mode="text", element_id=None):
        if not element_id:
            element_id = f"text_{len(self.elements)+1}"
        bounds = [pos[0], pos[1], self.width - pos[0] - 20, font_size + 25]
        config = {
            "text": text,
            "font_size": font_size,
            "color": color,
            "mode": mode.lower()
        }
        self.add_element(element_id, "text", bounds, config)
        return element_id

    def draw_latex(self, latex_str, pos=[40, 100], font_size=20, color="#6A1B9A", element_id=None):
        return self.annotate_text(latex_str, pos=pos, font_size=font_size, color=color, mode="math", element_id=element_id)

    def draw_stickers(self, item="apple", count=5, layout="row", bounds=[40, 150, 520, 120], label="", mode="text", show_border=False, element_id=None):
        if not element_id:
            element_id = f"sticker_{len(self.elements)+1}"
        config = {
            "item": item.lower(),
            "count": count,
            "layout": layout,
            "label": label,
            "mode": mode.lower(),
            "show_border": False
        }
        self.add_element(element_id, "stickers", bounds, config)
        return element_id

    def draw_geometry(self, shape_type="triangle", vertices=None, radius=None, labels=None, color="#2196F3", highlight_color="#FF5722", bounds=[40, 200, 520, 360], title="", mode="text", show_border=False, element_id=None):
        if not element_id:
            element_id = f"geom_{len(self.elements)+1}"
        sanitized_labels = []
        if labels:
            for l in labels:
                sanitized_labels.append({
                    "text": l.get("text", ""),
                    "pos": l.get("pos", None),
                    "mode": l.get("mode", "text").lower()
                })

        config = {
            "shape_type": shape_type,
            "vertices": vertices or [[50, 360], [400, 360], [400, 120]],
            "radius": radius,
            "labels": sanitized_labels,
            "color": color,
            "highlight_color": highlight_color,
            "title": title,
            "mode": mode.lower(),
            "show_border": False
        }
        self.add_element(element_id, "geometry", bounds, config)
        return element_id

    def plot_function(self, equation="y = a*x**2 + c", x_range=[-5, 5], y_range=[-8, 8], color="#E91E63", title="", variables=None, sliders=None, x_step=1, y_step=1, show_ticks=True, show_sliders=True, mode="text", show_border=False, bounds=[40, 440, 520, 330], element_id=None):
        if not element_id:
            element_id = f"graph_{len(self.elements)+1}"
        config = {
            "equation": equation,
            "x_range": x_range,
            "y_range": y_range,
            "color": color,
            "title": title or f"Graph of {equation}",
            "variables": variables or {},
            "sliders": sliders or [{"var": "a", "min": -3.0, "max": 3.0}],
            "x_step": x_step,
            "y_step": y_step,
            "show_ticks": show_ticks,
            "show_sliders": show_sliders,
            "mode": mode.lower(),
            "show_border": False
        }
        self.add_element(element_id, "graph", bounds, config)
        return element_id

    def draw_fraction(self, numerator=3, denominator=4, visual_type="bar", color="#FF5722", label="", mode="math", bounds=[40, 120, 520, 120], show_border=False, element_id=None):
        if not element_id:
            element_id = f"frac_{len(self.elements)+1}"
        config = {
            "numerator": numerator,
            "denominator": denominator,
            "visual_type": visual_type,
            "color": color,
            "label": label or f"\\frac{{{numerator}}}{{{denominator}}}",
            "mode": mode.lower(),
            "show_border": False
        }
        self.add_element(element_id, "fraction", bounds, config)
        return element_id

    def show_numberline(self, min_val=-5, max_val=5, step=1, marked_points=None, hops=None, title="", mode="text", bounds=[40, 350, 520, 200], show_border=False, element_id=None):
        if not element_id:
            element_id = f"numline_{len(self.elements)+1}"
        sanitized_hops = []
        if hops:
            for h in hops:
                sanitized_hops.append({
                    "start": h.get("start", 0),
                    "end": h.get("end", 1),
                    "label": h.get("label", ""),
                    "mode": h.get("mode", "text").lower()
                })
        config = {
            "min_val": min_val,
            "max_val": max_val,
            "step": step,
            "marked_points": marked_points or [],
            "hops": sanitized_hops,
            "title": title or "Number Line",
            "mode": mode.lower(),
            "show_border": False
        }
        self.add_element(element_id, "numberline", bounds, config)
        return element_id

    def animate_element(self, target_id, path_type="line", from_pos=[40, 150], to_pos=[300, 150], duration_ms=1200, element_id=None):
        if not element_id:
            element_id = f"anim_{len(self.elements)+1}"
        config = {
            "target_id": target_id,
            "path_type": path_type,
            "from_pos": from_pos,
            "to_pos": to_pos,
            "duration_ms": duration_ms
        }
        self.add_element(element_id, "animation", [0, 0, 0, 0], config)
        return element_id

    def _draw_sticker_icon(self, draw, item, cx, cy, size=32):
        """Draws normalized vector primitives (0..100) scaled to target (cx, cy, size)."""
        if item not in VECTOR_STICKERS:
            r = size // 2
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(156, 39, 176), outline=(106, 27, 154), width=2)
            return

        s = float(size) / 100.0
        ox = cx - size / 2.0
        oy = cy - size / 2.0

        for prim in VECTOR_STICKERS[item]:
            ptype = prim[0]
            if ptype == "ellipse":
                box, fill, outline, w = prim[1], prim[2], prim[3], prim[4]
                sbox = [ox + box[0]*s, oy + box[1]*s, ox + box[2]*s, oy + box[3]*s]
                draw.ellipse(sbox, fill=fill, outline=outline, width=max(1, int(w*s)) if outline else 0)

            elif ptype == "polygon":
                pts, fill, outline, w = prim[1], prim[2], prim[3], prim[4]
                spts = [(ox + p[0]*s, oy + p[1]*s) for p in pts]
                draw.polygon(spts, fill=fill, outline=outline, width=max(1, int(w*s)) if outline else 0)

            elif ptype == "rectangle":
                box, fill, outline, w = prim[1], prim[2], prim[3], prim[4]
                sbox = [ox + box[0]*s, oy + box[1]*s, ox + box[2]*s, oy + box[3]*s]
                draw.rectangle(sbox, fill=fill, outline=outline, width=max(1, int(w*s)) if outline else 0)

            elif ptype == "line":
                pts, stroke, w = prim[1], prim[2], prim[3]
                spts = [(ox + p[0]*s, oy + p[1]*s) for p in pts]
                draw.line(spts, fill=stroke, width=max(1, int(w*s)))

            elif ptype == "arc":
                box, start_a, end_a, stroke, w = prim[1], prim[2], prim[3], prim[4], prim[5]
                sbox = [ox + box[0]*s, oy + box[1]*s, ox + box[2]*s, oy + box[3]*s]
                draw.arc(sbox, start_a, end_a, fill=stroke, width=max(1, int(w*s)))

    def render(self, anim_progress=None, dynamic_vars=None):
        if self.theme == "chalkboard":
            bg_color = (27, 59, 43)
            grid_color = (40, 80, 60)
            default_text_color = (240, 240, 240)
            badge_bg = (34, 75, 55)
            badge_border = (60, 110, 85)
        elif self.theme == "graph_paper":
            bg_color = (240, 244, 248)
            grid_color = (208, 215, 222)
            default_text_color = (30, 30, 30)
            badge_bg = (255, 255, 255)
            badge_border = (180, 195, 210)
        else:
            bg_color = (247, 235, 217)      # #F7EBD9 Rich Warm Honey Parchment
            grid_color = (230, 213, 195)    # #E6D5C3 Soft Warm Amber Grid
            default_text_color = (39, 31, 24)  # #271F18 Deep Roasted Coffee
            badge_bg = (253, 247, 237)      # #FDF7ED Warm Soft Cream Pill Badge
            badge_border = (230, 210, 185)  # #E6D2B9 Soft Amber Badge Border

        img = Image.new("RGB", (self.width, self.height), color=bg_color)
        draw = ImageDraw.Draw(img)

        for x in range(0, self.width, 40):
            draw.line([(x, 0), (x, self.height)], fill=grid_color, width=1)
        for y in range(0, self.height, 40):
            draw.line([(0, y), (self.width, y)], fill=grid_color, width=1)

        anim_overrides = {}
        param_vars = {}
        if dynamic_vars:
            param_vars.update(dynamic_vars)

        if anim_progress is not None:
            t_norm = max(0.0, min(1.0, float(anim_progress)))
            for elem in self.elements:
                etype = elem.get("type")

                # A. Handle Spatial Position Animation (type: "animation")
                if etype == "animation":
                    def get_param(key, default=None):
                        if key in elem:
                            return elem[key]
                        config = elem.get("config", {})
                        return config.get(key, default)

                    target_id = get_param("target") or get_param("target_id")
                    if not target_id:
                        continue

                    raw_from = get_param("from") or get_param("from_pos")
                    if not raw_from:
                        for t_elem in self.elements:
                            if t_elem.get("id") == target_id:
                                raw_from = t_elem.get("pos") or t_elem.get("bounds") or [30, 20]
                                break
                    if not raw_from:
                        raw_from = [30, 20]

                    raw_to = get_param("to") or get_param("to_pos") or raw_from
                    motion = str(get_param("motion") or get_param("path_type") or "slide").strip()

                    x1, y1 = raw_from[0], raw_from[1]
                    x2, y2 = raw_to[0], raw_to[1]

                    cur_x = x1 + (x2 - x1) * t_norm
                    cur_y = y1 + (y2 - y1) * t_norm

                    motion_lower = motion.lower()
                    if motion_lower == "hop":
                        arc_height = 80.0
                        cur_y -= math.sin(t_norm * math.pi) * arc_height
                    elif motion_lower == "bounce":
                        bounce = abs(math.sin(t_norm * math.pi * 3)) * (1.0 - t_norm) * 50.0
                        cur_y -= bounce
                    elif motion_lower in ["slide", "line", "linear"]:
                        pass
                    else:
                        try:
                            safe_dict = {
                                "t": t_norm,
                                "sin": math.sin,
                                "cos": math.cos,
                                "pi": math.pi,
                                "sqrt": math.sqrt,
                                "abs": abs,
                                "pow": math.pow,
                                "exp": math.exp
                            }
                            disp_y = float(eval(motion, {"__builtins__": None}, safe_dict))
                            cur_y += disp_y
                        except Exception:
                            pass

                    anim_overrides[target_id] = [int(cur_x), int(cur_y)]

                # B. Handle Parameter Animation (type: "animate_param")
                elif etype == "animate_param":
                    vname = elem.get("var") or elem.get("target_var") or elem.get("param") or "val"
                    vname_clean = str(vname).replace("{", "").replace("}", "").replace("$", "").strip()

                    from_v = elem.get("from")
                    to_v = elem.get("to")
                    val_expr = elem.get("val")

                    if val_expr:
                        try:
                            safe_dict = {
                                "t": t_norm,
                                "sin": math.sin,
                                "cos": math.cos,
                                "pi": math.pi,
                                "sqrt": math.sqrt,
                                "abs": abs
                            }
                            cur_val = float(eval(str(val_expr), {"__builtins__": None}, safe_dict))
                        except Exception:
                            cur_val = 0.0
                    elif from_v is not None and to_v is not None:
                        try:
                            fv = float(from_v)
                            tv = float(to_v)
                            cur_val = fv + (tv - fv) * t_norm
                        except Exception:
                            cur_val = from_v
                    else:
                        cur_val = 0.0

                    param_vars[vname_clean] = cur_val

        # Universal Pre-Render Substitution Helper Engine with Format Specifiers ({var:int}, {var:1f}, {var:2f})
        def substitute_item(obj):
            if isinstance(obj, str):
                for vk, vv in (param_vars or {}).items():
                    # Patterns: {vk}, {vk:int}, {vk:d}, {vk:0f}, {vk:1f}, {vk:2f}, $vk
                    patterns = [
                        (f"{{{vk}:int}}", "int"),
                        (f"{{{vk}:d}}", "int"),
                        (f"{{{vk}:0f}}", "int"),
                        (f"{{{vk}:1f}}", "1f"),
                        (f"{{{vk}:2f}}", "2f"),
                        (f"{{{vk}}}", "auto"),
                        (f"${vk}", "auto")
                    ]
                    for ph, fmt_type in patterns:
                        if obj.strip() == ph:
                            # Exact string match: Return raw typed value (int or float) directly!
                            if fmt_type == "int":
                                return int(round(float(vv)))
                            elif fmt_type == "1f":
                                return round(float(vv), 1)
                            elif fmt_type == "2f":
                                return round(float(vv), 2)
                            else:
                                if isinstance(vv, float) and vv.is_integer():
                                    return int(vv)
                                return vv
                        elif ph in obj:
                            if fmt_type == "int":
                                fmt_str = str(int(round(float(vv))))
                            elif fmt_type == "1f":
                                fmt_str = f"{float(vv):.1f}"
                            elif fmt_type == "2f":
                                fmt_str = f"{float(vv):.2f}"
                            else:
                                if isinstance(vv, float):
                                    fmt_str = f"{int(vv)}" if vv.is_integer() else f"{vv:.2f}"
                                else:
                                    fmt_str = str(vv)
                            obj = obj.replace(ph, fmt_str)
                # Any placeholder no var resolved (static frame / undefined var) must
                # not survive as a literal into numeric parsing — that is the crash.
                return _resolve_leftover_placeholder(obj)
            elif isinstance(obj, list):
                return [substitute_item(item) for item in obj]
            elif isinstance(obj, tuple):
                return tuple(substitute_item(item) for item in obj)
            elif isinstance(obj, dict):
                return {k: substitute_item(v) for k, v in obj.items()}
            return obj

        for raw_elem in self.elements:
            elem = substitute_item(raw_elem)
            elem_id = elem.get("id")
            elem_type = elem.get("type")
            if elem_type in ["animation", "animate_param"]:
                continue

            bounds = list(elem.get("bounds", [0, 0, self.width, self.height]))
            config = elem.get("config", {})

            if elem_id in anim_overrides:
                bounds[0] = anim_overrides[elem_id][0]
                bounds[1] = anim_overrides[elem_id][1]

            if elem_type == "text":
                def get_param(key, default=None):
                    if key in ["pos", "bounds"] and elem_id in anim_overrides:
                        return anim_overrides[elem_id]
                    if key in elem:
                        return elem[key]
                    return config.get(key, default)

                text = get_param("text", "")
                color = get_param("color", default_text_color)
                raw_size = get_param("size") or get_param("font_size", "medium")
                mode = get_param("mode", "").lower()

                # Extract starting position (pos or bounds)
                raw_pos = get_param("pos") or get_param("bounds") or [30, 20]
                x = raw_pos[0]
                y = raw_pos[1]

                # Parse Font Size (Presets or Direct Point Int)
                font_presets = {
                    "small": 16,
                    "sm": 16,
                    "medium": 22,
                    "md": 22,
                    "large": 28,
                    "lg": 28,
                    "xlarge": 36,
                    "xl": 36
                }
                if isinstance(raw_size, str):
                    font_size = font_presets.get(raw_size.lower(), 22)
                elif isinstance(raw_size, (int, float)):
                    font_size = int(raw_size)
                else:
                    font_size = 22

                max_w = max(200, self.width - x - 20)

                # Only rasterise GENUINE LaTeX. A plain sentence that merely contains
                # '^' or '=' stays plain text (prettified to 'x²'), so its spaces are
                # kept and it is width-fitted instead of blown up into a giant image.
                if _looks_like_latex(text, mode):
                    latex_img = render_latex_to_pil(text, font_size=font_size, color=color, max_width=max_w)
                    if latex_img:
                        img.paste(latex_img, (x, y), latex_img)
                    else:
                        clean_txt = _to_display_text(sanitize_text(text))
                        font = get_fitted_font(clean_txt, max_w, initial_size=font_size, bold=True)
                        draw.text((x, y), clean_txt, fill=color, font=font)
                else:
                    clean_txt = _to_display_text(sanitize_text(text))
                    font = get_fitted_font(clean_txt, max_w, initial_size=font_size, bold=True)
                    draw.text((x, y), clean_txt, fill=color, font=font)

            elif elem_type == "stickers":
                # Helper to read parameter from root or config (flat & legacy support)
                def get_param(key, default=None):
                    if key in ["pos", "bounds"] and elem_id in anim_overrides:
                        return anim_overrides[elem_id]
                    if key in elem:
                        return elem[key]
                    return config.get(key, default)

                item = get_param("item", "apple").lower()
                raw_count = get_param("count", 1)
                raw_size = get_param("size", "medium")
                label = get_param("label", "")
                
                # Extract starting position (pos or bounds)
                raw_pos = get_param("pos") or get_param("bounds") or [30, 80]
                bx = raw_pos[0]
                by = raw_pos[1]

                # 1. Parse Size (Presets or Integer Major Axis)
                size_presets = {
                    "small": 24,
                    "sm": 24,
                    "medium": 32,
                    "md": 32,
                    "large": 48,
                    "lg": 48,
                    "xlarge": 64,
                    "xl": 64
                }
                if isinstance(raw_size, str):
                    icon_size = size_presets.get(raw_size.lower(), 32)
                elif isinstance(raw_size, (int, float)):
                    icon_size = int(raw_size)
                else:
                    icon_size = 32

                # Preset gap built-in (icon_size / 2) -> Pitch = icon_size * 1.5
                pitch_x = int(icon_size * 1.5)
                pitch_y = int(icon_size * 1.5)

                # 2. Parse Count (Single Int or Matrix [rows, cols] or "rows x cols")
                grid_rows = 1
                grid_cols = 1
                if isinstance(raw_count, int):
                    grid_rows = 1
                    grid_cols = max(1, raw_count)
                elif isinstance(raw_count, (list, tuple)) and len(raw_count) >= 2:
                    grid_rows = max(1, int(raw_count[0]))
                    grid_cols = max(1, int(raw_count[1]))
                elif isinstance(raw_count, str):
                    import re
                    match = re.search(r"(\d+)\s*x\s*(\d+)", raw_count, re.IGNORECASE)
                    if match:
                        grid_rows = max(1, int(match.group(1)))
                        grid_cols = max(1, int(match.group(2)))
                    else:
                        try:
                            grid_cols = max(1, int(raw_count))
                        except Exception:
                            grid_cols = 1

                # 3. Smart Label Rendering (Auto-detects Math/LaTeX without requiring mode parameter)
                top_offset = 4
                if label:
                    label_color = "#1E88E5"
                    max_lbl_w = max(200, self.width - bx - 20)
                    has_math_symbols = any(sym in label for sym in ["\\", "$", "^", "_", "{", "}"])
                    
                    if has_math_symbols:
                        limg = render_latex_to_pil(label, font_size=14, color=label_color, max_width=max_lbl_w)
                        if limg:
                            img.paste(limg, (bx, by + 4), limg)
                            top_offset = limg.height + 10
                        else:
                            lbl_font = get_fitted_font(sanitize_text(label), max_lbl_w, initial_size=15, bold=True)
                            draw.text((bx, by + 4), sanitize_text(label), fill=label_color, font=lbl_font)
                            top_offset = 28
                    else:
                        clean_lbl = sanitize_text(label)
                        lbl_font = get_fitted_font(clean_lbl, max_lbl_w, initial_size=15, bold=True)
                        draw.text((bx, by + 4), clean_lbl, fill=label_color, font=lbl_font)
                        top_offset = 28

                # 4. Render Sticker Grid / Row
                start_center_x = bx + icon_size // 2
                start_center_y = by + top_offset + icon_size // 2

                for r in range(grid_rows):
                    for c in range(grid_cols):
                        cx = start_center_x + c * pitch_x
                        cy = start_center_y + r * pitch_y
                        if cx < self.width - 10 and cy < self.height - 10:
                            self._draw_sticker_icon(draw, item, cx, cy, size=icon_size)

            elif elem_type == "geometry":
                def get_param(key, default=None):
                    if key in ["pos", "bounds"] and elem_id in anim_overrides:
                        return anim_overrides[elem_id]
                    if key in elem:
                        return elem[key]
                    return config.get(key, default)

                shape_name = (get_param("shape") or get_param("shape_type") or "triangle").lower()
                raw_vertices = get_param("vertices")
                color = get_param("color", "#1976D2")
                hcolor = get_param("highlight") or get_param("highlight_color", "#E53935")
                labels = get_param("labels", [])
                title = get_param("text") or get_param("title", "")
                radius = get_param("radius", 70)

                # Anchor position (pos or bounds)
                raw_pos = get_param("pos") or get_param("bounds") or [40, 60]
                bx = raw_pos[0]
                by = raw_pos[1]

                # 1. Smart Title Rendering (Auto-detects Math/LaTeX without requiring mode parameter)
                top_offset = 4
                if title:
                    title_color = "#0D47A1"
                    max_t_w = max(200, self.width - bx - 20)
                    if _looks_like_latex(title):
                        timg = render_latex_to_pil(title, font_size=15, color=title_color, max_width=max_t_w)
                        if timg:
                            img.paste(timg, (bx, by + 4), timg)
                            top_offset = timg.height + 10
                        else:
                            clean_t = _to_display_text(sanitize_text(title))
                            tfont = get_fitted_font(clean_t, max_t_w, initial_size=18, bold=True)
                            draw.text((bx, by + 4), clean_t, fill=title_color, font=tfont)
                            top_offset = 28
                    else:
                        clean_t = _to_display_text(sanitize_text(title))
                        tfont = get_fitted_font(clean_t, max_t_w, initial_size=18, bold=True)
                        draw.text((bx, by + 4), clean_t, fill=title_color, font=tfont)
                        top_offset = 28

                # 2. Shape Defaults (Relative to pos anchor, max dimension 220px)
                if not raw_vertices:
                    if shape_name in ["triangle", "right_triangle"]:
                        rel_vertices = [[0, 150], [220, 150], [220, 0]]
                    elif shape_name == "equilateral_triangle":
                        rel_vertices = [[0, 160], [220, 160], [110, 22]]
                    elif shape_name == "isosceles_triangle":
                        rel_vertices = [[0, 150], [220, 150], [110, 0]]
                    elif shape_name == "rectangle":
                        rel_vertices = [[0, 0], [220, 0], [220, 140], [0, 140]]
                    elif shape_name == "square":
                        rel_vertices = [[0, 0], [160, 0], [160, 160], [0, 160]]
                    elif shape_name in ["diamond", "rhombus"]:
                        rel_vertices = [[80, 0], [160, 80], [80, 160], [0, 80]]
                    elif shape_name == "pentagon":
                        rel_vertices = [[80, 0], [156, 55], [127, 145], [33, 145], [4, 55]]
                    elif shape_name == "hexagon":
                        rel_vertices = [[40, 0], [120, 0], [160, 70], [120, 140], [40, 140], [0, 70]]
                    else:
                        rel_vertices = [[0, 150], [220, 150], [220, 0]]
                else:
                    rel_vertices = raw_vertices

                shape_origin_y = by + top_offset

                # 2b. Universal Anchor-Fixed Board Auto-Scaler:
                # If relative shape coordinates exceed remaining screen space (X > 580 or Y > 780),
                # auto-scale the shape down proportionately while keeping anchor pos fixed!
                if shape_name == "circle":
                    avail_r_x = self.width - 20 - (bx + 10)
                    avail_r_y = self.height - 20 - (shape_origin_y + 10)
                    max_allowed_r = max(20, min(avail_r_x, avail_r_y))
                    if radius > max_allowed_r:
                        radius = max_allowed_r
                elif rel_vertices:
                    max_rel_x = max(v[0] for v in rel_vertices)
                    max_rel_y = max(v[1] for v in rel_vertices)
                    avail_w = max(40, self.width - 20 - bx)
                    avail_h = max(40, self.height - 20 - shape_origin_y)

                    scale_x = float(avail_w) / float(max_rel_x) if max_rel_x > avail_w else 1.0
                    scale_y = float(avail_h) / float(max_rel_y) if max_rel_y > avail_h else 1.0
                    auto_scale = min(scale_x, scale_y)

                    if auto_scale < 1.0:
                        rel_vertices = [[int(v[0] * auto_scale), int(v[1] * auto_scale)] for v in rel_vertices]

                # 3. Render Geometry Shape
                if shape_name == "circle":
                    cx = bx + radius + 10
                    cy = shape_origin_y + radius + 10
                    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill="#E8F5E9", outline=color, width=3)
                    draw.line([(cx, cy), (cx + radius, cy)], fill=hcolor, width=3)
                    draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill="#1B5E20")

                elif len(rel_vertices) >= 3:
                    # Convert relative vertices [vx, vy] -> absolute screen coordinates [bx + vx, shape_origin_y + vy]
                    pts = [(bx + v[0], shape_origin_y + v[1]) for v in rel_vertices]
                    draw.polygon(pts, fill="#E3F2FD", outline=color, width=3)
                    
                    if shape_name == "right_triangle" and len(pts) >= 3:
                        # Highlight hypotenuse
                        draw.line([pts[0], pts[2]], fill=hcolor, width=4)
                        # Right-angle indicator box at vertex 1
                        rx, ry = pts[1]
                        draw.rectangle([rx - 15, ry - 15, rx, ry], fill="#FFEBEE", outline=hcolor, width=2)

                # 4. Render vertex labels. When a label carries no explicit pos, pin
                # it to ITS vertex (label i -> vertex i) nudged slightly OUTWARD from
                # the shape centroid, instead of the old default that stacked every
                # label on top of each other at [20, 20] (why A/B/C never showed).
                abs_pts = None
                cxc = cyc = 0
                if len(rel_vertices) >= 2:
                    abs_pts = [(bx + v[0], shape_origin_y + v[1]) for v in rel_vertices]
                    cxc = sum(p[0] for p in abs_pts) / len(abs_pts)
                    cyc = sum(p[1] for p in abs_pts) / len(abs_pts)
                for i, lbl in enumerate(labels):
                    txt = lbl.get("text", "")
                    if not txt:
                        continue
                    rel_lpos = lbl.get("pos")
                    if rel_lpos:
                        abs_lx = bx + rel_lpos[0]
                        abs_ly = shape_origin_y + rel_lpos[1]
                    elif abs_pts is not None and i < len(abs_pts):
                        vx, vy = abs_pts[i]
                        # push the label ~16px away from the centroid so it sits just
                        # outside the corner rather than on the edge.
                        dx, dy = vx - cxc, vy - cyc
                        norm = (dx * dx + dy * dy) ** 0.5 or 1.0
                        abs_lx = int(vx + 16 * dx / norm - 5)
                        abs_ly = int(vy + 16 * dy / norm - 8)
                    else:
                        abs_lx, abs_ly = bx + 20, shape_origin_y + 20
                    max_lbl_w = max(60, self.width - abs_lx - 10)

                    if _looks_like_latex(txt):
                        limg = render_latex_to_pil(txt, font_size=14, color="#212121", max_width=max_lbl_w)
                        if limg:
                            img.paste(limg, (abs_lx, abs_ly), limg)
                        else:
                            clean_l = _to_display_text(sanitize_text(txt))
                            lbl_font = get_fitted_font(clean_l, max_lbl_w, initial_size=16, bold=True)
                            draw.text((abs_lx, abs_ly), clean_l, fill="#212121", font=lbl_font)
                    else:
                        clean_l = _to_display_text(sanitize_text(txt))
                        lbl_font = get_fitted_font(clean_l, max_lbl_w, initial_size=16, bold=True)
                        draw.text((abs_lx, abs_ly), clean_l, fill="#212121", font=lbl_font)

            elif elem_type == "graph":
                def get_param(key, default=None):
                    if key in ["pos", "bounds"] and elem_id in anim_overrides:
                        return anim_overrides[elem_id]
                    if key in elem:
                        return elem[key]
                    return config.get(key, default)

                equation = get_param("equation", "y = x^2")
                raw_pos = get_param("pos") or get_param("bounds") or [40, 60]
                raw_size = get_param("size", "medium")
                xmin, xmax = get_param("x_range") or [-5, 5]
                ymin, ymax = get_param("y_range") or [-5, 5]
                color = get_param("color", "#E91E63")
                title = get_param("title") or get_param("text", "")
                show_ticks = get_param("show_ticks", True)
                x_step = get_param("x_step", 1)
                y_step = get_param("y_step", 1)

                bx = raw_pos[0]
                by = raw_pos[1]

                # 1. Parse Physical Screen Size Viewport (Independent of x_range / y_range!)
                size_presets = {
                    "small": (220, 160),
                    "sm": (220, 160),
                    "medium": (280, 200),
                    "md": (280, 200),
                    "large": (350, 250),
                    "lg": (350, 250),
                    "xlarge": (450, 320),
                    "xl": (450, 320)
                }

                if isinstance(raw_size, str):
                    bw, bh = size_presets.get(raw_size.lower(), (280, 200))
                elif isinstance(raw_size, (list, tuple)) and len(raw_size) >= 2:
                    bw, bh = int(raw_size[0]), int(raw_size[1])
                elif isinstance(raw_size, (int, float)):
                    bw = int(raw_size)
                    bh = int(bw * 0.7)
                else:
                    bw, bh = 280, 200

                # Universal Board Guardrail: Auto-scale physical viewport if exceeding screen space
                avail_w = max(100, self.width - 20 - bx)
                avail_h = max(100, self.height - 20 - by)
                if bw > avail_w:
                    scale_factor = float(avail_w) / float(bw)
                    bw = avail_w
                    bh = int(bh * scale_factor)
                if bh > avail_h:
                    scale_factor = float(avail_h) / float(bh)
                    bh = avail_h
                    bw = int(bw * scale_factor)

                # 2. Smart Title Rendering (Auto-detects Math/LaTeX without requiring mode parameter)
                top_offset = 4
                disp_title = title or f"Graph of {equation}"
                if disp_title:
                    title_color = "#880E4F"
                    max_t_w = max(150, bw - 20)
                    has_math_title = any(sym in disp_title for sym in ["\\", "$", "^", "_", "{", "}", "=", "+", "-"])
                    if has_math_title:
                        timg = render_latex_to_pil(disp_title, font_size=14, color=title_color, max_width=max_t_w)
                        if timg:
                            img.paste(timg, (bx + 10, by + 4), timg)
                            top_offset = timg.height + 8
                        else:
                            tfont = get_fitted_font(sanitize_text(disp_title), max_t_w, initial_size=14, bold=True)
                            draw.text((bx + 10, by + 4), sanitize_text(disp_title), fill=title_color, font=tfont)
                            top_offset = 26
                    else:
                        clean_t = sanitize_text(disp_title)
                        tfont = get_fitted_font(clean_t, max_t_w, initial_size=14, bold=True)
                        draw.text((bx + 10, by + 4), clean_t, fill=title_color, font=tfont)
                        top_offset = 26

                # 3. Graph Viewport & Axis Projection
                px = bx + 30
                py = by + top_offset + 10
                pw = bw - 45
                ph = bh - top_offset - 25

                # Prevent division by zero
                dx = max(0.1, xmax - xmin)
                dy = max(0.1, ymax - ymin)

                ox = px + int((0 - xmin) / dx * pw)
                oy = py + int((ymax - 0) / dy * ph)

                # Draw Axis Lines & Arrows
                if px <= ox <= px + pw:
                    draw.line([(ox, py), (ox, py + ph)], fill=(140, 160, 180), width=2)
                    draw.polygon([(ox, py - 4), (ox - 4, py + 4), (ox + 4, py + 4)], fill=(140, 160, 180))
                if py <= oy <= py + ph:
                    draw.line([(px, oy), (px + pw, oy)], fill=(140, 160, 180), width=2)
                    draw.polygon([(px + pw + 4, oy), (px + pw - 4, oy - 4), (px + pw - 4, oy + 4)], fill=(140, 160, 180))

                # Draw Ticks & Numbers
                if show_ticks:
                    small_font = get_fitted_font("0", 20, initial_size=10, bold=False)
                    for xi in range(int(xmin), int(xmax) + 1, max(1, int(x_step))):
                        if xi == 0:
                            continue
                        tx = px + int((xi - xmin) / dx * pw)
                        if px <= tx <= px + pw:
                            draw.line([(tx, oy - 4), (tx, oy + 4)], fill=(100, 120, 140), width=2)
                            draw.text((tx - 4, oy + 5), str(xi), fill="#424242", font=small_font)

                    for yi in range(int(ymin), int(ymax) + 1, max(1, int(y_step))):
                        if yi == 0:
                            continue
                        ty = py + int((ymax - yi) / dy * ph)
                        if py <= ty <= py + ph:
                            draw.line([(ox - 4, ty), (ox + 4, ty)], fill=(140, 160, 180), width=2)
                            draw.text((ox + 6, ty - 5), str(yi), fill="#424242", font=small_font)

                # 4. Evaluate & Plot Function Curve
                pts = []
                expr_str = equation.replace("y", "").replace("=", "").replace("^", "**").strip()
                eval_scope = {"math": math, "sin": math.sin, "cos": math.cos, "sqrt": math.sqrt, "pi": math.pi, "abs": abs}

                steps = 140
                for i in range(steps + 1):
                    x_val = xmin + (xmax - xmin) * (i / steps)
                    eval_scope["x"] = x_val
                    try:
                        y_val = float(eval(expr_str, {"__builtins__": None}, eval_scope))
                    except Exception:
                        y_val = 0.0

                    if ymin <= y_val <= ymax:
                        sx = px + int((x_val - xmin) / dx * pw)
                        sy = py + int((ymax - y_val) / dy * ph)
                        pts.append((sx, sy))

                if len(pts) >= 2:
                    draw.line(pts, fill=color, width=3)

            elif elem_type == "fraction":
                def get_param(key, default=None):
                    if key in ["pos", "bounds"] and elem_id in anim_overrides:
                        return anim_overrides[elem_id]
                    if key in elem:
                        return elem[key]
                    return config.get(key, default)

                raw_num = get_param("numerator", 3)
                raw_den = get_param("denominator", 4)
                color = get_param("color", "#FF5722")
                title = get_param("title") or get_param("text", "") or get_param("label", "")
                raw_pos = get_param("pos") or get_param("bounds") or [30, 60]
                raw_size = get_param("size", "medium")

                bx = raw_pos[0]
                by = raw_pos[1]

                size_presets = {
                    "small": (220, 120),
                    "sm": (220, 120),
                    "medium": (280, 160),
                    "md": (280, 160),
                    "large": (350, 200),
                    "lg": (350, 200),
                    "xlarge": (450, 250),
                    "xl": (450, 250)
                }

                if isinstance(raw_size, str):
                    bw, bh = size_presets.get(raw_size.lower(), (280, 160))
                elif isinstance(raw_size, (list, tuple)) and len(raw_size) >= 2:
                    bw, bh = _safe_int(raw_size[0], 280), _safe_int(raw_size[1], 160)
                elif isinstance(raw_size, (int, float)):
                    bw = int(raw_size)
                    bh = int(bw * 0.6)
                else:
                    bw, bh = 280, 160

                # Universal Board Guardrail: Auto-scale physical viewport if exceeding screen space
                avail_w = max(100, self.width - 20 - bx)
                avail_h = max(80, self.height - 20 - by)
                if bw > avail_w:
                    scale_factor = float(avail_w) / float(bw)
                    bw = avail_w
                    bh = int(bh * scale_factor)
                if bh > avail_h:
                    scale_factor = float(avail_h) / float(bh)
                    bh = avail_h
                    bw = int(bw * scale_factor)

                # Parse 1D vs 2D Denominator (e.g. 4 vs [2, 4] vs "2x4"). _safe_int so a
                # stray placeholder / garbage degrades to a default instead of crashing.
                if isinstance(raw_den, str) and "x" in raw_den.lower():
                    parts = raw_den.lower().split("x")
                    den_rows, den_cols = _safe_int(parts[0], 1), _safe_int(parts[1], 4)
                elif isinstance(raw_den, (list, tuple)) and len(raw_den) >= 2:
                    den_rows, den_cols = _safe_int(raw_den[0], 1), _safe_int(raw_den[1], 4)
                else:
                    den_rows, den_cols = 1, (_safe_int(raw_den, 4)
                                            if isinstance(raw_den, (int, float, str)) else 4)

                tot_den = max(1, den_rows * den_cols)

                # Parse 1D vs 2D Numerator (e.g. 3 vs [2, 3] vs "2x3")
                if isinstance(raw_num, str) and "x" in raw_num.lower():
                    parts = raw_num.lower().split("x")
                    num_rows, num_cols = _safe_int(parts[0], 1), _safe_int(parts[1], 3)
                    tot_num = num_rows * num_cols
                    is_2d_num = True
                elif isinstance(raw_num, (list, tuple)) and len(raw_num) >= 2:
                    num_rows, num_cols = _safe_int(raw_num[0], 1), _safe_int(raw_num[1], 3)
                    tot_num = num_rows * num_cols
                    is_2d_num = True
                else:
                    tot_num = (_safe_int(raw_num, 3)
                               if isinstance(raw_num, (int, float, str)) else 3)
                    num_rows, num_cols = 1, tot_num
                    is_2d_num = False

                # 1. Smart Title Rendering
                top_offset = 4
                disp_title = title or f"Fraction: {tot_num}/{tot_den}"
                if disp_title:
                    title_color = "#E65100"
                    max_t_w = max(150, bw - 20)
                    has_math_title = any(sym in disp_title for sym in ["\\", "$", "^", "_", "{", "}", "=", "+", "-"])
                    if has_math_title:
                        timg = render_latex_to_pil(disp_title, font_size=14, color=title_color, max_width=max_t_w)
                        if timg:
                            img.paste(timg, (bx + 10, by + 4), timg)
                            top_offset = timg.height + 8
                        else:
                            tfont = get_fitted_font(sanitize_text(disp_title), max_t_w, initial_size=14, bold=True)
                            draw.text((bx + 10, by + 4), sanitize_text(disp_title), fill=title_color, font=tfont)
                            top_offset = 26
                    else:
                        clean_t = sanitize_text(disp_title)
                        tfont = get_fitted_font(clean_t, max_t_w, initial_size=14, bold=True)
                        draw.text((bx + 10, by + 4), clean_t, fill=title_color, font=tfont)
                        top_offset = 26

                # 2. Render Fraction Bar / 2D Grid Block
                fy = by + top_offset + 8
                fw = int(bw * 0.65)
                fh = max(30, bh - top_offset - 20)
                fx = bx + 10

                block_w = max(4, fw // den_cols)
                block_h = max(4, fh // den_rows)

                for r in range(den_rows):
                    for c in range(den_cols):
                        x1 = fx + c * block_w
                        y1 = fy + r * block_h
                        x2 = x1 + block_w - 3
                        y2 = y1 + block_h - 3

                        if is_2d_num:
                            filled = (r < num_rows) and (c < num_cols)
                        else:
                            idx = r * den_cols + c
                            filled = idx < tot_num

                        fcolor = color if filled else "#E0E0E0"
                        draw.rectangle([x1, y1, x2, y2], fill=fcolor, outline="#BDBDBD", width=2)

                # 3. Render Fraction Math Formula Display (e.g. 3/4)
                frac_latex = r"$\frac{" + str(tot_num) + r"}{" + str(tot_den) + r"}$"
                limg = render_latex_to_pil(frac_latex, font_size=18, color=color, max_width=bw - fw - 20)
                if limg:
                    img.paste(limg, (bx + fw + 20, fy + int(fh * 0.2)), limg)
                else:
                    nx = bx + fw + 20
                    ny = fy + int(fh * 0.2)
                    frac_font = get_fitted_font(str(tot_num), 20, initial_size=16, bold=True)
                    draw.text((nx + 6, ny), str(tot_num), fill=color, font=frac_font)
                    draw.line([(nx, ny + 20), (nx + 24, ny + 20)], fill="#333333", width=3)
                    draw.text((nx + 6, ny + 24), str(tot_den), fill="#333333", font=frac_font)

            elif elem_type == "numberline":
                def get_param(key, default=None):
                    if key in ["pos", "bounds"] and elem_id in anim_overrides:
                        return anim_overrides[elem_id]
                    if key in elem:
                        return elem[key]
                    return config.get(key, default)

                min_v = _safe_int(get_param("min") if get_param("min") is not None else get_param("min_val", 0), 0)
                max_v = _safe_int(get_param("max") if get_param("max") is not None else get_param("max_val", 10), 10)
                if max_v <= min_v:
                    max_v = min_v + 10          # a degenerate range would divide-by-zero below
                step_v = max(1, _safe_int(get_param("step", 1), 1))
                raw_hops = get_param("hops", [])
                color = get_param("color", "#1976D2")
                title = get_param("title") or get_param("text", "")
                raw_pos = get_param("pos") or get_param("bounds") or [30, 60]
                raw_size = get_param("size", "medium")

                bx = raw_pos[0]
                by = raw_pos[1]

                size_presets = {
                    "small": (220, 100),
                    "sm": (220, 100),
                    "medium": (280, 120),
                    "md": (280, 120),
                    "large": (350, 150),
                    "lg": (350, 150),
                    "xlarge": (450, 180),
                    "xl": (450, 180)
                }

                if isinstance(raw_size, str):
                    bw, bh = size_presets.get(raw_size.lower(), (280, 120))
                elif isinstance(raw_size, (list, tuple)) and len(raw_size) >= 2:
                    bw, bh = int(raw_size[0]), int(raw_size[1])
                elif isinstance(raw_size, (int, float)):
                    bw = int(raw_size)
                    bh = int(bw * 0.45)
                else:
                    bw, bh = 280, 120

                # Universal Board Guardrail: Auto-scale physical viewport if exceeding screen space
                avail_w = max(100, self.width - 20 - bx)
                avail_h = max(60, self.height - 20 - by)
                if bw > avail_w:
                    scale_factor = float(avail_w) / float(bw)
                    bw = avail_w
                    bh = int(bh * scale_factor)
                if bh > avail_h:
                    scale_factor = float(avail_h) / float(bh)
                    bh = avail_h
                    bw = int(bw * scale_factor)

                # 1. Smart Title Rendering
                top_offset = 4
                disp_title = title or f"Number Line: {min_v} to {max_v}"
                if disp_title:
                    title_color = "#1565C0"
                    max_t_w = max(150, bw - 20)
                    has_math_title = any(sym in disp_title for sym in ["\\", "$", "^", "_", "{", "}", "=", "+", "-"])
                    if has_math_title:
                        timg = render_latex_to_pil(disp_title, font_size=14, color=title_color, max_width=max_t_w)
                        if timg:
                            img.paste(timg, (bx + 10, by + 4), timg)
                            top_offset = timg.height + 8
                        else:
                            tfont = get_fitted_font(sanitize_text(disp_title), max_t_w, initial_size=14, bold=True)
                            draw.text((bx + 10, by + 4), sanitize_text(disp_title), fill=title_color, font=tfont)
                            top_offset = 26
                    else:
                        clean_t = sanitize_text(disp_title)
                        tfont = get_fitted_font(clean_t, max_t_w, initial_size=14, bold=True)
                        draw.text((bx + 10, by + 4), clean_t, fill=title_color, font=tfont)
                        top_offset = 26

                # 2. Number Line Axis
                lx, ly, lw = bx + 25, by + top_offset + (bh - top_offset) // 2 + 10, bw - 50
                draw.line([(lx, ly), (lx + lw, ly)], fill="#333333", width=3)
                draw.polygon([(lx - 6, ly), (lx + 4, ly - 5), (lx + 4, ly + 5)], fill="#333333")
                draw.polygon([(lx + lw + 6, ly), (lx + lw - 4, ly - 5), (lx + lw - 4, ly + 5)], fill="#333333")

                total_range = max(1, max_v - min_v)
                tick_positions = {}
                num_font = get_fitted_font("0", 20, initial_size=12, bold=True)

                for v in range(min_v, max_v + 1, step_v):
                    tx = lx + int((v - min_v) / total_range * lw)
                    tick_positions[v] = tx
                    draw.line([(tx, ly - 6), (tx, ly + 6)], fill="#333333", width=2)
                    draw.text((tx - 4, ly + 8), str(v), fill="#212121", font=num_font)

                # Parse Hop Arcs (supports [3, 5] list of hop lengths OR [{"start":0, "end":3}] list of dicts)
                formatted_hops = []
                if isinstance(raw_hops, (list, tuple)):
                    curr_p = min_v
                    for h_item in raw_hops:
                        if isinstance(h_item, dict):
                            formatted_hops.append(h_item)
                        elif isinstance(h_item, (int, float)):
                            h_val = int(h_item)
                            formatted_hops.append({"start": curr_p, "end": curr_p + h_val})
                            curr_p += h_val

                # 3. Draw Hop Arc Curves
                for hop in formatted_hops:
                    h_start = hop.get("start", min_v)
                    h_end = hop.get("end", min_v + 1)
                    if h_start in tick_positions and h_end in tick_positions:
                        raw_x1 = tick_positions[h_start]
                        raw_x2 = tick_positions[h_end]
                        arc_h = 36

                        mid_x = (raw_x1 + raw_x2) // 2
                        mid_y = ly - arc_h

                        # Draw smooth curved arc
                        arc_pts = []
                        for step_i in range(21):
                            t_arc = step_i / 20.0
                            ax = int((1 - t_arc)**2 * raw_x1 + 2 * (1 - t_arc) * t_arc * mid_x + t_arc**2 * raw_x2)
                            ay = int((1 - t_arc)**2 * ly + 2 * (1 - t_arc) * t_arc * mid_y + t_arc**2 * ly)
                            arc_pts.append((ax, ay))

                        if len(arc_pts) >= 2:
                            draw.line(arc_pts, fill=color, width=3)
                            # Draw arrowhead at hop destination
                            end_pt = arc_pts[-1]
                            prev_pt = arc_pts[-3]
                            dx_a = end_pt[0] - prev_pt[0]
                            dy_a = end_pt[1] - prev_pt[1]
                            angle = math.atan2(dy_a, dx_a)

                            arrow_len = 10
                            arr_x1 = end_pt[0] - arrow_len * math.cos(angle - math.pi / 6)
                            arr_y1 = end_pt[1] - arrow_len * math.sin(angle - math.pi / 6)
                            arr_x2 = end_pt[0] - arrow_len * math.cos(angle + math.pi / 6)
                            arr_y2 = end_pt[1] - arrow_len * math.sin(angle + math.pi / 6)

                            draw.polygon([end_pt, (arr_x1, arr_y1), (arr_x2, arr_y2)], fill=color)

            elif elem_type == "tree":
                root_text = str(elem.get("root") or "").strip()
                title = str(elem.get("title") or "").strip()
                branches = elem.get("branches") or []
                raw_pos = get_param("pos", [40, 140])
                bx, by = int(raw_pos[0]), int(raw_pos[1])

                if title:
                    tfont = get_fitted_font(sanitize_text(title), 260, initial_size=14, bold=True)
                    draw.text((bx + 10, by + 4), sanitize_text(title), fill="#1B69B6", font=tfont)
                    by += 28

                node_font = get_fitted_font(root_text or "Root", 60, initial_size=16, bold=True)
                root_x, root_y = bx + 120, by + 20
                draw.ellipse([root_x - 24, root_y - 24, root_x + 24, root_y + 24], outline="#1B69B6", fill="#EBF3FA", width=3)
                draw.text((root_x - 10, root_y - 10), sanitize_text(root_text), fill="#1B69B6", font=node_font)

                if isinstance(branches, list) and branches:
                    for b_idx, b in enumerate(branches[:3]):
                        children = b.get("children") or []
                        if isinstance(children, list) and len(children) >= 2:
                            c1_text, c2_text = str(children[0]), str(children[1])
                            c1_x, c1_y = root_x - 50, root_y + 70 + b_idx * 70
                            c2_x, c2_y = root_x + 50, root_y + 70 + b_idx * 70

                            draw.line([(root_x, root_y + 24), (c1_x, c1_y - 20)], fill="#333333", width=2)
                            draw.line([(root_x, root_y + 24), (c2_x, c2_y - 20)], fill="#333333", width=2)

                            cfont1 = get_fitted_font(c1_text, 50, initial_size=14, bold=True)
                            draw.ellipse([c1_x - 20, c1_y - 20, c1_x + 20, c1_y + 20], outline="#2D7D46", fill="#EAF5ED", width=2)
                            draw.text((c1_x - 8, c1_y - 8), sanitize_text(c1_text), fill="#2D7D46", font=cfont1)

                            cfont2 = get_fitted_font(c2_text, 50, initial_size=14, bold=True)
                            draw.ellipse([c2_x - 20, c2_y - 20, c2_x + 20, c2_y + 20], outline="#2D7D46", fill="#EAF5ED", width=2)
                            draw.text((c2_x - 8, c2_y - 8), sanitize_text(c2_text), fill="#2D7D46", font=cfont2)


        # External Time Scrubber Bar: Appended below Y=800 (600x845) when animation payload is present
        max_d = getattr(self, "max_anim_duration", 0.0)
        if max_d > 0.0:
            bar_h = 45
            expanded_img = Image.new("RGB", (self.width, self.height + bar_h), color=bg_color)
            expanded_img.paste(img, (0, 0))

            bar_draw = ImageDraw.Draw(expanded_img)
            bar_y_start = self.height  # Y = 800

            # 1. Warm Bubbly Vanilla/Cream Panel Background (#FFF6E5) with Candy Amber Border (#FFE082)
            bar_draw.rectangle([0, bar_y_start, self.width, bar_y_start + bar_h], fill="#FFF6E5", outline="#FFE082", width=2)
            bar_draw.line([(0, bar_y_start), (self.width, bar_y_start)], fill="#E6D5C3", width=2)

            # 2. Bubbly Tangerine Play/Replay Button Orb (#FF7043)
            icon_cx, icon_cy = 30, bar_y_start + 22
            bar_draw.ellipse([icon_cx - 14, icon_cy - 14, icon_cx + 14, icon_cy + 14], fill="#FF7043", outline="#F4511E", width=2)
            bar_draw.polygon([(icon_cx - 4, icon_cy - 7), (icon_cx + 7, icon_cy), (icon_cx - 4, icon_cy + 7)], fill="#FFFFFF")

            # 3. Candy Track Line & Electric Cyan Progress Fill (X=65 to 485)
            track_x1 = 65
            track_x2 = 485
            track_y = bar_y_start + 22
            track_w = track_x2 - track_x1

            # Soft Pastel Mint/Lavender Track Background (#E0F2F1)
            bar_draw.line([(track_x1, track_y), (track_x2, track_y)], fill="#E0F2F1", width=10)
            bar_draw.ellipse([track_x1 - 5, track_y - 5, track_x1 + 5, track_y + 5], fill="#E0F2F1")
            bar_draw.ellipse([track_x2 - 5, track_y - 5, track_x2 + 5, track_y + 5], fill="#E0F2F1")

            # Determine current time
            if anim_progress is not None:
                cur_t = float(anim_progress) * max_d
            elif getattr(self, "current_scrub_time", None) is not None:
                cur_t = self.current_scrub_time
            else:
                cur_t = max_d

            ratio = max(0.0, min(1.0, cur_t / max_d))
            fill_x = track_x1 + int(ratio * track_w)

            # Vibrant Electric Turquoise/Cyan Active Fill (#00E5FF)
            if fill_x > track_x1:
                bar_draw.line([(track_x1, track_y), (fill_x, track_y)], fill="#00BCD4", width=10)
                bar_draw.ellipse([track_x1 - 5, track_y - 5, track_x1 + 5, track_y + 5], fill="#00BCD4")

            # Bubbly Golden Sun Draggable Thumb Handle (#FFCA28 with #FF6F00 candy outline & white highlight)
            bar_draw.ellipse([fill_x - 12, track_y - 12, fill_x + 12, track_y + 12], fill="#FFCA28", outline="#FF6F00", width=2)
            # Shiny white highlight bubble on top left of thumb
            bar_draw.ellipse([fill_x - 7, track_y - 7, fill_x - 2, track_y - 2], fill="#FFFFFF")

            # 4. Playful Rounded Pill Badge Container (#E1F5FE Soft Sky Blue)
            badge_str = f"{cur_t:.1f}s / {max_d:.1f}s"
            bfont = get_fitted_font(badge_str, 85, initial_size=12, bold=True)
            badge_x = 500
            badge_y = bar_y_start + 11
            bar_draw.rounded_rectangle([badge_x, badge_y, badge_x + 92, badge_y + 22], radius=11, fill="#E1F5FE", outline="#81D4FA", width=2)
            bar_draw.text((badge_x + 8, badge_y + 3), badge_str, fill="#0277BD", font=bfont)

            return expanded_img

        return img
