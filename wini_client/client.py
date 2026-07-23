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
import queue
import threading
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
    reason = "silence"
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
                    reason = "hard_cap"
                    break
    pcm = np.concatenate(chunks)
    # Part 13 diagnostics: the endpoint window is the ONE interval neither
    # ttfa_ms (armed AFTER this returns) nor the server's latency_ms can see.
    # `speech_ms` is what the child actually said; `hangover_ms` is the fixed
    # silence tail we spend confirming they stopped; `reason` distinguishes a
    # clean endpoint from a runaway that ran to the 15 s cap.
    record_utterance.last = {
        "capture_ms": int(len(pcm) / rate * 1000),
        "speech_ms": int(max(0, len(chunks) - silence_blocks) * block_ms),
        "hangover_ms": int(min(silent, silence_blocks) * block_ms),
        "reason": reason,
    }
    return pcm.tobytes()


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


def _prep_audio(pcm: bytes, src_rate: int, dst_rate: int,
                fade_in: bool = True, fade_out: bool = True) -> np.ndarray:
    """PCM bytes -> float32 mono at dst_rate, with edge fades to kill clicks.

    The fades are optional because a STREAMED answer arrives as many chunks: a
    fade at every chunk boundary is audible as a periodic dip and is exactly what
    makes chunked TTS sound robotic. Streamed playback fades in on the first
    chunk and out on the last, and not in between.
    """
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    audio = _resample_to(audio, src_rate, dst_rate)
    fade = min(len(audio) // 2, int(dst_rate * PLAY_FADE_S))
    if fade > 0:
        env = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        if fade_in:
            audio[:fade] *= env
        if fade_out:
            audio[-fade:] *= env[::-1]
    return audio


# One shared OutputStream (_out_stream) serves TTS, emotion sounds, the purr
# loop and idle ambience — all from different threads. PortAudio blocking
# writes from two threads at once garble or raise, so every write goes through
# this lock. Emotion sounds are short (≤~0.5 s) so the lock is held only briefly;
# the purr loop passes an ``interrupt`` so a starting TTS turn preempts it fast.
_play_lock = threading.Lock()
_PREEMPT_SLICE_S = 0.08          # purr write granularity when interruptible


def play_pcm(pcm: bytes, rate: int,
             interrupt: "threading.Event | None" = None) -> None:
    import sounddevice as sd

    if not pcm:
        return
    with _play_lock:
        try:
            stream, srate = _ensure_out_stream(rate)
            audio = _prep_audio(pcm, rate, srate)
            buf = audio.reshape(-1, 1)
            if interrupt is None:
                stream.write(buf)
            else:
                # Write in slices so a higher-priority sound (TTS) can preempt
                # an in-flight low-priority loop within one slice, not one chunk.
                step = max(1, int(srate * _PREEMPT_SLICE_S))
                for i in range(0, len(buf), step):
                    if interrupt.is_set():
                        return
                    stream.write(buf[i:i + step])
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


class Ttfa:
    """Time-to-first-audio: recording ends → the child hears the first sample.

    This is the number Part 13 is judged on, and the only one that spans the
    stages the server can't see (VAD hangover on one side, playback on the
    other). Armed when record_utterance returns; marked by whichever audio path
    plays first (filler line, streamed chunk, or the whole-answer fallback).
    """

    def __init__(self) -> None:
        self._t0 = None
        self.ms = None

    def arm(self) -> None:
        self._t0 = time.perf_counter()
        self.ms = None

    def mark(self) -> None:
        if self._t0 is not None and self.ms is None:
            self.ms = int((time.perf_counter() - self._t0) * 1000)


def play_pcm_chunk(pcm: bytes, rate: int, *, first: bool, last: bool) -> None:
    """Write ONE chunk of a streamed answer into the persistent output stream.

    Same lock and same stream as play_pcm — but no per-chunk fades (see
    _prep_audio) and the PLAY_TAIL_S half-duplex tail only after the final
    chunk, so a streamed answer sounds like one continuous utterance rather
    than a sequence of clips.
    """
    if not pcm:
        return
    with _play_lock:
        stream, srate = _ensure_out_stream(rate)
        audio = _prep_audio(pcm, rate, srate, fade_in=first, fade_out=last)
        stream.write(audio.reshape(-1, 1))
        if last:
            stream.write(np.zeros((int(srate * PLAY_TAIL_S), 1), dtype=np.float32))


class AudioStreamPlayer:
    """Plays streamed PCM chunks in order, on a background thread.

    The point is that the HTTP reader must never block on playback: chunk N
    plays while chunk N+1 is still arriving. Chunks are handed over through a
    bounded queue — bounded so a fast server applies backpressure instead of
    growing the client's memory without limit.

    Ordering is guaranteed by construction (one TCP stream, one consumer, FIFO
    queue); `seq` is carried only to ASSERT that, never to reorder. An underrun
    simply waits for the next chunk — it must never skip, because a skipped
    chunk is a missing word.

    ``set_speaking`` spans the WHOLE sequence: the touch-emotion engine shares
    the single reSpeaker playback substream, and if it thought Wini had stopped
    talking between chunks it would cut in with its own audio mid-answer
    (wini_client/SPEAKER_TROUBLESHOOTING.md).
    """

    def __init__(self, audio_manager=None, ttfa: "Ttfa | None" = None,
                 log=print) -> None:
        self._q: "queue.Queue[tuple[bytes, int] | None]" = queue.Queue(maxsize=32)
        self._am = audio_manager
        self._ttfa = ttfa
        self._log = log
        self._thread: threading.Thread | None = None
        self._error: Exception | None = None
        self._next_seq = 0
        self._last_rate = 24000
        self.chunks_played = 0

    def push(self, pcm: bytes, rate: int, seq: int | None = None) -> None:
        if seq is not None:
            if seq != self._next_seq:
                self._log(f"[client] audio chunk out of order: got {seq}, "
                          f"expected {self._next_seq} — playing in arrival order")
            self._next_seq = seq + 1
        if self._thread is None:
            if self._am is not None:
                self._am.set_speaking(True)
            self._thread = threading.Thread(target=self._run, name="audio-stream",
                                            daemon=True)
            self._thread.start()
        self._q.put((pcm, rate))

    def _run(self) -> None:
        first = True
        try:
            while True:
                item = self._q.get()
                if item is None:
                    # End of stream: flush the half-duplex tail so the buffered
                    # audio is fully out before the mic re-opens.
                    if not first:
                        play_pcm_chunk(b"\x00\x00", self._last_rate,
                                       first=False, last=True)
                    return
                pcm, rate = item
                self._last_rate = rate
                if first and self._ttfa is not None:
                    self._ttfa.mark()
                play_pcm_chunk(pcm, rate, first=first, last=False)
                first = False
                self.chunks_played += 1
        except Exception as e:  # noqa: BLE001 — surfaced to the caller in finish()
            self._error = e
        finally:
            if self._am is not None:
                self._am.set_speaking(False)

    @property
    def started(self) -> bool:
        return self._thread is not None

    def finish(self, timeout: float = 120.0) -> None:
        """Block until every queued chunk has been spoken."""
        if self._thread is None:
            return
        self._q.put(None)
        self._thread.join(timeout=timeout)
        if self._error is not None:
            self._log(f"[client] streamed playback failed: {self._error}")


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
                   mode: str | None = None, on_audio=None, on_meta=None) -> dict:
        """POST one utterance; parse the server's NDJSON stream.

        Line kinds, each handed to its callback the moment it arrives:
          part="filler"     early transcript (+ optional filler audio)
          part="turn_meta"  the whole turn minus audio, sent before the first
                            audio chunk so the UI updates while Wini speaks
          part="audio"      one PCM chunk of the answer, in `seq` order
        The last line is the full turn result and is returned.

        `mode` (EXPLAIN/PRACTICE/TEST from the touch UI) rides on the
        `X-Wini-Mode` header — additive; the brain records it (Part 12 §5.9).
        None ⇒ no header ⇒ byte-identical to today (server defaults to EXPLAIN).
        """
        headers = {"Content-Type": "application/octet-stream",
                   "X-Sample-Rate": str(rate),
                   # No compression layer between us and the NDJSON lines: a
                   # decompressor is another place the stream can buffer.
                   "Accept-Encoding": "identity"}
        if mode:
            headers["X-Wini-Mode"] = mode
        r = requests.post(f"{self.base}/voice_turn", data=pcm, timeout=120,
                          stream=True, headers=headers)
        r.raise_for_status()
        result = None
        # chunk_size MUST be a small int, never None: urllib3 reads `None` as
        # "read to EOF", so iter_lines(chunk_size=None) buffers the ENTIRE
        # response and hands every line over at once — measured 2026-07-20, it
        # made the server's per-chunk streaming completely invisible to the
        # client (all lines landed together at 14.1 s). 512 B granularity against
        # ~15 KB audio lines costs nothing.
        for line in r.iter_lines(chunk_size=512):
            if not line:
                continue
            obj = json.loads(line)
            part = obj.get("part")
            if part == "filler":
                if on_filler is not None:
                    on_filler(obj)
            elif part == "audio":
                if on_audio is not None:
                    on_audio(obj)
            elif part == "turn_meta":
                if on_meta is not None:
                    on_meta(obj)
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

