"""EmotionEngine — lightweight emotional state machine for Wini.

Maps touch gestures to emotional states, tracks a continuous mood value,
and triggers appropriate sounds through the AudioManager.

States
------
IDLE → CURIOUS → HAPPY → CONTENT → EXCITED → SLEEPY → OVERSTIMULATED

Mood (0–100) determines sound expressiveness and decays over time.  State
transitions are driven by gesture callbacks and by time-based decay rules
checked in ``tick()``.
"""

from __future__ import annotations

import random
import time
from enum import Enum, auto
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from wini_client.audio_manager import AudioManager


class State(Enum):
    IDLE = auto()
    CURIOUS = auto()
    HAPPY = auto()
    CONTENT = auto()
    EXCITED = auto()
    SLEEPY = auto()
    OVERSTIMULATED = auto()


# ── tuning ───────────────────────────────────────────────────────────────────
MOOD_DECAY_PER_SECOND = 1.0 / 60.0   # -1 per minute
OVERSTIM_TOUCH_THRESHOLD = 8          # touches in 10 s → overstimulated
OVERSTIM_WINDOW_S = 10.0
OVERSTIM_COOLDOWN_S = 5.0

# State decay: seconds of no interaction before transitioning downward.
_DECAY_TABLE = {
    State.EXCITED:  30.0,    # → HAPPY
    State.HAPPY:    60.0,    # → CONTENT
    State.CONTENT:  120.0,   # → IDLE
    State.CURIOUS:  60.0,    # → IDLE
    State.IDLE:     300.0,   # → SLEEPY  (5 min)
}

# Gesture → state transitions (from_state → to_state)
# If the current state isn't listed, the gesture still updates mood but
# doesn't change state (unless it's a tap waking from SLEEPY).
_TAP_TRANSITIONS = {
    State.IDLE:    State.CURIOUS,
    State.SLEEPY:  State.CURIOUS,
}

_DOUBLE_TAP_TRANSITIONS = {
    State.IDLE:    State.HAPPY,
    State.CURIOUS: State.HAPPY,
    State.SLEEPY:  State.HAPPY,
}

# Gesture → sound family (used when no state-specific override applies)
_DEFAULT_SOUNDS = {
    "single_tap":  "acknowledge",
    "double_tap":  "happy",
    "hold_start":  None,        # handled by purr
    "hold_end":    None,        # handled by satisfied via AudioManager.stop_purr
    "pat":         None,        # escalating sequence below
}

# State → candidate sound families for single taps.  A *list*, not one family:
# picking from a small set per state is what stops the cat sounding like a
# doorbell.  Weights are positional — the first entry is the typical response,
# the rest are occasional flavour.
_TAP_SOUNDS_BY_STATE = {
    State.IDLE:          [("acknowledge", 0.55), ("trill", 0.30), ("chirp", 0.15)],
    State.CURIOUS:       [("curious", 0.55), ("trill", 0.25), ("chirp", 0.20)],
    State.HAPPY:         [("happy", 0.60), ("trill", 0.25), ("chirp", 0.15)],
    State.CONTENT:       [("content", 0.65), ("satisfied", 0.25), ("trill", 0.10)],
    State.EXCITED:       [("excited", 0.45), ("chirp", 0.35), ("happy", 0.20)],
    State.SLEEPY:        [("sleepy", 0.75), ("content", 0.25)],
    State.OVERSTIMULATED: [("overstimulated", 1.0)],
}

# Escalating pat sequence sounds — greeting trill → question → meow → chatter
_PAT_ESCALATION = ["trill", "curious", "happy", "excited"]

# Double tap: an excited cat repeats itself, so vary the greeting.
_DOUBLE_TAP_SOUNDS = [("happy", 0.50), ("chirp", 0.30), ("trill", 0.20)]


def _weighted_pick(choices: list[tuple[str, float]]) -> str:
    """Pick one family name from ``[(name, weight), ...]``."""
    names = [c[0] for c in choices]
    weights = [c[1] for c in choices]
    return random.choices(names, weights=weights, k=1)[0]


