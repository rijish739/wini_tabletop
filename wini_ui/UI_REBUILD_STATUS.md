# Wini Touch UI — Rebuild Status & Stage Handoff

> **What this is:** the working log for rebuilding `wini_ui/` from a single 3-card
> mode picker into the full paper-like UI system described in the design spec.
> Read this first in any new session that continues the build.
>
> **Source of truth for the design:** `WINI Educational Robot UI Design Specification`
> (the .docx the user provided) — Class-10 educational robot, Waveshare 7″ DSI,
> **portrait 600×1024**, LVGL, voice-first, calm **matte "paper"** aesthetic
> (Kindle Scribe / Apple Books / NCERT textbook). The display is *secondary* to the
> voice; it reduces uncertainty (stage, robot state, progress) without demanding
> attention.
>
> **This doc + `WINI_UI_STATUS.md`** sit *below* the 4-doc lockstep set (they carry
> no authoritative contract), so this rebuild does **not** trigger the lockstep
> propagation rule. Only these two device/UX docs get updated.

---

## The staged plan (5 stages, one reviewable build each)

| Stage | Scope | Status |
|---|---|---|
| **1. Foundation & paper frame** | theme manager, serif fonts, `lv_conf`/CMake, HEADER/CONTENT/FOOTER chrome | ✅ **DONE, verified on panel** |
| **2. Component / widget library** | status_chip, progress_bar, hint_indicator, question/explanation/formula/illustration/result cards, answer_feedback, dialog, toast | ✅ **DONE, verified on panel** |
| **3. Overlays & voice states** | listening / thinking (+sub-states) / loading / celebration | ✅ **DONE, verified on panel** |
| **4. Screens & screen manager** | persistent screens + fade/slide transitions: splash, idle(picker), explain, practice, test, result, settings, error | ✅ **DONE, verified on panel** |
| **5. State machine, IPC, brightness, audio, docs** | event-driven FSM, backlight sysfs fade (cap 35%), audio cues, IPC inbound reader, wiring | ✅ **DONE, verified on panel (one full turn)** |

Full plan file (approved): `C:\Users\LENOVO\.claude\plans\shimmying-conjuring-riddle.md`.

---

## Architecture (theme-driven, component-based, persistent screens)

Directory layout under `wini_ui/` (subdirs are globbed by CMake with
`CONFIGURE_DEPENDS`, so new files need no CMake edits):

```
theme/    wini_theme.{h,c}     single source of color / type / spacing. NOTHING else hardcodes a color.
fonts/    wini_font_serif_{18,28}.c   bundled serif (generated, committed)
chrome/   screen_base.{h,c}    the fixed HEADER/CONTENT/FOOTER frame every screen reuses
          header.{h,c}         stage chip · chapter/topic (or "Question N of M") · robot-status chip
          footer.{h,c}         segmented Explain/Practice/Test progress bars (bars, never %)
widgets/  chip.{h,c}             matte pill primitive (shared by the two chips)
          stage_chip / status_chip   header pills, extracted + reused
          progress_bar          segmented stage bar (footer bars reuse this)
          hint_indicator        ●/○ dots (one label; NEVER "Hint Level N")
          question_card / explanation_card / formula_card / illustration_card / result_card
          answer_feedback       ✓ Correct / soft-orange "Almost…" banner
          dialog                scrim + centered card + buttons
          toast                 self-dismissing bottom pill
overlays/ overlay_base.{h,c}   full-cover paper panel + explicit-anim opa show/hide + pulse-dot
          listening / thinking / loading / celebration   the four voice states
screens/  screen_mgr.{h,c}   persistent-screen switchboard + wini_nav_button + wini_screen_frame
          splash / idle / explain / practice / test / result / settings / error   the 8 screens
app/      app_state.{h,c}    the FSM: parses inbound {"cmd":..} lines → screens/chrome/cards/overlays
platform/ brightness.{h,c}   DSI backlight via sysfs, capped 35%, short fade (best-effort)
          audio_fx.{h,c}     minimal calm SDL2 audio cues (listen / correct / celebrate)
main.c    LVGL/SDL init + brightness/audio init + screen_mgr + app_state + ipc reader + poll loop
ipc.{h,c} mode-channel client — outbound mode_selected + a background inbound reader thread
mode_select.{h,c}     LEGACY dark picker — NOT compiled (excluded from CMake). Superseded by screens/idle.
```

