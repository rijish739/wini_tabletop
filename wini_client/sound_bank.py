"""SoundBank — procedural **cat voice** synthesis using numpy.

Wini's theme is a cat, so every sound is a synthesized feline vocalization,
not a beep.  Sounds are generated at **16 kHz** (the reSpeaker Lite's native
rate).  No WAV files, no dependencies beyond numpy.

How the voice works
-------------------
A meow is not a tone — it is a *vowel that moves*.  Real meows are
``[m]→[e]→[o]→[u]``: the mouth starts closed (nasal, muffled), opens (bright,
loud), then rounds and closes again.  That mouth movement is what the ear
hears as "meow" rather than "beeeep".

So instead of sine + envelope, we use an **additive source–filter model**:

* **Source** — a harmonic stack over a moving pitch (F0) contour, with a
  natural spectral rolloff, jitter (micro pitch wobble) and vibrato.
* **Filter** — 3 formant resonances whose centre frequencies *track over
  time* along vowel targets.  Harmonics near a formant are boosted, the rest
  fall away.  Vectorized per-harmonic, so it is fast enough to pre-generate
  the whole bank at startup (~0.3 s on a Pi 5).

Cat F0 sits around 500–800 Hz with formants far higher than a human's — the
vocal tract is tiny.  Those numbers are baked into the vowel tables below.

Families (all cat vocalizations)
--------------------------------
acknowledge     Short closed-mouth "mrrp" chirrup — the greeting trill.
curious         Rising interrogative "mrrow?" — pitch lifts at the end.
happy           Classic bright "meow", full mouth opening.
excited         Prey-chatter "ek-ek-ek" + a high chirp.
content         Closed-mouth murmur "mhmm" — low, warm, no mouth opening.
sleepy          Long slow breathy "maaaow", pitch sagging.
satisfied       Short descending "mrow" — the sigh at the end of a hold.
idle_ambient    Barely-audible chirrup / breath.
overstimulated  Clipped, rough "myaa!" complaint — sharper, not a hiss.
chirp           Bright single chirp (bird-watching sound).
trill           Rolled "brrrp" — rapid AM, mouth closed.

purr            Real purr: ~24 Hz pulse train through a low body resonance,
                with breath modulation.  Loopable 500 ms chunk.

Aliveness
---------
Mechanical repetition is the thing to avoid, so variation is layered:
per-family variations (4–6 each), anti-repetition history, per-play pitch /
duration / volume jitter, a random pre-roll delay, and a per-family chance of
a **double utterance** ("meow-meow") at a slightly different pitch.
"""

from __future__ import annotations

import random
from collections import deque
from typing import Dict, List, Tuple

import numpy as np

RATE = 16_000  # reSpeaker native rate

_RNG = np.random.default_rng()


# ── vowel table ──────────────────────────────────────────────────────────────
# (F1, F2, F3) in Hz — cat-scaled, not human.  "m" is the closed nasal mouth
# (dark, heavily damped); the rest are the open-mouth positions a meow sweeps
# through as the jaw drops and the lips round.
_VOWELS: Dict[str, Tuple[float, float, float]] = {
    "m":  (330, 1100, 2400),   # closed / nasal
    "e":  (900, 2150, 3000),   # bright, jaw opening   ("mee")
    "a":  (1050, 1800, 2900),  # widest opening        ("maa")
    "o":  (760, 1150, 2700),   # rounding              ("mow")
    "u":  (430, 900, 2500),    # nearly closed again   ("mu")
}

# Formant bandwidths (Hz).  Wider = softer / breathier, narrower = more
# "voiced" and present.
_BW = (140.0, 200.0, 320.0)
# Relative formant amplitudes — F1 dominates loudness, F3 adds brightness.
_FAMP = (1.0, 0.55, 0.22)


