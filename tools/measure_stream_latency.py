"""Streaming latency measurement via /stream_turn (NDJSON, full pipeline).

Captures exact timestamps of:
  T_filler      : {"part":"filler"}  — STT+perception done, generation starting
  T_first_audio : {"part":"audio","seq":0} — first PCM chunk leaving server (speaker starts)
  T_turn_meta   : {"part":"turn_meta"} — display/visual directive sent to client

Gap = T_turn_meta - T_first_audio
  < 0  : visual ready BEFORE audio started  (IDEAL — SYNC_VISUAL working)
  > 0  : visual arrives AFTER audio started (the bug)
  >> 0 : visual comes after ALL audio done  (serial draw, SYNC_VISUAL OFF)

Usage:
    $env:WINI_SERVER="http://192.168.0.104:8123"
    python tools/measure_stream_latency.py [--turns 5] [--text "explain quadratics"]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests

BRAIN_URL = os.getenv("WINI_SERVER", "http://192.168.0.104:8123")
API_KEY   = os.getenv("WINI_API_KEY", "")

DEFAULT_TEXTS = [
    "explain quadratic equations",
    "what is the discriminant",
    "how do I find the roots of a parabola",
    "show me a worked example with two numbers",
    "why does the vertex matter",
]

# Set up UTF-8 output so the report prints cleanly on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def hdrs(extra=None):
    h = {"Content-Type": "application/json", "Accept-Encoding": "identity"}
    if API_KEY:
        h["X-Wini-Key"] = API_KEY
    if extra:
        h.update(extra)
    return h


def wait_ready(timeout_s=60.0):
    print(f"[probe] checking brain at {BRAIN_URL} ...")
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        try:
            r = requests.get(f"{BRAIN_URL}/health", timeout=5, headers=hdrs())
            h = r.json()
            if h.get("ready"):
                print(f"[probe] brain READY  gen_backend={h.get('gen_backend')}")
                return
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError("brain not ready")


def stream_turn(text: str) -> dict:
    """POST to /stream_turn and capture per-part timestamps."""
    payload = json.dumps({"text": text}).encode()
    t_req = time.perf_counter()

    r = requests.post(
        f"{BRAIN_URL}/stream_turn", data=payload, timeout=120, stream=True,
        headers=hdrs()
    )
    r.raise_for_status()

    T = {}          # part -> wall clock (perf_counter)
    audio_count = 0
    result_obj = {}

    for raw_line in r.raw:
        if not raw_line:
            continue
        t_now = time.perf_counter()
        t_rel = int((t_now - t_req) * 1000)
        try:
            obj = json.loads(raw_line.decode("utf-8").strip())
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        part = obj.get("part")
        if part == "filler":
            if "filler" not in T:
                T["filler"] = t_now
            print(f"    t={t_rel:5d}ms RECEIVED part=filler")
        elif part == "audio":
            audio_count += 1
            if "first_audio" not in T:
                T["first_audio"] = t_now
                print(f"    t={t_rel:5d}ms RECEIVED part=audio seq=0")
        elif part == "turn_meta":
            if "turn_meta" not in T:
                T["turn_meta"] = t_now
                print(f"    t={t_rel:5d}ms RECEIVED part=turn_meta (early visual!)")
            result_obj = obj
        elif part is None:
            if "final" not in T:
                T["final"] = t_now
                print(f"    t={t_rel:5d}ms RECEIVED part=final")
            if not result_obj:
                result_obj = obj


    t_done = time.perf_counter()
    lm = result_obj.get("latency_ms") or {}

    def rel(key):
        """ms from request start to that event"""
        return int((T[key] - t_req) * 1000) if key in T else None

    gap = None
    if "first_audio" in T and "turn_meta" in T:
        gap = int((T["turn_meta"] - T["first_audio"]) * 1000)

    return {
        "text": text,
        "wall_ms":        int((t_done - t_req) * 1000),
        "T_filler_ms":    rel("filler"),
        "T_first_audio":  rel("first_audio"),
        "T_turn_meta":    rel("turn_meta"),
        "T_final":        rel("final"),
        "gap_ms":         gap,           # T_turn_meta - T_first_audio
        "audio_chunks":   audio_count,
        "streamed":       result_obj.get("audio_streamed", False),
        # brain-side latency breakdown
        "lm_brain":       lm.get("brain"),
        "lm_tts_first":   lm.get("tts_first_chunk"),
        "lm_tts_total":   lm.get("tts"),
        "lm_t9":          lm.get("t9"),
        "lm_perception":  lm.get("perception"),
        "rl_earned":      (result_obj.get("visual") or {}).get("allowed"),
        "action":         result_obj.get("action"),
    }


def fmt(v, w=6):
    return f"{int(v):>{w}}" if v is not None else f"{'--':>{w}}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=5)
    ap.add_argument("--text", default=None)
    ap.add_argument("--skip-ready", action="store_true")
    args = ap.parse_args()

    if not args.skip_ready:
        wait_ready()

    texts = (
        [args.text] * args.turns if args.text
        else (DEFAULT_TEXTS * (args.turns // len(DEFAULT_TEXTS) + 1))[:args.turns]
    )

    # Header
    print()
    hdr = (f"{'#':>3}  {'Wall':>6}  {'Percep':>6}  {'Filler':>6}  "
           f"{'1stAud':>6}  {'Meta':>6}  {'Gap':>7}  {'Chk':>3}  "
           f"{'TTSfst':>6}  {'TTStot':>6}  {'T9':>5}  RL  Action")
    print(hdr)
    print("-" * len(hdr))

    rows = []
    for i, text in enumerate(texts, 1):
        try:
            row = stream_turn(text)
        except Exception as e:
            print(f"{i:>3}  ERROR: {e}")
            continue

        gap_s = f"{row['gap_ms']:>+7}" if row['gap_ms'] is not None else f"{'--':>7}"
        rl_s  = "Y" if row.get("rl_earned") else "N"
        print(
            f"{i:>3}  {fmt(row['wall_ms'])}  {fmt(row['lm_perception'])}  "
            f"{fmt(row['T_filler_ms'])}  {fmt(row['T_first_audio'])}  "
            f"{fmt(row['T_turn_meta'])}  {gap_s}  {row['audio_chunks']:>3}  "
            f"{fmt(row['lm_tts_first'])}  {fmt(row['lm_tts_total'])}  "
            f"{fmt(row['lm_t9'], 5)}  {rl_s}   {row.get('action','?')}"
        )
        rows.append(row)
        time.sleep(0.5)

    if not rows:
        print("No results.")
        return

    print()
    print("== SUMMARY ==")
    def avg(k):
        vs = [r[k] for r in rows if r.get(k) is not None]
        return round(sum(vs) / len(vs)) if vs else None

    print(f"  Turns             : {len(rows)}")
    print(f"  Avg wall time     : {fmt(avg('wall_ms'))} ms")
    print(f"  Avg perception    : {fmt(avg('lm_perception'))} ms")
    print(f"  Avg T_first_audio : {fmt(avg('T_first_audio'))} ms  (rel. to request start)")
    print(f"  Avg T_turn_meta   : {fmt(avg('T_turn_meta'))} ms  (rel. to request start)")
    print(f"  Avg TTS first chk : {fmt(avg('lm_tts_first'))} ms")
    print(f"  Avg TTS total     : {fmt(avg('lm_tts_total'))} ms")
    print(f"  Avg T9 pick       : {fmt(avg('lm_t9'), 5)} ms")
    print()

    gap_avg = avg('gap_ms')
    if gap_avg is not None:
        sign = "+" if gap_avg >= 0 else ""
        print(f"  [** SPEECH->VISUAL GAP **]  avg = {sign}{gap_avg} ms")
        if gap_avg < 0:
            print(f"  => Visual arrives BEFORE audio starts — SYNC_VISUAL is working!")
        elif gap_avg < 300:
            print(f"  => Gap < 300ms — acceptable, visual appears at start of speech")
        elif gap_avg < 1000:
            print(f"  => Gap {gap_avg}ms — visible but minor; SYNC_VISUAL may be partially helping")
        else:
            print(f"  => Gap > 1s — visual appears well AFTER speech starts; check WINI_SYNC_VISUAL")
    print()


if __name__ == "__main__":
    main()
