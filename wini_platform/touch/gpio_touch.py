"""GpioTouchReader — poll a GPIO pin for touch state at ~100 Hz.

Drop-in alternative to SerialHead's on_head callback for setups where the
touch sensor is wired directly to a Raspberry Pi GPIO pin (no STM32 head
board).  Uses ``lgpio`` which is the recommended GPIO library for the Pi 5
(RPi.GPIO does not support the RP1 chip; gpiod is an alternative but lgpio
is already installed system-wide on Raspberry Pi OS).

Usage::

    reader = GpioTouchReader(gpio_pin=22, chip=4, on_touch=my_callback)
    reader.start()          # spawns the polling thread
    ...
    reader.shutdown()       # stops the thread, releases the GPIO claim
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional


class GpioTouchReader:
    """Poll a single GPIO pin and deliver boolean level callbacks.

    Parameters
    ----------
    gpio_pin : int
        BCM GPIO number (default 22 — physical pin 15).
    chip : int
        gpiochip number.  Pi 5 uses ``/dev/gpiochip4``.
    on_touch : callable(bool) | None
        Called at ~100 Hz with the current pin level (True = touched).
        Must be fast and non-blocking (runs on the polling thread).
    poll_hz : float
        Polling frequency in Hz (default 100).
    log : callable
        Logging function (default ``print``).
    """

    def __init__(self,
                 gpio_pin: int = 22,
                 chip: int = 4,
                 on_touch: Optional[Callable[[bool], None]] = None,
                 poll_hz: float = 100.0,
                 log: Callable[[str], None] = print):
        self._pin = gpio_pin
        self._chip_num = chip
        self._on_touch = on_touch
        self._interval = 1.0 / poll_hz
        self._log = log

        self._handle: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._connected = False

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Open the GPIO chip, claim the pin, and start the polling thread."""
        self._stop.clear()
        try:
            import lgpio
            self._handle = lgpio.gpiochip_open(self._chip_num)
            lgpio.gpio_claim_input(self._handle, self._pin)
            self._connected = True
            self._log(f"[gpio_touch] opened gpiochip{self._chip_num}, "
                      f"claimed GPIO{self._pin} as input")
        except Exception as e:  # noqa: BLE001
            self._log(f"[gpio_touch] failed to open GPIO{self._pin}: {e}")
            self._connected = False
            return

        self._thread = threading.Thread(
            target=self._poll_loop, name="gpio-touch-poll", daemon=True)
        self._thread.start()

    @property
    def connected(self) -> bool:
        return self._connected

    def shutdown(self) -> None:
        """Stop the polling thread and release the GPIO claim."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._handle is not None:
            try:
                import lgpio
                lgpio.gpiochip_close(self._handle)
            except Exception:  # noqa: BLE001
                pass
            self._handle = None
        self._connected = False

    # ── polling ──────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        import lgpio

        handle = self._handle
        pin = self._pin
        callback = self._on_touch
        interval = self._interval

        while not self._stop.is_set():
            try:
                level = bool(lgpio.gpio_read(handle, pin))
                if callback is not None:
                    callback(level)
            except Exception as e:  # noqa: BLE001
                self._log(f"[gpio_touch] read error: {e}")
                self._connected = False
                # Back off on errors (device gone, permission, etc.)
                if not self._stop.wait(1.0):
                    # Try to re-read — if the chip is still open it may recover
                    try:
                        lgpio.gpio_read(handle, pin)
                        self._connected = True
                    except Exception:  # noqa: BLE001
                        break
                continue
            self._stop.wait(interval)
