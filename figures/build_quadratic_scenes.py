"""Hand-curated, GUARANTEED-SYNCED scene specs for the whole quadratic-equations
chapter (jemh104).

Why this exists: the Gemini-authored scenes drifted out of sync — most visibly
`forming_quadratic_equations`, where beat 1 revealed every equation line at once and
the later beats narrated lines that were already on screen (voice 3 steps behind the
picture), and `quadratic_formula`, which narrated "use the quadratic formula" but only
drew a parabola and never applied the formula (and its root labels had no `at`, so the
renderer silently skipped them).

The cure is a strict contract, enforced structurally here:

    ONE beat  ==  ONE spoken sentence  ==  the ONE new line that sentence introduces.

No line appears before the sentence that says it; the string that is spoken and the
string that is drawn are authored together, so they cannot disagree. Lines accumulate
down a vertical column at evenly-computed canvas fractions (every label gets an `at`),
so nothing is ever dropped. The last line of each solve is highlighted in `accent`.

These double as the reviewed GOLD one-shot examples the Gemini author leans on
(`build_concept_scene.GOLD_EXAMPLE`), so the whole chapter pulls toward this standard.

    py -3 -m figures.build_quadratic_scenes            # write all 8 + self-check
    py -3 -m figures.build_quadratic_scenes --render   # also write preview GIFs
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from figures.build_concept_scene import validate_scene

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "rag_store" / "figure_specs"

TOP, BOTTOM = 0.24, 0.90        # canvas-fraction band the equation column lives in


def _size_for(text: str) -> int:
    """Auto-size so long algebra lines still fit the 500px card."""
    n = len(text)
    if n <= 18:
        return 23
    if n <= 26:
        return 20
    if n <= 34:
        return 17
    return 15


def column_scene(concept_id: str, title: str, steps: list[dict]) -> dict:
    """Build a DERIVATION-column scene from ordered steps.

    Each step = {"say": narration sentence, "line": the equation text it reveals,
    "accent": bool (highlight, e.g. the final answer)}. Every step introduces exactly
    one line, and the line is placed at its own row so the column accumulates in lock
    step with the narration."""
    n = len(steps)
    scene = {
        "version": 1,
        "concept_id": concept_id,
        "title": title,
        "canvas": {"w": 500, "h": 380, "pad_top": 30, "pad_bottom": 20,
                   "pad_left": 20, "pad_right": 20, "equal_aspect": False},
        "view": {"x0": 0, "y0": 0, "x1": 1, "y1": 1},
        "base": [],
        "beats": [],
    }
    for i, st in enumerate(steps):
        fy = TOP + (BOTTOM - TOP) * (i / (n - 1) if n > 1 else 0.5)
        line = st["line"]
        scene["beats"].append({
            "narration": st["say"],
            "anim_ms": 600,
            "hold_ms": 1100 if i < n - 1 else 1800,
            "in": [{
                "t": "label",
                "text": line,
                "space": "canvas",
                "at": [0.5, round(fy, 3)],
                "anchor": "center",
                "size": _size_for(line),
                "color": "accent" if st.get("accent") else "ink",
                "anim": "fade",
            }],
        })
    return scene


def graph_scene(concept_id: str, title: str, header: str, quad: list[float],
                domain: list[float], roots: list[tuple[float, str]],
                beats_text: dict, view: dict) -> dict:
    """Build a GRAPH scene: header equation, parabola draws on, roots appear + label.
    Kept for `roots_of_quadratic_equation`, the one concept a curve genuinely teaches
    better than a symbol column. Every beat still narrates exactly what it draws."""
    a, b, c = quad
    scene = {
        "version": 1,
        "concept_id": concept_id,
        "title": title,
        "canvas": {"w": 500, "h": 380, "pad_top": 58, "pad_bottom": 28,
                   "pad_left": 24, "pad_right": 24, "equal_aspect": False},
        "view": view,
        "base": [{"t": "axes", "x0": view["x0"] + 0.1, "y0": view["y0"],
                  "x1": view["x1"] - 0.2, "y1": view["y1"] - 0.4,
                  "grid": True, "step": 1}],
        "beats": [
            {"narration": beats_text["setup"], "anim_ms": 500, "hold_ms": 1000,
             "in": [{"t": "label", "text": header, "space": "canvas",
                     "at": [0.5, 0.1], "anchor": "center", "color": "accent",
                     "size": 22, "anim": "fade"}]},
            {"narration": beats_text["curve"], "anim_ms": 1300, "hold_ms": 500,
             "in": [{"t": "curve", "quad": [a, b, c], "domain": domain,
                     "stroke": "accent", "w": 4, "anim": "draw"},
                    {"t": "tracer", "quad": [a, b, c], "x_from": domain[0],
                     "x_to": domain[1], "r": 6, "fill": "accent2", "anim": "move"}]},
            {"narration": beats_text["cross"], "anim_ms": 600, "hold_ms": 1000,
             "in": [{"t": "point", "at": [roots[0][0], 0], "r": 7, "fill": "accent2",
                     "anim": "fade"},
                    {"t": "point", "at": [roots[1][0], 0], "r": 7, "fill": "accent2",
                     "anim": "fade"}]},
            {"narration": beats_text["roots"], "anim_ms": 600, "hold_ms": 1700,
             "in": [{"t": "label", "text": roots[0][1], "at": [roots[0][0] - 0.15, -0.25],
                     "anchor": "ne", "color": "ink", "size": 17, "anim": "fade"},
                    {"t": "label", "text": roots[1][1], "at": [roots[1][0] + 0.15, -0.25],
                     "anchor": "nw", "color": "ink", "size": 17, "anim": "fade"}]},
        ],
    }
    return scene


# ---------------------------------------------------------------------------
# The chapter, authored to the one-beat-one-sentence-one-line contract.
# ---------------------------------------------------------------------------

def all_scenes() -> list[dict]:
    scenes = []

    scenes.append(column_scene(
        "jemh104__quadratic_equation_definition",
        "Standard Form of a Quadratic Equation",
        [
            {"say": "A quadratic equation always has a term with x squared.",
             "line": "ax² + bx + c = 0", "accent": True},
            {"say": "It is written in standard form, where a, b and c are real numbers.",
             "line": "a, b, c are real numbers"},
            {"say": "The one strict rule is that a cannot be zero.",
             "line": "a ≠ 0", "accent": True},
            {"say": "For example, three x squared plus five x minus two equals zero.",
             "line": "3x² + 5x − 2 = 0"},
            {"say": "Here a is three, b is five, and c is minus two.",
             "line": "a = 3,  b = 5,  c = −2"},
        ]))

    scenes.append(column_scene(
        "jemh104__identifying_quadratic_equations",
        "Identifying Quadratic Equations",
        [
            {"say": "Is two x squared plus three x equal to two x squared minus five a quadratic equation?",
             "line": "2x² + 3x = 2x² − 5", "accent": True},
            {"say": "First, move every term to one side to set it equal to zero.",
             "line": "2x² + 3x − 2x² + 5 = 0"},
            {"say": "The two x squared terms cancel each other out.",
             "line": "3x + 5 = 0"},
            {"say": "The highest power of x left is one, not two.",
             "line": "highest power of x = 1"},
            {"say": "So this is not a quadratic equation.",
             "line": "Not a quadratic equation", "accent": True},
        ]))

    scenes.append(column_scene(
        "jemh104__forming_quadratic_equations",
        "Forming Quadratic Equations from Word Problems",
        [
            {"say": "Find two consecutive positive integers whose product is seventy-two.",
             "line": "two consecutive integers, product = 72"},
            {"say": "Let the first integer be x.",
             "line": "first integer = x"},
            {"say": "Then the next integer is x plus one.",
             "line": "next integer = x + 1"},
            {"say": "Their product is seventy-two, so x times x plus one equals seventy-two.",
             "line": "x(x + 1) = 72"},
            {"say": "Expand the left side to get x squared plus x equals seventy-two.",
             "line": "x² + x = 72"},
            {"say": "Move seventy-two across to form the quadratic equation.",
             "line": "x² + x − 72 = 0", "accent": True},
        ]))

    scenes.append(graph_scene(
        "jemh104__roots_of_quadratic_equation",
        "Roots of a Quadratic Equation",
        "x² − 2x − 3 = 0", [1, -2, -3], [-2.35, 4.35],
        [(-1, "x = −1"), (3, "x = 3")],
        {"setup": "Let's solve x squared minus two x minus three equals zero.",
         "curve": "Every quadratic draws a parabola, a smooth U-shaped curve.",
         "cross": "The roots are exactly where the curve crosses the x-axis.",
         "roots": "So the solutions are x equals minus one and x equals three."},
        {"x0": -3.2, "y0": -5, "x1": 5.2, "y1": 7}))

    scenes.append(column_scene(
        "jemh104__solving_by_factorization",
        "Solving Quadratic Equations by Factorization",
        [
            {"say": "Let's solve x squared plus five x plus six equals zero.",
             "line": "x² + 5x + 6 = 0", "accent": True},
            {"say": "We need two numbers that multiply to six and add to five.",
             "line": "want: product 6, sum 5"},
            {"say": "Two and three work, so we factor into x plus two times x plus three.",
             "line": "(x + 2)(x + 3) = 0"},
            {"say": "Now set each factor equal to zero.",
             "line": "x + 2 = 0   or   x + 3 = 0"},
            {"say": "So the roots are x equals minus two and x equals minus three.",
             "line": "x = −2   or   x = −3", "accent": True},
        ]))

    scenes.append(column_scene(
        "jemh104__quadratic_formula",
        "The Quadratic Formula",
        [
            {"say": "Let's solve x squared plus two x minus three equals zero using the quadratic formula.",
             "line": "x² + 2x − 3 = 0", "accent": True},
            {"say": "The quadratic formula gives x in terms of a, b and c.",
             "line": "x = (−b ± √(b² − 4ac)) / 2a"},
            {"say": "Here a is one, b is two, and c is minus three.",
             "line": "a = 1,  b = 2,  c = −3"},
            {"say": "Substitute those values into the formula.",
             "line": "x = (−2 ± √(2² − 4·1·(−3))) / 2"},
            {"say": "Under the root, four plus twelve is sixteen, whose square root is four.",
             "line": "x = (−2 ± 4) / 2"},
            {"say": "So the two roots are x equals one and x equals minus three.",
             "line": "x = 1   or   x = −3", "accent": True},
        ]))

    scenes.append(column_scene(
        "jemh104__discriminant_nature_of_roots",
        "Discriminant and Nature of Roots",
        [
            {"say": "Let's find the nature of the roots of two x squared plus three x minus five equals zero.",
             "line": "2x² + 3x − 5 = 0", "accent": True},
            {"say": "Identify a as two, b as three, and c as minus five.",
             "line": "a = 2,  b = 3,  c = −5"},
            {"say": "The discriminant D is b squared minus four a c.",
             "line": "D = b² − 4ac"},
            {"say": "Substitute the values.",
             "line": "D = 3² − 4·2·(−5)"},
            {"say": "That is nine plus forty, which equals forty-nine.",
             "line": "D = 9 + 40 = 49"},
            {"say": "Since D is greater than zero, there are two distinct real roots.",
             "line": "D > 0  →  two real roots", "accent": True},
        ]))

    scenes.append(column_scene(
        "jemh104__solving_real_world_problems",
        "Solving Real-World Problems with Quadratics",
        [
            {"say": "A garden's length is five metres more than its width, and its area is eighty-four square metres.",
             "line": "Area = 84 m²,  Length = Width + 5"},
            {"say": "Let the width be x, so the length is x plus five.",
             "line": "width = x,   length = x + 5"},
            {"say": "Area is length times width, so x times x plus five equals eighty-four.",
             "line": "x(x + 5) = 84"},
            {"say": "Expand and rearrange into a quadratic equation.",
             "line": "x² + 5x − 84 = 0"},
            {"say": "Factor it into x minus seven times x plus twelve.",
             "line": "(x − 7)(x + 12) = 0"},
            {"say": "So x is seven or minus twelve.",
             "line": "x = 7   or   x = −12"},
            {"say": "Width can't be negative, so the width is seven metres and the length is twelve.",
             "line": "width = 7 m,   length = 12 m", "accent": True},
        ]))

    return scenes


def _shape_of(scene: dict) -> str:
    """derivation (a symbol column) vs graph (has axes/curve) — for the index."""
    els = list(scene.get("base", [])) + [e for b in scene["beats"] for e in b.get("in", [])]
    return "graph" if any(e.get("t") in ("axes", "curve") for e in els) else "derivation"


def write_index() -> None:
    """Regenerate rag_store/concept_figures.json from EVERY *.scene.json on disk so
    the live-mic tier-0 lookup (scene_for_concept) has accurate beats/shape metadata.
    The lookup reads the scene file itself, but keeping the index truthful matters for
    the startup count log and any tooling that trusts it."""
    idx = {}
    for p in sorted(SPECS.glob("*.scene.json")):
        s = json.loads(p.read_text(encoding="utf-8"))
        cid = s.get("concept_id") or p.name.split(".scene.json")[0]
        idx[cid] = {
            "scene": f"rag_store/figure_specs/{p.name}",
            "beats": len(s.get("beats", [])),
            "title": s.get("title", ""),
            "shape": _shape_of(s),
        }
    out = ROOT / "rag_store" / "concept_figures.json"
    out.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"index -> {out.name}  ({len(idx)} concepts)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--render", action="store_true", help="also write preview GIFs")
    args = ap.parse_args()

    SPECS.mkdir(parents=True, exist_ok=True)
    ok = True
    for scene in all_scenes():
        cid = scene["concept_id"]
        errs = validate_scene(scene)
        if errs:
            ok = False
            print(f"INVALID {cid}:")
            for e in errs:
                print("   -", e)
            continue
        out = SPECS / f"{cid}.scene.json"
        out.write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"ok  {len(scene['beats'])} beats  -> {out.name}")
        if args.render:
            from figures.scene_render import render_gif
            gif = SPECS / f"{cid}.preview.gif"
            render_gif(scene, "light", 2.0, str(gif), 25)
            print(f"    gif -> {gif.name}")
    write_index()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
