"""Text cards for the display (loading / ready / awake / failed).

Port of jetson_platform/wini_touch_trigger.py `render()` minus the ROS bits:
returns an UN-FLIPPED 480x320 RGB uint8 array (the new display contract — the
driver owns panel orientation) instead of pre-flipped rgb8 bytes.
"""

from __future__ import annotations

import cv2
import numpy as np

W, H = 480, 320
FONT = cv2.FONT_HERSHEY_SIMPLEX

COLOR_INFO = (90, 200, 255)
COLOR_OK = (120, 230, 120)
COLOR_FAIL = (80, 80, 255)


def render_card(text: str, sub: str = "", color=COLOR_INFO) -> np.ndarray:
    canvas = np.zeros((H, W, 3), np.uint8)
    canvas[:] = (12, 12, 32)
    (tw, _), _ = cv2.getTextSize(text, FONT, 1.5, 3)
    cv2.putText(canvas, text, ((W - tw) // 2, H // 2 - 8), FONT, 1.5,
                color, 3, cv2.LINE_AA)
    if sub:
        (sw, _), _ = cv2.getTextSize(sub, FONT, 0.7, 2)
        cv2.putText(canvas, sub, ((W - sw) // 2, H // 2 + 44), FONT, 0.7,
                    (200, 200, 200), 2, cv2.LINE_AA)
    return canvas


def loading_card(dots: int) -> np.ndarray:
    """Animated 'Loading.' .. 'Loading...' — pass an incrementing tick."""
    return render_card("Loading" + "." * (1 + (dots // 3) % 3),
                       "Wini is waking up")


def ready_card() -> np.ndarray:
    return render_card("Ready!", "say something to Wini", color=COLOR_OK)


def awake_card() -> np.ndarray:
    return render_card("Wini is awake!", "", color=COLOR_OK)


def failed_card(sub: str = "check server.log") -> np.ndarray:
    return render_card("Start failed", sub, color=COLOR_FAIL)
