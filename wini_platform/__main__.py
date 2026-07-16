"""Entry point: python3 -m wini_platform

The single-process replacement for the ROS platform stack (display node, head
node, chin-reaction node, touch trigger) per WINI_ROSLESS_PLATFORM_PLAN.md §4.
wini_server.py remains a separate process; by default the supervisor spawns
and monitors it on a local URL (use --no-manage-server when systemd or Cloud
Run owns the brain).
"""

from __future__ import annotations

import argparse
import os
import signal
from pathlib import Path

from .supervisor import WiniPlatform, CORE_ROOT


def main() -> None:
    ap = argparse.ArgumentParser(description="Wini ROS-less platform")
    ap.add_argument("--server",
                    default=os.getenv("WINI_SERVER", "http://127.0.0.1:8123"))
    ap.add_argument("--store", default=os.getenv(
        "WINI_STORE", str(CORE_ROOT / "rag_store")))
    ap.add_argument("--no-manage-server", action="store_true",
                    help="never spawn wini_server.py (systemd/Cloud Run brain)")
    ap.add_argument("--autostart", action="store_true",
                    help="start the client at boot instead of waiting for a chin hold")
    ap.add_argument("--fake-display", action="store_true",
                    help="NullDriver — run without the SPI panel (development)")
    ap.add_argument("--no-touch", action="store_true",
                    help="run without the STM32 head board (development)")
    ap.add_argument("--ui", action="store_true",
                    help="launch the LVGL touch UI (wini_ui) on the DSI panel and "
                         "drive it over the mode channel (Pi build). Implies the "
                         "client uses ModeChannelSink instead of the eyes display.")
    ap.add_argument("--ui-port", type=int, default=int(os.getenv("WINI_UI_PORT", "8140")),
                    help="TCP port for the wini_ui mode channel (default 8140)")
    ap.add_argument("--ui-bin", default=os.getenv("WINI_UI_BIN"),
                    help="path to the wini_ui binary (default: wini_ui/build/wini_ui)")
    args = ap.parse_args()

    platform = WiniPlatform(server_url=args.server,
                            store_dir=Path(args.store),
                            manage_server=not args.no_manage_server,
                            fake_display=args.fake_display,
                            no_touch=args.no_touch,
                            ui=args.ui,
                            ui_port=args.ui_port,
                            ui_bin=Path(args.ui_bin) if args.ui_bin else None)
    # SIGTERM → clean stop (finish the in-flight SPI write, park the panel).
    # Killing the render loop mid-frame with SIGKILL can leave the ST7796S in
    # a state where the next init loses its reset race — see the driver note.
    signal.signal(signal.SIGTERM, lambda *_: platform._stop.set())
    platform.run(autostart=args.autostart)


if __name__ == "__main__":
    main()
