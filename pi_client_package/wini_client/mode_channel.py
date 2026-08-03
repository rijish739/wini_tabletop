"""Mode channel — the bidirectional device seam between the on-device UI and the client.

The LVGL touch UI (`wini_ui/`, a separate C process) connects to this local TCP
socket. It carries two directions of newline-delimited flat-JSON on ONE connection:

    UI -> client   {"event": "mode_selected", "mode": "EXPLAIN"|"PRACTICE"|"TEST"}\n
    client -> UI   {"cmd": "question", "n": "...", "text": "..."}\n   (and friends)

The client holds the latest mode in a `ModeState` and stamps it on every voice turn
(the `X-Wini-Mode` header). It also drives the UI FORWARD each turn via `send()` —
the `ModeChannelSink` (display_sinks.py) serializes the turn (thinking / question /
score / feedback / status / stage / progress) into the `{"cmd": ...}` lines the UI's
`wini_app_dispatch` applies. This is the Part 12 pedagogy-mode seam
(`PART12_PEDAGOGY_MODES_PLAN.md` §4.1 / §5.9); on the eventual ESP32-P4 the UI and the
client share one firmware and this socket collapses to a direct in-process call.

Never crashes a turn: all socket work runs on a daemon thread and swallows errors —
if the port cannot bind, the mode UI is simply disabled and the client runs as before;
if no UI is connected, `send()` is a silent no-op.
"""

from __future__ import annotations

import json
import socket
import threading

VALID_MODES = ("EXPLAIN", "PRACTICE", "TEST")

# The UI reader queues each inbound line into a fixed slot (ipc.c IPC_LINE_MAX)
# and drains it into a same-sized buffer, so a longer line is truncated mid-JSON
# and fails to parse. Keep every command line under that; the ModeChannelSink
# also caps individual fields, this is the last-ditch guard.
#
# 2026-07-23: raised 480 -> 1900 alongside IPC_LINE_MAX 512 -> 2048. A full
# explanation is 300-900 characters and the old budget forced the sink to clip
# it to 200, which is what put "..." mid-sentence on the panel. THESE TWO
# NUMBERS MOVE TOGETHER — MAX_LINE must stay below IPC_LINE_MAX.
MAX_LINE = 1900


class ModeState:
    """Thread-safe holder for the current pedagogy mode + a 'selected' event.

    `mode` starts None (≈ EXPLAIN / today's behavior). `wait_for_selection` lets the
    client optionally block its first turn until the UI sends a choice.
    """

    def __init__(self, mode: str | None = None):
        self._lock = threading.Lock()
        self._mode = mode
        self.selected = threading.Event()
        # Mic-mute toggle from the UI's pause button: while set, the client
        # neither records nor runs brain turns (the student is talking to
        # someone else). Cleared by the second tap.
        self.paused = threading.Event()
        if mode:
            self.selected.set()

    @property
    def mode(self) -> str | None:
        with self._lock:
            return self._mode

    def set(self, mode: str) -> None:
        with self._lock:
            self._mode = mode
        self.selected.set()

    def wait_for_selection(self, timeout: float | None = None) -> bool:
        return self.selected.wait(timeout)

    def clear(self) -> None:
        """Re-arm: forget the current mode so wait_for_selection blocks until the
        UI sends a fresh tap (used when the device sleeps after 'bye')."""
        with self._lock:
            self._mode = None
        self.selected.clear()


