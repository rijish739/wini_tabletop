"""Draw the answer — generate a declarative scene spec FROM the tutor's spoken answer.

This is the plan's ``generated_declarative_scene_spec`` visual type (§12.2) and the fix
for "visuals must be text-aware": instead of reusing a canned per-concept scene whose
worked example has nothing to do with what Wini just said, we build the figure FROM her
actual answer, so the picture and the voice match by construction.

Safety follows §3.3 "LLMs plan; deterministic systems render":
  * the LLM ONLY extracts the ordered *board lines* to show (short formula/step/number
    strings copied from the answer, no new facts) — a tiny structured call;
  * the brain lays them out DETERMINISTICALLY into a valid scene spec (canvas 500x380,
    a vertical stack of `label` beats, each with `at` always set — so the renderer's
    "skipping label missing ['at']" class of errors is impossible);
  * a number in a board line that is not grounded in the answer is DROPPED (belt against
    the model inventing a value the tutor never said).

The result is the SAME scene schema the device already renders (figures.scene_render.
render_beat_frame), so it drops straight into the existing beat player — no renderer
change. Beats carry empty narration: the scene is VISUAL-ONLY (Wini's streamed answer is
the audio), the board just mirrors it.
"""

from __future__ import annotations

import math
import re

# device figure card is 500x380 (display_sinks.FIG_MAX_W/H); fractional-canvas coords
CANVAS = {"w": 500, "h": 380, "pad_top": 30, "pad_bottom": 20,
          "pad_left": 20, "pad_right": 20, "equal_aspect": False}
VIEW = {"x0": 0, "y0": 0, "x1": 1, "y1": 1}

# A parabola graph uses a DATA view (fractional coords give way to real x/y) and a
# taller top pad so the equation label sits above the plotted axes (mirrors the
# authored jemh104 parabola scenes). The renderer plots any quad=[a,b,c] natively.
GRAPH_CANVAS = {"w": 500, "h": 380, "pad_top": 52, "pad_bottom": 26,
                "pad_left": 24, "pad_right": 24, "equal_aspect": False}

MAX_LINES = 6
MIN_LINES = 2
MAX_LINE_CHARS = 42

_NUM_RE = re.compile(r"(?<![A-Za-z_])\d+(?:\.\d+)?")

# spoken answers spell small numbers as words (TTS-friendly), so a board line "2x+3"
# must ground against "two ... three". Map the common ones both ways.
_NUM_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
    "nineteen": "19", "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50",
    "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90", "hundred": "100",
}


def _board_schema():
    from google.genai import types
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "title": types.Schema(type=types.Type.STRING),
            "lines": types.Schema(type=types.Type.ARRAY,
                                  items=types.Schema(type=types.Type.STRING)),
            # When the answer is about a quadratic / parabola graph, the model reports the
            # coefficients of the quadratic it is talking about (y = a x^2 + b x + c). The
            # brain then plots the curve and COMPUTES the roots/vertex deterministically —
            # the model never invents the geometry (§3.3 LLMs plan, deterministic renders).
            "parabola": types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "present": types.Schema(type=types.Type.BOOLEAN),
                    "a": types.Schema(type=types.Type.NUMBER),
                    "b": types.Schema(type=types.Type.NUMBER),
                    "c": types.Schema(type=types.Type.NUMBER),
                },
            ),
        },
        required=["lines"],
    )


_PROMPT = (
    "You are laying out a small teaching BOARD that mirrors, on screen, the maths a tutor "
    "is speaking aloud right now. From the tutor's answer below, list the KEY lines to "
    "SHOW as she talks — the equation, each worked step, key numbers, or a short "
    "definition — in the SAME order she says them.\n"
    "Rules:\n"
    f"- 2 to {MAX_LINES} lines, each SHORT (<= {MAX_LINE_CHARS} characters), fits on a card.\n"
    "- Copy the maths FROM THE ANSWER. Do NOT introduce any number, term, or step the "
    "answer does not state. Use digits and symbols (x, =, +, -, ^, sqrt) — not words.\n"
    "- No prose sentences on the board; just the maths lines.\n"
    "- If the answer has no maths worth putting on a board, return an empty list.\n"
    "GRAPH: set parabola.present=true ONLY when teaching the PARABOLA/graph is the MAIN "
    "point of the answer — its U-shape, how it opens up or down, WHERE IT CROSSES the "
    "x-axis (roots as points on the curve), or its vertex. Then give a, b, c of the "
    "quadratic y = a*x^2 + b*x + c being graphed: the SPECIFIC numbers if the answer (or "
    "the CONTEXT below) is about a specific quadratic (e.g. x^2 - 5x + 6 -> a=1, b=-5, "
    "c=6), otherwise a=1, b=0, c=0 for the general shape.\n"
    "Set parabola.present=FALSE when the answer is about HOW TO SOLVE (factorising, the "
    "quadratic formula, completing the square, splitting the middle term, computing the "
    "roots) or DEFINES the equation — EVEN IF it mentions in passing that 'the graph is a "
    "parabola'. A passing mention is NOT a reason to draw a graph; those answers get the "
    "text board instead. Never set a=0.\n"
    "Also give a SHORT title (<= 30 chars).\n\n"
    "{context}ANSWER:\n{answer}\n"
)

