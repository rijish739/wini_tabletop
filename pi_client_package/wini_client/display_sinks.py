"""Display sinks — the ONE platform seam that differs per device.

The brain sends display METADATA only ({image_path, alt_text, figure_id}); the
sink resolves `image_path` against the device's own local copy of the store
(SD card on the ESP32, rag_store/ on the Jetson) and puts the picture up while
Wini speaks. Unknown/missing path => keep the face (never crash a turn).

Sinks:
    NullSink      — no display (audio-only devices / debugging)
    ConsoleSink   — prints what WOULD be shown (any platform, zero deps)
    RosDisplaySink— Jetson (legacy ROS stack): publishes 480x320 rgb8 frames to
                    /wini/display/image at 5 Hz (the display_controll node
                    contract, JETSON_PIPELINE_RUNBOOK.md §7), pre-flipped
                    horizontally. Needs rclpy + cv2 + numpy, imported lazily.
    InProcSink    — ROS-less platform (WINI_ROSLESS_PLATFORM_PLAN.md): hands the
                    rendered frame straight to the in-process DisplayThread —
                    no keepalive, no pre-flip (the driver owns orientation).
    ModeChannelSink— Pi DSI panel via the LVGL touch UI (wini_ui): serializes the
                    turn into {"cmd": ...} lines on the mode channel instead of
                    rendering a raster frame. Figure crops are resolved against
                    the store, resized, written under /tmp and referenced by the
                    {"cmd":"figure"} command. Part 12 §5.6 / mode_channel.py.
"""

from __future__ import annotations

import threading
from pathlib import Path


def render_crop(store_dir: Path, rel_path: str, w: int, h: int,
                flip: bool = False):
    """Load a figure crop from the local store and letterbox it to w×h RGB.
    Returns a numpy array or None (missing/unreadable => caller keeps the face).
    flip=True pre-flips horizontally (legacy ROS display-node contract only)."""
    try:
        import cv2
        import numpy as np

        path = Path(store_dir) / rel_path
        if not path.exists():
            print(f"[display] crop missing (keeping face): {path}")
            return None
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            return None
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        ih, iw = rgb.shape[:2]
        scale = min(w / iw, h / ih)
        nw, nh = max(1, int(round(iw * scale))), max(1, int(round(ih * scale)))
        canvas = np.zeros((h, w, 3), dtype=np.uint8)
        y0, x0 = (h - nh) // 2, (w - nw) // 2
        canvas[y0:y0 + nh, x0:x0 + nw] = cv2.resize(rgb, (nw, nh),
                                                    interpolation=cv2.INTER_AREA)
        if flip:
            canvas = cv2.flip(canvas, 1)
        return np.ascontiguousarray(canvas)
    except Exception as e:  # noqa: BLE001
        print(f"[display] render failed for {rel_path}: {e}")
        return None


def render_item_frame(store_dir: Path, item: dict, w: int, h: int,
                      flip: bool = False):
    """Resolve a brain display item to a w×h RGB frame. A TEXT card
    (question_card/score_card, Part 12 Stage 4) renders via wini_platform.ui_cards;
    otherwise `image_path` is loaded as a figure crop. Returns None when there is
    nothing to show (missing/unreadable => caller keeps the current screen)."""
    kind = (item or {}).get("kind")
    if kind in ("question_card", "score_card"):
        try:
            import cv2
            import numpy as np

            from wini_platform.ui_cards import render_display_card
            frame = render_display_card(item)
            if frame is None:
                return None
            if (frame.shape[1], frame.shape[0]) != (w, h):
                frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
            if flip:
                frame = cv2.flip(frame, 1)
            return np.ascontiguousarray(frame)
        except Exception as e:  # noqa: BLE001 — a card must never crash a turn
            print(f"[display] card render failed ({kind}): {e}")
            return None
    rel = (item or {}).get("image_path")
    if not rel:
        return None
    return render_crop(store_dir, rel, w, h, flip=flip)


class NullSink:
    def show(self, item: dict) -> None:  # noqa: ARG002
        pass

    def clear(self) -> None:
        pass

    def thinking(self, active: bool) -> None:  # noqa: ARG002
        pass


