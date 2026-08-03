# Board Buddy ↔ Response Layer Integration Plan

> **Status (2026-07-29):** Phases 1–3 **BUILT** brain-side + device-side (headless-verified,
> 57/57 response-layer tests green incl. 22 new); Phase 4 (Cloud Run deploy + live winipi5
> two-surface bring-up) pending hardware. See **§11 Build status** at the foot of this doc.
> Original planning text below is preserved as the design of record.
> **Scope:** integrate the **Board Buddy** visual display engine
> (`github.com/Roavai/board_buddy`, frozen v1.0) as a rendering target for the
> `cloud_workspace_v8/response_layer/` Teaching-Script pipeline.
>
> **Given (2026-07-29):** Board Buddy is **already installed and unit-tested as a package
> on the Pi** and verified rendering live. So this is **purely an integration task** —
> the renderer exists and works. That removes three earlier concerns outright:
> vendoring/pinning (§6.8), the Phase-0 render spike (§7), and headless testability
> (§6.10). The remaining work is the wire contract, the grounded authoring module, the
> compiler branch, and **one decision: who owns the panel** (§6.1).
>
> **Confirmed wiring:** renderer stays on the **Pi**, brain stays in the **cloud**. The
> cloud brain authors the payload (it needs Vertex; the Pi cannot call it) and ships a
> small JSON payload over the existing mode channel; the Pi renders locally. This is the
> intended separation and the plan is built around it (§3.2, §6.2).
> **Author aid:** derived from a full read of the Board Buddy README + its three docs
> and every response-layer module (`contracts`, `planner`, `validator`, `visual_gate`,
> `compilers`, `scene_author`, `scene_adaptation`, `device_runner`, `device_profile`),
> plus the live seam in `tutor_loop._response_layer` and the device path in
> `wini_client/{client,display_sinks,scene_player}.py` + `figures/scene_render.py`.

---

## 0a. Settled architecture decision (2026-07-29) — LVGL is the parent

Per product direction, the ownership model is fixed (supersedes the "prefer Mode A"
lean below, which was written before this call):

- **LVGL `wini_ui` is the parent and owns the panel and the lifecycle.** It **launches**
  Board Buddy when a turn needs a visual explanation and **closes** it when done. Board
  Buddy never starts or stops itself.
- **While Board Buddy is active it has EXCLUSIVE use of the 600×845 region.** LVGL must
  not draw any other content inside 600×845 during that time (no card swaps, no status
  text over it) — it must not "fight" the visual.
- **The parent control shell lives OUTSIDE 600×845.** LVGL keeps persistent controls
  (pause / stop / mute / close) in the area outside Board Buddy's region, so the child can
  always be paused/closed by the parent and the learner.
- **Renderer on the Pi, brain in the cloud** (already agreed): the cloud brain authors the
  payload, ships JSON over the mode channel; the Pi renders with the installed Board Buddy.
- **The response-layer output must be fully tool-capability-aware** (§10, NEW): it knows
  Board Buddy's exact tool matrix and uses the right tool per concept, with animation
  **synced to the spoken answer**.

**Resolved 2026-07-29 (device-level choices):**
- **Launch mechanism = separate pygame surface.** LVGL spawns Board Buddy as its own
  pygame/SDL client positioned at (0,0) sized 600×845; Board Buddy runs its native 60 FPS
  loop + touch scrubber; LVGL kills the process to close. Wayland surface co-existence +
  touch routing between the two surfaces are now **in scope** (§6.1).
- **Control band = bottom strip 845–1024.** On the 600×1024 portrait panel, Board Buddy
  takes the top 0–845; the LVGL parent controls live in the ~600×179 strip below it.
- **Master clock = the LLM (brain), NOT the audio.** This is the big one — see §10.2. A
  visual teaching turn is an **LLM-orchestrated segment loop**: each segment the LLM
  independently decides to emit a Board Buddy tool call, a speech utterance, both, or
  neither; the device executes and reports completion; the LLM drives the next segment or
  ends. Board Buddy is a **pure executor** of the brain's payload, and the brain's visual
  output MUST be valid Board Buddy tool-call syntax. This matches Board Buddy's own LLM
  Integration Guide (function-calling `draw_board` + diagnostic + Option A/B turn control).

---

## 0. TL;DR + recommendation

Board Buddy and the response layer solve **adjacent** problems and currently overlap on
one: **how a maths visual gets drawn on the Pi screen.**

- The **response layer** already decides *whether* a visual is earned (Visual Benefit
  Gate), *what* it should show (grounded in the actual spoken answer via
  `scene_author.author_scene_from_answer`), and *when* each beat is revealed. It emits a
  visual in **our own scene schema** (`figures.scene_render`: `label / curve / tracer /
  point / axes` on a 0..1 canvas, a beat timeline).
- **Board Buddy** is a **richer renderer** with 8 child-friendly tools (stickers,
  number-line hops, 1D/2D fraction grids, function graphs, geometry, LaTeX text,
  parameter/spatial animation), a 60 FPS pygame loop, and an interactive time scrubber —
  but it has **no pedagogy, no grounding, no earn-decision**. It renders whatever JSON
  payload it is handed.

They compose cleanly if we treat **Board Buddy as a new *compiler target + renderer*,
not a new brain.** The response layer keeps owning the pedagogy; a new compiler branch
translates the validated Teaching Script into a Board Buddy `draw_board` payload.

