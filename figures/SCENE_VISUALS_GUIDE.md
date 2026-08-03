# Wini Dynamic Visuals — End-to-End Build Guide

*How the store-generated, narration-synced teaching visuals are built, rendered,
authored by Gemini, played on the device, and wired into a live mic turn — one
document, whole-chapter oriented.*

> Companion docs: `figures/SCENE_SYNC.md` (the sync idea in the abstract),
> `figures/README.md` (module map), `RAG_STORE_VISUALS_RESEARCH.md` (why we build
> visuals instead of shipping the PDF `figure_crops`). This guide is the operational
> how-to that ties them together and adds the **whole-chapter** workflow.

---

## 0. The one-paragraph picture

A concept's teaching visual is **not a pixel image** in the store — it is a tiny
(~2 KB) declarative **scene spec** (JSON). Gemini authors that spec once, offline,
under a `response_schema` that constrains it to a closed drawing vocabulary. At
teach time the device renders the spec deterministically with Pillow, one frame per
spoken sentence, so the picture grows in lock-step with the voice. Same spec renders
crisp on the Pi card today and the ESP32 panel tomorrow; only the spec crosses the
wire, never HD raster.

```
concepts.json ──► build_concept_scene.py (Gemini, offline, billed once)
                       │  response_schema + validate belt + auto-repair
                       ▼
   rag_store/figure_specs/<concept_id>.scene.json      ◄── the store artifact
                       │
        ┌──────────────┴───────────────┐
        ▼                              ▼
 scene_render.render_beat_frame   scene_render.render_gif
   (device, one PNG per beat)       (dev preview / review)
        │
        ▼
 wini_client/scene_player.py  ──►  mode channel :8140  ──►  wini_ui (LVGL)
        │  synth narration (Cloud TTS), play blocking (reSpeaker)
        ▼
   BEAT-LEVEL SYNC: frame N shown while sentence N is spoken
```

---

## 1. The render schema — how to build it

Two files define the contract. **Everything the renderer and Gemini agree on lives
here; nothing else is legal.**

### 1.1 `figures/figure_schema.py` — the closed vocabulary

- **`COLOR_TOKENS`** — the only legal colour names: `ink, paper, accent,
  accent_soft, accent2, muted, good, warn`. A spec may also use a literal `#rrggbb`.
  Colours are *tokens*, resolved per light/dark theme at render — never bake a hex
  the theme can't invert.
- **`PRIMITIVES`** — the closed set of static `t` values: `axes, segment, polygon,
  circle, arc, point, right_angle, label`.
- **`ANCHORS`** — text anchor positions: `center, n, s, e, w, ne, nw, se, sw`.
- **`RESPONSE_SCHEMA`** — a JSON-Schema that **doubles as the Gemini
  `response_schema`**. It is strict on the closed enums (`t`, colour tokens,
  anchors) and permissive on the element payload (each primitive uses only the
  fields it needs). The strictness on enums is the belt: Vertex controlled
  generation masks decoding to schema-valid tokens, so Gemini **cannot invent** an
  out-of-vocabulary primitive.
- **`validate(spec, extra_primitives=())`** — dependency-free structural check.
  Returns a list of human-readable problems (`[]` == valid). Catches the mistakes an
  LLM or a hand-edit actually makes: missing top-level keys, unknown primitive, bad
  colour token, bad anchor. `extra_primitives` lets the *scene* validator admit
  `curve`/`tracer` without polluting the static figure vocabulary.

### 1.2 Coordinates — view vs canvas (the mental model)

Two coordinate systems, and getting them right is 80 % of a clean layout:

| Space | Units | Y direction | Use for |
|---|---|---|---|
| **view** | maths units in the spec's `view:{x0,y0,x1,y1}` box | **up** (Cartesian) | anything on the plot: axes, curves, points, triangles |
| **canvas** | fraction 0..1 of the card | down | header/footer text, equation lines — anything that must never collide with the plot |

The renderer (`figure_render._Transform`) maps view→canvas with a **y-flip**, so
authoring a Cartesian plane reads naturally. Crucially, `_Transform` supports
**asymmetric padding** — `pad_top / pad_bottom / pad_left / pad_right` — which
reserves bands the plot never draws into. That is how the equation lives in a
header band instead of overlapping the y-axis (the bug we fixed on the Pi mock).

A `label` element with `space:"canvas"` is positioned by `at:[fx,fy]` fractions via
`_Transform.px_frac`; without it, `at:[x,y]` is a view point.