class ConsoleSink:
    def show(self, item: dict) -> None:
        kind = (item or {}).get("kind")
        if kind == "question_card":
            print(f"[display] QUESTION CARD [{item.get('item_no')}/{item.get('of')}]: "
                  f"{(item.get('text') or '')[:100]}")
        elif kind == "score_card":
            print(f"[display] SCORE CARD {item.get('score')}/{item.get('of')} "
                  f"gate={item.get('gate')} {item.get('per_item')}")
        else:
            print(f"[display] SHOW {item.get('image_path')} — {item.get('alt_text', '')[:80]}")

    def clear(self) -> None:
        print("[display] CLEAR (back to face)")

    def thinking(self, active: bool) -> None:
        print(f"[display] THINKING {'on' if active else 'off'}")


class RosDisplaySink:
    """Jetson SPI panel via the existing display_controll node.

    Contract (§7): 480x320 landscape rgb8, keepalive > 2 Hz (node reverts to the
    face 0.5 s after frames stop), horizontal pre-flip on the SENDING side (the
    physical panel mirrors left-right).
    """

    W, H = 480, 320
    KEEPALIVE_S = 0.15  # aim ~5 Hz net of publish overhead (contract: > 2 Hz)

    def __init__(self, store_dir: Path):
        import rclpy
        from rclpy.node import Node  # noqa: F401  (type import)
        from sensor_msgs.msg import Image

        from std_msgs.msg import Bool

        self._Image = Image
        self._Bool = Bool
        self.store = Path(store_dir)
        if not rclpy.ok():
            rclpy.init()
        self._node = rclpy.create_node("wini_client_display")
        self._pub = self._node.create_publisher(Image, "/wini/display/image", 10)
        # Turn-phase signal: the platform side (wini_touch_trigger.py) renders a
        # "thinking" face while True and restores the prior emotion on False.
        self._think_pub = self._node.create_publisher(Bool, "/wini/thinking", 10)
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        # Pure publisher — no spin needed; a plain thread keeps the frame alive.
        threading.Thread(target=self._keepalive, daemon=True).start()

    def _keepalive(self):
        while not self._stop.wait(self.KEEPALIVE_S):
            with self._lock:
                msg = self._frame
            if msg is None:
                continue
            try:
                self._pub.publish(msg)
            except Exception as e:  # noqa: BLE001 — keepalive must never die
                print(f"[display] publish failed: {e}")

    def show(self, item: dict) -> None:
        # flip=True: legacy contract — the ROS display node un-mirrors it.
        frame = render_item_frame(self.store, item, self.W, self.H, flip=True)
        if frame is None:
            return self.clear()
        # build the ROS message ONCE per frame; the keepalive republishes it
        msg = self._to_msg(frame)
        with self._lock:
            self._frame = msg
        label = (item or {}).get("kind") or (item or {}).get("image_path")
        print(f"[display] showing {label}")

    def clear(self) -> None:
        with self._lock:
            self._frame = None

    def thinking(self, active: bool) -> None:
        try:
            m = self._Bool()
            m.data = bool(active)
            self._think_pub.publish(m)
        except Exception as e:  # noqa: BLE001 — a face cue must never cost a turn
            print(f"[display] thinking signal failed: {e}")

    def _to_msg(self, frame):
        m = self._Image()
        m.height, m.width = self.H, self.W
        m.encoding = "rgb8"
        m.is_bigendian = 0
        m.step = self.W * 3
        m.data = frame.tobytes()
        return m


class InProcSink:
    """ROS-less platform sink: same metadata contract as RosDisplaySink
    (`image_path` = SD-card image ID resolved against the local store — the
    ESP32 contract is unchanged), but the rendered frame goes straight to the
    in-process DisplayThread. No keepalive thread, no pre-flip.

    `display` is a wini_platform DisplayThread (show_overlay/clear_overlay);
    `set_thinking` is the platform's thinking-face hook (may be None).
    """

    W, H = 480, 320

    def __init__(self, store_dir: Path, display, set_thinking=None):
        self.store = Path(store_dir)
        self._display = display
        self._set_thinking = set_thinking

    def show(self, item: dict) -> None:
        frame = render_item_frame(self.store, item, self.W, self.H)
        if frame is None:
            return  # keep whatever is on screen — never crash a turn
        self._display.show_overlay(frame)
        print(f"[display] showing {(item or {}).get('kind') or (item or {}).get('image_path')}")

    def clear(self) -> None:
        self._display.clear_overlay()

    def thinking(self, active: bool) -> None:
        if self._set_thinking is None:
            return
        try:
            self._set_thinking(bool(active))
        except Exception as e:  # noqa: BLE001 — a face cue must never cost a turn
            print(f"[display] thinking signal failed: {e}")