**Chosen path (see §0a): LVGL parent + separate Board Buddy pygame surface, driven by an
LLM-orchestrated segment loop.** Board Buddy runs its native 60 FPS surface in the top
600×845; LVGL owns lifecycle + the 845–1024 control strip; the brain's LLM interleaves
`draw_board` tool calls and speech per segment.

> The two-mode A/B table below was the pre-decision analysis and is kept for context. The
> chosen model is B-shaped (full native surface) but under LVGL parentage and with the LLM
> as the master clock — not the earlier "prefer A, defer B" lean.

| Mode | What runs on the Pi | Pros | Cons |
|---|---|---|---|
| **A — offscreen render → PNG** | `BoardBuddyCanvas.render()` headless → PNG → existing `{"cmd":"figure"}` card | No display-owner/Wayland/touch conflict, unit-testable | Loses 60 FPS + scrubber; static-per-beat |
| **B — full Board Buddy surface (CHOSEN)** | pygame owns 600×845, 60 FPS, touch scrubber | Full interactivity, smooth `animate_param`, child scrubbing | Must solve two-surface Wayland co-existence + touch routing (§6.1) — now in scope |

---

## 1. How the two systems are shaped

### 1.1 Response layer (brain-side, `cloud_workspace_v8/response_layer/`)

Runs **inside the Pi's `wini_server` brain process** (or the Cloud Run brain), flag-gated
by `WINI_RESPONSE_LAYER=1`. Pipeline per turn (see `tutor_loop._response_layer`, line 1573):

1. `build_response_context(...)` → `ResponseContext` (frozen upstream signals).
2. `TeachingScriptPlanner().plan(ctx)` → a `TeachingScript` of `Beat`s (bounded DAG).
3. `ScriptValidator().validate(...)` → fills `script.validation`, including the earned
   **visual decision** (`validation["visual"] = {allowed, reason, visual_type, ...}`).
4. If a visual is earned, the directive is `generated_declarative_scene_spec` with
   `pending_draw=True`. **After** answer generation, `turn()` calls
   `scene_author.author_scene_from_answer(answer, …)` which does the text-aware draw:
   a structured Gemini call extracts board lines / parabola coeffs FROM the answer,
   ungrounded numbers are dropped, and the brain lays them out **deterministically** into
   a `figures.scene_render` scene.
5. `compilers.compile_response(script, answer, scene, profile)` → a device bundle of
   compiled beats; `device_runner.DeviceScriptRunner` sequences them.

Key invariants the integration must not break:
- **Text-aware visuals mandate** (memory `visuals-must-be-text-aware`): a visual may ship
  only if coupled to the *actual spoken answer*. Canned per-concept scenes mislead.
- **LLMs plan; deterministic systems render** (`scene_author` §3.3): the model only
  extracts short strings/coefficients copied from the answer; the brain computes geometry
  and lays out. **No number on the board that the answer didn't state** (`_ground_lines`).
- **Single-writer learner state**: the response layer is planning/validation only; state
  moves once at turn close via `apply_response_outcomes`.
- **Device capability profile** (`device_profile.py`): the validator drops anything the
  reported device can't do (e.g. all robot primitives on winipi5).

### 1.2 Board Buddy (device-side renderer, frozen v1.0)

- Single file `board_buddy.py` (~1770 lines) + `docs/` + `examples/`. Deps: `Pillow`,
  `matplotlib`, `pygame`.
- Core API: `BoardBuddyCanvas(width=600, height=800, theme=…)` with
  `load_json(payload) -> diagnostic dict`, `render(anim_progress) -> PIL.Image`,
  `get_max_duration()`, `has_animation()`, `set_scrub_time(t)`,
  `handle_touch_scrub(x, y)`.
- Payload = a **flat JSON array** of elements; 8 `type`s: `text`, `stickers`, `geometry`,
  `graph`, `numberline`, `fraction`, `animate_param`, `animation`. Positions are **pixel**
  coords on a 600×800 viewport (600×845 when animated, +45px scrubber bar).
- Animation model: `animate_param` morphs `{var}` placeholders in text/equation/hops/
  numerator over `duration`; `load_json` computes `T_max`; the pygame loop runs 0→T_max at
  60 FPS then freezes. Diagnostic status returns **after** animation for animated payloads.
- README ships a `TutorBoardBridge` reference (pygame `set_mode((600,845))`, blocking
  `run_animation_loop`). Assumes **X11 `DISPLAY=:0`**.

### 1.3 Current device visual transport (what Board Buddy would slot into)

Brain → device is display **metadata only** over the mode channel (:8140). Scenes render
to **PNG frames** (`figures.scene_render.render_beat_frame`, Pillow) — one PNG per beat,
grown in step with the streamed answer (`wini_client/client.py` `_SceneRunner`, ~line 574)
— and pushed as `{"cmd":"figure","path":<png>}` to the **LVGL `wini_ui`** figure card
(500×380, portrait). LVGL only displays static PNGs; it does not run pygame.

---

## 2. The core integration gap

There are **two different visual schemas and two different renderers**:

