# jetson_platform/ — versioned copies of the on-device platform code

The Jetson's platform layer (launchers, touch trigger, and the ROS node sources) is
edited live on the board and was previously **not in git**. This directory versions it.
The board remains the runtime source of truth — treat workspace↔Jetson as a 3-way
merge (`JETSON_PIPELINE_RUNBOOK.md` §10), and re-snapshot here after on-device edits.

| File | On-device path | Role |
|---|---|---|
| `run_boot_platform.sh` | `~/run_boot_platform.sh` | boot bring-up (display + head + trigger); installed as `@reboot` crontab |
| `wini_touch_trigger.py` | `~/wini_touch_trigger.py` | chin-hold 3 s → start/wake pipeline (idempotent); loading/ready cards; thinking-face animation (`/wini/thinking`) |
| `run_thin.sh` | `~/run_thin.sh` | full pipeline start (audio pin + display + `wini_server.py` + client, `--on-session-end exit`, `WINI_FILLERS=0`) |
| `run_client.sh` | `~/run_client.sh` | client-only restart (fast wake from sleep; brain stays warm) |
| `wini_loading_text.py` | `~/wini_loading_text.py` | standalone "Loading…" frame publisher (display test utility) |
| `device_snapshot/display_controll/` | `~/Downloads/ros2_ws/src/display_controll/display_controll/` | face renderer (`eyes.py`, `wini_face.py`), ST7796S SPI driver, display node — snapshot 2026-07-04 |
| `device_snapshot/wini_hw_bridge/` | `~/Downloads/ros2_ws/src/wini_hw_bridge/wini_hw_bridge/` | STM32 serial base, head node (touch/IMU/ears), chin-blush reflex — snapshot 2026-07-04 |

Deploy a change: `scp <file> roavai@172.20.10.2:~/` (or into the workspace src path),
then restart the affected process — running Python keeps old code in memory.
`device_snapshot/` is also the library basis for the planned ROS-less platform:
see `WINI_ROSLESS_PLATFORM_PLAN.md`.