class EmotionEngine:
    """Wires touch gestures → emotional state → sound playback.

    Parameters
    ----------
    audio_manager : AudioManager
        The centralized audio gatekeeper.
    log : callable
        Logging function.
    """

    def __init__(self,
                 audio_manager: "AudioManager",
                 log: Callable[[str], None] = print):
        self._am = audio_manager
        self._log = log

        self._state = State.IDLE
        self._mood: float = 50.0
        self._last_interaction_t: float = time.monotonic()
        self._state_entered_t: float = time.monotonic()

        # Overstimulation tracking
        self._touch_times: list[float] = []

    # ── read-only ────────────────────────────────────────────────────────

    @property
    def state(self) -> State:
        return self._state

    @property
    def mood(self) -> float:
        return self._mood

    # ── gesture callbacks (called from touch gesture recognizer) ─────────

    def on_single_tap(self) -> None:
        self._record_touch()
        if self._check_overstim():
            return
        # State transition
        new_state = _TAP_TRANSITIONS.get(self._state)
        if new_state:
            self._transition(new_state)
        self._mood = min(100.0, self._mood + 2)
        self._am.set_mood(self._mood)
        # Sound
        choices = _TAP_SOUNDS_BY_STATE.get(self._state)
        family = _weighted_pick(choices) if choices else "acknowledge"
        self._am.play_emotion(family)
        self._log(f"[emotion] tap → {self._state.name} "
                  f"({family}) mood={self._mood:.0f}")

    def on_double_tap(self) -> None:
        self._record_touch()
        self._record_touch()   # counts as 2 touches
        if self._check_overstim():
            return
        new_state = _DOUBLE_TAP_TRANSITIONS.get(self._state)
        if new_state:
            self._transition(new_state)
        self._mood = min(100.0, self._mood + 5)
        self._am.set_mood(self._mood)
        family = _weighted_pick(_DOUBLE_TAP_SOUNDS)
        self._am.play_emotion(family)
        self._log(f"[emotion] double tap → {self._state.name} "
                  f"({family}) mood={self._mood:.0f}")

    def on_hold_start(self) -> None:
        self._record_touch()
        if self._check_overstim():
            return
        self._am.set_touching(True)
        self._am.start_purr()
        self._log(f"[emotion] hold start (purr)")

    def on_hold_end(self, duration_s: float) -> None:
        self._am.set_touching(False)
        self._am.stop_purr()       # plays satisfied sound
        self._mood = min(100.0, self._mood + 10)
        self._am.set_mood(self._mood)
        # Long holds can boost to CONTENT
        if self._state in (State.IDLE, State.CURIOUS, State.SLEEPY):
            self._transition(State.CONTENT)
        self._log(f"[emotion] hold end ({duration_s:.1f}s) → "
                  f"{self._state.name} mood={self._mood:.0f}")

    def on_pat_sequence(self, count: int) -> None:
        self._record_touch()
        if self._check_overstim():
            return
        # Escalating sounds
        idx = min(count - 1, len(_PAT_ESCALATION) - 1)
        family = _PAT_ESCALATION[idx]
        self._am.play_emotion(family)
        # 3+ pats → EXCITED
        if count >= 3 and self._state in (
                State.IDLE, State.CURIOUS, State.HAPPY, State.CONTENT):
            self._transition(State.EXCITED)
        self._mood = min(100.0, self._mood + 3)
        self._am.set_mood(self._mood)
        self._log(f"[emotion] pat x{count} → {self._state.name} mood={self._mood:.0f}")

    # ── tick (called from supervisor every TICK_S ≈ 0.2 s) ───────────────

    def tick(self, dt_s: float) -> None:
        """Update mood decay, state decay, idle-sound scheduling."""
        now = time.monotonic()

        # Mood decay
        self._mood = max(0.0, self._mood - MOOD_DECAY_PER_SECOND * dt_s)
        self._am.set_mood(self._mood)

        # State decay: if enough time has passed without interaction,
        # transition downward.
        idle_s = now - self._last_interaction_t
        in_state_s = now - self._state_entered_t
        decay_threshold = _DECAY_TABLE.get(self._state)

        if decay_threshold is not None and in_state_s >= decay_threshold:
            if self._state == State.EXCITED:
                self._transition(State.HAPPY)
            elif self._state == State.HAPPY:
                self._transition(State.CONTENT)
            elif self._state == State.CONTENT:
                self._transition(State.IDLE)
            elif self._state == State.CURIOUS:
                self._transition(State.IDLE)
            elif self._state == State.IDLE and idle_s >= _DECAY_TABLE[State.IDLE]:
                self._transition(State.SLEEPY)

        # Overstimulated auto-recovery
        if self._state == State.OVERSTIMULATED:
            if in_state_s >= OVERSTIM_COOLDOWN_S:
                self._transition(State.IDLE)

        # AudioManager idle tick (ambient sounds)
        self._am.tick()

    # ── internal helpers ─────────────────────────────────────────────────

    def _transition(self, new_state: State) -> None:
        if new_state != self._state:
            self._state = new_state
            self._state_entered_t = time.monotonic()

    def _record_touch(self) -> None:
        now = time.monotonic()
        self._last_interaction_t = now
        cutoff = now - OVERSTIM_WINDOW_S
        self._touch_times = [t for t in self._touch_times if t > cutoff]
        self._touch_times.append(now)

    def _check_overstim(self) -> bool:
        """Return True if we should suppress this gesture (overstimulated)."""
        if self._state == State.OVERSTIMULATED:
            return True
        if len(self._touch_times) >= OVERSTIM_TOUCH_THRESHOLD:
            self._transition(State.OVERSTIMULATED)
            self._am.play_emotion("overstimulated")
            self._log("[emotion] OVERSTIMULATED — ignoring touches for "
                      f"{OVERSTIM_COOLDOWN_S:.0f}s")
            return True
        return False
