#!/usr/bin/env python3
"""Wini head bridge: ears, IMU, touch sensors. Supports direct ear angle
commands or emotion-driven animated ears (mirrors display node emotions)."""

import math
import time
from typing import Callable, Dict, Tuple

import rclpy
from sensor_msgs.msg import Imu, JointState
from std_msgs.msg import Bool, Empty, Float32, String

from wini_hw_bridge.serial_base import WiniSerialNode

EAR_LIMIT_DEG = 90.0
ANIM_PERIOD_S = 0.02   # 50 Hz ear animation tick
HOME_SETTLE_S = 8.0    # hold the animator off while startup homing runs
EAR_DRIVE_ENABLED = False  # firmware ear loop broken: NEVER send W_EAL/W_EAR
                           # (does not sync to homed zero -> any target rails).
                           # Ears stay where W_DH homing parked them (upright).
EAR_HOLD_KP = 80           # gain that HOLDS the homed-upright position. With
                           # the animator disabled no W_EAL/W_EAR is ever sent,
                           # so this only holds home and never drives a target.
SEND_TOLERANCE_DEG = 0.5

# MPU6050 default sensitivities (±2g, ±250 dps).
ACCEL_SCALE = 9.80665 / 16384.0          # LSB → m/s²
GYRO_SCALE = (math.pi / 180.0) / 131.0   # LSB → rad/s


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# -------- Emotion ear-animation presets --------------------------------------
# Each preset is f(t, i) -> (left_deg, right_deg).
# Sign convention: CW = positive, CCW = negative. Left ear forward is CCW
# (negative); right ear is mirrored, so a symmetric "both forward" pose is
# (left=-X, right=+X).
# Intensity i ∈ [0, 1] scales deflection from rest.

def _neutral(t, i):
    s = 2.0 * math.sin(0.3 * 2 * math.pi * t) * i
    return (-s, s)

def _happy(t, i):
    a = (20.0 + 6.0 * math.sin(2 * math.pi * 1.5 * t)) * i
    return (-a, a)

def _sad(t, i):
    a = (-55.0 + 3.0 * math.sin(0.4 * 2 * math.pi * t)) * i
    return (-a, a)

def _angry(t, i):
    twitch = 6.0 * math.copysign(1.0, math.sin(2 * math.pi * 3.0 * t))
    a = (-75.0 + twitch) * i
    return (-a, a)

def _surprised(t, i):
    a = (65.0 + 4.0 * math.sin(2 * math.pi * 4.0 * t)) * i
    return (-a, a)

def _confused(t, i):
    # Asymmetric tilt that slowly wobbles. Both ears swing the same direction in
    # head frame → looks quizzical (one forward, one back).
    s = 30.0 * math.sin(2 * math.pi * 0.6 * t) * i
    return (-s, -s)

def _tired(t, i):
    a = (-45.0 + 2.5 * math.sin(2 * math.pi * 0.35 * t)) * i
    return (-a, a)

def _blush(t, i):
    a = (10.0 + 2.0 * math.sin(2 * math.pi * 2.0 * t)) * i
    return (-a, a)

def _love(t, i):
    a = (28.0 + 10.0 * math.sin(2 * math.pi * 0.8 * t)) * i
    return (-a, a)

def _excitement(t, i):
    a = (30.0 + 25.0 * math.sin(2 * math.pi * 2.5 * t)) * i
    return (-a, a)

def _smirk(t, i):
    # Asymmetric: left ear forward, right ear neutral with tiny twitch.
    twitch = 5.0 * math.sin(2 * math.pi * 1.0 * t)
    return (-40.0 * i, -twitch * i)

def _dizzy(t, i):
    # Counter-phase oscillation, no mirroring.
    p = 2 * math.pi * 0.7
    return (-40.0 * math.sin(p * t) * i, -40.0 * math.sin(p * t + math.pi / 2) * i)

def _xeyes(t, i):
    twitch = 8.0 * math.sin(2 * math.pi * 5.0 * t)
    a = (-35.0 + twitch) * i
    return (-a, a)


