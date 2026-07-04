"""Display sinks — the ONE platform seam that differs per device.

The brain sends display METADATA only ({image_path, alt_text, figure_id}); the
sink resolves `image_path` against the device's own local copy of the store
(SD card on the ESP32, rag_store/ on the Jetson) and puts the picture up while
Wini speaks. Unknown/missing path => keep the face (never crash a turn).

Sinks:
    NullSink      — no display (audio-only devices / debugging)
    ConsoleSink   — prints what WOULD be shown (any platform, zero deps)
    RosDisplaySink— Jetson: publishes 480x320 rgb8 frames to /wini/display/image
                    at 5 Hz (the existing display_controll node contract,
                    JETSON_PIPELINE_RUNBOOK.md §7), pre-flipped horizontally.
                    Needs rclpy + cv2 + numpy — platform extras, imported lazily.
"""

from __future__ import annotations

import threading
from pathlib import Path


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
        try:
            import cv2
            import numpy as np

            path = self.store / rel_path
            if not path.exists():
                print(f"[display] crop missing (keeping face): {path}")
                return None
            bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if bgr is None:
                return None
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            h, w = rgb.shape[:2]
            scale = min(self.W / w, self.H / h)
            nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
            canvas = np.zeros((self.H, self.W, 3), dtype=np.uint8)
            y0, x0 = (self.H - nh) // 2, (self.W - nw) // 2
            canvas[y0:y0 + nh, x0:x0 + nw] = cv2.resize(rgb, (nw, nh),
                                                        interpolation=cv2.INTER_AREA)
            return np.ascontiguousarray(cv2.flip(canvas, 1))  # panel un-mirrors it
        except Exception as e:  # noqa: BLE001
            print(f"[display] render failed for {rel_path}: {e}")
            return None

    def _to_msg(self, frame):
        m = self._Image()
        m.height, m.width = self.H, self.W
        m.encoding = "rgb8"
        m.is_bigendian = 0
        m.step = self.W * 3
        m.data = frame.tobytes()
        return m


def make_sink(kind: str, store_dir: Path):
    if kind == "ros":
        return RosDisplaySink(store_dir)
    if kind == "console":
        return ConsoleSink()
    return NullSink()
