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
import atexit
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
                     wait_for_speech_s: float | None = None,
                     stop_event=None) -> bytes | None:
    """Block until one spoken utterance is captured; return int16 mono PCM bytes.

    Returns None if wait_for_speech_s elapses with no speech (lets the main loop
    breathe — check the server, handle Ctrl-C — instead of blocking forever), or
    if stop_event is set (checked between 50 ms blocks — PortAudio blocking
    reads ignore SIGTERM, so an in-process host must stop the loop this way).
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
            if stop_event is not None and stop_event.is_set():
                return None
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

# ONE persistent output stream, opened on first play and kept open across
# turns (and across sleep). Cheap USB codecs (the C-Media dongle) click
# audibly every time a stream opens/closes, so the old sd.play()-per-turn
# popped at both TTS start and stop. Kept module-global: only the client
# thread plays audio.
_out_stream = None
_out_stream_rate = None      # the rate the OPEN stream runs at (= device rate)
_dev_native_rate = None      # cached native output rate for the resample path

PLAY_FADE_S = 0.010    # fade-in/out to kill waveform-edge clicks
PLAY_TAIL_S = 0.150    # silence written after speech so the buffered tail is
                       # fully out before we return to listening (half-duplex)


def _close_out_stream() -> None:
    global _out_stream, _out_stream_rate
    if _out_stream is not None:
        try:
            _out_stream.close()
        except Exception:  # noqa: BLE001
            pass
    _out_stream = None
    _out_stream_rate = None


# Always release the single-PCM reSpeaker on exit: a process that dies holding
# the output substream leaves the USB device claimed, so the NEXT client's
# prime_output() can't open playback and the whole session is silent (observed
# 2026-07-16). atexit covers normal exit and SIGTERM (the platform's stop
# signal, handled as a clean exit); a hard SIGKILL still leaks until reaped.
atexit.register(_close_out_stream)


def _out_device_and_rate():
    """(device_index_or_None, native_rate) for a PLAYBACK-capable device.

    Never trust `sd.default.device[1]` alone: on the single-PCM reSpeaker Lite
    the default OUTPUT index transiently flips to -1 while PortAudio/PipeWire
    re-enumerate the USB card, and querying kind="output" then throws and the
    old code fell back to 48000 — a rate the 16 kHz-only device rejects, so
    EVERY stream open failed ("no usable output stream configuration"). Instead
    scan for the first device that actually reports output channels and use its
    reported default_samplerate."""
    import sounddevice as sd
    try:
        idx = sd.default.device[1]
        if idx is None or idx < 0 or sd.query_devices(idx)["max_output_channels"] < 1:
            idx = next(i for i, d in enumerate(sd.query_devices())
                       if d["max_output_channels"] > 0)
        return idx, int(sd.query_devices(idx)["default_samplerate"])
    except Exception:  # noqa: BLE001 — nothing playback-capable right now
        return None, 48000


def _device_native_out_rate() -> int:
    """The output device's native samplerate (what a raw hw: stream must run
    at). Cached — used when we must resample TTS to match the device."""
    global _dev_native_rate
    if _dev_native_rate is None:
        _dev_native_rate = _out_device_and_rate()[1]
    return _dev_native_rate


def _resample_to(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    """Resample float32 mono audio src->dst Hz. Needed when the output device
    is locked to its native rate and there is no Pulse/plug layer to resample
    for us (Pi ReSpeaker Lite = 16 kHz only; brain TTS = 24 kHz)."""
    if src == dst or len(audio) == 0:
        return audio
    from math import gcd
    g = gcd(int(src), int(dst))
    up, down = int(dst) // g, int(src) // g
    try:
        from scipy.signal import resample_poly
        return resample_poly(audio, up, down).astype(np.float32)
    except Exception:  # noqa: BLE001 — no scipy: linear interp (speech-adequate)
        n = int(round(len(audio) * dst / src))
        xp = np.linspace(0.0, 1.0, len(audio), endpoint=False)
        xn = np.linspace(0.0, 1.0, n, endpoint=False)
        return np.interp(xn, xp, audio).astype(np.float32)


def _ensure_out_stream(tts_rate: int):
    """Open ONE persistent output stream, kept across turns (cheap USB codecs
    click on every open/close). Returns (stream, stream_rate). Preference order:
      1. PulseAudio at the TTS rate — it resamples for us (Jetson, runbook §4.2).
      2. Default device at the TTS rate.
      3. Default device at its NATIVE rate — play_pcm resamples to match (Pi
         ReSpeaker Lite exposes only its raw 16 kHz hw device: no pulse/plug
         layer in PortAudio, so 24 kHz is rejected outright).
    """
    global _out_stream, _out_stream_rate
    import sounddevice as sd

    if _out_stream is not None:
        return _out_stream, _out_stream_rate
    idx, native = _out_device_and_rate()
    # Try, in order: the Jetson pulse resampler; the resolved playback device at
    # the TTS rate then at its native rate (play_pcm resamples); and finally the
    # PortAudio default at a few common rates as a last resort. Pinning `idx`
    # (not None) is what makes this survive the default-output→-1 flip.
    candidates = [("pulse", tts_rate), (idx, tts_rate), (idx, native),
                  (None, tts_rate), (None, native), (None, 48000), (None, 44100)]
    for device, sr in candidates:
        if device is not None and not isinstance(device, str) and device < 0:
            continue
        kw = {"samplerate": sr, "channels": 1, "dtype": "float32"}
        if device is not None:
            kw["device"] = device
        try:
            s = sd.OutputStream(**kw)
            s.start()
            _out_stream, _out_stream_rate = s, sr
            return _out_stream, _out_stream_rate
        except (ValueError, sd.PortAudioError):
            continue
    raise sd.PortAudioError("no usable output stream configuration")


def prime_output() -> bool:
    """Open the persistent output stream BEFORE the mic is ever used.

    On the reSpeaker Lite (one USB PCM shared with capture) claiming the
    playback substream first and keeping it open lets the mic coexist for the
    rest of the process; opening playback *after* a capture churn is what
    intermittently left the device with no usable output. Best-effort: a failure
    here just defers to the first play_pcm. Returns True if the stream opened."""
    try:
        _ensure_out_stream(RATE)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[client] output prime deferred ({e})")
        return False


def _prep_audio(pcm: bytes, src_rate: int, dst_rate: int) -> np.ndarray:
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    audio = _resample_to(audio, src_rate, dst_rate)
    fade = min(len(audio) // 2, int(dst_rate * PLAY_FADE_S))
    if fade > 0:
        env = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        audio[:fade] *= env
        audio[-fade:] *= env[::-1]
    return audio


def play_pcm(pcm: bytes, rate: int) -> None:
    import sounddevice as sd

    if not pcm:
        return
    try:
        stream, srate = _ensure_out_stream(rate)
        audio = _prep_audio(pcm, rate, srate)
        stream.write(audio.reshape(-1, 1))
        stream.write(np.zeros((int(srate * PLAY_TAIL_S), 1), dtype=np.float32))
    except Exception as e:  # noqa: BLE001 — device gone/re-routed: reset + fall back
        print(f"[client] persistent playback failed ({e}); falling back to sd.play")
        _close_out_stream()
        dev_rate = _device_native_out_rate()
        try:
            sd.play(_prep_audio(pcm, rate, dev_rate),
                    samplerate=dev_rate, blocking=True)
        except Exception as e2:  # noqa: BLE001
            print(f"[client] fallback playback also failed ({e2})")


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

    def voice_turn(self, pcm: bytes, rate: int = RATE, on_filler=None,
                   mode: str | None = None) -> dict:
        """POST one utterance; parse the server's NDJSON stream. A mid-turn
        {"part": "filler", ...} line is handed to on_filler the moment it
        arrives (played while the server is still generating); the last line
        is the full turn result.

        `mode` (EXPLAIN/PRACTICE/TEST from the touch UI) rides on the
        `X-Wini-Mode` header — additive; the brain records it (Part 12 §5.9).
        None ⇒ no header ⇒ byte-identical to today (server defaults to EXPLAIN).
        """
        headers = {"Content-Type": "application/octet-stream",
                   "X-Sample-Rate": str(rate)}
        if mode:
            headers["X-Wini-Mode"] = mode
        r = requests.post(f"{self.base}/voice_turn", data=pcm, timeout=120,
                          stream=True, headers=headers)
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

    def text_turn(self, text: str, speak: bool = True,
                  mode: str | None = None) -> dict:
        payload = {"text": text, "speak": speak}
        if mode:
            payload["mode"] = mode
        r = requests.post(f"{self.base}/turn", json=payload, timeout=120)
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# main loop
# ---------------------------------------------------------------------------

def speak_result(result: dict, sink, mute: bool = False) -> None:
    """Display up FIRST, then speech, then display down — 'show while explaining'.

    A sink may expose `on_turn(result)` to drive richer UI off the WHOLE turn
    (mode/test/writeback aren't in the display item) — the LVGL ModeChannelSink
    uses it for screen/stage/progress/feedback. Called before show() so the screen
    is switched before the card lands on it.

    `mute` skips the speech (the UI pause button was pressed while this turn was
    in flight — Wini must not talk over the student's other conversation); the
    display still updates so nothing is lost."""
    on_turn = getattr(sink, "on_turn", None)
    if on_turn is not None:
        try:
            on_turn(result)
        except Exception as e:  # noqa: BLE001 — a UI cue must never cost a turn
            print(f"[display] on_turn failed: {e}")
    display = result.get("display") or []
    if display:
        sink.show(display[0])
    try:
        if result.get("audio_b64") and not mute:
            play_pcm(base64.b64decode(result["audio_b64"]), int(result.get("audio_rate", 24000)))
    finally:
        sink.clear()


class _StopOrPause:
    """Duck-typed stop_event for record_utterance: aborts an in-flight recording
    the moment the UI pause button is tapped (checked every 50 ms block), not
    just at the next loop turn."""

    def __init__(self, stop_event, paused):
        self._stop = stop_event
        self._paused = paused

    def is_set(self) -> bool:
        return (self._stop is not None and self._stop.is_set()) or self._paused.is_set()


def run_session(brain: BrainClient, sink, *, trigger: str = "vad",
                rms_threshold: float = 0.018, silence_ms: int = 1200,
                exit_on_session_end: bool = False, stop_event=None,
                mode_state=None, log=print) -> str:
    """The listen → turn → speak loop, callable as a library (the ROS-less
    platform runs this on its ClientThread with an InProcSink + stop_event).

    `mode_state` (optional ModeState from the touch UI) is read fresh each turn
    and stamped on the POST as X-Wini-Mode — the child can switch modes between
    turns by tapping a different card.

    Returns why it stopped: "session_ended" (farewell + exit_on_session_end)
    or "stopped" (stop_event set). KeyboardInterrupt propagates to the caller.
    """
    # Claim the speaker BEFORE the first mic open: on the single-PCM reSpeaker
    # Lite, opening playback after a capture churn is what silenced the voice.
    prime_output()
    paused = getattr(mode_state, "paused", None) if mode_state is not None else None
    rec_stop = _StopOrPause(stop_event, paused) if paused is not None else stop_event
    while True:
        if stop_event is not None and stop_event.is_set():
            return "stopped"
        # UI pause button: mic muted, no brain turns until the second tap.
        if paused is not None and paused.is_set():
            log("[client] paused (mic muted) — tap the pause button to resume.")
            while paused.is_set():
                if stop_event is not None and stop_event.wait(0.2):
                    return "stopped"
                if stop_event is None:
                    time.sleep(0.2)
            log("[client] resumed — listening.")
            continue
        try:
            if trigger == "enter":
                input("\n[press Enter, then speak]")
            pcm = record_utterance(threshold=rms_threshold,
                                   silence_ms=silence_ms,
                                   wait_for_speech_s=30.0 if trigger == "vad" else None,
                                   stop_event=rec_stop)
            if not pcm:
                continue  # idle window elapsed (or paused/stopping) — loop re-checks
            if paused is not None and paused.is_set():
                continue  # paused mid-utterance: drop it, no brain turn
            t0 = time.time()
            early_seen = []

            def on_part(part: dict) -> None:
                early_seen.append(True)
                log(f"\nYou:  {part.get('transcript', '')}")
                if part.get("filler"):
                    log(f"Wini [{part.get('bank')}]: {part.get('filler')}")
                if part.get("audio_b64"):
                    play_pcm(base64.b64decode(part["audio_b64"]),
                             int(part.get("audio_rate", 24000)))

            # Thinking face while the brain works: from utterance sent until the
            # answer audio is back; the sink restores the pre-turn emotion after.
            sink.thinking(True)
            try:
                result = brain.voice_turn(
                    pcm, on_filler=on_part,
                    mode=(mode_state.mode if mode_state is not None else None))
            finally:
                sink.thinking(False)
            transcript = result.get("transcript", "")
            if not transcript:
                continue  # STT heard nothing intelligible — re-listen silently
            if not early_seen:
                log(f"\nYou:  {transcript}")
            log(f"Wini: {result.get('answer')}")
            log(f"[client] turn {time.time() - t0:.1f}s  latency={result.get('latency_ms')} "
                f"action={result.get('action')} display={bool(result.get('display'))}")
            speak_result(result, sink,
                         mute=(paused is not None and paused.is_set()))
            if result.get("session_ended"):
                if exit_on_session_end:
                    log("[client] session ended — going to sleep (hold chin to wake).")
                    return "session_ended"
                log("[client] session ended (farewell spoken) — back to idle listening.")
        except requests.RequestException as e:
            log(f"[client] server error ({e}); retrying in 3s")
            if stop_event is not None and stop_event.wait(3):
                return "stopped"
            if stop_event is None:
                time.sleep(3)


def main() -> None:
    ap = argparse.ArgumentParser(description="Wini thin client (mic+speaker+display)")
    ap.add_argument("--server", default=os.getenv("WINI_SERVER", "http://127.0.0.1:8123"))
    ap.add_argument("--display", choices=["none", "console", "ros", "lvgl"],
                    default=os.getenv("WINI_DISPLAY", "none"),
                    help="'lvgl' drives the on-device touch UI (wini_ui) over the "
                         "mode channel — requires --ui-port.")
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
    ap.add_argument("--ui-port", type=int, default=int(os.getenv("WINI_UI_PORT", "0")),
                    help="TCP port for the touch-UI mode channel (0 = disabled). "
                         "The LVGL picker (wini_ui) connects here and sends the "
                         "chosen EXPLAIN/PRACTICE/TEST mode.")
    ap.add_argument("--wait-for-mode", action="store_true",
                    help="block the first turn until the UI sends a mode selection "
                         "(makes the picker the genuine entry point). Needs --ui-port.")
    ap.add_argument("--mode", choices=["EXPLAIN", "PRACTICE", "TEST"], default=None,
                    help="start in this pedagogy mode (overridden by UI selections)")
    args = ap.parse_args()

    brain = BrainClient(args.server)

    # Pedagogy-mode channel: the touch UI (wini_ui) taps a card → mode_selected,
    # and (with --display lvgl) the client drives the turn back over the same socket.
    mode_state = None
    channel = None
    if args.ui_port:
        from .mode_channel import ModeChannel, ModeState
        mode_state = ModeState(args.mode)
        channel = ModeChannel(mode_state, port=args.ui_port).start()
    elif args.mode:
        from .mode_channel import ModeState
        mode_state = ModeState(args.mode)

    if args.display == "lvgl":
        if channel is None:
            print("[client] --display lvgl needs --ui-port; falling back to console.")
            sink = make_sink("console", Path(args.store))
        else:
            from .display_sinks import ModeChannelSink
            sink = ModeChannelSink(channel, store_dir=Path(args.store))
    else:
        sink = make_sink(args.display, Path(args.store))

    print(f"[client] waiting for brain at {args.server} ...")
    health = brain.wait_ready()
    print(f"[client] brain ready (gen_backend={health.get('gen_backend')})")

    if args.once_text:
        result = brain.text_turn(args.once_text, speak=True,
                                 mode=(mode_state.mode if mode_state else None))
        print(f"[client] action={result.get('action')} concept={result.get('concept')} "
              f"display={bool(result.get('display'))} latency={result.get('latency_ms')}")
        print(f"Wini: {result.get('answer')}")
        speak_result(result, sink)
        return

    exit_on_end = (args.on_session_end == "exit")
    # Sleep/wake cycle: after a "bye" (session_ended) with on-session-end=exit we
    # release the mic and send the UI back to the idle picker, then block on the
    # next card tap. The device is "asleep" — not recording — until woken.
    while True:
        if args.wait_for_mode and mode_state is not None and not mode_state.mode:
            print("[client] waiting for a mode selection from the touch UI "
                  f"(port {args.ui_port}). Ctrl-C to stop.")
            try:
                mode_state.wait_for_selection()
            except KeyboardInterrupt:
                print("\n[client] bye")
                return
            print(f"[client] mode selected: {mode_state.mode}")

        print(f"[client] listening (trigger={args.trigger}). Ctrl-C to stop.")
        try:
            reason = run_session(brain, sink, trigger=args.trigger,
                                 rms_threshold=args.rms_threshold,
                                 silence_ms=args.silence_ms,
                                 exit_on_session_end=exit_on_end,
                                 mode_state=mode_state)
        except KeyboardInterrupt:
            print("\n[client] bye")
            return

        # Go to sleep on "bye": mic already released (we're no longer recording),
        # return the panel to the idle picker, and re-arm for a fresh tap.
        if reason == "session_ended" and exit_on_end and args.wait_for_mode \
                and mode_state is not None:
            if channel is not None:
                channel.send({"cmd": "screen", "to": "idle"})
            mode_state.clear()
            print("[client] asleep (mic off) — tap a card to wake.")
            continue
        return


if __name__ == "__main__":
    main()
