# Board Buddy ↔ Response Layer — Integration Eval Plan

> Companion to `BOARD_BUDDY_INTEGRATION_PLAN.md`. Defines **how we prove the integration
> works — on the real winipi5 screen**, not only in unit tests.
> **Principle:** every layer gets an **offline gate** (fast, deterministic, CI) AND an
> **on-device on-screen gate** (real panel, real pixels, real touch). A change ships only
> when both are green. The device gate is the one that matters most here, because the whole
> point of this integration is *what the child sees and touches on the 600×1024 panel*.

---

## 0. What "directly test on screen" means here

Board Buddy itself is already unit-tested; we are **not** re-testing its rendering fidelity.
We are testing the **integration**: that the brain's LLM-orchestrated segment loop drives
the **right tool, with grounded values, in the right screen region, at the right time,
under LVGL's parentage**, and that the child can pause/scrub/close it.

So the on-screen gate captures the **actual framebuffer** with `grim` (Wayland; memory
`winipi5-wayland-migration` — grim, not scrot), drives **real touch** with `uinput`
(not wlrctl), records audio timing, and cross-checks each screenshot against the exact
payload the brain sent. Objective checks, not "looks right".

Three ground-truth streams are captured for every on-screen test and correlated by
timestamp:
1. **Brain event log** — every segment decision + `board_open/board/board_close/speech`
   verb and the exact `draw_board` payload sent (the *intent*).
2. **Screenshots** (`grim`) at defined sync points (the *result*).
3. **Device event log + audio markers** — segment acks, speech start/stop, touch events.

---

## 1. Test environment & harness

### 1.1 Devices / processes
- **winipi5** (Waveshare 7" DSI, portrait **600×1024**, labwc/Wayland, py-3.12). Reached
  over SSH (mDNS `ubuntu.local`; IP drifts — memory `jetson-wifi-provisioning`).
- **Brain**: Cloud Run brain (or a local brain on a laptop for pre-cloud phases) — it holds
  the response layer + orchestration loop and needs Vertex.
- **Device stack**: `run_wini_package.sh` launches the client + LVGL `wini_ui`; Board Buddy
  is spawned by LVGL on `board_open`. Wayland env via `display_env.sh` (memory).

### 1.2 Harness pieces to build (under `tools/` + `eval/`)
| Harness | Purpose |
|---|---|
| `tools/bb_turn_driver.py` | Inject a **fixed transcript** into a turn (mic-free) so a scenario is deterministic and repeatable — the mic-free UI-driver pattern (memory `production-fixes-2026-07-16`). Drives one turn, waits for `board_close`. |
| `tools/bb_screencap.py` | SSH + `grim` a PNG at a named sync point; pull to the laptop; tag `{scenario, segment, phase}`. |
| `tools/bb_touch.py` | Synthesize touch via `uinput` at panel coords (scrubber taps/drags, control-button taps). |
| `eval/bb_regions.py` | Crop a screenshot into `R_board` (0–845 or 0–800), `R_scrubber` (800–845), `R_controls` (845–1024); non-blank / change / OCR / perceptual-hash checks. |
| `eval/bb_eval.py` | Orchestrate a scenario: drive turn → capture at each sync point → run region + log correlation asserts → emit a scorecard row. |
| `eval/bb_scenarios.json` | The scenario fixtures (§10): transcript, expected tool, expected grounded values, segment pattern. |

### 1.3 Sync points captured per turn
`pre_open` (before any visual) → `board_open` (surface up, blank/settling) → per segment
`board_settled_k` (animation of segment *k* at 100%) and, for animated payloads,
`board_mid_k` (~50% progress) → `speech_k_start/end` markers → `board_close` (surface gone,
LVGL card restored).

---

## 2. Eval levels (map to the integration plan)

| Level | Where | Gate | Covers plan § |
|---|---|---|---|
| **L1** Brain-side offline | laptop/CI, headless | automated | §10.1 belt, §10.2 loop, §6.4 grounding |
| **L2** Device surface | winipi5, on screen | on-device | §6.1 surface/exclusivity/touch/lifecycle |
| **L3** End-to-end scenarios | winipi5, on screen | on-device | §3.2 flow, §10.2 sync, §10.1 routing |
| **L4** Robustness / failure | winipi5, on screen | on-device | §6.1 crash, §6.4 grounding, §6.8 self-heal, §6.9 degrade |
| **L5** Regression / performance | both | automated + on-device | §6.3 Part-13 latency, budgets |

---

## 3. L1 — Brain-side offline evals (no screen; must pass before any device time)

Pure-function gates on the orchestration + belt, mirroring `response_layer/test_*`.

- **L1.1 Tool-schema validity.** Every `draw_board` payload the belt emits validates
  against the Board Buddy capability manifest (§10.1): known `type`, required params
  present, `pos` within `0≤x≤580, 0≤y≤780`, size presets valid, `{var}` syntax well-formed.
  Fuzz 500 model-shaped payloads incl. malformed → belt drops off-spec elements, never
  raises, never forwards an invalid element.
- **L1.2 Grounding.** For a corpus of (answer, payload) pairs, **no** number/count/hop/
  numerator on the board is absent from the answer's number set (`_ground_lines` /
  `_answer_number_set`). Adversarial: a hallucinated coefficient/count must be dropped.
  **Target: 0 ungrounded values forwarded.**
