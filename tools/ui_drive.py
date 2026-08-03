"""Drive the touch UI over the mode channel with no mic and no brain.

The panel is the only place several bugs are visible (a truncated explanation, a
maths glyph the font can't draw, a command line the C side silently dropped),
and a real voice turn needs a PipeWire seat that an SSH session does not have.
So this binds the mode-channel port itself, waits for wini_ui to reconnect, and
pushes the same {"cmd": ...} lines ModeChannelSink would — through the REAL
ModeChannelSink, so the caps, the glyph mapping and the JSON encoding under test
are the shipped ones.

Usage (on the device, with wini_ui running and the voice client stopped):
    .venv/bin/python tools/ui_drive.py --explain
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wini_client.display_sinks import ModeChannelSink          # noqa: E402
from wini_client.mode_channel import ModeChannel, ModeState    # noqa: E402

# A deliberately awkward answer: longer than the old 200-char cap, with caret
# powers, a LaTeX root, ASCII comparisons and an asterisk product.
LONG_ANSWER = (
    "A quadratic equation is any equation of the form ax^2 + bx + c = 0, where "
    "a, b and c are real numbers and a is not 0. To find its roots we can use "
    "the quadratic formula, where the discriminant D = b^2 - 4*a*c decides how "
    "many real roots there are. If D >= 0 the equation has real roots, and if "
    "D <= 0 it does not. For example x^2 - 4 = 0 has the two roots x = 2 and "
    "x = -2, because 2^2 - 4 = 0 and (-2)^2 - 4 = 0. Does that make sense?"
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8140)
    ap.add_argument("--wait", type=float, default=20.0,
                    help="seconds to wait for wini_ui to connect")
    ap.add_argument("--hold", type=float, default=90.0,
                    help="seconds to leave the content on the panel")
    ap.add_argument("--answer", default=LONG_ANSWER)
    args = ap.parse_args()

    ch = ModeChannel(ModeState(), port=args.port).start()
    ch.set_sticky({"cmd": "ready"})
    t0 = time.time()
    while ch._conn is None and time.time() - t0 < args.wait:   # noqa: SLF001
        time.sleep(0.25)
    if ch._conn is None:                                       # noqa: SLF001
        print("[ui_drive] no UI connected — is wini_ui running?")
        return 1
    print(f"[ui_drive] UI connected after {time.time() - t0:.1f}s")

    sink = ModeChannelSink(ch, store_dir=Path(__file__).resolve().parent.parent
                           / "rag_store")
    sink.on_turn({
        "mode": "EXPLAIN",
        "concept": "jemh104__quadratic_equation",
        "answer": args.answer,
        "display": [],
    })
    sink.clear()
    print(f"[ui_drive] pushed a {len(args.answer)}-char answer; holding "
          f"{args.hold:.0f}s")
    time.sleep(args.hold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
