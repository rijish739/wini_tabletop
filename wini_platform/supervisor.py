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
from . import ui_cards

# SerialHead is imported lazily (in __init__) so the platform can run on a device
# without pyserial / the STM32 head board — e.g. the Pi DSI + touch-UI build,
# where the LVGL picker replaces the chin sensor. See --no-touch / --ui.

# ── tunables (carried over from the ROS nodes) ──────────────────────────────
HOLD_S = 3.0                 # chin hold needed to trigger start/wake
RELEASE_GRACE_S = 0.3        # micro-release shorter than this keeps the hold
TICK_S = 0.2                 # supervisor housekeeping tick

THINK_EMOTION = ("XEYES", 12)     # X-eyes "loading/busy" look (replaced the CONFUSED squint)
THINK_TIMEOUT_S = 120.0           # safety: never stay in thinking face forever
GAZE_SWING_TICKS = 8              # 0.2 s ticks per gaze side (~1.6 s left/right)

BLUSH_INTENSITY = 12
BLUSH_HOLD_S = 3.0
BLUSH_DEBOUNCE_S = 0.4
IDLE_EMOTION = ("NEUTRAL", 15)   # eyes fully open at rest (15 = full neutral)

# HEAD-touch demo: hold the top (head) sensor to cycle emotions one-by-one;
# release returns to neutral. Only runs when idle (not thinking / not starting).
HEAD_CYCLE = ["HAPPY", "SAD", "ANGRY", "SURPRISED", "CONFUSED", "LOVE",
              "EXCITEMENT", "SMIRK", "DIZZY", "XEYES", "SLEEPY", "TIRED", "BLUSH"]
HEAD_CYCLE_INTENSITY = 15
HEAD_CYCLE_S = 1.0               # advance to the next emotion every ~1 s while held

STARTUP_TIMEOUT_S = 180.0    # cold start (server spawn + model load)
WAKE_TIMEOUT_S = 30.0        # server already warm

CORE_ROOT = Path(__file__).resolve().parents[1]   # the study-core checkout


