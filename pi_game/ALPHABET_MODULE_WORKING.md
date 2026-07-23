# Wini Letters — how the module works today

**Snapshot taken 2026-07-22** from winipi5 (`192.168.29.24`,
`/home/winipi5/cloud_tutor/cloud-CLI/pi_game`). Every source file on the device is
byte-identical to the copy now in `D:\cloud CLI\pi_game\` (MD5-verified, 26 files);
the generated `assets/` tree and the live `progress.db` were pulled across as well.

This document describes **what the code currently does**, not what it should do.
The design spec is `pigame.md`; the build/run notes are `README.md`. This file is
the third thing: a walk-through of the running system, written so the module can be
worked on from the laptop.

---

## 1. What it is

A calm, voice-led alphabet lesson for a young child, running full-screen on the
Pi's 7″ DSI panel (portrait, 600×1024). Twenty-six letters, **one identical
seven-stage lesson each**. No score, no timer, no reward, no failure state.

It is a **second, separate product** from the maths tutor that lives in the same
repo. The two cannot run at the same time — they contend for the panel, the single
reSpeaker playback substream, and GPIO22. `run_alphabet.sh` kills the tutor on
start; `run_wini_package.sh` does the reverse.

Entry points for a user:

| Surface | What it does |
|---|---|
| Desktop icon `~/Desktop/Wini-Letters.desktop` | runs `pi_game/run_alphabet.sh` |
| `./pi_game/run_alphabet.sh` | the same script, from a shell |
| `./pi_game/stop_alphabet.sh` | stops both halves, restores `touch_service.py` |
| on-screen ✕ (top-right, ~`(544, 72)`) | UI exits, then runs `ALPHABET_STOP_CMD` |

---

## 2. Process shape

Two processes, deliberately mirroring the tutor's `wini_server.py` + `wini_ui`
split, so there is one architecture to learn on this device.

```
alphabet_server.py  (Python 3.13, .venv)        alphabet_ui  (C, LVGL v9.2.3 + SDL2)
  the §12 lesson state machine                    draws ONE stage at a time
  Cloud TTS / Cloud STT / Vertex Gemini           reports touches and the drag
  SQLite progress store                           NEVER opens the speaker
        |                                                    |
        +------ :8160  TCP, newline-delimited JSON -----------+
        +------ :8150  HTTP  /health  /parent
