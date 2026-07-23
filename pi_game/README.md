# Alphabet Learning Module (`pi_game/`)

The calm, voice-led alphabet lesson from `pigame.md`, running on winipi5's 7″ DSI
panel. Twenty-six letters, one identical seven-stage lesson each, no scores and
no rewards.

Design spec: **`pigame.md`** — read it first; this file only covers how the thing
is built and run. Where the implementation departs from the spec, it says so and
says why (see [Deviations](#deviations-from-the-spec)).

---

## Shape

Two processes, mirroring the tutor's split (`wini_server.py` + `wini_ui`):

```
alphabet_server.py  (Python)          alphabet_ui  (C, LVGL v9 + SDL2)
  lesson state machine                  draws one stage at a time
  Cloud TTS / STT / Gemini              reports touches and drags
  SQLite progress                       never opens the speaker
        |                                        |
        +---- :8160 newline-delimited JSON ------+
        +---- :8150 HTTP /health, /parent
```

The **brain owns the lesson**; the UI is a renderer. A stage that only speaks
ends after a pause, a stage that needs the child ends by waiting for an event.

| Direction | Messages |
|---|---|
| UI → brain | `begin` · `touch` · `fed` · `next` · `again` · `quit` |
| brain → UI | `ready` · `stage` · `status` · `feedback` |

## Files

| Path | Role |
|---|---|
| `content.py` | the 26 lessons: phoneme, word, spoken lines, flat-art recipes |
| `gen_assets.py` | renders `assets/` from `content.py` (Pillow, runs on the Pi) |
| `speech.py` | Cloud TTS (disk-cached) + Cloud STT + the Gemini attempt judge |
| `progress.py` | SQLite store; `parent_summary()` is its only read path |
| `alphabet_server.py` | the state machine, both sockets, the launcher's health gate |
| `alphabet_ui/` | the C UI (theme, ipc, screens, generated Nunito fonts) |
| `drive_lesson.py` | headless UI stand-in — runs a lesson with no panel and no mic |
| `display_env.sh` | backend detection + `shot`/`tap`/`drag` (Wayland or X11) |
| `touchsim.py` | uinput multi-touch injector — synthetic finger, needs `sudo` |
| `shoot_stages.sh` | drives a real lesson on the panel and screenshots every stage |
| `test_drag.sh` | drag stress test: fast / slow / offset / short |
| `run_alphabet.sh` / `stop_alphabet.sh` | launcher pair (desktop icon: `Wini-Letters.desktop`) |

## Running

```bash
./pi_game/run_alphabet.sh      # brain + UI, same as the desktop icon
./pi_game/stop_alphabet.sh     # stops both, resumes the touch service
```

Launch it **from the panel or VNC**, not bare SSH: an SSH session has no
PipeWire seat, so the UI renders but the mic never opens and Stage 4 hears
silence every time (it degrades calmly — two attempts, then the lesson moves on —
so a silent Stage 4 in the logs usually means "launched over SSH", not a bug).

```bash
curl -s localhost:8150/health   # {"ok":true,"ready":true,...}
curl -s localhost:8150/parent   # the §16 parent report
```

## Rebuilding

```bash
# assets, after editing content.py
.venv/bin/python -m pi_game.gen_assets --force

# the UI
cmake -S pi_game/alphabet_ui -B pi_game/alphabet_ui/build
cmake --build pi_game/alphabet_ui/build -j4

# cache every spoken line for all 26 letters (~312 TTS calls, once)
.venv/bin/python -m pi_game.alphabet_server --prewarm-all
```

LVGL is **not vendored here** — the build reuses `wini_ui/lvgl` so both products
stay on one engine.

## Verifying without touching the device

```bash
# no panel, no mic: drives the brain's state machine directly
ALPHABET_NO_MIC=1 .venv/bin/python -m pi_game.drive_lesson --letter A --wrong-first

# the real panel, screenshots of all seven stages into /tmp/alpha_*.png
./pi_game/shoot_stages.sh

# the drag, which a synthetic tap cannot stand in for (run on the activity stage)
./pi_game/test_drag.sh fast     # also: slow | offset | short
```

Both drive the panel through `display_env.sh`, which detects Wayland or X11 and
injects input at the kernel level via `touchsim.py` — so they behave identically
on either backend and exercise the same path as a real finger.

**Scope your log greps to the current run.** The brain appends to one long-lived
`logs/alphabet.log`, so a bare `grep FEDMARK` happily returns a result from an
earlier lesson and makes a failing drag look like it passed — that happened.
Record `BASE=$(wc -l < logs/alphabet.log)` first and read past it.

---

## Things that will cost you an hour

- **`lv_font_conv` output is compressed by default** (`bitmap_format = 1`) and
  LVGL v9 will not decode it unless `LV_USE_FONT_COMPRESSED` is on. Symptom: a
  perfect layout in which every glyph is an empty tofu box. Generate with
  `--no-compress`.
- **`LV_SYMBOL_*` glyphs live in Montserrat**, not in our Nunito faces. Any label
  using one needs `lv_font_montserrat_14` set explicitly, or it draws a tofu box
  while every other label is fine.
- **`lv_image_set_scale()` does not resize the object.** It scales what is drawn
  and leaves the box at the source size, so a 420 px asset shown at 0.6× still
  occupies 420 px for layout *and hit-testing*. Bottom-aligned art floats high
  and drags aimed at the visible image miss it. Use `make_img_sized()`.
- **`lv_obj_align()` is not a one-shot move.** LVGL re-applies it on every layout
  pass, so `lv_obj_set_pos()` on an aligned object is silently undone — a drag
  looks completely dead. Break the alignment on `LV_EVENT_PRESSED` first.
- **`lv_obj_fade_in()` leaves objects at opa 0** in this SDL/LVGL build (the same
  trap `wini_ui` documents). Animate `LV_STYLE_OPA` explicitly — `alpha_fade_in()`.
- **ALSA's `default` device on this board is HDMI**, and playback there returns
  `audio open error: Unknown error 524`. The reSpeaker must be named:
  `plughw:CARD=Lite,DEV=0` (`ALPHABET_ALSA_DEVICE`).
- **`pkill -f alphabet_server` over SSH kills the SSH session**, because paramiko's
  command line contains that string via `python -m pi_game.alphabet_server`. Kill
  in a *separate* call from the one that starts it, and bracket the pattern.
- **Don't time-synchronise tests.** A letter's first run pays for cloud TTS and
  every later run replays from disk seconds faster, so fixed sleeps photograph
  the wrong stage. `shoot_stages.sh` waits on `STAGEMARK` log lines instead.
- **Synthetic drags need pauses.** LVGL samples the pointer at ~30 Hz; a press
  followed immediately by movement can land in one poll, so the press registers
  at the already-moved position and no drag starts. This passed for one letter
  and failed for the next on identical code. `touchsim.do_drag` settles 300 ms
  after the press and before the lift.
- **`wlrctl` cannot drag.** Each invocation creates a virtual pointer, sends one
  action, then exits and destroys it — so a press and the motion after it come
  from *different* devices and the compositor never sees a held drag. Taps work,
  which makes this deceptive. Inject through `/dev/uinput` instead so one process
  owns the whole gesture (`touchsim.py`).
- **A new uinput device needs a settling pause.** libinput has to notice it and
  the compositor has to add it to the seat; without ~1 s the first gesture of a
  run is silently swallowed.
- **Never drag by accumulating `lv_indev_get_vect()`.** Summing per-frame deltas
  drops motion whenever events are coalesced (a fast flick) and drifts over a
  long gesture. Re-derive the position from the *absolute* pointer each frame
  with a grab offset — that is self-correcting, so any error is erased on the
  next frame instead of accumulating. `food_drag_cb()` is the reference.
- **Handle `LV_EVENT_PRESS_LOST` as well as `RELEASED`.** If the finger slides off
  the object or a parent claims the gesture, no `RELEASED` ever arrives and a
  dragged object is left stranded mid-screen.
- **Substring matching against a one-character target accepts almost anything.**
  `"a" in "banana"` is true, so `banana` and `elephant` both scored as correct
  attempts at **A**, and `blue` at **B**. Match word-wise against real targets;
  never `t in heard` when `t` may be a single letter.
- **`"no" not in reply` makes an EMPTY model reply a silent pass.** Gemini 2.5
  Flash can return empty text (the thinking-budget gotcha), and that was landing
  as "correct". Check for an explicit `yes` / `no` prefix and treat anything else
  as an outage.
- **"Be generous" in a judge prompt is taken literally.** Told to accept anything
  "plausible", Gemini passed `blue` as an attempt at *buh* and `cat` at *kuh* —
  a word that merely begins with the sound. The prompt has to say outright that
  saying a word starting with the letter is not saying the sound.

## Deviations from the spec

Three, each deliberate:

1. **LVGL/C, not Flutter** (§4). Flutter ships no arm64 Linux desktop engine, so
   the only real option was the third-party `flutter-elinux` toolchain. The
   tutor's LVGL stack is already proven on this exact panel and is reused
   wholesale (engine, build pattern, IPC transport). *Approved by the user.*
2. **Cloud voice, not Whisper + Piper** (§13, §20.5). The project's hard mandate
   is that all inference is cloud (Vertex Gemini, Cloud STT/TTS) and nothing runs
   locally on the device. Every spoken line is pre-synthesized to disk, so the
   lesson still *plays* offline; only a cache miss needs the network.
   *Instructed by the user.*
3. **The mini activity adapts to the object.** §Stage 6 describes "Feed Apple",
   which is charming for the apple and wrong for the other 25 letters — applied
   literally it asks a child to feed the robot a cat, a drum and a zebra. The
   interaction is unchanged (drag the object to Wini, still exactly one activity),
   but only the five edible objects are eaten ("I am hungry… Yummy!"); the rest
   are handed over ("Can you bring me the…?" / "Thank you! I like it."), and the
   robot only opens its mouth for food. `content.EDIBLE` holds the list.

## Stage 4 — how the speech check actually decides

Three gates, cheapest first (`speech.judge_attempt`):

1. **Silence** → not a match. Worth one retry, costs nothing.
2. **Word-wise match** against the phoneme, its spoken spelling, and the letter's
   name (`LETTER_NAMES`). Near-misses count only when *both* strings are short,
   so a real word can never qualify here.
3. **Gemini** decides the rest — but only for short utterances; a long phrase is
   plainly not a child saying one sound, and is rejected without a call.

Two attempts, then the lesson moves on either way (§Stage 4, no failure state).
The move-on line is **`repeat_move_on`, not `repeat_ok`**: praising a sound the
robot never heard, on every lesson, is both dishonest and useless to a child who
is struggling — and it was the reason the feedback looked untrustworthy. Any
cloud failure still resolves to a pass; an outage must never read as "you were
wrong". `speech_matched` counts only genuine matches, so `/parent` stays truthful.

Regression set (21 cases, all passing) is in the test block used during the fix —
re-run it after touching the matcher:

```bash
.venv/bin/python -c "from pi_game.speech import judge_attempt as J; print(J('banana','A','ah','aah'))"   # must be False
```

## Not built yet

- **Phase 6 robot expressions** (LED, ears, head). The ears are disabled on this
  hardware anyway — see `EAR_ACTUATION_ISSUE.md`. The face states in
  `assets/common/` are the on-screen stand-in.
- **Stage 4 real-mic accuracy is unmeasured.** The *matcher* is now covered by a
  21-case regression set, but every on-device run has been over SSH, where there
  is no PipeWire seat and the mic returns silence. What is still unverified is
  the link before the matcher: whether Cloud STT transcribes a small child saying
  a bare phoneme usefully at all. That needs one run launched from the panel or
  VNC with someone actually speaking; `LETTER_NAMES` and the phoneme spellings
  are the things most likely to need tuning against real transcripts.