def _track(n: int, points: List[Tuple[float, float]]) -> np.ndarray:
    """Interpolate a control curve over *n* samples.

    *points* is ``[(position_0_to_1, value), ...]``.
    """
    xs = np.array([p[0] for p in points], dtype=np.float32)
    ys = np.array([p[1] for p in points], dtype=np.float32)
    return np.interp(np.linspace(0.0, 1.0, n, dtype=np.float32),
                     xs, ys).astype(np.float32)


def _vowel_tracks(n: int, seq: List[Tuple[float, str]]) -> List[np.ndarray]:
    """Build 3 formant tracks from a vowel sequence ``[(pos, vowel), ...]``."""
    return [_track(n, [(pos, _VOWELS[v][i]) for pos, v in seq])
            for i in range(3)]


def _voice(dur: float,
           f0_points: List[Tuple[float, float]],
           vowels: List[Tuple[float, str]],
           amp_points: List[Tuple[float, float]],
           harmonics: int = 34,
           tilt: float = 1.5,
           jitter: float = 0.012,
           vibrato_hz: float = 0.0,
           vibrato_depth: float = 0.0,
           breath: float = 0.0,
           rough_hz: float = 0.0,
           rough_depth: float = 0.0,
           seed: int = 0) -> np.ndarray:
    """Synthesize one vocalization.

    Parameters
    ----------
    dur : float
        Length in seconds.
    f0_points, amp_points : list of (position, value)
        Pitch (Hz) and amplitude (0–1) contours over the utterance.
    vowels : list of (position, vowel_name)
        The mouth trajectory — this is what makes it read as "meow".
    tilt : float
        Source spectral rolloff exponent (higher = darker / softer).
    jitter : float
        Fractional random pitch wobble.  Real voices are never dead steady;
        without this the result sounds synthetic.
    breath : float
        Amount of formant-shaped noise mixed in (adds a live, airy quality).
    rough_hz, rough_depth : float
        Amplitude modulation — the "rolled r" of a trill or a growl's rasp.
    """
    n = max(1, int(RATE * dur))
    rng = np.random.default_rng(1234 + seed)

    # ── pitch contour, with wobble + vibrato ─────────────────────────────
    f0 = _track(n, f0_points)
    if jitter > 0.0:
        # Slow random walk, smoothed — micro-variation, not noise.
        walk = rng.standard_normal(n).astype(np.float32)
        k = np.ones(int(RATE * 0.012), dtype=np.float32)
        k /= k.sum()
        walk = np.convolve(walk, k, mode="same").astype(np.float32)
        walk /= (np.abs(walk).max() + 1e-6)
        f0 = f0 * (1.0 + jitter * walk)
    if vibrato_hz > 0.0 and vibrato_depth > 0.0:
        t = np.linspace(0, dur, n, endpoint=False, dtype=np.float32)
        f0 = f0 * (1.0 + vibrato_depth * np.sin(2 * np.pi * vibrato_hz * t))

    phase = np.cumsum(2 * np.pi * f0 / RATE).astype(np.float32)

    # ── formant tracks ───────────────────────────────────────────────────
    ftracks = _vowel_tracks(n, vowels)

    # ── additive synthesis, formant-weighted ─────────────────────────────
    out = np.zeros(n, dtype=np.float32)
    nyq = RATE * 0.47
    for k in range(1, harmonics + 1):
        fk = f0 * k
        if fk.min() > nyq:
            break
        src = 1.0 / (k ** tilt)
        if src < 1e-4:
            break
        gain = np.zeros(n, dtype=np.float32)
        for i in range(3):
            gain += _FAMP[i] / (1.0 + ((fk - ftracks[i]) / (_BW[i] * 0.5)) ** 2)
        # Anti-alias: fade harmonics out as they approach Nyquist.
        gain *= np.clip((nyq - fk) / (nyq * 0.15), 0.0, 1.0)
        out += (src * gain * np.sin(k * phase + k * 0.7)).astype(np.float32)

    # ── breath noise, shaped by the same formants ────────────────────────
    if breath > 0.0:
        noise = rng.standard_normal(n).astype(np.float32)
        kern = np.ones(6, dtype=np.float32) / 6.0
        noise = np.convolve(noise, kern, mode="same").astype(np.float32)
        # Cheap formant colouring: modulate noise by the F1 track energy.
        out += breath * noise * (ftracks[0] / 1000.0)

    # ── roughness / trill AM ─────────────────────────────────────────────
    if rough_hz > 0.0 and rough_depth > 0.0:
        t = np.linspace(0, dur, n, endpoint=False, dtype=np.float32)
        am = 1.0 - rough_depth * (0.5 + 0.5 *
                                  np.sin(2 * np.pi * rough_hz * t))
        out *= am

    # ── amplitude contour ────────────────────────────────────────────────
    out *= _track(n, amp_points)

    # Normalize so every family lands at a comparable perceived level.
    peak = float(np.abs(out).max())
    if peak > 1e-6:
        out /= peak
    return out.astype(np.float32)


