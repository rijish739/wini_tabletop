"""Gemini TTS adapter for exact local answer speech."""

from __future__ import annotations

import time
from pathlib import Path

from google.genai import types

from .audio_io import save_pcm_as_wav
from .config import VoiceConfig, load_voice_config, make_genai_client


class GeminiTts:
    def __init__(self, cfg: VoiceConfig | None = None) -> None:
        self.cfg = cfg or load_voice_config()
        self.client = make_genai_client(self.cfg)
        self.last_latency_ms = 0

    def synthesize(self, text: str, pace: str = "slow-clear") -> bytes:
        prompt = (
            "Say in a warm, clear Indian-English friendly tutoring voice.\n"
            f"Pace: {pace}; add a short pause after each sentence.\n\n"
            f'"{text}"'
        )
        t0 = time.perf_counter()
        response = self.client.models.generate_content(
            model=self.cfg.tts_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                responseModalities=["AUDIO"],
                speechConfig=types.SpeechConfig(
                    voiceConfig=types.VoiceConfig(
                        prebuiltVoiceConfig=types.PrebuiltVoiceConfig(
                            voiceName=self.cfg.tts_voice,
                        )
                    )
                ),
            ),
        )
        self.last_latency_ms = int((time.perf_counter() - t0) * 1000)
        part = response.candidates[0].content.parts[0]
        inline = getattr(part, "inline_data", None) or getattr(part, "inlineData", None)
        if inline is None:
            raise RuntimeError("Gemini TTS response did not contain inline audio")
        data = getattr(inline, "data", None)
        if isinstance(data, str):
            import base64

            return base64.b64decode(data)
        return bytes(data)

    def synthesize_to_wav(self, text: str, out_path: Path, pace: str = "slow-clear") -> Path:
        return save_pcm_as_wav(out_path, self.synthesize(text, pace=pace), rate=self.cfg.output_rate)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pace", default="slow-clear")
    args = ap.parse_args()
    path = GeminiTts().synthesize_to_wav(args.text, Path(args.out), pace=args.pace)
    print(path)


if __name__ == "__main__":
    main()