| | Response layer scene spec | Board Buddy payload |
|---|---|---|
| Coordinate space | fractional `0..1` canvas + a data `view` (real x/y) | **pixel** 600×800 |
| Primitives | `label, curve(quad), tracer, point, axes, segment, polygon, right_angle` | `text, stickers, geometry, graph, numberline, fraction, animate_param, animation` |
| Graphs | `curve` = quadratic `[a,b,c]` sampled natively (no `eval`) | `graph` = **equation string** `"y = {a:2f}*x^2"` parsed by Board Buddy |
| Reveal model | beat timeline, one beat per audio chunk (`_SceneRunner`) | single payload, `animate_param` over `T_max`, 60 FPS |
| Renderer | Pillow → PNG → LVGL card | pygame surface (or `render()` → PIL) |
| Canvas | 500×380 | 600×800 (+45) |

So integration is **not** "call an API"; it is **a translation layer + a rendering
decision**. The response layer's job (earn + ground + sequence) stays; a new compiler
branch emits Board Buddy JSON, and Mode A/B decides how that JSON reaches pixels.

---

## 3. Proposed architecture

### 3.1 New pieces

```
response_layer/
  board_buddy_author.py     NEW  author_board_from_answer(answer, concept, ctx)
                                 -> Board Buddy payload (text-aware, grounded), mirrors
                                    scene_author.py discipline (LLM extracts, brain lays out)
  board_buddy_compile.py    NEW  scene_spec -> Board Buddy payload translator (fallback
                                    path for already-authored figures.scene_render scenes)
  contracts.py              EDIT add VisualType handling / capability flag (see §5)
  compilers.py              EDIT new _compile_visual branch -> {"kind":"board_buddy_payload", ...}
  device_profile.py         EDIT renderer="board_buddy" | capability flags + limits

wini_client/
  board_buddy_sink.py       NEW  device-side: receive payload, render (Mode A: headless
                                    render()->PNG->existing figure card; Mode B: pygame loop)
  vendor/board_buddy.py     NEW  vendored frozen v1.0 (pinned; do NOT edit — it is frozen)

wini_server.py              EDIT emit {"cmd":"board","payload":[...] , "tmax":…} on turn_meta
```

### 3.2 Data flow (LLM-orchestrated segment loop — the resolved model)

```
tutor_loop.turn()  [visual turn: Visual Benefit Gate earned a visual]
  └─ ORCHESTRATION LOOP (brain, budget-bounded), LLM given Board Buddy's
     draw_board function-calling schema as a real tool:
       segment = LLM.decide()  -> { board_call?: <draw_board payload>, speech?: <text>, done? }
         │ belt: validate board_call vs capability manifest (§10.1) + ground values; drop off-spec
         ├─ if first board_call:  emit {"cmd":"board_open"}   (LVGL spawns BB @ 0,0 600×845,
         │                                                     suppresses figure card)
         ├─ if board_call:        emit {"cmd":"board","payload":[...], "tmax":…}
         ├─ if speech:            stream speech -> Cloud TTS on client
         └─ WAIT device completion ack (animation done AND/OR speech done)
       ... LLM drives next segment, or done ->
  └─ emit {"cmd":"board_close"}   (LVGL kills BB subprocess, restores figure card)
DEVICE
  wini_client.board_buddy_sink (separate pygame surface, native 60 FPS + scrubber):
     board_open  -> spawn/position BB window, set board_active (gate LVGL card in 0–845)
     board       -> BoardBuddyCanvas.load_json(payload); run native loop to T_max
     speech      -> speak (client owns reSpeaker); on finish -> ack to brain
     board_close -> teardown, clear board_active, restore LVGL card
  LVGL wini_ui: parent controls (pause/stop/mute/close) in the 845–1024 strip
```

The brain↔device link is now **conversational within a turn**: the device acks each
segment's completion so the brain's LLM can decide the next one (see §10.2, §6.3).

### 3.3 Why author directly into Board Buddy payload (not translate our scene spec)

Under the segment-loop model the brain's LLM emits Board Buddy `draw_board` tool calls
directly, so the payload is authored inline by the same call that speaks — no separate
"author from the finished answer" pass is required on the happy path. Board Buddy's own
LLM Integration Guide provides the Gemini/OpenAI function schema to register as the tool.
The grounding + capability-belt discipline from `scene_author` (`_ground_lines`,
`_parse_parabola`) is reused as a **deterministic validator** on each tool call, not as the
generator. `scene_author.author_scene_from_answer` and a `board_buddy_compile.py`
(scene→payload translator) remain as **fallbacks** for a non-orchestrated turn or the
~existing authored `.scene.json` figures. This still gains Board Buddy's richer vocabulary
(stickers, numberline hops, 2D fraction grids) that our scene spec can't draw.

---

## 4. Schema translation map (scene spec → Board Buddy)

For the fallback translator and to bound scope. Not all of ours map 1:1.

| Our primitive | Board Buddy target | Notes / risk |
|---|---|---|
| `label` (text, fractional `at`) | `text` (pixel `pos`) | convert `at∈[0,1]` → pixels; keep LaTeX (`\frac`, `^`) — Board Buddy auto-LaTeX handles it |
| `curve` `quad:[a,b,c]` over `domain` | `graph` `equation:"y = a*x^2 + b*x + c"` | **coeff → equation-string** rebuild; Board Buddy re-parses & re-plots (different sampler) → visual may differ slightly; set `x_range`/`y_range` from our `view` |
| `tracer` (dot riding the quad) | `animate_param` on a graph var **or** drop | Board Buddy has no native "dot on curve"; approximate or omit |
| `point` `at:[x,y]` (root markers) | `geometry` `circle` small **or** `stickers` `star` | root dots → small circles at mapped pixels |
| `axes` `grid/step` | implicit in `graph` card | Board Buddy graph draws its own axes; don't double-draw |
| `right_angle`, `segment`, `polygon` | `geometry` (`right_triangle`, `rectangle`, vertices) | maps to geometry vertices |
| beat timeline reveal | Mode A: our reveal schedule; Mode B: `animate_param` | see §6 sync |

