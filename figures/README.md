# figures/ — store-generated teaching visuals (prototype)

Deterministic renderer for **figure specs**: a small closed JSON description of a
maths diagram that the store keeps *instead of* a PDF crop. The spec is authored on a
device-agnostic **view** (maths coordinates, y-up) and rendered on demand to a uniform
card at any resolution and theme. This is the "store specs, render with Pillow (+SVG)"
prototype from `RAG_STORE_VISUALS_RESEARCH.md`, modelled on the alphabet game's
`gen_assets.py`.

## Files

| file | role |
|---|---|
| `figure_schema.py` | the closed primitive vocabulary + JSON-Schema (doubles as the Gemini `response_schema`) + `validate()` |
| `figure_render.py` | two backends over one geometry: `render_png` (Pillow raster) and `render_svg` (hand-rolled SVG, no dependency) |
| `../rag_store/figure_specs/*.json` | the specs (source of truth, versionable, ~1.7 KB each) |

## Prototype concept

`rag_store/figure_specs/jemh107__distance_formula.json` — a Cartesian plane with two
points, a right triangle, dashed legs, right-angle mark, and the formula, rendered
theme-aware in light and dark from one spec.

## Render

```bash
py -3 -m figures.figure_render rag_store/figure_specs/jemh107__distance_formula.json \
    --png out.png --svg out.svg --theme light --scale 2
```

`--theme light|dark`, `--scale` supersamples the raster for crisp edges.

## Measured (this concept, dev box)

| | value |
|---|---|
| PNG render (2× AA, 500×380) | ~19 ms |
| SVG render | ~0.08 ms |
| spec size | 1.7 KB |
| SVG size | 3.9 KB |
| PNG size | 22 KB |
| old jemh107 PDF crops | avg 36 KB, up to 73 KB, non-uniform aspect (0.35–21.6) |

The spec is ~20× smaller than the crop it replaces, resolution-independent, and
theme-aware — the point of the redesign.

## Primitive vocabulary (v1)

`axes` (optional integer grid + arrows) · `segment` (optional dashed) · `polygon` ·
`circle` · `arc` · `point` (optional attached label) · `right_angle` · `label`.
Colours are theme tokens (`ink`, `paper`, `accent`, `accent_soft`, `accent2`,
`muted`, `good`, `warn`) or literal `#rrggbb`.

## Not done yet (next steps from the plan)

- Stage B authoring: `build_concept_figures.py` calling Vertex Gemini with
  `RESPONSE_SCHEMA` to author specs per concept, grounded on the existing crop.
- `concept_figures.json` index (concept_id → spec) — the concept-addressable link the
  store lacks today.
- T9 wiring: a new tier-0 in `tutor_loop._build_display` preferring the generated
  figure, old crops as fallback.
- An LVGL/ESP32 render path (rasterize the spec on the client, or ship the PNG).