```

Both sockets bind `127.0.0.1` only. `:8160` accepts **one UI connection at a time**
(`srv.listen(1)`); each accepted connection becomes a `Session` that runs lessons
until the UI disconnects.

**The brain owns the lesson. The UI is a renderer.** The UI has no idea what stage
comes next, how many attempts are allowed, or what counts as correct. It draws what
arrives and emits events.

### The wire contract

| Direction | Messages |
|---|---|
| UI → brain | `begin` · `touch` · `fed` · `next` · `again` · `quit` |
| brain → UI | `ready` · `stage` · `status` · `feedback` |

A `stage` command is self-contained — it carries the stage name, the instruction
text, the letter, `index`/`total`, and **absolute filesystem paths** to whatever art
that stage needs (`letter_img`, `object_img`, `tile_img` per choice, `robot_open`,
`robot_happy`). The UI loads PNGs straight off disk; no image data crosses the
socket.

`status` values are `speaking` · `listening` · `loading` · `waiting` · `error`, and
the UI renders them as plain words in the top strip ("Wini is talking", "Wini is
listening", "Getting ready", "Wini needs help") — no icons, no color changes.

`feedback` kinds are `touch_ok` · `touch_retry` · `repeat_ok` · `repeat_retry` ·
`repeat_move_on` · `activity_skip`. The **spoken line carries the message**; the UI
does almost nothing with them — only `repeat_ok` triggers a gentle pulse of the
content area. Nothing flashes, buzzes, or turns red.

---

## 3. The lesson — the seven stages

`Session.lesson()` in `alphabet_server.py` is the whole state machine. It is
deterministic: no branching, no randomness, no failure state. A stage that only
speaks ends after a calm pause; a stage that needs the child ends by waiting for an
event.

Before Stage 1 the brain sends `status: loading` and **prewarms this letter's audio
to disk**, then kicks off a background thread to prewarm the *next* letter while the
child works.

| # | Stage | Screen | Ends when |
|---|---|---|---|
| 1 | `intro` | the big letter | after `PAUSE_INTRO` = 1.4 s |
| 2 | `listen` | the big letter | after `PAUSE_STAGE` = 0.9 s |
| 3 | `touch` | 3 letter tiles | the **correct** tile is tapped |
| 4 | `repeat` | the big letter | 2 mic attempts, then move on regardless |
| 5 | `assoc` | the object + its word | after 1.4 s |
| 6 | `activity` | object + robot face | the object is dragged onto the robot, **or** 30 s |
| 7 | `complete` | letter + object | the child taps *Next letter* or *Again* |

Pacing constants live at the top of `alphabet_server.py`
(`PAUSE_AFTER_SPEECH` 0.7, `PAUSE_INTRO` 1.4, `PAUSE_STAGE` 0.9,
`ACTIVITY_WAIT_S` 30, `MAX_SPEECH_ATTEMPTS` 2). They are the pauses the child
thinks in — trimming them to make the lesson "snappier" is exactly the change the
spec forbids.

### Stage 3 — touch

Three tiles, one correct. A **wrong tap produces no buzzer, no red, no counter** —
just a spoken invitation to look again, and the board stays exactly as it was. The
loop repeats until the right tile is tapped. Both attempts and correct hits are
counted into the progress store.

`drain()` is called as the stage opens: it discards events queued *before* the stage
appeared. Without it, a child drumming on the panel during the intro would leave
taps in the queue that auto-answer the touch stage the instant it renders — the
child would never see the board, and the store would record an answer nobody gave.
Events that arrive *while a line is being spoken* are kept deliberately: once the
board is on screen, an early answer is a real answer.

### Stage 4 — repeat (the mic stage)

The letter stays on screen while the child speaks, so there is something to say the
sound *to*. Then, per attempt:

1. `speech.listen()` records one utterance with a child-tuned endpoint (RMS
   threshold 0.012, 1200 ms of trailing silence, 8 s hard cap) and sends it to
   Cloud STT (`en-IN`, `latest_short`, punctuation off).
2. `speech.judge_attempt()` decides, cheapest gate first:
   - **empty transcript** → not a match (worth one retry, costs nothing);
   - **word-wise match** against the phoneme, its spoken spelling, and the letter's
     name from `LETTER_NAMES` — plus short-target near-misses where *both* strings
     are ≤4 chars;
   - **Gemini** for anything else short (`len ≤ 12`); a long phrase is plainly not a
     child saying one sound and is rejected without spending a call.

Two attempts is the cap. The move-on line is **`repeat_move_on`, not `repeat_ok`** —
praising a sound the robot never heard, on every lesson, is dishonest and useless to
a child who is struggling. `speech_matched` counts only genuine matches, so
`/parent` stays truthful. Any *cloud failure* still resolves to a pass: an outage
must never read to a child as "you were wrong".

The matching is **word-wise and never a bare substring test**. A substring test
against a one-character target accepted any word containing that letter — `banana`
and `elephant` both scored as correct attempts at **A**, `blue` at **B**.

### Stage 6 — the mini activity

The object is dragged onto the robot. This is the one place the implementation
diverges from a literal reading of the spec (§Stage 6 "Feed Apple"): only the five
edible objects are *eaten* ("I am hungry… Yummy!") and the robot only opens its
mouth for those; the rest are *handed over* ("Can you bring me the…?" / "Thank you!
I like it."). `content.EDIBLE` holds the list. The interaction itself is unchanged —
still exactly one drag, one activity.

If nothing is dragged within 30 s the robot simply moves on. That is not a failure;
it is logged distinctly (`FEDMARK timeout` vs `FEDMARK ok`) because "the lesson
finished" alone does not tell you whether the drag worked.

### Stage 7 — completion, and what comes next

On `next` the brain advances to `ORDER[(idx+1) % 26]`; on `again` it re-runs the
same letter. The run is saved with `completed=1` **before** the wait, so a child who
walks away still gets credit.

At `begin` with no letter, the resume point is `progress.next_letter(ORDER)` — the
first letter not yet completed, wrapping to `A` once all 26 are done. Deterministic;
never a dead end.

---

## 4. Voice (`speech.py`)

Everything is cloud — Cloud TTS out, Cloud STT in, Vertex Gemini as the Stage-4
judge. Nothing infers locally on the device. Two project rules shape the file:

- **Clients are memoized per process.** Constructing a Google client costs 4–9 s of
  ADC/channel setup versus <1.5 s for a warm call, so `warm_clients()` synthesizes
  `"Hello."` at boot and the launcher gates the UI on that finishing.
- **Every cloud call carries a hard wall-clock timeout** via `_bounded()`
  (`ThreadPoolExecutor.result(timeout=…)`): TTS 25 s, STT 25 s, LLM 15 s. SDK-level
  timeouts have hung for hours in this project.

**TTS is disk-cached**, keyed by `sha256(voice|lang|rate|hz|text)[:24]`, written
atomically via a `.part` file (a half-written WAV in the cache would be a permanent
silent line, since "file exists" means "already synthesized"). Voice defaults:
`en-IN-Chirp3-HD-Achernar`, `en-IN`, rate **0.88**, 24 kHz — all overridable by
`ALPHABET_TTS_VOICE` / `_LANG` / `_RATE`.

Because a lesson's lines are fully deterministic (`content.lesson_lines`), one
prewarm pass makes the entire 26-letter module speak **from local files**; only a
cache miss needs the network. The snapshot carries 305 cached WAVs (~30 MB).

Playback is `aplay`, not sounddevice: fire-and-wait with no mixing, and it works
from a bare-SSH launch where no PortAudio/PipeWire session exists. The device is
named explicitly — `plughw:CARD=Lite,DEV=0` (`ALPHABET_ALSA_DEVICE`) — because
ALSA's `default` on this board is the HDMI sink and returns
`audio open error: Unknown error 524`.

`ALPHABET_NO_MIC=1` makes `listen()` return `""` immediately, which takes the same
path a silent child does. That is how headless verification works.

---

## 5. Content and assets

`content.py` is the **single hand-curated source** of what each letter teaches:
phoneme, TTS-friendly spelling, object word, spoken lines, and a flat-shape art
recipe (`ell` / `rect` / `poly` / `lens` / `line` / `arc` / `pie`, plus a pseudo-fill
`ERASE` that punches transparency). Model-generated lesson content is an explicit
non-goal in the spec, so nothing here is LLM-authored. Art coordinates are on a
420×420 canvas; the palette is muted throughout — never pure red/green, never neon.

`gen_assets.py` (Pillow, run on the Pi) projects that into:

```
assets/
  letters/<A-Z>/lesson.json     phoneme, say, lines, choices, objects, edible
                letter_big.png  the large glyph
                letter_tile.png the tile used in the Stage-3 board
                object.png      the drawn object
  common/robot_idle.png  robot_open.png  robot_happy.png
  tts_cache/<24-hex>.wav          305 files