**New capabilities Board Buddy unlocks (author directly, no equivalent in our spec):**
`stickers` (counting/grouping), `numberline` hops (add/subtract), 1D/2D `fraction`
grids (fraction multiplication as area model). These are worth a dedicated authoring
branch keyed off concept type (counting / arithmetic / fractions).

---

## 5. Device profile + contract changes

- `device_profile.py`: add `renderer="board_buddy"` as a valid value (or a
  `visual_renderer` field distinct from `pillow_lvgl`); add
  `supports_board_buddy: bool`, and Board-Buddy-specific limits
  (`max_visual_elements_per_beat` already exists — Board Buddy is happy with flat arrays,
  so keep generous on Pi). Board Buddy's future ESP32-P4 roadmap is **LVGL**, not pygame —
  encode that: `supports_board_buddy=False` on the ESP32 profile so the validator falls
  back to crop/formula-text there (see §7 ESP32).
- `contracts.VisualType`: reuse `GENERATED_DECLARATIVE_SCENE_SPEC` (authored-from-answer)
  and/or `INTERACTIVE_VISUAL` (Mode B with scrubber) — do **not** invent a raw
  `board_buddy` visual type; the type stays pedagogy-level, the *renderer* is a device
  concern. Add a compiler branch keyed on `profile["renderer"] == "board_buddy"`.
- `compilers._compile_visual`: for a scene-bearing beat on a Board-Buddy device, emit
  `{"kind":"board_buddy_payload", "payload":[...], "tmax":float, "narration_mode":"script_override"}`
  instead of `{"kind":"scene_spec", ...}`.

---

## 6. Issues to fix BEFORE integrating (the real work)

Ranked by how likely they are to block or bite.

### 6.1 Display-stack / ownership — SETTLED (LVGL parent, separate BB surface)
Ownership is decided (§0a): LVGL owns the panel + lifecycle; Board Buddy is launched as a
**separate pygame surface** positioned at (0,0) sized 600×845, gets exclusive use of that
region while active, and LVGL keeps controls in the bottom 845–1024 strip. Remaining work:

- **Two Wayland surfaces under labwc.** winipi5 is labwc/Wayland; Board Buddy's bridge
  assumes X11 `DISPLAY=:0`. Confirm pygame/SDL can present a **windowed, positioned**
  600×845 surface under labwc (SDL Wayland backend, or run Xwayland for the BB client), with
  the LVGL app as the other surface and labwc stacking them. This is the top device risk —
  validate early on the actual board.
- **Touch routing across two surfaces.** One physical touchscreen (uinput/evdev, Wayland).
  Touches inside 0–845 must reach Board Buddy (its scrubber lives at Y 800–845); touches in
  845–1024 must reach the LVGL controls. Normally the compositor routes by surface geometry
  — confirm this holds for the winipi5 touch stack, or add an explicit router.
- **Exclusivity enforcement.** The client must **suppress the LVGL figure card and any card
  writes into 0–845** while Board Buddy is up (a `board_active` flag gating
  `display_sinks`), and restore normal LVGL behaviour on `board_close`. New client-side
  state, driven by the parent lifecycle verbs (§10.3).
- **Lifecycle = process spawn/kill.** LVGL launches the BB client subprocess on
  `board_open` and terminates it on `board_close`; a crashed BB process must not take the
  parent down (supervise + degrade to the crop/formula-text fallback).

### 6.2 Transport: brain can't call the renderer directly
- Board Buddy runs on the **device**; the response layer runs in the **brain** (often
  Cloud Run, not even on the Pi). The brain must **emit the payload over the wire**, like
  it emits figure PNG paths today. New mode-channel command `{"cmd":"board", ...}` +
  device handler. The Pi cannot call Vertex (memory `response-layer-phase1-2`), so the
  authoring (`author_board_from_answer`, which needs Gemini) must run **brain-side**; only
  rendering runs device-side. Payload crossing the wire is small JSON — fine.

### 6.3 Generation architecture — segment loop vs Part-13 single-call streaming
- The resolved control model (§10.2) makes a visual turn an **LLM tool-use loop**: multiple
  brain LLM turns + a brain↔device completion round-trip **per segment**. This is a real
  departure from Part-13's *one* streamed generation call, and the main cost is **latency**
  (each extra segment = another LLM call + another device ack round-trip).
- **Scope proposal (Q4, §8):** run the segment loop **only on earned-visual turns**;
  plain Q&A / social / administrative turns keep the fast Part-13 single-call streamed path
  untouched. This preserves today's latency on the common case and pays the loop cost only
  when a visual is genuinely being taught.