### 1.3 The animation extension — `figures/scene_render.py`

A **scene** is a static figure spec plus a *timeline*. Two extra primitives over
`figure_schema`, admitted via `extra_primitives=("curve","tracer")`:

- **`curve`** — a quadratic `quad:[a,b,c]` (y=ax²+bx+c) **sampled** over
  `domain:[x0,x1]`. Closed and safe: coefficients only, **no expression `eval`**.
  `anim:"draw"` reveals it progressively.
- **`tracer`** — a dot that rides `quad` from `x_from` to `x_to`; `anim:"move"`.

`_REQUIRED` maps each primitive to the fields it cannot draw without. A malformed
element (an LLM omits `at`, say) **skips with a printed note, never crashes the
turn** — the same discipline as `tutor_loop`'s T9 path. This is load-bearing: a
single bad element must never take down a live teaching turn.

### 1.4 The scene spec shape

```jsonc
{
  "version": 1,
  "concept_id": "jemh104__quadratic_formula",
  "title": "The Quadratic Formula",
  "canvas": { "w": 500, "h": 380,
              "pad_top": 60, "pad_bottom": 20, "pad_left": 20, "pad_right": 20,
              "equal_aspect": false },
  "view":   { "x0": -4, "y0": -6, "x1": 4, "y1": 4 },
  "base":   [ /* elements drawn once, before any beat */ ],
  "beats": [
    { "narration": "We start with two x squared plus five x minus three equals zero.",
      "anim_ms": 700, "hold_ms": 900,
      "in": [ { "t": "label", "space": "canvas", "at": [0.5, 0.18],
                "anchor": "center", "text": "2x² + 5x − 3 = 0", "size": 20 } ] },
    { "narration": "…", "in": [ /* only what THIS sentence introduces */ ] }
  ]
}
```

**Two scene shapes** — pick by the concept:

- **GRAPH** (roots, coordinate geometry): draw `axes`/`curve`/`point` in view
  coords; put value labels **outside** any filled/curved region.
- **DERIVATION** (a formula, a symbolic solve): **no axes**. Build a column of
  equation lines as `space:"canvas"` labels, one algebra step per beat, stacked with
  increasing `fy` (0.18, 0.32, 0.46, 0.60, 0.74). Earlier lines stay on screen so
  the derivation accumulates; highlight the final answer with `color:"accent"`.

### 1.5 Two rendering entry points

Both in `scene_render.py`, both driven by the same spec:

- **`render_beat_frame(scene, upto_beat, theme, scale, out_path)`** — the **device
  path**. Renders the *accumulated* state after beat N (base + every beat's `in`
  through N) as one still PNG. The picture grows one step per spoken sentence.
  Robust: each figure swap is just a PNG write + LVGL card reload.
- **`render_gif(scene, theme, scale, out_path, fps)`** — the **dev/review path**.
  Full per-frame fade/draw/move animation to an animated GIF, plus it returns the
  narration timeline. Use it to eyeball a scene before shipping; it is **not** the
  device path (GIF `optimize` encode is ~13 s on the Pi — the device blits live
  frames instead).

`bench(scene)` measures on-device cost (`--bench`).

**Measured on winipi5** (PIL 11.1.0, aarch64): scale 1 = 5.5–8.6 ms/frame @500×380,
scale 2 = 32–36 ms/frame @1000×760, **RSS 36 MB**. Faster than the Windows dev box.
RAM negligible next to the client's existing numpy+cv2 (~100–150 MB).

### 1.6 Adding a new primitive (when you must)

1. Add the `t` name to `PRIMITIVES` (static) **or** pass it via `extra_primitives`
   (animation-only, like `curve`/`tracer`).
2. Add its required fields to `_REQUIRED` in `scene_render.py`.
3. Add a `elif t == "...":` branch in `_element_layer` (draw onto the RGBA layer at
   full opacity — the caller applies fade).
4. Add its fields to the Gemini `response_schema` element in
   `build_concept_scene._scene_response_schema` **and** to the `PRIMS`/prose in the
   `SYSTEM` prompt.
5. Keep it a **closed template** — no free-form paths, no code, no `eval`.

---

## 2. Syncing the visual with the audio

### 2.1 The sync principle — beat = sentence

The whole trick: **the visual and the speech advance on the same boundary.** One
beat carries exactly one narration sentence *and* the elements that sentence
introduces. Show beat N's frame, speak beat N's sentence to completion, advance.
No word-level timing, no audio-length estimation, no drift — the coupling is
structural.

