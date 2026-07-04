"""Touch library: STM32 head-board serial owner (chin/head touch, IMU).

ROS-less port of device_snapshot/wini_hw_bridge/serial_base.py +
wini_head_node.py (2026-07-04 snapshot). Ear animation code was dropped — it
was dead (`EAR_DRIVE_ENABLED=False`, firmware position-loop defect, see
EAR_ACTUATION_ISSUE.md); the W_EKP:80 hold gain + W_DH homing init are kept so
the ears park upright.
"""
