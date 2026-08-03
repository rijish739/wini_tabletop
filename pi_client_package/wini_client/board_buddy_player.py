"""Board Buddy pygame CHILD process — the native 60 FPS surface (§0a, §6.1).

LVGL is the parent and owns the panel; when a turn needs a visual explanation the client
(:mod:`wini_client.board_buddy_sink`) spawns THIS process as a separate pygame/SDL surface
positioned at (0,0) sized 600x845 (the top region of the 600x1024 portrait panel). It runs
Board Buddy's own render loop + touch scrubber and is killed on ``board_close``. Board Buddy
is a **pure executor**: this child renders whatever payload it is handed and reports done.

IPC (deliberately tiny, newline-delimited JSON on stdin/stdout so the parent supervises it
like any subprocess and a crash never takes the parent down — §6.1):

    parent -> child (stdin)   {"cmd":"board","payload":[...],"tmax":<hint>}\n
                              {"cmd":"scrub","t":<seconds>}\n     (parent control strip)
                              {"cmd":"pause"} / {"cmd":"resume"} / {"cmd":"close"}\n
    child  -> parent (stdout) {"ack":"ready"}\n            (window up, matplotlib warm)
                              {"ack":"animation_done","beat":<id?>}\n

Board Buddy is FROZEN v1.0 and installed as a package on the Pi (§6.8); we import it, never
edit it. All imports that need hardware (pygame, board_buddy, matplotlib) happen INSIDE
:func:`main` so this module imports cleanly on a dev box without them (tests import the
sink, never spawn this).

winipi5 device risks resolved live on the board (§6.1, Phase 3), NOT here:
  * SDL under labwc/Wayland must present a windowed, positioned 600x845 surface (SDL
    Wayland backend, or Xwayland). ``SDL_VIDEODRIVER`` / ``SDL_VIDEO_WINDOW_POS`` are set
    from the environment the sink passes.
  * Touch routing: touches in 0-845 must reach this window's scrubber (Y 800-845); the
    845-1024 control strip belongs to the LVGL parent. The compositor routes by surface
    geometry; confirm on the winipi5 touch stack.
"""

from __future__ import annotations

import json
import os
import sys
import threading

VIEW_W = 600
VIEW_H = 800
SCRUBBER_H = 45
WIN_W, WIN_H = VIEW_W, VIEW_H + SCRUBBER_H       # 600x845

# Board background per theme — mirrors board_buddy.render() so an EMPTY surface
# (opened a beat before the first payload, or after a render error) shows a blank
# board, never the uninitialized black rectangle that would cover the panel.
_THEME_BG = {
    "light": (247, 235, 217),
    "chalkboard": (27, 59, 43),
    "graph_paper": (240, 244, 248),
}


def _emit(obj: dict) -> None:
    """One JSON line to the parent on stdout (flush — the parent reads line-by-line)."""
    try:
        sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
        sys.stdout.flush()
    except (OSError, ValueError):
        pass


