#!/usr/bin/env python3
"""Publish a 'Loading...' text frame to /wini/display/image.

480x320 rgb8, horizontally pre-flipped for the mirrored SPI panel (runbook
section 7.2), published at 5 Hz (the display reverts to the face if frames
stop for 0.5 s). Dots animate so the user can see the system is alive.
Exits after --seconds (default 30) or on SIGTERM.
"""
import argparse
import time

import cv2
import numpy as np
import rclpy
from sensor_msgs.msg import Image

W, H = 480, 320
FONT = cv2.FONT_HERSHEY_SIMPLEX


def render(text, sub):
    canvas = np.zeros((H, W, 3), np.uint8)
    canvas[:] = (12, 12, 32)
    (tw, _), _ = cv2.getTextSize(text, FONT, 1.5, 3)
    cv2.putText(canvas, text, ((W - tw) // 2, H // 2 - 8), FONT, 1.5,
                (90, 200, 255), 3, cv2.LINE_AA)
    if sub:
        (sw, _), _ = cv2.getTextSize(sub, FONT, 0.7, 2)
        cv2.putText(canvas, sub, ((W - sw) // 2, H // 2 + 44), FONT, 0.7,
                    (200, 200, 200), 2, cv2.LINE_AA)
    return np.ascontiguousarray(cv2.flip(canvas, 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--text", default="Loading")
    ap.add_argument("--sub", default="Wini is waking up")
    args = ap.parse_args()

    rclpy.init()
    node = rclpy.create_node("wini_loading_text")
    pub = node.create_publisher(Image, "/wini/display/image", 10)
    node.get_logger().info(f"publishing loading frames for {args.seconds:.0f}s")

    msg = Image()
    msg.height, msg.width = H, W
    msg.encoding = "rgb8"
    msg.is_bigendian = 0
    msg.step = W * 3

    t0 = time.time()
    i = 0
    while rclpy.ok() and (time.time() - t0) < args.seconds:
        dots = "." * (1 + (i // 3) % 3)
        msg.data = render(args.text + dots, args.sub).tobytes()
        pub.publish(msg)
        i += 1
        time.sleep(0.2)

    node.get_logger().info("loading publisher done")
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
