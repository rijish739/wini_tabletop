# RAG Store — Visuals Research

> Research pass on how the store's images link to concepts, why the `figure_crops/`
> images render badly on the Pi panel, and how to replace them with clean, uniform,
> text-aware generated visuals. Measured on the store as of 2026-07-26.
> This is a **research/plan** doc, not a lockstep contract — nothing here is built yet.

---

## 0. TL;DR

1. **Linking is two disjoint mechanisms, and only formulas are well covered.**
   Formula crops link to concepts through `formula_links.json` (611/677 formula
   images → 96/108 concepts). Figure/table crops are supposed to link through the
   graph's `illustrated_by` edges, but those edges barely exist: **24 of 244
   fig/table crops are on a concept edge, covering 5/108 concepts.** The other
   ~220 fig/table crops are *orphans* for explicit linking — they only ever reach
   the screen through the T9 tier-3 chapter-scoped similarity fallback.
2. **The crops are non-uniform bitmaps ripped out of the PDF** (aspect ratios from
   0.35 to 21.6, heights from 38 to 984 px). Letterboxed into the 500×380 Pi card
   they look tiny, stretched, or slivered — exactly the complaint. This is inherent
   to the cropping approach, not a tuning bug.
3. **The fix is to stop cropping and start *generating*** — the same move the
   alphabet game already made: a declarative figure spec rendered deterministically
   to a uniform canvas. For maths the spec should be **LLM-authored per concept**
   (Gemini already runs perception/generation) and **rendered by a small
   deterministic drawer** to a fixed card size. This is low-RAM, low-latency, and
   theme-aware, unlike shipping HD raster.

---

## 1. How images link to concepts today

### 1.1 What's on disk

`rag_store/figure_crops/` — 17 chapter dirs (`jemh101`…`jemh1a2`), **921 PNGs**:

| kind | count | what it is |
|---|---:|---|
| `formula_*` | 677 | LaTeX-rendered formula/equation crops |
| `fig_*` | 181 | figure regions cropped out of the chapter PDF |
| `table_*` | 63 | table regions cropped out of the chapter PDF |

Plus `crops_manifest.json` (888 entries — bbox + page + source per crop) and a
`contact_sheet.html`.

### 1.2 The two linking mechanisms

There is **no `figure`/`image`/`visual` field on any concept** in `concepts.json`
(checked all 108). Images reach a concept by two separate paths:

**A. Formula crops → `rag_store/formula_links.json`** (`link_formulas.py`, v1).
Scores every `formula::` node against every concept by page-locality (0.6) + name
overlap (0.4), keeps links over threshold 0.35, top-3 concepts each. Result:

- 2135 links, **611 distinct formula images → 96/108 concepts**.
- Per-chapter coverage went from ~0→7 concepts-with-a-formula-visual after the v5.2
  chapter-wide rebuild (see the `coverage` block in the file). This matches the
  `formula-links-2026-07-20` memory (7/108 → 95/108 concept coverage).

**B. Figure/table crops → graph `illustrated_by` edges** (`graph.json`).
This is the intended path for `fig_`/`table_` crops, and it is almost empty:

| relation | edges |
|---|---:|
| `illustrated_by` (concept ↔ figure) | **46** |
| concepts with ≥1 figure edge | **5 / 108** |
| fig/table nodes on a concept edge | **22 / 245** |

So the graph carries figure→concept links for essentially nobody. The runtime
comment in `tutor_loop._build_display` says this outright: *"the graph's
illustrated_by edges cover almost no concepts, which left ordinary EXPLAIN turns
text-only."*

### 1.3 Full audit — is every crop linked?

Reachability of each on-disk PNG through an **explicit concept link** (formula_links
OR illustrated_by):

| kind | on disk | explicitly linked | orphaned |
|---|---:|---:|---:|
| formula | 677 | 611 (90%) | 66 |
| fig | 181 | 18 (10%) | 163 |
| table | 63 | 6 (10%) | 57 |
| **total** | **921** | **635 (69%)** | **286 (31%)** |