- **L1.3 Pedagogical tool routing.** For labelled concept/answer fixtures the chosen tool
  matches the expected class (counting→`stickers`, add/sub→`numberline`, fractions→
  `fraction`, quadratic→`graph`, formula/def→`text`, shape→`geometry`). **Target ≥ 0.9**
  top-1 on the routing fixture set.
- **L1.4 Segment loop shape.** Given scripted LLM decisions, the loop emits a well-formed
  `board_open → (board|speech)* → board_close`, honors the segment budget, gates only
  earned-visual turns, and consumes device acks in order (mock device). Non-visual turns
  emit **no** board verbs (Part-13 path untouched).
- **L1.5 Determinism.** `temperature=0` extraction + deterministic layout ⇒ identical
  payload for identical (answer, ctx). Snapshot/golden the payloads.

---

## 4. L2 — Device surface evals (ON SCREEN — the core of this plan)

Runs on winipi5 with a **static, hardcoded** Board Buddy payload (no brain LLM), so we
isolate the *surface/lifecycle* behaviour from authoring.

- **L2.1 Spawn & position.** On `board_open`, `grim` shows Board Buddy occupying **exactly**
  the top region: `R_board` = [0:600, 0:H] where H=800 (static) or 845 (animated). Assert
  `R_board` non-blank; assert rows **below** the BB region belong to LVGL (control strip).
  **Pass:** BB top-left at (0,0), width 600, height 800/845 ± a few px.
- **L2.2 Exclusivity (LVGL must not fight).** While BB is up, drive an event that would
  normally write the LVGL figure card (e.g. a `figure` cmd). Assert **no** card artifact
  appears in `R_board` (client `board_active` flag suppresses it — verified in the device
  log AND by `R_board` matching the BB-only golden). **Pass:** 0 card bleed into 0–845.
- **L2.3 Control strip present & persistent.** `R_controls` (845–1024) shows the
  pause/stop/mute/close bar throughout the BB session (non-blank, stable across sync
  points). **Pass:** all four controls detectable (template-match or OCR labels).
- **L2.4 Teardown & restore.** On `board_close`, `grim` shows BB gone and the **LVGL
  figure card / normal UI restored** in 0–845; `board_active` cleared in the log.
  **Pass:** post-close screenshot ≈ pre-open baseline (perceptual-hash within tolerance).
- **L2.5 Wayland co-existence (top device risk, §6.1).** Both surfaces (LVGL app + BB
  pygame) present simultaneously under labwc with correct stacking/geometry across an
  open→close→open cycle. **Pass:** no z-order flip, no black/again-blank BB region, 3/3
  cycles clean.
- **L2.6 Touch routing (top device risk, §6.1).** `uinput` tap in the **scrubber** band
  (y∈[800,845]) → BB frame changes (compare `R_board` before/after — the scrub moves the
  animation); `uinput` tap on a **control** (y>845) → the mapped action fires (close tears
  BB down). Cross taps must NOT leak to the wrong surface. **Pass:** scrubber tap only
  scrubs, control tap only controls; 0 mis-routed.
- **L2.7 Crash safety.** Kill the BB subprocess mid-session. **Pass:** LVGL parent survives,
  restores the card, and the turn degrades to the crop/formula-text fallback (§6.9);
  no frozen/blank panel.

---

## 5. L3 — End-to-end scenario evals (ON SCREEN — brain in the loop)

Full path: `bb_turn_driver` injects a transcript → brain runs the segment loop → winipi5
renders → capture + verify. One row per scenario in `eval/bb_scenarios.json`.

### 5.1 Concept-coverage scenarios (one per Board Buddy tool)
| # | Injected turn | Expected tool | On-screen assert |
|---|---|---|---|
| S1 | "count 5 apples with me" | `stickers` count 5 | OCR/template: 5 apple icons in `R_board` |
| S2 | "what is 3 + 5 on a number line" | `numberline` hops 3,5 | number line + 2 hop arcs; labels 3,5,8 |
| S3 | "show 2/3 × 3/4 as an area model" | `fraction` 2D grid | 3×4 grid, 6 filled cells |
| S4 | "why does x²−5x+6 make a parabola" | `graph` parabola | U-curve; roots at x=2,3 marked |
| S5 | "write the quadratic formula" | `text` LaTeX | formula text renders (auto-LaTeX) |
| S6 | "show a right triangle" | `geometry` right_triangle | triangle + right-angle marker |

