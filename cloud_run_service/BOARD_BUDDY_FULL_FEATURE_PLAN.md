# Board Buddy — Full-Feature Response-Layer Plan

> **Goal (user directive, 2026-08-01):** make the response layer *tool-aware* and have it
> **use every Board Buddy feature — stickers, graph, geometry, numberline, fraction,
> animation, and touch** — so a visual teaching turn is the best it can be for the learner.
>
> **Decisions taken (2026-08-01):**
> - **Delivery = BOTH.** The same authored payload feeds (a) the **live device surface**
>   (Pi/ESP32 thin client: 60 FPS pygame loop + touch scrubber) *and* (b) an **animated web
>   preview** (test/parent UI) — because animation and touch only exist at a *live* renderer,
>   never in the frozen PNG we ship today.
> - **Authoring = segment orchestrator.** On earned-visual turns the brain runs the
>   **LLM-master segment loop** (interleave *say + draw + animate* across N segments, pick the
>   routing-table tool per concept, default animation ON where the idea moves), not today's
>   single conservative author call.
>
> This document is scoped to **`cloud_run_service/`** (the deployed Cloud Run brain). It
> reuses the already-built device + orchestrator code from `cloud_workspace_v8/` (built &
> screenshot-verified on winipi5 2026-07-29) rather than reinventing it.

---

## 1. Where we are today (grounded in the code)

**The Cloud Run brain authors rich payloads but flattens them to a static image, and has no
segment loop.** Current path in `tutor_loop.py` → `response_layer/`:

1. `_response_layer()` plans a `TeachingScript`; the Visual Benefit Gate earns a visual
   (`validator.py`, `visual_gate.py`).
2. `compilers._compile_board_buddy()` → `board_buddy_author.author_board_from_answer()`:
   **ONE** structured Gemini call reads the finished answer and emits a Board Buddy payload.
   The full tool vocabulary *is* available to it (`board_buddy_caps.TOOL_SCHEMAS`, all 8
   tools) and the deterministic **belt** (`validate_board_call`) grounds every quantity.
3. `board_buddy_renderer.render_board_payload()` calls `canvas.render()` **once, at the
   final frame** → base64 **static PNG** data URL, attached as
   `rl_visual["rendered_board_data_url"]` and returned to the client in the turn's `visual`
   directive (`tutor_loop.py:2957`, surfaced at `:3028`).

### What that means feature-by-feature

| Feature | Authored? | Delivered to the child today? |
|---|---|---|
| `text` (auto-LaTeX) | ✅ | ✅ static PNG |
| `stickers` (1D/2D) | ✅ | ✅ static PNG |
| `geometry` | ✅ | ✅ static PNG |
| `graph` (y=f(x)) | ✅ | ✅ static PNG |
| `numberline` hops | ✅ | ✅ static PNG (final frame) |
| `fraction` (bar/grid) | ✅ | ✅ static PNG |
| **`animate_param` / `animation`** | ✅ authored | ❌ **frozen final frame** — no 60 FPS playback |
| **touch time-scrubber** | n/a | ❌ **absent** on the server-PNG path |
| **segment loop** (say+draw+animate interleaved) | ❌ | ❌ not in `cloud_run_service` |

### The divergence

The **full interactive path already exists** — but only in `cloud_workspace_v8/`:

- `response_layer/board_buddy_orchestrator.py` — the LLM segment loop (`BoardSegmentOrchestrator`
  + `vertex_segment_decider`).
- `response_layer/device_runner.py` — emits `board_open` / `board` / `board_close` around a
  beat, never revealing past an open child.
- `wini_client/board_buddy_player.py` + `board_buddy_sink.py` — the live pygame child surface
  (60 FPS + scrubber, matplotlib prewarm) and its parent-side sink, LVGL parent lifecycle.

**`cloud_run_service/response_layer/` is missing the orchestrator and device_runner.** It only
has `board_buddy_author.py`, `board_buddy_caps.py`, `board_buddy_compile.py`, `compilers.py`.
So the deployed brain is stuck on Mode A (static PNG); the interactive Mode B lives in the
other tree. This plan closes that gap.

---

## 2. Target experience — what "use all features" means

A visual teaching turn should feel like a tutor at a smart whiteboard, not a slide:

- **Right tool per concept**, driven by `board_buddy_caps.TOOL_ROUTING`:
  counting → `stickers`; add/subtract → `numberline` hops; fractions → `fraction`
  bar/grid; quadratics/plots → `graph`; shapes/angles → `geometry`; formula/steps →
  `text`; *a value that changes/grows* → `animate_param`.