**But orphaned ≠ never shown.** All **244 fig/table crops are registered as
`figure_caption` chunk rows carrying `image_path`**, and the T9 tier-3 selector
(`_build_display`, tier 3) builds its candidate pool from those chunk rows scoped by
chapter and ranks them by live similarity to the utterance. So an unlinked figure
can still appear — it just isn't *addressable by concept*, only *discoverable by
similarity*. Consequences:

- The formula path is concept-addressable and healthy.
- The figure/table path relies entirely on runtime similarity; there is no curated
  "this concept's canonical diagram." Selection quality is whatever MiniLM
  similarity + the chapter bar + the `T9_CONCEPT_BONUS` tie-break produce that turn
  (see `t9-figure-selection-rules` memory).

### 1.4 Manifest / integrity gaps found

- **33 formula PNGs on disk are not in `crops_manifest.json`** (e.g.
  `formula_jemh101_prime_factorization_of_a_2.png`,
  `formula_jemh107_converse_of_pythagoras_theorem.png`). They exist as files but the
  manifest doesn't describe them — provenance hole.
- **66 formula PNGs are not in `formula_links.json`** (below the 0.35 threshold or
  built after the last link run). They can never be pulled by concept; they can only
  surface via chunk-row similarity if they were also chunked.
- 0 manifest entries point at a missing file (no dangling references — good).

**Recommended hygiene regardless of the bigger redesign:** re-run
`python -m concept_resolver...`/`link_formulas.py` after any crop rebuild, and add a
`verify_store.py` check that (a) every on-disk crop is in the manifest and (b) every
manifest crop is either concept-linked or chunk-registered, so orphans surface in the
scorecard instead of silently.

---

## 2. Why the crops look bad on the Pi — and a generation plan

### 2.1 The root cause is the cropping method, not the display code

`crop_figures.py` finds figure regions on each PDF page with PyMuPDF
(`cluster_drawings` + `get_images` + caption anchors), takes the **bbox as-is**, and
renders it at a fixed zoom (`render_crop`). Whatever aspect ratio the textbook figure
happened to have on the page is what you get. Measured over the 921 crops:

| kind | width min/med/max | height min/med/max | aspect-ratio min/med/max |
|---|---|---|---|
| fig | 103 / 822 / 843 | 38 / 233 / 974 | **0.35 / 2.32 / 21.63** |
| table | 248 / 742 / 849 | 89 / 373 / 984 | 0.84 / 1.83 / 7.74 |
| formula | 43 / 162 / 769 | 37 / 42 / 136 | 0.59 / 3.38 / 17.29 |

The display path (`display_sinks.render_crop` / `_emit_figure`) then **letterboxes**
each into the card. On the Pi the card is `FIG_MAX_W, FIG_MAX_H = 500, 380` inside a
600×1024 portrait panel. So:

- a 21:1 figure sliver becomes a 500×24 line floating in black,
- a 103-px-wide fig becomes a stamp in the middle of the card,
- tables (dense text rasters) become unreadable at 500-wide,
- nothing shares a common size, baseline, stroke weight, or background, so every
  figure "jumps" relative to the last.

The device also changes: the target is moving to **ESP32-P4 + e-ink/LCD**
(`hardware-target-esp32p4` memory), where raster HD crops are even worse (RAM,
palette, refresh). This makes the redesign not optional.

### 2.2 The model to copy — the alphabet game

`pi_game/gen_assets.py` + `pi_game/content.py` already solve exactly this problem for
a different product:

- Each object is a **declarative art recipe** — a list of primitives
  (`ellipse`, `lens`, `rect`, `poly`, `line`, `arc`, `pie`) with fills/outlines,
  authored on a **fixed 420×420 canvas**.
- `draw_art()` renders the recipe with **Pillow** to a transparent RGBA PNG of a
  **uniform size**; letters are measured-and-scaled to an exact glyph height.
- Output is tiny, uniform, theme-consistent (INK/CREAM/ROSE palette), and
  regenerable offline with `python -m pi_game.gen_assets`.

The result on the panel is calm and consistent because *every* asset is drawn to the
same spec, not scavenged.

### 2.3 Plan — "Generated Figures" for maths

The maths difference: 108 concepts is too many to hand-author 26-at-a-time, and the
figures are structural (triangles with labels, number lines, factor trees, coordinate
planes, circles with tangents) rather than cute objects. So keep the alphabet game's
**deterministic-renderer-from-a-declarative-spec** architecture, but **let the LLM
author the spec** and give the renderer a maths-diagram vocabulary.