```

**Nothing at runtime reads `content.py`** — the brain reads `lesson.json` and the
PNGs. After editing content you must re-run
`.venv/bin/python -m pi_game.gen_assets --force`, and any changed spoken line needs
a fresh TTS synthesis (automatic on next play, or bulk via `--prewarm-all`).

---

## 6. The UI (`alphabet_ui/`, C + LVGL v9 + SDL2)

| File | Role |
|---|---|
| `main.c` | boot: LVGL + SDL window 600×1024, fullscreen-desktop, pointer/kbd, IPC, loop |
| `ipc.c/.h` | the lesson channel — background reader thread, ~1 s reconnect backoff |
| `screens/alpha_screens.c` | every stage, the drag, the command applier (the bulk of it) |
| `theme/alpha_theme.c/.h` | colors, spacing, `alpha_fade_in()`, `alpha_pulse()` |
| `fonts/alpha_font_{22,32,34}.c` | Nunito Sans, generated with `lv_font_conv --no-compress` |
| `CMakeLists.txt` | build; **reuses `../../wini_ui/lvgl`**, does not vendor a second LVGL |

Boot order matters: `ipc_init()` + `ipc_start()` run **before** `alpha_ui_init()`,
because the brain sends `ready` the moment it accepts, and the reader thread queues
it so the splash is correct on the very first frame.

`main.c` forces `SDL_AUDIODRIVER=dummy` unless `ALPHABET_UI_AUDIO` is set. This is
load-bearing: the reSpeaker exposes **one** playback substream and the brain owns
it. If SDL claims it for UI cues, Wini's voice goes silent.

On exit the UI runs `$ALPHABET_STOP_CMD` (the launcher passes
`pi_game/stop_alphabet.sh`). Without that, closing the window would leave the brain
running, still holding the speaker, and the background touch service would never
come back.

The JSON parsing in `alpha_screens.c` is two tiny hand-rolled scanners (`jstr`,
`jint`) — flat keys only, no allocator, no nesting. That is why every `stage`
payload is deliberately flat.

### The drag (`food_drag_cb`)

The single fiddliest piece of the UI, and the one with the most traps behind it:

- The position is **re-derived from the absolute pointer each frame with a grab
  offset**, never accumulated from `lv_indev_get_vect()`. Summing per-frame deltas
  drops motion on a fast flick and drifts over a long gesture; re-deriving is
  self-correcting.
- `lv_obj_align()` is re-applied on every layout pass, so `lv_obj_set_pos()` on an
  aligned object is silently undone. The alignment is broken on `LV_EVENT_PRESSED`
  first, or the drag looks completely dead.
- `LV_EVENT_PRESS_LOST` is handled alongside `RELEASED` — if the finger slides off
  the object no `RELEASED` ever arrives and the object is left stranded.
- Images use `make_img_sized()`, not `lv_image_set_scale()`: scaling changes what is
  drawn but leaves the object box at the source size, so hit-testing misses.

---

## 7. Progress store (`progress.py`, SQLite)

One table, `lesson_run`, **one row per letter per lesson run** — repeat visits
accumulate rather than overwrite, because a child re-doing A is practice, not a
correction. Columns: `letter`, `started_at`, `finished_at`, `completed`,
`touch_attempts`, `touch_correct`, `speech_attempts`, `speech_matched`, `seconds`.

Two spec rules shape it: **no scores, grades or ranking** (it records what happened,
never a judgement), and **the child never sees any of it**. Nothing from this store
is ever sent to the UI. `parent_summary()` is the only read path, served at
`GET :8150/parent`.

The pulled snapshot holds 6 runs (A–F, 2026-07-22 18:43–18:57), all completed,
touch 6/6, speech 0/12 matched — the expected shape for SSH-launched runs, where
there is no PipeWire seat and the mic returns silence every time.

---

## 8. Launch sequence, in order

`run_alphabet.sh`:

1. `cd` to the repo root; `mkdir -p logs`.
2. Take `logs/.alphabet.lock` via `flock -n 9`; a second icon tap exits quietly.
   **Every long-lived child is spawned with `9>&-`** — otherwise it inherits the
   lock fd and holds it for the whole session, and the *next* launch silently
   no-ops forever.
3. Source `pi_game/display_env.sh` → detects Wayland vs X11 and exports
   `SDL_VIDEODRIVER` etc. Over SSH the display vars are unset and SDL silently
   falls back to an offscreen driver: the window is created and nothing appears.
4. If both halves are already running, exit.
5. `pkill` the previous alphabet halves, **`touch_service.py`** (it owns GPIO22 and
   the speaker while idle), and all three tutor processes.
6. Source `./.env`.
7. Start the brain: `setsid .venv/bin/python -u -m pi_game.alphabet_server`.
8. **Gate on real readiness**, not a sleep: poll `:8150/health` for `ready` up to
   120 s. A picker you can tap during the 4–9 s client warmup looks broken.
9. Start the UI with `SDL_AUDIODRIVER=dummy` and `ALPHABET_STOP_CMD` set.

Logs (all appended): `logs/alphabet_launch.log`, `logs/alphabet.log`,
`logs/alphabet_ui.log`.

**Launch from the panel or VNC, not bare SSH.** SSH renders the UI fine but has no
PipeWire seat, so Stage 4 hears silence every time. It degrades calmly, so a silent
Stage 4 in the logs usually means "launched over SSH", not a bug.

---

## 9. Verifying without touching the device

```bash
# no panel, no mic — drives the brain's state machine directly
ALPHABET_NO_MIC=1 .venv/bin/python -m pi_game.drive_lesson --letter A --wrong-first

