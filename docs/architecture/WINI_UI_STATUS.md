# Wini Touch UI — What Works & How It Maps to the Brain

> **Scope:** the LVGL touch UI (`wini_ui/`) on the **winipi5** Raspberry Pi 5 dev board
> (Waveshare 7″ DSI, portrait 600×1024), and how a card tap flows through the voice
> client into the Part 12 pedagogy modes in the brain.
> **Status date:** 2026-07-16. **Device:** winipi5.local, checkout
> `/home/winipi5/cloud_tutor/cloud-CLI` (Part 12 files deployed, uncommitted).
> **Note (2026-07-16):** the `wini_ui/` picker described here has been rebuilt into a full
> screen system (theme + widgets + overlays + screens + an FSM/IPC layer). §9 below is the
> authoritative summary of the rebuilt UI; the working log is `wini_ui/UI_REBUILD_STATUS.md`.
> This is a *device/UX status* doc — it sits below the 4-doc lockstep set and carries no
> authoritative contract. Source of truth for the mode contracts is
> `PART12_PEDAGOGY_MODES_PLAN.md` + `learner_cognitive_state_architecture.md`.

---

## 1. The three running processes

The device experience is three cooperating processes, all on the Pi:

```mermaid
flowchart TD
    UI["<b>wini_ui</b> (C, LVGL + SDL2)<br/>fullscreen DSI, 600×1024<br/>3 cards: Explain / Practice / Test"]
    CLIENT["<b>wini_client.client</b> (Python)<br/>mode channel :8140 · VAD mic · TTS speaker"]
    BRAIN["<b>wini_server.py</b> (Python)<br/>Cloud STT → TutorLoop/Gemini → Cloud TTS<br/>:8123"]

    UI -- 'TCP :8140  {"event":"mode_selected","mode":"TEST"}' --> CLIENT
    CLIENT -- "POST /voice_turn  (X-Wini-Mode: TEST, raw PCM)" --> BRAIN
    BRAIN -- "turn dict: answer + audio + display[] + mode" --> CLIENT
    CLIENT -- "TTS on speaker · card details to console" --> UI
```

| Process | Binary / entry | Port | Role |
|---|---|---|---|
| **LVGL picker** | `wini_ui/build/wini_ui` | connects → 8140 | Touch mode selection. Fullscreen, borderless (no close button). |
| **Voice client** | `python -m wini_client.client` | serves 8140 | Owns the mode channel, mic (VAD), speaker (TTS). Stamps `X-Wini-Mode`. |
| **Brain** | `wini_server.py` | serves 8123 | STT + TutorLoop (Gemini) + TTS. Records the mode, runs the pedagogy. |

---

## 2. The UI → what each card does

The picker (`wini_ui/mode_select.c`) shows one full-width card per mode. A tap opens a
short-lived TCP connection to the client's **mode channel** (`127.0.0.1:8140`,
`wini_client/mode_channel.py`) and sends one newline-delimited JSON object.

| Card (color) | Subtitle | Sends `mode` | Brain behavior |
|---|---|---|---|
| **Explain** (blue) | "Learn something new" | `EXPLAIN` | Normal tutoring — **byte-identical to pre-Part-12**. |
| **Practice** (green) | "Try it together" | `PRACTICE` | Adaptive fading ladder: worked example → completion step → isomorphic problem. |
| **Test** (orange) | "Show what you know" | `TEST` | 5-item quiz, generated at serve time, graded, 80% mastery gate. |

If nothing is listening on 8140 (client down), the picker shows a **"waiting for Wini…"**
fallback and retries on the next tap — it is a lazy TCP client by design.

---

## 3. How a tap becomes a pedagogy mode

Two independent paths can set the mode; both are live:

1. **Touch (the UI):** tap → `mode_channel` → `client.self.mode` → the client stamps the
   HTTP header **`X-Wini-Mode`** on the next `/voice_turn`. The brain records it up front:
   `wini_server.py` → `if mode: session["mode"] = mode` (before the turn runs).
2. **Voice (spoken cue):** inside `TutorLoop.turn()`,
   `self.modes.resolve_mode(session, text, cue=mode_cues(text))`
   (`session_modes.py`) lets a spoken *"test me"* / *"let's practice"* / *"stop"* switch or
   override the mode mid-turn.

**Precedence:** the tap sets `session["mode"]` at the *start* of the turn; a mode cue in the
*spoken* text of that same turn overrides it; otherwise the tapped mode holds. `--wait-for-mode`
makes the client block its very first turn until a tap arrives, so the picker is the genuine
entry point. No header + no cue ⇒ `EXPLAIN` ⇒ today's behavior (safe default, ESP32-safe).

