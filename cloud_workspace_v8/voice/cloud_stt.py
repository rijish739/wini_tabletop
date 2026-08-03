"""Google Cloud Speech-to-Text adapter — English-only transcription.

GROUND TRUTH: this adapter transcribes to ENGLISH ONLY. The language is forced to
``en-US`` (see ``__init__`` default below) and is never overridden by any call site,
so the output is always Latin-script English text. It does NOT, and cannot, produce
Hindi or Telugu output.

Design note (why the language is pinned): the earlier Gemini Live STT path
(``voice/gemini_live_stt.py``, now retired) auto-detected language and would render
Indian-accented English into Telugu/Hindi script. Cloud STT lets us pin a single
``language_code``, which is why this class exists and hard-codes English.

A maths phrase-hint set boosts domain words ("discriminant", "real roots", ...) that
a generic model otherwise mangles ("railroads").
"""

from __future__ import annotations

from google.cloud import speech

MATHS_PHRASES = [
    "discriminant", "real roots", "two real roots", "no real roots", "equal roots",
    "quadratic", "quadratic equation", "nature of the roots",
    "D is positive", "D is negative", "D is zero", "D positive", "D negative",
    "b squared minus four a c", "coefficient", "factorise", "roots", "equation",
    "trigonometry", "sine", "cosine", "tangent", "hypotenuse", "right triangle",
    "Pythagoras", "theorem", "polynomial", "parabola", "vertex", "discriminate",
]


class CloudStt:
    def __init__(self, language: str = "en-US", phrases: list[str] | None = None,
                 boost: float = 18.0, model: str = "latest_short") -> None:
        # language defaults to en-US and every caller uses this default → English only.
        self.client = speech.SpeechClient()
        self.language = language
        self.model = model
        self.context = speech.SpeechContext(phrases=phrases or MATHS_PHRASES, boost=boost)

    def recognize_pcm(self, pcm: bytes, rate: int) -> str:
        if not pcm:
            return ""
        cfg = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=rate,
            language_code=self.language,
            model=self.model,
            speech_contexts=[self.context],
            enable_automatic_punctuation=True,
        )
        resp = self.client.recognize(config=cfg, audio=speech.RecognitionAudio(content=pcm))
        return " ".join(r.alternatives[0].transcript for r in resp.results if r.alternatives).strip()

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
        # Tail guard: if the stream ends with an un-finalized interim (the last word
        # can stay interim when audio ends without enough trailing silence to trip
        # the endpointer), keep it — otherwise streaming silently drops the final
        # word that the batch path returns. This is the difference that fails the
        # Phase D parity gate on the longest utterances.
        if last_interim.strip():
            finals.append(last_interim)
        return " ".join(finals).strip()
