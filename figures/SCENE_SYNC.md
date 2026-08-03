# Dynamic, narration-synced scenes

The static figure spec (`figure_schema.py`) answers *"what does this look like."* For a
worked solution — a quadratic and its roots — that isn't enough: the child has to see
the process *unfold* in step with what Wini is saying. A **scene spec** adds a timeline
so the visual and the speech advance together.

This is the prototype behind `scene_render.py` + the GIF demo
(`rag_store/figure_specs/jemh104__roots_of_quadratic_equation.scene.json`).

## The core idea: a beat = a sentence

A scene is a static `base` (drawn once) plus an ordered list of **beats**. Each beat
carries:

- `narration` — the sentence Wini speaks for this step,
- `in` — the elements that appear/animate during it (`anim`: `fade` | `draw` | `move`),
- `anim_ms` / `hold_ms` — how long the animation runs, then holds.

```json
{ "narration": "The roots are where the curve crosses the x-axis.",
  "anim_ms": 600, "hold_ms": 1000,
  "in": [ {"t":"point","at":[-1,0],"anim":"fade"},
          {"t":"point","at":[ 3,0],"anim":"fade"} ] }
```

Because the narration text and the animation live in the **same beat**, they can't drift
apart — advancing the speech advances the picture. That's the whole sync trick, and it
needs no word-level timing.

## How it syncs to live speech (fits Part 13 streaming)

The brain already segments and streams the answer sentence-by-sentence for TTS
(Part 13, TTFA ~3–4 s). Reuse that boundary:

```
brain: answer = [beat0.narration, beat1.narration, ...]   +   scene spec (beats)
        stream sentence N to Cloud TTS  ──▶  client speaks it
                                             client tells UI: "run beat N"
        (UI plays beat N's fade/draw/move, then holds until sentence N+1 arrives)
```

- **Primary mechanism — beat = streamed sentence.** When the client hands beat N's
  sentence to TTS, it fires beat N's animation. The hold lasts until the next sentence
  starts, so a longer sentence simply holds the frame longer — automatically in sync,
  no clock. This is robust to TTS latency jitter and is the recommended default.
- **Optional upgrade — word timing.** Cloud TTS can return word/`<mark>` timepoints;
  a beat can pin a sub-step to a specific word ("crosses **here**") for tighter cueing.
  More precise, more fragile — add it only where a beat needs mid-sentence emphasis.

## Rendering paths (same spec, three targets)

The spec is the artifact; how it's drawn depends on the surface:

| surface | how | notes |
|---|---|---|
| **this chat / proof** | `render_gif` (Pillow, `save_all`) | what produced the demo GIF |
| **RPi5 client (now)** | client renders each beat's frames with Pillow → swaps the `figure` PNG the LVGL card already loads | works with today's `display_sinks` figure path; a beat is a short frame run, not one static PNG |
| **LVGL / ESP32 (next)** | native scene player: LVGL objects + `lv_anim` for fade/move, or a small sprite/MJPEG run | only the ~2 KB spec crosses the wire; the device animates locally — no video streaming |
| **web parent dashboard** | emit SVG + CSS/SMIL or a tiny JS driver | trivial from the same beats |

Bandwidth stays tiny because **the spec travels, not the pixels** — the demo GIF is
1.3 MB, but the scene spec that generates it is ~2 KB.

## How the brain authors a scene

Same offline/inline Gemini step as the static figure plan (`RAG_STORE_VISUALS_RESEARCH.md`
Stage B), with the timeline added to the `response_schema`: given the concept + the
worked example it's about to explain, Gemini emits `{answer_sentences[], scene{beats[]}}`
where `answer_sentences[i]` is `beats[i].narration`. The `curve` primitive takes
quadratic coefficients (`quad:[a,b,c]`) — closed and safe, sampled by the renderer, **no
expression `eval`**. Validate against the schema, and the visual is guaranteed to be a
legal, drawable scene.

## Animation vocabulary (v1, added over the static renderer)

- `curve` — a quadratic `quad:[a,b,c]` sampled over `domain` (draw-on with `anim:"draw"`),
- `tracer` — a dot that rides a `quad` from `x_from`→`x_to` (`anim:"move"`),
- `anim:"fade"` — opacity ramp for any element (points, labels, dashed guides).

Next primitives worth adding for solutions: `move` a label along a path (carry a term
across an equals sign), `morph` between two forms (standard ↔ factored), and a
`number_line` mark that slides — all the same beat mechanism.

## Status

- **Built + verified:** scene schema, `scene_render.py`, the quadratic-roots scene, GIF.
- **Not built:** the client-side beat player (RPi5 PNG-swap + the LVGL/ESP32 native
  path), the Gemini scene-authoring step, and the answer↔beat pairing in `tutor_loop`.
