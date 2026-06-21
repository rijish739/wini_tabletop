"""Configuration helpers for cloud voice adapters."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
RUN_DIR = ROOT / ".voice_runs"


@dataclass(frozen=True)
class VoiceConfig:
    stt_provider: str
    tts_provider: str
    stt_model: str
    tts_model: str
    live_model: str
    tts_voice: str
    cloud_tts_voice: str
    project: str | None
    location: str | None
    use_vertex: bool
    use_enterprise: bool
    input_rate: int = 16000
    output_rate: int = 24000


def load_voice_config() -> VoiceConfig:
    load_dotenv(ROOT / ".env")
    use_vertex = _truthy(os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "true"))
    use_enterprise = _truthy(os.getenv("GOOGLE_GENAI_USE_ENTERPRISE", "false"))
    return VoiceConfig(
        stt_provider=os.getenv("WINI_STT_PROVIDER", "gemini_audio"),
        tts_provider=os.getenv("WINI_TTS_PROVIDER", "gemini_tts"),
        stt_model=os.getenv("WINI_STT_MODEL", "gemini-3.5-flash"),
        tts_model=os.getenv("WINI_TTS_MODEL", "gemini-3.1-flash-tts-preview"),
        live_model=os.getenv("WINI_LIVE_MODEL", "gemini-live-2.5-flash"),
        tts_voice=os.getenv("WINI_TTS_VOICE", "Kore"),
        cloud_tts_voice=os.getenv("WINI_CLOUD_TTS_VOICE", "en-IN-Chirp3-HD-Achernar"),
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
        use_vertex=use_vertex,
        use_enterprise=use_enterprise,
        input_rate=int(os.getenv("WINI_AUDIO_IN_RATE", "16000")),
        output_rate=int(os.getenv("WINI_AUDIO_OUT_RATE", "24000")),
    )


def make_genai_client(cfg: VoiceConfig):
    from google import genai

    kwargs = {
        "vertexai": cfg.use_vertex,
        "project": cfg.project,
        "location": cfg.location,
    }
    # google-genai rejects passing both vertexai and enterprise; only send
    # enterprise when it is actually enabled.
    if cfg.use_enterprise:
        kwargs["enterprise"] = True
    return genai.Client(**{k: v for k, v in kwargs.items() if v is not None})


def ensure_run_dir() -> Path:
    RUN_DIR.mkdir(exist_ok=True)
    return RUN_DIR


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}
