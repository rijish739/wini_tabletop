"""Author a narration-synced SCENE spec for a concept, with Vertex Gemini.

Stage B of the visuals plan (RAG_STORE_VISUALS_RESEARCH.md), scene variant. Given a
concept, ask Gemini for a `{title, canvas, view, base, beats[]}` scene under a
`response_schema` (so the primitive `t` and `anchor` values are decoding-constrained —
the CLAUDE.md "enums stop invented values" belt), validate it locally with
`figure_schema.validate` + scene-shape checks, and write it to
`rag_store/figure_specs/<concept_id>.scene.json`. Each beat's `narration` is one
sentence Wini speaks; the client fires that beat's animation when it streams that
sentence to TTS (see SCENE_SYNC.md).

Safety / cost discipline (matches the perception seam):
  * `generate_json` bounds the call with a hard wall-clock timeout,
  * `temperature=0`, `thinking_budget=0` (short structured reply),
  * NOTHING is billed unless you pass `--run`; `--dry-run` (default) prints the exact
    prompt + schema so the contract can be reviewed offline first,
  * `--self-check FILE` validates an existing hand-authored scene with no network.

Usage:
    py -3 -m figures.build_concept_scene jemh104__roots_of_quadratic_equation           # dry-run
    py -3 -m figures.build_concept_scene jemh104__roots_of_quadratic_equation --run --render
    py -3 -m figures.build_concept_scene --self-check rag_store/figure_specs/<id>.scene.json
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

from figures import figure_schema

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "rag_store"
SPECS = STORE / "figure_specs"
GOLD_EXAMPLE = SPECS / "jemh104__roots_of_quadratic_equation.scene.json"

PRIMS = list(figure_schema.PRIMITIVES) + ["curve", "tracer"]  # + animation primitives
TOKENS = list(figure_schema.COLOR_TOKENS)
ANCHORS = list(figure_schema.ANCHORS)

SYSTEM = f"""You author ANIMATED MATHS SCENES for a children's tutor that draws on a
500x380 card while a voice explains a worked solution step by step. You output ONE JSON
object; no prose, no markdown. Every string must be SHORT — the only place for
explanation is a beat's `narration`; never put descriptions in `text` or any other
field. Emit only the fields shown in the example.

A scene is a static `base` (drawn once) plus 3-5 ordered `beats`. Each beat is ONE
sentence of spoken narration plus the elements that appear during it. The visual and
the speech advance together, so narration must read as a natural spoken explanation and
each beat must add only what that sentence introduces.

COORDINATES. Elements use `view` maths coordinates (y is UP). Choose `view` so the whole
figure fits with margin. `canvas` reserves bands the plot never draws into:
`pad_top` for a header (put the equation/title here), `pad_bottom` for a footer,
`pad_left`/`pad_right` for axis labels. Use `equal_aspect:false` for function graphs.

PRIMITIVES (field `t`, one of): {PRIMS}
  axes   : x0,y0,x1,y1, grid(bool), step, arrows(bool)
  curve  : quad:[a,b,c] (y=ax^2+bx+c) sampled over domain:[x0,x1]; anim:"draw" reveals it
  tracer : a dot riding quad from x_from to x_to; anim:"move"
  segment: pts:[[x,y],[x,y]], dash(bool); anim:"draw" grows it
  polygon: pts:[...], fill, stroke
  point  : at:[x,y], r, fill; anim:"fade"
  right_angle: at, from, to, size
  label  : text, at, anchor, size, color; `space:"canvas"` places it by canvas fraction
           (0..1) for header/footer text; otherwise `at` is a view point.

