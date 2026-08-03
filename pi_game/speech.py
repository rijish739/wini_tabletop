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
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "assets" / "tts_cache"

# A warm, unhurried delivery (§11 Audio Design, §2.4 Slow Interaction).
VOICE_NAME = os.getenv("ALPHABET_TTS_VOICE", "en-IN-Chirp3-HD-Achernar")
VOICE_LANG = os.getenv("ALPHABET_TTS_LANG", "en-IN")
SPEAK_RATE = float(os.getenv("ALPHABET_TTS_RATE", "0.88"))
TTS_HZ = 24000
STT_HZ = 16000


@dataclass(frozen=True)
class Voice:
    """A TTS delivery: which cloud voice, in which language, how fast.

    Passed per call so one process can speak English and Kannada without
    rebuilding the (memoized, expensive) client. It also keys the WAV cache, so
    the two languages never collide on disk even for identical-looking text.
    """
    name: str
    lang: str
    rate: float


# The historical default is English; every function below falls back to it, so
# existing callers that pass only text keep their exact behaviour.
DEFAULT_VOICE = Voice(VOICE_NAME, VOICE_LANG, SPEAK_RATE)

# The default STT locale. The Kannada lessons pass "kn-IN" explicitly.
STT_LANG = os.getenv("ALPHABET_STT_LANG", "en-IN")

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


def _key(text: str, voice: Voice) -> str:
    raw = f"{voice.name}|{voice.lang}|{voice.rate}|{TTS_HZ}|{text}"
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