### 2.2 The device player — `wini_client/scene_player.py`

Per beat, `play_scene` does:

```python
render_beat_frame(scene, i, theme, scale=2.0, out_path=png)   # accumulate frame
chan.send({"cmd": "figure", "path": str(png)})                 # show it on LVGL
chan.send({"cmd": "explain", "title": ..., "body": narration}) # caption card
speaker.say(narration)      # Cloud TTS synth + play_pcm — BLOCKS until spoken
time.sleep(0.25)            # a small breath between steps
```

The **blocking** `speaker.say` is what creates the sync: the loop cannot advance to
beat N+1 until beat N's audio has finished playing. `_Speaker` wraps
`voice.cloud_tts.CloudTts.synth` → `wini_client.client.play_pcm` (the reSpeaker-aware
24 k→16 k blocking playback), and falls back to **timed pacing** (~55 ms/word, 1.4 s
floor) if TTS/audio is unavailable — so a visual-only demo still paces correctly.

`prime_output()` opens the persistent output stream up front so the first beat
doesn't clip.

### 2.3 Frame slots

Frames are written to `/tmp/wini_scene_{0..5}.png` cycled (`FIG_SLOTS = 6`) so the
LVGL side always reloads a fresh path and never caches a stale image.

### 2.4 Run the standalone demo (no mic, no brain)

```bash
.venv/bin/python -m wini_client.scene_player \
    rag_store/figure_specs/jemh104__quadratic_formula.scene.json --launch-ui
```

Flags: `--port 8140`, `--theme light|dark`, `--no-audio` (visual only, timed
pacing), `--launch-ui` (also start `wini_ui/build/wini_ui`), `--hold N` (seconds on
the final frame), `--loop`. This is the demo the user saw + heard on the Pi.

> **Scope note:** in the standalone player, the narration **is the scene's own beat
> text** — not the brain's generated answer. Wiring it to a live turn is §4.

---

## 3. Creating more concept scenes — the whole-chapter workflow

This is the section the compaction asked to focus on. `build_concept_scene.py`
authors **one** concept per invocation; a chapter is a loop over its concepts with a
few guards so a whole chapter costs a handful of billed calls and produces a review
gallery you can eyeball in one pass.

### 3.1 The single-concept authoring path (the unit of work)

`figures/build_concept_scene.py`:

1. `_load_concept(concept_id)` reads `rag_store/concepts.json`.
2. `_build_prompt` fills `SYSTEM` (the drawing contract + GRAPH-vs-DERIVATION
   guidance + "keep every string SHORT" rule) and `USER_TMPL` (concept name,
   summary, representations, vocabulary), and appends the **reviewed gold scene**
   (`jemh104__roots_of_quadratic_equation.scene.json`) as a one-shot format anchor.
3. `_scene_response_schema()` builds the genai `types.Schema` — constrains element
   `t` and `anchor` to the vocabulary (the decoding belt). **There is deliberately
   no generic `label` string field** — the model kept abusing it as free-text
   annotation and blowing the token budget.
4. `generate_json(user, response_schema, system, temperature=0.0,
   max_output_tokens=4096)` — reuses `llm_vertex` with a **hard wall-clock timeout**,
   `thinking_budget=0`.
5. `_normalize` → `_dedup_canvas_labels` (drop a line repeated as title + first step)
   + `_autostack_canvas_labels` (repair unpositioned canvas labels by stacking
   fy 0.16→0.9 in reveal order). These are the **auto-repair belt** for the two slips
   the model actually makes.
6. `validate_scene` — flattens base + all beat elements through
   `figure_schema.validate(..., extra_primitives=("curve","tracer"))`, then checks
   beats exist, each has non-empty narration and an `in`.
7. Writes `rag_store/figure_specs/<concept_id>.scene.json`.

Flags: `--run` (billed; default is dry-run that prints the exact prompt+schema for
offline review), `--render` (also write `<id>.preview.gif`),
`--self-check FILE` (offline validate an existing scene, no network).

```bash
# review the contract WITHOUT billing:
py -3 -m figures.build_concept_scene jemh104__quadratic_formula
# author for real + preview GIF:
py -3 -m figures.build_concept_scene jemh104__quadratic_formula --run --render
# validate a hand-edit offline:
py -3 -m figures.build_concept_scene --self-check rag_store/figure_specs/jemh104__quadratic_formula.scene.json
```

### 3.2 List a chapter's concepts