# Answer wording that means the turn is really about SOLVING, not the graph — used as a
# deterministic belt so a GENERIC (y=x²) parabola can never hijack a solving answer even
# if the model over-flags it. Specific parabolas (real roots) are never touched by this.
_SOLVE_MARKERS = (
    "factor", "formula", "complete the square", "completing the square",
    "split", "middle term", "discriminant", "grouping", "the roots are",
)


def extract_board_lines(answer: str, concept_id: str | None = None,
                        context: str | None = None
                        ) -> tuple[str, list[str], dict | None]:
    """One structured Gemini call → (title, [board line, ...], parabola|None).

    ``parabola`` is ``{"a","b","c"}`` when the answer is about a quadratic graph, else
    None. ``context`` (recent conversation) lets a follow-up like "why is it a parabola"
    plot the SPECIFIC quadratic on the table instead of a generic y=x². Never raises to
    the caller (the caller degrades to a text board / speech-only)."""
    from llm_vertex import generate_json

    ctx = (f"CONTEXT (recent conversation — use it to identify the specific quadratic "
           f"under discussion, if any):\n{context[:600]}\n\n") if context else ""
    res = generate_json(_PROMPT.format(context=ctx, answer=answer[:2000]),
                        response_schema=_board_schema(),
                        temperature=0.0, max_output_tokens=500)
    if not res.ok or not isinstance(res.data, dict):
        return "", [], None
    raw = res.data.get("lines") or []
    lines = [str(x).strip()[:MAX_LINE_CHARS] for x in raw if str(x).strip()][:MAX_LINES]
    title = str(res.data.get("title") or "").strip()[:40]
    return title, lines, _parse_parabola(res.data.get("parabola"))


def _parse_parabola(p) -> dict | None:
    """Coerce the model's parabola object to floats a,b,c (a!=0), or None. Defensive:
    a wrong-but-valid or partial object must never raise — it just means 'no graph'."""
    if not isinstance(p, dict) or not p.get("present"):
        return None
    try:
        a, b, c = float(p.get("a")), float(p.get("b", 0.0)), float(p.get("c", 0.0))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(a) or not math.isfinite(b) or not math.isfinite(c) or abs(a) < 1e-9:
        return None
    # keep coefficients in a sane textbook range so the view/curve stay legible
    if max(abs(a), abs(b), abs(c)) > 50:
        return None
    return {"a": a, "b": b, "c": c}


def _answer_number_set(answer: str) -> set[str]:
    """Numbers the answer states, as digit strings — literal digits plus number-words
    mapped to digits, so a spoken 'two x minus three' grounds a board '2x - 3'."""
    nums = set(_NUM_RE.findall(answer or ""))
    low = (answer or "").lower()
    for word, dig in _NUM_WORDS.items():
        if re.search(rf"\b{word}\b", low):
            nums.add(dig)
    return nums


def _ground_lines(lines: list[str], answer: str) -> list[str]:
    """Drop a line that shows a MULTI-DIGIT number the answer never states — the real
    hallucination risk (a wrong computed result). Single-digit numbers pass untouched:
    they are usually structural formula constants (the 2 and 4 in b²-4ac / 2a) or small
    values already extracted from the answer, and enforcing them would wrongly drop the
    quadratic formula itself."""
    grounded = _answer_number_set(answer)
    kept = []
    for ln in lines:
        risky = {n for n in _NUM_RE.findall(ln) if len(n.replace(".", "")) >= 2}
        if risky - grounded:
            continue  # a multi-digit board number the tutor never said -> drop
        kept.append(ln)
    return kept