class ModeChannel:
    """The TCP mode-channel server: one UI client at a time (the device has a
    single panel). Reads `mode_selected` into a `ModeState` AND holds the accepted
    connection so `send()` can push `{"cmd": ...}` command lines back to the UI on
    the same socket.

    Reader and writer live on different threads (the accept/recv loop vs. the
    client's turn thread), which is safe: a TCP socket is full-duplex, and every
    write is serialized under `_send_lock` so command lines never interleave.
    """

    def __init__(self, mode_state: ModeState, port: int = 8140,
                 host: str = "127.0.0.1", on_mode=None, stop_event=None, log=print):
        self.mode_state = mode_state
        self.port = port
        self.host = host
        self.on_mode = on_mode
        self.stop_event = stop_event
        self.log = log
        self._conn: socket.socket | None = None
        self._conn_lock = threading.Lock()   # guards the _conn reference
        self._send_lock = threading.Lock()    # serializes writes on that conn
        self._thread: threading.Thread | None = None
        # Latching state the UI needs no matter WHEN it connects (today: the
        # brain-ready signal that releases the splash). The UI is normally
        # launched only after the brain is warm, i.e. AFTER we would have sent
        # it, so a plain send() would go to nobody.
        self._sticky: list[dict] = []

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> "ModeChannel":
        self._thread = threading.Thread(target=self._run, name="wini-mode-channel",
                                        daemon=True)
        self._thread.start()
        return self

    def _stopping(self) -> bool:
        return self.stop_event is not None and self.stop_event.is_set()

    def _set_conn(self, conn: socket.socket | None) -> None:
        with self._conn_lock:
            self._conn = conn
        if conn is not None:
            for obj in list(self._sticky):
                self.send(obj)

    def set_sticky(self, obj: dict) -> None:
        """Send `obj` now AND re-send it to every UI that connects later.

        For one-shot lifecycle facts (brain ready) — not for turn content, which
        would be stale on a reconnect."""
        self._sticky.append(obj)
        self.send(obj)

    # ── client -> UI (the emitter path) ───────────────────────────────────────
    def send(self, obj: dict) -> bool:
        """Serialize `obj` to one flat-JSON command line and push it to the
        connected UI. No-op (returns False) if no UI is connected, the payload is
        oversized, or the socket is gone — a UI cue must never cost a turn.

        `ensure_ascii=False` keeps UTF-8 bytes intact (the UI's flat-JSON scanner
        takes `\\uXXXX`/`\\n` escapes literally); callers are expected to have
        already reduced values to short single-line ASCII."""
        with self._conn_lock:
            conn = self._conn
        if conn is None:
            return False
        try:
            line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return False
        line = line.replace("\n", " ").replace("\r", " ")   # never split a command
        data = (line + "\n").encode("utf-8", "replace")
        if len(data) > MAX_LINE:
            self.log(f"[mode] dropping oversized command ({len(data)}B): {line[:60]}...")
            return False
        with self._send_lock:
            with self._conn_lock:
                conn = self._conn
            if conn is None:
                return False
            try:
                conn.sendall(data)
                return True
            except OSError:
                # broken pipe / reset: drop the conn so the recv loop re-accepts.
                with self._conn_lock:
                    if self._conn is conn:
                        self._conn = None
                return False

    # ── UI -> client (the mode-selection reader) ──────────────────────────────
    def _handle(self, conn: socket.socket) -> None:
        buf = b""
        with conn:
            conn.settimeout(1.0)
            while not self._stopping():
                try:
                    chunk = conn.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        self.log(f"[mode] bad line: {line!r}")
                        continue
                    if obj.get("event") == "pause":
                        # Mic-mute toggle (pause_button.c). The status chip is
                        # echoed back so the header reflects the muted state.
                        if obj.get("on"):
                            self.mode_state.paused.set()
                            self.log("[mode] paused (mic muted by UI)")
                            self.send({"cmd": "status", "v": "offline"})
                        else:
                            self.mode_state.paused.clear()
                            self.log("[mode] resumed (mic live)")
                            self.send({"cmd": "status", "v": "listening"})
                        continue
                    if obj.get("event") != "mode_selected":
                        continue
                    mode = str(obj.get("mode", "")).strip().upper()
                    if mode not in VALID_MODES:
                        self.log(f"[mode] ignoring unknown mode: {mode!r}")
                        continue
                    self.mode_state.set(mode)
                    self.log(f"[mode] selected: {mode}")
                    if self.on_mode is not None:
                        try:
                            self.on_mode(mode)
                        except Exception as e:  # noqa: BLE001 — a UI cue must not cost a turn
                            self.log(f"[mode] on_mode error: {e}")

    def _run(self) -> None:
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((self.host, self.port))
            srv.listen(1)
            srv.settimeout(1.0)
        except OSError as e:
            self.log(f"[mode] could not bind {self.host}:{self.port}: {e} (mode UI disabled)")
            return
        self.log(f"[mode] channel listening on {self.host}:{self.port}")
        while not self._stopping():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self._set_conn(conn)      # publish it for send() before we block on recv
            try:
                self._handle(conn)
            except Exception as e:  # noqa: BLE001 — one bad connection must not kill the channel
                self.log(f"[mode] connection error: {e}")
            finally:
                self._set_conn(None)
        try:
            srv.close()
        except OSError:
            pass


def serve(mode_state: ModeState, port: int = 8140, host: str = "127.0.0.1",
          on_mode=None, stop_event=None, log=print) -> ModeChannel:
    """Start the mode-channel server on a daemon thread; return the live
    `ModeChannel` (call `.send({...})` to drive the UI). Backward compatible with
    the old thread-returning contract — callers that ignore the return still get
    a running server."""
    return ModeChannel(mode_state, port=port, host=host, on_mode=on_mode,
                       stop_event=stop_event, log=log).start()
