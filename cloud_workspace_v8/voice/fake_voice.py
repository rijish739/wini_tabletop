"""Fake voice adapters for no-cloud smoke tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .audio_io import save_pcm_as_wav


@dataclass
class SttResult:
    transcript: str
    uncertain: bool = False
    language: str = "en"
    latency_ms: int = 0


class FakeStt:
    def __init__(self, transcript: str = "") -> None:
        self.transcript = transcript

    def transcribe_wav(self, path: Path) -> SttResult:
        return SttResult(transcript=self.transcript or path.stem.replace("_", " "))


class FakeTts:
    def synthesize(self, text: str, pace: str = "slow-clear") -> bytes:
        seconds = max(1, min(4, len(text.split()) // 6 + 1))
        return b"\x00\x00" * 24000 * seconds

    def synthesize_to_wav(self, text: str, out_path: Path, pace: str = "slow-clear") -> Path:
        return save_pcm_as_wav(out_path, self.synthesize(text, pace=pace), rate=24000)
