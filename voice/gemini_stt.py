"""Gemini audio transcription adapter.

This adapter is intentionally narrow: audio in, transcript out. It must not
answer the student or perform pedagogy.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from google.genai import types

from .config import VoiceConfig, load_voice_config, make_genai_client


@dataclass
class SttResult:
    transcript: str
    uncertain: bool
    language: str = "en"
    latency_ms: int = 0
    raw_text: str = ""


PROMPT = """Transcribe this student utterance exactly.
Return only JSON with:
{"transcript": "...", "language": "en", "uncertain": false}

Rules:
- Keep mathematical words and symbols if spoken.
- Do not answer the student.
- Do not explain the audio.
- If there is no speech, return an empty transcript and uncertain=true.
"""


class GeminiStt:
    def __init__(self, cfg: VoiceConfig | None = None) -> None:
        self.cfg = cfg or load_voice_config()
        self.client = make_genai_client(self.cfg)

    def transcribe_wav(self, path: Path) -> SttResult:
        data = path.read_bytes()
        t0 = time.perf_counter()
        response = self.client.models.generate_content(
            model=self.cfg.stt_model,
            contents=[
                PROMPT,
                types.Part.from_bytes(data=data, mime_type="audio/wav"),
            ],
            config=types.GenerateContentConfig(
                temperature=0.0,
                responseMimeType="application/json",
            ),
        )
        latency = int((time.perf_counter() - t0) * 1000)
        raw = getattr(response, "text", "") or ""
        parsed = _parse_json(raw)
        transcript = _clean_transcript(str(parsed.get("transcript", "")))
        return SttResult(
            transcript=transcript,
            uncertain=bool(parsed.get("uncertain", not transcript)),
            language=str(parsed.get("language", "en")),
            latency_ms=latency,
            raw_text=raw,
        )


def _parse_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.IGNORECASE | re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not m:
            return {"transcript": cleaned, "uncertain": True}
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return {"transcript": cleaned, "uncertain": True}


def _clean_transcript(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    noise = {"thank you", "thanks for watching", "subscribe", "music", "[music]"}
    return "" if text.lower().strip(".!") in noise else text


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    args = ap.parse_args()
    result = GeminiStt().transcribe_wav(Path(args.audio))
    print(json.dumps(result.__dict__, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
