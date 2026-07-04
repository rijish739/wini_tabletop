"""Stage 2 acceptance demo — print chin/head touch edges, no ROS.

⚠️ Stop the ROS head node first (two owners of one serial port cannot coexist):
    pkill -f wini_head_node

Run:
    cd ~/wini/core && python3 -m wini_platform.touch.demo

Acceptance (repeat of the 2026-07-04 test): a clean 40 s no-touch baseline
(0 presses), then one 5 s hold on each sensor producing a single DOWN/UP edge
pair each, no bounce. The demo prints every edge with a timestamp and hold
duration, plus per-sensor press counts on exit (Ctrl-C).
"""

from __future__ import annotations

import signal
import time

from .serial_head import SerialHead


class EdgePrinter:
    def __init__(self, name: str):
        self.name = name
        self.level = False
        self.down_t = 0.0
        self.presses = 0

    def __call__(self, level: bool) -> None:
        if level == self.level:
            return
        now = time.monotonic()
        self.level = level
        if level:
            self.down_t = now
            self.presses += 1
            print(f"[{now:12.3f}] {self.name} DOWN  (press #{self.presses})")
        else:
            print(f"[{now:12.3f}] {self.name} UP    "
                  f"(held {now - self.down_t:.2f}s)")


def main() -> None:
    chin = EdgePrinter("CHIN")
    head_top = EdgePrinter("HEAD")
    head = SerialHead(on_chin=chin, on_head=head_top)
    head.start()

    print("[demo] watching touch edges — Ctrl-C to stop.")
    print("[demo] acceptance: 40 s untouched = 0 presses; a 5 s hold on each "
          "sensor = exactly one DOWN/UP pair.")
    t0 = time.monotonic()
    try:
        signal.pause()
    except AttributeError:  # Windows dev box has no signal.pause
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        dt = time.monotonic() - t0
        print(f"\n[demo] {dt:.0f}s elapsed — chin presses: {chin.presses}, "
              f"head presses: {head_top.presses}")
        head.shutdown()


if __name__ == "__main__":
    main()
