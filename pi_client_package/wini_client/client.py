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
import uuid
from pathlib import Path

import numpy as np
import requests

from .display_sinks import make_sink

RATE = 16000


# ---------------------------------------------------------------------------
# platform seam 1: microphone (RMS auto-endpoint, ~40 lines, no model)
# ---------------------------------------------------------------------------

# ── VAD tuning (Part 13 follow-up, 2026-07-23) ─────────────────────────────
#
# The old endpointer compared RMS against ONE fixed threshold (0.018) for both
# starting and stopping. On the Pi that is above the room's noise floor for
# starting but BELOW it for stopping, so the "is it quiet again?" test never
# passed: every measured turn on the device ended with reason="hard_cap",
# capture_ms=15000, hangover_ms=0 — the child spoke for 3 s and then waited 12 s
# in silence, and STT then paid ~3.5 s to transcribe 15 s of mostly nothing.
#
# The replacement tracks the actual noise floor and uses hysteresis: a loud
# START gate keeps room noise from triggering a turn, a lower STOP gate lets a
# sentence trail off without re-arming on the room tone between words.
# Measured on winipi5's reSpeaker Lite, 2026-07-23 (tools/mic_floor.py and
# tools/mic_speech_level.py, both checked in so this is re-derivable):
#     idle floor   p50 0.0239, max 0.0303   <- the capture chain's OWN noise
#     speech       p50 0.0763, p90 0.2487, peaks 0.43
# The floor sits ABOVE the old fixed 0.018 gate — 0% of idle blocks fell below
# it — which is the whole bug: "quiet" was unreachable, so no turn could ever
# end and every one ran to the 15 s cap.
VAD_ABS_FLOOR = 0.006      # never treat anything below this as speech
# Both gates are PURELY floor-relative, with no absolute ceiling. An earlier
# revision capped the start gate at 0.045 so a loud room could not make Wini
# deaf — and measuring a room at floor 0.050 showed why that is wrong: the cap
# put both gates BELOW the room, so the room read as continuous speech and the
# turn ran to the 15 s hard cap. That is the original bug, reintroduced by the
# safeguard. A gate under the noise floor is never the safer choice.
#
# At this device's 0.024 floor that puts stop at 0.041 and start at 0.055,
# against measured speech of p50 0.076 and onsets of 0.16-0.29.
VAD_START_MULT = 2.3       # start gate = floor x this
VAD_STOP_MULT = 1.7        # stop gate  = floor x this; must clear the floor's
                           # own peaks (~1.3x its median) or turns never end
VAD_STOP_RATIO = 0.80      # hard invariant: stop gate stays below the start gate
VAD_NOISE_ALPHA = 0.08     # EMA rate once running, updated on non-speech only
VAD_MIN_SPEECH_MS = 120    # ignore clicks/thumps shorter than this
VAD_CALIBRATE_MS = 300     # opening blocks: measure the floor, never latch speech

# The learned floor persists across calls — the room does not change between
# turns — but it is only a SEED: every recording re-measures the floor over its
# calibration window (see below). Seeding alone is not enough, because a seed
# below the true floor produces a stop gate below the room, which is exactly the
# never-endpoints failure this replaced.
_vad_noise = 0.020