**Key conventions (follow these in every later stage):**
- All color via `wini_color(WINI_COLOR_*)` / `wini_stage_color()` / `wini_status_color()`.
  Never `lv_color_hex(...)` a literal outside `theme/`.
- Two fonts only: `wini_font_heading()` (28) and `wini_font_body()` (18).
- Matte: `shadow_width = 0`, no gradients, hairline `WINI_COLOR_DIVIDER` borders. Reuse
  `wini_style_card` for card surfaces.
- Spacing/geometry via the `WINI_PAD_* / WINI_GAP* / WINI_RADIUS_* / WINI_HEADER_H /
  WINI_FOOTER_H / WINI_TOUCH_MIN` tokens in `theme/wini_theme.h`.
- Widgets that heap-allocate a struct free it via an `LV_EVENT_DELETE` cb on their root
  (see `header.c` / `footer.c`).

---

## Stage 1 — DONE (built + run + screenshot-verified on winipi5)

**Files added:** `theme/wini_theme.{h,c}`, `fonts/wini_font_serif_{18,28}.c`,
`chrome/screen_base.{h,c}`, `chrome/header.{h,c}`, `chrome/footer.{h,c}`.
**Changed:** `lv_conf.h` (heap → 1 MB; montserrat_14/20 kept for `LV_SYMBOL_*` icons),
`CMakeLists.txt` (globs the component tree), `main.c` (paper-frame demo).

**Palette wired (spec §Color Palette):** paper `#F6F5EF`, card `#FCFBF6`, text
`#222222`/`#666666`, divider `#DAD8CF`, Explain `#BFD8FF`, Practice `#D7F2D2`, Test
`#FFE6B8`, Success `#D5F4E6`, Error `#F6D6D6`, Thinking `#ECE8DF`, Listening `#D9F3F5`.
Robot-status vocabulary (Listening/Thinking/Teaching/Checking/Waiting/Offline) with muted
tints + labels is in the theme too.

**Decisions:** serif = **DejaVu Serif** (freely redistributable, already on disk via
matplotlib — clean to ship; no download, no swap needed). Verification is **on the Pi**
(this Windows laptop has no SDL2/LVGL).

**Verified render (screenshot):** paper background; header = EXPLAIN chip + "Chapter 4 /
Quadratic Equations" + Listening chip; content = "Area of a Circle" (serif 28) + wrapped
body + **A = π r²** with a real superscript; footer = Explain 6/6, Practice 3/6, Test 0/6.
Matte, no shadows. Matches the spec.

### ⚠️ Two gotchas discovered (do not rediscover)

1. **Include-guard vs. token name collision.** The header guard `WINI_HEADER_H` clashed
   with the theme's height token `#define WINI_HEADER_H 96` → the whole header was
   `#ifndef`-skipped and every symbol went undeclared. Chrome guards are now
   `WINI_CHROME_HEADER_H` / `WINI_CHROME_FOOTER_H`. Keep guards namespaced away from
   `theme` tokens.
2. **`lv_font_conv` compresses by default → tofu boxes.** Fonts generated without
   `--no-compress` set `.bitmap_format = 1` (compressed). LVGL v9's
   `LV_USE_FONT_COMPRESSED` defaults **off**, so every glyph rendered as a placeholder
   box while the layout was perfect. **Always pass `--no-compress`** (→ `.bitmap_format = 0`).

### Regenerating the serif fonts (only if a glyph is missing)