The brain echoes the resolved mode back in the turn dict (`"mode": resolved_mode`) and in the
learning log, so every turn is attributable to a mode.

---

## 4. What is working (verified)

| Capability | Status | Where verified |
|---|---|---|
| LVGL picker renders fullscreen on the DSI (600×1024, borderless) | ✅ Working | Screenshot, 2026-07-15 |
| Touch tap → `mode_selected` on :8140 | ✅ Working | Client log: `[mode] selected: EXPLAIN`; UI log: `tap TEST` |
| `X-Wini-Mode` pass-through → `session["mode"]` + echo | ✅ Working | `wini_server.py:138-155` |
| Spoken cue mode switch (*"test me"* etc.) | ✅ Working | `resolve_mode`; on-brain 2026-07-14 |
| **EXPLAIN** = pre-Part-12 baseline (no regression) | ✅ Working | Byte-identical decision surface, 2026-07-14 |
| **PRACTICE** adaptive ladder | ✅ Working | Live @ mastery 0.65 → ISOMORPHIC_PRACTICE, 2026-07-14 |
| **TEST**: 5-item runtime quiz gen + deterministic grade + 80% gate + spoken score | ✅ Working | 5/5 on FTA → gate pass, 2026-07-15 |
| Mic in — Cloud STT (16 kHz) | ✅ Working | STT transcript in log |
| Speaker out — Cloud TTS (24 kHz) **resampled to the device's 16 kHz** | ✅ Working | Fixed + verified 2026-07-15 (see §6) |

---

## 5. What is NOT wired yet (expectations)

