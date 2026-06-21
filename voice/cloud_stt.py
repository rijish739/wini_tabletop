"""Google Cloud Speech-to-Text adapter — English-only transcription.

The Gemini Live model kept transcribing Indian-accented English into Telugu/Hindi
script. Cloud STT lets us FORCE a single language (en-US), so output is always
English. A maths phrase-hint set boosts domain words ("discriminant", "real
roots", ...) that a generic model otherwise mangles ("railroads").
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