`node`/`npx` present. TTF: matplotlib's `DejaVuSerif.ttf`. Current symbol set beyond ASCII:
`²³×÷−√≤≥°±πΔθ→←↑↓●○◐✓…—–''""·⅓½¼`. Command (per size 18 and 28):

```bash
npx --yes lv_font_conv --font <DejaVuSerif.ttf> --size <18|28> --bpp 4 \
  --format lvgl --no-compress --range 0x20-0x7E --symbols "<symbol set>" \
  --force-fast-kern-format --lv-include lvgl.h -o fonts/wini_font_serif_<sz>.c
```

Add any new math/symbol glyphs a widget needs (Stage 2 formula_card, hint dots ●○, ✓)
to `--symbols` and regenerate both sizes.

---

## Build / deploy / run workflow (winipi5)

- **Device:** `winipi5@winipi5.local`, checkout `~/cloud_tutor/cloud-CLI/wini_ui`.
  LVGL v9 is already checked out there (`wini_ui/lvgl/`); a `build/` exists and is
  **kept** (LVGL objects cached — do **not** `rm -rf build`; just reconfigure).
- **Auth:** SSH password (ask the user; not stored here). This laptop has no `rsync`/
  `sshpass`, so transfer + remote commands go through **paramiko** (Python 3.12 has it).
  Pattern: `SSHClient` + `open_sftp().put(local, remote)` for changed files, then
  `exec_command("cd .../wini_ui && cmake -B build . && cmake --build build -j4")`.
- **Reconfigure + build:** `cmake -B build . && cmake --build build -j4`. Grep output for
  `error:` and `Built target wini_ui`.
- **Run on the DSI panel (X11 :0):**
  ```bash
  pkill -x wini_ui; sleep 1
  cd ~/cloud_tutor/cloud-CLI/wini_ui
  DISPLAY=:0 XAUTHORITY=$HOME/.Xauthority setsid ./build/wini_ui >/tmp/wini_ui.log 2>&1 </dev/null &
  ```
- **Screenshot (self-verify):** `DISPLAY=:0 XAUTHORITY=$HOME/.Xauthority scrot -o /tmp/wini_stage1.png`
  then SFTP it back and view. (`scrot` and `grim` are installed.)

### ⚠️ pkill gotcha
`pkill -f build/wini_ui` (or `-f wini_client`) matches its **own launcher command line**
and kills the shell before it acts (silent "no output"). Use `pkill -x wini_ui` (exact
process name) or the bracket trick `pkill -f 'wini_[c]lient'` to avoid self-kill.

---

## Stage 2 — DONE (built + run + screenshot-verified on winipi5)

**Files added** (all `widgets/<name>.{h,c}`, theme-driven, zero hardcoded colors):
`chip`, `stage_chip`, `status_chip`, `progress_bar`, `hint_indicator`, `question_card`,
`explanation_card`, `formula_card`, `illustration_card`, `result_card`, `answer_feedback`,
`dialog`, `toast`. **Changed:** `chrome/header.c` now consumes `stage_chip` + `status_chip`
(the inline chip builder moved to `widgets/chip.c`); `chrome/footer.c` now builds each stage
bar from `widgets/progress_bar`; `main.c` renders a temporary scrollable **widget gallery**
(replaces the Stage-1 demo). CMake already globs `widgets/*.c` — no CMake edit needed.

**Conventions honored:** each widget returns an `lv_obj_t *` root; simple ones stash their
one mutable child in the root's `user_data` (no heap), multi-field ones use a small heap
struct freed via an `LV_EVENT_DELETE` cb (as `header.c`/`footer.c` do). All surfaces reuse
`wini_style_card`; all color via the theme.

**Spec-critical behaviors implemented:** hint_indicator draws `●/○` dots (never "Level N");
formula_card is large/centered with real glyphs (`A = π r²`); illustration_card is a flat
NCERT circle-with-radius from LVGL primitives (bordered circle + `lv_line` radius + dot +
"r"), no clipart; answer_feedback is only ever "✓ Correct" (soft-mint) or "Almost. We'll
revisit this concept together." (soft-orange) — no ✗, no "Wrong/Error"; dialog is a soft
scrim + centered matte card; toast self-dismisses.