def apply_turn_ui(result: dict, sink) -> None:
    """Drive the display sink off a turn (or a streamed turn_meta part).

    A sink may expose `on_turn(result)` to drive richer UI off the WHOLE turn
    (mode/test/writeback aren't in the display item) — the LVGL ModeChannelSink
    uses it for screen/stage/progress/feedback. Called before show() so the
    screen is switched before the card lands on it.
    """
    on_turn = getattr(sink, "on_turn", None)
    if on_turn is not None:
        try:
            on_turn(result)
        except Exception as e:  # noqa: BLE001 — a UI cue must never cost a turn
            print(f"[display] on_turn failed: {e}")
    display = result.get("display") or []
    if display:
        sink.show(display[0])


def speak_result(result: dict, sink, mute: bool = False,
                 audio_manager=None, ttfa: "Ttfa | None" = None,
                 ui_applied: bool = False, audio_played: bool = False) -> None:
    """Display up FIRST, then speech, then display down — 'show while explaining'.

    A sink may expose `on_turn(result)` to drive richer UI off the WHOLE turn
    (mode/test/writeback aren't in the display item) — the LVGL ModeChannelSink
    uses it for screen/stage/progress/feedback. Called before show() so the screen
    is switched before the card lands on it.

    `mute` skips the speech (the UI pause button was pressed while this turn was
    in flight — Wini must not talk over the student's other conversation); the
    display still updates so nothing is lost.

    `audio_manager` (optional): if provided, ``set_speaking(True)`` is called
    before TTS playback and ``set_speaking(False)`` after, so the emotion
    engine knows to suppress touch sounds during speech.

    `ui_applied` / `audio_played`: set when the turn STREAMED (Part 13 Stage 1) —
    the UI was already driven off the turn_meta part and the audio was already
    spoken chunk by chunk, so this call only has to clear the display. Without
    `audio_played` the client would speak the whole answer a second time from
    the final line's back-compatible `audio_b64`."""
    if not ui_applied:
        apply_turn_ui(result, sink)
    try:
        if result.get("audio_b64") and not mute and not audio_played:
            if audio_manager is not None:
                audio_manager.set_speaking(True)
            try:
                if ttfa is not None:
                    ttfa.mark()
                play_pcm(base64.b64decode(result["audio_b64"]), int(result.get("audio_rate", 24000)))
            finally:
                if audio_manager is not None:
                    audio_manager.set_speaking(False)
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
                mode_state=None, audio_manager=None, log=print) -> str:
    """The listen → turn → speak loop, callable as a library (the ROS-less
    platform runs this on its ClientThread with an InProcSink + stop_event).

    `mode_state` (optional ModeState from the touch UI) is read fresh each turn
    and stamped on the POST as X-Wini-Mode — the child can switch modes between
    turns by tapping a different card.

    `audio_manager` (optional): passed through to ``speak_result`` so that
    TTS playback is bracketed with ``set_speaking(True/False)`` calls,
    letting the emotion engine suppress touch sounds during speech.

    Returns why it stopped: "session_ended" (farewell + exit_on_session_end)
    or "stopped" (stop_event set). KeyboardInterrupt propagates to the caller.
    """
    # Claim the speaker BEFORE the first mic open: on the single-PCM reSpeaker
    # Lite, opening playback after a capture churn is what silenced the voice.
    prime_output()
    ttfa = Ttfa()
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
            ttfa.arm()      # recording just ended — the child is now waiting
            early_seen = []

            def on_part(part: dict) -> None:
                early_seen.append(True)
                log(f"\nYou:  {part.get('transcript', '')}")
                if part.get("filler"):
                    log(f"Wini [{part.get('bank')}]: {part.get('filler')}")
                if part.get("audio_b64"):
                    if audio_manager is not None:
                        audio_manager.set_speaking(True)
                    try:
                        ttfa.mark()
                        play_pcm(base64.b64decode(part["audio_b64"]),
                                 int(part.get("audio_rate", 24000)))
                    finally:
                        if audio_manager is not None:
                            audio_manager.set_speaking(False)

            # Streamed answer audio (Part 13 Stage 1): chunks are pushed to a
            # background player so the HTTP reader never blocks on playback —
            # chunk N plays while N+1 is still arriving.
            player = AudioStreamPlayer(audio_manager=audio_manager, ttfa=ttfa,
                                       log=log)
            ui_applied = []

            def on_audio(part: dict) -> None:
                if paused is not None and paused.is_set():
                    return  # pause tapped mid-answer: stop feeding the speaker
                player.push(base64.b64decode(part["audio_b64"]),
                            int(part.get("audio_rate", 24000)),
                            seq=part.get("seq"))

            def on_meta(part: dict) -> None:
                # Display up BEFORE the first sample, preserving "show while
                # explaining" now that speech starts before the turn is complete.
                sink.thinking(False)
                apply_turn_ui(part, sink)
                ui_applied.append(True)
                log(f"Wini: {part.get('answer')}")

            # Thinking face while the brain works: from utterance sent until the
            # answer audio is back; the sink restores the pre-turn emotion after.
            sink.thinking(True)
            try:
                result = brain.voice_turn(
                    pcm, on_filler=on_part, on_audio=on_audio, on_meta=on_meta,
                    mode=(mode_state.mode if mode_state is not None else None))
            finally:
                sink.thinking(False)
                player.finish()
            transcript = result.get("transcript", "")
            if not transcript:
                continue  # STT heard nothing intelligible — re-listen silently
            if not early_seen:
                log(f"\nYou:  {transcript}")
            streamed = bool(result.get("audio_streamed")) and player.started
            if not streamed:
                log(f"Wini: {result.get('answer')}")
            speak_result(result, sink,
                         mute=(paused is not None and paused.is_set()),
                         audio_manager=audio_manager, ttfa=ttfa,
                         ui_applied=bool(ui_applied), audio_played=streamed)
            # Logged AFTER playback starts so ttfa_ms is populated. ttfa_ms is the
            # child-facing number; the latency_ms breakdown must account for it.
            _cap = getattr(record_utterance, "last", {})
            log(f"[client] turn {time.time() - t0:.1f}s  ttfa={ttfa.ms}ms "
                f"capture={_cap} "
                f"latency={result.get('latency_ms')} "
                f"chunks={player.chunks_played} "
                f"action={result.get('action')} display={bool(result.get('display'))}")
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


