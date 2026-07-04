"""WiniPlatform supervisor — wires display + touch + client into one process.

ROS-less port of jetson_platform/wini_touch_trigger.py (chin-hold state
machine, loading/ready/failed cards, thinking-face animation) and
device_snapshot/wini_hw_bridge/wini_chin_reaction_node.py (chin-tap → blush),
per WINI_ROSLESS_PLATFORM_PLAN.md §4. All the old topic publishes are direct
calls into the DisplayThread; run_thin.sh / run_client.sh subprocess launches
become a ClientThread running wini_client.client.run_session as a library.

wini_server.py stays a SEPARATE process (it is the Cloud Run artifact): the
supervisor only starts/monitors it — or starts nothing when the URL is remote
or --no-manage-server is given (systemd-managed / Cloud Run brain).

Sleep = ClientThread not running (mic closed). The brain stays warm; a chin
hold restarts the client in seconds.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .display.display_thread import DisplayThread
from .touch.serial_head import SerialHead
from . import ui_cards

# ── tunables (carried over from the ROS nodes) ──────────────────────────────
HOLD_S = 3.0                 # chin hold needed to trigger start/wake
RELEASE_GRACE_S = 0.3        # micro-release shorter than this keeps the hold
TICK_S = 0.2                 # supervisor housekeeping tick

THINK_EMOTION = ("CONFUSED", 8)   # quizzical squint; intensity <=10 avoids tongue
THINK_TIMEOUT_S = 120.0           # safety: never stay in thinking face forever
GAZE_SWING_TICKS = 8              # 0.2 s ticks per gaze side (~1.6 s left/right)

BLUSH_INTENSITY = 12
BLUSH_HOLD_S = 3.0
BLUSH_DEBOUNCE_S = 0.4
IDLE_EMOTION = ("NEUTRAL", 7)

STARTUP_TIMEOUT_S = 180.0    # cold start (server spawn + model load)
WAKE_TIMEOUT_S = 30.0        # server already warm

CORE_ROOT = Path(__file__).resolve().parents[1]   # the study-core checkout


class WiniPlatform:
    def __init__(self, server_url: str = "http://127.0.0.1:8123",
                 store_dir: Path | None = None,
                 manage_server: bool = True,
                 fake_display: bool = False,
                 no_touch: bool = False,
                 log=print):
        self._log = log
        self.server_url = server_url.rstrip("/")
        self.store_dir = Path(store_dir or (CORE_ROOT / "rag_store"))
        # Never spawn a local server for a remote brain (Cloud Run).
        self.manage_server = manage_server and (
            "127.0.0.1" in self.server_url or "localhost" in self.server_url)

        driver = None
        if fake_display:
            from .display.display_thread import NullDriver
            driver = NullDriver()
        self.display = DisplayThread(driver=driver)

        self.head = None if no_touch else SerialHead(
            on_chin=self._on_chin_level, log=log)

        # chin-hold state machine (written on the serial read thread, read on
        # the tick — single-writer per field, GIL-atomic floats/bools)
        self._hold_start: float | None = None
        self._last_true = 0.0
        self._fired = False

        # blush reflex
        self._chin_level = False
        self._blushing = False
        self._blush_until = 0.0
        self._last_blush_trigger = 0.0

        # thinking face
        self._thinking = False
        self._think_started = 0.0
        self._prev_emotion = IDLE_EMOTION
        self._gaze_tick = 0

        # startup / client
        self._starting = False
        self._loading_dots = 0
        self._client_thread: threading.Thread | None = None
        self._client_stop = threading.Event()
        self._server_proc: subprocess.Popen | None = None

        self._stop = threading.Event()

    # ── brain service helpers ────────────────────────────────────────────────

    def _health_ready(self) -> bool:
        try:
            with urllib.request.urlopen(self.server_url + "/health",
                                        timeout=1.0) as r:
                return bool(json.load(r).get("ready"))
        except Exception:  # noqa: BLE001
            return False

    def _server_alive(self) -> bool:
        return self._server_proc is not None and self._server_proc.poll() is None

    def _spawn_server(self) -> None:
        logs = CORE_ROOT / "logs"
        logs.mkdir(exist_ok=True)
        port = self.server_url.rsplit(":", 1)[-1]
        out = open(logs / "server.log", "ab")
        self._server_proc = subprocess.Popen(
            [sys.executable, "-u", "wini_server.py", "--port", port],
            cwd=str(CORE_ROOT), stdout=out, stderr=subprocess.STDOUT,
            start_new_session=(os.name == "posix"))
        self._log(f"[platform] spawned wini_server.py (pid {self._server_proc.pid}) "
                  f"-> {logs / 'server.log'}")

    @staticmethod
    def _pin_usb_audio() -> None:
        """run_thin.sh semantics: pin PULSE_SINK/PULSE_SOURCE to the USB card
        (the onboard card re-grabs the PulseAudio default, runbook §4)."""
        script = os.getenv(
            "WINI_AUDIO_SELECT",
            os.path.expanduser("~/ROS2WS_audio_pipeline/select_usb_audio.sh"))
        if not os.path.exists(script):
            return
        try:
            out = subprocess.run(["bash", script, "--export"],
                                 capture_output=True, text=True, timeout=15)
            for line in out.stdout.splitlines():
                line = line.strip()
                if line.startswith("export ") and "=" in line:
                    key, val = line[len("export "):].split("=", 1)
                    os.environ[key.strip()] = val.strip().strip('"').strip("'")
            print(f"[platform] audio pinned: "
                  f"PULSE_SINK={os.environ.get('PULSE_SINK')} "
                  f"PULSE_SOURCE={os.environ.get('PULSE_SOURCE')}")
        except Exception as e:  # noqa: BLE001
            print(f"[platform] audio pin failed (continuing): {e}")

    # ── thinking face (called from the ClientThread via InProcSink) ─────────

    def set_thinking(self, active: bool) -> None:
        if active:
            if not self._thinking:
                self._prev_emotion = self.display.get_emotion()
                self._gaze_tick = 0
                self._thinking = True
            self._think_started = time.monotonic()   # re-assert extends it
        elif self._thinking:
            self._thinking = False
            self._restore_face()

    def _restore_face(self) -> None:
        self.display.set_emotion(*self._prev_emotion)
        self.display.set_gaze(0.0, 0.0)

    # ── touch callbacks (serial read thread — keep fast) ────────────────────

    def _on_chin_level(self, level: bool) -> None:
        now = time.monotonic()
        # hold detection (wini_touch_trigger port)
        if level:
            self._last_true = now
            if self._hold_start is None:
                self._hold_start = now
        else:
            if now - self._last_true > RELEASE_GRACE_S:
                self._hold_start = None
                self._fired = False   # released -> re-arm
        # blush reflex (wini_chin_reaction_node port): debounced rising edge
        rising = level and not self._chin_level
        self._chin_level = level
        if rising and now - self._last_blush_trigger >= BLUSH_DEBOUNCE_S:
            self._last_blush_trigger = now
            self._blush_until = now + BLUSH_HOLD_S
            if not self._blushing:
                self._blushing = True
                self._log("[platform] chin touched -> BLUSH")
            if not self._thinking:   # thinking face owns the screen mid-turn
                self.display.set_emotion("BLUSH", BLUSH_INTENSITY)

    # ── client lifecycle ─────────────────────────────────────────────────────

    def _client_alive(self) -> bool:
        return self._client_thread is not None and self._client_thread.is_alive()

    def _trigger(self) -> None:
        if self._starting:
            return
        if self._client_alive():
            self._log("[platform] chin hold: client already awake, ignoring")
            self.display.show_overlay(ui_cards.awake_card(), timeout_s=2.0)
            return
        self._starting = True
        self._loading_dots = 0
        self.display.show_overlay(ui_cards.loading_card(0))
        threading.Thread(target=self._start_pipeline,
                         name="wini-start", daemon=True).start()

    def _start_pipeline(self) -> None:
        wake_only = self._health_ready()   # brain warm, client asleep after "bye"
        self._log("[platform] chin hold: "
                  + ("waking client" if wake_only else "cold-starting brain"))
        if not wake_only and self.manage_server and not self._server_alive():
            self._spawn_server()
        deadline = WAKE_TIMEOUT_S if wake_only else STARTUP_TIMEOUT_S
        t0 = time.monotonic()
        while time.monotonic() - t0 < deadline and not self._stop.is_set():
            if self._health_ready():
                self._starting = False
                self.display.show_overlay(ui_cards.ready_card(), timeout_s=2.5)
                self._start_client()
                self._log("[platform] pipeline ready")
                return
            time.sleep(1.0 if wake_only else 2.0)
        self._starting = False
        if not self._stop.is_set():
            self._log("[platform] brain did not become ready in time")
            self.display.show_overlay(ui_cards.failed_card("check logs/server.log"),
                                      timeout_s=5.0)

    def _start_client(self) -> None:
        if self._client_alive():
            return
        self._client_stop = threading.Event()
        self._client_thread = threading.Thread(
            target=self._client_worker, name="wini-client", daemon=True)
        self._client_thread.start()

    def _client_worker(self) -> None:
        from wini_client.client import BrainClient, run_session
        from wini_client.display_sinks import InProcSink

        self._pin_usb_audio()
        sink = InProcSink(self.store_dir, self.display,
                          set_thinking=self.set_thinking)
        brain = BrainClient(self.server_url)
        try:
            brain.wait_ready(timeout_s=60.0)
            reason = run_session(brain, sink, trigger="vad",
                                 exit_on_session_end=True,
                                 stop_event=self._client_stop)
            self._log(f"[platform] client session over ({reason}) — sleeping; "
                      "hold chin to wake.")
        except Exception as e:  # noqa: BLE001
            self._log(f"[platform] client loop died: {e}")
        finally:
            self.set_thinking(False)
            self.display.clear_overlay()

    def _stop_client(self) -> None:
        if not self._client_alive():
            return
        # stop via the event + short-timeout stream reads — PortAudio blocking
        # reads ignore signals, so never thread-kill (plan §9).
        self._client_stop.set()
        self._client_thread.join(timeout=10.0)
        if self._client_thread.is_alive():
            self._log("[platform] WARNING: client thread did not stop in 10 s")

    # ── main loop ────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        now = time.monotonic()
        # chin hold fires once per hold
        hold_start = self._hold_start
        if hold_start is not None and not self._fired and now - hold_start >= HOLD_S:
            self._fired = True
            self._trigger()
        # thinking face animation (emotion re-assert + wandering up-gaze)
        if self._thinking:
            if now - self._think_started > THINK_TIMEOUT_S:
                self._log("[platform] thinking face timed out; restoring")
                self._thinking = False
                self._restore_face()
            else:
                name, intensity = THINK_EMOTION
                self.display.set_emotion(name, intensity)
                side = -0.55 if (self._gaze_tick // GAZE_SWING_TICKS) % 2 else 0.55
                self.display.set_gaze(side, -0.6, 0.8)
                self._gaze_tick += 1
        # blush revert
        if self._blushing and now >= self._blush_until:
            self._blushing = False
            if not self._thinking:
                self.display.set_emotion(*IDLE_EMOTION)
                self._log(f"[platform] blush done -> {IDLE_EMOTION[0]}")
        # loading card animation while a startup sequence is in flight
        if self._starting:
            self._loading_dots += 1
            self.display.show_overlay(ui_cards.loading_card(self._loading_dots))

    def run(self, autostart: bool = False) -> None:
        self.display.start()
        if self.head is not None:
            self.head.start()
        self._log(f"[platform] up: hold chin {HOLD_S:.0f}s to start/wake; "
                  f"brain={self.server_url} "
                  f"(managed={'yes' if self.manage_server else 'no'})")
        if autostart:
            self._starting = True
            self.display.show_overlay(ui_cards.loading_card(0))
            threading.Thread(target=self._start_pipeline,
                             name="wini-start", daemon=True).start()
        try:
            while not self._stop.is_set():
                self._tick()
                time.sleep(TICK_S)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self._stop.set()
        self._log("[platform] shutting down...")
        self._stop_client()
        if self.head is not None:
            self.head.shutdown()
        self.display.stop()
        if self._server_alive():
            self._log("[platform] stopping managed wini_server.py")
            self._server_proc.terminate()
            try:
                self._server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._server_proc.kill()
