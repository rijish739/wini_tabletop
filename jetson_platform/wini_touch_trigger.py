#!/usr/bin/env python3
"""Chin-hold -> start the Wini thin-client cloud pipeline.

Subscribes to /wini/head/touch_chin (Bool level telemetry, ~100 Hz from
wini_head_node). When the chin is held >= HOLD_S seconds continuously
(RELEASE_GRACE_S tolerates micro-blips), it:

  1. Server AND client running -> flashes "Wini is awake!" (never restarts).
  2. Server warm but client asleep (it exits on the "bye" farewell,
     --on-session-end exit) -> relaunches JUST the client (~seconds), showing
     "Waking up..." until the client is listening again.
  3. Nothing running -> full `bash ~/run_thin.sh` cold start, publishing
     "Loading..." frames to /wini/display/image (480x320 rgb8, pre-flipped for
     the mirrored panel) until http://127.0.0.1:8123/health says ready (~40 s),
     then "Ready!" for 2 s and the display returns to the face.

Re-arms only after the chin is released, so a long hold fires exactly once.
Designed to run at boot alongside wini_head_node and the display node.
"""
import json
import subprocess
import threading
import time
import urllib.request

import cv2
import numpy as np
import rclpy
from geometry_msgs.msg import Point
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, String

HOLD_S = 3.0             # chin hold needed to trigger
RELEASE_GRACE_S = 0.3    # micro-release shorter than this doesn't reset the hold
THINK_EMOTION = "CONFUSED 8"   # quizzical squint; intensity <= 10 avoids the tongue
THINK_TIMEOUT_S = 120.0        # safety: never stay in thinking face forever
GAZE_SWING_TICKS = 8           # 0.2 s ticks per gaze side (~1.6 s left/right)
HEALTH_URL = "http://127.0.0.1:8123/health"
RUN_THIN = "/home/roavai/run_thin.sh"
RUN_CLIENT = "/home/roavai/run_client.sh"
STARTUP_TIMEOUT_S = 180.0
WAKE_TIMEOUT_S = 30.0
W, H = 480, 320
FONT = cv2.FONT_HERSHEY_SIMPLEX