def _fmt_num(v: float) -> str:
    """Compact number for a board label: 3 not 3.0, 1.5 kept, minus as U+2212."""
    s = f"{v:.2f}".rstrip("0").rstrip(".") if v % 1 else str(int(round(v)))
    return s.replace("-", "−")


def _fmt_quad(a: float, b: float, c: float) -> str:
    """'y = x² − 2x − 3' style equation string from coefficients (drops 1·, 0 terms)."""
    def term(coef, suffix, first):
        if abs(coef) < 1e-9:
            return ""
        sign = "−" if coef < 0 else ("" if first else "+")
        mag = abs(coef)
        body = "" if (abs(mag - 1) < 1e-9 and suffix) else _fmt_num(mag).lstrip("−")
        pad = "" if first else " "
        return f"{pad}{sign}{pad if not first else ''}{body}{suffix}"
    head = term(a, "x²", True) or "0"
    rest = term(b, "x", False) + term(c, "", False)
    return f"y = {head}{rest}".replace("  ", " ").strip()


def parabola_scene(concept_id: str | None, a: float, b: float, c: float,
                   title: str = "") -> dict:
    """Deterministically DRAW the parabola y = a x² + b x + c: axes + curve + a tracer +
    the real roots (computed here, not by the model) + labels. The curve/tracer feed the
    coefficients straight to the renderer's native quad plotter (_quad_y)."""
    disc = b * b - 4 * a * c
    roots: list[float] = []
    if disc >= 0:
        sq = math.sqrt(disc)
        roots = sorted({round((-b - sq) / (2 * a), 4), round((-b + sq) / (2 * a), 4)})
    vx = -b / (2 * a)
    vy = a * vx * vx + b * vx + c

    # x-domain: hug the roots (or the vertex when none), always show a little margin.
    if len(roots) >= 2:
        span = roots[-1] - roots[0]
        pad = max(1.2, span * 0.45)
        dx0, dx1 = roots[0] - pad, roots[-1] + pad
    else:
        dx0, dx1 = vx - 3.5, vx + 3.5
    # y-range from the curve values across the domain + the vertex, padded, and clamped
    # so a steep parabola never collapses the plot.
    ys = [a * dx0 * dx0 + b * dx0 + c, a * dx1 * dx1 + b * dx1 + c, vy, 0.0]
    ymin, ymax = min(ys), max(ys)
    if ymax - ymin > 16:                      # steep 'a': frame the vertex, not the tails
        if a > 0:
            ymax = vy + 12
        else:
            ymin = vy - 12
    ypad = max(0.8, (ymax - ymin) * 0.12)
    view = {"x0": round(dx0 - 0.3, 3), "y0": round(ymin - ypad, 3),
            "x1": round(dx1 + 0.3, 3), "y1": round(ymax + ypad, 3)}
    base = [{"t": "axes", "x0": view["x0"], "y0": view["y0"],
             "x1": view["x1"], "y1": view["y1"], "grid": True, "step": 1}]

    quad = [round(a, 4), round(b, 4), round(c, 4)]
    beats = [
        {"narration": "", "anim_ms": 400, "hold_ms": 700, "in": [{
            "t": "label", "text": _fmt_quad(a, b, c), "space": "canvas",
            "at": [0.5, 0.075], "anchor": "center", "size": 22, "color": "accent",
            "anim": "fade"}]},
        {"narration": "", "anim_ms": 900, "hold_ms": 500, "in": [
            {"t": "curve", "quad": quad, "domain": [round(dx0, 3), round(dx1, 3)],
             "stroke": "accent", "w": 4, "anim": "draw"},
            {"t": "tracer", "quad": quad, "x_from": round(dx0, 3), "x_to": round(dx1, 3),
             "r": 6, "fill": "accent2", "anim": "move"}]},
    ]
    if roots:
        beats.append({"narration": "", "anim_ms": 350, "hold_ms": 800,
                      "in": [{"t": "point", "at": [r, 0], "r": 7, "fill": "accent2",
                              "anim": "fade"} for r in roots]})
        beats.append({"narration": "", "anim_ms": 350, "hold_ms": 900,
                      "in": [{"t": "label", "text": f"x = {_fmt_num(r)}",
                              "at": [r + 0.15, -0.25],
                              "anchor": ("nw" if i or len(roots) == 1 else "ne"),
                              "color": "ink", "size": 17, "anim": "fade"}
                             for i, r in enumerate(roots)]})
    else:
        # No real roots: mark the vertex so the learner still sees where the curve turns.
        beats.append({"narration": "", "anim_ms": 350, "hold_ms": 900, "in": [
            {"t": "point", "at": [round(vx, 3), round(vy, 3)], "r": 7, "fill": "accent2",
             "anim": "fade"},
            {"t": "label", "text": "no real roots", "space": "canvas",
             "at": [0.5, 0.9], "anchor": "center", "size": 16, "color": "muted",
             "anim": "fade"}]})

    scene = {
        "version": 1,
        "concept_id": concept_id or "drawn",
        "title": (title or "Parabola")[:40],
        "canvas": dict(GRAPH_CANVAS), "view": view,
        "base": base, "beats": beats,
        "generated": True, "graph_kind": "parabola",
    }
    from .scene_adaptation import add_contract
    add_contract(scene)
    return scene