- **Animation is the default, not the exception, whenever the idea moves**: a parabola
  morphing as `a` changes, a hop arc growing 1→5 on the number line, a fraction grid filling
  row by row, a ball hopping between two counting groups. Board Buddy's whole point is the
  60 FPS `{var}` morph — a static render throws away its best asset.
- **Touch is a first-class review affordance**: the child scrubs the bubbly time-scrubber
  (Y 800–845) to replay any state 0→T_max and *verify a step before answering*
  (Integration Guide §1 Option A). The brain's segment loop pauses for that interaction on
  the beats where checking matters.
- **Say + draw are one act**: the same LLM segment that speaks also draws, so the picture
  matches the words by construction; the belt still drops any ungrounded number.

---

## 3. Architecture

### 3.1 Brain-side authoring — the segment orchestrator becomes the engine

Port `board_buddy_orchestrator.py` and `device_runner.py` from `cloud_workspace_v8/` into
`cloud_run_service/response_layer/`, then make the segment loop the **authoring path for
earned-visual turns** (plain Q&A/social/admin keep the Part-13 single-call streamed path —
latency guardrail, §6.3 of the integration plan).

Per segment the LLM (`vertex_segment_decider`) returns `{speech?, board_call?, done?}`; the
loop:
- runs each `board_call` through the belt grounded on **everything spoken so far + this
  segment's speech**,
- emits `board_open` (first draw) → `board` (payload + `tmax` + `animated`) → interleaved
  `speak`,
- waits for the device ack for **both** modalities before the next decision,
- closes with `board_close`.

Two authoring upgrades so it truly exercises every tool:

1. **Animation-forward decider prompt.** Extend `_segment_prompt` so that when the concept
   has a value that changes/grows/moves, the model **must** include an `animate_param` (or
   spatial `animation`) with the `{var}` placeholder written into the target
   element's `text`/`equation`/`title`/`hops`. `_brace_animated_vars` (already in
   `board_buddy_author`) fixes bare-var mistakes; extend it to numberline `hops` and text.
2. **Coverage-aware routing.** Feed the decider the concept family so it opens with the
   routing-table tool, and let it add a `text` takeaway band + a conceptual `stickers` badge
   (the 3-beat layout already scaffolded in `_author_prompt`). Keep the ≤12-element and
   ≤4-board-call budgets.

**Fallback preserved:** if the orchestrator declines/errs, fall back to the single-call
`author_board_from_answer` (unchanged), then to the scene→payload translator
(`board_buddy_compile`), then to crop/formula-text. A drawing failure never costs a turn.

### 3.2 Delivery — one payload, two live renderers

The payload (per-segment list of elements + `tmax` + `animated`) is the single source of
truth. It is delivered two ways:

**(A) Live device surface (Pi now, ESP32-P4 later).**
- `wini_server.py` emits the segment verbs on `turn_meta`:
  `{"cmd":"board_open"}`, `{"cmd":"board","payload":[...],"tmax":…,"animated":bool}`,
  `{"cmd":"speak","text":…}`, `{"cmd":"board_close"}`.
- The device runs the **already-built** `wini_client/board_buddy_player.py` +
  `board_buddy_sink.py`: native 60 FPS loop, `{var}` morph over `T_max`, the touch scrubber,
  and the LVGL parent controls in the 845–1024 strip. Acks each segment back to the brain
  (`ready` / `animation_done` / `interrupt`) so the loop is conversational within a turn.
- ESP32-P4 profile keeps `supports_board_buddy=False` → validator degrades to crop/text
  (already wired in `device_profile.py` / `ESP32_P4_PROFILE`).

**(B) Animated web preview (test/parent UI).**
- Replace the frozen `render_board_payload()` single-frame call with an **animated export**:
  render N frames across `0→T_max` (`canvas.render(anim_progress=t/T_max)`) and encode an
  **APNG/GIF** data URL. This gives the preview real animation (no touch).
- For animation **+ touch in the browser**, add an optional **client-side JS Board Buddy
  player** that consumes the same JSON payload and reimplements the scrubber. Larger effort;
  stage it behind a flag after the APNG path lands.
- Keep the `/board/render` POST endpoint but add `?mode=animated` (APNG) alongside the
  existing static PNG so debugging still works.

```
                      earned-visual turn
                            │
                 BoardSegmentOrchestrator (brain)   ← authoring engine (ported)
                  belt-grounded per segment
                            │  payload + tmax + animated
             ┌──────────────┴───────────────┐
             ▼                              ▼
   (A) turn_meta verbs             (B) render_board_payload(animated=True)
   board_open/board/speak/close        → APNG/GIF data URL   (+ optional JS player)
             │                              │
   device: board_buddy_player          web: <img>/<video> or JS scrubber
   60 FPS + touch scrubber
```

