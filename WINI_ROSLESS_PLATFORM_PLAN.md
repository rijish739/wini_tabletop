# Wini ROS-less Platform — Design & Migration Plan

> **Status: PLANNED (not started).** This document is the blueprint for replacing the
> ROS 2 stack on the device with a single lightweight Python process. Nothing in the
> running system has been changed for this yet; the current bring-up remains
> `jetson_platform/run_boot_platform.sh` (+ chin-hold → `run_thin.sh`) as documented in
> `JETSON_PIPELINE_RUNBOOK.md` §15. Written 2026-07-04.

## 1. Why remove ROS 2

The product pivoted to a **thin client + cloud brain** (CLAUDE.md deployment mandate):
the device is mic + speaker + display + touch; every model call happens in
`wini_server.py` (Vertex Gemini / Cloud STT / Cloud TTS). The final target device is an
**ESP32-P4**, which will never run ROS. What ROS still does on the Jetson today is
*intra-device glue on a single machine* — five small local channels between processes
that could be one process.

Measured/observed costs of keeping ROS for this:

| Cost | Evidence |
|---|---|
| DDS discovery drops | first `ros2 topic pub` silently lost without `-w 1` (runbook §8) |
| Cold CLI daemon flakiness | `ros2 topic hz`/`echo` printing nothing inside short timeouts (§15.3); a CLI echo crashed mid-init during the 2026-07-04 thinking-face test |
| Keepalive contract | display node needs frames re-published > 2 Hz or it reverts to the face (§7.1) — pure plumbing overhead |
| Boot complexity | two colcon workspaces must be sourced in the right order; symlink-install semantics; launcher-script pattern for every node (§2.1) |
| Memory | each rclpy Python node is a full interpreter + DDS participant (~60–120 MB each; 5 platform processes) |
| Divergence from target | the ESP32 port cannot reuse any of the topic plumbing — only the plain-Python parts carry over |

**Decision hinge (from the 2026-07-04 discussion):** if the robot's wheels/arms/nav
(`wini_drive_node`, `wini_arm_node`, nav/slam packages) are part of the product, KEEP
ROS as the hardware bus and skip this migration. If the product is the desk tutor,
this plan applies, and doubles as the dress rehearsal for the ESP32 port.

## 2. What is already ROS-free (do not touch)

| Piece | File(s) | Notes |
|---|---|---|
| Brain service | `wini_server.py` | stdlib `http.server`; the future Cloud Run artifact |
| Client core | `wini_client/client.py` | numpy + sounddevice + requests; RMS VAD, HTTP turns, filler/NDJSON parsing, sleep-on-farewell |
| Display driver | `device_snapshot/display_controll/wini_display_driver.py` | ST7796S over SPI via `adafruit_rgb_display` + Blinka (`board`, `digitalio`); portrait panel, landscape canvas, rotation + full-refresh logic all inside |
| Face renderer | `device_snapshot/display_controll/eyes.py`, `wini_face.py` | pure numpy/cv2; emotions, blink, gaze, blush/tears/sparkle overlays |
| Head serial protocol | `device_snapshot/wini_hw_bridge/serial_base.py` | pyserial; finds the STM32 by USB product string, line-based telemetry (`TC`/`TH` touch, IMU, ear angles) |

The ONLY ROS-specific code is the thin node wrappers and the topic plumbing between
them. That is what this plan removes.

## 3. Current topic graph → in-process mapping

Today's five platform channels and their ROS-less replacements:

| ROS topic (today) | Producer → Consumer | ROS-less replacement |
|---|---|---|
| `/wini/display/image` (Image, 480×320 rgb8, >2 Hz keepalive, pre-flipped) | client sink → display node | direct call `display.show_overlay(rgb_array)` / `display.clear_overlay()`; no keepalive, no flip contract needed (renderer owns the panel) |
| `/wini/emotion` (String "NAME intensity") | trigger/chin nodes → display node | `face.set_emotion(name, intensity)` call |
| `/wini/eyes_target` (Point, projected gaze) | trigger node → display node | `face.set_gaze(gx, gy, z)` call — drop the ×1500 projection hack entirely |
| `/wini/head/touch_chin`, `/wini/head/touch_top` (Bool @ ~100 Hz) | head node → trigger/chin nodes | `TouchSensor` callbacks (`on_chin(level)`, `on_head(level)`) from the serial reader thread |
| `/wini/thinking` (Bool) | client → trigger node | direct call `platform.set_thinking(bool)` (client loop runs in the same process) |

Everything is one machine, one producer, one consumer per channel — plain function
calls and one lock-free flag each. No message bus library is needed; do **not**
introduce MQTT/ZeroMQ/etc. (that would be ROS-lite, same overkill).

