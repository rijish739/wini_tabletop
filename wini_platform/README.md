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

## Dependencies (device venv, no `--system-site-packages`)

```
numpy opencv-python sounddevice requests pyserial
adafruit-circuitpython-rgb-display adafruit-blinka
```

Gotchas that still apply: PulseAudio USB pinning runs automatically at client
start (`WINI_AUDIO_SELECT` overrides the script path); SPI/GPIO group
permissions must be verified on the fresh venv; the client thread stops via
`stop_event` (PortAudio reads ignore signals); ears stay off (firmware defect,
`EAR_ACTUATION_ISSUE.md`).