class WiniPlatform:
    def __init__(self, server_url: str = "http://127.0.0.1:8123",
                 store_dir: Path | None = None,
                 manage_server: bool = True,
                 fake_display: bool = False,
                 no_touch: bool = False,
                 ui: bool = False,
                 ui_port: int = 8140,
                 ui_bin: Path | None = None,
                 log=print):
        self._log = log
        self.server_url = server_url.rstrip("/")
        self.store_dir = Path(store_dir or (CORE_ROOT / "rag_store"))
        # Never spawn a local server for a remote brain (Cloud Run).
        self.manage_server = manage_server and (
            "127.0.0.1" in self.server_url or "localhost" in self.server_url)

        # In UI mode the DSI is owned by wini_ui (LVGL), so the eyes DisplayThread
        # must NOT grab the ST7796S SPI panel — force the NullDriver there too.
        driver = None
        if fake_display or ui:
            from .display.display_thread import NullDriver
            driver = NullDriver()
        self.display = DisplayThread(driver=driver)

        if no_touch:
            self.head = None
        else:
            from .touch.serial_head import SerialHead
            self.head = SerialHead(on_chin=self._on_chin_level,
                                   on_head=self._on_head_level, log=log)

        # LVGL touch-UI mode (Pi DSI): the supervisor launches wini_ui and the
        # client drives it over the mode channel (ModeChannelSink) instead of the
        # in-process eyes DisplayThread. A card tap picks the mode AND wakes the
        # client (the chin-hold analogue). See wini_ui/ + wini_client/mode_channel.py.
        self._stop = threading.Event()
        self.ui = ui
        self.ui_port = ui_port
        self.ui_bin = Path(ui_bin) if ui_bin else (CORE_ROOT / "wini_ui" / "build" / "wini_ui")
        self.mode_state = None
        self.mode_channel = None
        self._ui_proc: subprocess.Popen | None = None
        if self.ui:
            from wini_client.mode_channel import ModeChannel, ModeState
            self.mode_state = ModeState()
            self.mode_channel = ModeChannel(
                self.mode_state, port=self.ui_port,
                on_mode=self._on_ui_mode, stop_event=self._stop, log=log)

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

        # head-touch emotion cycle (demo) — replaced by the emotion engine
        # when a GPIO touch reader is available, but kept as fallback.
        self._head_level = False
        self._head_cycling = False
        self._head_idx = 0
        self._head_last_advance = 0.0

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

        # ── Emotion-based touch audio engine ─────────────────────────────
        # GPIO touch reader (direct TTP223 on GPIO22, Pi 5 gpiochip4).
        # Falls back gracefully: if lgpio is unavailable or the pin can't be
        # claimed, the engine simply doesn't start — everything else works.
        self._gpio_touch = None
        self._gesture_rec = None
        self.emotion_engine = None
        self.audio_manager = None
        self._init_emotion_engine(log)

    def _init_emotion_engine(self, log) -> None:
        try:
            from wini_client.sound_bank import SoundBank
            from wini_client.audio_manager import AudioManager
            from wini_client.client import play_pcm
            
            sound_bank = SoundBank()
            self.audio_manager = AudioManager(play_fn=play_pcm, sound_bank=sound_bank, log=log)
        except Exception as e:
            log(f"[platform] failed to initialize audio manager: {e}")
            return

        try:
            from .touch_gestures import TouchGestureRecognizer
            from .emotion_engine import EmotionEngine

            self._gesture_rec = TouchGestureRecognizer(
                on_single_tap=lambda: self.emotion_engine.on_single_tap() if self.emotion_engine else None,
                on_double_tap=lambda: self.emotion_engine.on_double_tap() if self.emotion_engine else None,
                on_hold_start=lambda: self.emotion_engine.on_hold_start() if self.emotion_engine else None,
                on_hold_end=lambda dur: self.emotion_engine.on_hold_end(dur) if self.emotion_engine else None,
                on_pat_sequence=lambda count: self.emotion_engine.on_pat_sequence(count) if self.emotion_engine else None,
                log=log
            )

            self.emotion_engine = EmotionEngine(self.audio_manager, log=log)
        except Exception as e:
            log(f"[platform] failed to initialize emotion engine: {e}")
            return

        # If touch is enabled, initialize the GPIO touch reader
        if self.head is not None:
            try:
                from .touch.gpio_touch import GpioTouchReader
                self._gpio_touch = GpioTouchReader(
                    gpio_pin=22,
                    chip=4,
                    on_touch=self._gesture_rec.on_level,
                    log=log
                )
            except Exception as e:
                log(f"[platform] failed to initialize GpioTouchReader: {e}")

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

    # ── LVGL touch UI (Pi DSI panel) ─────────────────────────────────────────

    def _ui_send(self, obj: dict) -> None:
        """Best-effort command to the LVGL UI (no-op when not in UI mode)."""
        if self.mode_channel is not None:
            self.mode_channel.send(obj)

    def _ui_alive(self) -> bool:
        return self._ui_proc is not None and self._ui_proc.poll() is None

    def _start_ui(self) -> None:
        """Launch the wini_ui LVGL process on the DSI. Best-effort: a missing
        binary or X display disables the panel but never stops the platform."""
        if self._ui_alive():
            return
        if not self.ui_bin.exists():
            self._log(f"[platform] wini_ui binary not found at {self.ui_bin} "
                      "(build it under wini_ui/build) — UI disabled")
            return
        env = dict(os.environ)
        env.setdefault("DISPLAY", ":0")
        env.setdefault("XAUTHORITY", os.path.expanduser("~/.Xauthority"))
        # The voice client owns the reSpeaker's single playback substream —
        # the UI's SDL audio must never claim it or Wini's voice goes silent
        # (wini_client/SPEAKER_TROUBLESHOOTING.md; main.c also defaults dummy).
        env.setdefault("SDL_AUDIODRIVER", "dummy")
        logs = CORE_ROOT / "logs"
        logs.mkdir(exist_ok=True)
        out = open(logs / "wini_ui.log", "ab")
        try:
            self._ui_proc = subprocess.Popen(
                [str(self.ui_bin), "--port", str(self.ui_port)],
                cwd=str(CORE_ROOT), env=env, stdout=out,
                stderr=subprocess.STDOUT,
                start_new_session=(os.name == "posix"))
            self._log(f"[platform] launched wini_ui (pid {self._ui_proc.pid}) "
                      f"-> {logs / 'wini_ui.log'}")
        except Exception as e:  # noqa: BLE001 — the panel is optional
            self._log(f"[platform] could not launch wini_ui: {e}")

    def _on_ui_mode(self, mode: str) -> None:
        """A card tap picked a pedagogy mode; treat it as the wake gesture too —
        if the client is asleep, start it (the chin-hold analogue on the Pi)."""
        if not self._client_alive() and not self._starting:
            self._log(f"[platform] UI mode '{mode}' — waking client")
            self._trigger()

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

    def _on_head_level(self, level: bool) -> None:
        # serial read thread — keep fast; the cycling is driven from _tick.
        self._head_level = level
        # Also feed the gesture recognizer if the emotion engine is active.
        if self._gesture_rec is not None:
            self._gesture_rec.on_level(level)

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
        self._log("[platform] trigger: "
                  + ("waking client" if wake_only else "cold-starting brain"))
        self._ui_send({"cmd": "loading", "on": 1,
                       "text": "Waking Wini..." if wake_only else "Wini is waking up..."})
        if not wake_only and self.manage_server and not self._server_alive():
            self._spawn_server()
        deadline = WAKE_TIMEOUT_S if wake_only else STARTUP_TIMEOUT_S
        t0 = time.monotonic()
        while time.monotonic() - t0 < deadline and not self._stop.is_set():
            if self._health_ready():
                self._starting = False
                self.display.show_overlay(ui_cards.ready_card(), timeout_s=2.5)
                self._ui_send({"cmd": "loading", "on": 0})
                self._start_client()
                self._log("[platform] pipeline ready")
                return
            time.sleep(1.0 if wake_only else 2.0)
        self._starting = False
        if not self._stop.is_set():
            self._log("[platform] brain did not become ready in time")
            self.display.show_overlay(ui_cards.failed_card("check logs/server.log"),
                                      timeout_s=5.0)
            self._ui_send({"cmd": "loading", "on": 1,
                           "text": "Start failed - check logs"})

    def _start_client(self) -> None:
        if self._client_alive():
            return
        self._client_stop = threading.Event()
        self._client_thread = threading.Thread(
            target=self._client_worker, name="wini-client", daemon=True)
        self._client_thread.start()

    def _wait_capture_ready(self, timeout_s: float = 25.0) -> bool:
        """Block until the mic actually captures a block. At boot PulseAudio's
        USB source can still be settling when the client starts, so the first
        read fails with ALSA EIO (-5)/PortAudioError and used to kill the whole
        session (looked like 'the model didn't load'). Retry a cheap one-block
        capture until it works instead of dying on that race; a warm source
        (wake path) passes on the first try (~50 ms)."""
        import sounddevice as sd
        from wini_client.client import RATE

        block = int(RATE * 0.05)
        deadline = time.monotonic() + timeout_s
        attempt = 0
        while not self._stop.is_set() and not self._client_stop.is_set():
            attempt += 1
            try:
                with sd.InputStream(samplerate=RATE, channels=1, dtype="int16",
                                    blocksize=block, device="pulse") as s:
                    s.read(block)
                if attempt > 1:
                    self._log(f"[platform] mic capture ready (after {attempt} tries)")
                return True
            except Exception as e:  # noqa: BLE001
                if time.monotonic() >= deadline:
                    self._log(f"[platform] mic not ready after {attempt} tries "
                              f"({e}); starting session anyway")
                    return False
                self._log(f"[platform] mic not ready (try {attempt}): {e}; retrying")
                time.sleep(1.0)
        return False

    def _client_worker(self) -> None:
        from wini_client.client import BrainClient, run_session

        self._pin_usb_audio()
        self._wait_capture_ready()
        # UI mode: drive the LVGL panel over the mode channel; the touch card
        # already selected the pedagogy mode (stamped per turn). Otherwise the
        # in-process eyes DisplayThread (the Jetson robot path) is unchanged.
        if self.ui:
            from wini_client.display_sinks import ModeChannelSink
            sink = ModeChannelSink(self.mode_channel, self.store_dir)
            mode_state = self.mode_state
            wake_hint = "tap a card to wake."
        else:
            from wini_client.display_sinks import InProcSink
            sink = InProcSink(self.store_dir, self.display,
                              set_thinking=self.set_thinking)
            mode_state = None
            wake_hint = "hold chin to wake."
        brain = BrainClient(self.server_url)
        try:
            brain.wait_ready(timeout_s=60.0)
            reason = run_session(brain, sink, trigger="vad",
                                 exit_on_session_end=True,
                                 stop_event=self._client_stop,
                                 mode_state=mode_state,
                                 audio_manager=self.audio_manager)
            self._log(f"[platform] client session over ({reason}) — sleeping; "
                      + wake_hint)
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
        # head-hold emotion cycle (manual demo) — only when the emotion engine
        # is NOT active (emotion engine replaces this feature).
        if self.emotion_engine is None:
            if self._head_level and not self._thinking and not self._starting:
                if not self._head_cycling:
                    self._head_cycling = True
                    self._head_idx = 0
                    self._head_last_advance = now
                    self.display.set_emotion(HEAD_CYCLE[0], HEAD_CYCLE_INTENSITY)
                elif now - self._head_last_advance >= HEAD_CYCLE_S:
                    self._head_idx = (self._head_idx + 1) % len(HEAD_CYCLE)
                    self._head_last_advance = now
                    self.display.set_emotion(HEAD_CYCLE[self._head_idx],
                                             HEAD_CYCLE_INTENSITY)
            elif self._head_cycling and not self._head_level:
                self._head_cycling = False
                if not self._thinking and not self._blushing:
                    self.display.set_emotion(*IDLE_EMOTION)
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
        # keep the LVGL panel alive: relaunch if it crashed (best-effort, no spam —
        # only when it had started and then exited, never when the binary is absent)
        if self.ui and self._ui_proc is not None and self._ui_proc.poll() is not None:
            self._log("[platform] wini_ui exited — relaunching")
            self._ui_proc = None
            self._start_ui()
        # Emotion engine tick (mood decay, state transitions, idle sounds)
        if self.emotion_engine is not None:
            self.emotion_engine.tick(TICK_S)

    def run(self, autostart: bool = False) -> None:
        self.display.start()
        if self.head is not None:
            self.head.start()
        if self._gpio_touch is not None:
            self._gpio_touch.start()
        if self.ui:
            self.mode_channel.start()      # server side of the mode channel
            self._start_ui()               # launch the LVGL panel on the DSI
        trigger_hint = ("tap a card" if self.ui
                        else f"hold chin {HOLD_S:.0f}s") + " to start/wake"
        self._log(f"[platform] up: {trigger_hint}; "
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
        if self.audio_manager is not None:
            self.audio_manager.shutdown()
        if self._gpio_touch is not None:
            self._gpio_touch.shutdown()
        if self.head is not None:
            self.head.shutdown()
        if self._ui_alive():
            self._log("[platform] stopping wini_ui")
            self._ui_proc.terminate()
            try:
                self._ui_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._ui_proc.kill()
        self.display.stop()
        if self._server_alive():
            self._log("[platform] stopping managed wini_server.py")
            self._server_proc.terminate()
            try:
                self._server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._server_proc.kill()
