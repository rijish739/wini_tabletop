"""Google Cloud Text-to-Speech adapter — verbatim spoken output for Wini.

Unlike the Gemini Live native-audio model (which paraphrases and embellishes),
Cloud TTS speaks EXACTLY the text it is given. That is essential here: the words
come from the local tutor brain and must not be altered. Returns raw LINEAR16
PCM so the runner can play it through sounddevice.

Two paths (Part 13 Stage 1):
    synth()        one-shot — nothing plays until the WHOLE answer is synthesized
                   (measured 3.4-4.3 s, and it scales with answer length).
    synth_stream() bidirectional streaming — first PCM chunk in ~0.3 s, and the
                   cost stops scaling with answer length. This is the single
                   biggest latency win in Part 13.
`synth()` is deliberately left untouched as the fallback path.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Iterable, Iterator

from google.cloud import texttospeech as tts

# Hard wall-clock bounds. CLAUDE.md gotcha: SDK-level deadlines have stalled for
# hours in this project — the caller-side bound is the one that actually holds.
STREAM_FIRST_CHUNK_TIMEOUT_S = 15.0
STREAM_CHUNK_TIMEOUT_S = 10.0
STREAM_TOTAL_TIMEOUT_S = 60.0

_DONE = object()


class CloudTts:
    def __init__(self, voice_name: str = "en-IN-Chirp3-HD-Achernar",
                 language: str = "en-IN", rate: int = 24000) -> None:
        self.client = tts.TextToSpeechClient()
        self.voice = tts.VoiceSelectionParams(language_code=language, name=voice_name)
        self.cfg = tts.AudioConfig(audio_encoding=tts.AudioEncoding.LINEAR16, sample_rate_hertz=rate)
        self.rate = rate
        self.last_latency_ms = 0
        # Streaming config. NOTE: streaming wants AudioEncoding.PCM (headerless),
        # not LINEAR16 (which returns a 44-byte WAV header the player would emit
        # as a click). Chirp3-HD supports streaming; older voices do not.
        self.stream_cfg = tts.StreamingSynthesizeConfig(
            voice=self.voice,
            streaming_audio_config=tts.StreamingAudioConfig(
                audio_encoding=tts.AudioEncoding.PCM, sample_rate_hertz=rate),
        )

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

    # ------------------------------------------------------------------
    def synth_stream(self, text_iter: Iterable[str]) -> Iterator[bytes]:
        """Stream LINEAR16 PCM chunks as `text_iter` yields speakable pieces.

        `text_iter` is consumed lazily, so this composes with streaming
        generation: the first clause can be synthesized while the model is still
        writing the rest. Yields headerless PCM at ``self.rate``.

        The gRPC call runs on a worker thread feeding a queue, purely so the
        consumer gets a HARD per-chunk wall-clock bound — a stalled stream must
        abort, not hang (CLAUDE.md: SDK deadlines have stalled for hours).
        Raises TimeoutError on a stall and re-raises any worker exception, so
        the caller can fall back to `synth()`.
        """
        q: "queue.Queue[object]" = queue.Queue(maxsize=64)

        def _requests():
            yield tts.StreamingSynthesizeRequest(streaming_config=self.stream_cfg)
            for piece in text_iter:
                if piece and piece.strip():
                    yield tts.StreamingSynthesizeRequest(
                        input=tts.StreamingSynthesisInput(text=piece))

        def _worker():
            try:
                for resp in self.client.streaming_synthesize(_requests()):
                    if resp.audio_content:
                        q.put(resp.audio_content)
                q.put(_DONE)
            except Exception as e:  # noqa: BLE001 — surfaced to the consumer below
                q.put(e)

        threading.Thread(target=_worker, name="tts-stream", daemon=True).start()

        t0 = time.perf_counter()
        first = True
        while True:
            budget = STREAM_FIRST_CHUNK_TIMEOUT_S if first else STREAM_CHUNK_TIMEOUT_S
            remaining = STREAM_TOTAL_TIMEOUT_S - (time.perf_counter() - t0)
            if remaining <= 0:
                raise TimeoutError(
                    f"streaming TTS exceeded {STREAM_TOTAL_TIMEOUT_S}s overall")
            try:
                item = q.get(timeout=min(budget, remaining))
            except queue.Empty:
                raise TimeoutError(
                    f"streaming TTS stalled after {budget}s waiting for a chunk")
            if item is _DONE:
                return
            if isinstance(item, Exception):
                raise item
            if first:
                self.last_latency_ms = int((time.perf_counter() - t0) * 1000)
                first = False
            yield item  # type: ignore[misc]