def layout_scene(concept_id: str | None, title: str, lines: list[str]) -> dict:
    """Deterministic vertical stack of label beats. Every label carries `at`
    (fractional canvas coords), so render_beat_frame never skips one."""
    n = len(lines)
    top, bot = 0.16, 0.88
    size = 24 if n <= 3 else (20 if n <= 5 else 17)
    beats = []
    for i, ln in enumerate(lines):
        y = top if n == 1 else top + (bot - top) * i / (n - 1)
        beats.append({
            "narration": "",                       # visual-only; the answer is the audio
            "anim_ms": 450, "hold_ms": 900,
            "in": [{
                "t": "label", "text": ln, "space": "canvas",
                "at": [0.5, round(y, 3)], "anchor": "center",
                "size": size, "color": ("accent" if i == 0 else "ink"), "anim": "fade",
            }],
        })
    scene = {
        "version": 1,
        "concept_id": concept_id or "drawn",
        "title": title or "",
        "canvas": dict(CANVAS), "view": dict(VIEW),
        "base": [], "beats": beats,
        "generated": True,                          # marks a drawn-from-answer scene
    }
    # Phase 2.5 applies to generated specs too: the visual has claim tags and live
    # narration is explicitly script-owned, even though generated beats are blank.
    from .scene_adaptation import add_contract
    add_contract(scene)
    return scene


def _is_generic_parabola(p: dict) -> bool:
    """The default illustrative y = x² (a=1, b=0, c=0) — no specific roots to teach."""
    return (abs(p["a"] - 1) < 1e-9 and abs(p["b"]) < 1e-9 and abs(p["c"]) < 1e-9)


def _looks_like_solving(answer: str) -> bool:
    """Answer is really about SOLVING (factorise/formula/steps), not the graph."""
    low = (answer or "").lower()
    return sum(m in low for m in _SOLVE_MARKERS) >= 2


def author_scene_from_answer(answer: str, concept_id: str | None = None,
                             evidence: list[dict] | None = None,
                             context: str | None = None) -> dict | None:
    """Full pipeline: extract board lines from the answer, drop ungrounded numbers,
    lay them out. Returns a valid scene spec, or None when there is nothing math-worthy
    to draw / the call failed (caller then degrades to speech-only).

    ``context`` (recent conversation) is used only to identify a specific quadratic for
    the graph path — it never adds spoken/text content."""
    if not answer or len(answer.split()) < 6:
        return None
    try:
        title, lines, parabola = extract_board_lines(answer, concept_id, context)
    except Exception:  # noqa: BLE001 — a drawing failure must never cost the turn
        return None
    grounded = _ground_lines(lines, answer)
    # Belt (Q1 fix): a GENERIC y=x² parabola must never hijack a solving/procedural
    # answer — a passing "the graph is a parabola" is not a reason to draw an empty
    # curve when the real teaching is the worked steps. A SPECIFIC parabola (real roots)
    # is always kept: the graph IS the point there.
    if parabola and _is_generic_parabola(parabola) and _looks_like_solving(answer) \
            and len(grounded) >= 2:
        parabola = None
    # Prefer a real GRAPH when the answer is genuinely about a parabola: draw the actual
    # curve + its roots instead of a text stack. Coefficients come from the answer/context;
    # the geometry (roots, vertex, view) is computed deterministically in parabola_scene.
    if parabola:
        try:
            return parabola_scene(concept_id, parabola["a"], parabola["b"],
                                  parabola["c"], title)
        except Exception:  # noqa: BLE001 — fall back to the text board on any math error
            pass
    if len(grounded) < MIN_LINES:
        return None
    return layout_scene(concept_id, title, grounded)
