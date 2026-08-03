"""Board Buddy device sink — the client-side manager of the pygame child (§3.2, §6.1, §10.3).

The renderer stays on the Pi, the brain in the cloud (§0a). The cloud brain authors a small
Board Buddy JSON payload and ships it over the wire; THIS module — running in the Python
client next to the panel — owns the child Board Buddy pygame surface: it spawns it, feeds it
payloads, reads its completion acks, forwards the LVGL control-strip actions
(scrub/pause/close), and tears it down. It also tells the LVGL parent (over the mode channel)
to suppress its figure card while Board Buddy owns the 0-845 region and to show the 845-1024
control strip — LVGL is the parent, Board Buddy the child (§0a).

Two drivers use it, both through :meth:`handle`:
  * the **compiled/turn_meta path** (working today): a turn's earned visual rides a
    ``board_payload`` on the visual directive; the client opens → boards → closes around the
    streamed audio.
  * the **segment loop** (§10.2, cloud Phase 4): the brain emits ``board_open`` /
    ``board`` / ``speak`` / ``board_close`` verbs; :meth:`handle` executes each and
    :meth:`wait_animation` provides the completion round-trip the loop needs.

Import-safe: spawning needs pygame + the installed ``board_buddy`` package, but nothing here
imports them — the child process does (:mod:`wini_client.board_buddy_player`). On a device
without them the child acks ``unavailable`` and the sink degrades (the caller falls back to
the crop / scene-PNG path). A crashed child never takes the client down (§6.1).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

READY_TIMEOUT_S = 12.0        # matplotlib prewarm + window up (cold); generous on the Pi
ANIM_TIMEOUT_S = 30.0         # a single board animation should never run longer


class BoardBuddySink:
    """Owns the Board Buddy child process and the LVGL card-suppression handshake.

    ``chan`` is the mode channel to the LVGL UI (``ModeChannel`` from mode_channel.py); when
    present, ``board_open`` / ``board_close`` verbs are forwarded so the C parent hides its
    figure card and shows the control strip. ``on_speak`` (optional) is called with a
    segment's speech text on a ``speak`` verb (the client wires it to Cloud TTS)."""

    def __init__(self, chan=None, *, on_speak=None, log=print, python_exe: str | None = None,
                 env_extra: dict | None = None):
        self.chan = chan
        self.on_speak = on_speak
        self.log = log
        self._py = python_exe or sys.executable
        self._env_extra = dict(env_extra or {})
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()
        self.active = False                       # Board Buddy owns 0-845 right now
        self._ready = threading.Event()
        self._anim_done = threading.Event()
        self._unavailable = False                 # child reported no pygame/board_buddy

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def _child_env(self) -> dict:
        env = dict(os.environ)
        # Position the child window at the top-left of the panel (§0a).
        env.setdefault("SDL_VIDEO_WINDOW_POS", "0,0")
        # Force native Wayland backend so the labwc window-rule for "wini-board-buddy"
        # (fixedPosition + MoveTo 0,0) applies correctly.  Without this the child
        # inherits only DISPLAY=:0 from wini_client (which runs without WAYLAND_DISPLAY
        # in its own env), SDL falls back to X11/Xwayland, and the labwc rule never
        # fires — so the window appears off-screen / behind LVGL on the physical panel.
        xdg_rt = env.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        env.setdefault("WAYLAND_DISPLAY", "wayland-0")
        env.setdefault("XDG_RUNTIME_DIR", xdg_rt)
        env.setdefault("SDL_VIDEODRIVER", "wayland")
        env.update(self._env_extra)
        return env

    def open(self) -> bool:
        """Spawn the child, wait for it to be ready, and suppress the LVGL card. Returns
        False (and degrades) if Board Buddy is unavailable or the child never readies."""
        with self._lock:
            if self.active and self._proc and self._proc.poll() is None:
                return True
            if self._unavailable:
                return False
            try:
                self._proc = subprocess.Popen(
                    [self._py, "-u", "-m", "wini_client.board_buddy_player"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    env=self._child_env(), text=True, bufsize=1)
            except Exception as e:  # noqa: BLE001 — spawn failure degrades to the fallback path
                self.log(f"[board] spawn failed: {e}")
                return False
            self._ready.clear()
            self._anim_done.clear()
            self._reader = threading.Thread(target=self._read_acks, name="bb-acks",
                                            daemon=True)
            self._reader.start()
        if not self._ready.wait(READY_TIMEOUT_S) or self._unavailable:
            self.log("[board] child not ready — degrading to fallback")
            self._kill()
            return False
        self.active = True
        self._notify_lvgl({"cmd": "board_open"})     # LVGL hides its figure card
        self.log("[board] Board Buddy surface up (0,0 600x845); LVGL card suppressed")
        return True

    def board(self, payload: list[dict], *, tmax: float = 0.0, animated: bool = False,
              wait: bool = False) -> bool:
        """Hand the child a payload to render. With ``wait=True`` block until the animation
        completes (the segment-loop completion round-trip, §10.2); the caller's own speech
        runs concurrently and is NOT clamped to this (memory answer-length-stays-dynamic)."""
        if not self.active and not self.open():
            return False
        self._anim_done.clear()
        if not self._send_child({"cmd": "board", "payload": payload, "tmax": tmax}):
            return False
        if wait:
            return self.wait_animation(ANIM_TIMEOUT_S)
        return True

    def wait_animation(self, timeout: float = ANIM_TIMEOUT_S) -> bool:
        """Block until the child acks ``animation_done`` (or the timeout). Used by the
        segment loop's ``wait_ack``; the compiled/turn_meta path does not wait."""
        return self._anim_done.wait(timeout)

    def scrub(self, t: float) -> None:
        self._send_child({"cmd": "scrub", "t": float(t)})

    def pause(self) -> None:
        self._send_child({"cmd": "pause"})

    def resume(self) -> None:
        self._send_child({"cmd": "resume"})

    def close(self) -> None:
        """Tear the child down and restore the LVGL card (§10.3)."""
        if self._proc is not None:
            self._send_child({"cmd": "close"})
        self._kill()
        if self.active:
            self._notify_lvgl({"cmd": "board_close"})       # LVGL restores its card
        self.active = False

    # ── wire-verb dispatch (both drivers go through here) ──────────────────────
    def handle(self, verb: dict) -> None:
        """Execute one wire verb from the brain: board_open | board | speak | board_close.

        A speech verb is delegated to ``on_speak`` (the client owns the speaker); board
        verbs drive the child. Unknown verbs are ignored (forward-compatible)."""
        cmd = verb.get("cmd")
        if cmd == "board_open":
            self.open()
        elif cmd == "board":
            # In the segment loop the brain waits on the device ack, so block here on the
            # animation; a static board returns immediately (its ack fires on first frame).
            self.board(verb.get("payload") or [], tmax=float(verb.get("tmax") or 0.0),
                       animated=bool(verb.get("animated")), wait=bool(verb.get("wait", True)))
        elif cmd == "speak":
            if self.on_speak is not None and verb.get("text"):
                self.on_speak(verb["text"])
        elif cmd == "board_close":
            self.close()

    # ── internals ──────────────────────────────────────────────────────────────
    def _send_child(self, obj: dict) -> bool:
        proc = self._proc
        if proc is None or proc.poll() is not None or proc.stdin is None:
            return False
        try:
            proc.stdin.write(json.dumps(obj, separators=(",", ":")) + "\n")
            proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def _read_acks(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ack = json.loads(line)
            except ValueError:
                continue
            kind = ack.get("ack")
            if kind == "ready":
                self._ready.set()
            elif kind == "unavailable":
                self._unavailable = True
                self._ready.set()             # unblock open(); it checks _unavailable
                self.log(f"[board] renderer unavailable: {ack.get('error')}")
            elif kind == "animation_done":
                self._anim_done.set()
            elif kind in ("load_error", "render_error"):
                self.log(f"[board] child {kind}: {ack.get('error')}")
                self._anim_done.set()          # never hang the loop on a child error
            elif kind == "diagnostic":
                self.log(f"[board] diagnostic warnings: {ack.get('warnings')}")
        # stdout closed: the child exited. If it went down mid-turn, restore the card.
        if self.active:
            self.log("[board] child exited; restoring LVGL card")
            self._notify_lvgl({"cmd": "board_close"})
            self.active = False
        self._ready.set()
        self._anim_done.set()

    def _kill(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:  # noqa: BLE001
            pass

    def _notify_lvgl(self, obj: dict) -> None:
        if self.chan is not None:
            try:
                self.chan.send(obj)
            except Exception as e:  # noqa: BLE001 — a UI cue must never cost a turn
                self.log(f"[board] LVGL notify failed: {e}")
