"""Board Buddy End-to-End Canvas Renderer — integrates board_buddy.py with wini_server.

Renders raw Board Buddy payloads (stickers, geometry, graphs, number lines, fractions, text)
directly into PNG images or Base64 Data URLs for real-time visual debugging in UI.
"""

from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BB_DIR = ROOT / "board_buddy" / "board_buddy-main"
if BB_DIR.exists() and str(BB_DIR) not in sys.path:
    sys.path.insert(0, str(BB_DIR))

try:
    from board_buddy import BoardBuddyCanvas
except Exception as _e:
    print(f"[board_buddy_renderer] Warning: BoardBuddyCanvas import error: {_e}")
    BoardBuddyCanvas = None


def render_board_payload(payload: list[dict] | dict, width: int = 600, height: int = 800) -> str | None:
    """Renders a Board Buddy JSON payload to a base64 PNG data URL.
    Returns None if rendering fails or canvas is unavailable.
    """
    if BoardBuddyCanvas is None or not payload:
        return None
    try:
        if isinstance(payload, dict):
            payload = payload.get("elements") or payload.get("payload") or [payload]
        if not payload:
            return None
        canvas = BoardBuddyCanvas(width=width, height=height)
        res = canvas.load_json(payload)
        img = canvas.render()
        if img is None:
            return None
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{b64}"
    except Exception as e:  # noqa: BLE001 — rendering failure must never crash server
        print(f"[board_buddy_renderer] render failed: {e}")
        return None


def render_board_payload_animated(payload: list[dict] | dict, *, fps: int = 12,
                                  max_frames: int = 72, width: int = 600,
                                  height: int = 800) -> str | None:
    """Render an ANIMATED Board Buddy payload to a base64 **APNG** data URL that plays in a
    plain ``<img>`` (full colour, unlike GIF). This is the web-preview counterpart of the
    device's live 60 FPS surface: it samples ``canvas.render(anim_progress=t/T_max)`` across
    ``0..T_max`` so a morphing parabola / growing hop / filling grid actually MOVES in the UI
    instead of the frozen final frame today (BOARD_BUDDY_FULL_FEATURE_PLAN.md Phase C).

    A static payload (no animation, ``T_max==0``) has nothing to animate -> returns None so
    the caller keeps the cheaper single-frame ``render_board_payload``. Never raises.
    """
    if BoardBuddyCanvas is None or not payload:
        return None
    try:
        if isinstance(payload, dict):
            payload = payload.get("elements") or payload.get("payload") or [payload]
        if not payload:
            return None
        canvas = BoardBuddyCanvas(width=width, height=height)
        canvas.load_json(payload)
        try:
            tmax = float(canvas.get_max_duration())
        except Exception:  # noqa: BLE001 — some builds only expose has_animation()
            tmax = 0.0
        if tmax <= 0.0:
            return None                     # static -> caller uses the single-frame path
        n = max(2, min(int(max_frames), int(round(tmax * max(1, fps))) + 1))
        frames = []
        for i in range(n):
            prog = i / (n - 1)              # 0.0 .. 1.0 inclusive (freeze on the final frame)
            img = canvas.render(anim_progress=prog)
            if img is not None:
                frames.append(img.convert("RGBA"))
        if len(frames) < 2:
            return None
        frame_ms = max(20, int(round(1000.0 * tmax / (len(frames) - 1))))
        buf = io.BytesIO()
        frames[0].save(buf, format="PNG", save_all=True, append_images=frames[1:],
                       duration=frame_ms, loop=0, disposal=1)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{b64}"
    except Exception as e:  # noqa: BLE001 — rendering failure must never crash server
        print(f"[board_buddy_renderer] animated render failed: {e}")
        return None
