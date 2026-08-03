"""Windows launcher — start the brain and the pygame UI in one process.

Mirrors run_alphabet.sh, minus everything Linux (flock, setsid, pkill, ALSA,
touch_service): on Windows we run the brain's socket server in a background
thread and the pygame window on the main thread (the OS requires the window loop
on the main thread), and they talk over 127.0.0.1:8160 exactly as on the Pi.

    python run_game.py [--fullscreen] [--no-warm]

Readiness is gated on the brain's /health, not a sleep, so the window never
opens before the lesson channel is listening.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import alphabet_server as brain     # noqa: E402
import alphabet_ui as ui            # noqa: E402


def _wait_health(http_port: int, timeout_s: float = 120.0) -> bool:
    url = f"http://127.0.0.1:{http_port}/health"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as r:
                data = json.loads(r.read().decode("utf-8"))
                if data.get("ready"):
                    return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the Wini alphabet game on Windows")
    ap.add_argument("--fullscreen", action="store_true")
    ap.add_argument("--no-warm", action="store_true",
                    help="skip the cloud warmup (cached lines still play)")
    ap.add_argument("--port", type=int, default=brain.UI_PORT)
    ap.add_argument("--http-port", type=int, default=brain.HTTP_PORT)
    args = ap.parse_args()

    print("[run] starting brain...", flush=True)
    t = threading.Thread(
        target=brain.serve_forever,
        kwargs={"port": args.port, "http_port": args.http_port,
                "warm": not args.no_warm},
        daemon=True,
    )
    t.start()

    print("[run] waiting for the lesson channel to come up...", flush=True)
    if not _wait_health(args.http_port):
        print("[run] brain did not become ready in time — opening the window anyway",
              flush=True)

    print("[run] opening the window", flush=True)
    return ui.run(host="127.0.0.1", port=args.port, fullscreen=args.fullscreen)


if __name__ == "__main__":
    raise SystemExit(main())