def synth(text: str, voice: Voice = DEFAULT_VOICE) -> Path:
    """Return a local WAV of `text`, synthesizing through Cloud TTS on a miss."""
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{_key(text, voice)}.wav"
    if out.exists():
        return out

    from google.cloud import texttospeech as tts

    def _call() -> bytes:
        resp = _tts().synthesize_speech(
            input=tts.SynthesisInput(text=text),
            voice=tts.VoiceSelectionParams(language_code=voice.lang, name=voice.name),
            audio_config=tts.AudioConfig(
                audio_encoding=tts.AudioEncoding.LINEAR16,
                sample_rate_hertz=TTS_HZ,
                speaking_rate=voice.rate,
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


def prewarm(texts: list[str], voice: Voice = DEFAULT_VOICE) -> tuple[int, int]:
    """Synthesize every uncached line. Returns (synthesized, already_cached)."""
    made = cached = 0
    for t in texts:
        if (CACHE / f"{_key(t, voice)}.wav").exists():
            cached += 1
            continue
        synth(t, voice)
        made += 1
    return made, cached


def play(path: Path) -> None:
    """Play a WAV and block until it finishes.

    Fire-and-wait, no mixing. The tricky part is WHO owns the reSpeaker's single
    playback substream:

    * On winipi5 the running **PipeWire daemon owns it**, so an exclusive
      `aplay -D plughw:CARD=Lite` gets "Device or resource busy" and there is no
      ALSA `pipewire` PCM plugin to route around it. `pw-play` mixes through the
      daemon and is the route that actually works — so it is tried FIRST whenever
      it exists.
    * On a board with no PipeWire, `pw-play` is absent and we fall back to aplay
      against the named reSpeaker (ALSA's `default` here is HDMI card 0, which
      returns "Unknown error 524", so the device must be named), then the default.

    First command that exits 0 wins; both routes work from a bare SSH launch.
    """
    import shutil

    cmds: list[list[str]] = []
    player = os.getenv("ALPHABET_PLAYER")            # force one route if set
    if player == "pwplay" or (player is None and shutil.which("pw-play")):
        cmds.append(["pw-play", str(path)])
    if player != "pwplay":
        for dev in ([ALSA_DEVICE] if ALSA_DEVICE else []) + [None]:
            cmds.append(["aplay", "-q"] + (["-D", dev] if dev else []) + [str(path)])

    for cmd in cmds:
        if subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0:
            return
    print(f"[alpha] playback failed for {path.name} "
          f"(tried {[c[0] for c in cmds]}; is another process holding the speaker?)",
          flush=True)


def say(text: str, voice: Voice = DEFAULT_VOICE) -> None:
    play(synth(text, voice))


# ---------------------------------------------------------------------------
# Speech to text


def listen(out_path: Path, silence_ms: int = 1200, hard_cap_s: float = 8.0,
           stt_lang: str = STT_LANG) -> str:
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
            language_code=stt_lang,
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


def judge_attempt(heard: str, letter: str, phoneme: str, say_as: str,
                  lang: str = "en") -> bool:
    """True if `heard` is plausibly the child attempting the target sound.

    `lang` selects the script the transcript comes back in — English STT returns
    Latin, Kannada STT returns the Kannada block — so the two need different
    normalization and different Gemini prompts.

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
    if lang == "kn":
        return _judge_attempt_kn(heard, letter, phoneme, say_as)

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


# ---------------------------------------------------------------------------
# The Kannada path — same shape, different script

_KN_BLOCK = re.compile(r"[ಀ-೿]+")

# A held or repeated vowel of ANY length ("ಆಆಆ") is caught by the pure-repeat test
# below. This gate is only for the leftover: a short, NON-repeat token worth a
# Gemini call. It must stay small — ಆನೆ (ಆ+ನ+ೆ = 3 codepoints) is a word that
# merely begins with the vowel, the Kannada form of the English "word starting
# with the letter" trap, and must fall on the reject side of this gate.
_KN_ELONGATION_MAX = 2


def _normalize_kn(s: str) -> str:
    """Keep only Kannada-block characters — drops STT's spaces and punctuation."""
    return "".join(_KN_BLOCK.findall(s))


def _judge_attempt_kn(heard: str, slug: str, phoneme: str, say_as: str) -> bool:
    """True if `heard` is plausibly the child saying the target vowel.

    For a vowel the target IS the akshara (content_kn sets phoneme == say == the
    character). The cheap check accepts the bare vowel or the vowel held/repeated,
    but NOT a longer token that only starts with it — so ಆ passes and ಆನೆ does not.
    A short unmatched utterance (odd STT spelling of one sound) is worth a Gemini
    call; a long one is plainly a word and is rejected without spending one.
    """
    h = _normalize_kn(heard)
    if not h:
        return False                      # genuinely silent — worth one retry

    targets = {t for t in (_normalize_kn(phoneme), _normalize_kn(say_as)) if t}
    for t in targets:
        # The whole utterance is nothing but this vowel, once or held: "ಆ", "ಆಆ".
        if t and len(h) % len(t) == 0 and h == t * (len(h) // len(t)):
            return True

    if len(h) > _KN_ELONGATION_MAX:       # a syllable or a word, not a bare vowel
        return False

    return _gemini_judge_kn(heard, phoneme)


def _gemini_judge_kn(heard: str, akshara: str) -> bool:
    """Ask Gemini whether a messy Kannada transcript is a fair attempt at a vowel."""
    prompt = (
        "A young child learning the Kannada alphabet was asked to say the "
        f"ISOLATED SOUND of the vowel (swara) '{akshara}'. Speech-to-text heard: "
        f"'{heard}'.\n\n"
        "Answer YES if the child was attempting that bare vowel sound. "
        "Speech-to-text mangles small children, so allow for odd spellings of a "
        "short sound, and accept the vowel appearing on its own or as the start "
        "of a tiny syllable.\n\n"
        "Answer NO if the child said an ordinary WORD — even one that begins with "
        f"'{akshara}' — because saying a word is not the same as saying the bare "
        "vowel sound, and must not count.\n\n"
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
        print(f"[alpha] gemini kn judge gave no verdict ({text!r}) — passing", flush=True)
        return True
    except Exception as exc:
        print(f"[alpha] gemini kn judge unavailable ({exc}) — passing", flush=True)
        return True                        # never punish a cloud failure