---

## 4. Phased work plan

### Phase A — port the interactive engine into `cloud_run_service` (brain-side) — ✅ DONE (2026-08-01)
1. Copy `board_buddy_orchestrator.py` and `device_runner.py` from
   `cloud_workspace_v8/response_layer/` into `cloud_run_service/response_layer/`; reconcile
   imports against this tree's `board_buddy_author` (the two authors differ — diff and keep
   this tree's belt behavior). Add them to `__init__.py` lazy re-exports.
2. Confirm `device_profile.py` here already carries `supports_board_buddy` /
   `board_buddy_tools` / `board_buddy_sticker_names` (it does in workspace_v8 — verify parity).
3. **Exit:** `python -m response_layer.test_board_buddy` (port the 22-test suite) green here,
   headless, no hardware.

### Phase B — make the orchestrator the authoring path for earned-visual turns — ✅ DONE (2026-08-01)

**Built (flag-gated `WINI_BB_ORCHESTRATOR`, default OFF):**
- Animation-forward prompts: `board_buddy_author._author_prompt` now teaches the graph
  `{a}`, numberline `['{hop:int}']`, and fraction `['{r:int}', cols]` animation patterns;
  `board_buddy_orchestrator._segment_prompt` gained the same "ANIMATE whenever the idea
  moves" rule.
- `board_buddy_author._clean_hops` normalizes a bare animated-var hop (`"hop"`) to the
  placeholder `"{hop:int}"` so the arc animates instead of being dropped.
- `board_buddy_orchestrator.author_board_orchestrated(answer, profile, ...)` — runs the
  segment loop in-process (default no-device seams) with `ground_seed=answer` so every board
  frame is belt-grounded against the WHOLE finished answer; returns
  `{segments:[{payload,tmax,animated,speech}], merged, tmax, animated}`.
- `compilers._compile_board_buddy` prefers the orchestrated author when the flag is on
  (segments + merged), else the single author (now emitting a one-element `segments` list too).
- **Scope note:** this keeps the proven Part-13 streamed-answer path as the turn's SPEECH; the
  orchestrator is the board-AUTHORING engine, not a master-clock replacement for generation.
  The full "LLM master clock replaces streamed generation with live per-segment speech+ack"
  model is deliberately deferred — it would rewrite the streamed turn and needs a conversational
  within-turn wire protocol this service does not yet have. See §6 risks.
- Tests: `response_layer.test_board_buddy` now **28/28** (added bare-var hop + orchestrated
  authoring merge/ungrounded cases).

### Phase B — original design (superseded by the DONE note above)
1. In `tutor_loop._response_layer` / the compile seam, route an **earned-visual EXPLAIN /
   representation-gap turn** through `BoardSegmentOrchestrator` instead of the single
   `_compile_board_buddy` call. Keep the single-call author as the fallback.
2. Strengthen `_segment_prompt` (§3.1): animation-forward rule + concept-family routing +
   the 3-beat layout (header/badge, main visual, takeaway). Extend `_brace_animated_vars` to
   cover `numberline.hops` and `text`.
3. Preserve the latency guardrail: plain turns keep the Part-13 single-call streamed path;
   the loop only runs when a visual is earned. Budget ≤6 segments / ≤4 board calls.
4. **Exit:** a scripted visual turn produces `board_open → (board|speak)* → board_close`
   with grounded, animated payloads and correct acks, offline.

### Phase C — dual delivery — ✅ DONE brain-side (2026-08-01); live-device bring-up pending

**Built:**
- `board_buddy_renderer.render_board_payload_animated(payload, fps=12, ...)` — renders frames
  across `0..T_max` via `canvas.render(anim_progress)` and encodes a full-colour **APNG** data
  URL that plays in a plain `<img>`. A static payload returns `None` (caller keeps the cheaper
  single frame). Smoke-verified: a 2 s parabola morph → ~325 KB APNG.
- `tutor_loop` compile seam: an animated board renders to the APNG (falls back to the static
  frame on any failure) and now carries `board_payload` / `board_segments` / `board_tmax` /
  `board_animated` on the visual directive so a LIVE surface can play it. Rides `turn_meta`
  unchanged (no extra server wiring — it is already on `result["visual"]`).
- `wini_server` `/board/render?mode=animated` (also `mode` in the JSON body) returns the APNG,
  with a static-frame fallback; response includes `"animated": bool`.
