# Wini Ear Actuation — Firmware Position-Loop Defect (investigation + interim fix)

**Date:** 2026-06-24
**Module:** `wini_hw_bridge` / `wini_head_node` (Jetson, `~/Downloads/ros2_ws`)
**Head MCU:** STM32 `wini_head` on `/dev/ttyACM1`, firmware `stm32_wini_V2_release_06052026/wini_head_v2.bin`

## Summary

The ears cannot be positioned by the firmware's closed-loop control. **Homing
(`W_DH`) works and parks the ears upright, but any `W_EAL`/`W_EAR` position
command drives the commanded ear to a mechanical rail (~±88°) and jams it**
(firmware then latches PWM to 0 via stall cutoff). This is a firmware defect in
the ear position loop, not a host/command problem.

Because the head node's 50 Hz emotion animator streams `W_EAL/W_EAR` from
`/wini/emotion`, the ears jammed as soon as any emotion (e.g. BLUSH) was active.

## Symptom

- On startup the ears homed and sat upright (correct).
- Once emotion-driven ear angles were sent, the ears moved to the end stops
  (right ≈ −90°, left ≈ +90°) and stopped moving.

## Evidence (raw-serial probes, head node stopped)

All probes: `W_STOP:0` (arm), `W_EPWM:2500`, `W_DH` (home → upright ≈ 0°), then a
single static position command, reading `R2_EAL/R2_EAR` (deg×100) and
`R0_PWM_L/R` (debug telemetry).

| Test | Command | Result |
|---|---|---|
| Homing | `W_DH` | ears sweep and settle **upright ≈ 0°**, PWM 2500 — motors + feedback OK |
| Hold home | `W_EAL:0 W_EAR:0` | **rails to ≈ ±88°** at full PWM (target = current pos, should not move) |
| Small angles | `W_EAL:0.5 / 1 / 2` | all rail to ≈ −88° (a 0.5° cmd is **not** multiplied; value-independent) |
| Sign | `W_EAL:±3…±20` | both signs rail |
| Offset idea | `W_EAL:80 / 90` | rails (90 does **not** hold upright — no frame offset) |
| Gain polarity | `W_EKP:−120…−10` | rails | 
| Gain zero | `W_EKP:0` | **stable** — ear holds at home, no positioning |
| Gain positive | `W_EKP:+20/+50/+100` | rails even when commanded to 0° at full PWM |

Right ear (left uncommanded) held its homed position throughout — only the
commanded ear railed. Commands are all `ACK`'d. Old vs new protocol docs define
`W_EAL/W_EAR` identically, so the head node uses the convention correctly.

## Root cause

With `W_EKP:0` the ear is stable (no drive); with **any** nonzero gain it goes to
full PWM toward the rail **even when commanded to its current position** (zero
error should give zero PWM). Therefore the **position loop's internal feedback is
not synchronized to the homed zero**: `W_DH` resets the reported angle but the
control loop still believes it is ~90° away, so any gain drives it to the rail
regardless of the target. Open-loop homing is unaffected, which is why homing
works but closed-loop positioning does not.

## Ruled out (host side)

Command sign, magnitude/scaling (multiply), frame offset, gain polarity and
magnitude, protocol-version convention drift, and the display node (it only
*subscribes* to `/wini/emotion`; it never sends ear commands). The emotion
animator merely *feeds* correct commands that the firmware mis-executes.

## Firmware fix required

The ear position controller must **reset/zero its control feedback when homing
completes** (sync the loop's internal position to the homed 0°), or the homing
routine must zero the loop state, not just the telemetry. After that, `W_EAL/
W_EAR` should track and the host animator can be re-enabled.

## Interim measure (applied 2026-06-24, host side)

`wini_head_node.py`:
- Sets a holding gain `W_EKP:80` then homes the ears (`W_DH`) in `on_connected`,
  so they home to ~0° and **hold upright**.
- `EAR_DRIVE_ENABLED = False` → the 50 Hz animator **never sends `W_EAL/W_EAR`**.
  The ears hold the homed-upright position; they do not wiggle.
- Touch sensors (`/wini/head/touch_chin`, `/wini/head/touch_top`) and IMU
  telemetry are unaffected.

**Gotcha (gain & holding):** with `W_EKP:0` the ears have no holding force and
droop to a rail *after* homing. With a non-zero gain (30–150 tested) homing
drives at full PWM and holds ~0°; `W_EKP:80` gives L≈+0.3°, R≈−0.6°. The gain
only ever *holds* the homed position here because the animator is disabled — if
ear driving is re-enabled while the firmware loop is still broken, any
`W_EAL/W_EAR` target will rail regardless of gain.

Behaviour now: **chin press → BLUSH face on the display only, no ear movement.**
(`wini_chin_reaction_node` publishes `/wini/emotion BLUSH`; the display renders
the blush face; the head node ignores it for the ears.)

### Re-enabling ears after the firmware is fixed

1. Flash the corrected head firmware.
2. Re-run the tracking probe: home, then `W_EAL:15` should settle near +15°
   (use `~/ear_poscheck.py` / `~/ear_ekp_pos.py` on the Jetson).
3. Set `EAR_DRIVE_ENABLED = True` in `wini_head_node.py`, rebuild
   (`colcon build --packages-select wini_hw_bridge --symlink-install`), restart.

### Diagnostic scripts (kept on the Jetson, `~`)

`ear_diag.py`, `ear_diag2.py`, `ear_home_test.py`, `ear_poscheck.py`,
`ear_sweep.py`, `ear_offset_test.py`, `ear_probe3.py`, `ear_ekp_test.py`,
`ear_ekp_pos.py` — raw-serial ear probes (stop the head node first to free
`/dev/ttyACM1`).
