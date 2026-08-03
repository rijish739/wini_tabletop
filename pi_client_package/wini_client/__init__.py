"""Wini thin client — the device side of the split.

Deliberately tiny and portable: the device is ONLY a platform for a mic, a
speaker, a display, and (later) touch sensors. All intelligence lives behind the
brain service's HTTP contract (wini_server.py). Porting to a new device (ESP32,
another SBC) means reimplementing the four platform seams in README.md — nothing
else. Hard dependency budget: numpy + sounddevice + requests (display sinks may
add platform-local extras, e.g. rclpy/cv2 on the Jetson).
"""

__version__ = "0.1.0"
