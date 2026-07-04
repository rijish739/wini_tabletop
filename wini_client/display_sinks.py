"""Display sinks — the ONE platform seam that differs per device.

The brain sends display METADATA only ({image_path, alt_text, figure_id}); the
sink resolves `image_path` against the device's own local copy of the store
(SD card on the ESP32, rag_store/ on the Jetson) and puts the picture up while
Wini speaks. Unknown/missing path => keep the face (never crash a turn).

Sinks:
    NullSink      — no display (audio-only devices / debugging)
    ConsoleSink   — prints what WOULD be shown (any platform, zero deps)
    RosDisplaySink— Jetson (legacy ROS stack): publishes 480x320 rgb8 frames to
                    /wini/display/image at 5 Hz (the display_controll node
                    contract, JETSON_PIPELINE_RUNBOOK.md §7), pre-flipped
                    horizontally. Needs rclpy + cv2 + numpy, imported lazily.
    InProcSink    — ROS-less platform (WINI_ROSLESS_PLATFORM_PLAN.md): hands the
                    rendered frame straight to the in-process DisplayThread —
                    no keepalive, no pre-flip (the driver owns orientation).
"""

from __future__ import annotations

import threading
from pathlib import Path


def render_crop(store_dir: Path, rel_path: str, w: int, h: int,
                flip: bool = False):
    """Load a figure crop from the local store and letterbox it to w×h RGB.
    Returns a numpy array or None (missing/unreadable => caller keeps the face).
    flip=True pre-flips horizontally (legacy ROS display-node contract only)."""
    try:
        import cv2
        import numpy as np

        path = Path(store_dir) / rel_path
        if not path.exists():
            print(f"[display] crop missing (keeping face): {path}")
            return None
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            return None
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        ih, iw = rgb.shape[:2]
        scale = min(w / iw, h / ih)
        nw, nh = max(1, int(round(iw * scale))), max(1, int(round(ih * scale)))
        canvas = np.zeros((h, w, 3), dtype=np.uint8)
        y0, x0 = (h - nh) // 2, (w - nw) // 2
        canvas[y0:y0 + nh, x0:x0 + nw] = cv2.resize(rgb, (nw, nh),
                                                    interpolation=cv2.INTER_AREA)
        if flip:
            canvas = cv2.flip(canvas, 1)
        return np.ascontiguousarray(canvas)
    except Exception as e:  # noqa: BLE001
        print(f"[display] render failed for {rel_path}: {e}")
        return None


class NullSink:
    def show(self, item: dict) -> None:  # noqa: ARG002
        pass

    def clear(self) -> None:
        pass

    def thinking(self, active: bool) -> None:  # noqa: ARG002
        pass


class ConsoleSink:
    def show(self, item: dict) -> None:
        print(f"[display] SHOW {item.get('image_path')} — {item.get('alt_text', '')[:80]}")

    def clear(self) -> None:
        print("[display] CLEAR (back to face)")

    def thinking(self, active: bool) -> None:
        print(f"[display] THINKING {'on' if active else 'off'}")


class RosDisplaySink:
    """Jetson SPI panel via the existing display_controll node.

    Contract (§7): 480x320 landscape rgb8, keepalive > 2 Hz (node reverts to the
    face 0.5 s after frames stop), horizontal pre-flip on the SENDING side (the
    physical panel mirrors left-right).
    """

    W, H = 480, 320
    KEEPALIVE_S = 0.15  # aim ~5 Hz net of publish overhead (contract: > 2 Hz)

    def __init__(self, store_dir: Path):
        import rclpy
        from rclpy.node import Node  # noqa: F401  (type import)
        from sensor_msgs.msg import Image

        from std_msgs.msg import Bool

        self._Image = Image
        self._Bool = Bool
        self.store = Path(store_dir)
        if not rclpy.ok():
            rclpy.init()
        self._node = rclpy.create_node("wini_client_display")
        self._pub = self._node.create_publisher(Image, "/wini/display/image", 10)
        # Turn-phase signal: the platform side (wini_touch_trigger.py) renders a
        # "thinking" face while True and restores the prior emotion on False.
        self._think_pub = self._node.create_publisher(Bool, "/wini/thinking", 10)
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        # Pure publisher — no spin needed; a plain thread keeps the frame alive.
        threading.Thread(target=self._keepalive, daemon=True).start()

    def _keepalive(self):
        while not self._stop.wait(self.KEEPALIVE_S):
            with self._lock:
                msg = self._frame
            if msg is None:
                continue
            try:
                self._pub.publish(msg)
            except Exception as e:  # noqa: BLE001 — keepalive must never die
                print(f"[display] publish failed: {e}")

    def show(self, item: dict) -> None:
        rel = (item or {}).get("image_path")
        if not rel:
            return self.clear()
        frame = self._render(rel)
        # build the ROS message ONCE per figure; the keepalive republishes it
        msg = self._to_msg(frame) if frame is not None else None
        with self._lock:
            self._frame = msg
        if msg is not None:
            print(f"[display] showing {rel}")

    def clear(self) -> None:
        with self._lock:
            self._frame = None

    def thinking(self, active: bool) -> None:
        try:
            m = self._Bool()
            m.data = bool(active)
            self._think_pub.publish(m)
        except Exception as e:  # noqa: BLE001 — a face cue must never cost a turn
            print(f"[display] thinking signal failed: {e}")

    def _render(self, rel_path: str):
        # flip=True: legacy contract — the ROS display node un-mirrors it.
        return render_crop(self.store, rel_path, self.W, self.H, flip=True)

    def _to_msg(self, frame):
        m = self._Image()
        m.height, m.width = self.H, self.W
        m.encoding = "rgb8"
        m.is_bigendian = 0
        m.step = self.W * 3
        m.data = frame.tobytes()
        return m


class InProcSink:
    """ROS-less platform sink: same metadata contract as RosDisplaySink
    (`image_path` = SD-card image ID resolved against the local store — the
    ESP32 contract is unchanged), but the rendered frame goes straight to the
    in-process DisplayThread. No keepalive thread, no pre-flip.

    `display` is a wini_platform DisplayThread (show_overlay/clear_overlay);
    `set_thinking` is the platform's thinking-face hook (may be None).
    """

    W, H = 480, 320

    def __init__(self, store_dir: Path, display, set_thinking=None):
        self.store = Path(store_dir)
        self._display = display
        self._set_thinking = set_thinking

    def show(self, item: dict) -> None:
        rel = (item or {}).get("image_path")
        if not rel:
            return self.clear()
        frame = render_crop(self.store, rel, self.W, self.H)
        if frame is None:
            return  # keep whatever is on screen — never crash a turn
        self._display.show_overlay(frame)
        print(f"[display] showing {rel}")

    def clear(self) -> None:
        self._display.clear_overlay()

    def thinking(self, active: bool) -> None:
        if self._set_thinking is None:
            return
        try:
            self._set_thinking(bool(active))
        except Exception as e:  # noqa: BLE001 — a face cue must never cost a turn
            print(f"[display] thinking signal failed: {e}")


def make_sink(kind: str, store_dir: Path):
    if kind == "ros":
        return RosDisplaySink(store_dir)
    if kind == "console":
        return ConsoleSink()
    return NullSink()