# the real panel: runs a lesson and screenshots all seven stages to /tmp/alpha_*.png
./pi_game/shoot_stages.sh

# the drag, which a synthetic tap cannot stand in for
./pi_game/test_drag.sh fast     # also: slow | offset | short
```

Both panel scripts go through `display_env.sh`, which gives backend-agnostic
`shot` / `tap` / `drag`. Input is injected at the kernel level through `/dev/uinput`
(`touchsim.py`, needs `sudo`), so it takes the same path as a real finger.

Two dead ends already ruled out — do not retry them: **`wlrctl` cannot drag** (each
invocation creates a virtual pointer, sends one action, destroys it, so press and
motion come from different devices), and **`xdotool`/`scrot` are X11-only** since
the 2026-07-22 move to labwc/Wayland.

**Scope log greps to the current run.** The brain appends to one long-lived
`logs/alphabet.log`, so a bare `grep FEDMARK` happily returns a hit from an earlier
lesson and makes a failing drag look like it passed. Record
`BASE=$(wc -l < logs/alphabet.log)` first and read past it.

---

## 10. Building it from outside the Pi

**Short answer: the Python half runs anywhere; the C half must be built for
aarch64 Linux, and the practical loop stays edit-here / build-on-Pi.**

The deployed binary is
`ELF 64-bit LSB pie, ARM aarch64, dynamically linked` — a Windows laptop cannot
produce that directly. Device toolchain: gcc 14.2.0, CMake 3.31.6, SDL2 2.32.4,
LVGL v9.2.3 (`lvgl/lvgl` @ `933b235`).

Three options, in order of how much they actually buy you:

**(a) Edit on the laptop, build on the Pi — the working loop.** Nothing to set up;
a full rebuild is a couple of minutes.

```bash
MSYS_NO_PATHCONV=1 python tools/pi.py push "D:/cloud CLI/pi_game/alphabet_ui/screens/alpha_screens.c" /home/winipi5/cloud_tutor/cloud-CLI/pi_game/alphabet_ui/screens/alpha_screens.c
MSYS_NO_PATHCONV=1 python tools/pi.py run "cd /home/winipi5/cloud_tutor/cloud-CLI && cmake --build pi_game/alphabet_ui/build -j4 2>&1 | tail -20"
```

CMake globs with `CONFIGURE_DEPENDS`, so **new** `.c` files need no CMakeLists edit —
`-- GLOB mismatch!` followed by a reconfigure is correct, not an error.

**(b) Build and run the UI on the laptop under WSL2 for layout work.** This
produces an x86_64 binary that is **not deployable**, but it opens a real 600×1024
LVGL window you can iterate on with a mouse, no device needed. Requires
`build-essential cmake libsdl2-dev` and, importantly, the LVGL checkout that
`CMakeLists.txt` expects and that this laptop **does not currently have**:

```bash
git clone https://github.com/lvgl/lvgl.git wini_ui/lvgl
git -C wini_ui/lvgl checkout 933b235      # v9.2.3, the version on the device
cmake -S pi_game/alphabet_ui -B /tmp/alpha_build
cmake --build /tmp/alpha_build -j4
DISPLAY=:0 /tmp/alpha_build/alphabet_ui --host <pi-ip> --port 8160
```

Point it at the Pi's brain (SSH-forward `:8160`) and it will drive a real lesson,
minus the audio — the brain speaks on the Pi's speaker, not yours.

**(c) Cross-compile to aarch64 and push the binary.** Possible with an
`aarch64-linux-gnu` toolchain plus an arm64 SDL2 sysroot, but the sysroot is the
whole cost and it buys perhaps 90 seconds per build over option (a). Not worth it
unless the Pi becomes unavailable.

**The Python half needs no build at all.** `alphabet_server.py`, `content.py`,
`speech.py`, `progress.py`, `gen_assets.py` and `drive_lesson.py` run on the laptop
given the repo's venv, Google ADC, and a `.env`. `gen_assets.py` (Pillow only) will
regenerate the entire `assets/letters` tree identically here; `--prewarm-all` will
rebuild `tts_cache` at the cost of ~312 Cloud TTS calls. Both trees are already in
this snapshot, so neither is necessary.

---

## 11. What is in the laptop copy

```
D:\cloud CLI\pi_game\
  *.py  *.sh  README.md  pigame.md          all 26 sources, MD5-identical to the Pi
  ALPHABET_MODULE_WORKING.md                this file (laptop-only)
  alphabet_ui/                              C sources + generated fonts
  assets/                                   347 files, ~30 MB — pulled from the Pi
  progress.db                               live store, 6 runs (A–F)