def _to_pcm16(audio: np.ndarray, amplitude: float) -> bytes:
    """Float32 → int16 PCM bytes, scaled by amplitude."""
    scaled = np.clip(audio * amplitude, -1.0, 1.0)
    return (scaled * 32767).astype(np.int16).tobytes()


def _concat(*segments: np.ndarray) -> np.ndarray:
    return np.concatenate(segments).astype(np.float32)


def _silence(dur: float) -> np.ndarray:
    return np.zeros(max(1, int(RATE * dur)), dtype=np.float32)


# ── sound generators ─────────────────────────────────────────────────────────
# Each returns float32 audio at RATE, peak-normalized.  The SoundBank applies
# amplitude + per-play variation on top.

def _gen_acknowledge(idx: int) -> np.ndarray:
    """Short closed-mouth chirrup "mrrp" — the greeting/acknowledge trill."""
    base = [620, 660, 580, 700][idx % 4]
    dur = [0.17, 0.15, 0.20, 0.16][idx % 4]
    return _voice(
        dur,
        f0_points=[(0.0, base * 0.80), (0.35, base), (1.0, base * 1.12)],
        vowels=[(0.0, "m"), (0.45, "u"), (1.0, "m")],
        amp_points=[(0.0, 0.0), (0.12, 1.0), (0.7, 0.9), (1.0, 0.0)],
        tilt=1.9, rough_hz=[30, 34, 27, 32][idx % 4], rough_depth=0.55,
        breath=0.03, seed=idx,
    )


def _gen_curious(idx: int) -> np.ndarray:
    """Rising interrogative "mrrow?" — the question meow."""
    base = [540, 580, 500, 620][idx % 4]
    dur = [0.34, 0.30, 0.38, 0.32][idx % 4]
    return _voice(
        dur,
        # The lift at the tail is the whole point — that's the question mark.
        f0_points=[(0.0, base * 0.85), (0.25, base), (0.6, base * 0.95),
                   (1.0, base * 1.45)],
        vowels=[(0.0, "m"), (0.22, "e"), (0.55, "o"), (0.8, "o"), (1.0, "u")],
        amp_points=[(0.0, 0.0), (0.10, 0.85), (0.35, 1.0), (0.85, 0.75),
                    (1.0, 0.0)],
        tilt=1.5, breath=0.05, vibrato_hz=[16, 19, 14, 18][idx % 4],
        vibrato_depth=0.012, seed=idx,
    )


def _gen_happy(idx: int) -> np.ndarray:
    """Classic bright "meow" — full [m]→[e]→[o]→[u] mouth opening."""
    base = [660, 700, 620, 720, 580][idx % 5]
    dur = [0.40, 0.36, 0.45, 0.34, 0.42][idx % 5]
    return _voice(
        dur,
        f0_points=[(0.0, base * 0.82), (0.18, base * 1.06), (0.45, base),
                   (1.0, base * 0.74)],
        vowels=[(0.0, "m"), (0.16, "e"), (0.40, "a"), (0.72, "o"), (1.0, "u")],
        amp_points=[(0.0, 0.0), (0.09, 0.8), (0.28, 1.0), (0.75, 0.8),
                    (1.0, 0.0)],
        tilt=1.4, breath=0.05, vibrato_hz=[18, 22, 15, 20, 17][idx % 5],
        vibrato_depth=0.014, seed=idx,
    )


