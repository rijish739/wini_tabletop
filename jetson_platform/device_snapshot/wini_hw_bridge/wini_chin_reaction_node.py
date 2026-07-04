#!/usr/bin/env python3
"""Wini chin-touch reaction: when the chin touch sensor fires, Wini blushes.

This is pure glue. The capabilities already exist:
  * the display node (wini_display) renders a BLUSH face from /wini/emotion;
  * the head node (wini_head_node) animates the ears from /wini/emotion via its
    gentle _blush preset.
Both subscribe /wini/emotion, so a single "BLUSH" publish drives the face and
the ears together. All that was missing was a trigger off the chin sensor, which
wini_head_node publishes on /wini/head/touch_chin but nothing consumed.

On a debounced rising edge of the chin sensor we publish BLUSH, hold it briefly
(a fresh touch extends the hold), then revert to the idle emotion (NEUTRAL).
Everything is exposed as ROS params so it can be tuned at launch.
"""

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Bool, String


class WiniChinReactionNode(Node):
    def __init__(self):
        super().__init__("wini_chin_reaction_node")

        # ---- params (override at launch without editing code) ----------------
        self.declare_parameter("blush_intensity", 12)
        self.declare_parameter("blush_hold_s", 3.0)
        self.declare_parameter("idle_emotion", "NEUTRAL")
        self.declare_parameter("idle_intensity", 7)
        self.declare_parameter("debounce_s", 0.4)

        self._blush_intensity = int(self.get_parameter("blush_intensity").value)
        self._hold_s = float(self.get_parameter("blush_hold_s").value)
        self._idle_emotion = str(self.get_parameter("idle_emotion").value).upper()
        self._idle_intensity = int(self.get_parameter("idle_intensity").value)
        self._debounce_s = float(self.get_parameter("debounce_s").value)

        # ---- state -----------------------------------------------------------
        self._last_touch = False     # previous chin sensor level (edge detect)
        self._blushing = False       # currently inside a blush reaction
        self._blush_until = 0.0      # monotonic deadline to revert
        self._last_trigger = 0.0     # debounce guard

        # ---- pub / sub -------------------------------------------------------
        self._emotion_pub = self.create_publisher(String, "/wini/emotion", 10)
        self.create_subscription(Bool, "/wini/head/touch_chin",
                                 self._cb_chin, 10)
        # 10 Hz housekeeping: revert once the hold window expires.
        self.create_timer(0.1, self._tick)

        self.get_logger().info(
            f"chin-reaction up: BLUSH {self._blush_intensity} for "
            f"{self._hold_s:.1f}s on /wini/head/touch_chin, then -> "
            f"{self._idle_emotion}."
        )

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds / 1e9

    def _publish_emotion(self, name: str, intensity: int) -> None:
        m = String()
        m.data = f"{name} {intensity}"
        self._emotion_pub.publish(m)

    def _cb_chin(self, msg: Bool) -> None:
        touched = bool(msg.data)
        rising = touched and not self._last_touch
        self._last_touch = touched
        if not rising:
            return
        now = self._now()
        if now - self._last_trigger < self._debounce_s:
            return
        self._last_trigger = now
        # (Re)arm the hold window; a fresh touch while blushing extends it.
        self._blush_until = now + self._hold_s
        if not self._blushing:
            self._blushing = True
            self.get_logger().info("chin touched -> BLUSH")
        self._publish_emotion("BLUSH", self._blush_intensity)

    def _tick(self) -> None:
        if self._blushing and self._now() >= self._blush_until:
            self._blushing = False
            self._publish_emotion(self._idle_emotion, self._idle_intensity)
            self.get_logger().info(f"blush done -> {self._idle_emotion}")


def main(args=None):
    rclpy.init(args=args)
    node = WiniChinReactionNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        # Clean exit on Ctrl-C or a launch/SIGTERM shutdown — the signal
        # handler has already torn down the context in the latter case.
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