- **Speech stays dynamic-length.** A segment's speech is not clamped to Board Buddy's
  `T_max` (memory `answer-length-stays-dynamic`). Board Buddy runs its native loop on its
  own surface/thread; the device acks when **both** the segment's speech and its animation
  have finished, and the LLM decides the next segment — so speech and animation are
  coordinated at **segment boundaries**, exactly as the user specified ("one tool call, wait
  for the speech to complete, then the LLM decides again").
- **Barge-in still works:** a learner interrupt cancels the current segment (duck speech,
  pause the BB loop) and re-enters the brain — reuse `device_runner.interrupt` /
  `resume_decision`, extended to the generation-segment loop.

### 6.4 Text-aware grounding must carry over (hard mandate)
- Board Buddy will happily render any payload — including `animate_param from/to` values
  and `stickers count` the tutor never said. This is exactly the "canned visual misleads"
  failure (memory `visuals-must-be-text-aware`).
- **Fix**: `author_board_from_answer` reuses `scene_author._ground_lines` /
  `_answer_number_set` discipline — every number, count, hop, numerator/denominator on the
  board must be grounded in the answer text, else dropped. The LLM extracts; the brain
  validates + lays out. No `animate_param` range the answer didn't state.

### 6.5 Touch arbitration
- Board Buddy's scrubber consumes touch on `Y ≥ 800`. The response layer also wants touch
  for **assessment hooks** (`_compile_interaction` → `touch_prompt`; `device_runner`
  `await_touch`). GPIO22 + touchscreen are the device's touch inputs.
- **Fix / decision**: in Mode A there is no scrubber (no conflict). In Mode B, define which
  region/owner gets a touch: scrubber bar (Board Buddy) vs assessment prompt (runner). Keep
  them **temporally exclusive** — a beat is either scrubbing-review or awaiting-assessment,
  never both.

### 6.6 Dependencies + latency on the Pi
- New device deps: `pygame`, `matplotlib`, `Pillow`. Pillow is already used; matplotlib is
  heavy and its **LaTeX text rendering is slow** (per-figure font/mathtext cost). Board
  Buddy uses matplotlib mathtext for `text`/`title` LaTeX.
- **Fix**: measure headless `render()` latency per beat on the Pi 5 before committing;
  cache fonts; prewarm matplotlib (import + one throwaway render at startup, like the
  existing embedder prewarm). Confirm pygame is only needed for Mode B — Mode A may avoid
  it (verify Board Buddy's `render()` path doesn't import pygame at module load).

### 6.7 Coordinate + canvas geometry
- Our card is **500×380**; Board Buddy is **600×800**. The winipi5 panel is 600×1024
  portrait, so Board Buddy's 600×845 fits, but the LVGL figure card is smaller.
- **Fix (Mode A)**: render Board Buddy at its native 600×800, then letterbox/scale into the
  existing card like `display_sinks._emit_figure` already does for crops — or widen the
  card. Decide target card size; keep aspect.

### 6.8 Board Buddy is FROZEN v1.0 — integrate around it (mostly resolved)
- Already installed as a package on the Pi, so **no vendoring decision to make** — just
  pin/record whatever version is deployed so a future update is deliberate. Do **not**
  modify it; all adaptation lives in *our* new modules.
- Still worth doing: feed its **diagnostic return** (`partial_success` / `warnings`) back
  into compiler/telemetry for self-heal (drop an unknown element, log, degrade to crop) —
  the README explicitly designs this loop.

### 6.9 ESP32-P4 future target
- The real device roadmap is **ESP32-P4 + LVGL** (memory `hardware-target-esp32p4`), which
  **cannot** run pygame/matplotlib. Board Buddy's own roadmap says an LVGL port comes later.
- **Fix**: gate Board Buddy behind `device_profile.supports_board_buddy`; ESP32 profile
  sets it False and the validator degrades to `retrieved_crop` / `static_text_formula`.
  The response layer already has this fallback shape — keep the Board Buddy path a
  capability, not an assumption.

### 6.10 Testing (Board Buddy itself already unit-tested; test only OUR seam)
- The renderer is already unit-tested on the Pi, so we don't retest it. What still needs
  tests is **our new code**: `test_board_buddy_author.py` (grounding — no ungrounded
  number/count/hop survives) and `test_board_buddy_compile.py` (scene→payload), mirroring
  the existing `response_layer/test_*` suites. These run headless (`render()` returns a PIL
  image, no window) against Board Buddy's shipped `examples/` payloads.

### 6.11 Deployment reconciliation
- The response-layer Phase 2.5–5 code was built partly on the Pi and only recently
  reconciled into D:, and is **not yet on Cloud Run** (memory
  `response-layer-phase2_5-5`). Board Buddy authoring must land in the **Cloud Run brain**
  (it needs Vertex); the renderer lands on the **device**. Sequence the two deploys.

---

## 7. Phased implementation plan

**Phase 0 — DONE (Board Buddy installed + unit-tested + rendering live on the Pi).**
- Renderer exists and works. No vendoring/spike needed.

**Phase 1 — capability manifest + tool-aware authoring (brain-side).**
- `response_layer/board_buddy_caps.py`: the machine-readable capability manifest (§10.1)
  + Board Buddy's `draw_board` **function-calling schema** to register as an LLM tool.
- The grounding/validation belt: reuse `scene_author._ground_lines` / `_parse_parabola` as
  a **validator** over a tool call (drop off-spec/ungrounded elements). Pedagogical tool
  routing rules (§10.1). Unit tests: no ungrounded count/coeff survives; off-spec element
  dropped; every allowed tool schema-checks.
- **Exit:** given a segment's `board_call`, the belt yields a valid, grounded payload or
  rejects it — pure functions, headless, fully tested.

**Phase 2 — segment orchestration loop (brain-side) + wire verbs.**
- The LLM tool-use loop (§10.2): register `draw_board`, run the budget-bounded segment
  loop, emit `board_open` / `board` / `board_close` + speech, consume device completion
  acks. Extend `device_runner` to gate **generation** segments (not just assessment) with
  the ack/suspend-resume it already has. Gate the loop to earned-visual turns (§6.3, Q4).
- `wini_server` emits the verbs; a stub device ack lets this be tested without hardware.
- **Exit:** a scripted visual turn produces a correct `board_open → (board|speech)* →
  board_close` sequence with acks, offline; plain turns unchanged (Part-13 path intact).

**Phase 3 — device: separate Board Buddy surface under LVGL parent (on winipi5).**
- `wini_client/board_buddy_sink.py`: on `board_open`, LVGL spawns the BB pygame subprocess
  positioned (0,0) 600×845 and sets `board_active` (suppress the figure card in 0–845);
  `board` → `load_json` + native 60 FPS loop; speech via the client; ack on completion;
  `board_close` → kill BB, restore card. LVGL parent controls (pause/stop/mute/close) in
  the 845–1024 strip mapped to scrub/pause/stop/mute.
- Resolve the two device risks live: **SDL/pygame windowed+positioned under labwc**, and
  **touch routing across the two surfaces** (§6.1). matplotlib prewarm on the BB process.
- **Exit:** a live EXPLAIN turn on winipi5 runs the segment loop — Board Buddy animates in
  its region, speech interleaves per the LLM's segments, parent controls work, no card
  bleed into 0–845.

**Phase 4 — cloud + ESP32.** Deploy the orchestration to the Cloud Run brain (needs
Vertex); set the ESP32 profile `supports_board_buddy=False` so the validator degrades to
`retrieved_crop` / `static_text_formula`. Sequence brain deploy before relying on it live.

---

## 8. Decisions — resolved + still open

**Resolved (2026-07-29):**
- **Q1 — Launch mechanism:** separate positioned pygame surface, spawned/killed by LVGL
  (§6.1).
- **Q2 — Control band:** bottom strip 845–1024 (§0a).
- **Q3 — Master clock:** the LLM (brain), via segment-streamed orchestration; Board Buddy
  is a pure executor (§10.2).

**Still open:**
1. **Q4 — Does the segment loop replace single-call streaming for all turns, or only
   earned-visual turns?** (§6.3) — recommendation: **only earned-visual turns**, so plain
   Q&A keeps today's Part-13 latency. Needs a yes/no.
2. **Authoring vocabulary scope** — register all 8 Board Buddy tools with the LLM day one,
   or start with `text`/`graph` (parity with today's scene author) and add
   stickers/numberline/fraction/geometry/animation in a follow-up?
3. **Segment budget** — a cap on segments per turn (latency + cost guardrail). Suggest a
   small default (e.g. ≤4 board calls / turn) — confirm a number.
4. **Vendoring** — moot; already installed. Just record the deployed version.

---

## 10. Tool-capability awareness + audio sync (NEW — product requirement)

The response layer must **know Board Buddy's exact tool capabilities and use them well**,
with animation **synced to the spoken answer**. Two parts:

### 10.1 Capability manifest (the response layer is tool-aware, not tool-blind)
- Add a machine-readable **Board Buddy capability manifest** the authoring + validator read,
  derived from Board Buddy's docs: the 8 tool `type`s, each tool's required/optional params
  and bounds (positions `0≤x≤580, 0≤y≤780`; size presets; `{var:int|1f|2f}` placeholder
  syntax; sticker library names; fraction 1D-vs-2D array forms; geometry shapes), and the
  viewport (600×800, +45 scrubber). Encode it once (e.g. `response_layer/board_buddy_caps.py`)
  and surface a subset on the `DeviceCapabilityProfile` (`board_buddy_tools=[...]`,
  `board_buddy_sticker_names=[...]`) so a device that ships a **subset** of tools is honored.
- The authoring prompt is built **from** that manifest, so the model can only choose real
  tools with real params. The deterministic layout validates every produced element against
  the manifest and **drops** anything off-spec (belt: controlled generation stops invented
  values, not wrong-but-valid ones — same rule as perception §5.3).
- **Pedagogical tool routing** (concept/answer → best tool), so the tool actually fits the
  teaching, not just "some picture":
  - counting / grouping → `stickers` (1D count or 2D grid)
  - addition / subtraction / "hops" → `numberline` with `hops`
  - fractions, fraction multiplication → `fraction` 1D bar / 2D area grid
  - quadratic / parabola / plotting `y=f(x)` → `graph` (reuse `scene_author` parabola coeffs)
  - shapes / angles / right-triangle → `geometry`
  - formula / definition / worked steps → `text` (auto-LaTeX board stack)
  - a morphing parameter that the answer actually varies → `animate_param` (grounded range)

### 10.2 The LLM is the master — segment-streamed orchestration (RESOLVED)
The brain's LLM, not the audio clock, drives the turn. A visual teaching turn becomes a
**segment loop** (an agentic tool-use loop, the model Board Buddy's LLM Integration Guide
is designed for):

```
loop (per teaching turn, budget-bounded):
  LLM segment decision ->  { board_call?: <Board Buddy draw_board payload>,
                             speech?:    <utterance text>,
                             done?:      <end the turn> }
  device executes the segment:
     if board_call:  board_open (first time) -> load_json(payload) -> play (native loop)
     if speech:      speak (Cloud TTS on the client)
     report completion back to the brain (animation done AND/OR speech done)
  LLM sees completion -> next segment, or done -> board_close
```

Rules this encodes:
- **Independent modalities per segment.** The LLM may emit board-only, speech-only, both,
  or neither. "One tool call, wait for the speech to complete, then the LLM decides again"
  is exactly a segment boundary.
- **Board Buddy is a pure executor.** It renders whatever payload it is handed and returns
  its diagnostic; it makes no pedagogical or timing decision. All intelligence is in the
  brain's segment output.
- **The brain's visual output is Board Buddy tool-call syntax, by construction.** The LLM
  is given Board Buddy's **function-calling schema** (from its Integration Guide) as a real
  tool, so every `board_call` is schema-valid. A deterministic belt still validates against
  the capability manifest (§10.1) and **drops** off-spec elements before they reach the wire.
- **Grounding still holds.** Because the same LLM speaks and draws in the same segment,
  the picture matches the words by construction — but the belt still enforces "no value on
  the board the segment's speech/context didn't state" (`scene_author._ground_lines`
  discipline), so a hallucinated count/coefficient never renders.
- **Completion round-trip.** The device must report segment completion (speech finished,
  animation finished) so the brain can drive the next segment. This makes brain↔device
  **conversational within a turn** (today it is fire-and-forget). `device_runner` already
  has the shape for this (`acknowledge` / `spoken_checkpoint` suspend-resume); extend it to
  gate *generation* segments, not only assessment.

**Open tension (Q4, §8):** this loop is a **departure from Part-13's single streamed
generation call**. Multiple LLM turns + brain↔device round-trips per teaching turn add
latency. Proposed scope: the segment loop runs **only when a visual is earned** (EXPLAIN /
representation-gap turns); plain Q&A keeps the fast single-call streamed path. Confirm.

### 10.3 Runner / lifecycle (LVGL parent commands)
- New mode-channel verbs so LVGL, the parent, owns the child's lifecycle:
  `{"cmd":"board_open"}` (LVGL launches Board Buddy, claims 600×845, suppresses the figure
  card), `{"cmd":"board","payload":[...],"tmax":…}` (load + play), `{"cmd":"board_close"}`
  (LVGL tears Board Buddy down, restores the card). The parent controls (pause/stop/mute/
  close) map to `set_scrub_time`/pause/stop on the child and to audio mute on the client.
- `device_runner` gains a Board-Buddy interaction/visual kind so a beat that uses Board
  Buddy emits `board_open → board → board_close` around the beat's speech, and the parent
  never reveals the next beat until the child is closed (the existing "minimum coherent
  unit is one packaged beat" rule).

---

## 9. What we explicitly do NOT change

- The Visual Benefit Gate / earn decision, the single-writer state path, the Part-13
  single-call streaming generator, and the "visuals must be text-aware" grounding rule.
- Board Buddy's source (frozen; vendored read-only).
- The existing crop (`retrieved_crop`) and formula-text fallbacks — they remain the
  degrade path when Board Buddy is unavailable (ESP32, render failure, ungrounded content).

---

## 11. Build status (2026-07-29)

**Phase 1 — capability manifest + grounded authoring (brain-side): DONE.**
- `response_layer/board_buddy_caps.py` — machine-readable manifest of the 8 tools (params,
  bounds, viewport 600×800/+45, sticker library, geometry shapes, fraction modes, `{var}`
  format specs), pedagogical tool routing (§10.1), and profile-subset helpers
  (`allowed_tools_for_profile` / `allowed_stickers_for_profile` / `supports_board_buddy`).
  `MANIFEST_VERSION="board_buddy-v1.0"` records the deployed renderer (§8 Q4).
- `response_layer/board_buddy_author.py` — `validate_board_call` (the deterministic belt:
  capability-checks every element, grounds every quantity/hop/coeff against the answer,
  drops off-spec, clamps/lays-out positions, honours the device tool subset) + the fallback
  `author_board_from_answer` (one structured Gemini call → belt). Reuses `scene_author`'s
  exact grounding primitives.

**Phase 1b — scene→payload fallback translator: DONE.**
- `response_layer/board_buddy_compile.py` — `compile_scene_to_board` (label→text,
  curve→graph per §4; axes/tracer/point not translated on the fallback path).

**Phase 2 — segment orchestration loop (brain-side): DONE (offline).**
- `response_layer/board_buddy_orchestrator.py` — `BoardSegmentOrchestrator`: budget-bounded
  LLM segment loop (§10.2) with injected `decide`/`emit`/`wait_ack` seams, grounding each
  `board_call` against accumulated spoken text, emitting `board_open → (board|speak)* →
  board_close` with acks + interrupt teardown. `vertex_segment_decider` is the live decider.
  Fully tested with a scripted decider (no LLM, no hardware).

**Phase 2b — contract/profile/compiler/runner edits: DONE.**
- `device_profile.py` — `supports_board_buddy` + `board_buddy_tools` + `board_buddy_sticker_names`;
  `WINIPI5_PROFILE` enables it (full set), new `ESP32_P4_PROFILE` disables it (§6.9).
- `compilers.py` — `_compile_visual` emits `{"kind":"board_buddy_payload",...}` on a
  board-capable device, else the scene_spec PNG path (non-board devices unchanged).
- `device_runner.py` — emits `board_open`/`board` on prepare and `board_close` when leaving
  Board Buddy (next beat / script end / interrupt-end), never revealing past an open child.
- `tutor_loop.py` — surfaces `board_payload`/`board_tmax`/`board_animated` on the visual
  directive so it rides `turn_meta` (§6.2). Inert unless `WINI_RESPONSE_LAYER=1` **and** the
  device profile supports Board Buddy.

**Phase 3 — device sink + child surface: BUILT (IPC-verified with stubs; live bring-up pending).**
- `wini_client/board_buddy_player.py` — the pygame CHILD: positioned 600×845 surface, native
  60 FPS loop, touch scrubber, matplotlib prewarm, newline-JSON stdin/stdout IPC, graceful
  degrade if pygame/board_buddy absent or a payload/render errors (never hangs the parent).
- `wini_client/board_buddy_sink.py` — `BoardBuddySink`: spawns/kills the child, feeds
  payloads, reads acks (ready/animation_done/unavailable), forwards control-strip
  scrub/pause, notifies LVGL to suppress/restore its card via mode-channel `board_open`/
  `board_close`. Verified end-to-end against stub pygame/board_buddy (handshake, animated +
  static acks, crash-degrade, card restore).
- `wini_client/client.py` — flag-gated (`WINI_BOARD_BUDDY=1`, default OFF) routing of a
  `board_payload` directive to the sink instead of the scene-PNG figure, with turn-end/exit
  teardown.

**Tests:** `response_layer/test_board_buddy.py` (22 tests: grounding belt, capability/subset,
translator, orchestration loop budgets/interrupt, compiler + runner branches). Existing 35
response-layer tests unaffected.

**Reconciliation to the REAL v1.0 (2026-07-29, on winipi5).** The plan's tool descriptions
were approximations; verified against the deployed `~/board_buddy_sandbox/board_buddy.py` and
corrected across caps/author/compile: **every element needs a unique `id`** (load_json skips
those without one); stickers use **`item`** + the real 64-icon library; numberline uses
**`min`/`max`** + hops **`{start,end}`**; fraction uses **`visual_type`** (int or `[rows,cols]`
for a 2D grid, no num2/den2); geometry `shape` is aliased to `shape_type`; graph equations use
`^`. The belt accepts the model's start/end/from/to aliases and emits the canonical keys.
**Conformance test on the Pi:** the belt's output for all 8 tools loads via the real
`load_json` with **ZERO warnings** and renders to a 600×845 PIL image. A LaTeX quirk was fixed
(Board Buddy's default text color is an RGB tuple its matplotlib LaTeX path rejects → the belt
now defaults a hex color so `text` renders as LaTeX).

**Phase 3 — device bring-up: DONE + screenshot-verified live on winipi5 (2026-07-29).**
- The pygame surface renders correctly under **labwc/Wayland** (`SDL_VIDEODRIVER=wayland`), zero
  errors — LaTeX equation + grounded stickers + numberline hop + parabola all on the panel.
- **Borderless + positioned at (0,0)** via a labwc `windowRule` (identifier `wini-board-buddy`,
  `serverDecoration=no`, `MoveTo 0 0`, `ignoreFocusRequest=yes`).
- **Two Wayland surfaces coexisting:** Board Buddy (native pygame) composites on top of
  `wini_ui` (LVGL/Xwayland) — board owns 0–845, the LVGL parent's Close/Pause + EXPLAIN/PRACTICE/
  TEST controls sit in the 845–1024 strip.
- **LVGL C parent completed:** `wini_ui/app/app_state.c` handles `board_open` (set
  `s_board_active`, clear figure cards) / `board_close`, and the `figure` cmd is suppressed while
  the board is active — compiled clean on the Pi and verified via the mode channel.
- Player IPC hardened live: exits on stdin EOF; a static payload acks exactly once; `WINI_BB_PATH`
  puts the frozen `board_buddy` module on `sys.path`.

**Pi-5 `render()` latency (§6.6, measured 2026-07-29, warm medians):** stickers 0.6 ms,
numberline 1.8 ms, geometry 2.8 ms, fraction 15 ms, graph 30 ms, LaTeX text 19 ms (77 ms cold —
matplotlib mathtext, the predicted cost center; the player prewarms it), a full 6-tool board
~70 ms. Static boards are comfortably real-time; a heavily animated LaTeX board renders at
~15–30 FPS (acceptable; the player caches + prewarms).

**Phase 4 — Cloud Run + remaining:**
- Board Buddy authoring/compile deployed to the **Cloud Run brain** (`wini-brain`, asia-south1)
  by building `brain:v9` from `cloud_workspace_v8/` — flag-gated (`WINI_RESPONSE_LAYER`), so
  behavior is unchanged until the flag flips.
- **Touch routing across the two surfaces** (§6.1) still to validate with a real finger on the
  winipi5 stack (the compositor routes by surface geometry; the scrubber lives at Y 800–845).
- Wire the live client (`WINI_BOARD_BUDDY=1`) into a real mic EXPLAIN turn end-to-end once the
  cloud brain revision is confirmed serving.