def _gen_excited(idx: int) -> np.ndarray:
    """Prey-chatter "ek-ek-ek" then a high chirp — the window-watching sound."""
    base = [900, 980, 850][idx % 3]
    chatters = [3, 4, 3][idx % 3]
    parts: List[np.ndarray] = []
    for i in range(chatters):
        parts.append(_voice(
            0.045,
            f0_points=[(0.0, base * 1.10), (1.0, base * 0.88)],
            vowels=[(0.0, "e"), (1.0, "m")],
            amp_points=[(0.0, 0.0), (0.2, 1.0), (1.0, 0.0)],
            tilt=1.2, harmonics=18, rough_hz=55, rough_depth=0.5,
            breath=0.10, seed=idx * 10 + i,
        ))
        parts.append(_silence(0.030))
    parts.append(_voice(
        0.13,
        f0_points=[(0.0, base * 0.95), (0.4, base * 1.35), (1.0, base * 1.15)],
        vowels=[(0.0, "m"), (0.4, "e"), (1.0, "u")],
        amp_points=[(0.0, 0.0), (0.15, 1.0), (0.7, 0.85), (1.0, 0.0)],
        tilt=1.4, harmonics=20, breath=0.06, seed=idx,
    ))
    return _concat(*parts)


def _gen_content(idx: int) -> np.ndarray:
    """Closed-mouth murmur "mhmm" — warm, low, mouth never opens."""
    base = [340, 370, 310][idx % 3]
    dur = [0.42, 0.36, 0.50][idx % 3]
    return _voice(
        dur,
        f0_points=[(0.0, base * 0.94), (0.4, base), (1.0, base * 0.82)],
        vowels=[(0.0, "m"), (0.5, "m"), (1.0, "m")],
        amp_points=[(0.0, 0.0), (0.18, 1.0), (0.72, 0.9), (1.0, 0.0)],
        tilt=2.1, breath=0.04, rough_hz=[21, 24, 19][idx % 3],
        rough_depth=0.25, vibrato_hz=5.0, vibrato_depth=0.010, seed=idx,
    )


def _gen_sleepy(idx: int) -> np.ndarray:
    """Long slow breathy "maaaow" — a yawny meow, pitch sagging throughout."""
    base = [420, 450, 390][idx % 3]
    dur = [0.72, 0.62, 0.82][idx % 3]
    return _voice(
        dur,
        f0_points=[(0.0, base * 0.90), (0.25, base), (1.0, base * 0.62)],
        vowels=[(0.0, "m"), (0.20, "a"), (0.55, "a"), (0.85, "o"), (1.0, "u")],
        amp_points=[(0.0, 0.0), (0.20, 0.85), (0.45, 1.0), (0.8, 0.55),
                    (1.0, 0.0)],
        tilt=2.0, breath=0.14, vibrato_hz=4.5, vibrato_depth=0.018,
        jitter=0.020, seed=idx,
    )


def _gen_satisfied(idx: int) -> np.ndarray:
    """Short descending "mrow" — the contented sigh after a long stroke."""
    base = [520, 560, 480][idx % 3]
    dur = [0.26, 0.22, 0.30][idx % 3]
    return _voice(
        dur,
        f0_points=[(0.0, base * 1.05), (0.3, base), (1.0, base * 0.68)],
        vowels=[(0.0, "m"), (0.25, "o"), (0.7, "o"), (1.0, "u")],
        amp_points=[(0.0, 0.0), (0.12, 1.0), (0.65, 0.8), (1.0, 0.0)],
        tilt=1.8, breath=0.08, rough_hz=22, rough_depth=0.30, seed=idx,
    )