**Verified render (screenshots):** all 13 widgets in the gallery, plus the tapped dialog
(dimmed scrim, "End session?" card, Not-now / End buttons) and the toast (appears bottom-
centre, then auto-dissolves). Header/footer still correct after the refactor.

### ⚠️ Two gotchas discovered (do not rediscover)

1. **DejaVu Serif has no U+2713 ✓** — `lv_font_conv` silently drops any `--symbols` glyph
   the TTF lacks (it was in the Stage-1 symbol list but never made the cmap; check the
   `unicode_list` offsets, not the `Opts:` comment). So `answer_feedback` **draws** its tick
   with an `lv_line` polyline instead of using a glyph — on-theme (ink on paper) and font-
   independent. If a future widget needs ✓/✗ as text, pull them from a font that has them
   (e.g. DejaVu **Sans**) as a second `--font` source when regenerating, or draw them.
2. **`lv_obj_fade_in` leaves the object at opacity 0 here** — its early-apply sets opa 0 and
   the in-animation never visibly completes in this SDL/LVGL setup (fade **out** + the
   delayed-delete timer both work fine). `toast.c` therefore shows at full opacity
   immediately and only fades on the way out. Don't rely on `lv_obj_fade_in` for Stage 3
   overlay entrances — animate `LV_STYLE_OPA` with an explicit `lv_anim` and verify it.

### Verifying on the panel without touch hardware
The gallery scrolls; drive it over SSH with `xdotool` on `DISPLAY=:0`. **Wheel events
(`click 5`) do NOT scroll LVGL content** — use a press-drag instead (`mousemove x y
mousedown 1`, step the pointer up in ~40 px hops, `mouseup 1`). Let scroll **inertia settle
(~1.5 s)** before clicking a button, or the target has moved and the tap misses.

---

## Stage 3 — DONE (built + run + screenshot-verified on winipi5)

**Files added:** `overlays/overlay_base.{h,c}` + `overlays/{listening,thinking,loading,
celebration}.{h,c}`. **Changed:** `main.c` builds the four overlays once on `lv_layer_top()`
(persistent, hidden) and the gallery grew a top **"overlays — tap to show"** row (Listen /
Think / Load / Celebrate); listening/thinking/loading dismiss on tap, celebration
dismisses itself.

**overlay_base** is the shared scaffold: a full-cover **paper** panel (opaque `WINI_COLOR_BG`,
`IGNORE_LAYOUT` + center-pinned so it covers any flex/scroll parent), a centered column for
the state's indicator + copy, and `wini_overlay_show` / `_hide` that fade `LV_STYLE_OPA` with
an **explicit `lv_anim`** (250 ms) — deliberately NOT `lv_obj_fade_in` (Stage-2 gotcha 2). It
also exposes `wini_overlay_pulse_dot` (endless, calm **opacity** breathing — no scaling).