class _StdinReader(threading.Thread):
    """Read parent commands off stdin on a daemon thread into a shared latest-command
    slot; the render loop polls it so blitting never blocks on IO."""

    def __init__(self):
        super().__init__(name="bb-stdin", daemon=True)
        self._lock = threading.Lock()
        self._queue: list[dict] = []
        self.closed = False

    def run(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("cmd") == "close":
                self.closed = True
                return
            with self._lock:
                self._queue.append(obj)
        # stdin closed (parent went away / EOF): exit the surface cleanly rather than
        # keep spinning the render loop forever on a dead pipe.
        self.closed = True

    def drain(self) -> list[dict]:
        with self._lock:
            out, self._queue = self._queue, []
        return out


def _prewarm_matplotlib() -> None:
    """matplotlib mathtext is slow on first use (§6.6) — do one throwaway render at startup
    so the first real board is not gated on font/mathtext init (mirrors the embedder prewarm)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig = plt.figure(figsize=(1, 1))
        fig.text(0.5, 0.5, r"$x^2$")
        fig.canvas.draw()
        plt.close(fig)
    except Exception:  # noqa: BLE001 — prewarm is best-effort
        pass


def _pil_to_surface(pygame, img):
    """PIL.Image -> pygame.Surface (Board Buddy render() returns a PIL image)."""
    return pygame.image.fromstring(img.tobytes(), img.size, img.mode)


def main() -> int:
    # Positioned, windowed surface at the top of the panel. SDL_VIDEO_WINDOW_POS is honoured
    # on X11; under labwc/Wayland the client cannot self-position, so a labwc window rule
    # keyed on the app_id below places + undecorates it (see the labwc bring-up, §6.1).
    os.environ.setdefault("SDL_VIDEO_WINDOW_POS", "0,0")
    os.environ.setdefault("SDL_VIDEO_WAYLAND_WMCLASS", "wini-board-buddy")
    os.environ.setdefault("SDL_VIDEO_X11_WMCLASS", "wini-board-buddy")
    borderless = os.environ.get("WINI_BB_BORDERLESS", "1") not in ("0", "false", "no")

    # Board Buddy v1.0 lives as a standalone module (frozen; ~/board_buddy_sandbox on the
    # Pi), not a pip package — put its dir on sys.path before importing. Override with
    # WINI_BB_PATH; default to the known sandbox location.
    bb_path = os.environ.get("WINI_BB_PATH") or os.path.expanduser("~/board_buddy_sandbox")
    if bb_path and bb_path not in sys.path:
        sys.path.insert(0, bb_path)
    try:
        import pygame
        from board_buddy import BoardBuddyCanvas       # frozen v1.0 (see WINI_BB_PATH)
    except Exception as e:  # noqa: BLE001 — no renderer here: tell the parent and exit clean
        _emit({"ack": "unavailable", "error": f"{type(e).__name__}: {e}"})
        return 2

    _prewarm_matplotlib()
    pygame.init()
    flags = pygame.NOFRAME if borderless else 0
    screen = pygame.display.set_mode((WIN_W, WIN_H), flags)
    pygame.display.set_caption("Wini Board Buddy")
    clock = pygame.time.Clock()

    theme = os.environ.get("WINI_BB_THEME", "light")
    bg = _THEME_BG.get(theme, _THEME_BG["light"])

    # Never present a black window. pygame's fresh surface is uninitialized (black);
    # if the parent opens the board a beat before the first payload, that black
    # rectangle covers the panel and reads as a "black screen". Paint the board
    # background immediately so an opening/empty surface is a blank board instead.
    try:
        screen.fill(bg)
        pygame.display.flip()
    except Exception:  # noqa: BLE001 — cosmetic; never block startup
        pass

    # This surface only takes touch (the scrubber) — never typed input. SDL enables
    # text input on window creation, which activates the Wayland input-method and
    # pops the on-screen keyboard (squeekboard) over the LVGL control strip. Stop it
    # so Board Buddy and the LVGL parent coexist cleanly on the panel.
    try:
        pygame.key.stop_text_input()
    except Exception:  # noqa: BLE001 — older SDL/pygame without the call: harmless
        pass

    canvas = BoardBuddyCanvas(width=VIEW_W, height=VIEW_H, theme=theme)
    reader = _StdinReader()
    reader.start()
    _emit({"ack": "ready"})

    have_payload = False
    t = 0.0                # animation clock (seconds)
    t_max = 0.0
    paused = False
    static_acked = False   # a static payload acks completion exactly once
    running = True
    while running:
        # 1) apply parent commands
        if reader.closed:
            break
        for cmd in reader.drain():
            kind = cmd.get("cmd")
            if kind == "board":
                diag = {}
                try:
                    diag = canvas.load_json(cmd.get("payload") or []) or {}
                except Exception as e:  # noqa: BLE001 — a bad payload degrades, never crashes
                    _emit({"ack": "load_error", "error": str(e)})
                    continue
                have_payload = True
                t = 0.0
                static_acked = False
                try:
                    t_max = float(canvas.get_max_duration()) if canvas.has_animation() else 0.0
                except Exception:  # noqa: BLE001
                    t_max = float(cmd.get("tmax") or 0.0)
                paused = False
                if diag.get("warnings"):
                    _emit({"ack": "diagnostic", "warnings": diag.get("warnings")})
            elif kind == "scrub":
                try:
                    t = max(0.0, min(t_max, float(cmd.get("t", t))))
                    canvas.set_scrub_time(t)
                    paused = True                # scrubbing implies manual control
                except Exception:  # noqa: BLE001
                    pass
            elif kind == "pause":
                paused = True
            elif kind == "resume":
                paused = False

        # 2) pygame events (window close + touch scrub on the bottom bar)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.MOUSEBUTTONDOWN and have_payload:
                x, y = ev.pos
                if y >= VIEW_H:                  # touch inside the scrubber strip
                    try:
                        canvas.handle_touch_scrub(x, y)
                        paused = True
                    except Exception:  # noqa: BLE001
                        pass

        # 3) advance + render
        if have_payload:
            was_animating = t < t_max
            if not paused and t_max > 0.0 and t < t_max:
                t = min(t_max, t + clock.get_time() / 1000.0)
            progress = 1.0 if t_max <= 0 else (t / t_max)
            try:
                frame = canvas.render(progress)
                screen.blit(_pil_to_surface(pygame, frame), (0, 0))
                pygame.display.flip()
            except Exception as e:  # noqa: BLE001 — a render error ends this payload cleanly
                _emit({"ack": "render_error", "error": str(e)})
                have_payload = False
            # animation just finished (or a static payload rendered once): ack the segment
            # exactly once, then keep the frame up without re-acking every tick.
            if t_max > 0.0 and was_animating and t >= t_max:
                _emit({"ack": "animation_done"})
            elif t_max <= 0.0 and not static_acked:
                _emit({"ack": "animation_done"})
                static_acked = True
        else:
            # Idle (no payload yet, or a render error cleared it): hold the blank
            # board background rather than a black or stale frame.
            try:
                screen.fill(bg)
                pygame.display.flip()
            except Exception:  # noqa: BLE001
                pass

        clock.tick(60)                            # native 60 FPS loop

    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
