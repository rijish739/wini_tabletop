#!/usr/bin/env python3
"""Play every cat sound in the SoundBank through the reSpeaker, in order.

The touch service and the tutor package both own the speaker exclusively, so
stop them first:

    pkill -f touch_service.py
    .venv/bin/python3 -u tools/audition_cat_sounds.py

Each family is played a few times so the per-play variation (pitch, doubling,
anti-repetition) is audible — a single play tells you nothing about whether
the robot sounds alive.
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

from wini_client.sound_bank import SoundBank      # noqa: E402
from wini_client.client import play_pcm           # noqa: E402

REPEATS = int(os.environ.get("REPEATS", "3"))


def main() -> None:
    bank = SoundBank()
    for family in bank.families:
        print(f"\n=== {family} ===", flush=True)
        for i in range(REPEATS):
            pcm, rate = bank.get_sound(family, mood=70.0)
            print(f"  play {i + 1}/{REPEATS}  {1000 * len(pcm) // (2 * rate)} ms",
                  flush=True)
            play_pcm(pcm, rate)
            time.sleep(0.55)
        time.sleep(0.6)

    print("\n=== purr (4 s continuous) ===", flush=True)
    for _ in range(8):
        pcm, rate = bank.get_purr_chunk(mood=70.0)
        play_pcm(pcm, rate)

    print("\ndone.", flush=True)


if __name__ == "__main__":
    main()
