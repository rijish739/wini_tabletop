"""Wini thin client — mic in, speaker out, display metadata to a sink.

The whole loop (half-duplex by construction — it never records while speaking):

    idle listen (RMS VAD) ─► record until silence ─► POST /voice_turn (raw PCM)
        ◄─ {transcript, answer, display, audio_b64, session_ended}
    show display ─► play audio ─► clear display ─► back to idle listen

No wakeword, no local ASR/TTS/LLM — the brain service (wini_server.py) does
everything. Triggers:
    --trigger vad    always-listening RMS endpointing (default)
    --trigger enter  push-to-talk (press Enter, speak, silence ends it) — also
                     the shape a TOUCH SENSOR trigger will take: replace the
                     input() wait with the GPIO callback.

Test modes (no mic needed):
    --once-text "explain quadratic zeroes"   one text turn through the FULL
        output path (display + spoken audio), then exit.

Deps: numpy, sounddevice, requests. Display sinks may add platform extras.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
from pathlib import Path

import numpy as np
import requests

from .display_sinks import make_sink

RATE = 16000


# ---------------------------------------------------------------------------
# platform seam 1: microphone (RMS auto-endpoint, ~40 lines, no model)
# ---------------------------------------------------------------------------

def record_utterance(rate: int = RATE, threshold: float = 0.018, silence_ms: int = 1200,
                     hard_cap_s: float = 15.0, preroll_ms: int = 400,
                     wait_for_speech_s: float | None = None) -> bytes | None:
    """Block until one spoken utterance is captured; return int16 mono PCM bytes.

    Returns None if wait_for_speech_s elapses with no speech (lets the main loop
    breathe — check the server, handle Ctrl-C — instead of blocking forever).
    """
    import sounddevice as sd

    block_ms = 50
    block = int(rate * block_ms / 1000)
    silence_blocks = max(1, silence_ms // block_ms)
    preroll_blocks = max(1, preroll_ms // block_ms)
    wait_blocks = None if wait_for_speech_s is None else int(wait_for_speech_s * 1000 / block_ms)
    ring: list[np.ndarray] = []
    chunks: list[np.ndarray] = []
    speaking = False
    silent = waited = 0
    deadline_blocks = int(hard_cap_s * 1000 / block_ms)
    # Route via PulseAudio where present (honors PULSE_SOURCE; the raw ALSA
    # default on the Jetson is pinned to the onboard card with no mic — §4.2).
    try:
        stream_cm = sd.InputStream(samplerate=rate, channels=1, dtype="int16",
                                   blocksize=block, device="pulse")
    except (ValueError, sd.PortAudioError):
        stream_cm = sd.InputStream(samplerate=rate, channels=1, dtype="int16",
                                   blocksize=block)
    with stream_cm as stream:
        while True:
            data, _ = stream.read(block)
            flat = data.reshape(-1).copy()
            rms = float(np.sqrt(np.mean((flat.astype(np.float32) / 32768.0) ** 2)))
            if not speaking:
                ring.append(flat)
                ring = ring[-preroll_blocks:]
                if rms >= threshold:
                    speaking = True
                    chunks.extend(ring)
                    ring.clear()
                    silent = 0
                else:
                    waited += 1
                    if wait_blocks is not None and waited >= wait_blocks:
                        return None
            else:
                chunks.append(flat)
                if rms < threshold:
                    silent += 1
                    if silent >= silence_blocks:
                        break
                else:
                    silent = 0
                if len(chunks) >= deadline_blocks:
                    break
    return np.concatenate(chunks).tobytes()


# ---------------------------------------------------------------------------
# platform seam 2: speaker
# ---------------------------------------------------------------------------

def play_pcm(pcm: bytes, rate: int) -> None:
    import sounddevice as sd

    if not pcm:
        return
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    try:
        # Route through PulseAudio where present (Jetson: raw ALSA default is
        # pinned to the onboard card and rejects 24 kHz — §4.2 of the runbook;
        # PULSE_SINK/select_usb_audio.sh pick the USB speaker and resample).
        sd.play(audio, samplerate=rate, blocking=True, device="pulse")
    except (ValueError, sd.PortAudioError):
        sd.play(audio, samplerate=rate, blocking=True)


# ---------------------------------------------------------------------------
# brain service contract (platform seam 3 is the display sink; 4 is the trigger)
# ---------------------------------------------------------------------------

class BrainClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def wait_ready(self, timeout_s: float = 300.0) -> dict:
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            try:
                h = requests.get(f"{self.base}/health", timeout=5).json()
                if h.get("ready"):
                    return h
                if h.get("error"):
                    raise RuntimeError(f"brain failed to load: {h['error']}")
            except requests.RequestException:
                pass
            time.sleep(2)
        raise TimeoutError(f"brain at {self.base} not ready after {timeout_s:.0f}s")

    def voice_turn(self, pcm: bytes, rate: int = RATE, on_filler=None) -> dict:
        """POST one utterance; parse the server's NDJSON stream. A mid-turn
        {"part": "filler", ...} line is handed to on_filler the moment it
        arrives (played while the server is still generating); the last line
        is the full turn result."""
        r = requests.post(f"{self.base}/voice_turn", data=pcm, timeout=120,
                          stream=True,
                          headers={"Content-Type": "application/octet-stream",
                                   "X-Sample-Rate": str(rate)})
        r.raise_for_status()
        result = None
        for line in r.iter_lines():
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("part") == "filler":
                if on_filler is not None:
                    on_filler(obj)
            else:
                result = obj
        if result is None:
            raise requests.RequestException("voice_turn stream ended without a result")
        return result

    def text_turn(self, text: str, speak: bool = True) -> dict:
        r = requests.post(f"{self.base}/turn", json={"text": text, "speak": speak},
                          timeout=120)
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# main loop
# ---------------------------------------------------------------------------

def speak_result(result: dict, sink) -> None:
    """Display up FIRST, then speech, then display down — 'show while explaining'."""
    display = result.get("display") or []
    if display:
        sink.show(display[0])
    try:
        if result.get("audio_b64"):
            play_pcm(base64.b64decode(result["audio_b64"]), int(result.get("audio_rate", 24000)))
    finally:
        sink.clear()


def main() -> None:
    ap = argparse.ArgumentParser(description="Wini thin client (mic+speaker+display)")
    ap.add_argument("--server", default=os.getenv("WINI_SERVER", "http://127.0.0.1:8123"))
    ap.add_argument("--display", choices=["none", "console", "ros"],
                    default=os.getenv("WINI_DISPLAY", "none"))
    ap.add_argument("--store", default=os.getenv("WINI_STORE",
                    str(Path(__file__).resolve().parent.parent / "rag_store")),
                    help="local store copy holding figure_crops/ (the 'SD card')")
    ap.add_argument("--trigger", choices=["vad", "enter"], default="vad")
    ap.add_argument("--on-session-end", choices=["listen", "exit"],
                    default=os.getenv("WINI_ON_SESSION_END", "listen"),
                    help="'exit' = go to sleep after the farewell (the touch "
                         "trigger node restarts the client on a chin hold)")
    ap.add_argument("--rms-threshold", type=float, default=0.018)
    ap.add_argument("--silence-ms", type=int, default=1200)
    ap.add_argument("--once-text", default=None,
                    help="one text turn through the full output path, then exit")
    args = ap.parse_args()

    sink = make_sink(args.display, Path(args.store))
    brain = BrainClient(args.server)
    print(f"[client] waiting for brain at {args.server} ...")
    health = brain.wait_ready()
    print(f"[client] brain ready (gen_backend={health.get('gen_backend')})")

    if args.once_text:
        result = brain.text_turn(args.once_text, speak=True)
        print(f"[client] action={result.get('action')} concept={result.get('concept')} "
              f"display={bool(result.get('display'))} latency={result.get('latency_ms')}")
        print(f"Wini: {result.get('answer')}")
        speak_result(result, sink)
        return

    print(f"[client] listening (trigger={args.trigger}). Ctrl-C to stop.")
    while True:
        try:
            if args.trigger == "enter":
                input("\n[press Enter, then speak]")
            pcm = record_utterance(threshold=args.rms_threshold,
                                   silence_ms=args.silence_ms,
                                   wait_for_speech_s=30.0 if args.trigger == "vad" else None)
            if not pcm:
                continue  # idle window elapsed — just listen again
            t0 = time.time()
            early_seen = []

            def on_part(part: dict) -> None:
                early_seen.append(True)
                print(f"\nYou:  {part.get('transcript', '')}")
                if part.get("filler"):
                    print(f"Wini [{part.get('bank')}]: {part.get('filler')}")
                if part.get("audio_b64"):
                    play_pcm(base64.b64decode(part["audio_b64"]),
                             int(part.get("audio_rate", 24000)))

            # Thinking face while the brain works: from utterance sent until the
            # answer audio is back; the sink restores the pre-turn emotion after.
            sink.thinking(True)
            try:
                result = brain.voice_turn(pcm, on_filler=on_part)
            finally:
                sink.thinking(False)
            transcript = result.get("transcript", "")
            if not transcript:
                continue  # STT heard nothing intelligible — re-listen silently
            if not early_seen:
                print(f"\nYou:  {transcript}")
            print(f"Wini: {result.get('answer')}")
            print(f"[client] turn {time.time() - t0:.1f}s  latency={result.get('latency_ms')} "
                  f"action={result.get('action')} display={bool(result.get('display'))}")
            speak_result(result, sink)
            if result.get("session_ended"):
                if args.on_session_end == "exit":
                    print("[client] session ended — going to sleep (hold chin to wake).")
                    return
                print("[client] session ended (farewell spoken) — back to idle listening.")
        except KeyboardInterrupt:
            print("\n[client] bye")
            return
        except requests.RequestException as e:
            print(f"[client] server error ({e}); retrying in 3s")
            time.sleep(3)


if __name__ == "__main__":
    main()
