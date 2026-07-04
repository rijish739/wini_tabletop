"""Stage 1 acceptance demo — face + emotions + overlays, no ROS anywhere.

Run on the Jetson (stop the old ROS display node first — one panel owner):
    cd ~/wini/core && python3 -m wini_platform.display.demo

Sequence: face idle -> emotion cycle -> gaze sweep -> orientation/calibration
card (must render upright, per the plan's Stage 1 test) -> loading card
animation -> figure-crop overlay (first crop found under rag_store/) -> face.

--fake uses a NullDriver (no SPI hardware; development machines).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2
import numpy as np

from .display_thread import DisplayThread, NullDriver, CANVAS_W, CANVAS_H
from .. import ui_cards

EMOTIONS = ["NEUTRAL", "HAPPY", "SURPRISED", "CONFUSED", "SAD", "ANGRY",
            "TIRED", "BLUSH", "LOVE", "EXCITEMENT", "SMIRK", "DIZZY", "XEYES"]


def calibration_card() -> np.ndarray:
    """Orientation card: labeled corners + arrow up. If any label reads
    mirrored or the arrow is not up, the panel pipeline is wrong."""
    c = np.zeros((CANVAS_H, CANVAS_W, 3), np.uint8)
    c[:] = (12, 32, 12)
    f = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(c, "TL", (8, 28), f, 0.9, (90, 200, 255), 2, cv2.LINE_AA)
    cv2.putText(c, "TR", (CANVAS_W - 52, 28), f, 0.9, (90, 200, 255), 2, cv2.LINE_AA)
    cv2.putText(c, "BL", (8, CANVAS_H - 10), f, 0.9, (90, 200, 255), 2, cv2.LINE_AA)
    cv2.putText(c, "BR", (CANVAS_W - 52, CANVAS_H - 10), f, 0.9, (90, 200, 255), 2, cv2.LINE_AA)
    cv2.putText(c, "WINI CAL", (CANVAS_W // 2 - 90, CANVAS_H // 2 + 10), f, 1.2,
                (255, 255, 255), 3, cv2.LINE_AA)
    cv2.arrowedLine(c, (CANVAS_W // 2, CANVAS_H - 40), (CANVAS_W // 2, 60),
                    (120, 230, 120), 3, tipLength=0.2)
    return c


def find_figure_crop(store: Path) -> np.ndarray | None:
    crops = store / "figure_crops"
    if not crops.is_dir():
        return None
    for p in sorted(crops.rglob("*.png")) + sorted(crops.rglob("*.jpg")):
        bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        scale = min(CANVAS_W / w, CANVAS_H / h)
        nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        canvas = np.zeros((CANVAS_H, CANVAS_W, 3), np.uint8)
        y0, x0 = (CANVAS_H - nh) // 2, (CANVAS_W - nw) // 2
        canvas[y0:y0 + nh, x0:x0 + nw] = cv2.resize(
            rgb, (nw, nh), interpolation=cv2.INTER_AREA)
        print(f"[demo] figure crop: {p}")
        return canvas
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 1 display demo (no ROS)")
    ap.add_argument("--fake", action="store_true",
                    help="NullDriver — run without the SPI panel")
    ap.add_argument("--store", default=str(
        Path(__file__).resolve().parents[2] / "rag_store"))
    ap.add_argument("--dwell", type=float, default=1.5,
                    help="seconds per emotion / overlay phase")
    args = ap.parse_args()

    display = DisplayThread(driver=NullDriver() if args.fake else None)
    display.start()
    d = args.dwell
    try:
        print("[demo] face idle")
        time.sleep(d)

        for emo in EMOTIONS:
            print(f"[demo] emotion {emo}")
            display.set_emotion(emo, 12)
            time.sleep(d)
        display.set_emotion("NEUTRAL", 15)

        print("[demo] gaze sweep")
        for gx in (-0.8, 0.0, 0.8, 0.0):
            display.set_gaze(gx, -0.4)
            time.sleep(d / 2)
        display.set_gaze(0.0, 0.0)

        print("[demo] calibration card (check: corners read TL/TR/BL/BR, arrow UP)")
        display.show_overlay(calibration_card())
        time.sleep(max(d * 2, 4.0))

        print("[demo] loading card animation")
        t0 = time.monotonic()
        dots = 0
        while time.monotonic() - t0 < max(d * 2, 3.0):
            display.show_overlay(ui_cards.loading_card(dots))
            dots += 1
            time.sleep(0.2)

        crop = find_figure_crop(Path(args.store))
        if crop is not None:
            print("[demo] figure-crop overlay (timeout 3 s -> auto-revert to face)")
            display.show_overlay(crop, timeout_s=3.0)
            time.sleep(4.0)
        else:
            print(f"[demo] no figure crops under {args.store}; skipping")
            display.clear_overlay()

        print("[demo] back to face; done")
        time.sleep(d)
    finally:
        display.stop()
        if args.fake:
            drv = display._driver
            print(f"[demo] NullDriver rendered {drv.frames} frames")


if __name__ == "__main__":
    main()