D:\cloud CLI\Wini-Letters.desktop           the icon, identical to ~/Desktop's copy
```

Not copied, and not needed:

- `alphabet_ui/build/` — aarch64 build tree; rebuild, don't ship.
- `wini_ui/lvgl/` — 201 MB upstream checkout; clone from GitHub at `933b235` if you
  need to build (see §10b). **This is the one prerequisite missing on the laptop.**
- `__pycache__/`.

`pigame.md` exists only on the laptop — the design spec was never pushed to the
device.

---

## 12. Traps worth re-reading before changing anything

The full list is in `README.md` under *Things that will cost you an hour*. The five
most expensive:

1. **`lv_font_conv` compresses by default** and LVGL v9 will not decode it without
   `LV_USE_FONT_COMPRESSED`. Symptom: a perfect layout in which every glyph is an
   empty tofu box. Generate with `--no-compress`.
2. **`LV_SYMBOL_*` glyphs live in Montserrat**, not in the Nunito faces — any label
   using one needs `lv_font_montserrat_14` set explicitly.
3. **`pkill -f alphabet_server` over SSH kills your own SSH session**, because
   paramiko's command line contains that string. Kill in a *separate* call from the
   one that starts it, and bracket the pattern (`alphabet_[s]erver`).
4. **Don't time-synchronise tests.** A letter's first run pays for cloud TTS and
   every later run replays from disk seconds faster, so fixed sleeps photograph the
   wrong stage. Wait on `STAGEMARK` log lines.
5. **Synthetic drags need pauses.** LVGL samples the pointer at ~30 Hz; a press
   followed immediately by motion can land in one poll, so the press registers at
   the already-moved position and no drag starts. `touchsim.do_drag` settles 300 ms
   after the press and before the lift.

---

## 13. Known gaps

- **Stage 4 real-mic accuracy is unmeasured.** The *matcher* has a 21-case
  regression set, but every on-device run so far has been over SSH, where the mic
  returns silence. What is unverified is the link before the matcher: whether Cloud
  STT transcribes a small child saying a bare phoneme usefully at all. That needs
  one run launched from the panel or VNC with someone actually speaking.
  `LETTER_NAMES` and the phoneme spellings are the things most likely to need
  tuning against real transcripts.
- **Phase 6 robot expressions** (LED, ears, head) are not built. The ears are
  disabled on this hardware anyway (`EAR_ACTUATION_ISSUE.md`); the face PNGs in
  `assets/common/` are the on-screen stand-in.
- **The module is untracked in git** (`pi_game/` is not ignored — it has simply
  never been committed), so this laptop copy and the device copy are the only two.