Concepts carry `chapter_doc` (e.g. `jemh104`). To enumerate a chapter:

```bash
py -3 - <<'PY'
import io, json
data = json.load(io.open("rag_store/concepts.json", encoding="utf-8"))
ch = "jemh104"
ids = [c["concept_id"] for c in data if c.get("chapter_doc") == ch]
print(len(ids), "concepts in", ch)
for cid in ids: print(" ", cid)
PY
```

### 3.3 The batch driver (recommended shape)

There is no batch script yet — this is the design of record. Wrap the single-concept
`author()` in a loop with these guards (each is a lesson already paid for):

1. **Dry-run the whole chapter first** (no `--run`) to eyeball prompts, then commit
   to billing.
2. **Skip already-authored + validated** specs (idempotent re-runs; only re-author
   the failures).
3. **Author sequentially**, not in parallel — one Vertex client, built once
   (client construction is the ~4–9 s cold-start cost, not the call). Reuse
   `generate_json`'s memoized client.
4. **Auto-repair + validate each** (steps 5–6 above already do this); on invalid,
   **log and continue** — never abort the chapter on one bad concept.
5. **Render a preview GIF per concept** into `rag_store/figure_specs/*.preview.gif`
   so the whole chapter is a review gallery you scan in one pass.
6. **Write a per-run report**: concept_id, ok/invalid, latency_ms, #beats — so a
   re-run targets only the failures.

Skeleton (put in `figures/build_chapter_scenes.py`):

```python
import io, json, time
from pathlib import Path
from figures import build_concept_scene as bcs

def chapter_ids(chapter):
    data = json.load(io.open("rag_store/concepts.json", encoding="utf-8"))
    return [c["concept_id"] for c in data if c.get("chapter_doc") == chapter]

def run_chapter(chapter, run=False, render=True, force=False):
    specs = Path("rag_store/figure_specs")
    report = []
    for cid in chapter_ids(chapter):
        out = specs / f"{cid}.scene.json"
        if out.exists() and not force:
            report.append((cid, "skip", 0)); continue
        t0 = time.monotonic()
        rc = bcs.author(cid, run=run, render=render)   # writes + validates + repairs
        report.append((cid, "ok" if rc == 0 else "FAIL", round((time.monotonic()-t0)*1000)))
    for cid, status, ms in report:
        print(f"{status:5} {ms:6} ms  {cid}")
    return report
```

### 3.4 The concept→scene index the store lacks

After a chapter is authored, write `rag_store/concept_figures.json` mapping
`concept_id → scene path` (+ `authored_at`, `beats`, `shape`). This is the index the
store never had (concepts.json has no figure field) and is what the live mic path
(§4) looks up. Regenerate it from whatever `figure_specs/*.scene.json` exist so it
stays in sync:

```python
import json, glob, io
idx = {}
for p in glob.glob("rag_store/figure_specs/*.scene.json"):
    s = json.load(io.open(p, encoding="utf-8"))
    idx[s["concept_id"]] = {"scene": p, "beats": len(s.get("beats", [])),
                            "title": s.get("title", "")}
json.dump(idx, io.open("rag_store/concept_figures.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
```

### 3.5 Quality gate before you trust a chapter

For each authored scene:

- `--self-check` passes (structural).
- The preview GIF reads correctly: equation in the header band (not over axes), no
  labels inside a filled region, derivation accumulates, final answer in `accent`.