def _start_touch_audio(gpio_pin: int = 22, chip: int = 4, log=print):
    """Best-effort: build the emotion-based touch-audio engine and start the
    GPIO touch reader (direct button on ``gpio_pin``, Pi 5 ``gpiochip{chip}``).

    Returns ``(audio_manager, shutdown_fn)`` when the reader connects, so the
    caller can hand ``audio_manager`` to ``run_session`` (TTS suppression) and
    call ``shutdown_fn()`` on exit.  Returns ``(None, None)`` on any failure
    (no lgpio, pin unavailable, laptop test rig) — everything else still works.

    A background ticker drives mood decay + idle ambience, since the client's
    main thread blocks inside ``run_session`` (the supervisor ticks it in its
    own loop instead).
    """
    try:
        from .sound_bank import SoundBank
        from .audio_manager import AudioManager
        from wini_platform.touch_gestures import TouchGestureRecognizer
        from wini_platform.emotion_engine import EmotionEngine
        from wini_platform.touch.gpio_touch import GpioTouchReader
    except Exception as e:  # noqa: BLE001
        log(f"[client] touch-audio engine unavailable ({e}); continuing without it")
        return None, None

    try:
        bank = SoundBank()
        am = AudioManager(play_fn=play_pcm, sound_bank=bank, log=log)
        engine = EmotionEngine(am, log=log)
        rec = TouchGestureRecognizer(
            on_single_tap=engine.on_single_tap,
            on_double_tap=engine.on_double_tap,
            on_hold_start=engine.on_hold_start,
            on_hold_end=engine.on_hold_end,
            on_pat_sequence=engine.on_pat_sequence,
            log=log,
        )
        reader = GpioTouchReader(gpio_pin=gpio_pin, chip=chip,
                                 on_touch=rec.on_level, log=log)
        reader.start()
    except Exception as e:  # noqa: BLE001
        log(f"[client] touch-audio engine init failed ({e}); continuing without it")
        return None, None

    if not reader.connected:
        log(f"[client] GPIO{gpio_pin} touch not available; emotion sounds disabled")
        reader.shutdown()
        am.shutdown()
        return None, None

    stop = threading.Event()

    def _ticker() -> None:
        while not stop.wait(0.2):
            try:
                engine.tick(0.2)
            except Exception:  # noqa: BLE001 — never let the ticker die on one bad tick
                pass

    threading.Thread(target=_ticker, name="emotion-tick", daemon=True).start()

    def _shutdown() -> None:
        stop.set()
        reader.shutdown()
        am.shutdown()

    log(f"[client] touch-audio engine live on GPIO{gpio_pin} (gpiochip{chip})")
    return am, _shutdown


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
    ap.add_argument("--touch-gpio", type=int,
                    default=int(os.getenv("WINI_TOUCH_GPIO", "22")),
                    help="BCM GPIO pin for the emotion-touch button (default 22). "
                         "Best-effort: no-ops if lgpio/the pin is unavailable.")
    ap.add_argument("--touch-chip", type=int,
                    default=int(os.getenv("WINI_TOUCH_CHIP", "4")),
                    help="gpiochip number for the touch pin (Pi 5 = 4).")
    ap.add_argument("--no-touch-audio", action="store_true",
                    help="disable the emotion-based touch-audio engine entirely.")
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
    if channel is not None:
        # Releases the UI's splash. Sticky: the launcher holds wini_ui back until
        # the brain is warm, so the UI usually connects AFTER this point.
        channel.set_sticky({"cmd": "ready"})

    if args.once_text:
        result = brain.text_turn(args.once_text, speak=True,
                                 mode=(mode_state.mode if mode_state else None))
        print(f"[client] action={result.get('action')} concept={result.get('concept')} "
              f"display={bool(result.get('display'))} latency={result.get('latency_ms')}")
        print(f"Wini: {result.get('answer')}")
        speak_result(result, sink)
        return

    # Emotion-based touch-audio engine: a GPIO button (default GPIO22) drives
    # tap/hold/pat gestures → synthesized emotion sounds. audio_manager is handed
    # to run_session so touch sounds are suppressed while TTS speaks. Best-effort:
    # on the laptop test rig (no lgpio) it no-ops and the rest of the client runs.
    audio_manager, touch_shutdown = (None, None)
    if not args.no_touch_audio:
        audio_manager, touch_shutdown = _start_touch_audio(
            gpio_pin=args.touch_gpio, chip=args.touch_chip)

    exit_on_end = (args.on_session_end == "exit")
    # Sleep/wake cycle: after a "bye" (session_ended) with on-session-end=exit we
    # release the mic and send the UI back to the idle picker, then block on the
    # next card tap. The device is "asleep" — not recording — until woken.
    try:
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
                                     mode_state=mode_state,
                                     audio_manager=audio_manager)
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
    finally:
        if touch_shutdown is not None:
            touch_shutdown()


if __name__ == "__main__":
    main()
