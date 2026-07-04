"""Display library: ST7796S driver + face renderer + the DisplayThread owner.

`eyes.py`, `wini_face.py`, `wini_display_driver.py` are verbatim copies of the
2026-07-04 device snapshot (jetson_platform/device_snapshot/display_controll/)
— pure renderer / hardware code that was already ROS-free. `display_thread.py`
is the ROS-less port of the wini_display node's main loop.
"""