- **Web preview (B):** the APNG gives real animation now. Browser animation **+ touch** (a JS
  Board Buddy player consuming the same JSON payload) remains the stretch item.
- **Live device surface (A):** the payload + segments now ride `turn_meta`; the device player
  (`wini_client/board_buddy_player.py`, already built) plays them with the 60 FPS loop + touch
  scrubber. End-to-end live bring-up (emit the verbs on a real mic turn, device ack round-trip)
  is the remaining hardware step.

### Phase C — original design (superseded by the DONE note above)
1. **Live surface (A):** `wini_server.py` emits the segment verbs on `turn_meta`; wire the
   device ack round-trip (extend the existing streaming meta path). The device player/sink
   already exist — this is the brain-side emit + ack plumbing.
2. **Web preview (B):** upgrade `board_buddy_renderer.py` with
   `render_board_payload_animated(payload, fps=…, loop=…) -> APNG/GIF data URL`; call it in
   the compile seam in place of the single-frame render; add `/board/render?mode=animated`.
3. (Stretch) client-side JS Board Buddy player for browser animation **+** touch.
4. **Exit:** on winipi5 a live EXPLAIN turn animates in-region with a working scrubber and
   parent controls; the web preview shows the same turn animating.

### Phase D — coverage eval + guardrails — ✅ DONE (2026-08-01)

**Built:** `response_layer/eval_board_coverage.py` — `python -m response_layer.eval_board_coverage`
(offline, no Vertex) proves every tool family (stickers, numberline, fraction, graph, geometry,
text, animate_param) survives the belt when GROUNDED and is DROPPED when not — zero ungrounded
leaks. `--live [--orchestrator]` runs the real author over each concept and checks the
routing-table tool was picked + animation fired on moving concepts (billed). Offline run:
**all 7 tools covered, 0 leaks.** Tests now **30/30**.

**Local live verification (laptop, wini_commands_guide.md):** started `wini_server.py --port 8123`
(`GEN_BACKEND=gemini WINI_RESPONSE_LAYER=1`), ran real `/turn`s, rendered + screenshotted boards.
Findings + fixes:
- Boards render and are mathematically correct (parabola crosses the right roots, etc.).
- **Animation + touch confirmed on the real canvas:** a grounded `{a}` parabola-morph renders
  a=1→3 (curve visibly steepens, auto-title tracks "1x²"→"3x²") WITH the touch time-scrubber
  bar present and advancing (0.0s→2.5s). The animated APNG path (web preview) also verified.
- **Live-render defects found → fixed belt-side** (BB is frozen; fix the author, never BB):
  the model wrapped text/titles in `$$..$$`, used `\text{}` and unicode `−`/`×` glyphs (rendered
  as raw source / tofu boxes), and left graphs untitled (BB then mathmode-auto-titles
  "Graph of <equation>" → fused prose + literal `*`). Added `board_buddy_author._sanitize_math_text`
  (strips `$$`/`$`, unwraps `\text{}`/`\mathrm{}`, drops "Graph of" prose, maps amsmath arrows +
  unicode maths, turns ` * ` into implicit mult) applied to every `text`/`title` DISPLAY string
  (never the graph `equation`, which BB parses), and a clean default graph title. Re-render
  verified: titles + step lines now render as proper LaTeX.
- **Known limitation (not a bug in our code):** a `text` element that mixes a PROSE sentence with
  a maths symbol (`^`) still fuses spaces — matplotlib mathmode ignores spaces. Mitigated by
  authoring guidance ("text = short label or bare formula, never a sentence with a formula"); a
  full fix needs a device-side renderer patch.
- **Animation rarely fires on real curriculum turns:** the board is grounded on the ANSWER, and
  Class-10 answers describe static figures, not motion, so no `animate_param`. The capability is
  proven; eliciting it live needs answers that describe a changing value (or the orchestrator).

### Phase D — original design (superseded by the DONE note above)
1. Extend `BOARD_BUDDY_INTEGRATION_EVAL_PLAN.md` with a **tool-coverage eval**: a fixed set
   of concept prompts (counting, add/subtract, fractions, quadratic, geometry, a
   growing/changing value) must each trigger the routing-table tool AND, for the moving
   concepts, a grounded `animate_param`. Assert via the `board_buddy_validate` /
   `response_compile` debug events (`tools_used`, `stickers_used`, `animated`).
2. Assert the grounding invariant holds end-to-end: no ungrounded number/count/hop survives
   the belt on any eval prompt (the "visuals must be text-aware" mandate).
3. **Exit:** coverage report shows every tool exercised on its concept and animation firing
   on moving concepts, with zero ungrounded values.

---