def _gen_idle_ambient(idx: int) -> np.ndarray:
    """Barely-audible chirrup or sleepy breath — "I'm still here"."""
    base = [560, 600, 520, 640][idx % 4]
    dur = [0.13, 0.11, 0.16, 0.12][idx % 4]
    out = _voice(
        dur,
        f0_points=[(0.0, base * 0.9), (0.5, base), (1.0, base * 1.08)],
        vowels=[(0.0, "m"), (0.5, "u"), (1.0, "m")],
        amp_points=[(0.0, 0.0), (0.2, 1.0), (0.7, 0.8), (1.0, 0.0)],
        tilt=2.2, rough_hz=28, rough_depth=0.5, breath=0.06, seed=idx,
    )
    return out * 0.45          # deliberately quiet — it's ambience


def _gen_overstimulated(idx: int) -> np.ndarray:
    """Clipped rough "myaa!" complaint — "that's enough now".

    Deliberately *not* a hiss: this plays at a child, so it reads as an
    annoyed mew, sharp and short, rather than a threat.
    """
    base = [780, 830][idx % 2]
    dur = [0.20, 0.17][idx % 2]
    return _voice(
        dur,
        f0_points=[(0.0, base * 1.15), (0.2, base * 1.05), (1.0, base * 0.80)],
        vowels=[(0.0, "e"), (0.3, "a"), (1.0, "a")],
        amp_points=[(0.0, 0.0), (0.05, 1.0), (0.55, 0.85), (1.0, 0.0)],
        tilt=1.15, breath=0.16, rough_hz=[46, 52][idx % 2], rough_depth=0.45,
        jitter=0.030, seed=idx,
    )


def _gen_chirp(idx: int) -> np.ndarray:
    """Bright single chirp — the short "brrt!" of a cat spotting something."""
    base = [880, 950, 820][idx % 3]
    dur = [0.12, 0.10, 0.14][idx % 3]
    return _voice(
        dur,
        f0_points=[(0.0, base * 0.85), (0.35, base * 1.25), (1.0, base * 1.05)],
        vowels=[(0.0, "m"), (0.4, "e"), (1.0, "u")],
        amp_points=[(0.0, 0.0), (0.12, 1.0), (0.6, 0.9), (1.0, 0.0)],
        tilt=1.3, harmonics=22, rough_hz=40, rough_depth=0.35,
        breath=0.07, seed=idx,
    )


def _gen_trill(idx: int) -> np.ndarray:
    """Rolled "brrrp" — the sound a cat makes walking up to you."""
    base = [500, 540, 460, 580][idx % 4]
    dur = [0.30, 0.26, 0.34, 0.28][idx % 4]
    return _voice(
        dur,
        f0_points=[(0.0, base * 0.88), (0.5, base), (1.0, base * 1.20)],
        vowels=[(0.0, "m"), (0.5, "u"), (1.0, "m")],
        amp_points=[(0.0, 0.0), (0.15, 0.95), (0.6, 1.0), (1.0, 0.0)],
        tilt=1.9, rough_hz=[26, 30, 23, 33][idx % 4], rough_depth=0.75,
        breath=0.04, seed=idx,
    )


