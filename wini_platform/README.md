# wini_platform — the ROS-less device platform (one process)

Implementation of `WINI_ROSLESS_PLATFORM_PLAN.md` §4–§6: the five ROS platform
channels become direct calls inside a single Python process. **Status: DEPLOYED
on the Jetson 2026-07-04 and the boot default** (`@reboot` crontab →
`~/run_wini_platform.sh`; old ROS line kept commented as rollback). Stage 1 demo
ran clean on the panel, Stage 2 no-touch baseline passed, Stage 3 served a real
voice turn; remaining human checks + measurements are listed in the plan doc's
stage table (runbook §16 has the bring-up commands).

> Naming: the plan drafted this as `platform/`, but a top-level Python package
> named `platform` shadows the stdlib `platform` module (imported by requests,
> torch, sounddevice…), so the package is `wini_platform` and it lives inside
> the study-core checkout — one repo to deploy, `~/wini/core` on the device.

## Layout

| File | Role | Origin |
|---|---|---|
| `display/eyes.py`, `display/wini_face.py`, `display/wini_display_driver.py` | face renderer + ST7796S SPI driver | verbatim copies of the 2026-07-04 `device_snapshot/display_controll/` |
| `display/display_thread.py` | `DisplayThread` — single panel owner, 30 fps; emotion/gaze setters + overlay slot (no image topic, no keepalive; callers compose un-flipped, `show_overlay` applies the §7.2 panel-mirror pre-flip in one place) | port of `wini_display.py` main loop |
| `display/demo.py` | Stage 1 acceptance demo | new |
| `touch/serial_head.py` | `SerialHead` — single owner of the head STM32 port; TC/TH/IMU callbacks; `W_EKP:80` + `W_DH` init (ears hold upright; animator dropped — dead code) | port of `serial_base.py` + `wini_head_node.py` |
| `touch/demo.py` | Stage 2 acceptance demo | new |
| `ui_cards.py` | loading/ready/awake/failed text cards (un-flipped RGB arrays) | port of `wini_touch_trigger.render()` |
| `supervisor.py` | chin-hold state machine, blush reflex, thinking face, brain-server monitor, ClientThread | port of `wini_touch_trigger.py` + `wini_chin_reaction_node.py` |
| `__main__.py` | `python3 -m wini_platform` | new |
| `wini-platform.service` | Stage 4 systemd user unit | new |

Client side (in `wini_client/`): `display_sinks.InProcSink` (same
`image_path`/SD-card metadata contract as the ESP32 — resolves against the
local store, letterboxes to 480×320 un-flipped, hands the array to the
DisplayThread which pre-flips for the mirrored panel) and
`client.run_session(...)` (the mic→turn→speak loop as a stoppable library
call; the CLI `python -m wini_client.client` is unchanged). `play_pcm` keeps
ONE persistent output stream open across turns — the C-Media USB codec clicks
on every stream open/close, so per-utterance `sd.play()` popped at TTS start
and stop; a 10 ms fade at each end kills waveform-edge clicks too.

## Stage tests (run on the Jetson)

⚠️ Before any test: stop the ROS platform first — one owner per device.
`pkill -f "wini_display|wini_head_node|wini_chin_reaction|wini_touch_trigger"`

- **Stage 1** `python3 -m wini_platform.display.demo` — emotions cycle, gaze
  sweeps, calibration card upright (corners TL/TR/BL/BR readable, arrow up),
  loading card animates, figure crop shows then auto-reverts to the face.
- **Stage 2** `python3 -m wini_platform.touch.demo` — 40 s untouched = 0
  presses; one 5 s hold per sensor = exactly one DOWN/UP pair, no bounce.
- **Stage 3** `python3 -m wini_platform` — full UX cycle: chin hold → Loading…
  → Ready → voice turn with thinking face → figure on screen → “bye” → sleep →
  chin hold → fast wake.
- **Stage 4** install `wini-platform.service` (header has the commands),
  power-cycle ×3.
- **Stage 5** measure RAM/boot-to-face/latency and record them in
  `WINI_ROSLESS_PLATFORM_PLAN.md` §7 (never write an unmeasured number).

Dev flags (no hardware): `--fake-display --no-touch`, and
`python3 -m wini_platform.display.demo --fake`.

## Dependencies

Two requirement files (unpinned — match the device venv):

