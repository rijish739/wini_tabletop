"""ST7796S display driver for Wini.

Single owner of all hardware access and color-pipeline transforms.
"""

import struct
import time
import threading

import numpy as np
import board
import digitalio
from adafruit_rgb_display.rgb import DisplaySPI

# ── Physical display dimensions (portrait) ──────────────────────────────────
DISPLAY_W = 320   # portrait width
DISPLAY_H = 480   # portrait height

# Render canvas dimensions (landscape — eyes render in landscape then rotate)
CANVAS_W = 480
CANVAS_H = 320

BAUDRATE = 20_000_000
FULL_REFRESH_INTERVAL_S = 1.0   # periodic full-frame refresh to clear SPI artefacts


# ── ST7796S display class ────────────────────────────────────────────────────

class ST7796S(DisplaySPI):
    _COLUMN_SET = 0x2A
    _PAGE_SET   = 0x2B
    _RAM_WRITE  = 0x2C
    _RAM_READ   = 0x2E
    # Sequenced manually in init() — the ST7796S needs ~120 ms settle after
    # SWRESET (0x01) and SLPOUT (0x11). The base class writes _INIT commands
    # back-to-back with no delay; re-initing against a busy controller (e.g.
    # right after the previous owner was killed mid-frame) then gets ignored
    # and the panel stays asleep — every write lands in display RAM invisibly
    # with no error anywhere (hit 2026-07-04 on a platform relaunch).
    _INIT = ()

    def init(self) -> None:
        for command, data, delay_s in (
            (0x01, None,    0.150),   # SW reset  → ≥120 ms settle
            (0x11, None,    0.150),   # Sleep out → ≥120 ms settle
            (0x3A, b"\x55", 0.0),     # 16-bit color
            (0x36, b"\x88", 0.0),     # MADCTL
        ):
            self.write(command, data)
            if delay_s:
                time.sleep(delay_s)
        super().init()
        cols = struct.pack(">HH", self._X_START, self.width  + self._X_START - 1)
        rows = struct.pack(">HH", self._Y_START, self.height + self._Y_START - 1)
        for command, data in (
            (0x2A, cols),
            (0x2B, rows),
            (0x20, None),
            (0x13, None),   # normal display mode
            (0x29, None),   # display on
            (0x36, b"\x88"),
        ):
            self.write(command, data)


# ── WiniDisplayDriver ────────────────────────────────────────────────────────

class WiniDisplayDriver:
    """Owns the ST7796S hardware and the full color pipeline."""

    def __init__(self):
        cs_pin    = digitalio.DigitalInOut(board.CE0)
        dc_pin    = digitalio.DigitalInOut(board.D4)
        reset_pin = digitalio.DigitalInOut(board.D22)
        spi       = board.SPI()

        self._dc_pin   = dc_pin
        self._disp     = ST7796S(
            spi, rotation=0,
            cs=cs_pin, dc=dc_pin, rst=reset_pin,
            baudrate=BAUDRATE,
            width=DISPLAY_W, height=DISPLAY_H,
        )
        self._spi_bus  = self._disp.spi_device.spi
        self._cs_pin   = self._disp.spi_device.chip_select
        self._lock     = threading.Lock()

        # Previous frame for dirty-rect diffing (portrait RGB565)
        self._prev_frame: np.ndarray = np.zeros(
            (DISPLAY_H, DISPLAY_W), dtype=np.uint16
        )
        self._first_frame         = True
        self._last_full_refresh   = 0.0

    # ── Public API ───────────────────────────────────────────────────────────

    def push_landscape(self, frame_rgb: np.ndarray) -> None:
        rgb565 = self._landscape_to_portrait_rgb565(frame_rgb)
        self._push_rgb565(rgb565)

    def push_portrait(self, frame_rgb: np.ndarray) -> None:
        rgb565 = self._to_rgb565(frame_rgb)
        self._push_rgb565(rgb565)

    def push_rect_rgb565(self, data: bytes,
                         x0: int, y0: int, x1: int, y1: int) -> None:
        """Push pre-converted RGB565 bytes to a specific display rectangle."""
        self._fast_block(data, x0, y0, x1, y1)

    def invalidate(self) -> None:
        """Force a full-frame redraw on the next push call."""
        self._first_frame = True

    # ── Color pipeline ───────────────────────────────────────────────────────

    @staticmethod
    def _to_rgb565(frame_rgb: np.ndarray) -> np.ndarray:
        inv = 255 - frame_rgb
        r = inv[:, :, 0].astype(np.uint16)
        g = inv[:, :, 1].astype(np.uint16)
        b = inv[:, :, 2].astype(np.uint16)

        rgb565 = np.empty(frame_rgb.shape[:2], dtype=np.uint16)
        np.multiply(r & 0xF8, 256, out=rgb565)          # R[15:11]
        rgb565 |= (g & 0xFC) << 3                       # G[10:5]
        rgb565 |= b >> 3                                 # B[4:0]
        rgb565.byteswap(inplace=True)
        return rgb565

    @staticmethod
    def _landscape_to_portrait_rgb565(frame_rgb: np.ndarray) -> np.ndarray:
        import cv2
        portrait = cv2.rotate(frame_rgb, cv2.ROTATE_90_CLOCKWISE)
        cv2.flip(portrait, 1, dst=portrait)
        return WiniDisplayDriver._to_rgb565(portrait)

    # ── Dirty-rect push ──────────────────────────────────────────────────────

    def _push_rgb565(self, frame: np.ndarray) -> None:
        now = time.time()
        needs_full = (
            self._first_frame
            or (now - self._last_full_refresh) >= FULL_REFRESH_INTERVAL_S
        )

        if needs_full:
            self._fast_block(frame.tobytes())
            self._first_frame = False
            self._last_full_refresh = now
        else:
            row_changed = np.any(frame != self._prev_frame, axis=1)
            if row_changed.any():
                col_changed = np.any(frame != self._prev_frame, axis=0)
                y0 = int(np.argmax(row_changed))
                y1 = int(len(row_changed) - 1 - np.argmax(row_changed[::-1]))
                x0 = int(np.argmax(col_changed))
                x1 = int(len(col_changed) - 1 - np.argmax(col_changed[::-1]))
                self._fast_block(
                    frame[y0:y1 + 1, x0:x1 + 1].tobytes(), x0, y0, x1, y1
                )

        np.copyto(self._prev_frame, frame)

    # ── Raw SPI write ────────────────────────────────────────────────────────

    def _fast_block(self, data: bytes,
                    x0: int = 0, y0: int = 0,
                    x1: int = DISPLAY_W - 1, y1: int = DISPLAY_H - 1) -> None:
        caset = struct.pack('>HH', x0, x1)
        raset = struct.pack('>HH', y0, y1)
        with self._lock:
            while not self._spi_bus.try_lock():
                pass
            try:
                self._spi_bus.configure(baudrate=BAUDRATE, polarity=0, phase=0)
                self._cs_pin.value = False
                self._dc_pin.value = False
                self._spi_bus.write(bytearray([0x2A]))
                self._dc_pin.value = True
                self._spi_bus.write(caset)
                self._dc_pin.value = False
                self._spi_bus.write(bytearray([0x2B]))
                self._dc_pin.value = True
                self._spi_bus.write(raset)
                self._dc_pin.value = False
                self._spi_bus.write(bytearray([0x2C]))
                self._dc_pin.value = True
                self._spi_bus.write(data)
                self._cs_pin.value = True
            finally:
                self._spi_bus.unlock()