**Stage A — figure-spec schema (the "recipe" for maths).**
A small, closed, JSON schema of maths primitives + a few composite templates:
`point`, `segment`, `polygon(labeled vertices)`, `right_angle_mark`, `arc`,
`circle`, `tangent`, `number_line(ticks, marks)`, `axes(range, gridlines)`,
`function_plot(expr, domain)`, `bar`/`grid`, `factor_tree(node,children)`,
`brace`, `label(text, anchor)`. Every primitive is authored on a fixed **card-sized
canvas** (e.g. 500×380 to match the Pi card, DPR-scaled) with a fixed palette and
stroke weight. This is the maths analogue of `content.py`'s `art` list.

**Stage B — author one canonical spec per concept, offline, with Gemini.**
Reuse the existing Vertex Gemini client (`llm_vertex.py`) in a build script
(`build_concept_figures.py`, sibling of `link_formulas.py`). For each concept feed
`{name, summary, representations, a caption/figure crop as grounding}` and ask for a
**figure_spec JSON constrained by `response_schema`** (same controlled-generation
belt Part 11 already relies on — the model can only emit in-vocabulary primitives).
Validate against the schema, render with the deterministic drawer, and store:

```
rag_store/figure_specs/<concept_id>.json      # the spec (source of truth, versionable, tiny)
rag_store/figure_gen/<concept_id>.png         # a pre-rendered card (optional cache)
concept_figures.json                          # concept_id -> spec path (the NEW explicit link)
```

`concept_figures.json` is the **concept-addressable figure index the store is
missing today** — it replaces the empty `illustrated_by` edges with one curated,
uniform figure per concept.

**Stage C — renderer.** A ~200-line `figure_render.py`:
- authoring/build side renders spec→PNG with **Pillow** (already the alphabet
  dependency) at card size, uniform stroke/palette, theme-aware (light/dark),
- or emits **SVG** for the web/LVGL-vector path (see §3.4).
Deterministic, no model at render time, so it's free to re-render at any resolution
for any device (Pi card, ESP32 panel, parent-dashboard web).

**Stage D — wire into T9.** `_build_display` gains a tier-0/1: if the primary
concept has a `concept_figures.json` entry, show the generated card (concept-
addressable, always on-topic, always uniform). Fall back to the current
similarity-based crop tiers only when there is no generated figure yet. This keeps
the "one primary visual per turn" contract and the answer-length-stays-dynamic rule
(the figure is chosen, not the text trimmed).

**Migration & safety.**
- The old crops stay as fallback and as **grounding input** for Stage B, so nothing
  regresses while coverage fills in.
- Build is idempotent and cached like the alphabet's `--force` flag; regenerate a
  single concept without touching the rest.
- Gate the rollout on a small human spot-check per chapter (the alphabet game's art
  needed several "reads as the wrong thing" corrections — e.g. the leaf/kite and the
  double-arc-face bugs in `content.py` comments; maths diagrams will need the same
  eyeballing before they ship).

---

## 3. Text-aware lightweight visual generation — options researched

Goal restated: render a **small visual for the sentence Wini is about to say**, with
**low RAM and low latency**, *not* HD art. Two families exist; the store should use a
hybrid.

### 3.1 Family 1 — LLM writes code/spec, a deterministic renderer draws it

This is the industry-standard "diagram-as-code" pattern and the natural fit here
because a Gemini call is already in the loop.

- **LLM → structured JSON spec → your own renderer** (the §2.3 plan). Strongest fit:
  the `response_schema`/controlled-generation belt makes the spec *closed and safe*
  (no arbitrary code), rendering is deterministic and offline, output size/theme is
  whatever you draw. This is what "generate like the alphabet game" means, upgraded
  with an LLM author. Structured-output tooling is now mature across Gemini/OpenAI/
  Claude (JSON-Schema-constrained decoding).
- **LLM → matplotlib code → sandbox render.** Gemini's **code-execution** tool ships
  a sandbox with `matplotlib`, `numpy`, `sympy` and returns rendered images; good for
  function plots/bar charts. But: matplotlib is a heavy import (slow first render,
  ~tens of MB RSS), the sandbox adds seconds of latency, and it's overkill for a
  labeled triangle. Use it *only* for genuine function/graph plots, not for geometry.
