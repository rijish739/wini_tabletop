#!/usr/bin/env python3
"""Run a standalone touch gesture and audio synthesis demo on the Pi."""
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from wini_client.sound_bank import SoundBank
from wini_client.audio_manager import AudioManager
from wini_client.client import play_pcm
from wini_platform.touch_gestures import TouchGestureRecognizer
from wini_platform.emotion_engine import EmotionEngine
from wini_platform.touch.gpio_touch import GpioTouchReader

def main():
    print("Initializing sound engine...")
    bank = SoundBank(rate=16000)   # default amplitude (0.5) — audible on-device
    am = AudioManager(play_fn=play_pcm, sound_bank=bank, log=print)
    
    print("Initializing gesture recognizer & emotion engine...")
    engine = EmotionEngine(audio_manager=am, log=print)
    
    rec = TouchGestureRecognizer(
        on_single_tap=engine.on_single_tap,
        on_double_tap=engine.on_double_tap,
        on_hold_start=engine.on_hold_start,
        on_hold_end=engine.on_hold_end,
        on_pat_sequence=engine.on_pat_sequence,
        log=print
    )

    print("Initializing GPIO touch reader on GPIO22...")
    reader = GpioTouchReader(
        gpio_pin=22,
        chip=4,
        on_touch=rec.on_level,
        log=print
    )
    
    reader.start()
    
    if not reader.connected:
        print("ERROR: GPIO reader failed to connect. Is it running on a Pi with GPIO22 available?")
        return

    print("\n--- STANDALONE TOUCH DEMO READY ---")
    print("Interact with the touch button on GPIO22 (pin 15):")
    print("  - Single tap: Curious chirp / acknowledge beep")
    print("  - Double tap: Happy trill")
    print("  - Long hold: Purring loop, release -> satisfied sound")
    print("  - Repeated patting (3+ taps): Excited beeps")
    print("Press Ctrl-C to stop.")
    
    try:
        while True:
            # Feed ticks to the emotion engine for mood decay and idle sounds
            engine.tick(0.2)
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopping demo...")
    finally:
        reader.shutdown()
        am.shutdown()
        print("Demo stopped.")

if __name__ == "__main__":
    main()
