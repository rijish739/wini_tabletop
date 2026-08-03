"""AudioManager — centralized gatekeeper for all audio output.

All emotion and ambient sounds must pass through this manager, which
enforces:

1. **TTS exclusivity** — emotion sounds are suppressed while TTS is active.
2. **Priority ordering** — TTS > emotion > idle ambience.
3. **Cooldowns** — ≥ 800 ms between emotion sounds; max 5 per rolling 10 s.
4. **Hold hum lifecycle** — plays looping purr in a background thread;
   fades immediately when TTS starts.

The manager does NOT own the output stream.  It routes audio through the
existing ``play_pcm()`` function in ``wini_client.client``, which owns
the persistent reSpeaker output stream.
"""

from __future__ import annotations

import random
import threading
import time
from collections import deque
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .sound_bank import SoundBank


# ── tuning ───────────────────────────────────────────────────────────────────
COOLDOWN_MS = 800                # min gap between emotion sounds
MAX_SOUNDS_PER_WINDOW = 5        # max emotion sounds in WINDOW_S
WINDOW_S = 10.0                  # rolling window for the above cap
IDLE_MIN_S = 30.0                # min time between idle ambient sounds
IDLE_MAX_S = 90.0                # max time between idle ambient sounds


class AudioManager:
    """Thread-safe audio gatekeeper.

    Parameters
    ----------
    play_fn : callable(pcm_bytes, sample_rate)
        The function that actually writes to the speaker — normally
        ``wini_client.client.play_pcm``.
    sound_bank : SoundBank
        Pre-generated emotion sounds.
    log : callable
        Logging function (default ``print``).
    """

    def __init__(self,
                 play_fn: Callable[[bytes, int], None],
                 sound_bank: "SoundBank",
                 log: Callable[[str], None] = print):
        self._play_fn = play_fn
        self._bank = sound_bank
        self._log = log

        self._lock = threading.Lock()
        self._speaking = False        # TTS active flag
        self._touching = False        # finger on head
        self._last_sound_t: float = 0.0
        self._sound_times: deque = deque()  # timestamps of recent plays
        self._mood: float = 50.0      # current mood (set by emotion engine)

        # Hold hum
        self._purr_thread: threading.Thread | None = None
        self._purr_stop = threading.Event()

        # Idle ambient scheduling
        self._next_idle_t: float = time.monotonic() + random.uniform(
            IDLE_MIN_S, IDLE_MAX_S)

    # ── TTS state ────────────────────────────────────────────────────────

    def set_speaking(self, active: bool) -> None:
        """Called by the client before / after TTS playback."""
        with self._lock:
            was_speaking = self._speaking
            self._speaking = active
        if active and not was_speaking:
            # TTS just started — kill any hold hum immediately
            self._stop_purr_thread()

    def is_speaking(self) -> bool:
        return self._speaking

    # ── touch state (for idle suppression) ───────────────────────────────

    def set_touching(self, active: bool) -> None:
        self._touching = active

    # ── mood (set by EmotionEngine) ──────────────────────────────────────

    def set_mood(self, mood: float) -> None:
        self._mood = max(0.0, min(100.0, mood))

    # ── emotion sound playback ───────────────────────────────────────────

    def play_emotion(self, family: str) -> bool:
        """Accept a sound from *family* and dispatch playback to a worker thread.

        Returns False if suppressed (TTS active, cooldown, or rate limit); True
        if accepted.  Playback runs off-thread so the caller — typically the
        GPIO poll / gesture thread — never blocks on the (blocking) speaker
        write, which is what made rapid taps feel unresponsive.
        """
        now = time.monotonic()
        with self._lock:
            if self._speaking:
                return False
            # Cooldown
            if (now - self._last_sound_t) * 1000 < COOLDOWN_MS:
                return False
            # Rate limit
            cutoff = now - WINDOW_S
            while self._sound_times and self._sound_times[0] < cutoff:
                self._sound_times.popleft()
            if len(self._sound_times) >= MAX_SOUNDS_PER_WINDOW:
                return False
            # Reserve this slot
            self._last_sound_t = now
            self._sound_times.append(now)

        threading.Thread(target=self._render_and_play, args=(family,),
                         name=f"emotion-{family}", daemon=True).start()
        return True

    def _render_and_play(self, family: str) -> None:
        """Generate + play one emotion sound (runs on a worker thread)."""
        try:
            pcm, rate = self._bank.get_sound(family, self._mood)
            # Double-check TTS didn't start while we were generating
            if self._speaking:
                return
            self._play_fn(pcm, rate)
        except Exception as e:  # noqa: BLE001
            self._log(f"[audio_mgr] play_emotion({family}) failed: {e}")

    # ── hold hum (purr) ──────────────────────────────────────────────────

    def start_purr(self) -> None:
        """Begin a continuous low hum.  Loops until ``stop_purr()`` or TTS."""
        if self._speaking:
            return
        self._stop_purr_thread()
        self._purr_stop.clear()
        self._purr_thread = threading.Thread(
            target=self._purr_loop, name="purr-loop", daemon=True)
        self._purr_thread.start()

    def stop_purr(self) -> None:
        """Stop the hold hum and play a satisfied ending sound."""
        was_purring = self._purr_thread is not None and self._purr_thread.is_alive()
        self._stop_purr_thread()
        if was_purring and not self._speaking:
            self.play_emotion("satisfied")

    def _stop_purr_thread(self) -> None:
        self._purr_stop.set()
        if self._purr_thread is not None:
            self._purr_thread.join(timeout=1.0)
            self._purr_thread = None

    def _purr_loop(self) -> None:
        while not self._purr_stop.is_set() and not self._speaking:
            try:
                pcm, rate = self._bank.get_purr_chunk(self._mood)
                if self._speaking or self._purr_stop.is_set():
                    break
                # Pass the stop event as the write-preempt signal: when TTS
                # starts, set_speaking() sets _purr_stop, and the in-flight
                # chunk bails within one slice so TTS isn't stuck behind it.
                try:
                    self._play_fn(pcm, rate, interrupt=self._purr_stop)
                except TypeError:
                    # play_fn without the interrupt kwarg (e.g. a test double)
                    self._play_fn(pcm, rate)
            except Exception:  # noqa: BLE001
                break

    # ── idle ambient sounds ──────────────────────────────────────────────

    def tick(self) -> None:
        """Called from the supervisor's 0.2 s tick.  Schedules idle sounds."""
        now = time.monotonic()
        if now < self._next_idle_t:
            return
        # Reschedule
        self._next_idle_t = now + random.uniform(IDLE_MIN_S, IDLE_MAX_S)
        # Conditions: not speaking, not touching, not in cooldown
        if self._speaking or self._touching:
            return
        # Play on a separate thread so we don't block the tick
        threading.Thread(
            target=self._play_idle, daemon=True, name="idle-sound").start()

    def _play_idle(self) -> None:
        try:
            if self._speaking:
                return
            pcm, rate = self._bank.get_sound("idle_ambient", self._mood)
            if self._speaking:
                return
            self._play_fn(pcm, rate)
        except Exception:  # noqa: BLE001
            pass

    # ── cleanup ──────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        self._stop_purr_thread()
