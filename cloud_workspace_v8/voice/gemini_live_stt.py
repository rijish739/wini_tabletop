"""Gemini Live API, used ONLY for input transcription (no audio-out).

Context: voice/live_session.py already replaced a full Gemini-Live audio-in/
audio-out loop with Cloud STT + Cloud TTS on 2026-06-18, because the Live
native-audio model would not speak text verbatim AND its STT transcribed
English speech into Telugu/Hindi script (see rag_memory.md). This module
re-checks *only* the STT half -- no audio out, so the paraphrasing defect does
not apply -- purely so voice_latency_spike.py can compare its latency and
transcript quality against Cloud STT side by side. Treat this as a probe, not
a proven adapter: if the script-language bug resurfaces, keep Cloud STT.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from google.genai import types

from .config import VoiceConfig, load_voice_config, make_genai_client


@dataclass
class LiveSttResult:
    transcript: str
    latency_ms: int
    error: str | None = None


class GeminiLiveStt:
    def __init__(self, cfg: VoiceConfig | None = None, language_codes: tuple[str, ...] = ("en-IN",),
                 timeout_s: float = 10.0) -> None:
        self.cfg = cfg or load_voice_config()
        self.client = make_genai_client(self.cfg)
        self.language_codes = list(language_codes)
        self.timeout_s = timeout_s

    def transcribe_pcm(self, pcm: bytes, rate: int) -> LiveSttResult:
        t0 = time.perf_counter()
        try:
            text = asyncio.run(asyncio.wait_for(self._transcribe(pcm, rate), timeout=self.timeout_s))
            error = None
        except Exception as exc:  # noqa: BLE001 -- never let a probe crash the pipeline
            text = ""
            error = f"{type(exc).__name__}: {exc}"
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return LiveSttResult(transcript=text.strip(), latency_ms=latency_ms, error=error)

    async def _transcribe(self, pcm: bytes, rate: int) -> str:
        config = types.LiveConnectConfig(
            response_modalities=["TEXT"],
            input_audio_transcription=types.AudioTranscriptionConfig(
                language_codes=self.language_codes
            ),
        )
        parts: list[str] = []
        async with self.client.aio.live.connect(model=self.cfg.live_model, config=config) as session:
            await session.send_realtime_input(
                audio=types.Blob(data=pcm, mime_type=f"audio/pcm;rate={rate}")
            )
            await session.send_realtime_input(audio_stream_end=True)
            async for msg in session.receive():
                sc = getattr(msg, "server_content", None)
                if sc is None:
                    continue
                transcription = getattr(sc, "input_transcription", None)
                if transcription and transcription.text:
                    parts.append(transcription.text)
                if getattr(sc, "turn_complete", False):
                    break
        return "".join(parts)


def main() -> None:
    import argparse
    from pathlib import Path

    from .audio_io import read_wav

    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    args = ap.parse_args()
    pcm, rate = read_wav(Path(args.audio))
    result = GeminiLiveStt().transcribe_pcm(pcm, rate)
    print(result)


if __name__ == "__main__":
    main()
