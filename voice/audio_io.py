"""Headset recording and playback helpers."""

from __future__ import annotations

import queue
import time
import wave
from pathlib import Path

import numpy as np


def write_wav(path: Path, pcm16: np.ndarray | bytes, rate: int = 16000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = pcm16.tobytes() if isinstance(pcm16, np.ndarray) else pcm16
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(data)
    return path


def wav_bytes(pcm: bytes, rate: int = 24000) -> bytes:
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def read_wav(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise ValueError("expected mono 16-bit WAV")
        return wf.readframes(wf.getnframes()), wf.getframerate()


def record_push_to_talk(out_path: Path, rate: int = 16000, device: int | str | None = None) -> Path:
    import sounddevice as sd

    print("Press Enter to start recording.")
    input()
    print("Recording... press Enter to stop.")
    q: queue.Queue[np.ndarray] = queue.Queue()

    def callback(indata, frames, time_info, status):  # noqa: ANN001
        if status:
            print(status)
        q.put(indata.copy())

    chunks: list[np.ndarray] = []
    with sd.InputStream(samplerate=rate, channels=1, dtype="int16", callback=callback, device=device):
        import threading

        stopper = threading.Event()

        def wait_stop() -> None:
            input()
            stopper.set()

        thread = threading.Thread(target=wait_stop, daemon=True)
        thread.start()
        while not stopper.is_set():
            try:
                chunks.append(q.get(timeout=0.1))
            except queue.Empty:
                pass
    if not chunks:
        raise RuntimeError("no audio captured")
    pcm = np.concatenate(chunks, axis=0).reshape(-1)
    return write_wav(out_path, pcm, rate=rate)


def record_auto_endpoint(
    out_path: Path,
    rate: int = 16000,
    threshold: float = 0.018,
    silence_ms: int = 800,
    hard_cap_s: float = 15.0,
    preroll_ms: int = 400,
) -> Path:
    import sounddevice as sd

    block_ms = 50
    block = int(rate * block_ms / 1000)
    silence_blocks = max(1, silence_ms // block_ms)
    preroll_blocks = max(1, preroll_ms // block_ms)
    max_blocks = int(hard_cap_s * 1000 / block_ms)
    ring: list[np.ndarray] = []
    chunks: list[np.ndarray] = []
    speaking = False
    silent = 0
    print("Listening... speak naturally.")
    with sd.InputStream(samplerate=rate, channels=1, dtype="int16", blocksize=block) as stream:
        for _ in range(max_blocks):
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
                chunks.append(flat)
                if rms < threshold:
                    silent += 1
                    if silent >= silence_blocks:
                        break
                else:
                    silent = 0
    if not chunks:
        raise RuntimeError("no speech detected; lower --rms-threshold or use --push-to-talk")
    return write_wav(out_path, np.concatenate(chunks), rate=rate)


def play_wav(path: Path) -> None:
    import sounddevice as sd

    pcm, rate = read_wav(path)
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    sd.play(audio, samplerate=rate, blocking=True)


def save_pcm_as_wav(path: Path, pcm: bytes, rate: int = 24000) -> Path:
    return write_wav(path, pcm, rate=rate)


def duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as wf:
        return int(1000 * wf.getnframes() / wf.getframerate())


def now_ms() -> int:
    return int(time.perf_counter() * 1000)
