"""Measure the FIRST voice turn after the brain reports ready.

Issue under test (2026-07-23): "once the display appears there should not be any
delay". The launcher gates the UI on /health ready, so whatever is still cold at
that moment is paid by the child's first sentence. This probe POSTs a real
utterance to /voice_turn the instant readiness flips and prints the per-stage
breakdown, so a cold STT or a cold streaming-TTS handshake shows up as a first
turn that is slower than the second.

    python tools/first_turn_probe.py --make-pcm /tmp/utt.raw   # once, needs TTS
    python tools/first_turn_probe.py --pcm /tmp/utt.raw --turns 3
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "http://127.0.0.1:8123"
UTTERANCE = "Can you explain what a quadratic equation is?"


def make_pcm(out: Path, text: str) -> None:
    """Synthesize `text` and write 16 kHz mono int16 PCM — a stand-in for the
    mic, so the probe runs over SSH where there is no PipeWire seat."""
    import numpy as np

    from voice.cloud_tts import CloudTts

    tts = CloudTts()
    audio = np.frombuffer(tts.synth(text), dtype=np.int16).astype(np.float32)
    # 24 kHz -> 16 kHz (STT rate); linear interp is plenty for a probe.
    n = int(round(len(audio) * 16000 / tts.rate))
    xp = np.linspace(0.0, 1.0, len(audio), endpoint=False)
    xn = np.linspace(0.0, 1.0, n, endpoint=False)
    pcm = np.interp(xn, xp, audio).astype(np.int16)
    out.write_bytes(pcm.tobytes())
    print(f"[probe] wrote {out} ({len(pcm) / 16000:.1f}s of speech)")


def wait_ready(timeout_s: float = 240.0) -> float:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout_s:
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=3) as r:
                if json.load(r).get("ready"):
                    return time.perf_counter() - t0
        except Exception:  # noqa: BLE001 — not listening yet
            pass
        time.sleep(0.25)
    raise TimeoutError("brain never reported ready")


def one_turn(pcm: bytes) -> dict:
    req = urllib.request.Request(
        f"{BASE}/voice_turn", data=pcm,
        headers={"Content-Type": "application/octet-stream",
                 "X-Sample-Rate": "16000", "X-Wini-Mode": "EXPLAIN",
                 "Accept-Encoding": "identity"})
    t0 = time.perf_counter()
    first_audio_ms = None
    result = None
    with urllib.request.urlopen(req, timeout=180) as r:
        for line in r:
            if not line.strip():
                continue
            obj = json.loads(line)
            if obj.get("part") == "audio":
                if first_audio_ms is None:
                    first_audio_ms = int((time.perf_counter() - t0) * 1000)
            elif obj.get("part") not in ("filler", "turn_meta"):
                result = obj
    total_ms = int((time.perf_counter() - t0) * 1000)
    return {"total_ms": total_ms, "server_first_audio_ms": first_audio_ms,
            "transcript": (result or {}).get("transcript"),
            "latency_ms": (result or {}).get("latency_ms")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--make-pcm", type=Path)
    ap.add_argument("--pcm", type=Path)
    ap.add_argument("--text", default=UTTERANCE)
    ap.add_argument("--turns", type=int, default=1)
    args = ap.parse_args()

    if args.make_pcm:
        make_pcm(args.make_pcm, args.text)
        return 0
    if not args.pcm:
        ap.error("--pcm or --make-pcm is required")

    pcm = args.pcm.read_bytes()
    print(f"[probe] waiting for ready ... ({wait_ready():.1f}s)")
    for i in range(args.turns):
        out = one_turn(pcm)
        print(f"[probe] turn {i + 1}: total={out['total_ms']}ms "
              f"first_audio={out['server_first_audio_ms']}ms")
        print(f"         transcript={out['transcript']!r}")
        print(f"         stages={out['latency_ms']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