## 4. Target architecture — ONE process: `wini_platform.py`

```
wini_platform.py  (single Python process, ~4 threads)
│
├── DisplayThread (30 fps)                  ← owns the ST7796S panel exclusively
│     wini_face.WiniFace renderer (eyes.py)
│     + overlay slot: figure crop | loading card | None(face)
│     + emotion/gaze/thinking state (plain attributes, written by other threads)
│
├── TouchThread                             ← owns /dev/ttyACM* (head STM32)
│     serial_base read loop (stripped of rclpy)
│     → chin-hold state machine (3 s hold, 0.3 s grace — port of
│       jetson_platform/wini_touch_trigger.py logic)
│     → chin-tap → blush reflex (port of wini_chin_reaction_node)
│
├── ClientThread                            ← owns mic + speaker (PulseAudio)
│     wini_client.client loop imported as a library
│     display sink = InProcSink (calls DisplayThread’s slots directly)
│     thinking signal = platform.set_thinking()
│     on session_ended: thread exits → platform idles (sleep); chin hold restarts it
│
└── Supervisor (main thread)
      starts/stops ClientThread on chin trigger; launches/monitors wini_server.py
      as a subprocess (or assumes it as a separate systemd service); loading card
      on the display while /health is not ready
```

Design rules:

1. **The display thread is the single owner of the panel** (it already is in the ROS
   node — `wini_display.py` main loop). Emotion, gaze, thinking, and overlay are just
   state it reads each frame. This deletes the whole image-topic/keepalive/flip
   contract: the renderer composes the figure crop itself, exactly like the face.
2. **The touch thread is the single owner of the head serial port.** Ears stay
   disabled (`EAR_DRIVE_ENABLED=False` — firmware defect, see `EAR_ACTUATION_ISSUE.md`);
   keep the `W_EKP:80` + homing init from `wini_head_node.on_connected` so the ears
   hold upright.
3. **Sleep = ClientThread not running** (mic closed). The brain server can stay warm —
   same UX as today's `--on-session-end exit` + `run_client.sh` wake.
4. **`wini_server.py` stays a separate process.** It is the Cloud Run artifact and must
   not be merged into the platform. The platform only starts/monitors it and polls
   `/health` (or, later, points at a Cloud Run URL and starts nothing).
5. **GIL note:** the 30 fps render is numpy/cv2 (releases the GIL), audio I/O is
   PortAudio callbacks (C threads), serial reads block in C. Four threads coexist fine;
   the old system proved the same workloads coexist as separate processes.

## 5. New on-device workspace layout

```
~/wini/                          ← replaces BOTH colcon workspaces for the tutor
├── core/                        ← the study core (this repo, minus dev-only dirs)
│   ├── wini_server.py  wini_client/  tutor_loop.py  perception/  voice/
│   ├── pacing/  cognitive_*/  concept_resolver/  policy_shadow/  query.py
│   ├── rag_store/  models/  persona.json  learner_state.json  .env
├── platform/
│   ├── wini_platform.py         ← NEW: the single process (section 4)
│   ├── display/                 ← copied from device_snapshot/display_controll/
│   │   ├── wini_display_driver.py  wini_face.py  eyes.py
│   ├── touch/
│   │   ├── serial_head.py       ← serial_base.py + wini_head_node telemetry parse,
│   │   │                          rclpy stripped (see section 6)
│   ├── ui_cards.py              ← loading/ready/failed text cards
│   │                              (from jetson_platform/wini_touch_trigger.py render())
│   └── wini-platform.service    ← systemd user unit (or crontab @reboot line)
├── .venv/                       ← ONE venv (see section 7)
└── logs/
```

No colcon, no `install/`, no `setup.bash`, no `--symlink-install`: edit → restart
process. The two old workspaces stay untouched on disk as rollback.

## 6. File-by-file porting notes

