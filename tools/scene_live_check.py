"""Mic-free end-to-end check of the tier-0 SCENE live path (SCENE_VISUALS_GUIDE §4).

The device has no remote mic, but the whole point is to exercise the INTEGRATED
path — STT -> brain -> concept resolution -> scene selection -> beat-synced
playback — not just the pieces. So this drives the REAL ``run_session`` turn loop
and only substitutes the one thing a laptop/SSH session can't supply: the mic
capture. It synthesizes the prompt with Cloud TTS (a stand-in for the child's
voice), resamples it to 16 kHz, and feeds that PCM in place of a recorded
utterance. Everything downstream is the shipped code: the brain transcribes the
audio, resolves the concept, and the client's on_meta/on_audio scene logic +
``play_scene`` run untouched.

Run it on the device, with the normal tutor stopped and the seat audio env set
(SCENE_VISUALS_GUIDE §5.4):

    pkill -f 'wini_[c]lient.client'; pkill -f 'touch_[s]ervice.py'
    export XDG_RUNTIME_DIR=/run/user/1000 \
           DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
           WAYLAND_DISPLAY=wayland-0 DISPLAY=:0
    .venv/bin/python tools/scene_live_check.py --launch-ui \
        --prompt "explain the quadratic formula"

It launches wini_ui itself (--launch-ui), plays exactly one turn, and exits.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from wini_client import client as C  # noqa: E402
from wini_client.client import BrainClient, RATE, _resample_to, run_session  # noqa: E402
from wini_client.display_sinks import ModeChannelSink  # noqa: E402
from wini_client.mode_channel import ModeChannel, ModeState  # noqa: E402


def synth_utterance(text: str) -> bytes:
    """Cloud TTS the prompt and resample to the 16 kHz mono PCM the mic path
    would have produced — the brain's STT sees ordinary clear speech."""
    from voice.cloud_tts import CloudTts
    tts = CloudTts()
    pcm24 = tts.synth(text)
    a = np.frombuffer(pcm24, dtype=np.int16).astype(np.float32) / 32768.0
    a16 = _resample_to(a, tts.rate, RATE)
    return (np.clip(a16, -1, 1) * 32767).astype(np.int16).tobytes()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prompt", default="explain the quadratic formula")
    ap.add_argument("--server", default="http://127.0.0.1:8123")
    ap.add_argument("--ui-port", type=int, default=8140)
    ap.add_argument("--launch-ui", action="store_true")
    ap.add_argument("--ui-bin", default=str(ROOT / "wini_ui" / "build" / "wini_ui"))
    ap.add_argument("--theme", default="light", choices=["light", "dark"])
    ap.add_argument("--hold", type=float, default=1.0,
                    help="seconds to keep the UI up after the turn (for screenshots)")
    args = ap.parse_args()

    print(f"[check] synthesizing utterance: {args.prompt!r}")
    pcm = synth_utterance(args.prompt)
    print(f"[check] utterance: {len(pcm)} bytes @ {RATE} Hz "
          f"({len(pcm) / 2 / RATE:.1f}s)")

    # Inject the canned utterance in place of the mic: return it ONCE, then stop
    # the session. run_session's _select_recorder('rms') returns this global.
    stop = threading.Event()
    served = {"n": 0}

    def fake_record(*a, **k):  # noqa: ANN001, ANN201
        if served["n"] == 0:
            served["n"] = 1
            print("[check] feeding synthesized utterance to the turn loop")
            return pcm
        stop.set()          # second ask: end after the one turn
        return None

    C.record_utterance = fake_record
    C.prime_input = lambda *a, **k: None   # no real mic to open in this check

    brain = BrainClient(args.server)
    print(f"[check] waiting for brain at {args.server} ...")
    brain.wait_ready()

    state = ModeState("EXPLAIN")
    chan = ModeChannel(state, port=args.ui_port).start()
    time.sleep(0.4)
    sink = ModeChannelSink(chan, store_dir=ROOT / "rag_store")

    ui_proc = None
    if args.launch_ui:
        import os
        env = dict(os.environ)
        env.setdefault("SDL_AUDIODRIVER", "dummy")
        print(f"[check] launching UI: {args.ui_bin} --port {args.ui_port}")
        ui_proc = subprocess.Popen([args.ui_bin, "--port", str(args.ui_port)],
                                   env=env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.STDOUT)
        # give the UI a moment to connect to the channel before the turn
        for _ in range(100):
            with chan._conn_lock:
                if chan._conn is not None:
                    break
            time.sleep(0.2)
        chan.set_sticky({"cmd": "ready"})
        print("[check] UI connected" if chan._conn else "[check] UI not connected (continuing)")

    try:
        reason = run_session(brain, sink, trigger="vad", vad="rms",
                             stop_event=stop, mode_state=state,
                             scenes=True, scene_theme=args.theme,
                             store_dir=ROOT / "rag_store")
        print(f"[check] session ended: {reason}")
    finally:
        if ui_proc is not None:
            time.sleep(args.hold)
            ui_proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
