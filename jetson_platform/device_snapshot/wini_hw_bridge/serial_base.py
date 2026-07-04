"""Shared serial-bridge base for all three wini STM32 controllers."""

import threading
import time
from typing import Dict, Optional

import rclpy
import serial
import serial.tools.list_ports
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, HistoryPolicy
from std_msgs.msg import Bool

USB_PACKET_LIMIT = 64
RECONNECT_INTERVAL_S = 1.0
NOT_FOUND_LOG_THROTTLE_S = 60.0
BAUDRATE = 115200


def latched_qos() -> QoSProfile:
    return QoSProfile(
        depth=1,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
        history=HistoryPolicy.KEEP_LAST,
    )


class WiniSerialNode(Node):
    """Base class with auto-discovery, reconnect, locked writes, and a generic
    Rn_KEY:val telemetry parser. Subclasses implement on_telemetry() and
    on_connected() to react to incoming lines and (re)initialise the board."""

    def __init__(self, node_name: str, usb_product_match: str):
        super().__init__(node_name)
        self._usb_match = usb_product_match.lower()
        self._serial: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._read_thread: Optional[threading.Thread] = None
        self._stop_read = threading.Event()
        self._last_not_found_log = 0.0

        self._connected_pub = self.create_publisher(
            Bool, f'/wini/{usb_product_match.replace("wini_", "")}/connected', latched_qos()
        )
        self._publish_connected(False)

        self._reconnect_timer = self.create_timer(
            RECONNECT_INTERVAL_S, self._reconnect_tick
        )

    # --- connection lifecycle ----------------------------------------------------

    def _publish_connected(self, ok: bool):
        msg = Bool()
        msg.data = ok
        self._connected_pub.publish(msg)

    def _find_port(self) -> Optional[str]:
        for port in serial.tools.list_ports.comports():
            if port.product and self._usb_match in port.product.lower():
                return port.device
        return None

    def _reconnect_tick(self):
        if self._serial and self._serial.is_open:
            return
        port = self._find_port()
        if not port:
            now = time.monotonic()
            if now - self._last_not_found_log > NOT_FOUND_LOG_THROTTLE_S:
                self.get_logger().warn(
                    f"{self._usb_match} not found on USB; will keep retrying."
                )
                self._last_not_found_log = now
            return
        try:
            self._serial = serial.Serial(port, BAUDRATE, timeout=0.1)
            time.sleep(0.5)
            self.get_logger().info(f"Connected to {self._usb_match} on {port}.")
            self._stop_read.clear()
            self._read_thread = threading.Thread(
                target=self._read_loop, daemon=True
            )
            self._read_thread.start()
            self._publish_connected(True)
            try:
                self.on_connected()
            except Exception as e:
                self.get_logger().error(f"on_connected() failed: {e}")
        except serial.SerialException as e:
            self.get_logger().error(f"Failed to open {port}: {e}")
            self._serial = None

    def _drop_connection(self):
        self._stop_read.set()
        try:
            if self._serial and self._serial.is_open:
                self._serial.close()
        except Exception:
            pass
        self._serial = None
        self._publish_connected(False)

    # --- writing ------------------------------------------------------------------

    def send_command(self, cmd: str):
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
        with self._lock:
            try:
                # If small enough, single write.
                if len(data) <= USB_PACKET_LIMIT:
                    self._serial.write(data)
                else:
                    # Split on spaces, regroup into packets of <=63 bytes + '\n'.
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
            except Exception as e:
                self.get_logger().error(f"Serial write failed: {e}")
                self._drop_connection()

    # --- reading / parsing --------------------------------------------------------

    def _read_loop(self):
        ser = self._serial
        while rclpy.ok() and not self._stop_read.is_set() and ser and ser.is_open:
            try:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                if line.startswith("ACK") or line.startswith("NACK"):
                    self.get_logger().debug(line)
                    continue
                data = self.parse_telemetry(line)
                if data:
                    try:
                        self.on_telemetry(data, line)
                    except Exception as e:
                        self.get_logger().error(f"on_telemetry() failed: {e}")
            except Exception as e:
                self.get_logger().error(f"Serial read failed: {e}")
                self._drop_connection()
                return

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
                    n = int(key[1 : key.index("_")])
                    scale = 10.0 ** n
                    key = key[key.index("_") + 1 :]
                except ValueError:
                    pass
            out[key] = val / scale
        return out

    # --- subclass hooks -----------------------------------------------------------

    def on_connected(self):
        """Called once on every successful (re)connection. Send init commands here."""
        pass

    def on_telemetry(self, data: Dict[str, float], raw_line: str):
        """Called for every parsed telemetry line."""
        pass

    # --- shutdown -----------------------------------------------------------------

    def shutdown(self):
        """Disarm motors and close the port. Safe to call multiple times."""
        try:
            self.send_command("W_STOP:1")
            time.sleep(0.05)
        except Exception:
            pass
        self._drop_connection()