def _gen_purr(idx: int) -> np.ndarray:
    """One loopable 500 ms purr chunk.

    A real purr is not a hum — it is a ~24 Hz train of glottal pulses ringing
    a low body resonance, with a slow breath cycle on top.  24 Hz gives
    exactly 12 pulses per 500 ms, so the chunk loops seamlessly.
    """
    dur = 0.5
    n = int(RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False, dtype=np.float32)
    rng = np.random.default_rng(77 + idx)

    pulse_hz = [24.0, 26.0, 22.0][idx % 3]
    # Asymmetric pulse: fast attack, slow decay — that's the "rr" texture.
    ph = (t * pulse_hz) % 1.0
    pulse = np.exp(-ph * 6.0).astype(np.float32)
    pulse *= np.clip(ph * 40.0, 0.0, 1.0)      # soften the discontinuity

    # Low body resonance the pulses excite.
    body_f = [155.0, 172.0, 140.0][idx % 3]
    body = (np.sin(2 * np.pi * body_f * t)
            + 0.5 * np.sin(2 * np.pi * body_f * 2 * t)
            + 0.25 * np.sin(2 * np.pi * body_f * 3 * t)).astype(np.float32)

    # A little noise gives the purr its fur-and-air texture.
    noise = rng.standard_normal(n).astype(np.float32)
    kern = np.ones(24, dtype=np.float32) / 24.0
    noise = np.convolve(noise, kern, mode="same").astype(np.float32)

    out = pulse * (body + 0.8 * noise)

    # Seamless loop: 20-sample crossfade at the edges.
    fade = 20
    env = np.ones(n, dtype=np.float32)
    env[:fade] = np.linspace(0, 1, fade, dtype=np.float32)
    env[-fade:] = np.linspace(1, 0, fade, dtype=np.float32)
    out = out * env

    peak = float(np.abs(out).max())
    if peak > 1e-6:
        out /= peak
    return out.astype(np.float32)


# ── family registry ──────────────────────────────────────────────────────────
# family_name: (generator_fn, num_variations, weights, double_chance)
# `double_chance` = probability of chaining a second utterance ("meow-meow"),
# which is a cheap, very effective anti-repetition trick.

_FAMILIES: Dict[str, Tuple[callable, int, List[float], float]] = {
    "acknowledge":    (_gen_acknowledge, 4, [0.32, 0.28, 0.22, 0.18], 0.15),
    "curious":        (_gen_curious,     4, [0.32, 0.26, 0.22, 0.20], 0.10),
    "happy":          (_gen_happy,       5, [0.26, 0.24, 0.20, 0.16, 0.14], 0.30),
    "excited":        (_gen_excited,     3, [0.40, 0.32, 0.28], 0.20),
    "content":        (_gen_content,     3, [0.40, 0.34, 0.26], 0.05),
    "sleepy":         (_gen_sleepy,      3, [0.40, 0.32, 0.28], 0.0),
    "satisfied":      (_gen_satisfied,   3, [0.38, 0.34, 0.28], 0.12),
    "idle_ambient":   (_gen_idle_ambient, 4, [0.30, 0.28, 0.24, 0.18], 0.0),
    "overstimulated": (_gen_overstimulated, 2, [0.55, 0.45], 0.25),
    "chirp":          (_gen_chirp,       3, [0.40, 0.32, 0.28], 0.35),
    "trill":          (_gen_trill,       4, [0.30, 0.28, 0.24, 0.18], 0.20),
}

_PURR_VARIATIONS = 3