- **LaTeX/TikZ → SVG/PNG** (e.g. **texoid**, **pymathematical**, `mathsvg`). Best-
  in-class for equations and classical geometry, but a full TeX toolchain is a large
  dependency and slow per render — wrong for an on-device or per-turn path. Keep this
  strictly at *build time* if used at all (it's essentially what produced the
  existing `formula_*` crops).

### 3.2 Family 2 — parametric/programmatic drawing libraries (no LLM at render)

For the deterministic renderer itself:

- **Pillow (`ImageDraw`)** — already in the repo via the alphabet game, tiny, fast,
  raster out. Best default for the Pi/ESP32 raster card.
- **`drawsvg`** — pure-Python SVG generator, lightweight, good if the display path
  can consume SVG (web dashboard, LVGL vector).
- **`mathsvg`** — Python lib specifically for drawing mathematical objects (axes,
  arcs, ticks) to SVG; a ready-made maths vocabulary if you don't want to hand-roll
  primitives.
- **Interactive maths (web only):** `function-plot`, **JSXGraph**, Desmos/GeoGebra
  embeds — great for the parent dashboard, irrelevant to the LVGL C panel.

### 3.3 Latency / RAM comparison (qualitative)

| approach | render latency | RAM | on-device? | best for |
|---|---|---|---|---|
| JSON spec → Pillow | ms | ~5–15 MB | yes | geometry, number lines, factor trees |
| JSON spec → drawsvg/SVG | ms | tiny | yes (if SVG sink) | scalable/theme-aware, web |
| LLM → matplotlib sandbox | seconds | tens of MB | no (cloud) | true function/data plots |
| LaTeX/TikZ toolchain | seconds | large | no | build-time equations only |
| ship existing HD crop | n/a (I/O) | image-size | yes | *what we're replacing* |

### 3.4 Recommendation

**Do §2.3: LLM-authored, schema-constrained figure specs rendered deterministically
to a uniform card.** Concretely:

1. **Spec is the artifact, not the pixels.** Store the tiny JSON spec per concept;
   render on demand. This is what makes it low-RAM/low-latency and device-portable
   (Pi card now, ESP32 panel next), and re-themeable (light/dark) for free.
2. **Renderer = Pillow** for the raster panel path (reuse the alphabet dependency),
   with an **SVG (`drawsvg`) emitter** as a second backend for web/vector sinks.
3. **Author once, offline, with the existing Vertex Gemini client**, constrained by
   `response_schema` so the spec is closed and safe — no code execution at runtime,
   no per-turn model cost for the picture.
4. **Reserve matplotlib-via-Gemini-code-execution for real function plots only**,
   called at build time and cached, never in the hot turn path.
5. **Keep the current crops as fallback + grounding** during migration; fill
   `concept_figures.json` chapter by chapter with a human spot-check gate.

This gives the store the concept-addressable, uniform, cheap-to-render figures it
lacks today, on the exact architecture the alphabet game already proved on the panel.

---

## Sources

- [texoid — LaTeX→SVG/PNG server](https://github.com/DMOJ/texoid)
- [pymathematical — equations→SVG/PNG/MathML](https://github.com/danmou/pymathematical)
- [mathsvg — draw mathematical objects to SVG (PyPI)](https://pypi.org/project/mathsvg)
- [drawSvg — programmatic SVG generation (PyPI)](https://pypi.org/project/drawsvg/1.0.0.2/)
- [Gemini API — Code execution (matplotlib sandbox)](https://ai.google.dev/gemini-api/docs/code-execution)
- [Gemini API — Tools / function calling](https://ai.google.dev/gemini-api/docs/tools)
- [Structured Output Generation in LLMs — JSON Schema & grammar-based decoding](https://medium.com/@emrekaratas-ai/structured-output-generation-in-llms-json-schema-and-grammar-based-decoding-6a5c58b698a6)
- [Structured outputs guide — JSON Schema across OpenAI/Claude/Gemini](https://logic.inc/resources/structured-outputs-guide)