def render(text, sub="", color=(90, 200, 255)):
    canvas = np.zeros((H, W, 3), np.uint8)
    canvas[:] = (12, 12, 32)
    (tw, _), _ = cv2.getTextSize(text, FONT, 1.5, 3)
    cv2.putText(canvas, text, ((W - tw) // 2, H // 2 - 8), FONT, 1.5,
                color, 3, cv2.LINE_AA)
    if sub:
        (sw, _), _ = cv2.getTextSize(sub, FONT, 0.7, 2)
        cv2.putText(canvas, sub, ((W - sw) // 2, H // 2 + 44), FONT, 0.7,
                    (200, 200, 200), 2, cv2.LINE_AA)
    return np.ascontiguousarray(cv2.flip(canvas, 1)).tobytes()


def server_running() -> bool:
    return subprocess.run(
        ["pgrep", "-f", "wini_server[.]py"], capture_output=True).returncode == 0


def client_running() -> bool:
    return subprocess.run(
        ["pgrep", "-f", "wini_client[.]client"], capture_output=True).returncode == 0


def health_ready() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=1.0) as r:
            return bool(json.load(r).get("ready"))
    except Exception:  # noqa: BLE001
        return False


def gaze_point(gx: float, gy: float) -> Point:
    """Map a desired gaze (-1..1, y negative = up) to the display node's
    /wini/eyes_target projection: gaze = clip(coord / (z + 0.001) * 1.5) with
    z=0, i.e. coord * 1500 — and z=0 keeps the pupil at its normal size."""
    return Point(x=gx / 1500.0, y=gy / 1500.0, z=0.0)


class TouchTrigger(Node):
    def __init__(self):
        super().__init__("wini_touch_trigger")
        self._pub = self.create_publisher(Image, "/wini/display/image", 10)
        self._msg = Image()
        self._msg.height, self._msg.width = H, W
        self._msg.encoding = "rgb8"
        self._msg.is_bigendian = 0
        self._msg.step = W * 3

        self._hold_start = None    # when the current chin hold began
        self._last_true = 0.0      # last time we saw touch=True
        self._fired = False        # latched until the chin is released
        self._starting = False     # a startup sequence is in flight
        self._frame = None         # bytes to publish, or None (face shows)
        self._frame_until = None   # optional deadline to auto-clear the frame
        self._dots = 0

        # Thinking face (client publishes /wini/thinking around each turn):
        # while True, show THINK_EMOTION + wandering up-gaze; on False restore
        # whatever emotion was on the face before the turn.
        self._emo_pub = self.create_publisher(String, "/wini/emotion", 10)
        self._gaze_pub = self.create_publisher(Point, "/wini/eyes_target", 10)
        self._thinking = False
        self._think_started = 0.0
        self._prev_emotion = "NEUTRAL 15"
        self._self_emotion = None   # what WE last published (ignore its echo)
        self._gaze_tick = 0

        self.create_subscription(Bool, "/wini/head/touch_chin", self._on_touch, 10)
        self.create_subscription(Bool, "/wini/thinking", self._on_thinking, 10)
        self.create_subscription(String, "/wini/emotion", self._on_emotion, 10)
        self.create_timer(0.2, self._tick)
        self.get_logger().info(
            f"touch trigger up: hold chin {HOLD_S:.0f}s -> run_thin.sh; "
            f"thinking face = {THINK_EMOTION}")

    # -- thinking face --------------------------------------------------------
    def _on_emotion(self, msg):
        # Track the ambient emotion so we can restore it after thinking; skip
        # the echo of our own publishes.
        if msg.data == self._self_emotion:
            return
        self._prev_emotion = msg.data

    def _on_thinking(self, msg):
        active = bool(msg.data)
        if active == self._thinking:
            if active:
                self._think_started = time.monotonic()  # re-assert extends it
            return
        self._thinking = active
        if active:
            self._think_started = time.monotonic()
            self._gaze_tick = 0
        else:
            self._restore_face()

    def _restore_face(self):
        self._self_emotion = self._prev_emotion
        self._emo_pub.publish(String(data=self._prev_emotion))
        self._gaze_pub.publish(gaze_point(0.0, 0.0))

    # -- chin hold detection ------------------------------------------------
    def _on_touch(self, msg):
        now = time.monotonic()
        if msg.data:
            self._last_true = now
            if self._hold_start is None:
                self._hold_start = now
        else:
            if now - self._last_true > RELEASE_GRACE_S:
                self._hold_start = None
                self._fired = False   # released -> re-arm

    def _tick(self):
        now = time.monotonic()
        if (self._hold_start is not None and not self._fired
                and now - self._hold_start >= HOLD_S):
            self._fired = True
            self._trigger()
        # thinking face animation (emotion re-assert + wandering up-gaze)
        if self._thinking:
            if now - self._think_started > THINK_TIMEOUT_S:
                self.get_logger().warn("thinking face timed out; restoring")
                self._thinking = False
                self._restore_face()
            else:
                self._self_emotion = THINK_EMOTION
                self._emo_pub.publish(String(data=THINK_EMOTION))
                side = -0.55 if (self._gaze_tick // GAZE_SWING_TICKS) % 2 else 0.55
                self._gaze_pub.publish(gaze_point(side, -0.6))
                self._gaze_tick += 1
        # display keepalive at 5 Hz while we own the screen
        if self._frame_until is not None and now >= self._frame_until:
            self._frame = None
            self._frame_until = None
        if self._frame is not None:
            if self._starting:  # animate Loading dots
                self._dots += 1
                self._frame = render("Loading" + "." * (1 + (self._dots // 3) % 3),
                                     "Wini is waking up")
            self._msg.data = self._frame
            self._pub.publish(self._msg)

    # -- pipeline startup ---------------------------------------------------
    def _trigger(self):
        if self._starting:
            return
        if server_running() and client_running():
            self.get_logger().info("chin hold: pipeline already running, ignoring")
            self._show("Wini is awake!", "", 2.0, color=(120, 230, 120))
            return
        wake_only = server_running()   # brain warm, client asleep after "bye"
        self.get_logger().info(
            "chin hold: " + ("waking client" if wake_only else "starting thin pipeline"))
        self._starting = True
        self._frame = render("Loading.", "Wini is waking up")
        self._frame_until = None
        threading.Thread(target=self._start_pipeline, args=(wake_only,),
                         daemon=True).start()

    def _start_pipeline(self, wake_only: bool):
        script = RUN_CLIENT if wake_only else RUN_THIN
        try:
            subprocess.run(["bash", script], capture_output=True,
                           timeout=60, start_new_session=True)
        except Exception as e:  # noqa: BLE001
            self.get_logger().error(f"{script} failed: {e}")
        deadline = WAKE_TIMEOUT_S if wake_only else STARTUP_TIMEOUT_S
        t0 = time.monotonic()
        while time.monotonic() - t0 < deadline:
            if health_ready() and client_running():
                self.get_logger().info("pipeline ready")
                self._starting = False
                self._show("Ready!", "say something to Wini", 2.5,
                           color=(120, 230, 120))
                return
            time.sleep(1.0 if wake_only else 2.0)
        self.get_logger().error("pipeline did not become ready in time")
        self._starting = False
        self._show("Start failed", "check server.log", 5.0,
                   color=(80, 80, 255))

    def _show(self, text, sub, seconds, color=(90, 200, 255)):
        self._frame = render(text, sub, color=color)
        self._frame_until = time.monotonic() + seconds


def main():
    rclpy.init()
    node = TouchTrigger()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