class SoundBank:
    """Pre-generates and caches all cat sounds; serves them with variation
    and anti-repetition logic.

    Parameters
    ----------
    rate : int
        Sample rate.  Default 16 000 (reSpeaker native).
    base_amplitude : float
        Peak amplitude for emotion sounds relative to TTS (TTS ≈ 0.7).
        Default 0.5 — audible over the reSpeaker Lite alongside speech
        (0.15 was measured too quiet on-device, 2026-07-17).
    """

    def __init__(self, rate: int = RATE, base_amplitude: float = 0.5):
        self.rate = rate
        self.amplitude = base_amplitude
        # Pre-generate all variations as float32 arrays
        self._cache: Dict[str, List[np.ndarray]] = {}
        self._weights: Dict[str, List[float]] = {}
        self._double: Dict[str, float] = {}
        for name, (gen_fn, count, weights, dbl) in _FAMILIES.items():
            self._cache[name] = [gen_fn(i) for i in range(count)]
            self._weights[name] = weights
            self._double[name] = dbl
        self._purrs = [_gen_purr(i) for i in range(_PURR_VARIATIONS)]
        self._purr_idx = 0
        # Repetition avoidance: track last N indices per family
        self._history: Dict[str, deque] = {
            name: deque(maxlen=5) for name in _FAMILIES}

    # ── selection ────────────────────────────────────────────────────────

    def _pick(self, family: str) -> np.ndarray:
        """Choose a variation, penalizing recently-played ones."""
        variations = self._cache[family]
        weights = list(self._weights[family])
        history = self._history[family]

        for idx in history:
            if 0 <= idx < len(weights):
                weights[idx] *= 0.1   # heavy penalty, not zero (fallback)
        total = sum(weights)
        if total <= 0:
            weights = [1.0] * len(variations)
            total = sum(weights)
        probs = [w / total for w in weights]

        chosen = random.choices(range(len(variations)), weights=probs, k=1)[0]
        history.append(chosen)
        return variations[chosen].copy()

    @staticmethod
    def _repitch(audio: np.ndarray, factor: float) -> np.ndarray:
        """Resample to shift pitch (and, inseparably, duration)."""
        if abs(factor - 1.0) <= 0.001:
            return audio
        new_len = max(1, int(len(audio) / factor))
        return np.interp(
            np.linspace(0, len(audio) - 1, new_len),
            np.arange(len(audio)),
            audio,
        ).astype(np.float32)

    # ── public API ───────────────────────────────────────────────────────

    def get_sound(self, family: str,
                  mood: float = 50.0) -> Tuple[bytes, int]:
        """Return ``(pcm_int16_bytes, sample_rate)`` for a cat vocalization
        from *family*, with per-play pitch / duration / volume variation and
        an occasional double utterance.

        *mood* (0–100) scales amplitude **and pitch**: a low-mood cat is
        quieter and lower, a high-mood one brighter and more insistent.
        """
        if family not in self._cache:
            raise ValueError(f"unknown sound family: {family!r}")

        audio = self._pick(family)

        # ── playback variation ───────────────────────────────────────────
        # Pitch ±8% — wider than a beep bank can get away with, because a
        # voice stays recognizable when transposed.
        mood_pitch = 0.94 + 0.12 * min(1.0, max(0.0, mood / 100.0))
        audio = self._repitch(audio, (1.0 + random.uniform(-0.08, 0.08))
                              * mood_pitch)

        # Occasional second utterance, slightly lower and quieter — the way a
        # real cat repeats itself rather than emitting one identical bleep.
        if random.random() < self._double.get(family, 0.0):
            second = self._repitch(self._pick(family),
                                   random.uniform(0.86, 0.96))
            gap = _silence(random.uniform(0.06, 0.14))
            audio = _concat(audio, gap, second * random.uniform(0.65, 0.85))

        # Duration ±6% (trim or zero-pad)
        dur_factor = 1.0 + random.uniform(-0.06, 0.06)
        target_len = max(1, int(len(audio) * dur_factor))
        if target_len < len(audio):
            audio = audio[:target_len]
        elif target_len > len(audio):
            audio = np.pad(audio, (0, target_len - len(audio)))

        # Volume ±8%
        vol_factor = 1.0 + random.uniform(-0.08, 0.08)

        # Mood scaling: quiet when low, insistent when high.
        mood_scale = 0.6 + 0.7 * min(1.0, max(0.0, mood / 100.0))

        amp = self.amplitude * vol_factor * mood_scale

        # Start delay: 0–50 ms of silence
        delay_s = random.uniform(0.0, 0.05)
        if delay_s > 0:
            audio = _concat(_silence(delay_s), audio)

        return _to_pcm16(audio, amp), self.rate

    def get_purr_chunk(self, mood: float = 50.0) -> Tuple[bytes, int]:
        """Return one 500 ms loopable purr chunk as (pcm_bytes, rate).

        Successive chunks rotate through variations so a long hold breathes
        instead of looping one identical buffer.
        """
        mood_scale = 0.6 + 0.7 * min(1.0, max(0.0, mood / 100.0))
        amp = self.amplitude * 0.8 * mood_scale
        chunk = self._purrs[self._purr_idx % len(self._purrs)]
        self._purr_idx += 1
        return _to_pcm16(chunk, amp), self.rate

    @property
    def families(self) -> list[str]:
        return list(self._cache.keys())
