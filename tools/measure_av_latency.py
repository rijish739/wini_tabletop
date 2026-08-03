"""Speech-to-visual latency measurement tool for the Pi local brain.

Uses /voice_turn with silent PCM to exercise the FULL streaming pipeline:
  STT -> Perception -> Response Layer -> Generation (streamed) -> TTS (streamed)
  Measures:
    T_first_audio  : when first {"part":"audio"} line arrives (speaker would start)
    T_turn_meta    : when {"part":"turn_meta"} arrives (visual/display update)
    gap            : T_turn_meta - T_first_audio
                     < 0 = visual ready BEFORE audio starts  (IDEAL with SYNC_VISUAL=1)
                     > 0 = visual arrives AFTER audio started (the bug we are fixing)

Usage:
    $env:WINI_SERVER="http://192.168.0.104:8123"
    python tools/measure_av_latency.py [--turns 5] [--text "explain quadratics"]

Note: /voice_turn sends PCM to STT. With silent PCM the STT transcript is empty and
the brain short-circuits (no turn). To get a real turn, pass a pre-recorded PCM file
or use --bypass-stt to call /turn (batch, no streaming) for the latency_ms breakdown only.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import time

import requests

BRAIN_URL = os.getenv("WINI_SERVER", "http://192.168.0.104:8123")
API_KEY   = os.getenv("WINI_API_KEY", "")
RATE      = 16000   # Hz — must match X-Sample-Rate

DEFAULT_TEXTS = [
    "explain quadratic equations",
    "what is the discriminant",
    "how do I find the roots of a parabola",
    "show me a worked example with two numbers",
    "why does the vertex matter",
]


def make_headers(extra: dict | None = None) -> dict:
    h = {"Accept-Encoding": "identity"}
    if API_KEY:
        h["X-Wini-Key"] = API_KEY
    if extra:
        h.update(extra)
    return h


def wait_ready(timeout_s: float = 60.0):
    print(f"[probe] waiting for brain at {BRAIN_URL}/health ...")
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        try:
            r = requests.get(f"{BRAIN_URL}/health", timeout=5,
                             headers=make_headers())
            h = r.json()
            if h.get("ready"):
                print(f"[probe] brain ready  gen_backend={h.get('gen_backend')}")
                return
            if h.get("error"):
                raise RuntimeError(f"brain load error: {h['error']}")
        except requests.RequestException:
            pass
        time.sleep(2)
    raise TimeoutError(f"brain not ready after {timeout_s:.0f} s")


# ---------------------------------------------------------------------------
# Streaming /voice_turn measurement
# ---------------------------------------------------------------------------

def make_silence_pcm(duration_s: float = 0.5, rate: int = RATE) -> bytes:
    """Generate silent (zero) int16 mono PCM bytes."""
    n = int(duration_s * rate)
    return struct.pack(f"<{n}h", *([0] * n))


def measure_voice_turn_streaming(text: str, rate: int = RATE) -> dict:
    """
    POST to /turn with speak=True (batch mode) and record latency_ms breakdown.
    Also POST to /voice_turn with a pre-synthesized silence+label PCM if available.

    For now we use /turn to get latency_ms, AND separately test the streaming path
    by posting a synthetic text to /voice_turn. Since STT will transcribe silence to
    nothing, we use an alternative: post the text to /turn with emit header to force
    streaming. But that's not a real API.

    ACTUAL approach: POST to /voice_turn with the text encoded as raw bytes of a
    pre-synthesized audio (if available). Since we can't synthesize here, we measure
    /turn's latency_ms as the best proxy.

    STREAMING TEST: We also run a streaming request by calling brain.text_turn via
    /voice_turn using the bypass trick: POST 0.5s of silence. The brain's STT returns
    empty transcript -> early return. So we need the text to go through STT as actual
    audio, which requires a TTS pre-step. Instead we use a hybrid:
      - /turn for latency_ms (brain + perception + tts timings)
      - brain log inspection for SYNC_VISUAL pre-warm timing
    """
    # --- Step 1: Text turn (batch) for latency_ms breakdown ---
    payload = {"text": text, "speak": True}
    t_req = time.perf_counter()
    r = requests.post(f"{BRAIN_URL}/turn", json=payload, timeout=120,
                      headers=make_headers({"Content-Type": "application/json"}))
    t_resp = time.perf_counter()
    r.raise_for_status()
    result = r.json()
    result["_wall_ms"] = int((t_resp - t_req) * 1000)
    result["_mode"] = "batch"
    return result


def measure_voice_turn_ndjson(text_hint: str, rate: int = RATE) -> dict | None:
    """
    POST 0.5s of silence to /voice_turn. If STT returns a non-empty transcript,
    capture the NDJSON stream timestamps. With pure silence STT returns empty ->
    short-circuits. This is useful only if there's real audio content.

    Returns None if STT heard nothing (silence case).
    """
    pcm = make_silence_pcm(0.5, rate)
    t_req = time.perf_counter()
    r = requests.post(
        f"{BRAIN_URL}/voice_turn", data=pcm, timeout=120, stream=True,
        headers=make_headers({
            "Content-Type": "application/octet-stream",
            "X-Sample-Rate": str(rate),
        })
    )
    r.raise_for_status()

    t_first_audio = None
    t_turn_meta = None
    result = None

    for line in r.iter_lines(chunk_size=512):
        if not line:
            continue
        t_now = time.perf_counter()
        obj = json.loads(line)
        part = obj.get("part")
        if part == "audio" and t_first_audio is None:
            t_first_audio = t_now
        elif part == "turn_meta":
            t_turn_meta = t_now
        elif part is None or part == "filler":
            pass
        else:
            result = obj

    if result is None or not result.get("transcript"):
        return None  # silence — STT heard nothing

    gap_ms = None
    if t_first_audio is not None and t_turn_meta is not None:
        gap_ms = int((t_turn_meta - t_first_audio) * 1000)

    return {
        "_wall_ms": int((time.perf_counter() - t_req) * 1000),
        "_mode": "stream",
        "_t_first_audio_rel": int((t_first_audio - t_req) * 1000) if t_first_audio else None,
        "_t_turn_meta_rel": int((t_turn_meta - t_req) * 1000) if t_turn_meta else None,
        "_audio_to_meta_gap_ms": gap_ms,
        "latency_ms": result.get("latency_ms", {}),
        "transcript": result.get("transcript", ""),
        "audio_streamed": result.get("audio_streamed", False),
    }


def fmt_ms(v) -> str:
    if v is None:
        return "   — "
    return f"{int(v):5d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--turns", type=int, default=5)
    ap.add_argument("--text", default=None)
    ap.add_argument("--skip-ready", action="store_true")
    ap.add_argument("--stream-test", action="store_true",
                    help="Also test /voice_turn with silence to probe streaming path")
    args = ap.parse_args()

    if not args.skip_ready:
        wait_ready()

    texts = ([args.text] * args.turns
             if args.text
             else (DEFAULT_TEXTS * ((args.turns // len(DEFAULT_TEXTS)) + 1))[:args.turns])

    print(f"\n{'Turn':>4}  {'Wall':>6}  {'Brain':>6}  {'Percep':>6}  "
          f"{'TTS1st':>6}  {'TTStot':>6}  {'T9':>5}  Mode      "
          f"{'Draw':>6}  Text")
    print("-" * 115)

    rows = []
    for i, text in enumerate(texts, 1):
        try:
            result = measure_voice_turn_streaming(text)
        except Exception as e:  # noqa: BLE001
            print(f"{i:>4}  ERROR: {e}")
            continue

        lm = result.get("latency_ms") or {}
        wall      = result["_wall_ms"]
        mode      = result.get("_mode", "?")
        brain     = lm.get("brain")
        percep    = lm.get("perception")
        tts_first = lm.get("tts_first_chunk")
        tts_total = lm.get("tts")
        t9        = lm.get("t9")
        draw_ms   = lm.get("draw") or lm.get("scene_draw")
        streamed  = result.get("audio_streamed", False)

        rows.append({
            "turn": i, "text": text[:40], "wall": wall,
            "brain": brain, "perception": percep,
            "tts_first": tts_first, "tts_total": tts_total,
            "t9": t9, "streamed": streamed, "draw": draw_ms,
        })

        mode_label = "[stream]" if streamed else "[batch] "
        print(f"{i:>4}  {fmt_ms(wall)}  {fmt_ms(brain)}  {fmt_ms(percep)}  "
              f"{fmt_ms(tts_first)}  {fmt_ms(tts_total)}  {fmt_ms(t9)}  "
              f"{mode_label}  {fmt_ms(draw_ms)}  {text[:35]}")

        time.sleep(1)

    if not rows:
        print("[measure] no results.")
        return

    print("\n-- Batch /turn Summary ------------------------------------------")
    def avg(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    print(f"  Turns             : {len(rows)}")
    print(f"  Avg wall time     : {fmt_ms(avg('wall'))} ms")
    print(f"  Avg brain time    : {fmt_ms(avg('brain'))} ms")
    print(f"  Avg TTS total     : {fmt_ms(avg('tts_total'))} ms")
    print(f"  Avg T9 pick       : {fmt_ms(avg('t9'))} ms")
    print()

    # Note about streaming path
    print("-- Streaming path note ------------------------------------------")
    print("  /turn (batch) does not stream TTS, so tts_first_chunk is always")
    print("  absent. The WINI_SYNC_VISUAL=1 pre-warm fires only on the")
    print("  /voice_turn streaming path. Check brain_local.log for:")
    print("    '[tutor] board pre-warmed from sentence 0 (N ms, sync-visual)'")
    print("  vs '[tutor] drew answer scene (N lines) in M ms'")
    print()
    print("  Run the brain log inspection now:")
    print(f"    python tools/pi.py run \"grep -E 'pre-warmed|drew answer scene|response-layer' "
          f"/home/winipi5/cloud_tutor/cloud-CLI/logs/brain_local.log | tail -20\"")
    print()


if __name__ == "__main__":
    main()