### Phase E — cue-driven animation + real-life-example routing — ✅ DONE + LIVE-VERIFIED (2026-08-01)

The reason animation/stickers rarely fired (Phase D finding): the board is grounded on the
ANSWER, and a curriculum answer describes static figures. Fix = detect the intent at the CUE,
steer the ANSWER (motion / countable objects), then the board grounds the animate_param /
stickers from it. Structural chain: **cue → policy flag → answer prompt → response context →
board author.**

- `cognitive_classifier/cues.py`: two new STANDALONE runtime cues (no feature-vector rebuild):
  `is_animation_request` (animate / real-time / "as a grows" / "watch it change") and
  `is_real_life_request` (real-life/everyday/practical example, "where is this used").
- `tutor_loop.py`: derives `wants_animation` / `wants_real_life`, folds both into `wants_visual`
  (so a board is earned); passes `animate` / `real_life` to `qwen_answer`, which injects a
  **motion cue** (name the ONE changing value + its from/to) or a **real-life cue** (invent a
  small-count everyday-object scene, no textbook figure); suppresses the "look at Fig X"
  screen-cue on these authored-board turns.
- `contracts.ResponseContext` + `adapter` carry `wants_animation` / `wants_real_life`;
  `compilers.compile_response` → `_compile_board_buddy` → `author_board_from_answer` /
  `author_board_orchestrated` take `want_animation` / `want_real_life` and inject an authoring
  directive (force `animate_param` / lead with real-object `stickers`).
- **Reliability net:** `board_buddy_author.stickers_from_answer` — deterministic real-life
  fallback that draws the first "<n> <object>" (n 1–12, object a library sticker or synonym,
  both grounded in the answer) as stickers + a label, used when the author's 2nd Gemini call
  returns nothing. `_STICKER_SYNONYMS` maps common kid words (marble→ball, crayon→pencil…).
- **Live-verified (laptop, billed /turn):** "…animation how y = a x² changes as a grows from 1
  to 3" → answer describes the motion → board `animate_param a:1→3`, animated APNG + touch
  scrubber. "real life example … objects I can count" → answer uses small countable objects →
  stickers board (6 balls / 5 coins / 7 pencils), **3/3 reliable** with the fallback. Tests
  **32/32**.

## 5. Invariants this plan does NOT break

- **Text-aware grounding (hard mandate).** Every number/count/hop/numerator on the board is
  grounded against the spoken answer by `validate_board_call`; the LLM extracts, the belt
  drops off-spec. Animation ranges (`from`/`to`) are grounded too.
- **LLMs plan, deterministic systems render/lay-out.** The belt clamps positions, seats
  labels, picks canonical vertices, defaults LaTeX-safe colors.
- **Single-writer learner state.** The response layer stays planning/validation only; state
  moves once at turn close.
- **Latency on the common case.** The segment loop runs only on earned-visual turns; plain
  Q&A keeps the Part-13 single-call streamed path.
- **Device capability subset.** `allowed_tools_for_profile` / `supports_board_buddy` honor a
  device that ships fewer tools; ESP32 degrades to crop/text.
- **Board Buddy is frozen v1.0.** All adaptation lives in our modules; `MANIFEST_VERSION`
  records the deployed renderer.

---

## 6. Risks / open items

- **Latency of the segment loop** (multiple LLM calls + device acks per turn). Mitigate with
  the ≤4 board-call budget, running only on earned-visual turns, and keeping speech dynamic
  (never clamped to `T_max`).
- **Two-tree reconciliation.** `board_buddy_author.py` differs between `cloud_run_service` and
  `cloud_workspace_v8`; the port must keep *this* tree's belt behavior. Diff before copying.
- **APNG/GIF weight.** Many frames of a LaTeX-heavy board are large; cap fps (e.g. 12–15) and
  frame count, reuse the matplotlib prewarm, and prefer APNG for quality/size.
- **Touch on the web** needs the JS player (stretch); the APNG preview gives animation but
  not scrubbing — acceptable as the first web step.
- **Cloud Run deploy sequencing.** Brain (authoring + verbs) must be serving before the live
  client relies on it (`WINI_RESPONSE_LAYER` + `WINI_BOARD_BUDDY` flags).

---

## 7. Lockstep / doc propagation

This plan sits under the Board Buddy integration doc set. On implementation, update:
`BOARD_BUDDY_INTEGRATION_PLAN.md` §11 build status, `BOARD_BUDDY_INTEGRATION_EVAL_PLAN.md`
(coverage eval), and the memory note `board-buddy-integration` with the cloud_run_service
port + dual-delivery state. Re-measure any latency/coverage number before writing it into a
doc.
