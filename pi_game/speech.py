"""Cloud voice for the alphabet module — TTS out, STT in, Gemini as the judge.

All three run in the cloud (Vertex / Google Cloud); nothing local. Two project
rules shape this file:

* **Clients are built once per process.** Constructing a Google client costs
  4-9 s of ADC/channel setup while a warm call is under 1.5 s, so every client
  here is lazily memoized and the launcher prewarms them before the panel lights
  up (CLAUDE.md "cold-start" gotcha).
* **Every cloud call carries a hard wall-clock timeout.** SDK-level timeouts have
  hung for hours in this project, so each call goes through `_bounded`.

Spoken lines are cached to disk as WAV keyed by voice+rate+text. A lesson's lines
are fully deterministic (content.lesson_lines), so after one prewarm pass the
whole 26-letter module speaks from local files with no per-turn cloud latency —
which is what keeps the §17 audio budget reachable over a home connection.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import wave
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "assets" / "tts_cache"

# A warm, unhurried delivery (§11 Audio Design, §2.4 Slow Interaction).
VOICE_NAME = os.getenv("ALPHABET_TTS_VOICE", "en-IN-Chirp3-HD-Achernar")
VOICE_LANG = os.getenv("ALPHABET_TTS_LANG", "en-IN")
SPEAK_RATE = float(os.getenv("ALPHABET_TTS_RATE", "0.88"))
TTS_HZ = 24000
STT_HZ = 16000

# The reSpeaker Lite, addressed by card name so a USB re-enumeration that shifts
# the card number does not silence the robot. Set ALPHABET_ALSA_DEVICE="" to fall
# back to the ALSA default (useful on other hardware).
ALSA_DEVICE = os.getenv("ALPHABET_ALSA_DEVICE", "plughw:CARD=Lite,DEV=0")

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
    tmp.replace(path)


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
    """Play a WAV and block until it finishes.

    aplay, not sounddevice: playback here is fire-and-wait with no mixing, and
    aplay works from a bare SSH launch where a PortAudio/PipeWire session may not
    exist. The reSpeaker exposes ONE playback substream, so the launcher stops
    touch_service.py first (PI_ACCESS.md §7) — otherwise this fails.

    The device is named explicitly: ALSA's `default` on this board is the HDMI
    sink (card 0) and returns "audio open error: Unknown error 524", so an
    unqualified aplay is silent even with the speaker free. Measured, not
    guessed — `plughw:CARD=Lite` is the reSpeaker.
    """
    for dev in ([ALSA_DEVICE] if ALSA_DEVICE else []) + [None]:
        cmd = ["aplay", "-q"] + (["-D", dev] if dev else []) + [str(path)]
        if subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0:
            return
    print(f"[alpha] playback failed for {path.name} "
          f"(device {ALSA_DEVICE!r}; is touch_service.py holding the speaker?)",
          flush=True)


def say(text: str) -> None:
    synth_and_play = synth(text)
    play(synth_and_play)


# ---------------------------------------------------------------------------
# Speech to text


def listen(out_path: Path, silence_ms: int = 1200, hard_cap_s: float = 8.0) -> str:
    """Record one child utterance and transcribe it. "" if nothing was heard.

    Children pause mid-word, so the endpoint silence is longer and the RMS gate
    lower than the tutor's adult defaults — cutting a child off mid-attempt is
    exactly the rushed feeling §2.4 forbids.
    """
    # Headless verification (and any launch with no PipeWire seat) has no mic.
    # Returning "" here takes the same path a silent child does, so the lesson
    # still advances through its two attempts and on to the next stage.
    if os.getenv("ALPHABET_NO_MIC") == "1":
        return ""

    from voice.audio_io import record_auto_endpoint

    try:
        record_auto_endpoint(out_path, rate=STT_HZ, threshold=0.012,
                             silence_ms=silence_ms, hard_cap_s=hard_cap_s)
    except Exception:
        return ""            # nothing said, or no mic session — never an error

    with wave.open(str(out_path), "rb") as wf:
        pcm = wf.readframes(wf.getnframes())
    if not pcm:
        return ""

    from google.cloud import speech

    def _call() -> str:
        cfg = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=STT_HZ,
            language_code="en-IN",
            model="latest_short",
            # A single sound is not a sentence; punctuation would only add noise
            # for the matcher below.
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
# success: it shows the child connected the symbol to a sound, which is what the
# stage is really checking.
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

# A child's answer to "can you say ah?" is one short sound. Anything longer is a
# sentence ("I don't know", "banana") and is not a bare attempt at the phoneme.
_SHORT_UTTERANCE = 4


def judge_attempt(heard: str, letter: str, phoneme: str, say_as: str) -> bool:
    """True if `heard` is plausibly the child attempting the target sound.

    Cheap local check first, Gemini only when that is inconclusive, so the common
    case costs nothing.

    The matching is deliberately WORD-WISE and never a bare substring test. A
    substring test against the one-character letter target accepts any word that
    merely contains that letter — "banana" and "elephant" both scored as correct
    attempts at A, and "blue" as an attempt at B. That silently inflated the
    success rate and is exactly what made the praise look untrustworthy.

    A cloud failure still resolves to True (see _gemini_judge): the lesson has no
    failure state, and an outage must never read to a child as "you were wrong".
    """
    h = _normalize(heard)
    if not h:
        return False                      # genuinely silent — worth one retry

    targets = {t for t in (_normalize(phoneme), _normalize(say_as)) if t}
    targets.update(LETTER_NAMES.get(letter.upper(), ()))

    # Compare word by word: STT may return "ah" alone or "ah ah" or "a, ah".
    for word in re.findall(r"[a-z]+", heard.lower()):
        if word in targets:
            return True
        # Near-misses of a short target: "aa" for "ah", "buh" for "buhh". Both
        # sides must be short, so a real word can never qualify on this path.
        if len(word) <= _SHORT_UTTERANCE:
            for t in targets:
                if len(t) <= _SHORT_UTTERANCE and (word[0] == t[0]) and (
                        word.startswith(t) or t.startswith(word)):
                    return True

    # A single short sound that STT spelled some other way is still very likely
    # an attempt; hand those to Gemini. A long phrase is not, so don't spend a
    # call on it — it is plainly not the child saying one sound.
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
        f"with the '{phoneme}' sound — saying a word that starts with the "
        "letter is not the same as saying the sound, and must not count.\n"
        "\n"
        "Reply with exactly one word: YES or NO."
    )
    try:
        # generate_reply already bounds itself on a wall clock, so it needs no
        # _bounded wrapper of its own — just hand it this stage's budget.
        from llm_vertex import generate_reply
        out = generate_reply(prompt, temperature=0.0, max_output_tokens=8,
                             timeout_s=LLM_TIMEOUT_S)
        text = (out.text or "").strip().lower()
        if text.startswith("yes"):
            return True
        if text.startswith("no"):
            return False
        # Neither word — most likely an empty completion. Treat it as an outage,
        # not as an answer. (Testing "no" not in text used to make an EMPTY reply
        # a silent pass, which is the worst possible default here.)
        print(f"[alpha] gemini judge gave no verdict ({text!r}) — passing", flush=True)
        return True
    except Exception as exc:
        print(f"[alpha] gemini judge unavailable ({exc}) — passing", flush=True)
        return True                        # never punish a cloud failure