| File | Install where | Covers |
|---|---|---|
| `requirements.txt` | every OS | supervisor, software display (`--fake-display`), touch parser, in-proc client |
| `requirements-device.txt` | Jetson / RPi only | the ST7796S SPI panel driver (`adafruit-blinka`, `adafruit-circuitpython-rgb-display`); pulls in `requirements.txt` too |

```
# laptop / dev box (no SPI panel):
pip install -r wini_platform/requirements.txt
# on the Jetson / a Pi-class board with the real panel:
pip install -r wini_platform/requirements-device.txt
```

`sounddevice` needs the PortAudio runtime: bundled in the wheel on **Windows**,
`brew install portaudio` on **macOS**, `sudo apt install libportaudio2` on
**Debian/Ubuntu/Jetson**.

The brain service (`wini_server.py`) is a SEPARATE process with its own heavier
deps in the **repo-root `requirements.txt`** (Vertex/Gemini SDK, faiss, …) plus a
`.env` and Google ADC credentials — see `JETSON_PIPELINE_RUNBOOK.md` §14. Run the
brain only where the brain lives; the platform reaches it over HTTP (`--server`).

Gotchas that still apply: PulseAudio USB pinning runs automatically at client
start (`WINI_AUDIO_SELECT` overrides the script path, Linux only); SPI/GPIO group
permissions must be verified on the fresh venv; the client thread stops via
`stop_event` (PortAudio reads ignore signals); ears stay off (firmware defect,
`EAR_ACTUATION_ISSUE.md`).

## Running on another OS (Windows / macOS / any Linux)

`wini_platform` is the Jetson *device* orchestrator: it owns the SPI face panel,
the STM32 touch/head board, and an in-process copy of the thin client (mic →
brain → speaker + display). Only two pieces are hardware-bound — the **SPI panel**
(`--fake-display` swaps in a pure-numpy `NullDriver`) and the **STM32 board**
(`--no-touch` skips it entirely). Everything else is portable Python, so the
platform brings up on a laptop against a local or remote brain.

**Audio is portable with no code change.** The client tries PulseAudio's `"pulse"`
device (the Jetson's USB mic/speaker routing) and **automatically falls back to
the OS default input/output device** when there is no PulseAudio — so on Windows
and macOS you simply get the laptop's default mic and speakers. (The supervisor's
boot-time mic-settle probe also targets `"pulse"`; off-Jetson it just retries for
a few seconds before proceeding — harmless, and skipped entirely in the headless
shape below.)

### Run shapes

Run every command **from the repo root** (`cloud CLI/`, the parent of
`wini_platform/`) so `wini_server.py` and the `wini_client` import resolve:

| Goal | Command | Hardware |
|---|---|---|
| Jetson device (full) | `python3 -m wini_platform` | SPI panel + STM32 + USB audio |
| Laptop, real audio | `python3 -m wini_platform --fake-display --no-touch --autostart --server <brain-url>` | default mic + speaker |
| Headless / CI (no audio) | `python3 -m wini_platform --fake-display --no-touch --server <brain-url>` | none (no trigger ⇒ no session) |

- `--autostart` starts the client immediately — there is no chin sensor to hold
  off-device; without it (and without a touch board) the supervisor just idles.
- `--no-manage-server` when the brain is remote / already running / on Cloud Run,
  so the supervisor never tries to spawn `wini_server.py` locally.
- `--store <dir>` points at the local `rag_store/` copy that holds
  `figure_crops/` (the device's "SD card"); defaults to the one in the checkout.

### Step by step (laptop)

1. **Python 3.10+** (3.12 is fine) and the PortAudio runtime for your OS (above).
2. **Get a brain.** Either run it locally in one terminal — from the repo root
   `pip install -r requirements.txt` then `python wini_server.py` (needs `.env` +
   `gcloud auth application-default login`) — or point `--server` at an
   already-running / Cloud Run URL and skip this.
3. **Install the platform** in a venv (do NOT install `requirements-device.txt`
   off-device — that's the SPI panel driver):
   ```
   python -m venv .venv
   . .venv/bin/activate            # Windows: .venv\Scripts\activate
   pip install -r wini_platform/requirements.txt
   ```
4. **Run** the laptop shape, e.g.:
   ```
   python -m wini_platform --fake-display --no-touch --autostart \
       --server http://127.0.0.1:8123
   ```
   Speak; the reply plays on your default speakers. `Ctrl-C` stops it cleanly.

No brain and no hardware? `python3 -m wini_platform.display.demo --fake` renders
the face / emotions / cards through the `NullDriver` — a quick way to exercise the
render path on any OS with nothing attached.