Each: assert the **sent payload** used the expected tool (brain log) AND `R_board` is
non-blank + matches the scenario golden (perceptual hash, tolerant) AND OCR-grounding
holds (§7).

### 5.2 Segment-pattern scenarios (the LLM-as-master model, §10.2)
- **P1 board-only segment** then **speech-only segment** then **board+speech segment** —
  assert the device executed exactly that pattern (verbs + acks in the device log), and a
  screenshot at each segment matches the segment's intent.
- **P2 interleave / step-build**: multi-segment turn where each `board` call adds a step
  (e.g. reveal roots after the curve). Assert `R_board` **changes** between
  `board_settled_k` and `board_settled_{k+1}` (region diff > threshold) — the visual grows
  with the teaching.
- **P3 speech-then-decide**: a segment whose `board` waits for the prior segment's speech
  to finish before the next `board` — assert the next `board` verb timestamp > prior
  `speech_end` (the "wait for speech to complete, then LLM decides again" contract).

### 5.3 Sync assertions (per segment)
- **Alignment:** `board_settled_k` occurs within the same segment window as `speech_k`
  (no visual for step k+1 while step k is being spoken). Measured from correlated logs +
  screenshot timestamps.
- **No runaway:** the visual never advances past the segment the LLM has committed (Board
  Buddy is a pure executor — it doesn't free-run ahead of the brain).
- **Speech stays dynamic:** speech length is not clamped to `T_max` (a long answer isn't
  cut when the animation ends) — assert speech_end can exceed animation_end.

---

## 6. L4 — Robustness & failure evals (ON SCREEN)

- **L4.1 Off-spec self-heal (§6.8).** Force the brain to emit a payload with one unknown
  element type. Assert Board Buddy renders the valid elements, returns `partial_success`
  with a warning, and the brain logs the warning (no crash, no blank). Screen shows the
  valid elements only.
- **L4.2 Ungrounded value blocked on screen (§6.4).** Craft an answer+payload where the
  model tries to put a number the answer never stated. Assert (a) belt drops it (L1.2) and
  (b) **OCR of `R_board` contains no ungrounded number** — grounding proven on the actual
  pixels, not just in code (§7).
- **L4.3 Barge-in (§6.3).** During a segment, inject a learner interrupt. Assert speech
  ducks/pauses, BB loop pauses, the loop re-enters the brain, and on "resume" the same
  segment continues (screenshot before/after interrupt match). On "stop", `board_close`
  fires and the card restores.
- **L4.4 Parent controls under load.** Tap **pause** mid-animation → BB freezes (two
  screenshots 1s apart identical); **close** → teardown (L2.4); **mute** → audio stops but
  visual continues; **stop** → whole turn ends cleanly.
- **L4.5 Degradation path (§6.9).** Run with `supports_board_buddy=False` in the device
  profile. Assert **no** BB surface appears and the turn falls back to the T9 crop /
  formula-text on the normal LVGL card — the ESP32-shaped path works today on the Pi.
- **L4.6 BB-unavailable / spawn fail.** Simulate BB binary missing. Assert graceful
  fallback (as L4.5), parent UI intact, one clear log line.

---

## 7. On-screen grounding via OCR (the strongest "test on the screen" check)

Grounding is the hard mandate; verify it **on the rendered pixels**, not only in the belt:
1. `grim` the settled `R_board`.
2. OCR it (tesseract) → the set of numbers/tokens actually visible on the board.
3. Cross-check against the turn's answer number set (`scene_author._answer_number_set`).
4. **Assert:** every multi-digit number visible on the board ⊆ the answer's numbers
   (single-digit structural constants exempted, matching `_ground_lines`).

This catches a class the offline belt can't: a value that slips through *and* actually
renders. Run it on S1–S6 and L4.2. **Target: 0 ungrounded numbers on screen across the
suite.**

---

## 8. L5 — Regression & performance

- **L5.1 Part-13 preserved (§6.3).** For a set of **non-visual** turns (plain Q&A, social,
  admin), assert the brain emits **no** board verbs and TTFA/latency match the pre-
  integration baseline within tolerance (memory `part13-streaming-built`: TTFA ~3.3–4.4s).
  **Pass:** no regression on the common case.
- **L5.2 Segment-loop latency budget.** Measure added latency per visual turn = Σ(extra LLM
  segment calls + device ack round-trips). Report p50/p95 vs segment count. **Guardrail:**
  within the agreed budget (segment cap, §8 Q; suggest ≤4 board calls/turn).
- **L5.3 Render latency on the Pi.** Per-segment `load_json`+first-frame time on winipi5,
  incl. matplotlib LaTeX (§6.6). Confirm prewarm removes the first-call spike. **Report**
  p50/p95; flag if a segment exceeds a child-attention threshold (~1.5s to first visible).
- **L5.4 Soak / lifecycle churn.** 50 open→close cycles across mixed scenarios: no surface
  leak, no zombie BB process, no compositor z-order drift, memory flat (§6.1, L2.5).

---

## 9. Metrics & pass/fail summary

| Metric | How measured | Pass threshold |
|---|---|---|
| Tool-schema validity | L1.1 fuzz | 100% valid or dropped; 0 invalid forwarded |
| Ungrounded values (offline) | L1.2 | 0 forwarded |
| Ungrounded numbers on screen | L7 OCR | 0 across suite |
| Tool routing top-1 | L1.3 | ≥ 0.90 |
| Surface position/exclusivity | L2.1–2.4 | 0 bleed into 0–845; restore ≈ baseline |
| Touch routing correctness | L2.6 | 0 mis-routed taps |
| Wayland co-existence | L2.5 / L5.4 | 3/3 clean; 50/50 soak clean |
| Concept coverage | L3 S1–S6 | 6/6 correct tool + golden + grounding |
| Segment pattern fidelity | L3 P1–P3 | verbs/acks match intent 100% |
| Sync alignment | L3 §5.3 | visual step k within speech-k window; no runaway |
| Barge-in / controls | L4.3–4.4 | all actions correct, panel never frozen/blank |
| Degradation | L4.5–4.6 | fallback works, parent intact |
| Part-13 non-visual latency | L5.1 | within baseline tolerance |
| Visual-turn added latency | L5.2 | within segment budget |
| First-visible latency | L5.3 | p95 under threshold |

---

## 10. Test fixtures (`eval/bb_scenarios.json`)

Each scenario: `{ id, injected_transcript, expected_tool, expected_grounded_values,
segment_pattern, golden_image, notes }`. Seed with S1–S6 + P1–P3 + the L4 adversarial
cases. Goldens captured once from an approved run and version-controlled (small PNGs of
`R_board`); comparisons use perceptual hash with a tolerance so anti-aliasing/font jitter
doesn't flap.

---

## 11. Execution flow (per CI + per device run)

**Offline (CI, every change):** L1 + L5.1. Fast, blocks merge.

**On-device (winipi5, per integration milestone):**
```
1. ssh winipi5; ./display_env.sh; ./run_wini_package.sh   (brain URL configured)
2. eval/bb_eval.py --level L2                 # surface/lifecycle, static payloads
3. eval/bb_eval.py --level L3 --scenarios all # end-to-end, brain in loop
4. eval/bb_eval.py --level L4                 # robustness/failure
5. eval/bb_eval.py --perf                     # L5.2–5.4
   -> each writes screenshots + a scorecard row + a pass/fail; artifacts pulled to laptop
```
Every on-device run archives: screenshots per sync point, brain event log, device log,
audio markers, and the scorecard — so a failure is diagnosable from artifacts alone.

---

## 12. Phase gates (tie eval to the build phases in the integration plan §7)

| Build phase | Eval gate to pass |
|---|---|
| Phase 1 (manifest + belt) | L1.1–L1.3, L1.5 |
| Phase 2 (brain orchestration loop) | L1.4 + L5.1 (mock device) |
| Phase 3 (device separate surface) | **L2 + L3 + L4 + L5.3–5.4 on winipi5** ← the real gate |
| Phase 4 (cloud + ESP32) | re-run L3 against the Cloud Run brain; L4.5 for the ESP32 profile |

**Sign-off:** the integration is "done" when Phase-3 on-screen gates (L2–L4) are green on
winipi5 for all S1–S6 + P1–P3 scenarios, OCR-grounding is 0 ungrounded across the suite,
the 50-cycle soak is clean, and non-visual turns show no latency regression.

---

## 13. Open items this eval plan assumes (confirm alongside §8 of the integration plan)

- The **segment budget** number (drives L5.2 threshold).
- Whether the loop runs **only on earned-visual turns** (drives L5.1 scope).
- Which **Board Buddy tools ship first** (drives which of S1–S6 are in the first gate vs
  deferred).
- Availability of **tesseract** on the harness host for the OCR grounding check (§7) — if
  not, substitute template-matching against per-scenario goldens.
