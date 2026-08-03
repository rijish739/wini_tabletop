"""The languages the alphabet module can teach, and everything that differs.

One lesson engine, two content sets. Every place that used to reach straight for
``content`` now takes a ``Language`` instead, so the state machine, the asset
loader and the voice all stay language-neutral. English is byte-for-byte what it
was; Kannada is the swaragalu twin.

Each ``Language`` bundles the four things that actually vary:

* ``module``    — the content module (``content`` or ``content_kn``): ORDER,
                  LETTERS, EDIBLE, lesson_dict, lesson_lines.
* ``voice``     — which Cloud TTS voice speaks, and the STT locale to hear back.
* ``asset_root``— the subdirectory under ``assets/`` its PNGs live in, so the two
                  scripts never share a directory (English keeps the flat
                  ``assets/letters/``; Kannada gets ``assets/kn/letters/``).
* ``font_path`` — the TTF ``gen_assets`` rasterizes its glyphs from. Latin glyphs
                  come from Nunito; Kannada aksharas need a Kannada face.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from pi_game import content, content_kn
from pi_game.speech import Voice

# gen_assets rasterizes each glyph to PNG from these faces, and textimg renders
# whole Kannada lines from the Kannada face. Nunito has no Kannada glyphs and the
# Kannada face has no reason to draw Latin, so they are per language, not global.
NUNITO_FONT = os.getenv(
    "ALPHABET_FONT_EN",
    "/usr/share/fonts/truetype/nunito-sans/NunitoSans-VariableFont_YTLC,opsz,wdth,wght.ttf",
)


def _first_font(candidates: list[str | None], default: str) -> str:
    """First path that exists (~ expanded). The Kannada face is installed no-sudo
    to the user font dir on the Pi, so probe that before the system location."""
    for c in candidates:
        if c and os.path.exists(os.path.expanduser(c)):
            return os.path.expanduser(c)
    return os.path.expanduser(default)


KANNADA_FONT = _first_font(
    [
        os.getenv("ALPHABET_FONT_KN"),
        "~/.local/share/fonts/NotoSansKannada-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansKannada-Regular.ttf",
    ],
    "~/.local/share/fonts/NotoSansKannada-Regular.ttf",
)


@dataclass(frozen=True)
class Language:
    code: str            # "en", "kn" — the token on the wire and in the DB
    label: str           # what the start-screen toggle shows ("English", "ಕನ್ನಡ")
    module: object       # content module: ORDER / LETTERS / lesson_dict / lesson_lines
    voice: Voice         # Cloud TTS delivery
    stt_lang: str        # Cloud STT locale for the repeat stage
    asset_root: str      # subdir under assets/ ("" for English, "kn" for Kannada)
    font_path: str       # TTF gen_assets renders glyphs from


ENGLISH = Language(
    code="en",
    label="English",
    module=content,
    # The historical default delivery — unchanged, so the English cache still hits.
    voice=Voice(
        os.getenv("ALPHABET_TTS_VOICE", "en-IN-Chirp3-HD-Achernar"),
        os.getenv("ALPHABET_TTS_LANG", "en-IN"),
        float(os.getenv("ALPHABET_TTS_RATE", "0.88")),
    ),
    stt_lang=os.getenv("ALPHABET_STT_LANG", "en-IN"),
    asset_root="",
    font_path=NUNITO_FONT,
)

KANNADA = Language(
    code="kn",
    label="ಕನ್ನಡ",
    module=content_kn,
    # Chirp3-HD carries a Kannada voice under the same star names as en-IN; if a
    # given install lacks it, override with e.g. ALPHABET_TTS_VOICE_KN=kn-IN-Wavenet-A.
    voice=Voice(
        os.getenv("ALPHABET_TTS_VOICE_KN", "kn-IN-Chirp3-HD-Achernar"),
        "kn-IN",
        float(os.getenv("ALPHABET_TTS_RATE_KN", "0.9")),
    ),
    stt_lang="kn-IN",
    asset_root="kn",
    font_path=KANNADA_FONT,
)


LANGS: dict[str, Language] = {ENGLISH.code: ENGLISH, KANNADA.code: KANNADA}

# What the child gets if the UI sends no language (older UI, or a bare CLI begin).
DEFAULT_LANG = ENGLISH.code


def get(code: str | None) -> Language:
    """Resolve a wire/CLI language code to a Language, falling back to English."""
    return LANGS.get((code or "").lower(), LANGS[DEFAULT_LANG])