EAR_EMOTIONS: Dict[str, Callable[[float, float], Tuple[float, float]]] = {
    "NEUTRAL": _neutral,
    "HAPPY": _happy,
    "SAD": _sad,
    "ANGRY": _angry,
    "SURPRISED": _surprised,
    "CONFUSED": _confused,
    "TIRED": _tired,
    "BLUSH": _blush,
    "LOVE": _love,
    "EXCITEMENT": _excitement,
    "SMIRK": _smirk,
    "DIZZY": _dizzy,
    "XEYES": _xeyes,
}


class WiniHeadNode(WiniSerialNode):
    def __init__(self):
        super().__init__("wini_head_node", "wini_head")

        # ---- ear-control state ------------------------------------------------
        self._mode = "EMOTION"        # or "DIRECT"
        self._emotion = "NEUTRAL"
        self._intensity = 1.0          # 0..1
        self._direct_left = 0.0        # deg
        self._direct_right = 0.0
        self._last_sent_left = None
        self._last_sent_right = None
        self._anim_t0 = time.monotonic()
        self._wiggle = False
        self._wiggle_t0 = time.monotonic()
        self._homing_until = 0.0   # animator stays hands-off until this time

        # ---- desired W_STOP / W_DBG state ------------------------------------
        self._stop_state = 0
        self._debug_state = 0

        # ---- subscriptions ----------------------------------------------------
        self.create_subscription(Float32, "/wini/head/ear_left_cmd",
                                 self._cb_left, 10)
        self.create_subscription(Float32, "/wini/head/ear_right_cmd",
                                 self._cb_right, 10)
        self.create_subscription(Empty, "/wini/head/home_ears",
                                 self._cb_home, 10)
        self.create_subscription(Bool, "/wini/head/motor_stop",
                                 self._cb_stop, 10)
        self.create_subscription(Bool, "/wini/head/debug_telemetry",
                                 self._cb_debug, 10)
        self.create_subscription(Bool, "/wini/head/bootloader_cmd",
                                 self._cb_bootloader, 10)
        self.create_subscription(String, "/wini/head/ear_control_mode",
                                 self._cb_mode, 10)
        self.create_subscription(String, "/wini/emotion",
                                 self._cb_emotion, 10)
        self.create_subscription(Bool, "/wini/head/ear_wiggle",
                                 self._cb_wiggle, 10)
        # Generic raw-command passthrough — for runtime tuning of registers
        # that don't have a dedicated topic yet (W_EKP, W_EKD, W_EFRIC,
        # W_ETOL, W_EDAMP, etc.). Useful when iterating on firmware gains
        # before promoting the final value into on_connected.
        self.create_subscription(String, "/wini/head/raw_cmd",
                                 self._cb_raw_cmd, 10)

        # ---- publishers -------------------------------------------------------
        self._imu_pub = self.create_publisher(Imu, "/wini/head/imu", 10)
        self._joint_pub = self.create_publisher(JointState,
                                                "/wini/head/ear_states", 10)
        self._touch_chin_pub = self.create_publisher(Bool,
                                                     "/wini/head/touch_chin", 10)
        self._touch_top_pub = self.create_publisher(Bool,
                                                    "/wini/head/touch_top", 10)

        # ---- 50 Hz ear animator ----------------------------------------------
        self.create_timer(ANIM_PERIOD_S, self._anim_tick)

        self.get_logger().info("Wini head node initialised.")

    # --- callbacks ----------------------------------------------------------------

    def _cb_left(self, msg: Float32):
        self._direct_left = _clamp(msg.data, -EAR_LIMIT_DEG, EAR_LIMIT_DEG)

    def _cb_right(self, msg: Float32):
        self._direct_right = _clamp(msg.data, -EAR_LIMIT_DEG, EAR_LIMIT_DEG)

    def _cb_home(self, _msg: Empty):
        self.send_command("W_DH")
        self._last_sent_left = None
        self._last_sent_right = None

    def _cb_stop(self, msg: Bool):
        new_state = 1 if msg.data else 0
        if new_state != self._stop_state:
            self._stop_state = new_state
            self.send_command(f"W_STOP:{new_state}")

    def _cb_debug(self, msg: Bool):
        new_state = 1 if msg.data else 0
        if new_state != self._debug_state:
            self._debug_state = new_state
            self.send_command(f"W_DBG:{new_state}")

    def _cb_bootloader(self, msg: Bool):
        if msg.data:
            self.send_command("W_BOOT0")

    def _cb_mode(self, msg: String):
        m = msg.data.strip().upper()
        if m in ("EMOTION", "DIRECT"):
            self._mode = m
            self._anim_t0 = time.monotonic()

    def _cb_emotion(self, msg: String):
        parts = msg.data.replace(":", " ").replace(",", " ").split()
        if not parts:
            return
        name = parts[0].strip().upper()
        if name not in EAR_EMOTIONS:
            name = "NEUTRAL"
        if name != self._emotion:
            self._anim_t0 = time.monotonic()
        self._emotion = name
        if len(parts) > 1:
            try:
                raw = int(parts[1])
                # Remap so intensity 7 (mid-range / "normal") feels near full
                # expression: i = (raw/15)^0.4 gives 0.83 at raw=7, 1.0 at 15.
                self._intensity = _clamp((raw / 7.0), 0.0, 1.0)
            except ValueError:
                pass

    def _cb_raw_cmd(self, msg: String):
        cmd = (msg.data or "").strip()
        if not cmd:
            return
        self.get_logger().info(f"raw_cmd -> {cmd!r}")
        self.send_command(cmd)

    def _cb_wiggle(self, msg: Bool):
        new_state = bool(msg.data)
        if new_state and not self._wiggle:
            self._wiggle_t0 = time.monotonic()
            # Force the next anim tick to emit fresh W_EAL/W_EAR commands
            # by busting the SEND_TOLERANCE_DEG dedup state. Without this,
            # if the prior emotion preset happened to leave both ears within
            # 0.5° of the wiggle origin (t=0 of _confused is ~0°), the first
            # wiggle frame would be suppressed; in pathological cases the
            # firmware then never gets a "wake-up" target and the ears
            # appear stuck even though the topic was received.
            self._last_sent_left = None
            self._last_sent_right = None
            self.get_logger().info("ear_wiggle ON (rising edge)")
        elif not new_state and self._wiggle:
            self.get_logger().info("ear_wiggle OFF")
        self._wiggle = new_state

    # --- animator -----------------------------------------------------------------

    def _anim_tick(self):
        # While startup homing runs, stay hands-off so our position targets
        # do not fight the firmware W_DH routine.
        if time.monotonic() < self._homing_until:
            return
        if not EAR_DRIVE_ENABLED:
            # Ear actuation disabled (firmware loop broken). Emotion/face and
            # touch sensing still work; ears hold the homed-upright position.
            return
        # Throttled diagnostics: when wiggle is active, every ~50 ticks (1 s
        # at 50 Hz) log the current targets and serial-write decision so we
        # can confirm host→firmware transmission. Removed/silenced when not
        # wiggling to keep the log quiet during normal use.
        if not hasattr(self, '_anim_tick_counter'):
            self._anim_tick_counter = 0
        self._anim_tick_counter += 1
        if self._wiggle:
            t = (time.monotonic() - self._wiggle_t0) * 2.0
            tl, tr = _confused(t, 1.0)
            target_l = _clamp(tl, -EAR_LIMIT_DEG, EAR_LIMIT_DEG)
            target_r = _clamp(tr, -EAR_LIMIT_DEG, EAR_LIMIT_DEG)
        elif self._mode == "DIRECT":
            target_l = self._direct_left
            target_r = self._direct_right
        else:
            preset = EAR_EMOTIONS.get(self._emotion, _neutral)
            t = time.monotonic() - self._anim_t0
            tl, tr = preset(t, self._intensity)
            target_l = _clamp(tl, -EAR_LIMIT_DEG, EAR_LIMIT_DEG)
            target_r = _clamp(tr, -EAR_LIMIT_DEG, EAR_LIMIT_DEG)

        parts = []
        if (self._last_sent_left is None
                or abs(target_l - self._last_sent_left) > SEND_TOLERANCE_DEG):
            parts.append(f"W_EAL:{target_l:.2f}")
            self._last_sent_left = target_l
        if (self._last_sent_right is None
                or abs(target_r - self._last_sent_right) > SEND_TOLERANCE_DEG):
            parts.append(f"W_EAR:{target_r:.2f}")
            self._last_sent_right = target_r
        if parts:
            self.send_command(" ".join(parts))
        # Diagnostic — only log while wiggling to investigate the
        # "no ear motion" report. Removes itself effectively once wiggle
        # ends. ~once per second.
        if self._wiggle and (self._anim_tick_counter % 50 == 0):
            self.get_logger().info(
                f"wiggle tick: target=({target_l:+.2f},{target_r:+.2f})  "
                f"sent={('YES' if parts else 'NO')}  "
                f"last_sent=({self._last_sent_left},{self._last_sent_right})  "
                f"serial_open={bool(self._serial and self._serial.is_open)}"
            )

    # --- telemetry ----------------------------------------------------------------

    def on_connected(self):
        # Re-assert latched state and (re)initialise the ear subsystem.
        # CRITICAL: the firmware boots with the ear PWM cap (W_EPWM) at an
        # unknown / sometimes-zero value. With EPWM=0 the firmware accepts
        # W_EAL/W_EAR target updates but the motor PWM ceiling stays at
        # zero, so the ears appear stuck even though host-side everything
        # is correct. Mirrors what wini_arm_node already does for the neck
        # (`W_NPWM:4199` in its on_connected). EAFL/EABL set the firmware-
        # side ear angle limits to match the host clamp (±EAR_LIMIT_DEG).
        init = (
            f"W_EPWM:2500 W_EKP:{EAR_HOLD_KP} "
            f"W_EAFL:{EAR_LIMIT_DEG} W_EABL:{-EAR_LIMIT_DEG} "
            f"W_STOP:{self._stop_state} W_DBG:{self._debug_state}"
        )
        self.send_command(init)
        # Home the ears so 0deg is referenced to the mechanical stop
        # (upright) BEFORE the animator drives any target. Without this the
        # absolute emotion angles ride on an undefined boot position and can
        # push an ear past a stop and jam it (firmware then latches PWM to 0).
        self.send_command("W_DH")
        self._homing_until = time.monotonic() + HOME_SETTLE_S
        self.get_logger().info(
            f"head init sent: {init!r}; homing for {HOME_SETTLE_S:.0f}s")
        self._last_sent_left = None
        self._last_sent_right = None

    def on_telemetry(self, data, _raw):
        now = self.get_clock().now().to_msg()

        if "EAL" in data and "EAR" in data:
            js = JointState()
            js.header.stamp = now
            js.name = ["left_ear_joint", "right_ear_joint"]
            js.position = [
                math.radians(data["EAL"]),
                math.radians(data["EAR"]),
            ]
            self._joint_pub.publish(js)

        if "AX" in data:
            imu = Imu()
            imu.header.stamp = now
            imu.header.frame_id = "head_imu_link"
            imu.linear_acceleration.x = data.get("AX", 0.0) * ACCEL_SCALE
            imu.linear_acceleration.y = data.get("AY", 0.0) * ACCEL_SCALE
            imu.linear_acceleration.z = data.get("AZ", 0.0) * ACCEL_SCALE
            imu.angular_velocity.x = data.get("GX", 0.0) * GYRO_SCALE
            imu.angular_velocity.y = data.get("GY", 0.0) * GYRO_SCALE
            imu.angular_velocity.z = data.get("GZ", 0.0) * GYRO_SCALE
            imu.orientation_covariance[0] = -1.0   # orientation unknown
            self._imu_pub.publish(imu)

        if "TC" in data:
            b = Bool(); b.data = bool(int(data["TC"])); self._touch_chin_pub.publish(b)
        if "TH" in data:
            b = Bool(); b.data = bool(int(data["TH"])); self._touch_top_pub.publish(b)


def main(args=None):
    rclpy.init(args=args)
    node = WiniHeadNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
