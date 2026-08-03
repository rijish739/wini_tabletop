"""Silero neural VAD for the thin client — the RPi-side equivalent of the ESP32-P4
ESP-SR AFE's neural VAD (2026-07-25).

Why this exists: the RMS/floor-relative endpointer in client.py gates on ENERGY, so
any loud non-speech (a TV, a fan, clatter, a chair scrape) trips it and soft speech
slips under the gate. Silero VAD gates on "is this speech" acoustically — a small
(~2 MB) neural model that runs real-time on the Pi 5 CPU via onnxruntime and rejects
non-speech that energy gating cannot.

Contract match: ``record_utterance_silero`` has the SAME signature and return type as
client.record_utterance (int16 mono PCM bytes, or None), so it is a drop-in. The RMS
path stays as the fallback when onnxruntime / the model is unavailable, or the rate is
not 16 kHz (Silero's 16 kHz mode wants exactly 512-sample frames).

The final device (ESP32-P4) will do this in C with ESP-SR's WakeNet + AFE, not this
model — but the onset/offset behaviour this produces is the reference target.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

MODEL_PATH = Path(__file__).resolve().parent / "silero_vad.onnx"

# Silero 16 kHz mode consumes exactly 512 samples (32 ms) per inference.
SILERO_FRAME = 512
SILERO_RATE = 16000

# Speech-probability gates. Hysteresis, like the RMS path: latch speech at >= START,
# only treat it as ended when it drops below STOP (Silero's own VADIterator uses
# threshold / threshold-0.15 the same way). Env-tunable so they can be dialled in
# against the real device mic without a code push.
SPEECH_START = float(os.getenv("WINI_VAD_START", "0.5"))
SPEECH_STOP = float(os.getenv("WINI_VAD_STOP", "0.35"))
MIN_SPEECH_MS = 120          # ignore sub-word blips (matches the RMS path)
# Diagnostics: WINI_VAD_DEBUG=1 prints the per-second probability trajectory so the
# gates can be set from measured numbers (mirrors how the RMS floor was tuned).
DEBUG = os.getenv("WINI_VAD_DEBUG", "0").strip().lower() not in ("0", "false", "no", "")


class SileroVad:
    """Stateful per-frame speech-probability scorer. One instance per recording;
    the LSTM state is carried frame to frame and reset between utterances."""

    # Silero v5 prepends 64 samples of the PREVIOUS frame as context (16 kHz), so
    # the model actually sees 64 + 512 = 576 samples per call. Feeding a bare 512
    # frame makes every score ~0 — the model never builds context (the v5 gotcha).
    CONTEXT = 64

    def __init__(self, model_path: Path = MODEL_PATH):
        import onnxruntime as ort  # lazy: the RMS fallback needs no onnx

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1     # one utterance at a time; keep it light
        self._sess = ort.InferenceSession(
            str(model_path), sess_options=opts, providers=["CPUExecutionProvider"])
        self._sr = np.array(SILERO_RATE, dtype=np.int64)
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self.CONTEXT), dtype=np.float32)

    def prob(self, frame_i16: np.ndarray) -> float:
        """Speech probability [0,1] for one 512-sample int16 frame."""
        x = (frame_i16.astype(np.float32) / 32768.0).reshape(1, -1)
        x = np.concatenate([self._context, x], axis=1).astype(np.float32)  # 64 + 512
        out, self._state = self._sess.run(
            None, {"input": x, "state": self._state, "sr": self._sr})
        self._context = x[:, -self.CONTEXT:]      # carry the tail into the next frame
        return float(out[0][0])


def available() -> bool:
    """True iff Silero can run here (onnxruntime import + model file present)."""
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return MODEL_PATH.exists()


def record_utterance_silero(rate: int = SILERO_RATE, threshold: float | None = None,
                            silence_ms: int = 700, hard_cap_s: float = 15.0,
                            preroll_ms: int = 400, wait_for_speech_s: float | None = None,
                            stop_event=None) -> "bytes | None":
    """Capture one spoken utterance using Silero VAD. Same contract as
    client.record_utterance: returns int16 mono PCM bytes, or None on
    timeout/stop. ``threshold`` (an RMS escape hatch) is accepted for signature
    compatibility and only honoured if it looks like a probability (0<t<1)."""
    import sounddevice as sd

    if rate != SILERO_RATE:
        # Silero 16 kHz mode needs 16 kHz; let the caller fall back to RMS.
        raise ValueError(f"Silero VAD path requires {SILERO_RATE} Hz, got {rate}")

    start_p = threshold if (threshold is not None and 0.0 < threshold < 1.0) else SPEECH_START
    stop_p = min(SPEECH_STOP, start_p - 0.1)

    block = SILERO_FRAME
    block_ms = block * 1000 // rate            # 32 ms
    silence_blocks = max(1, silence_ms // block_ms)
    preroll_blocks = max(1, preroll_ms // block_ms)
    min_speech_blocks = max(1, MIN_SPEECH_MS // block_ms)
    wait_blocks = None if wait_for_speech_s is None else int(wait_for_speech_s * 1000 / block_ms)
    deadline_blocks = int(hard_cap_s * 1000 / block_ms)

    vad = SileroVad()
    ring: list[np.ndarray] = []          # pre-roll: recent frames before onset
    chunks: list[np.ndarray] = []
    pending = 0                          # consecutive speech frames not yet latched
    speaking = False
    silent = waited = frames = 0
    pmax = 0.0
    recent: list[float] = []             # probs since the last per-second log line
    log_every = max(1, 1000 // block_ms)  # ~1 s
    reason = "cap"

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
            if flat.shape[0] != block:      # short read at close — pad, score, done
                flat = np.pad(flat, (0, block - flat.shape[0]))
            p = vad.prob(flat)
            frames += 1
            pmax = max(pmax, p)
            recent.append(p)
            if DEBUG and frames % log_every == 0:
                r = np.array(recent); recent = []
                print(f"[vad] {'REC ' if speaking else 'wait'} t={frames * block_ms / 1000:.1f}s "
                      f"p(min/mean/max)={r.min():.2f}/{r.mean():.2f}/{r.max():.2f} "
                      f"silent={silent}/{silence_blocks}", flush=True)
            if not speaking:
                ring.append(flat)
                ring = ring[-preroll_blocks:]
                if p >= start_p:
                    pending += 1
                    if pending >= min_speech_blocks:
                        speaking = True
                        chunks.extend(ring)      # prepend the clipped first word
                        ring.clear()
                        pending = 0
                        silent = 0
                        if DEBUG:
                            print(f"[vad] speech latched (p={p:.2f})", flush=True)
                else:
                    pending = 0
                    waited += 1
                    if wait_blocks is not None and waited >= wait_blocks:
                        return None
            else:
                chunks.append(flat)
                if p < stop_p:
                    silent += 1
                    if silent >= silence_blocks:
                        reason = "silence"
                        break
                else:
                    silent = 0
                if len(chunks) >= deadline_blocks:
                    reason = "cap"
                    break

    if not chunks:
        return None
    speech_ms = len(chunks) * block_ms
    # Always print a one-line summary (like the RMS path): reason distinguishes a
    # clean endpoint from a runaway to the 15 s cap; pmax says whether speech was
    # even detected. This is what to read from client.log to tune the gates.
    print(f"[vad] end reason={reason} speech={speech_ms}ms pmax={pmax:.2f} "
          f"(start={start_p:.2f} stop={stop_p:.2f})", flush=True)
    return np.concatenate(chunks).astype(np.int16).tobytes()