| Gap | Detail |
|---|---|
| ~~The Python client doesn't yet EMIT the inbound commands~~ **RESOLVED 2026-07-16** | The emitter is live: `wini_client --display lvgl` builds a `ModeChannelSink` (display_sinks.py) that serializes each turn into `{"cmd":...}` lines on the mode-channel socket (`ModeChannel.send`, mode_channel.py). Verified with the real Gemini brain on the panel. **Sync fixes same day:** the header now follows the turn's concept via `{"cmd":"lines","l1":"Chapter N","l2":"Topic"}` (pinned to the test's locked concept while a set is serving), and the screens' hard-coded demo content (Chapter 4 header, formula/illustration cards, permanent ✓ Correct banner, fake progress) was removed/hidden so the panel can never show content the brain didn't send — the "old chapter title/image stays after a topic shift" bug. |
| **Brain figure images** ~~not wired~~ **RESOLVED 2026-07-17** | The T9 figure crops the brain selects (`display[]` items carrying `image_path`, e.g. the NCERT parabola / triangle / distance-formula diagrams) now paint on the panel. `ModeChannelSink._emit_figure` resolves the crop against the local store, scales it to fit the card, writes a PNG under `/tmp/wini_fig_{0..3}.png` (cycled), and sends `{"cmd":"figure","path":..,"caption":..}`; a turn without a figure sends `{"cmd":"figure","off":1}`. The UI's `widgets/figure_card.c` (an `lv_image` + caption, bound on explain+practice) loads it via the POSIX FS driver + lodepng. **Verified end-to-end on winipi5** (3 distinct brain images rendered — Fig. 2.2 parabola, Fig. 6.8 similar figures, Fig. 7.3 distance formula). **Gotcha found + fixed:** LVGL's default BUILTIN allocator is capped at `LV_MEM_SIZE` (was 1 MB) and silently OOMs decoding a ~370 KB full-page crop alongside all 8 persistent screens — the PNG drew blank. Switched `lv_conf.h` to `LV_USE_STDLIB_MALLOC 1` (C-library malloc) — no cap on the Pi. The formula/illustration *demo* cards still stay HIDDEN (no IPC command drives them). |
| **Stage 5 perception signals** | Deferred. Mode requests are detected by **deterministic cues** (which work); the learned `practice_request`/`test_request` signal is an optimization, not a dependency. |
| **Boot integration** | The picker + client are started manually (see §7); folding `wini_ui` into `wini_platform/supervisor.py` for auto-start on boot is a follow-on. |

---

## 6. Audio path (and the fix made 2026-07-15)

- **STT:** mic → default input device (ReSpeaker Lite) @ **16 kHz** → brain → Cloud STT.
- **TTS:** brain returns Cloud TTS PCM @ **24 kHz** → client plays on the speaker.
- **The device only does 16 kHz.** The ReSpeaker Lite's raw hw output supports **only 16 kHz**,
  and PortAudio here exposes *no* Pulse/plug device to resample. The client used to ask the
  speaker for 24 kHz and crashed (`Invalid sample rate [-9997]`), which took down the mode
  channel and caused the "waiting for Wini…" state.
- **Fix:** `wini_client/client.py` playback now **resamples TTS to whatever rate the output
  device accepts** (scipy `resample_poly`, 24k→16k here), preferring Pulse only where it's
  genuinely present (Jetson). The brain stays device-agnostic (keeps emitting 24 kHz).

---

## 7. How to run it (winipi5)

Brain, then client (opens the mode channel), then the picker:

```bash
cd /home/winipi5/cloud_tutor/cloud-CLI

# 1) Brain
GEN_BACKEND=gemini nohup .venv/bin/python wini_server.py --port 8123 >/tmp/wini_brain.log 2>&1 &
#   poll until: {"ready": true, "gen_backend": "gemini"}
curl -s http://127.0.0.1:8123/health

# 2) Voice client — mode channel + always-listening mic, gated on the first tap
WINI_SERVER=http://127.0.0.1:8123 \
  nohup .venv/bin/python -u -m wini_client.client \
    --display console --trigger vad --ui-port 8140 --wait-for-mode \
    >/tmp/wini_client.log 2>&1 &

# 3) LVGL picker on the DSI (X11 :0)
DISPLAY=:0 XAUTHORITY=$HOME/.Xauthority nohup ./wini_ui/build/wini_ui >/tmp/wini_ui.log 2>&1 &
```

Then **tap a card and speak** (e.g. tap **Test** → *"test me on polynomials"*). Watch the flow:

```bash
tail -f /tmp/wini_client.log      # mode selected, STT, action, latency, card contents
tail -f /tmp/wini_ui.log          # tap events + connect status
```

- Trigger is VAD (always-listening); background noise can register as a turn. Push-to-talk
  is `--trigger enter`.
- The picker is borderless-fullscreen — no close button. Stop it with `pkill -f build/wini_ui`
  (or Alt+F4 on a keyboard).

---

## 8. One-line summary

**Tap → mode → voice pedagogy works end-to-end** (Explain / Practice / Test, with spoken
questions, grading, and the 80% gate). The UI can now *show* the turn (screens, overlays,
cards, progress) — the reserved client→UI channel is built and verified on the UI side (§9);
the only remaining seam is the Python client **emitting** those command lines instead of
logging them.

---

## 9. Rebuilt `wini_ui` + the inbound command channel (2026-07-16)

The single dark 3-card picker (`mode_select.c`) was rebuilt into the full paper-like UI from
the design spec, in five verified stages (working log: `wini_ui/UI_REBUILD_STATUS.md`):

1. **Foundation** — `theme/` (one source of color/serif-type/spacing), bundled DejaVu Serif, and
   the fixed HEADER / CONTENT / FOOTER `chrome/`.
2. **Widgets** — `widgets/` (stage/status chips, segmented progress bars, hint dots, question /
   explanation / formula / illustration / result cards, answer feedback, dialog, toast).
3. **Overlays** — `overlays/` voice states (listening / thinking + sub-states / loading /
   celebration), calm opacity-only motion.
4. **Screens** — `screens/screen_mgr` (persistent screens, opacity crossfade) + splash, idle
   (the paper home launcher, replaces the dark picker), explain, practice, test, result,
   settings, error.
5. **Event layer** — `app/app_state` FSM + a bidirectional `ipc.c` (background reader thread),
   `platform/brightness.c` (backlight sysfs, capped 35%), `platform/audio_fx.c` (SDL2 audio cues).

**UI→client events (2026-07-16):** besides `{"event":"mode_selected","mode":..}`, the UI sends
`{"event":"pause","on":0|1}` from the floating **pause button** (bottom-right, above the footer,
`widgets/pause_button.c`). While on=1 the client mutes the mic and runs no brain turns (aborts an
in-flight recording, drops a captured utterance, skips speech on an in-flight turn); the second
tap resumes. The button turns soft-orange "Mic off - resume" and sets the status chip to Offline.
Events carry the absolute on-value, so a duplicated delivery is harmless (idempotent).

**One-press start (2026-07-16; warm-gated 2026-07-20):** `run_wini_package.sh` (repo root) starts
brain + client (`--display lvgl --ui-port 8140 --wait-for-mode --on-session-end exit`) + `wini_ui`,
idempotent (exits if all three already run; kills a half-set first). On winipi5 the desktop icon
`~/Desktop/Wini.desktop` runs it (canonical copy: `Wini.desktop` at the repo root) — launch from the
panel/desktop (NOT bare SSH) so the processes inherit the desktop audio session.

The UI is now started **only after `/health` reports `ready`** (poll, 180 s cap), so the panel stays
dark through the ~15 s warmup and lights up working instead of showing a picker whose taps go
nowhere — that dead picker was the whole "the desktop icon isn't the same as the script" report.
Concurrent launches are serialized by `flock` on `logs/.launch.lock`, and the script tees to
`logs/launch.log` (the icon runs `Terminal=false`, so that file is the only record).

> **Gotcha (cost a debugging cycle):** every long-lived child must be spawned with `9>&-`. Without
> it the child inherits the lock fd and holds the lock after the launcher exits — the leak came out
> through `wini_ui` → close button → `stop_wini_package.sh` → `touch_service.py`, and the *next*
> icon tap then silently no-opped forever.

**Close button (2026-07-20):** `widgets/close_button.c`, a floating pill bottom-LEFT (mirroring the
pause pill bottom-right, so the two are never adjacent to a mis-tap). Tap → a confirm dialog
("Finish for now?" / Keep going · Close Wini) — a stray tap from a child must not end the session.
Confirming runs `$WINI_STOP_CMD` (set by the launcher to `stop_wini_package.sh`) detached via
`setsid`, which kills brain + client + UI and resumes the background touch-emotion service, then
requests its own quit so the panel clears even where the script is absent.

**The client→UI contract (now implemented, UI side).** Newline-delimited flat JSON on the same
`127.0.0.1:8140` connection the UI already uses for `mode_selected`. `app_state` parses each and
drives the live screen:

| Command | Effect |
|---|---|
| `{"cmd":"ready"}` | brain is warm — releases the splash to Idle (2026-07-20). Sticky: the client re-sends it to every UI that connects, because the launcher starts the UI *after* the brain is ready. Ignored unless the splash is showing, so it can't yank a student mid-session. |
| `{"cmd":"screen","to":"idle\|explain\|practice\|test\|result\|settings\|error"}` | crossfade to a screen |
| `{"cmd":"status","v":"listening\|thinking\|teaching\|checking\|waiting\|offline"}` | header robot-status chip |
| `{"cmd":"stage","v":"explain\|practice\|test"}` · `{"cmd":"lines","l1":..,"l2":..}` | header stage chip / topic lines |
| `{"cmd":"progress","stage":..,"done":N,"of":M}` | footer segmented bar |
| `{"cmd":"question","n":..,"text":..}` · `{"cmd":"explain","title":..,"body":..}` | set the current card |
| `{"cmd":"feedback","kind":"correct\|almost"}` · `{"cmd":"hint","level":N}` | practice feedback / hint dots |
| `{"cmd":"listening"\|"thinking"\|"loading","on":0\|1, ...}` | show/hide a voice-state overlay (parented to CONTENT — chrome stays visible) |
| `{"cmd":"score","score":N,"of":M,"caption":..}` | fill the result card + go to Result |
| `{"cmd":"celebrate","msg":..}` · `{"cmd":"brightness","pct":N}` | celebration overlay / backlight |
| `{"cmd":"figure","path":"/tmp/wini_fig_0.png","caption":..}` · `{"cmd":"figure","off":1}` | show a brain figure crop on the current screen's figure card / hide it (2026-07-17) |

**Verified end-to-end against one full PRACTICE turn (2026-07-16, on the panel).** A stand-in
`wini_client` listened on :8140, launched the UI, tapped **Practice** (UI → `mode_selected:PRACTICE`
received), then streamed the turn back: `question` → `status:listening`+`listening:on` →
`status:thinking`+`thinking:on(understanding)` → `status:checking`+`feedback:correct`+`progress 3/5`
→ `celebrate`. Each beat was screenshot-confirmed: the status chip, the content-region overlays
(header/footer staying visible), the question text, the ✓ Correct banner, the footer advancing, and
the "Well done" badge auto-dismissing back to practice. On winipi5 **brightness is live**
(`/sys/class/backlight/11-0045`, capped 35%) and the **audio device opens** for cues.

**Remaining integration (Python side):** add a display sink in `wini_client` that writes these
command lines onto the mode-channel socket (the brain already produces the equivalent turn state
via `tutor_loop._mode_display` / `wini_platform/ui_cards.py`), replacing the `--display console`
path for the DSI. That is the one seam between "verified with a stub" and "driven by the real brain."