def record_utterance(rate: int = RATE, threshold: float | None = None,
                     silence_ms: int = 700,
                     hard_cap_s: float = 15.0, preroll_ms: int = 400,
                     wait_for_speech_s: float | None = None,
                     stop_event=None) -> bytes | None:
    """Block until one spoken utterance is captured; return int16 mono PCM bytes.

    Endpointing is adaptive by default (see the VAD_* constants). Passing
    `threshold` pins the START gate to that fixed RMS instead — an escape hatch
    (--rms-threshold) for a rig where the adaptive floor misbehaves. The STOP
    gate stays noise-relative either way: a fixed stop gate is precisely the bug
    this replaced.

    Returns None if wait_for_speech_s elapses with no speech (lets the main loop
    breathe — check the server, handle Ctrl-C — instead of blocking forever), or
    if stop_event is set (checked between blocks — PortAudio blocking reads
    ignore SIGTERM, so an in-process host must stop the loop this way).
    """
    global _vad_noise
    import sounddevice as sd

    # 30 ms (was 50): the hangover and the stop-event check are both quantised
    # to this, so a smaller block ends the turn sooner and costs nothing.
    block_ms = 30
    block = int(rate * block_ms / 1000)
    silence_blocks = max(1, silence_ms // block_ms)
    preroll_blocks = max(1, preroll_ms // block_ms)
    min_speech_blocks = max(1, VAD_MIN_SPEECH_MS // block_ms)
    calib_blocks = max(1, VAD_CALIBRATE_MS // block_ms)
    wait_blocks = None if wait_for_speech_s is None else int(wait_for_speech_s * 1000 / block_ms)
    ring: list[np.ndarray] = []
    chunks: list[np.ndarray] = []
    pending: list[np.ndarray] = []      # candidate speech, not yet latched
    calib: list[float] = []             # opening blocks, used to measure the floor
    speaking = False
    silent = waited = seen = 0
    reason = "silence"
    noise = _vad_noise
    deadline_blocks = int(hard_cap_s * 1000 / block_ms)

    def gates(n: float) -> "tuple[float, float]":
        stop = max(n * VAD_STOP_MULT, VAD_ABS_FLOOR * 0.7)
        start = (threshold if threshold
                 else max(n * VAD_START_MULT, VAD_ABS_FLOOR))
        # Hysteresis is the point: a stop gate at or above the start gate would
        # end the turn during the speech that started it. With an explicit
        # --rms-threshold the START is pinned, so the STOP is what gives way.
        start = max(start, stop / VAD_STOP_RATIO) if not threshold else start
        return start, min(stop, start * VAD_STOP_RATIO)

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
            seen += 1
            # The opening blocks are ALWAYS treated as room tone: they cover the
            # mic's turn-on transient (loud enough to latch as speech) and they
            # are where the floor is MEASURED. A 25th percentile, not a mean:
            # it survives both that transient and a child who starts talking
            # before the window closes, either of which would otherwise inflate
            # the floor and raise the gates out of reach.
            if seen <= calib_blocks:
                calib.append(rms)
                if seen == calib_blocks:
                    noise = max(float(np.percentile(calib, 25)), 1e-4)
            start_gate, stop_gate = gates(noise)
            if not speaking:
                ring.append(flat)
                ring = ring[-preroll_blocks:]
                if rms >= start_gate and seen > calib_blocks:
                    pending.append(flat)
                    if len(pending) >= min_speech_blocks:
                        speaking = True
                        chunks.extend(ring)      # pre-roll: the clipped first word
                        ring.clear()
                        pending.clear()
                        silent = 0
                else:
                    pending.clear()
                    if seen > calib_blocks:   # don't fight the measured floor
                        noise = ((1 - VAD_NOISE_ALPHA) * noise
                                 + VAD_NOISE_ALPHA * rms)
                    waited += 1
                    if wait_blocks is not None and waited >= wait_blocks:
                        _vad_noise = noise
                        return None
            else:
                chunks.append(flat)
                # Hysteresis: stop_gate < start_gate, so a trailing-off word still
                # counts as speech but the room tone between sentences does not.
                if rms < stop_gate:
                    silent += 1
                    if silent >= silence_blocks:
                        break
                else:
                    silent = 0
                if len(chunks) >= deadline_blocks:
                    reason = "hard_cap"
                    break
    _vad_noise = noise
    if not chunks:
        return None
    pcm = np.concatenate(chunks)
    # Part 13 diagnostics: the endpoint window is the ONE interval neither
    # ttfa_ms (armed AFTER this returns) nor the server's latency_ms can see.
    # `speech_ms` is what the child actually said; `hangover_ms` is the silence
    # tail we spend confirming they stopped; `reason` distinguishes a clean
    # endpoint from a runaway that ran to the 15 s cap. `noise`/`start_gate`
    # are what the adaptive gate settled on — a hard_cap with a start_gate at
    # the ceiling means the room is too loud, not that the code regressed.
    start_gate, _ = gates(noise)
    record_utterance.last = {
        "capture_ms": int(len(pcm) / rate * 1000),
        "speech_ms": int(max(0, len(chunks) - silence_blocks) * block_ms),
        "hangover_ms": int(min(silent, silence_blocks) * block_ms),
        "reason": reason,
        "noise": round(noise, 4),
        "gate": round(start_gate, 4),
    }
    return pcm.tobytes()


def prime_input(rate: int = RATE) -> bool:
    """Open (and immediately close) the capture stream once at startup.

    The FIRST InputStream open on the Pi negotiates the reSpeaker's USB PCM
    through PipeWire and takes noticeably longer than every later one — paid, as
    it was, on the child's first utterance, inside the window where they are
    already talking. Doing it during warmup moves that cost behind the splash.
    Best-effort: a failure here just defers to the first real record_utterance."""
    import sounddevice as sd

    block = int(rate * 0.03)
    for kw in ({"device": "pulse"}, {}):
        try:
            with sd.InputStream(samplerate=rate, channels=1, dtype="int16",
                                blocksize=block, **kw) as s:
                s.read(block)          # actually pull a buffer: opening is lazy
            return True
        except (ValueError, sd.PortAudioError):
            continue
    print("[client] input prime deferred (no capture device yet)")
    return False


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


_scene_nonce = 0


class _SceneVisual:
    """VISUAL-ONLY tier-0 scene (SCENE_VISUALS_GUIDE §4). Renders a scene's
    accumulated beat frames and grows the panel figure in step with the brain
    answer's audio chunks — it plays NO audio of its own (the reSpeaker Lite has a
    single playback substream; a second TTS consumer starved the answer, seen live
    2026-07-26). The brain's real answer stays the sound; this only draws.

    Frames render on a background thread so the HTTP reader never blocks; each beat
    gets a unique /tmp path (per-instance nonce) so the LVGL figure card never
    reloads a stale cached image."""

    def __init__(self, scene: dict, chan, theme: str, log=print,
                 tmpdir: str | None = None):
        global _scene_nonce
        _scene_nonce += 1
        self.scene = scene
        self.chan = chan
        self.theme = theme
        self.log = log
        self.n = len(scene.get("beats", []))
        tmp = tmpdir or os.environ.get("TMPDIR", "/tmp")
        self.paths = [os.path.join(tmp, f"wini_scene_{_scene_nonce}_{i}.png")
                      for i in range(self.n)]
        self.ready = [False] * self.n
        self.shown = -1
        self._lock = threading.Lock()
        self._stop = threading.Event()
        threading.Thread(target=self._render_all, name="scene-render",
                         daemon=True).start()

    def _render_one(self, i: int) -> bool:
        try:
            from figures.scene_render import render_beat_frame
            render_beat_frame(self.scene, i, self.theme, scale=2.0,
                              out_path=self.paths[i])
            with self._lock:
                self.ready[i] = True
            return True
        except Exception as e:  # noqa: BLE001 — a bad frame must never cost the turn
            self.log(f"[scene] render beat {i} failed: {e}")
            return False

    def _render_all(self) -> None:
        for i in range(self.n):
            self._render_one(i)

    def _send(self, i: int) -> None:
        try:
            self.chan.send({"cmd": "figure", "path": self.paths[i]})
            self.shown = i
        except Exception as e:  # noqa: BLE001
            self.log(f"[scene] figure send failed: {e}")

    def show_first(self) -> None:
        """Put beat 0's frame up right away (render it synchronously if the
        background thread hasn't reached it yet) so the picture is on screen the
        moment the answer starts, not a beat later."""
        if self.n == 0:
            return
        if not self.ready[0]:
            self._render_one(0)
        if self.ready[0] and self.shown < 0:
            self._send(0)

    def start_paced(self) -> None:
        """Reveal the beats on a WALL-CLOCK schedule (the scene's own authored
        ``anim_ms`` + ``hold_ms`` per beat), not per audio chunk.

        The answer streams ~one small PCM chunk every quarter-second (~78 for a
        20s answer) but a scene has only 4-8 beats, so keying the reveal to the
        chunk index saturated ``min(chunk_idx, n-1)`` to the LAST beat within the
        first second — the child saw the finished figure instantly, never the
        build-up (seen live 2026-07-26). Time-pacing decouples the two: beat 0 now,
        then one beat per authored dwell, so the steps draw on as Wini talks."""
        self.show_first()
        if self.n <= 1:
            return
        threading.Thread(target=self._pace_loop, name="scene-pace",
                         daemon=True).start()

    def _pace_loop(self) -> None:
        for i in range(1, self.n):
            prev = self.scene["beats"][i - 1]
            dwell = (prev.get("anim_ms", 600) + prev.get("hold_ms", 800)) / 1000.0
            if self._stop.wait(dwell):
                return          # finish() (answer ended) — snap to full elsewhere
            self._show_when_ready(i)

    def _show_when_ready(self, i: int, spins: int = 150) -> None:
        """Send beat ``i`` once its frame exists, waiting briefly for the render
        thread (rendering a beat is 32-36ms; a fresh miss renders it inline)."""
        for _ in range(spins):
            with self._lock:
                if self.ready[i]:
                    break
            if self._stop.wait(0.02):
                return
        else:
            self._render_one(i)
        with self._lock:
            if i <= self.shown:
                return
        self._send(i)

    def finish(self) -> None:
        """Guarantee the COMPLETE final frame is on screen when the answer ends
        (a short answer may not have paced through every beat)."""
        self._stop.set()
        if self.n == 0:
            return
        last = self.n - 1
        if not self.ready[last]:
            self._render_one(last)
        if self.ready[last] and self.shown != last:
            self._send(last)


# ---------------------------------------------------------------------------
# brain service contract (platform seam 3 is the display sink; 4 is the trigger)
# ---------------------------------------------------------------------------

def _cloud_run_auth(base: str):
    """Return a zero-arg callable giving an `Authorization` header dict for a
    private Cloud Run brain, or None when no auth is needed (Part 15).

    Local brains (localhost / 127.0.0.1 / plain http) need no auth — the callable
    is None and every request is byte-identical to the on-Pi setup. For a remote
    https run.app endpoint we mint a Google-signed **ID token** whose audience is
    the service URL, from the device service-account key at $WINI_SA_KEY. The token
    is cached inside the credentials object and refreshed only when expired."""
    if base.startswith("http://") or "127.0.0.1" in base or "localhost" in base:
        return None
    key_path = os.getenv("WINI_SA_KEY")
    if not key_path:
        print("[client] remote brain but WINI_SA_KEY is unset — calls will be "
              "unauthenticated (expect 401/403).")
        return None
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as _GRequest
    except ImportError:
        print("[client] google-auth not installed; cannot authenticate to the "
              "cloud brain. `pip install google-auth`.")
        return None
    creds = service_account.IDTokenCredentials.from_service_account_file(
        key_path, target_audience=base)
    _req = _GRequest()

    def _header():
        if not creds.valid:
            creds.refresh(_req)
        return {"Authorization": f"Bearer {creds.token}"}

    return _header


class BrainClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self._auth = _cloud_run_auth(self.base)

    def _headers(self, extra: dict | None = None) -> dict:
        h = dict(extra or {})
        if self._auth is not None:
            h.update(self._auth())
        # Part 15: app shared-secret for a public Cloud Run brain. Sent on every
        # request; the server rejects a mismatch with 401 before any billed work.
        api_key = os.getenv("WINI_API_KEY", "").strip()
        if api_key:
            h["X-Wini-Key"] = api_key
        return h

    def wait_ready(self, timeout_s: float = 300.0) -> dict:
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            try:
                h = requests.get(f"{self.base}/health", timeout=5,
                                 headers=self._headers()).json()
                if h.get("ready"):
                    return h
                if h.get("error"):
                    raise RuntimeError(f"brain failed to load: {h['error']}")
            except requests.RequestException:
                pass
            time.sleep(2)
        raise TimeoutError(f"brain at {self.base} not ready after {timeout_s:.0f}s")

    def voice_turn(self, pcm: bytes, rate: int = RATE, on_filler=None,
                   mode: str | None = None, on_audio=None, on_meta=None,
                   turn_id: str | None = None) -> dict:
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
        headers = self._headers({"Content-Type": "application/octet-stream",
                   "X-Sample-Rate": str(rate),
                   "X-Wini-Turn-Id": turn_id or f"turn_{uuid.uuid4().hex}",
                   # No compression layer between us and the NDJSON lines: a
                   # decompressor is another place the stream can buffer.
                   "Accept-Encoding": "identity"})
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
                  mode: str | None = None, turn_id: str | None = None) -> dict:
        payload = {"text": text, "speak": speak,
                   "turn_id": turn_id or f"turn_{uuid.uuid4().hex}"}
        if mode:
            payload["mode"] = mode
        r = requests.post(f"{self.base}/turn", json=payload, timeout=120,
                          headers=self._headers())
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


def _select_recorder(vad: str, log=print):
    """Pick the utterance recorder. 'silero' = neural VAD (rejects non-speech energy
    the RMS gate falsely triggers on; the RPi stand-in for the ESP32-P4 ESP-SR AFE).
    'rms' = the energy/floor-relative fallback. 'auto' = Silero if onnxruntime + the
    model are present, else RMS. Same signature/return either way (drop-in)."""
    want = (vad or "auto").lower()
    if want != "rms":
        note = "unavailable"
        try:
            from wini_client import vad_silero
            if vad_silero.available():
                log("[client] VAD: Silero neural (rejects non-speech energy)")
                return vad_silero.record_utterance_silero
            note = "onnxruntime or silero_vad.onnx missing"
        except Exception as e:  # noqa: BLE001
            note = str(e)
        log(f"[client] VAD: Silero {note} — falling back to RMS energy")
    else:
        log("[client] VAD: RMS energy (floor-relative)")
    return record_utterance


def _fmt_diag(d: dict) -> list[str]:
    """Format the brain's per-turn `diagnostics` block into a few readable terminal
    lines: the pedagogy decision, the cognitive-signal vector, and learner-state flags.
    Returns [] when there is nothing to show (a non-learning turn carries no cognitive
    update)."""
    if not d:
        return []
    cog = d.get("cognitive") or {}
    lines = []
    why = f" ({d['why']})" if d.get("why") else ""
    mastery = d.get("mastery")
    mastery_s = f" mastery={mastery:.2f}" if isinstance(mastery, (int, float)) else ""
    lines.append(f"[diag] action={d.get('action')}{why}  need={d.get('need')}  "
                 f"mode={d.get('mode')}  concept={d.get('concept')}{mastery_s}")
    if cog:
        # show the cognitive vector compactly, biggest signals first
        order = ("cognitive_load", "frustration_risk", "confusion", "curiosity",
                 "engagement", "confidence", "boredom")
        parts = [f"{k.replace('_risk','').replace('cognitive_','')}={cog[k]:.2f}"
                 for k in order if k in cog]
        parts += [f"{k}={v:.2f}" for k, v in cog.items() if k not in order]
        lines.append("       cognitive: " + "  ".join(parts))
    vis = d.get("visual") or {}
    extras = []
    if d.get("signals"):
        extras.append(f"signals={d['signals']}")
    if vis.get("type"):
        extras.append(f"visual={vis.get('type')}(earned={vis.get('earned')})")
    if d.get("pending_check"):
        extras.append(f"pending_check={d['pending_check']}")
    if d.get("pending_hope"):
        extras.append(f"pending_hope={d['pending_hope']}")
    if d.get("writeback"):
        extras.append(f"graded={d['writeback']}")
    if extras:
        lines.append("       " + "  ".join(extras))
    return lines


def run_session(brain: BrainClient, sink, *, trigger: str = "vad",
                rms_threshold: float | None = None, silence_ms: int = 700,
                vad: str = "auto",
                exit_on_session_end: bool = False, stop_event=None,
                mode_state=None, audio_manager=None, log=print,
                scenes: bool = True, scene_theme: str = "light",
                store_dir=None, diag: bool = False) -> str:
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
    # ...then pay the capture-open cost here rather than inside the child's
    # first sentence. Order matters — playback first, per the comment above.
    prime_input()
    ttfa = Ttfa()
    paused = getattr(mode_state, "paused", None) if mode_state is not None else None
    rec_stop = _StopOrPause(stop_event, paused) if paused is not None else stop_event
    record_fn = _select_recorder(vad, log)   # Silero neural VAD, or RMS fallback

    # Tier-0 authored scenes (SCENE_VISUALS_GUIDE §4) — VISUAL-ONLY. On an EXPLAIN
    # turn whose resolved concept has an authored scene, the scene's frames become
    # the figure and GROW in step with the brain's spoken answer (one beat per
    # audio chunk). The brain's real answer stays the ONLY audio — the scene does
    # NOT speak. That is deliberate: the reSpeaker Lite has a single playback
    # substream, so a second TTS consumer (the old scene-narration mode) fought the
    # answer for the device and both went silent ([PaErrorCode -9985], seen live
    # 2026-07-26). Keeping the answer as the audio also means the child hears a real
    # answer to THEIR question, not a canned worked example.
    #
    # Only possible on the LVGL panel — the sink exposes its mode channel as `_ch`;
    # other sinks (console/ROS/in-proc) have no `_ch`, so scenes stay off and the
    # crop path is unchanged.
    scene_chan = getattr(sink, "_ch", None)
    # Board Buddy (BOARD_BUDDY_INTEGRATION_PLAN.md §3.2): when the brain ships a
    # `board_payload` on the visual directive and this device can render it, the richer
    # Board Buddy surface replaces the scene-PNG figure for that turn. Flag-gated (default
    # OFF) so existing devices are byte-identical until Board Buddy is provisioned + the
    # Wayland/touch co-existence is verified live (§6.1, Phase 3).
    board_sink = None
    if os.getenv("WINI_BOARD_BUDDY", "0").strip().lower() in ("1", "true", "yes", "on") \
            and scene_chan is not None:
        try:
            from wini_client.board_buddy_sink import BoardBuddySink
            board_sink = BoardBuddySink(chan=scene_chan, log=log)
            log("[client] Board Buddy rendering ENABLED (WINI_BOARD_BUDDY=1)")
        except Exception as e:  # noqa: BLE001 — never block the loop on the board sink
            log(f"[client] Board Buddy sink unavailable ({e}); scene-PNG path only")
            board_sink = None
    scene_lookup = None
    if scenes and scene_chan is not None:
        try:
            from wini_client.scene_player import (
                scene_for_concept as _scene_for_concept,
                load_scene_index as _load_scene_index)
            scene_lookup = _scene_for_concept
            n_scenes = len(_load_scene_index(store_dir))
            log(f"[client] tier-0 scene visuals ON ({n_scenes} authored) for EXPLAIN turns")
        except Exception as e:  # noqa: BLE001 — scenes are additive; never block the loop
            log(f"[client] tier-0 scenes unavailable ({e}); using crop path only")
            scene_lookup = None

    def _pick_scene(concept_id):
        """A tier-0 scene for this concept iff the child is in EXPLAIN mode — a
        scene is a teaching aid, never a graded reveal. Returns the scene or None."""
        if scene_lookup is None:
            return None
        m = str((mode_state.mode if mode_state is not None else None) or "EXPLAIN").upper()
        return scene_lookup(concept_id, store_dir) if m == "EXPLAIN" else None

    def _close_board():
        if board_sink is not None:
            board_sink.close()          # idempotent — tears the child down, restores card

    while True:
        if stop_event is not None and stop_event.is_set():
            _close_board()
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
            pcm = record_fn(threshold=rms_threshold,
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
            # Tier-0 scene VISUAL for this turn (or None). The scene's frames grow
            # the figure as the answer speaks; the brain's answer stays the audio.
            # `rl` records whether the Response Layer is driving this turn (the brain
            # rides "rl":true on the filler line); when it is, the authoritative visual
            # directive rides turn_meta and concept-default arming is suppressed.
            scene_ctx: dict = {"vis": None, "meta_seen": False, "rl": False,
                               "directive": None, "board": False}

            def _arm_scene(concept_id, graded: bool, scene=None) -> None:
                """Attach a visual scene for an EXPLAIN, non-graded turn (once).
                `scene` may be an INLINE spec — the brain's drawn-from-answer scene
                (response_layer.scene_author), which mirrors Wini's actual words —
                otherwise it is looked up by concept. A graded turn keeps the plain path."""
                if scene_ctx["vis"] is not None or graded or scene_chan is None:
                    return
                if scene is None:
                    scene = _pick_scene(concept_id)
                if scene is None or not scene.get("beats"):
                    return
                try:
                    scene_ctx["vis"] = _SceneVisual(scene, scene_chan, scene_theme,
                                                    log=log)
                    src = "drawn from answer" if scene.get("generated") else f"for {concept_id}"
                    log(f"[client] scene visual ({len(scene['beats'])} beats, {src}) "
                        f"— figure grows as Wini speaks")
                except Exception as e:  # noqa: BLE001 — never let a scene cost the turn
                    log(f"[client] scene visual init failed ({e}); crop path")

            def on_part(part: dict) -> None:
                early_seen.append(True)
                log(f"\nYou:  {part.get('transcript', '')}")
                # If the brain rides the resolved concept on this early line
                # (server change; cloud brain may not yet), arm the visual now so
                # the picture is up as the first words play. But when the Response
                # Layer is engaged ("rl":true) the EARNED visual decision rides
                # turn_meta — do not concept-default-arm here; wait for the directive.
                if part.get("rl"):
                    scene_ctx["rl"] = True
                else:
                    _arm_scene(part.get("concept"), graded=False)
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
                # The scene reveal is time-paced (start_paced), NOT chunk-paced:
                # audio chunks arrive ~4x/s but a scene has only 4-8 beats, so
                # chunk-keying saturated to the final beat within the first second.

            def on_meta(part: dict) -> None:
                # Display up BEFORE the first sample, preserving "show while
                # explaining" now that speech starts before the turn is complete.
                sink.thinking(False)
                scene_ctx["meta_seen"] = True
                # Arm the visual off the authoritative concept/mode (the cloud brain
                # reaches here, not on_part). Graded or non-EXPLAIN turns get no scene.
                vis_dir = part.get("visual")
                # Board Buddy: a board-capable device renders the brain's payload on the
                # native surface instead of arming a scene-PNG figure (§3.2). Open + hand
                # off; the child animates around the streamed audio, closed at turn end.
                if board_sink is not None and vis_dir and vis_dir.get("board_payload"):
                    scene_ctx["board"] = True
                    try:
                        board_sink.handle({"cmd": "board_open"})
                        board_sink.handle({"cmd": "board",
                                           "payload": vis_dir.get("board_payload"),
                                           "tmax": vis_dir.get("board_tmax", 0.0),
                                           "animated": vis_dir.get("board_animated"),
                                           "wait": False})   # don't block the audio thread
                        on_turn = getattr(sink, "on_turn", None)
                        if on_turn is not None:
                            on_turn(part)
                        ui_applied.append(True)
                        log(f"Wini: {part.get('answer')}")
                        return
                    except Exception as e:  # noqa: BLE001 — degrade to the scene/crop path
                        log(f"[client] board render failed ({e}); scene path")
                        scene_ctx["board"] = False
                if scene_ctx["rl"] or vis_dir is not None:
                    # Response Layer: arm a scene ONLY when the Visual Benefit Gate
                    # earned one (arm_scene). Otherwise the turn is speech-only, or the
                    # display path shows an EARNED crop — never a concept-default scene.
                    scene_ctx["directive"] = vis_dir
                    if vis_dir and vis_dir.get("arm_scene"):
                        _arm_scene(part.get("concept"), graded=False,
                                   scene=vis_dir.get("scene"))
                else:
                    _arm_scene(part.get("concept"), graded=bool(part.get("writeback")))
                vis = scene_ctx["vis"]
                if vis is not None:
                    # Switch to the explain screen + header + caption, but let the
                    # scene own the FIGURE (skip apply_turn_ui's crop show()). Send
                    # the scene's first frame right after so on_turn's figure-off
                    # never leaves the card blank.
                    on_turn = getattr(sink, "on_turn", None)
                    if on_turn is not None:
                        try:
                            on_turn(part)
                        except Exception as e:  # noqa: BLE001 — a UI cue never costs a turn
                            log(f"[display] on_turn failed: {e}")
                    vis.start_paced()
                else:
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
            vis = scene_ctx["vis"]
            # Non-streamed Response-Layer turn (on_meta never ran): honor the visual
            # directive off the final result so an EARNED scene still arms.
            rl_dir = result.get("visual")
            if vis is None and not scene_ctx["meta_seen"] and rl_dir \
                    and rl_dir.get("arm_scene"):
                _arm_scene(result.get("concept"), graded=False, scene=rl_dir.get("scene"))
                vis = scene_ctx["vis"]
            # Final authoritative gate (covers NON-streamed turns, where on_meta
            # never ran): a graded or non-EXPLAIN turn shows its normal display, not
            # a teaching scene. The answer audio is unaffected either way.
            if vis is not None and (bool(result.get("writeback"))
                    or str(result.get("mode") or "EXPLAIN").upper() != "EXPLAIN"):
                log("[client] tier-0 scene dropped (graded/non-EXPLAIN turn)")
                vis = scene_ctx["vis"] = None
            # A non-streamed scene turn never hit on_meta: set its screen now so the
            # scene figure has an explain screen to land on.
            if vis is not None and not scene_ctx["meta_seen"]:
                on_turn = getattr(sink, "on_turn", None)
                if on_turn is not None:
                    try:
                        on_turn(result)
                    except Exception as e:  # noqa: BLE001
                        log(f"[display] on_turn failed: {e}")
                vis.start_paced()
            # The answer is ALWAYS the audio (streamed already played; non-streamed
            # plays here from audio_b64). For a scene turn `ui_applied=True` keeps
            # speak_result from re-showing the T9 crop over our figure; clear() at
            # its end returns the status indicator to "waiting" so the child knows
            # it is their turn.
            speak_result(result, sink,
                         mute=(paused is not None and paused.is_set()),
                         audio_manager=audio_manager, ttfa=ttfa,
                         ui_applied=bool(ui_applied) or vis is not None,
                         audio_played=streamed)
            if vis is not None:
                vis.finish()   # leave the COMPLETE figure up for the child to study
            if board_sink is not None and scene_ctx.get("board"):
                # Answer audio is done by now (streamed player.finish() ran; non-streamed
                # played in speak_result). Tear the child down so the LVGL card is restored
                # for the next turn (§10.3). A future refinement may keep the interactive
                # scrubber up until the next turn begins.
                board_sink.close()
                scene_ctx["board"] = False
            # Logged AFTER playback starts so ttfa_ms is populated. ttfa_ms is the
            # child-facing number; the latency_ms breakdown must account for it.
            _cap = getattr(record_utterance, "last", {})
            log(f"[client] turn {time.time() - t0:.1f}s  ttfa={ttfa.ms}ms "
                f"capture={_cap} "
                f"latency={result.get('latency_ms')} "
                f"chunks={player.chunks_played} "
                f"action={result.get('action')} display={bool(result.get('display'))}")
            if diag:
                for _dl in _fmt_diag(result.get("diagnostics") or {}):
                    log(_dl)
            if result.get("session_ended"):
                if exit_on_session_end:
                    log("[client] session ended — going to sleep (hold chin to wake).")
                    return "session_ended"
                log("[client] session ended (farewell spoken) — back to idle listening.")
        except requests.RequestException as e:
            log(f"[client] server error ({e}); retrying in 3s")
            _close_board()
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
    ap.add_argument("--vad", choices=["auto", "silero", "rms"],
                    default=os.getenv("WINI_VAD", "auto"),
                    help="endpointer: 'silero' neural VAD (rejects non-speech "
                         "energy), 'rms' the energy fallback, 'auto' Silero if "
                         "available else RMS (default).")
    ap.add_argument("--rms-threshold", type=float, default=None,
                    help="pin the VAD start gate to a fixed RMS. Default: adapt "
                         "to the measured room noise floor (VAD_* in this file).")
    ap.add_argument("--silence-ms", type=int, default=700,
                    help="silence held after speech before the turn is sent. "
                         "Every ms here is added directly to the child's wait.")
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
    ap.add_argument("--no-scenes", action="store_true",
                    help="disable tier-0 authored scenes (SCENE_VISUALS_GUIDE §4); "
                         "EXPLAIN turns then always use the T9 similarity crops.")
    ap.add_argument("--scene-theme", choices=["light", "dark"],
                    default=os.getenv("WINI_SCENE_THEME", "light"),
                    help="light/dark theme for rendered scene frames (default light).")
    ap.add_argument("--diag", action="store_true",
                    default=os.getenv("WINI_DIAG", "").strip().lower()
                    in ("1", "true", "yes", "on"),
                    help="print the learner cognitive state + pedagogy decision each "
                         "turn (action/why, cognitive signals, mastery, pending check). "
                         "Also enabled by WINI_DIAG=1.")
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
    # Warm the audio devices HERE, not on entry to run_session: the launcher
    # holds the UI splash until the brain is ready, and run_session does not
    # start until the child has tapped a card — so priming there still charged
    # the first-open cost to their first sentence. Both calls are idempotent.
    prime_output()
    prime_input()
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
                                     silence_ms=args.silence_ms, vad=args.vad,
                                     exit_on_session_end=exit_on_end,
                                     mode_state=mode_state,
                                     audio_manager=audio_manager,
                                     scenes=not args.no_scenes,
                                     scene_theme=args.scene_theme,
                                     store_dir=Path(args.store), diag=args.diag)
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
