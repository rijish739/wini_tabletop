"""SerialHead — single owner of the wini_head STM32 serial port.

Kept from the ROS nodes: USB discovery by product string, 1 s reconnect loop,
locked writes split at the 64-byte USB packet limit, the Rn_KEY telemetry
parser, and the on-connect init (`W_EPWM`/`W_EKP`/limits + `W_DH` homing so the
ears hold upright — see wini_head_node.on_connected for the firmware rationale).
Dropped: all rclpy plumbing and the ear animator (dead code —
EAR_DRIVE_ENABLED was False; firmware ear loop defect, EAR_ACTUATION_ISSUE.md).

Telemetry is delivered via plain callbacks from the read thread:
    on_chin(level: bool)   ~100 Hz level of the chin touch sensor (TC)
    on_head(level: bool)   ~100 Hz level of the top touch sensor (TH)
    on_imu(dict)           optional; scaled accel (m/s^2) + gyro (rad/s)
Callbacks must be fast and non-blocking (they run on the serial read thread).

⚠️ Never run this alongside the old ROS wini_head_node — two owners of one
serial port cannot coexist.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Callable, Dict, Optional

import serial
import serial.tools.list_ports

USB_PACKET_LIMIT = 64
RECONNECT_INTERVAL_S = 1.0
NOT_FOUND_LOG_THROTTLE_S = 60.0
BAUDRATE = 115200

EAR_LIMIT_DEG = 90.0
EAR_HOLD_KP = 80          # holds the homed-upright position; with no W_EAL/
                          # W_EAR ever sent this never drives a target.

# MPU6050 default sensitivities (±2g, ±250 dps).
ACCEL_SCALE = 9.80665 / 16384.0          # LSB → m/s²
GYRO_SCALE = (math.pi / 180.0) / 131.0   # LSB → rad/s


class SerialHead:
    def __init__(self,
                 usb_product_match: str = "wini_head",
                 on_chin: Optional[Callable[[bool], None]] = None,
                 on_head: Optional[Callable[[bool], None]] = None,
                 on_imu: Optional[Callable[[Dict[str, float]], None]] = None,
                 on_connect_change: Optional[Callable[[bool], None]] = None,
                 log: Callable[[str], None] = print):
        self._usb_match = usb_product_match.lower()
        self._on_chin = on_chin
        self._on_head = on_head
        self._on_imu = on_imu
        self._on_connect_change = on_connect_change
        self._log = log

        self._serial: Optional[serial.Serial] = None
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._stop_read = threading.Event()
        self._read_thread: Optional[threading.Thread] = None
        self._reconnect_thread: Optional[threading.Thread] = None
        self._last_not_found_log = 0.0

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._stop.clear()
        self._reconnect_thread = threading.Thread(
            target=self._reconnect_loop, name="wini-head-reconnect", daemon=True)
        self._reconnect_thread.start()

    def connected(self) -> bool:
        return bool(self._serial and self._serial.is_open)

    def shutdown(self) -> None:
        """Disarm motors and close the port. Safe to call multiple times."""
        self._stop.set()
        try:
            self.send_command("W_STOP:1")
            time.sleep(0.05)
        except Exception:
            pass
        self._drop_connection()

    # ── connection ───────────────────────────────────────────────────────────

    def _find_port(self) -> Optional[str]:
        for port in serial.tools.list_ports.comports():
            if port.product and self._usb_match in port.product.lower():
                return port.device
        return None

    def _reconnect_loop(self) -> None:
        while not self._stop.wait(RECONNECT_INTERVAL_S):
            if self._serial and self._serial.is_open:
                continue
            port = self._find_port()
            if not port:
                now = time.monotonic()
                if now - self._last_not_found_log > NOT_FOUND_LOG_THROTTLE_S:
                    self._log(f"[head] {self._usb_match} not found on USB; "
                              "will keep retrying.")
                    self._last_not_found_log = now
                continue
            try:
                self._serial = serial.Serial(port, BAUDRATE, timeout=0.1)
                time.sleep(0.5)
                self._log(f"[head] connected to {self._usb_match} on {port}.")
                self._stop_read.clear()
                self._read_thread = threading.Thread(
                    target=self._read_loop, name="wini-head-read", daemon=True)
                self._read_thread.start()
                if self._on_connect_change:
                    self._on_connect_change(True)
                try:
                    self.on_connected()
                except Exception as e:  # noqa: BLE001
                    self._log(f"[head] on_connected() failed: {e}")
            except serial.SerialException as e:
                self._log(f"[head] failed to open {port}: {e}")
                self._serial = None

    def _drop_connection(self) -> None:
        self._stop_read.set()
        try:
            if self._serial and self._serial.is_open:
                self._serial.close()
        except Exception:
            pass
        self._serial = None
        if self._on_connect_change:
            try:
                self._on_connect_change(False)
            except Exception:
                pass

    # ── init on (re)connect ──────────────────────────────────────────────────

    def on_connected(self) -> None:
        # Firmware boots with the ear PWM cap at an unknown/zero value; set it,
        # the hold gain, and the angle limits, then home (W_DH) so 0° is
        # referenced to the mechanical stop (upright). No ear targets are ever
        # sent afterwards — the ears just hold home.
        init = (
            f"W_EPWM:2500 W_EKP:{EAR_HOLD_KP} "
            f"W_EAFL:{EAR_LIMIT_DEG} W_EABL:{-EAR_LIMIT_DEG} "
            f"W_STOP:0 W_DBG:0"
        )
        self.send_command(init)
        self.send_command("W_DH")
        self._log(f"[head] init sent: {init!r}; homing")

    # ── writing ──────────────────────────────────────────────────────────────

    def send_command(self, cmd: str) -> None:
        """Send one or more space-separated W_ commands. Splits across multiple
        writes if the payload exceeds the 64-byte USB packet limit."""
        if not self._serial or not self._serial.is_open:
            return
        payload = cmd.strip()
        if not payload:
            return
        if not payload.endswith("\n"):
            payload += "\n"
        data = payload.encode("utf-8")
        with self._write_lock:
            try:
                if len(data) <= USB_PACKET_LIMIT:
                    self._serial.write(data)
                else:
                    tokens = payload.strip().split()
                    chunk = ""
                    for tok in tokens:
                        candidate = (chunk + " " + tok).strip()
                        if len(candidate) + 1 > USB_PACKET_LIMIT:
                            self._serial.write((chunk + "\n").encode("utf-8"))
                            chunk = tok
                        else:
                            chunk = candidate
                    if chunk:
                        self._serial.write((chunk + "\n").encode("utf-8"))
                self._serial.flush()
            except Exception as e:  # noqa: BLE001
                self._log(f"[head] serial write failed: {e}")
                self._drop_connection()

    # ── reading / parsing ────────────────────────────────────────────────────

    def _read_loop(self) -> None:
        ser = self._serial
        while (not self._stop.is_set() and not self._stop_read.is_set()
               and ser and ser.is_open):
            try:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                if line.startswith("ACK") or line.startswith("NACK"):
                    continue
                data = self.parse_telemetry(line)
                if data:
                    try:
                        self._dispatch(data)
                    except Exception as e:  # noqa: BLE001
                        self._log(f"[head] telemetry callback failed: {e}")
            except Exception as e:  # noqa: BLE001
                self._log(f"[head] serial read failed: {e}")
                self._drop_connection()
                return

    def _dispatch(self, data: Dict[str, float]) -> None:
        if "TC" in data and self._on_chin:
            self._on_chin(bool(int(data["TC"])))
        if "TH" in data and self._on_head:
            self._on_head(bool(int(data["TH"])))
        if "AX" in data and self._on_imu:
            self._on_imu({
                "ax": data.get("AX", 0.0) * ACCEL_SCALE,
                "ay": data.get("AY", 0.0) * ACCEL_SCALE,
                "az": data.get("AZ", 0.0) * ACCEL_SCALE,
                "gx": data.get("GX", 0.0) * GYRO_SCALE,
                "gy": data.get("GY", 0.0) * GYRO_SCALE,
                "gz": data.get("GZ", 0.0) * GYRO_SCALE,
            })

    @staticmethod
    def parse_telemetry(line: str) -> Dict[str, float]:
        """Parse `Rn_KEY:VAL R0_KEY:VAL ...` lines, dividing by 10**n."""
        out: Dict[str, float] = {}
        for tok in line.split():
            if ":" not in tok:
                continue
            key, raw = tok.split(":", 1)
            try:
                val = float(raw)
            except ValueError:
                continue
            scale = 1.0
            if key.startswith("R") and "_" in key:
                try:
                    n = int(key[1: key.index("_")])
                    scale = 10.0 ** n
                    key = key[key.index("_") + 1:]
                except ValueError:
                    pass
            out[key] = val / scale
        return out