# ── LVGL touch-UI sink (Pi DSI panel via the mode channel) ──────────────────

# What the panel can actually draw. The UI fonts (wini_ui/fonts/*.c) are a
# DejaVu Serif subset built with `--range 0x20-0x7E --symbols ²³×÷−√≤≥°±πΔθ…`,
# so ASCII plus that symbol list renders and everything else is a blank box.
# The channel is UTF-8 clean (mode_channel sends ensure_ascii=False), so there is
# no reason to downgrade ² to "^2" — that ASCII fallback is exactly what put
# "x^2" in front of the student.
try:
    from mathtext import PANEL_GLYPHS as _PANEL_GLYPHS
except Exception:  # noqa: BLE001 — thin client without the repo root on sys.path
    _PANEL_GLYPHS = set("²³×÷−√≤≥°±πΔθ→←↑↓●○◐✓…—–‘’“”·⅓½¼")

# Glyphs the fonts DON'T carry, mapped to something readable rather than dropped.
_ASCII_MAP = {
    "≠": "!=", "∞": "inf", "¾": "3/4", "≈": "~", "∠": "angle ", "∴": "so ",
}


import re as _re

_LATEX_MACROS = {
    r"\pi": "pi", r"\times": "x", r"\cdot": ".", r"\div": "/", r"\theta": "theta",
    r"\sqrt": "sqrt", r"\degree": "deg", r"\leq": "<=", r"\geq": ">=",
    # longer macros FIRST: sequential replace() would turn \neq into "!=q"
    r"\neq": "!=",
    r"\le": "<=", r"\ge": ">=", r"\ne": "!=",
    r"\approx": "~", r"\left": "", r"\right": "", r"\,": " ", r"\;": " ",
}


def _delatex(s: str) -> str:
    """Render the maths in a brain string the way a STUDENT should read it:
    ``x^2`` -> ``x²``, ``\\sqrt{3}`` -> ``√3``, ``>=`` -> ``≥``, ``a * b`` ->
    ``a × b``. The spoken path renders the same input as words instead — that
    difference is intended; what was NOT intended is the two parsing it
    differently, which is why the primitives live in one module (audit B-5).

    Falls back to the local ASCII implementation when `mathtext` is not
    importable: this module also runs from the thin client, where the repo root
    is not guaranteed to be on sys.path, and a display card must never take the
    turn down with it.
    """
    try:
        from mathtext import to_panel_unicode
        return to_panel_unicode(s)
    except Exception:  # noqa: BLE001 — see docstring
        for d in ("$", r"\(", r"\)", r"\[", r"\]"):
            s = s.replace(d, "")
        for k, v in _LATEX_MACROS.items():
            s = s.replace(k, v)
        s = _re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"\1/\2", s)
        s = _re.sub(r"([\^_])\{([^{}]*)\}", r"\1\2", s)   # x^{2} -> x^2
        s = s.replace("{", "").replace("}", "")
        s = _re.sub(r"\\([a-zA-Z]+)", r"\1", s)           # unknown macro: keep the word
        s = _re.sub(r"\^2(?![0-9a-zA-Z])", "²", s)
        s = _re.sub(r"\^3(?![0-9a-zA-Z])", "³", s)
        return s.replace("\\", "")


def _pretty_concept(cid) -> str:
    """A human heading from a concept id: 'jemh111__area_of_segment' -> 'Area Of
    Segment' (drop the chapter-doc/'grade9::' prefix, underscores to spaces,
    title-case)."""
    tail = _re.split(r"__|::", str(cid or ""))[-1]
    return tail.replace("_", " ").strip().title()


def _concept_lines(cid) -> "tuple[str, str]":
    """Header (line1, line2) for a concept id. NCERT doc ids encode the chapter
    ('jemh111__x' -> Chapter 11), so the header reads 'Chapter 11 / Area Of
    Segment'; anything else (grade9:: bridges, plain slugs) is topic-only."""
    m = _re.match(r"^[a-z]+?1(\d\d)__", str(cid or ""))
    topic = _pretty_concept(cid)
    if m:
        return f"Chapter {int(m.group(1))}", topic
    return topic, ""


