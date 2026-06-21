"""Google Cloud Text-to-Speech adapter — verbatim spoken output for Wini.

Unlike the Gemini Live native-audio model (which paraphrases and embellishes),
Cloud TTS speaks EXACTLY the text it is given. That is essential here: the words
come from the local tutor brain and must not be altered. Returns raw LINEAR16
PCM so the runner can play it through sounddevice.
"""

from __future__ import annotations

import time

from google.cloud import texttospeech as tts


class CloudTts:
    def __init__(self, voice_name: str = "en-IN-Chirp3-HD-Achernar",
                 language: str = "en-IN", rate: int = 24000) -> None:
        self.client = tts.TextToSpeechClient()
        self.voice = tts.VoiceSelectionParams(language_code=language, name=voice_name)
        self.cfg = tts.AudioConfig(audio_encoding=tts.AudioEncoding.LINEAR16, sample_rate_hertz=rate)
        self.rate = rate
        self.last_latency_ms = 0

    def synth(self, text: str) -> bytes:
        """Synthesize `text` to LINEAR16 PCM bytes (mono, self.rate Hz)."""
        if not text.strip():
            return b""
        t0 = time.perf_counter()
        resp = self.client.synthesize_speech(
            input=tts.SynthesisInput(text=text), voice=self.voice, audio_config=self.cfg
        )
        self.last_latency_ms = int((time.perf_counter() - t0) * 1000)
        return resp.audio_content
