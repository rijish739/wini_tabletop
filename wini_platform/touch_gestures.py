"""TouchGestureRecognizer — convert raw touch levels into gestures.

Receives ~100 Hz boolean level updates from either ``SerialHead.on_head`` or
``GpioTouchReader.on_touch`` and emits high-level gesture callbacks:

    on_single_tap()          — press < 300 ms, no second tap within 400 ms
    on_double_tap()          — two < 300 ms presses within 400 ms
    on_hold_start()          — held continuously ≥ 700 ms
    on_hold_end(duration_s)  — released after a hold
    on_pat_sequence(count)   — 3+ taps within a 3 s window (count ≤ 4)

All callbacks run on the touch-reader thread and must be fast / non-blocking.
"""

from __future__ import annotations

import time
import threading
from typing import Callable, Optional


# ── tuning constants ─────────────────────────────────────────────────────────
# A "tap" is any press released BEFORE the hold threshold fires — there is no
# separate upper bound, so there's no dead zone between TAP_MAX and HOLD where a
# press produces nothing (that gap made mid-length touches feel unresponsive).
DOUBLE_TAP_WINDOW_MS = 300  # max gap between two taps for a double-tap
HOLD_THRESHOLD_MS = 600   # press duration to trigger a "hold"
PAT_WINDOW_S = 3.0        # rolling window to count repeated pats
PAT_MAX_COUNT = 4         # don't escalate excitement past this


class TouchGestureRecognizer:
    """State machine that converts boolean level edges into gesture callbacks.

    Parameters
    ----------
    on_single_tap : callable
        Called when a single short tap is confirmed (after the double-tap
        window expires without a second tap).
    on_double_tap : callable
        Called when two short taps land within the double-tap window.
    on_hold_start : callable
        Called the moment a press exceeds HOLD_THRESHOLD_MS.
    on_hold_end : callable(duration_s: float)
        Called when the finger lifts after a hold.
    on_pat_sequence : callable(count: int)
        Called on the 3rd and every subsequent tap within PAT_WINDOW_S,
        with count clamped to PAT_MAX_COUNT.
    log : callable
        Logging function (default ``print``).
    """

    def __init__(self,
                 on_single_tap: Optional[Callable[[], None]] = None,
                 on_double_tap: Optional[Callable[[], None]] = None,
                 on_hold_start: Optional[Callable[[], None]] = None,
                 on_hold_end: Optional[Callable[[float], None]] = None,
                 on_pat_sequence: Optional[Callable[[int], None]] = None,
                 log: Callable[[str], None] = print):
        self._on_single_tap = on_single_tap
        self._on_double_tap = on_double_tap
        self._on_hold_start = on_hold_start
        self._on_hold_end = on_hold_end
        self._on_pat_sequence = on_pat_sequence
        self._log = log

        # Internal state — written from the touch-reader thread only, so no
        # lock is needed (single-writer, GIL-atomic floats/bools/ints).
        self._level = False          # current raw level
        self._press_start: float = 0.0   # monotonic time of last DOWN edge
        self._holding = False        # we've already fired hold_start
        self._pending_tap = False    # a short tap is waiting for double-tap
        self._pending_tap_t: float = 0.0  # when the pending tap was released

        # Pat tracking: timestamps of recent taps within PAT_WINDOW_S.
        self._tap_times: list[float] = []

        # A timer thread to resolve the single-vs-double-tap ambiguity:
        # after the first tap we wait DOUBLE_TAP_WINDOW_MS; if no second tap
        # arrives we emit single_tap.
        self._timer: threading.Timer | None = None

    # ── public entry point ───────────────────────────────────────────────

    def on_level(self, level: bool) -> None:
        """Feed a raw touch level sample.  Call at ≥ 50 Hz for reliable
        gesture detection.  Must be called from a single thread."""
        now = time.monotonic()
        prev = self._level
        self._level = level

        if level and not prev:
            # ── DOWN edge ────────────────────────────────────────────────
            self._press_start = now
            self._holding = False

        elif not level and prev:
            # ── UP edge ──────────────────────────────────────────────────
            if self._holding:
                # End of a hold gesture
                hold_s = now - self._press_start
                self._holding = False
                self._fire(self._on_hold_end, hold_s)
                return

            # Not holding → the press was shorter than HOLD_THRESHOLD_MS, so it
            # is a tap regardless of exact duration (no TAP_MAX dead zone).
            self._register_tap(now)

        elif level and prev:
            # ── STILL PRESSED ────────────────────────────────────────────
            if not self._holding:
                elapsed_ms = (now - self._press_start) * 1000.0
                if elapsed_ms >= HOLD_THRESHOLD_MS:
                    self._holding = True
                    # Cancel any pending single-tap resolution (the long press
                    # supersedes it).
                    self._cancel_timer()
                    self._pending_tap = False
                    self._fire(self._on_hold_start)

    # ── internal ─────────────────────────────────────────────────────────

    def _register_tap(self, now: float) -> None:
        """A short tap just ended.  Decide: double-tap, pat, or queue for
        single-tap resolution."""
        # Record in the pat window
        cutoff = now - PAT_WINDOW_S
        self._tap_times = [t for t in self._tap_times if t > cutoff]
        self._tap_times.append(now)
        pat_count = len(self._tap_times)

        # Repeated patting (≥ 3 taps in the window)
        if pat_count >= 3:
            self._cancel_timer()
            self._pending_tap = False
            clamped = min(pat_count, PAT_MAX_COUNT)
            self._fire(self._on_pat_sequence, clamped)
            return

        # Double-tap check
        if self._pending_tap:
            gap_ms = (now - self._pending_tap_t) * 1000.0
            if gap_ms <= DOUBLE_TAP_WINDOW_MS:
                self._cancel_timer()
                self._pending_tap = False
                self._fire(self._on_double_tap)
                return

        # Queue as a pending tap — wait for a second tap or timeout
        self._pending_tap = True
        self._pending_tap_t = now
        self._cancel_timer()
        self._timer = threading.Timer(
            DOUBLE_TAP_WINDOW_MS / 1000.0, self._resolve_single_tap)
        self._timer.daemon = True
        self._timer.start()

    def _resolve_single_tap(self) -> None:
        """Timer callback: the double-tap window expired → emit single tap."""
        if self._pending_tap:
            self._pending_tap = False
            self._fire(self._on_single_tap)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    @staticmethod
    def _fire(callback, *args) -> None:
        if callback is not None:
            try:
                callback(*args)
            except Exception:  # noqa: BLE001 — never let a callback crash the reader
                pass
