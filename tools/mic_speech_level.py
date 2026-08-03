"""Measure SPEECH RMS on this device's microphone, via acoustic loopback.

Setting the VAD start gate needs two numbers: the room/mic noise floor
(tools/mic_floor.py) and how loud speech actually lands on this capture chain.
The second cannot be guessed — the reSpeaker Lite's own noise floor is ~0.025
RMS, which is where a naive "speech is above 0.018" assumption came from and why
the old endpointer could never detect silence at all.

So: play a synthesized utterance out of the speaker and record it back. It is
not a child's voice at a child's distance, but it is real acoustics through the
real capture path, which is what separates speech from the noise floor.

Run with nothing else holding the audio device (stop_wini_package.sh first):
    .venv/bin/python tools/mic_speech_level.py --pcm /tmp/utt.raw
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np


def _endpoint_check(speech, dur: float) -> int:
    """Play `speech` and let the SHIPPED endpointer decide when it ended.

    This is the one check that exercises the real microphone, the real gates and
    the real floor measurement together — the synthetic suite
    (wini_client/test_vad.py) can only prove the logic, not the tuning.
    """
    import sounddevice as sd

    from wini_client.client import record_utterance

    def _play():
        time.sleep(1.0)                        # inside the wait window
        try:
            sd.play(speech.astype(np.float32) / 32768.0, samplerate=16000,
                    blocking=True)
        except Exception as e:  # noqa: BLE001
            print(f"[endpoint] playback failed: {e}")

    threading.Thread(target=_play, daemon=True).start()
    t0 = time.perf_counter()
    pcm = record_utterance(wait_for_speech_s=15.0)
    wall = time.perf_counter() - t0
    if pcm is None:
        print("[endpoint] FAIL — never detected the speech (start gate too high)")
        return 1
    last = getattr(record_utterance, "last", {})
    print(f"[endpoint] wall={wall:.1f}s  played={dur:.1f}s  {last}")
    ok = last.get("reason") == "silence"
    print("[endpoint] " + ("PASS — endpointed on silence" if ok else
                           "FAIL — ran to the hard cap (the original bug)"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pcm", type=Path, required=True,
                    help="16 kHz mono int16 raw PCM to play (tools/first_turn_probe.py --make-pcm)")
    ap.add_argument("--endpoint", action="store_true",
                    help="run the REAL record_utterance against this playback "
                         "and report where it endpointed, instead of dumping "
                         "the RMS profile")
    args = ap.parse_args()

    import sounddevice as sd

    speech = np.frombuffer(args.pcm.read_bytes(), dtype=np.int16)
    dur = len(speech) / 16000.0
    block = 480

    if args.endpoint:
        return _endpoint_check(speech, dur)

    def _play():
        time.sleep(0.6)                       # let the recorder settle first
        try:
            sd.play(speech.astype(np.float32) / 32768.0, samplerate=16000,
                    blocking=True)
        except Exception as e:  # noqa: BLE001
            print(f"[level] playback failed: {e}")

    try:
        stream = sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                                blocksize=block, device="pulse")
    except Exception:  # noqa: BLE001
        stream = sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                                blocksize=block)

    threading.Thread(target=_play, daemon=True).start()
    vals = []
    with stream as s:
        for _ in range(int((dur + 1.4) * 1000 / 30)):
            data, _o = s.read(block)
            f = data.reshape(-1).astype(np.float32) / 32768.0
            vals.append(float(np.sqrt(np.mean(f ** 2))))

    v = np.array(vals)
    lead = v[:15]                              # the 450 ms before playback
    body = v[25:]                              # once speech is running
    print(f"pre-speech floor : p50={np.percentile(lead, 50):.4f} "
          f"max={lead.max():.4f}")
    print(f"during speech    : p50={np.percentile(body, 50):.4f} "
          f"p75={np.percentile(body, 75):.4f} p90={np.percentile(body, 90):.4f} "
          f"max={body.max():.4f}")
    print("profile (30ms blocks): "
          + " ".join(f"{x:.3f}" for x in v[::5][:60]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
