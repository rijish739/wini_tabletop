"""Google Cloud Speech-to-Text adapter — English-only transcription.

The Gemini Live model kept transcribing Indian-accented English into Telugu/Hindi
script. Cloud STT lets us FORCE a single language (en-US), so output is always
English. A maths phrase-hint set boosts domain words ("discriminant", "real
roots", ...) that a generic model otherwise mangles ("railroads").
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from google.cloud import speech

try:
    import debug_logger as _dbg
except ImportError:
    _dbg = None  # type: ignore[assignment]

MATHS_PHRASES = [
    "discriminant", "real roots", "two real roots", "no real roots", "equal roots",
    "quadratic", "quadratic equation", "nature of the roots",
    "D is positive", "D is negative", "D is zero", "D positive", "D negative",
    "b squared minus four a c", "coefficient", "factorise", "roots", "equation",
    "trigonometry", "sine", "cosine", "tangent", "hypotenuse", "right triangle",
    "Pythagoras", "theorem", "polynomial", "parabola", "vertex", "discriminate",
]


@dataclass(frozen=True)
class TranscriptionEvidence:
    transcript: str
    confidence: float


class CloudStt:
    def __init__(self, language: str = "en-US", phrases: list[str] | None = None,
                 boost: float = 18.0, model: str = "latest_short") -> None:
        self.client = speech.SpeechClient()
        self.language = language
        self.model = model
        self.context = speech.SpeechContext(phrases=phrases or MATHS_PHRASES, boost=boost)

    def recognize_pcm(self, pcm: bytes, rate: int) -> str:
        """Compatibility API returning text only."""
        return self.recognize_pcm_evidence(pcm, rate).transcript

    def recognize_pcm_evidence(self, pcm: bytes, rate: int) -> TranscriptionEvidence:
        if not pcm:
            return TranscriptionEvidence("", 0.0)
        if _dbg:
            _dbg.emit(_dbg.L1, "stt_start", mode="pcm", pcm_bytes=len(pcm), rate=rate)
        t0 = time.perf_counter()
        cfg = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=rate,
            language_code=self.language,
            model=self.model,
            speech_contexts=[self.context],
            enable_automatic_punctuation=True,
        )
        try:
            resp = self.client.recognize(config=cfg, audio=speech.RecognitionAudio(content=pcm))
            transcript = " ".join(
                r.alternatives[0].transcript for r in resp.results if r.alternatives
            ).strip()
            confidences = [float(r.alternatives[0].confidence)
                           for r in resp.results if r.alternatives
                           and getattr(r.alternatives[0], "confidence", None) is not None]
            confidence = (sum(confidences) / len(confidences)) if confidences else 0.0
        except Exception as _e:
            if _dbg:
                _dbg.emit(_dbg.L1, "stt_error", mode="pcm", error=str(_e))
            raise
        ms = int((time.perf_counter() - t0) * 1000)
        if _dbg:
            _dbg.emit(_dbg.L1, "stt_done", mode="pcm", transcript=transcript,
                      confidence=round(confidence, 4), ms=ms, empty=not bool(transcript))
        return TranscriptionEvidence(transcript, max(0.0, min(1.0, confidence)))

    def _recognition_config(self, rate: int) -> "speech.RecognitionConfig":
        """The one config both paths share — so streaming transcripts match batch by
        construction (same model, same MATHS_PHRASES boost that stops
        'discriminant' -> 'railroads'). Part 15 Phase D's hard gate is parity with
        batch; sharing the config is how that gate is met, not hoped for."""
        return speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=rate,
            language_code=self.language,
            model=self.model,
            speech_contexts=[self.context],
            enable_automatic_punctuation=True,
        )

    def recognize_stream(self, pcm_blocks, rate: int,
                         single_utterance: bool = False, on_interim=None) -> str:
        """Streaming transcription (Part 15 Phase D). ``pcm_blocks`` is an iterable of
        LINEAR16 PCM byte chunks (the client feeds ~50 ms blocks as the child speaks);
        the final transcript is returned when the stream ends.

        Same RecognitionConfig as the batch path, so the result matches
        ``recognize_pcm`` on the same audio — the hard no-regression gate. Interim
        hypotheses are delivered to ``on_interim(text)`` if provided (the hook the
        speculative-perception half of Phase B waits on: the first stable interim
        lets perception start before the child finishes). ``single_utterance`` lets
        Cloud STT own end-of-speech endpointing so the device can drop its own
        silence timeout."""
        if _dbg:
            _dbg.emit(_dbg.L1, "stt_start", mode="stream", rate=rate)
        t0 = time.perf_counter()
        streaming_config = speech.StreamingRecognitionConfig(
            config=self._recognition_config(rate),
            interim_results=True,
            single_utterance=single_utterance,
        )

        def _requests():
            for block in pcm_blocks:
                if block:
                    yield speech.StreamingRecognizeRequest(audio_content=block)

        finals: list[str] = []
        last_interim = ""      # tail guard: see below
        try:
            responses = self.client.streaming_recognize(streaming_config, _requests())
            for resp in responses:
                for result in resp.results:
                    if not result.alternatives:
                        continue
                    text = result.alternatives[0].transcript
                    if result.is_final:
                        finals.append(text)
                        last_interim = ""       # this segment resolved; drop its interim
                    else:
                        last_interim = text
                        if on_interim is not None:
                            try:
                                on_interim(text)
                            except Exception:  # noqa: BLE001 — a hook must never break STT
                                pass
        except Exception as _e:
            if _dbg:
                _dbg.emit(_dbg.L1, "stt_error", mode="stream", error=str(_e))
            raise
        # Tail guard: if the stream ends with an un-finalized interim (the last word
        # can stay interim when audio ends without enough trailing silence to trip
        # the endpointer), keep it — otherwise streaming silently drops the final
        # word that the batch path returns. This is the difference that fails the
        # Phase D parity gate on the longest utterances.
        if last_interim.strip():
            finals.append(last_interim)
        transcript = " ".join(finals).strip()
        ms = int((time.perf_counter() - t0) * 1000)
        if _dbg:
            _dbg.emit(_dbg.L1, "stt_done", mode="stream", transcript=transcript,
                      ms=ms, empty=not bool(transcript))
        return transcript