| Source (snapshot in `jetson_platform/device_snapshot/`) | Port effort | What changes |
|---|---|---|
| `eyes.py` | none | pure renderer, copy as-is |
| `wini_face.py` | none | pure renderer, copy as-is |
| `wini_display_driver.py` | none | already the single hardware owner; copy as-is |
| `wini_display.py` | ~50 lines | keep the main render loop + overlay-timeout logic; delete the Node class; replace the three subscriptions with plain setters; drop the rgb8/size validation and the un-mirror flip expectation (compose overlays un-flipped — the driver handles panel orientation) |
| `wini_head_node.py` + `serial_base.py` | ~half day | strip rclpy publishers; keep: port discovery by USB product string, reconnect loop, init/homing command, telemetry parse. Emit via plain callbacks. Drop ear animation code (dead — `EAR_DRIVE_ENABLED=False`), keep IMU parse optional |
| `wini_chin_reaction_node.py` | trivial | becomes ~15 lines inside TouchThread: debounced rising edge → `face.set_emotion("BLUSH", 12)` for 3 s → restore |
| `jetson_platform/wini_touch_trigger.py` | ~half day | the hold-detect state machine, idempotent start, loading/ready/failed cards, and thinking-face animation port directly; all publishes become direct calls; `run_thin.sh`/`run_client.sh` subprocess calls become ClientThread start |
| `wini_client/display_sinks.py` | ~30 lines | add `InProcSink` (resolve `image_path` against `rag_store/`, letterbox to 480×320 — reuse `RosDisplaySink._render` minus the flip — hand the array to the display thread). `RosDisplaySink` stays for any machine that still runs ROS |
| `wini_client/client.py` | small | factor `main()`'s loop body into a callable that takes an injected sink + a `stop_event`, so ClientThread can run and stop it; keep the CLI entry point working unchanged |

## 7. Dependencies (the "light" part)

One venv (`--system-site-packages` NOT needed anymore — ROS was the reason for it):

```
# platform (device) side
numpy  opencv-python  sounddevice  requests  pyserial
adafruit-circuitpython-rgb-display  adafruit-blinka   # board, digitalio
```

Server side (same box today): the study-core deps — `google-genai`,
`google-cloud-speech`, `google-cloud-texttospeech`, `python-dotenv`,
`sentence-transformers`/`torch` (MiniLM retrieval + HOPE), `networkx`, `rapidfuzz`,
`rank-bm25` (see `NEW_MACHINE_SETUP.md` for the full ladder). Note what is GONE from
the platform: rclpy, DDS, colcon, both workspace overlays, tf/msg packages.

Expected wins (to be measured at Stage 5 and recorded here):
- RAM: 5 platform processes → 1 (~200–400 MB back)
- Boot to face: no workspace sourcing, no DDS discovery — target < 10 s from crontab
- Zero topic-plumbing failure modes (keepalive, discovery, cold daemon)

## 8. Migration stages (each independently testable)

1. **Stage 0 — freeze & version.** This commit: docs + `jetson_platform/` scripts +
   `device_snapshot/` of the on-device sources. Rollback is always "run the old
   launchers".
2. **Stage 1 — display library.** Build `platform/display/` + a standalone
   `python3 -m platform.display.demo` that shows the face, cycles emotions, overlays a
   figure crop and the loading card. No ROS anywhere. **Test:** panel output identical
   to today (calibration card from the runbook §7.2 must render upright).
3. **Stage 2 — touch library.** `platform/touch/serial_head.py` + a demo that prints
   chin/head edges. **Test:** repeat the 2026-07-04 acceptance: clean 40 s no-touch
   baseline (0 presses), one 5 s hold each sensor, single edge pair, no bounce.
   ⚠️ Stop the ROS head node first — two owners of one serial port cannot coexist.
4. **Stage 3 — `wini_platform.py`.** Wire display + touch + trigger state machine +
   ClientThread (client loop as library, `InProcSink`). **Test:** full UX cycle against
   the running `wini_server.py`: chin hold → loading card → Ready → turn with thinking
   face → figure on screen → "bye" → sleep → chin hold → fast wake.
5. **Stage 4 — boot swap.** Point the `@reboot` crontab (or a systemd unit) at the new
   process; power-cycle test ×3. Old ROS stack remains on disk, launchable by hand.
6. **Stage 5 — measure & record.** RAM/boot/latency numbers into this doc; update
   `JETSON_PIPELINE_RUNBOOK.md` (§15 becomes legacy alongside §5) and
   `WINI_ARCHITECTURE.md`. Per CLAUDE.md: never write a number without measuring it.

## 9. Risks & gotchas (carry-overs that still apply)

- **PulseAudio USB re-grab** (§15.3): the platform must still run
  `select_usb_audio.sh` semantics at start and open streams with `device="pulse"`.
- **PortAudio blocking reads ignore SIGTERM**: ClientThread must be stopped via its
  `stop_event` + a short-timeout stream read, not thread-kill; process-level stop is
  `pkill -9` as today.
- **SPI permissions**: the display needs `/dev/spidev*` + GPIO access (user in `spi`/
  `gpio` groups or udev rules) — today this rides on the ROS user's setup; verify on
  the fresh venv.
- **Serial port contention** during migration: never run old head node + new touch
  thread simultaneously.
- **The ESP32 contract is unchanged**: `display[].image_path` stays the SD-card image
  ID (runbook §14.3); `InProcSink` is just today's RosDisplaySink minus ROS.
- **Ears stay off** until the STM32 firmware position-loop fix (`EAR_ACTUATION_ISSUE.md`).
