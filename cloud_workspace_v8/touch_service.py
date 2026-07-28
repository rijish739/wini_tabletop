#!/usr/bin/env python3
"""Always-on background touch-emotion service (winipi5).

Owns GPIO22 + the reSpeaker output and plays synthesized emotion sounds in
response to touch — whenever the main tutor package is NOT running.

The reSpeaker Lite exposes ONE playback substream and GPIO22 takes ONE claim,
so this service and the tutor package are mutually exclusive:
  * run_wini_package.sh  stops this service on start (the tutor client then
    provides touch-audio itself via wini_client.client._start_touch_audio).
  * stop_wini_package.sh restarts this service once the speaker/GPIO are free.

Run:   setsid .venv/bin/python3 -u touch_service.py >> logs/touch.log 2>&1 </dev/null &
Stop:  pkill -f 'python3 -u touch_service.py'     (SIGTERM → clean shutdown)
"""

import os
import signal
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from wini_client.sound_bank import SoundBank
from wini_client.audio_manager import AudioManager
from wini_client.client import play_pcm
from wini_platform.touch_gestures import TouchGestureRecognizer
from wini_platform.emotion_engine import EmotionEngine
from wini_platform.touch.gpio_touch import GpioTouchReader


def main() -> None:
    bank = SoundBank()                     # default amplitude (0.5)
    am = AudioManager(play_fn=play_pcm, sound_bank=bank, log=print)
    engine = EmotionEngine(am, log=print)
    rec = TouchGestureRecognizer(
        on_single_tap=engine.on_single_tap,
        on_double_tap=engine.on_double_tap,
        on_hold_start=engine.on_hold_start,
        on_hold_end=engine.on_hold_end,
        on_pat_sequence=engine.on_pat_sequence,
        log=print,
    )
    reader = GpioTouchReader(gpio_pin=22, chip=4, on_touch=rec.on_level, log=print)
    reader.start()
    if not reader.connected:
        print("[touch_service] GPIO22 unavailable (tutor package running?) — exiting.")
        return

    print("[touch_service] up: GPIO22 touch-emotions live.")
    stop = {"v": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__("v", True))
    try:
        while not stop["v"]:
            engine.tick(0.2)               # mood decay + idle ambience
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        reader.shutdown()
        am.shutdown()
        print("[touch_service] stopped.")


if __name__ == "__main__":
    main()
