"""DisplayThread — single owner of the ST7796S panel (30 fps render loop).

ROS-less port of the wini_display node (device_snapshot/display_controll/
wini_display.py): the render loop, face style, and overlay-timeout logic are
kept; the Node class and its three subscriptions become plain thread-safe
setters. This deletes the whole image-topic contract — no >2 Hz keepalive, no
rgb8/size validation, and overlays are composed UN-FLIPPED (the driver owns
panel orientation; senders no longer pre-flip).

Every other thread talks to the panel only through this object:

    display.set_emotion("HAPPY", 12)
    display.set_gaze(gx, gy)          # gx/gy in -1..1 directly (the old
                                      # /wini/eyes_target ×1500 projection
                                      # hack is gone)
    display.show_overlay(rgb_array, timeout_s=2.5)   # figure crop / text card
    display.clear_overlay()           # back to the face
"""

from __future__ import annotations

import threading
import time

import numpy as np

from .wini_face import WiniFace

# Must match display/wini_display_driver.py (not imported from there — that
# module needs the Blinka `board` package, which only exists on the device).
CANVAS_W = 480   # landscape render width
CANVAS_H = 320   # landscape render height

FRAME_PERIOD_S = 1.0 / 30.0     # main render loop target (30 fps)

# Face style carried over verbatim from the ROS display node's main().
FACE_STYLE = dict(
    style_name='linear',
    color1=(255, 255, 255),
    color2=(255, 255, 255),
    size_x=170,
    size_y=190,
    separation=40,
    pos_y=-50,
    pupil_size=0.8,
    iris_size=0.9,
    iris_style='radial',
    iris_color2=(250, 244, 187),   # outer cream
    iris_color=(240, 234, 177),    # inner dark amber
    gaze_offset_y=0.7,
    blink_rate=1.0,
)

DEFAULT_EMOTION = 'NEUTRAL'
DEFAULT_INTENSITY = 15
DEFAULT_GAZE = (0.0, 0.0, 0.4)


class NullDriver:
    """Drop-in for WiniDisplayDriver on machines without the SPI panel
    (development / CI). Keeps the last frame for inspection."""

    def __init__(self):
        self.last_frame = None
        self.frames = 0

    def push_landscape(self, frame_rgb: np.ndarray) -> None:
        self.last_frame = frame_rgb
        self.frames += 1

    def invalidate(self) -> None:
        pass


class DisplayThread(threading.Thread):
    def __init__(self, driver=None):
        super().__init__(name='wini-display', daemon=True)
        if driver is None:
            from .wini_display_driver import WiniDisplayDriver
            driver = WiniDisplayDriver()
        self._driver = driver
        self._face = WiniFace(width=CANVAS_W, height=CANVAS_H)
        self._face.set_style(**FACE_STYLE)

        self._lock = threading.Lock()
        self._emotion = DEFAULT_EMOTION
        self._intensity = DEFAULT_INTENSITY
        self._gaze = DEFAULT_GAZE
        self._overlay: np.ndarray | None = None
        self._overlay_until: float | None = None
        self._stop_evt = threading.Event()

        self._face.set_emotion(self._emotion, self._intensity)
        self._face.set_gaze(*self._gaze)

    # ── API (called from any thread) ─────────────────────────────────────────

    def set_emotion(self, name: str, intensity: int | None = None) -> None:
        with self._lock:
            self._emotion = str(name).strip().upper()
            if intensity is not None:
                self._intensity = int(intensity)

    def get_emotion(self) -> tuple[str, int]:
        with self._lock:
            return self._emotion, self._intensity

    def set_gaze(self, gx: float, gy: float, z: float | None = None) -> None:
        """Gaze direction in -1..1 (y negative = up); z = pupil depth 0.1..1.0
        (kept from the old node's projected value; None keeps the current z)."""
        with self._lock:
            if z is None:
                z = self._gaze[2]
            self._gaze = (
                float(np.clip(gx, -1.0, 1.0)),
                float(np.clip(gy, -1.0, 1.0)),
                float(np.clip(z, 0.1, 1.0)),
            )

    def show_overlay(self, frame_rgb: np.ndarray,
                     timeout_s: float | None = None) -> None:
        """Replace the face with a full-canvas RGB image (figure crop, text
        card). Shown until clear_overlay()/replacement, or for timeout_s.

        Callers compose UN-flipped; the horizontal pre-flip for the mirrored
        panel (runbook §7.2 — the glass mirrors left-right, the face never
        showed it because eyes are near-symmetric) happens here, in exactly
        one place, instead of in every sender as under ROS."""
        if frame_rgb is None:
            return self.clear_overlay()
        frame_rgb = np.asarray(frame_rgb, dtype=np.uint8)
        if frame_rgb.shape != (CANVAS_H, CANVAS_W, 3):
            raise ValueError(
                f'overlay must be {CANVAS_H}x{CANVAS_W}x3 rgb, got {frame_rgb.shape}')
        frame_rgb = np.ascontiguousarray(frame_rgb[:, ::-1])   # panel un-mirrors it
        with self._lock:
            self._overlay = frame_rgb
            self._overlay_until = (
                None if timeout_s is None else time.monotonic() + timeout_s)

    def clear_overlay(self) -> None:
        with self._lock:
            self._overlay = None
            self._overlay_until = None

    def stop(self, join: bool = True) -> None:
        self._stop_evt.set()
        if join and self.is_alive():
            self.join(timeout=2.0)

    # ── render loop ──────────────────────────────────────────────────────────

    def run(self) -> None:
        last_frame_time = time.monotonic()
        while not self._stop_evt.is_set():
            now = time.monotonic()
            with self._lock:
                if self._overlay_until is not None and now >= self._overlay_until:
                    self._overlay = None
                    self._overlay_until = None
                overlay = self._overlay
                emotion, intensity = self._emotion, self._intensity
                gaze = self._gaze

            if overlay is not None:
                self._driver.push_landscape(overlay)
            else:
                self._face.set_emotion(emotion, intensity)
                self._face.set_gaze(*gaze)
                self._face.update()
                self._driver.push_landscape(self._face.render())

            elapsed = time.monotonic() - last_frame_time
            sleep_time = FRAME_PERIOD_S - elapsed
            if sleep_time > 0.001:
                time.sleep(sleep_time)
            last_frame_time = time.monotonic()