def _clean(s, cap: int) -> str:
    """Reduce a brain string to a single line the LVGL fonts can render and the
    UI's flat-JSON scanner won't mangle, within `cap` characters.

    Truncation cuts at the last SENTENCE end that fits (falling back to the last
    word) rather than mid-token: an explanation chopped at a fixed width left
    fragments like "x = 2 =-2" on the panel, which reads as broken maths rather
    than as a truncated sentence. Callers should size `cap` so this never fires.
    """
    s = _delatex(str(s or ""))
    for k, v in _ASCII_MAP.items():
        s = s.replace(k, v)
    s = "".join(ch if (32 <= ord(ch) < 127 or ch in _PANEL_GLYPHS) else " "
                for ch in s)
    s = " ".join(s.split())               # collapse any whitespace run to one space
    if len(s) > cap:
        head = s[:cap - 1]
        cut = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
        if cut < cap // 2:                # no sentence break worth keeping
            cut = head.rfind(" ")
            s = (head[:cut] if cut > 0 else head).rstrip() + "…"
        else:
            s = head[:cut + 1]
    return s


class ModeChannelSink:
    """Drives the LVGL touch UI (wini_ui) over the mode channel: each turn is
    serialized into the {"cmd": ...} lines `wini_app_dispatch` applies to the DSI
    panel. Same show/clear/thinking seam as the raster sinks, plus `on_turn(result)`
    which the client hands the FULL turn dict — screen/stage/progress/feedback come
    from `mode`/`test`/`writeback`, which aren't in the display item.

    Figure crops (T9 items carrying `image_path`): the UI and the client share a
    filesystem, so the sink resolves the crop against the store, scales it to fit
    the card, writes a PNG under /tmp and sends {"cmd":"figure","path":...} — the
    UI's figure_card loads it from disk. Turns without a figure send
    {"cmd":"figure","off":1} so a previous turn's picture never lingers."""

    SCREEN = {"EXPLAIN": "explain", "PRACTICE": "practice", "TEST": "test"}
    FIG_MAX_W, FIG_MAX_H = 500, 380        # fits the 600-wide portrait card
    FIG_SLOTS = 4                          # /tmp/wini_fig_{0..3}.png, cycled

    def __init__(self, channel, store_dir=None):
        self._ch = channel                 # a mode_channel.ModeChannel (.send(dict))
        self.store = Path(store_dir) if store_dir else None
        self._mode = "EXPLAIN"
        self._fig_n = 0

    # -- rich per-turn hook (client calls this before show/clear) --------------
    def on_turn(self, result: dict) -> None:
        result = result or {}
        mode = str(result.get("mode") or "EXPLAIN").upper()
        self._mode = mode if mode in self.SCREEN else "EXPLAIN"

        # 1. feedback for the answer graded THIS turn, before we move the screen on.
        outcome = (result.get("writeback") or {}).get("outcome")
        if outcome in ("correct", "partial", "wrong"):
            self._ch.send({"cmd": "feedback",
                           "kind": "correct" if outcome == "correct" else "almost"})

        # 2. move to the mode's screen (a score card drives the RESULT screen itself).
        display0 = ((result.get("display") or [None]) or [None])[0] or {}
        if display0.get("kind") != "score_card":
            self._ch.send({"cmd": "screen", "to": self.SCREEN[self._mode]})
        self._ch.send({"cmd": "stage", "v": self.SCREEN[self._mode]})
        self._ch.send({"cmd": "status", "v": "teaching"})

        # 2b. header chapter/topic lines follow the turn's concept — the header
        # must never keep the previous chapter's title after a topic shift
        # (UI/brain desync bug, 2026-07-16). Sent AFTER "screen" so it lands on
        # the header of the screen now being shown. An ACTIVE test pins the
        # header to the set's locked concept: the child's short answers ("48")
        # re-classify turn to turn and would wobble the title mid-quiz.
        test_now = result.get("test") or {}
        cid = (test_now.get("concept_id")
               if test_now.get("phase") == "serving" else None) or result.get("concept")
        if cid:
            l1, l2 = _concept_lines(cid)
            cmd = {"cmd": "lines", "l1": _clean(l1, 60)}
            if l2:
                cmd["l2"] = _clean(l2, 60)
            self._ch.send(cmd)

        # 3. quiz progress from the TEST echo (served/graded of n).
        test = result.get("test") or {}
        n = test.get("n")
        if n:
            done = n if test.get("phase") == "summary" \
                else (test.get("graded") or test.get("served") or 0)
            self._ch.send({"cmd": "progress", "stage": "test",
                           "done": int(done), "of": int(n)})

        # 4. EXPLAIN turns carry no card — put the spoken answer on the explain
        #    screen so the panel paints the turn instead of sitting blank.
        if self._mode == "EXPLAIN" and result.get("answer"):
            # The card WRAPS and the explain screen scrolls, so the body is
            # capped by the transport (mode_channel MAX_LINE / ipc.c
            # IPC_LINE_MAX / the dispatch buffer), not by a display width. 200
            # used to cut a typical 300-400 char answer mid-sentence — the child
            # read half an explanation ending in "...".
            self._ch.send({"cmd": "explain",
                           "title": _clean(_pretty_concept(result.get("concept")), 40),
                           "body": _clean(result.get("answer"), 900)})

        # 5. a turn WITHOUT a figure hides the previous turn's one (never stale);
        #    a turn WITH one gets it via show() right after this hook.
        if not display0.get("image_path"):
            self._ch.send({"cmd": "figure", "off": 1})

    # -- narrow display seam --------------------------------------------------
    def show(self, item: dict) -> None:
        item = item or {}
        kind = item.get("kind")
        if kind == "question_card":
            n = ""
            if item.get("item_no") and item.get("of"):
                n = f"Question {item['item_no']} of {item['of']}"
            self._ch.send({"cmd": "question", "n": n,
                           "text": _clean(item.get("text"), 400)})
        elif kind == "score_card":
            passed = item.get("gate") == "pass"
            self._ch.send({"cmd": "score",
                           "score": int(item.get("score") or 0),
                           "of": int(item.get("of") or 0),
                           "caption": "Great job!" if passed else "Keep going!"})
            if passed:
                self._ch.send({"cmd": "celebrate", "msg": "Well done!"})
        elif item.get("image_path"):
            self._emit_figure(item)
        # anything else: no LVGL command; keep whatever screen is up.

    def _emit_figure(self, item: dict) -> None:
        """Resolve the T9 figure crop, scale it to the card, write a PNG under
        /tmp and point the UI at it. Any failure keeps the current screen."""
        if not self.store:
            return
        try:
            import cv2

            path = self.store / item["image_path"]
            img = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if img is None:
                print(f"[display] figure missing/unreadable: {path}")
                return
            h, w = img.shape[:2]
            scale = min(self.FIG_MAX_W / w, self.FIG_MAX_H / h, 1.0)
            if scale < 1.0:
                img = cv2.resize(img, (max(1, round(w * scale)),
                                       max(1, round(h * scale))),
                                 interpolation=cv2.INTER_AREA)
            out = f"/tmp/wini_fig_{self._fig_n}.png"
            self._fig_n = (self._fig_n + 1) % self.FIG_SLOTS
            if not cv2.imwrite(out, img):
                print(f"[display] figure write failed: {out}")
                return
            self._ch.send({"cmd": "figure", "path": out,
                           "caption": _clean(item.get("alt_text"), 90)})
            print(f"[display] figure -> {out} ({item.get('image_path')})")
        except Exception as e:  # noqa: BLE001 — a figure must never crash a turn
            print(f"[display] figure emit failed: {e}")

    def clear(self) -> None:
        # The card stays on screen (a quiz question must persist for the child to
        # read); just flag that Wini finished speaking and it is their turn.
        self._ch.send({"cmd": "status", "v": "waiting"})

    def thinking(self, active: bool) -> None:
        self._ch.send({"cmd": "thinking", "on": 1 if active else 0})
        if active:
            self._ch.send({"cmd": "status", "v": "thinking"})


def make_sink(kind: str, store_dir: Path):
    if kind == "ros":
        return RosDisplaySink(store_dir)
    if kind == "console":
        return ConsoleSink()
    return NullSink()
