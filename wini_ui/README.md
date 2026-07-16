# wini_ui — LVGL touch UI

The device's on-screen UI: a calm, matte **paper** interface (theme + widgets + overlays +
persistent screens + an event-driven FSM) for the Part 12 pedagogy modes
(`PART12_PEDAGOGY_MODES_PLAN.md` §4.1). It opens on a home launcher — three tappable cards
**Explain / Practice / Test** — and, once a session starts, shows the header stage/status, the
question/explanation/formula/result cards, the voice-state overlays (listening / thinking /
loading / celebration), and footer progress, all driven by the brain over the IPC channel.
Written in **C with LVGL v9** on purpose: the same code is portable to the eventual **ESP32-P4**
thin client. On the Raspberry Pi 5 dev board it renders through the **SDL2** backend as a
fullscreen X11 window on the DSI Waveshare panel (portrait 600×1024, visible over VNC).

> **Rebuild status & architecture:** `UI_REBUILD_STATUS.md` (the 5-stage working log) and
> `../WINI_UI_STATUS.md` §9 (device-doc summary + the inbound command table). The single-screen
> `mode_select.c` below is the LEGACY picker, superseded by `screens/idle.c` and no longer compiled.

```
 [wini_ui  (C, LVGL+SDL2)]  --tap "Practice"-->  TCP 127.0.0.1:8140
        │  {"event":"mode_selected","mode":"PRACTICE"}\n
        ▼
 [wini_client (Python)]  --X-Wini-Mode: PRACTICE-->  [wini_server (brain)]
```

## IPC contract

Newline-delimited JSON over TCP. **The Python client is the server** (listens on
`127.0.0.1:8140`, see `wini_client/mode_channel.py`); **wini_ui is the client**
(connects lazily, retries once on a stale socket).

- **UI → client (implemented):** `{"event":"mode_selected","mode":"EXPLAIN|PRACTICE|TEST"}`
- **client → UI (implemented, UI side):** flat `{"cmd":...}` command lines drive the FSM
  (`app/app_state.c`) — `screen` / `status` / `stage` / `lines` / `progress` / `question` /
  `explain` / `feedback` / `hint` / `listening` / `thinking` / `loading` / `score` / `celebrate`
  / `brightness`. Full table + one-full-turn verification: `../WINI_UI_STATUS.md` §9. The Python
  **emitter** in `wini_client` (a display sink onto this socket) is the remaining integration step.

## Build (Raspberry Pi / Linux, X11)

```bash
sudo apt install build-essential cmake libsdl2-dev git

# LVGL v9 as a sibling of the C sources (submodule, or a direct clone):
cd wini_ui
git clone --depth 1 --branch release/v9.2 https://github.com/lvgl/lvgl.git lvgl
# (or, once wired as a submodule: git submodule update --init wini_ui/lvgl)

cmake -B build .
cmake --build build -j4
```

## Run

```bash
./run_wini_ui.sh                 # DISPLAY=:0, connects to 127.0.0.1:8140
./run_wini_ui.sh --port 8140 --host 127.0.0.1 --size 600 1024   # overrides
```

Start the voice client with the mode channel enabled so taps have a listener:

```bash
python -m wini_client.client --ui-port 8140 --wait-for-mode \
       --server http://127.0.0.1:8123
```

`--wait-for-mode` makes the picker the genuine entry point (the client blocks its
first turn until a card is tapped). Without `--ui-port`, the client behaves exactly as
before (mode = EXPLAIN, no header sent).

## Porting to the ESP32-P4

The LVGL screen code (`mode_select.c`) carries over unchanged — only two seams differ:
the display/input drivers (SDL2 here → the P4's panel + touch driver there) and
`ipc.c` (the TCP socket collapses to a direct in-firmware call, since the UI and the
client run in one process on the MCU).

## Files

| File | Role |
|---|---|
| `main.c` | LVGL init, SDL2 display + input, tick source, event loop |
| `mode_select.c/.h` | the three-card screen + tap handlers |
| `ipc.c/.h` | mode-channel TCP client (lazy connect, timeout, retry) |
| `lv_conf.h` | minimal LVGL config (SDL, 32-bit color, fonts) |
| `CMakeLists.txt` | build (links `lvgl` + `SDL2`) |
| `run_wini_ui.sh` | `DISPLAY=:0` launcher |