- Narration reads as natural spoken sentences (short, speakable, one idea/beat).
- Numbers are clean (the prompt asks for clean worked examples — verify the model
  didn't pick ugly roots).

Only scenes that pass go into `concept_figures.json`.

---

## 4. Wiring it into a live mic turn

Today `scene_player` is standalone: narration = the scene's own beats. In a live
turn the narration must be **the brain's generated answer**, and the scene is chosen
by the **resolved concept**. Here is the integration design.

### 4.1 What a live turn already produces

`tutor_loop` runs perception (Gemini, gemini-only since Part 11) which resolves the
turn's **primary concept** (the `fuse_primary` cross-checked concept id), and the
generator streams the answer sentence-by-sentence (Part 13 streaming — TTS chunking
already splits on sentence boundaries). Those are the two hooks:

- **concept id** → which scene to play (`concept_figures.json` lookup).
- **streamed sentences** → the beat boundaries to advance on.

### 4.2 The wiring (T9 tier-0)

The plan (RAG_STORE_VISUALS_RESEARCH.md) calls this **T9 tier-0**: an authored scene
sits *above* the existing similarity-crop tiers. On an EXPLAIN turn:

1. Resolve concept → look up `concept_figures.json`. **Hit** → tier-0 scene.
   **Miss** → fall through to today's T9 similarity crops (unchanged fallback).
2. Two sync modes, in order of fidelity:
   - **Scene-narration mode (ship first):** the scene's own beats *are* the
     explanation — play the authored scene (§2) and let its beat narration be what
     Wini speaks. Simplest, and the scene was authored to be a correct worked
     example. Best when the learner asked "explain X".
   - **Answer-driven mode (later):** keep the brain's generated answer as the
     spoken text and **map each streamed sentence to the next beat's frame** (show
     beat i's accumulated frame as sentence i is spoken). Needs the scene's beat
     count to roughly match the answer's sentence count, or a coarser "advance the
     figure every K sentences" rule.
3. Non-EXPLAIN modes (PRACTICE/TEST) do **not** auto-play scenes — a scene is a
   teaching aid, not a test reveal.

### 4.3 Where the code goes

- **Client:** factor the per-beat body of `scene_player.play_scene` into a reusable
  `play_beat(chan, scene, i, speaker_or_none)` so the live client can drive it from
  the STT/brain loop instead of the standalone `main()`. The client already hosts
  the mode channel and owns the speaker in the normal pipeline
  (`run_wini_package.sh`), so no second channel is needed — reuse the running one.
- **Selection:** a small `scene_for_concept(concept_id)` helper reading
  `concept_figures.json`, returning the scene dict or `None`.
- **Trigger:** in the client's turn handler, when mode == EXPLAIN and a scene
  exists, drive beats as the answer streams; otherwise keep today's `render_crop`
  T9 path. Keep the `_REQUIRED` skip-guard discipline so a bad scene degrades to the
  crop path, never crashes the turn.

### 4.4 Contract already in place

The mode channel (`wini_client/mode_channel.py`, TCP :8140, newline-JSON,
`MAX_LINE 1900`) and the LVGL commands (`figure`, `explain`, `screen`, `stage`,
`lines`, `status`) that `app_state.c` already handles are exactly what `scene_player`
uses — so the live path speaks the **same** UI contract. Nothing new on the UI side.

---

## 5. Connecting to the Pi (winipi5)

### 5.1 Reach the device

The tools live at `/f/ROS_testing/` (`plink`/`pscp`). Host key and password are
fixed for this lab board:

```bash
/f/ROS_testing/plink -ssh -batch \
  -hostkey SHA256:9Cm9oVUWxYqNvzhp5f1rmkYYRtm0YFA/wE6aJVbXKH0 \
  -pw roavai winipi5@winipi5.local "hostname; uname -m"
```

- Repo on the Pi: `/home/winipi5/cloud_tutor/cloud-CLI`
- venv: `.venv/bin/python` (Python 3.13.5, PIL 11.1.0, aarch64)
- **`pscp` does NOT expand `~`** — always use absolute remote paths.

### 5.2 Copy files up

```bash
/f/ROS_testing/pscp -batch -hostkey SHA256:9Cm9oVUWxYqNvzhp5f1rmkYYRtm0YFA/wE6aJVbXKH0 \
  -pw roavai \
  "D:/cloud CLI/rag_store/figure_specs/jemh104__quadratic_formula.scene.json" \
  winipi5@winipi5.local:/home/winipi5/cloud_tutor/cloud-CLI/rag_store/figure_specs/
```

### 5.3 Display / Wayland facts

winipi5 runs **labwc/Wayland** (since 2026-07-22):

- Screenshots: **`grim`** (not `scrot`), Wayland-native.
- Env for GUI/screen work over SSH: `WAYLAND_DISPLAY=wayland-0`, `DISPLAY=:0`.
- UI binary: `wini_ui/build/wini_ui --port 8140`.
- Panel: Waveshare 7″ DSI, portrait 600×1024; the figure card is **500×380**
  (`display_sinks.FIG_MAX_W/H`) — the canvas default in the specs.

### 5.4 Audio over SSH — the unlock (important)

PortAudio shows **`[]` output devices over bare SSH** for two reasons, both must be
fixed:

1. The **ReSpeaker Lite has a single playback substream** and the running
   `wini_client.client` + `touch_service.py` **hold it**.
2. The **seat session env is missing**.

Fix:

```bash
pkill -f 'wini_[c]lient.client'   # free the device
pkill -f 'touch_[s]ervice.py'
export XDG_RUNTIME_DIR=/run/user/1000
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
export WAYLAND_DISPLAY=wayland-0
export DISPLAY=:0
# now hw:2,0 @16kHz enumerates and playback works
```

Launch a demo detached via a `/tmp/*.sh` + `setsid`. **Restore the normal tutor**
afterward with `run_wini_package.sh` under the **same seat env** (it launches
brain :8123 + client `--display lvgl --ui-port 8140` + the UI binary).

### 5.5 Benchmark render cost on the device

```bash
.venv/bin/python -m figures.scene_render \
  rag_store/figure_specs/jemh104__quadratic_formula.scene.json --bench
```

`psutil` is not in the Pi venv — `bench` falls back to `/proc/self/status` VmRSS.

### 5.6 Font consistency note

`NunitoSans.ttf` (the UI look) is **not** at
`pi_game/alphabet_ui/fonts/NunitoSans.ttf` on this checkout, so
`figure_render._FONT_CANDIDATES` falls back to system **DejaVuSans** — full
√/²/subscript coverage, renders correctly but differs from the NunitoSans UI look.
Deploy NunitoSans to the Pi (or repoint the candidates) for visual consistency.

---

## 6. Status & remaining work

**Built + verified on winipi5 (2026-07-26):** render schema + Pillow/SVG renderer,
scene renderer (beat frames + GIF), Gemini scene authoring (`build_concept_scene`),
client beat-player (`scene_player`), audio-over-SSH unlock — PLUS the forward plan:

- `figures/build_chapter_scenes.py` — the batch driver (§3.3). Authored the whole of
  **jemh104 (8/8 concepts)**; the driver skips already-valid specs and writes the index.
  Two authoring guards were added to `build_concept_scene` this pass: an 8192-token
  budget + 90 s timeout (a truncated JSON response is an unparseable, lost scene), and
  a **HARD LIMIT prompt rule** (≤6 beats, ≤6 elements/beat, never re-emit a label) that
  stopped a runaway repetition loop on the discriminant's three cases.
- `rag_store/concept_figures.json` — the concept→scene index (§3.4), 8 concepts.
- **Live mic wiring (T9 tier-0), VISUAL-ONLY**, verified against the cloud brain via
  `tools/scene_live_check.py` (mic-free: Cloud-TTS'd utterance → real STT/brain/
  perception → panel). The first cut (scene-narration: the scene *replaced* the spoken
  answer and spoke its own TTS) was rejected on the device — the reSpeaker Lite has ONE
  playback substream, so a second TTS consumer starved the answer (`[PaErrorCode -9985]`,
  TTS died). The shipping design:
  - The brain's **real answer is the only audio** (no second speaker, no contention).
    The scene provides only the **figure**, which grows one beat per answer audio chunk
    (`_SceneVisual` in `client.py`; unique `/tmp/wini_scene_<nonce>_<i>.png` per frame so
    the LVGL card never reloads a stale image). The final frame is guaranteed at the end.
  - The T9 crop is suppressed on a scene turn (`on_meta` runs `sink.on_turn` for the
    screen/header, not `apply_turn_ui`'s crop `show()`); normal status flow is preserved
    so the indicator returns to **waiting**. Graded / non-EXPLAIN turns get no scene.
  - Arms off the authoritative concept in `on_meta` (works against the cloud brain as-is),
    or earlier in `on_part` if the brain rides `concept` on the `filler` part. Toggle:
    `--no-scenes`. Verified cloud: `chunks=78` answer played, **0 audio errors**, 21 s turn.
  - `build_concept_scene --shape graph|derivation`; `quadratic_formula` re-authored as a
    **GRAPH** (parabola + roots on axes).

**Still to build:**

- Answer↔visual coherence: the brain's answer sometimes names a different figure it chose
  ("look at the prayer hall") while the panel shows the scene graph. Either gate scenes to
  turns where the brain has no figure of its own, or feed the scene id back to the brain so
  its answer describes what's on screen.
- `filler`-part `concept` on the **Cloud Run** brain (already on the on-Pi `wini_server.py`)
  so the visual arms from the first word instead of mid-answer. Not required for correctness.
- LVGL-native / ESP32 beat player and intra-beat smooth animation on device.
- More chapters (the driver is chapter-general: `build_chapter_scenes.py jemhXXX --run`).
- A static-figure authoring script; deploy NunitoSans to the Pi (§5.6).
