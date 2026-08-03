"""debug_stt_test.py — CLI tool to test the brain's STT layer from Windows/Linux.

Sends a WAV file (or raw PCM) to the brain's /voice_turn endpoint over HTTP,
prints each NDJSON part as it arrives, then fetches /debug/logs to show the
per-layer debug events for that turn.

No mic or PipeWire needed — audio is POST'd as raw bytes, so this works
perfectly over SSH where the Pi's sound system is unavailable.

Usage:
    python tools/debug_stt_test.py --wav path/to/file.wav
    python tools/debug_stt_test.py --wav path/to/file.wav --host 192.168.29.104
    python tools/debug_stt_test.py --text "hello wini"       # text turn only
    python tools/debug_stt_test.py --host <cloud-run-url> --text "hello"

When --wav is given, the file header is stripped automatically for .wav files
and raw PCM is sent (LINEAR16, mono). Sample rate is read from the WAV header;
override with --rate if sending raw PCM.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ── ANSI colours (disabled on Windows unless terminal supports it) ──────────
try:
    import os
    _ansi = os.name != "nt" or os.environ.get("TERM") is not None \
        or "WT_SESSION" in os.environ or "COLORTERM" in os.environ
except Exception:
    _ansi = False

_C = {
    "reset":   "\033[0m"   if _ansi else "",
    "bold":    "\033[1m"   if _ansi else "",
    "muted":   "\033[90m"  if _ansi else "",
    "green":   "\033[92m"  if _ansi else "",
    "yellow":  "\033[93m"  if _ansi else "",
    "blue":    "\033[94m"  if _ansi else "",
    "magenta": "\033[95m"  if _ansi else "",
    "cyan":    "\033[96m"  if _ansi else "",
    "red":     "\033[91m"  if _ansi else "",
}

LAYER_COLOUR = {
    "SRV": "muted", "L0": "blue", "L1": "green", "L2": "magenta",
    "L3": "cyan",   "L4": "yellow", "L5": "yellow", "L6": "magenta",
    "L7": "cyan",   "L8": "green",
}
LAYER_NAME = {
    "SRV": "Server", "L0": "Connect", "L1": "STT", "L2": "Perception",
    "L3": "State", "L4": "Pedagogy", "L5": "Retrieval",
    "L6": "Generation", "L7": "TTS", "L8": "Write-back",
}


def c(color, text):
    return _C.get(color, "") + str(text) + _C["reset"]


def print_layer_event(entry: dict) -> None:
    layer = entry.get("layer", "??")
    event = entry.get("event", "")
    ts    = (entry.get("ts") or "")[-12:]  # last 12 chars = HH:MM:SS.mmm
    col   = LAYER_COLOUR.get(layer, "muted")
    name  = LAYER_NAME.get(layer, layer)
    skip  = {"ts", "layer", "event"}
    fields = "  ".join(
        f"{c('bold', k)}={c('green', repr(v)) if isinstance(v, str) else c('yellow', v)}"
        for k, v in entry.items() if k not in skip
    )
    print(f"  {c('muted', ts)}  {c(col, f'[{layer}]'):20s} "
          f"{c('bold', event):30s}  {c('muted', name):12s}  {fields}")


# ── WAV parsing ────────────────────────────────────────────────────────────

def load_wav(path: Path) -> tuple[bytes, int]:
    """Return (pcm_bytes, sample_rate). Strips the 44-byte standard WAV header."""
    data = path.read_bytes()
    # RIFF magic → it's a WAV
    if data[:4] == b"RIFF":
        # sample rate at bytes 24-27 (little-endian u32)
        rate = struct.unpack_from("<I", data, 24)[0]
        # Standard header = 44 bytes, but the 'data' sub-chunk can be offset
        # Walk the chunks to find 'data'
        offset = 12  # skip RIFF header (12 bytes)
        while offset + 8 <= len(data):
            chunk_id = data[offset:offset+4]
            chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
            if chunk_id == b"data":
                pcm = data[offset + 8: offset + 8 + chunk_size]
                return pcm, rate
            offset += 8 + chunk_size
        # Fallback: skip 44 bytes
        return data[44:], rate
    # No header — treat as raw PCM
    return data, 16000


# ── HTTP helpers ───────────────────────────────────────────────────────────

def do_request(url: str, body: bytes | None = None,
               headers: dict | None = None, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, data=body, headers=headers or {},
                                  method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_debug_logs(base: str, tail: int = 30) -> list[dict]:
    try:
        raw = do_request(f"{base}/debug/logs?tail={tail}")
        return json.loads(raw).get("entries", [])
    except Exception as e:
        print(c("red", f"  [warn] Could not fetch debug logs: {e}"))
        return []


# ── Voice turn ────────────────────────────────────────────────────────────

def run_voice_turn(base: str, pcm: bytes, rate: int) -> dict | None:
    url = f"{base}/voice_turn"
    print(c("blue", f"\n→ POST {url}  ({len(pcm):,} PCM bytes @ {rate} Hz)"))
    t0 = time.perf_counter()
    try:
        raw = do_request(url, body=pcm,
                         headers={"Content-Type": "application/octet-stream",
                                  "X-Sample-Rate": str(rate)},
                         timeout=90)
    except urllib.error.HTTPError as e:
        print(c("red", f"  HTTP {e.code}: {e.read().decode(errors='replace')}"))
        return None
    elapsed = time.perf_counter() - t0
    print(c("muted", f"  ← {elapsed*1000:.0f} ms total\n"))

    last = None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        part = obj.get("part", "final")
        if part == "filler":
            print(c("green",   f"  [filler]    transcript = {obj.get('transcript', '')}"))
        elif part == "turn_meta":
            print(c("cyan",    f"  [turn_meta] action={obj.get('action')}  "
                               f"concept={obj.get('concept')}  mode={obj.get('mode')}"))
            diag = obj.get("diagnostics") or {}
            print(c("muted",   f"              why={diag.get('why')}  "
                               f"mastery={diag.get('mastery')}"))
        elif part == "audio":
            print(c("muted",   f"  [audio]     seq={obj.get('seq')}  "
                               f"bytes={len(obj.get('audio_b64',''))*3//4}"))
        else:
            # Final line
            last = obj
            print()
            print(c("bold",    "  ── Final turn result ──"))
            print(c("green",   f"  transcript : {obj.get('transcript')}"))
            ans = (obj.get("answer") or "").strip()
            if ans:
                print(c("yellow",  f"  answer     : {ans[:200]}{'…' if len(ans)>200 else ''}"))
            lms = obj.get("latency_ms") or {}
            if lms:
                parts = "  ".join(f"{k}={v}" for k, v in lms.items())
                print(c("cyan",    f"  latency    : {parts}"))
    return last


# ── Text turn ─────────────────────────────────────────────────────────────

def run_text_turn(base: str, text: str) -> dict | None:
    url = f"{base}/turn"
    print(c("blue", f"\n→ POST {url}  text={repr(text[:80])}"))
    t0 = time.perf_counter()
    try:
        raw = do_request(url, body=json.dumps({"text": text, "speak": False}).encode(),
                         headers={"Content-Type": "application/json"}, timeout=90)
    except urllib.error.HTTPError as e:
        print(c("red", f"  HTTP {e.code}: {e.read().decode(errors='replace')}"))
        return None
    elapsed = time.perf_counter() - t0
    obj = json.loads(raw)
    print(c("muted", f"  ← {elapsed*1000:.0f} ms"))
    print(c("green",  f"  answer : {(obj.get('answer') or '')[:300]}"))
    lms = obj.get("latency_ms") or {}
    if lms:
        print(c("cyan",   f"  latency: " + "  ".join(f"{k}={v}" for k, v in lms.items())))
    return obj


# ── Health check ──────────────────────────────────────────────────────────

def check_health(base: str) -> bool:
    try:
        raw = do_request(f"{base}/health", timeout=10)
        h = json.loads(raw)
        if h.get("ready"):
            print(c("green", f"  /health → OK  gen_backend={h.get('gen_backend')}"))
            return True
        print(c("yellow", f"  /health → not ready: {h.get('error')}"))
        return False
    except Exception as e:
        print(c("red", f"  /health → FAILED: {e}"))
        return False


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="192.168.29.24",
                    help="Brain host IP or Cloud Run base URL (default: 192.168.29.24)")
    ap.add_argument("--port", default="8123", help="Port (default: 8123, ignored if --host is a URL)")
    ap.add_argument("--wav",  help="Path to WAV or raw PCM file for voice turn test")
    ap.add_argument("--rate", type=int, default=16000, help="PCM sample rate (used for raw files)")
    ap.add_argument("--text", help="Text to send via /turn (skips voice)")
    ap.add_argument("--no-debug-logs", action="store_true",
                    help="Skip fetching /debug/logs after the turn")
    ap.add_argument("--log-tail", type=int, default=40,
                    help="How many debug log entries to show (default: 40)")
    args = ap.parse_args()

    # Build base URL
    host = args.host.strip().rstrip("/")
    if host.startswith("http"):
        base = host
    else:
        base = f"http://{host}:{args.port}"

    print(c("bold", f"\nWini Debug STT Test — {base}"))
    print(c("muted", "─" * 60))

    # 1. Health check
    print(c("blue", "\n[L0] Checking /health …"))
    ok = check_health(base)
    if not ok:
        print(c("red", "Brain not ready. Abort."))
        sys.exit(1)

    # 2. Clear debug buffer for a clean test
    try:
        do_request(f"{base}/debug/clear", body=b"")
        print(c("muted", "  /debug/clear → OK (buffer flushed for clean test)"))
    except Exception:
        pass

    # 3. Run the turn
    result = None
    if args.text:
        result = run_text_turn(base, args.text)
    elif args.wav:
        wav_path = Path(args.wav)
        if not wav_path.exists():
            print(c("red", f"File not found: {wav_path}"))
            sys.exit(1)
        pcm, rate = load_wav(wav_path)
        if args.rate != 16000 and not str(args.wav).lower().endswith(".wav"):
            rate = args.rate   # user override for raw PCM
        print(c("blue", f"\n[L1] Loading audio: {wav_path.name}  "
                         f"({len(pcm):,} bytes  @ {rate} Hz)"))
        result = run_voice_turn(base, pcm, rate)
    else:
        print(c("yellow", "No --wav or --text specified. Running health check only."))

    # 4. Fetch and print debug layer events
    if result is not None and not args.no_debug_logs:
        print(c("bold", f"\n\n── Debug layer events (last {args.log_tail}) ──"))
        print(c("muted", "─" * 60))
        time.sleep(0.3)   # let async writeback events land
        entries = fetch_debug_logs(base, args.log_tail)
        if not entries:
            print(c("muted", "  (no entries in buffer)"))
        for entry in entries:
            print_layer_event(entry)
        print()

    print(c("muted", "─" * 60))
    print(c("green" if result else "red",
            "DONE" if result else "NO RESULT — check brain logs"))
    print()


if __name__ == "__main__":
    main()
