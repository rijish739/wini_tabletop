"""Report the microphone's actual room noise floor, in the same RMS units the
endpointer uses.

Point of the tool: `record_utterance`'s gates are noise-relative, so "is the VAD
tuned?" is answerable only against a real measurement of the room the device is
in. It also shows, directly, why a single fixed gate could not work — print how
many blocks the old 0.018 threshold would have called silence.

Run on the device (needs an audio seat — the desktop/VNC session, not bare SSH):
    .venv/bin/python tools/mic_floor.py [--seconds 3]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--idle", type=float, default=0.0,
                    help="also run the REAL endpointer against this many seconds "
                         "of an empty room; it must NOT start a turn")
    args = ap.parse_args()

    import sounddevice as sd

    from wini_client.client import (VAD_ABS_FLOOR, VAD_START_MULT,
                                    VAD_STOP_MULT, VAD_STOP_RATIO)

    block = 480                       # 30 ms at 16 kHz, the endpointer's block
    try:
        stream = sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                                blocksize=block, device="pulse")
    except Exception:  # noqa: BLE001 — no pulse layer: raw device
        stream = sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                                blocksize=block)

    vals = []
    with stream as s:
        for _ in range(int(args.seconds * 1000 / 30)):
            data, _over = s.read(block)
            f = data.reshape(-1).astype(np.float32) / 32768.0
            vals.append(float(np.sqrt(np.mean(f ** 2))))

    v = np.array(vals)
    p50, p90 = float(np.percentile(v, 50)), float(np.percentile(v, 90))
    print(f"room RMS over {args.seconds:.0f}s: min={v.min():.4f} p50={p50:.4f} "
          f"p90={p90:.4f} max={v.max():.4f}")
    stop = max(p50 * VAD_STOP_MULT, VAD_ABS_FLOOR * 0.7)
    start = max(max(p50 * VAD_START_MULT, VAD_ABS_FLOOR), stop / VAD_STOP_RATIO)
    stop = min(stop, start * VAD_STOP_RATIO)
    print(f"adaptive gates at this floor: start={start:.4f} stop={stop:.4f}")
    quiet = 100.0 * float((v < 0.018).mean())
    print(f"old fixed 0.0180 gate would call {quiet:.0f}% of these blocks silent "
          f"({'ENDPOINTS' if quiet > 80 else 'NEVER ENDPOINTS — the hard_cap bug'})")
    quiet_new = 100.0 * float((v < stop).mean())
    print(f"new stop gate calls {quiet_new:.0f}% of them silent "
          f"({'OK' if quiet_new > 80 else 'STILL TOO TIGHT'})")

    if args.idle > 0:
        # The other half of the tuning: a start gate low enough to hear a quiet
        # child is only safe if the empty room never clears it. A false start
        # sends silence to STT and burns a turn on nothing.
        from wini_client.client import record_utterance
        got = record_utterance(wait_for_speech_s=args.idle)
        if got is None:
            print(f"idle-room check: PASS — no turn started in {args.idle:.0f}s")
        else:
            print(f"idle-room check: FAIL — room noise started a turn: "
                  f"{getattr(record_utterance, 'last', {})}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