**Exact spec copy is baked in, not caller-supplied where the spec fixes it:** listening =
"I'm listening" / "Speak naturally."; thinking = "I'm thinking…" + a `wini_thinking_substate_t`
enum carrying the three exact lines ("Understanding your answer…" / "Searching today's
lesson…" / "Preparing explanation…"); loading takes an **intent** string (never "Loading…");
celebration = a soft-mint badge with a **drawn ✓** (lv_line, same reason as answer_feedback)
+ message, **one** gentle opacity pulse, then a one-shot `lv_timer` auto-hides it. No confetti,
no zoom/bounce/shake anywhere — all motion is opacity.

**Verified render (screenshots):** all four overlays fade in over the gallery correctly, the
thinking dots stagger, celebration pulses once and **auto-returns to the gallery**, and
tap-to-dismiss works. Header/footer are covered by the demo overlays because they sit on
`lv_layer_top()`; in Stage 4 screens can instead parent an overlay to the **content region**
to keep chrome visible (overlay_base accepts any parent).

### ⚠️ Gotcha carried forward
`lv_obj_fade_in` is still avoided — overlay entrances use an explicit `lv_anim` on
`LV_STYLE_OPA` (verified to actually reach full opacity). Reuse `wini_overlay_show/_hide` for
Stage 4 screen transitions rather than the `lv_obj_fade_*` helpers.

---

## Stage 4 — DONE (built + run + screenshot-verified on winipi5)

**Files added:** `screens/screen_mgr.{h,c}` + `screens/{splash,idle,explain,practice,test,
result,settings,error}.{h,c}`. **Changed:** `main.c` drops the Stage 2/3 widget gallery and
now boots the screen manager (`wini_screen_mgr_init(lv_screen_active())`), opening on splash.
`mode_select.{h,c}` stays excluded from CMake (its role is taken by `screens/idle.c`).

**screen_mgr** is the switchboard: every screen is built **once** as a hidden, full-size child
of the active screen and kept alive for the whole session (never destroy/rebuild). `wini_screen_show`
crossfades **opacity** between them with an explicit `lv_anim` on `LV_STYLE_OPA` (220 ms) — the
same pattern as `overlay_base`, deliberately NOT `lv_obj_fade_*` / `lv_screen_load_anim` (the
Stage-2 gotcha 2). It also exposes two shared helpers used by the screen files: `wini_nav_button`
(a calm matte pill that crossfades to a target screen; `primary`=soft-mint affirmative) and
`wini_screen_frame` (full-size root + the shared `wini_frame_create` HEADER/CONTENT/FOOTER).

**The 8 screens (all mock content — real data arrives via IPC in Stage 5):**
- **splash** — plain paper "Wini" / "Getting ready…"; a one-shot `lv_timer` auto-advances to idle after 1.5 s.
- **idle** — the home launcher: greeting + three soft-tinted stage cards (`wini_stage_color`) that open a
  session + a quiet **Settings** pill. This is the paper re-skin of the old dark `mode_select` picker.
- **explain** — frame (EXPLAIN / Teaching) + explanation_card + formula_card (A = π r²) + illustration_card
  + a "Let's practice" primary pill; content is scrollable in case the figure runs long.
- **practice** — frame (PRACTICE / Checking) + question_card + hint_indicator (●○○) + answer_feedback +
  "Take the test". Also carries a **listening overlay parented to the CONTENT region** (not `lv_layer_top`),
  proving the handoff requirement: the overlay covers the question while the header/footer stay visible.
- **test** — frame (TEST / Waiting) + a **bare** question_card only. No hint dots, no feedback, no figure —
  the assessment screen must not coach.
- **result** — frame + centered result_card ("4 / 5", "Chapter complete") + "Back home". No pass/fail language.
- **settings** — plain paper (not a session stage, so no stage header): Brightness / Volume / Voice matte rows
  + "Check connection" (previews the error screen) + "Done".
- **error** — plain paper, a soft slow pulse dot + "Connection Lost" / "Trying again…" + "Back home". Calm, no red.

**Verified render (screenshots):** every screen shown via real taps over SSH — the full walk
idle → explain → practice (incl. the content-region listening overlay covering only the content) →
test → result, plus settings and the error screen. The opacity crossfade between persistent screens
works; the splash auto-advance to idle works; header/footer stay visible under the content overlay.

### ⚠️ Notes carried forward
- Screen transitions reuse the `LV_STYLE_OPA` `lv_anim` (verified to reach full opacity); `lv_obj_fade_*`
  and `lv_screen_load_anim` are still avoided.
- `wini_frame_create` does NOT set a flex flow on `content` — each screen sets
  `lv_obj_set_flex_flow(content, LV_FLEX_FLOW_COLUMN)` itself (otherwise children stack at 0,0).
- Overlays accept any parent: parent them to a screen's `content` (Stage 4) to keep chrome visible,
  or to `lv_layer_top()` (Stage 3 demo) to cover the whole panel.

---

## Stage 5 — DONE (built + run + verified against one full turn on winipi5)

**Files added:** `app/app_state.{h,c}`, `platform/brightness.{h,c}`, `platform/audio_fx.{h,c}`.
**Changed:** `ipc.{h,c}` (bidirectional now — a background reader thread + a line queue),
`main.c` (boots brightness/audio, builds screens + `wini_app_init`, starts the IPC reader, and
calls `wini_app_poll()` each frame), and the framed screens (`practice/test/explain/result`) +
`idle` — each now **self-registers** its live widgets with `app_state` and idle sends
`mode_selected` on tap. CMake already globs `app/` + `platform/`.

**The event layer.** `ipc.c`'s reader thread owns the socket (connect + ~1 Hz reconnect), reads
newline-JSON **client→UI** command lines into a mutex-guarded ring buffer, and **never touches
LVGL**. `main.c` drains it on the LVGL thread via `wini_app_poll()` → `wini_app_dispatch()`.
`app_state` is the FSM: a tiny flat-JSON scanner (no allocator) pulls `cmd` + fields and calls the
right screen/chrome/card/overlay setter. Screens hand it their widgets through `wini_app_bind_*`,
so the FSM addresses live objects without owning their construction. Command vocabulary + the
table are in `WINI_UI_STATUS.md` §9 (the authoritative device-doc summary).

**Platform seams (best-effort, clean no-op if absent).** `brightness.c` finds the first writable
`/sys/class/backlight/*/brightness`, caps at **35%**, and ramps in ~150 ms. `audio_fx.c` opens an
SDL2 audio device and plays short low-amplitude raised-cosine sine cues (listen / correct /
celebrate). On winipi5 **both are live**: backlight node `11-0045` (max 255) rests at 35%, and the
audio device opens (`[audio] ready`).

**Verified against ONE FULL PRACTICE TURN (screenshots).** A stand-in `wini_client`
(`brain_stub.py`) listened on :8140, launched the UI, tapped **Practice** (UI emitted
`{"event":"mode_selected","mode":"PRACTICE"}`, received), then streamed the turn back over the same
socket: `question` → `status:listening`+`listening:on` → `status:thinking`+`thinking:on(understanding)`
→ `status:checking`+`feedback:correct`+`progress 3/5` → `celebrate:"Well done"`. Every beat was
screenshot-confirmed on the panel — the header status chip flipping Listening→Thinking→Checking, the
**content-region** overlays (header/footer staying visible), the FSM-set question text, the ✓ Correct
banner, the footer Practice bar advancing to 3/6, and the "Well done" badge auto-dismissing back to
practice. This exercises the real IPC framing end-to-end (the only stubbed part is the brain that
produces the turn — the Python emitter is the remaining integration seam, see `WINI_UI_STATUS.md` §5/§9).

### ⚠️ Notes / gotchas
- The reader thread must not call LVGL; keep all UI work on the poll path (`wini_app_poll`).
- `app_state.c` needs `<stdio.h>` for `snprintf` (the flat-JSON scanner) — easy to miss.
- Overlays the FSM drives on practice are the **content-region** ones bound by the screen; loading +
  celebration are global (top layer). Prefer content-region so chrome stays visible during a turn.

---

## The rebuild is complete (Stages 1–5)

All five stages are built and screenshot-verified on winipi5. What remains is **cross-process
integration**, tracked in `WINI_UI_STATUS.md` §5: teach `wini_client` to emit these `{"cmd":..}`
command lines (a display sink onto the mode-channel socket) so the real brain drives the panel,
and fold `wini_ui` auto-start into `wini_platform/supervisor.py`. Those are Python-side follow-ons,
not UI work.

---

## Current process state on the Pi (as of this handoff)
- `wini_ui`, `wini_server.py` (brain), and `wini_client` (voice client) are **all stopped**
  (`STOPPED` confirmed). Restart them per `WINI_UI_STATUS.md` §7 when needed.
