"""Synthetic touchscreen — inject real finger events through /dev/uinput.

Why this exists rather than xdotool/wlrctl:

* **wlrctl cannot drag.** Each invocation creates a zwlr_virtual_pointer, sends
  one action, then exits and destroys the device. A press and the motion that
  follows therefore come from *different* virtual devices, so the compositor
  never sees a held-button drag — the object simply never moves. Verified: the
  food's centre stayed at its resting coordinates through a full drag.
* **xdotool is X11-only**, and winipi5 moved to labwc/Wayland on 2026-07-22.

Injecting at the kernel level sidesteps both: this registers a multi-touch
device that looks like the panel, so events travel the *same* path as a real
finger (evdev -> libinput -> compositor -> SDL -> LVGL). That makes it both
backend-agnostic and a more faithful test than pointer emulation ever was.

Needs write access to /dev/uinput, so run it under sudo (passwordless on this
board).

    sudo .venv/bin/python -m pi_game.touchsim tap 300 935
    sudo .venv/bin/python -m pi_game.touchsim drag 300 650 300 320 --steps 12
"""

from __future__ import annotations

import argparse
import sys
import time

from evdev import AbsInfo, UInput
from evdev import ecodes as e

# The panel, in its portrait orientation (PI_ACCESS.md §1).
SCREEN_W = 600
SCREEN_H = 1024

# A single-finger multitouch digitizer. INPUT_PROP_DIRECT is what marks it as a
# touchscreen rather than a trackpad — without it libinput treats the absolute
# coordinates as pointer-relative gestures and nothing lands where you asked.
CAPS = {
    e.EV_ABS: [
        (e.ABS_MT_POSITION_X, AbsInfo(0, 0, SCREEN_W - 1, 0, 0, 0)),
        (e.ABS_MT_POSITION_Y, AbsInfo(0, 0, SCREEN_H - 1, 0, 0, 0)),
        (e.ABS_MT_SLOT,       AbsInfo(0, 0, 1, 0, 0, 0)),
        (e.ABS_MT_TRACKING_ID, AbsInfo(0, 0, 65535, 0, 0, 0)),
        (e.ABS_X,             AbsInfo(0, 0, SCREEN_W - 1, 0, 0, 0)),
        (e.ABS_Y,             AbsInfo(0, 0, SCREEN_H - 1, 0, 0, 0)),
    ],
    e.EV_KEY: [e.BTN_TOUCH],
}


class Touch:
    def __init__(self, settle: float = 1.0) -> None:
        self.ui = UInput(CAPS, name="wini-touchsim", version=1,
                         input_props=[e.INPUT_PROP_DIRECT])
        # libinput must notice the new device and the compositor must add it to
        # the seat before anything sent here is routed anywhere. Without this
        # pause the first gesture of a run is silently swallowed.
        time.sleep(settle)
        self._id = 1

    def close(self) -> None:
        self.ui.close()

    def _sync(self) -> None:
        self.ui.write(e.EV_SYN, e.SYN_REPORT, 0)
        self.ui.syn()

    def down(self, x: int, y: int) -> None:
        self.ui.write(e.EV_ABS, e.ABS_MT_SLOT, 0)
        self.ui.write(e.EV_ABS, e.ABS_MT_TRACKING_ID, self._id)
        self._id += 1
        self.ui.write(e.EV_ABS, e.ABS_MT_POSITION_X, x)
        self.ui.write(e.EV_ABS, e.ABS_MT_POSITION_Y, y)
        self.ui.write(e.EV_ABS, e.ABS_X, x)
        self.ui.write(e.EV_ABS, e.ABS_Y, y)
        self.ui.write(e.EV_KEY, e.BTN_TOUCH, 1)
        self._sync()

    def move(self, x: int, y: int) -> None:
        self.ui.write(e.EV_ABS, e.ABS_MT_SLOT, 0)
        self.ui.write(e.EV_ABS, e.ABS_MT_POSITION_X, x)
        self.ui.write(e.EV_ABS, e.ABS_MT_POSITION_Y, y)
        self.ui.write(e.EV_ABS, e.ABS_X, x)
        self.ui.write(e.EV_ABS, e.ABS_Y, y)
        self._sync()

    def up(self) -> None:
        self.ui.write(e.EV_ABS, e.ABS_MT_SLOT, 0)
        self.ui.write(e.EV_ABS, e.ABS_MT_TRACKING_ID, -1)   # finger lifted
        self.ui.write(e.EV_KEY, e.BTN_TOUCH, 0)
        self._sync()


def do_tap(t: Touch, x: int, y: int, hold: float = 0.09) -> None:
    t.down(x, y)
    time.sleep(hold)
    t.up()


def do_drag(t: Touch, x0: int, y0: int, x1: int, y1: int,
            steps: int = 12, pause: float = 0.05) -> None:
    t.down(x0, y0)
    # LVGL samples the pointer at ~30 Hz. Settle after the press so the press and
    # the first motion cannot land in one poll — otherwise LVGL registers the
    # press at the already-moved position, misses the object, and no drag starts.
    time.sleep(0.30)
    for i in range(1, steps + 1):
        t.move(round(x0 + (x1 - x0) * i / steps),
               round(y0 + (y1 - y0) * i / steps))
        time.sleep(pause)
    time.sleep(0.30)
    t.up()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("tap")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)

    d = sub.add_parser("drag")
    d.add_argument("x0", type=int)
    d.add_argument("y0", type=int)
    d.add_argument("x1", type=int)
    d.add_argument("y1", type=int)
    d.add_argument("--steps", type=int, default=12)
    d.add_argument("--pause", type=float, default=0.05)

    args = ap.parse_args()

    try:
        t = Touch()
    except PermissionError:
        print("cannot open /dev/uinput — run under sudo", file=sys.stderr)
        return 2

    try:
        if args.cmd == "tap":
            do_tap(t, args.x, args.y)
            print(f"tap ({args.x},{args.y})")
        else:
            do_drag(t, args.x0, args.y0, args.x1, args.y1,
                    args.steps, args.pause)
            print(f"drag ({args.x0},{args.y0}) -> ({args.x1},{args.y1})")
    finally:
        # Hold the device open a moment: closing it in the same breath as the
        # last event can destroy it before the compositor has processed the lift.
        time.sleep(0.3)
        t.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
