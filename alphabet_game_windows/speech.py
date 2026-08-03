"""Cloud voice for the alphabet module — Windows port.

Ported from pi_game/speech.py. The only things that change for Windows are the
audio *paths*; the cloud logic (Cloud TTS, Cloud STT, Gemini judge), the on-disk
WAV cache, and the two project rules below are unchanged.

* **Clients are built once per process.** Constructing a Google client costs
  4-9 s of ADC/channel setup while a warm call is under 1.5 s, so every client
  here is lazily memoized and the launcher prewarms them before the window opens.
* **Every cloud call carries a hard wall-clock timeout.** SDK-level timeouts have
  hung for hours in this project, so each call goes through `_bounded`.

Windows changes vs. the Pi:
  * playback is `winsound.PlaySound` (blocking), not ALSA `aplay`. It plays the
    same 24 kHz mono 16-bit WAVs the cache already holds.
  * the mic path (`voice.audio_io`) is imported lazily and guarded — if it or its
    dependencies (sounddevice/PortAudio) are missing, `listen()` degrades to the
    same silent-child path a headless run takes, instead of crashing the lesson.

Spoken lines are cached to disk as WAV keyed by voice+rate+text, so once a line
is cached it plays with NO cloud call — the whole 26-letter module speaks from
the bundled cache even with no Google credentials on the machine.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import wave
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
# voice.audio_io and llm_vertex live at the repo root; make them importable.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

CACHE = ROOT / "assets" / "tts_cache"

# A warm, unhurried delivery (matches the Pi build).
VOICE_NAME = os.getenv("ALPHABET_TTS_VOICE", "en-IN-Chirp3-HD-Achernar")
VOICE_LANG = os.getenv("ALPHABET_TTS_LANG", "en-IN")
SPEAK_RATE = float(os.getenv("ALPHABET_TTS_RATE", "0.88"))
TTS_HZ = 24000
STT_HZ = 16000

TTS_TIMEOUT_S = 25.0
STT_TIMEOUT_S = 25.0
LLM_TIMEOUT_S = 15.0

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="alpha-cloud")


def _bounded(fn, timeout_s: float, *a, **kw):
    """Run `fn` with a hard wall-clock cap. Raises TimeoutError past the cap."""
    fut = _pool.submit(fn, *a, **kw)
    try:
        return fut.result(timeout=timeout_s)
    except FutureTimeout:
        fut.cancel()
        raise TimeoutError(f"cloud call exceeded {timeout_s:.0f}s")


# ---------------------------------------------------------------------------
# Lazily memoized clients

_tts_client = None
_stt_client = None


def _tts():
    global _tts_client
    if _tts_client is None:
        from google.cloud import texttospeech as tts
        _tts_client = tts.TextToSpeechClient()
    return _tts_client


def _stt():
    global _stt_client
    if _stt_client is None:
        from google.cloud import speech
        _stt_client = speech.SpeechClient()
    return _stt_client


# ---------------------------------------------------------------------------
# Text to speech


def _key(text: str) -> str:
    raw = f"{VOICE_NAME}|{VOICE_LANG}|{SPEAK_RATE}|{TTS_HZ}|{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _write_wav(path: Path, pcm: bytes, rate: int) -> None:
    tmp = path.with_suffix(".part")
    with wave.open(str(tmp), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    # Atomic publish: a half-written WAV in the cache would be a permanent silent
    # line, since later runs treat "file exists" as "already synthesized".
    os.replace(tmp, path)


def synth(text: str) -> Path:
    """Return a local WAV of `text`, synthesizing through Cloud TTS on a miss."""
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{_key(text)}.wav"
    if out.exists():
        return out

    from google.cloud import texttospeech as tts

    def _call() -> bytes:
        resp = _tts().synthesize_speech(
            input=tts.SynthesisInput(text=text),
            voice=tts.VoiceSelectionParams(language_code=VOICE_LANG, name=VOICE_NAME),
            audio_config=tts.AudioConfig(
                audio_encoding=tts.AudioEncoding.LINEAR16,
                sample_rate_hertz=TTS_HZ,
                speaking_rate=SPEAK_RATE,
            ),
        )
        return resp.audio_content

    pcm = _bounded(_call, TTS_TIMEOUT_S)
    # LINEAR16 comes back as a complete WAV; strip the 44-byte header so the
    # cache holds one consistent format regardless of encoding choice.
    if pcm[:4] == b"RIFF":
        pcm = pcm[44:]
    _write_wav(out, pcm, TTS_HZ)
    return out


def prewarm(texts: list[str]) -> tuple[int, int]:
    """Synthesize every uncached line. Returns (synthesized, already_cached)."""
    made = cached = 0
    for t in texts:
        if (CACHE / f"{_key(t)}.wav").exists():
            cached += 1
            continue
        synth(t)
        made += 1
    return made, cached


def play(path: Path) -> None:
    """Play a WAV and block until it finishes (Windows).

    winsound, not ALSA `aplay`: it is in the standard library, needs no external
    binary, and plays synchronously (SND_FILENAME | SND_NODEFAULT), which gives
    the same fire-and-wait behaviour the lesson pacing relies on. It plays the
    24 kHz mono 16-bit WAVs the cache already holds.

    A playback failure is swallowed with a note, exactly like the Pi build: a
    silent line must never stall or crash the lesson.
    """
    try:
        import winsound
        # SND_FILENAME: `path` is a file. SND_NODEFAULT: on any error stay silent
        # rather than playing the Windows "ding". Synchronous (no SND_ASYNC) so
        # this blocks until the clip finishes, matching aplay's fire-and-wait.
        winsound.PlaySound(str(path),
                           winsound.SND_FILENAME | winsound.SND_NODEFAULT)
        return
    except Exception as exc:
        print(f"[alpha] playback failed for {path.name} ({exc})", flush=True)


def say(text: str) -> None:
    play(synth(text))


# ---------------------------------------------------------------------------
# Speech to text


def _record(out_path: Path, silence_ms: int, hard_cap_s: float) -> bool:
    """Record one utterance to `out_path`. False if no mic path is available.

    The recorder lives in the repo-root `voice` package (sounddevice-based, so
    it works on Windows). It is imported here, lazily and guarded: on any import
    or runtime failure we return False and the caller treats it as silence, so a
    machine with no microphone still runs the lesson end to end.
    """
    try:
        from voice.audio_io import record_auto_endpoint
    except Exception as exc:
        print(f"[alpha] mic unavailable ({exc}) — treating as silence", flush=True)
        return False
    try:
        record_auto_endpoint(out_path, rate=STT_HZ, threshold=0.012,
                             silence_ms=silence_ms, hard_cap_s=hard_cap_s)
        return True
    except Exception:
        return False


def listen(out_path: Path, silence_ms: int = 1200, hard_cap_s: float = 8.0) -> str:
    """Record one child utterance and transcribe it. "" if nothing was heard.

    Set ALPHABET_NO_MIC=1 to skip the mic entirely (returns "" at once) — the
    same path a silent child takes, so the lesson still advances through its two
    attempts. That is the default-safe mode for a laptop with no headset.
    """
    if os.getenv("ALPHABET_NO_MIC") == "1":
        return ""

    if not _record(out_path, silence_ms, hard_cap_s):
        return ""

    try:
        with wave.open(str(out_path), "rb") as wf:
            pcm = wf.readframes(wf.getnframes())
    except Exception:
        return ""
    if not pcm:
        return ""

    from google.cloud import speech

    def _call() -> str:
        cfg = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=STT_HZ,
            language_code="en-IN",
            model="latest_short",
            enable_automatic_punctuation=False,
        )
        resp = _stt().recognize(config=cfg, audio=speech.RecognitionAudio(content=pcm))
        return " ".join(r.alternatives[0].transcript
                        for r in resp.results if r.alternatives).strip()

    try:
        return _bounded(_call, STT_TIMEOUT_S)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Did the child attempt the sound?


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


# How Cloud STT tends to spell each letter's NAME. Naming the letter counts as a
# success: it shows the child connected the symbol to a sound.
LETTER_NAMES = {
    "A": ("ay", "eh", "ei"),      "B": ("bee", "be", "bi"),
    "C": ("see", "sea", "si"),    "D": ("dee", "de", "di"),
    "E": ("ee", "e", "yi"),       "F": ("ef", "eff"),
    "G": ("gee", "jee", "ji"),    "H": ("aitch", "aych", "hech"),
    "I": ("eye", "ai", "i"),      "J": ("jay", "jai"),
    "K": ("kay", "kai"),          "L": ("el", "ell"),
    "M": ("em", "emm"),           "N": ("en", "enn"),
    "O": ("oh", "o", "ow"),       "P": ("pee", "pe", "pi"),
    "Q": ("cue", "queue", "kyu"), "R": ("ar", "are", "aar"),
    "S": ("es", "ess"),           "T": ("tee", "te", "ti"),
    "U": ("you", "yu", "u"),      "V": ("vee", "ve", "vi"),
    "W": ("doubleyou", "doubleu"), "X": ("ex", "eks"),
    "Y": ("why", "wai"),          "Z": ("zed", "zee", "zi"),
}

_SHORT_UTTERANCE = 4


def judge_attempt(heard: str, letter: str, phoneme: str, say_as: str) -> bool:
    """True if `heard` is plausibly the child attempting the target sound.

    Cheap local check first, Gemini only when that is inconclusive. Matching is
    word-wise, never a bare substring test. A cloud failure resolves to True: the
    lesson has no failure state.
    """
    h = _normalize(heard)
    if not h:
        return False

    targets = {t for t in (_normalize(phoneme), _normalize(say_as)) if t}
    targets.update(LETTER_NAMES.get(letter.upper(), ()))

    for word in re.findall(r"[a-z]+", heard.lower()):
        if word in targets:
            return True
        if len(word) <= _SHORT_UTTERANCE:
            for t in targets:
                if len(t) <= _SHORT_UTTERANCE and (word[0] == t[0]) and (
                        word.startswith(t) or t.startswith(word)):
                    return True

    if len(h) > 12:
        return False

    return _gemini_judge(heard, letter, phoneme)


def _gemini_judge(heard: str, letter: str, phoneme: str) -> bool:
    """Ask Gemini whether a messy transcript is a fair attempt at the sound."""
    prompt = (
        "A young child was asked to say the ISOLATED SOUND of the letter "
        f"'{letter}', pronounced '{phoneme}'. Speech-to-text heard: '{heard}'.\n"
        "\n"
        "Answer YES only if the child was attempting that bare sound, or said "
        f"the name of the letter '{letter}'. Speech-to-text mangles small "
        "children, so allow for odd spellings of a short sound.\n"
        "\n"
        "Answer NO if the child said an ordinary WORD, even one that begins "
        f"with the '{phoneme}' sound.\n"
        "\n"
        "Reply with exactly one word: YES or NO."
    )
    try:
        from llm_vertex import generate_reply
        out = generate_reply(prompt, temperature=0.0, max_output_tokens=8,
                             timeout_s=LLM_TIMEOUT_S)
        text = (out.text or "").strip().lower()
        if text.startswith("yes"):
            return True
        if text.startswith("no"):
            return False
        print(f"[alpha] gemini judge gave no verdict ({text!r}) — passing", flush=True)
        return True
    except Exception as exc:
        print(f"[alpha] gemini judge unavailable ({exc}) — passing", flush=True)
        return True