RULES.
  * EVERY label needs an `at`. A `space:"canvas"` label uses `at:[fx,fy]` canvas
    fractions (0..1); a view label uses `at:[x,y]` maths coords. Never omit `at`.
  * The `label` FIELD belongs only to a `point` (its dot caption). On a `t:"label"`
    element use `text`, never a `label` field.
  * Put the equation/title in the header: a `space:"canvas"` label at `at:[0.5,~0.09]`,
    `anchor:"center"`. NEVER a view label over the axes.
  * TWO scene shapes, pick by the concept:
     - GRAPH concept (roots, coordinate geometry): draw axes/curve/points in `view`
       coords; put value labels OUTSIDE any filled/curved region.
     - DERIVATION concept (a formula, a symbolic solve — like this one): NO axes. Build
       a COLUMN of equation lines as `space:"canvas"` labels, one algebra step per beat,
       stacked with increasing `fy` (e.g. 0.18, 0.32, 0.46, 0.60, 0.74), `anchor:"center"`,
       size ~20. Earlier lines stay on screen so the derivation accumulates; highlight the
       final answer line with `color:"accent"`. Keep to ONE line per beat where you can.
  * Colours are ONLY these tokens: {TOKENS} (or a #rrggbb). `accent`=main curve/answer,
    `accent2`=highlighted points, `muted`=guides/grid, `ink`=body text.
  * anim is "fade" | "draw" | "move". anim_ms 400-1400, hold_ms 600-1800.
  * Maths text may use unicode: superscripts x², subscripts x₁, √, and − (U+2212) for
    minus. Keep each narration sentence short and speakable.
HARD LIMITS (never exceed — the card is small and the reply must fit).
  * AT MOST 6 beats, and AT MOST 6 elements in any one beat's `in`.
  * A beat introduces ONLY what its sentence adds. NEVER re-emit a label whose `text`
    you already placed in an earlier beat — earlier elements stay on screen on their own.
    Do not restate the standard-form equation on every step.
Return a scene with the SAME shape as the example provided."""

USER_TMPL = """Concept: {name}  (id: {concept_id}, chapter {chapter})
Summary: {summary}
Representations to lean on: {reps}
Key vocabulary: {vocab}

Author a scene that teaches ONE concrete worked example of this concept as it is spoken
aloud — reveal the setup, then build to the answer. Pick clean numbers. 3-5 beats."""


def _load_concept(concept_id: str) -> dict:
    data = json.load(io.open(STORE / "concepts.json", encoding="utf-8"))
    for c in data:
        if c["concept_id"] == concept_id:
            return c
    raise SystemExit(f"concept not found: {concept_id}")


SHAPE_HINT = {
    "graph": ("\n\nSHAPE OVERRIDE — author this as a GRAPH, not a derivation column: "
              "draw `axes` (with the x-axis and y-axis), a `curve` for the parabola "
              "(pick clean integer roots), and mark the two roots as `point`s on the "
              "x-axis with short labels OUTSIDE the curve. Reveal setup → curve → "
              "roots across the beats. Put the equation in the header band only. NO "
              "stacked equation column."),
    "derivation": ("\n\nSHAPE OVERRIDE — author this as a DERIVATION column of "
                   "`space:\"canvas\"` equation lines (no axes), one algebra step per "
                   "beat, final answer in `accent`."),
}


def _build_prompt(concept: dict, shape: str | None = None) -> tuple[str, str]:
    vocab = ", ".join(v.get("term", v) if isinstance(v, dict) else v
                      for v in (concept.get("vocabulary") or [])[:8])
    user = USER_TMPL.format(
        name=concept["name"], concept_id=concept["concept_id"],
        chapter=concept.get("chapter_doc", "?"),
        summary=(concept.get("summary") or "")[:600],
        reps=", ".join(concept.get("representations") or []),
        vocab=vocab or "(none)",
    )
    if shape in SHAPE_HINT:
        user += SHAPE_HINT[shape]
    # One-shot: hand the model the reviewed gold scene as the format anchor.
    if GOLD_EXAMPLE.exists():
        user += ("\n\nHere is a GOLD example scene (same JSON shape you must return, for a "
                 "different concept):\n"
                 + GOLD_EXAMPLE.read_text(encoding="utf-8"))
    return SYSTEM, user


def _scene_response_schema():
    """genai types.Schema for a scene. Constrains `t`/`anchor` to the vocabulary
    (the decoding belt); everything else is optional and validated locally."""
    from google.genai import types as T

    def S(**kw):
        return T.Schema(**kw)

    num = S(type=T.Type.NUMBER)
    num_arr = S(type=T.Type.ARRAY, items=num)
    pts = S(type=T.Type.ARRAY, items=num_arr)
    element = S(
        type=T.Type.OBJECT,
        required=["t"],
        properties={
            "t": S(type=T.Type.STRING, enum=PRIMS),
            "at": num_arr, "from": num_arr, "to": num_arr, "pts": pts,
            "quad": num_arr, "domain": num_arr,
            "x_from": num, "x_to": num, "r": num, "size": num, "w": num,
            "samples": num, "step": num, "start": num, "end": num,
            "x0": num, "y0": num, "x1": num, "y1": num,
            "grid": S(type=T.Type.BOOLEAN), "dash": S(type=T.Type.BOOLEAN),
            "arrows": S(type=T.Type.BOOLEAN), "italic": S(type=T.Type.BOOLEAN),
            "text": S(type=T.Type.STRING),
            "anchor": S(type=T.Type.STRING, enum=ANCHORS),
            "space": S(type=T.Type.STRING, enum=["view", "canvas"]),
            "color": S(type=T.Type.STRING), "fill": S(type=T.Type.STRING),
            "stroke": S(type=T.Type.STRING), "anim": S(type=T.Type.STRING),
        },
    )
    # NOTE: no generic `label`/`label_anchor` string property — the model kept abusing
    # it as a free-text annotation and blew the token budget. Point captions in a
    # hand-authored spec still work (the renderer reads `label`); the LLM just attaches
    # a separate `t:"label"` element near the point instead.
    beat = S(
        type=T.Type.OBJECT, required=["narration", "in"],
        properties={
            "narration": S(type=T.Type.STRING),
            "anim_ms": S(type=T.Type.INTEGER), "hold_ms": S(type=T.Type.INTEGER),
            "in": S(type=T.Type.ARRAY, items=element),
        },
    )
    canvas = S(
        type=T.Type.OBJECT, required=["w", "h"],
        properties={k: (S(type=T.Type.BOOLEAN) if k == "equal_aspect"
                         else S(type=T.Type.INTEGER))
                    for k in ("w", "h", "pad_top", "pad_bottom", "pad_left",
                              "pad_right", "equal_aspect")},
    )
    view = S(type=T.Type.OBJECT, required=["x0", "y0", "x1", "y1"],
             properties={k: num for k in ("x0", "y0", "x1", "y1")})
    return S(
        type=T.Type.OBJECT,
        required=["concept_id", "title", "canvas", "view", "beats"],
        properties={
            "concept_id": S(type=T.Type.STRING), "title": S(type=T.Type.STRING),
            "canvas": canvas, "view": view,
            "base": S(type=T.Type.ARRAY, items=element),
            "beats": S(type=T.Type.ARRAY, items=beat),
        },
    )


def validate_scene(scene: dict) -> list[str]:
    """Static-figure element checks + scene-shape checks (beats, narration, anims)."""
    errs: list[str] = []
    for k in ("concept_id", "canvas", "view", "beats"):
        if k not in scene:
            errs.append(f"missing key: {k}")
    if errs:
        return errs
    # reuse the element validator by flattening base + all beat elements
    flat = {"version": 1, "concept_id": scene["concept_id"], "canvas": scene["canvas"],
            "view": scene["view"],
            "elements": list(scene.get("base", []))
            + [e for b in scene["beats"] for e in b.get("in", [])]}
    errs += figure_schema.validate(flat, extra_primitives=("curve", "tracer"))
    if not scene["beats"]:
        errs.append("scene has no beats")
    for i, b in enumerate(scene["beats"]):
        if not (b.get("narration") or "").strip():
            errs.append(f"beat[{i}] has empty narration")
        if "in" not in b:
            errs.append(f"beat[{i}] missing 'in'")
    return errs


def _normalize(scene: dict, concept_id: str) -> dict:
    scene.setdefault("version", 1)
    scene["concept_id"] = concept_id
    scene.setdefault("base", [])
    for b in scene.get("beats", []):
        b.setdefault("anim_ms", 700)
        b.setdefault("hold_ms", 900)
        b.setdefault("in", [])
    _dedup_canvas_labels(scene)
    _autostack_canvas_labels(scene)
    return scene


def _dedup_canvas_labels(scene: dict) -> None:
    """Drop canvas-space labels whose text already appeared (keep the first). The
    model sometimes emits the equation as both a title and the first derivation
    line, which would print it twice in the stacked column."""
    seen: set[str] = set()
    removed = 0
    for b in scene.get("beats", []):
        keep = []
        for e in b.get("in", []):
            if e.get("t") == "label" and e.get("space") == "canvas":
                txt = (e.get("text") or "").strip()
                if txt in seen:
                    removed += 1
                    continue
                seen.add(txt)
            keep.append(e)
        b["in"] = keep
    if removed:
        print(f"[normalize] removed {removed} duplicate canvas label(s)")


def _autostack_canvas_labels(scene: dict) -> None:
    """Repair the most common LLM slip: canvas-space label lines with no `at`.
    A symbolic/derivation scene is a column of equation lines; if the model gave
    them `space:"canvas"` but forgot positions, stack them top-to-bottom in reveal
    order so the scene still renders instead of collapsing to one point."""
    pending = [e for b in scene.get("beats", []) for e in b.get("in", [])
               if e.get("t") == "label" and e.get("space") == "canvas" and "at" not in e]
    if not pending:
        return
    n = len(pending)
    top, bottom = 0.16, 0.9
    for i, e in enumerate(pending):
        fy = top + (bottom - top) * (i / max(1, n - 1)) if n > 1 else 0.5
        e["at"] = [0.5, round(fy, 3)]
        e.setdefault("anchor", "center")
        e.pop("label", None)          # stray caption key the renderer ignores anyway
    print(f"[normalize] auto-stacked {n} unpositioned canvas label(s)")


def author(concept_id: str, *, run: bool, render: bool, shape: str | None = None) -> int:
    concept = _load_concept(concept_id)
    system, user = _build_prompt(concept, shape=shape)

    if not run:
        print("=== DRY RUN (no Gemini call, nothing billed) ===\n")
        print("--- SYSTEM ---\n" + system)
        print("\n--- USER ---\n" + user)
        print(f"\n--- response_schema: scene with element.t enum {PRIMS} ---")
        print("Pass --run to author for real.")
        return 0

    from llm_vertex import generate_json

    schema = _scene_response_schema()
    print(f"[authoring] {concept_id} via Gemini (temperature=0, schema-constrained)...")
    # Offline authoring is NOT latency-sensitive, so give the scene a generous
    # output budget: a multi-case concept (e.g. the discriminant's three natures)
    # emits enough JSON that a 4096-token cap truncated it mid-element, and a
    # truncated response is unparseable JSON — the whole scene lost. 8192 clears
    # the largest scenes measured; `timeout_s` overrides the 20 s generation floor
    # for the same reason (a bigger scene simply takes longer to write out).
    res = generate_json(user, response_schema=schema, system=system,
                        temperature=0.0, max_output_tokens=8192, timeout_s=90.0)
    if not res.ok or not isinstance(res.data, dict):
        print(f"[fail] Gemini returned no parseable JSON in {res.latency_ms} ms")
        print(res.text[:800])
        return 1
    scene = _normalize(res.data, concept_id)
    errs = validate_scene(scene)
    if errs:
        print(f"[invalid] {len(errs)} problem(s) in the authored scene:")
        for e in errs:
            print("  -", e)
        print("\n(raw scene follows for debugging)\n",
              json.dumps(scene, ensure_ascii=False, indent=2)[:1500])
        return 1

    out = SPECS / f"{concept_id}.scene.json"
    out.write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] {res.latency_ms} ms, {len(scene['beats'])} beats -> {out}")

    if render:
        from figures.scene_render import render_gif
        gif = SPECS / f"{concept_id}.preview.gif"
        tl = render_gif(scene, "light", 2.0, str(gif), 25)
        print(f"[render] {gif}")
        for t in tl:
            print(f"   [{t['start_ms']:>5} ms] {t['narration']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("concept_id", nargs="?")
    ap.add_argument("--run", action="store_true", help="actually call Gemini (billed)")
    ap.add_argument("--render", action="store_true", help="also render a preview GIF")
    ap.add_argument("--shape", choices=["graph", "derivation"], default=None,
                    help="force the scene shape (default: model picks by concept)")
    ap.add_argument("--self-check", metavar="FILE",
                    help="validate an existing scene JSON offline and exit")
    args = ap.parse_args()

    if args.self_check:
        scene = json.loads(Path(args.self_check).read_text(encoding="utf-8"))
        errs = validate_scene(scene)
        if errs:
            print(f"INVALID ({len(errs)}):")
            for e in errs:
                print("  -", e)
            return 1
        print(f"OK — {len(scene.get('beats', []))} beats, "
              f"{len(scene.get('base', []))} base elements, valid.")
        return 0

    if not args.concept_id:
        ap.error("concept_id is required (or use --self-check FILE)")
    return author(args.concept_id, run=args.run, render=args.render, shape=args.shape)


if __name__ == "__main__":
    raise SystemExit(main())
