"""Alphabet module UI — Windows port (pygame, replaces the C/LVGL renderer).

This is a faithful re-implementation of pi_game/alphabet_ui (main.c + ipc.c +
screens/alpha_screens.c) in pygame. It is a *renderer*: it owns no lesson logic,
it draws whatever `stage` the brain sends and reports touches, the drag, and the
completion choices back over the same newline-delimited JSON socket.

    brain -> UI :  ready | stage | status | feedback
    UI -> brain :  begin | touch | fed | next | again   (quit == socket close)

Design carried over from the spec (pigame.md §9/§10) and the C build:
  * warm-white paper palette, no pure red/green, no shadows or gradients, so
    right/wrong is never signalled by colour;
  * the same five status words, the same seven stages, the same generous
    drop-slop on the drag;
  * a calm 250 ms fade-in on each new stage; a gentle press-pulse on a tapped
    tile — nothing flashes, buzzes, or turns red.

Run standalone (brain must already be listening):
    python alphabet_ui.py [--host 127.0.0.1] [--port 8160] [--fullscreen]
Normally you launch everything together with run_game.py.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import socket
import sys
import threading
import time
from pathlib import Path

import pygame

ROOT = Path(__file__).resolve().parent

# ---- window / layout (the §9 stack, sized for the 600x1024 portrait panel) ----
WIN_W, WIN_H = 600, 1024
PAD = 28
GAP = 24
STATUS_H = 88
ACTION_H = 120
INSTR_H = 150
RADIUS = 20

# Content artwork sizes — the same pixel budgets as alpha_screens.c.
ROBOT_PX = 360
FOOD_PX = 180
OBJECT_PX = 320
SMALL_PX = 150
TILE_PX = 220
DROP_SLOP = 20

FPS = 60
FADE_MS = 250
PULSE_MS = 240

# ---- §9 palette. Every value muted on purpose. --------------------------------
COL = {
    "bg":         (0xF8, 0xF5, 0xEF),
    "card":       (0xFF, 0xFD, 0xF8),
    "text":       (0x3A, 0x37, 0x30),
    "text_muted": (0x7A, 0x74, 0x66),
    "divider":    (0xE2, 0xDD, 0xD1),
    "primary":    (0xA8, 0xC8, 0xE8),
    "accent":     (0xB8, 0xDD, 0xB0),
    "highlight":  (0xE8, 0xB5, 0x83),
}


def _now() -> int:
    return pygame.time.get_ticks()


# ---------------------------------------------------------------------------
# Lesson-channel client — one TCP connection, background reader, poll queue.


class Channel:
    """Mirror of ipc.c: connect (with retry), read newline JSON, send events."""

    def __init__(self, host: str, port: int) -> None:
        self.host, self.port = host, port
        self.q: queue.Queue[dict] = queue.Queue()
        self.sock: socket.socket | None = None
        self.connected = False
        self.alive = True
        threading.Thread(target=self._reader, daemon=True).start()

    def _connect(self) -> None:
        while self.alive and self.sock is None:
            try:
                s = socket.create_connection((self.host, self.port), timeout=2.0)
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                s.settimeout(None)
                self.sock = s
                self.connected = True
                print("[ui] connected to brain", flush=True)
            except OSError:
                time.sleep(1.0)          # ~1 Hz reconnect, like the C build

    def _reader(self) -> None:
        buf = b""
        while self.alive:
            if self.sock is None:
                self._connect()
                buf = b""
                continue
            try:
                chunk = self.sock.recv(4096)
            except OSError:
                chunk = b""
            if not chunk:
                self.connected = False
                try:
                    if self.sock:
                        self.sock.close()
                finally:
                    self.sock = None
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    self.q.put(json.loads(line.decode("utf-8")))
                except json.JSONDecodeError:
                    pass

    def poll(self) -> dict | None:
        try:
            return self.q.get_nowait()
        except queue.Empty:
            return None

    def send(self, obj: dict) -> None:
        s = self.sock
        if s is None:
            return
        try:
            s.sendall((json.dumps(obj) + "\n").encode("utf-8"))
        except OSError:
            self.connected = False

    def close(self) -> None:
        self.alive = False
        if self.sock:
            try:
                self.sock.close()          # brain sees EOF -> quit
            except OSError:
                pass
            self.sock = None


# ---------------------------------------------------------------------------
# Image cache — load once, scale on demand.

_img_cache: dict[str, pygame.Surface] = {}
_scaled_cache: dict[tuple[str, int], pygame.Surface] = {}


def load_image(path: str) -> pygame.Surface | None:
    if not path:
        return None
    if path in _img_cache:
        return _img_cache[path]
    try:
        img = pygame.image.load(path).convert_alpha()
    except Exception as exc:
        print(f"[ui] could not load {path}: {exc}", flush=True)
        img = None
    _img_cache[path] = img
    return img


def scaled_to_box(path: str, side: int) -> pygame.Surface | None:
    """Square-fit an image into side x side (art is square), smoothly scaled."""
    key = (path, side)
    if key in _scaled_cache:
        return _scaled_cache[key]
    img = load_image(path)
    if img is None:
        return None
    out = pygame.transform.smoothscale(img, (side, side))
    _scaled_cache[key] = out
    return out


def fit_within(path: str, max_w: int, max_h: int) -> pygame.Surface | None:
    """Scale preserving aspect so it fits within max_w x max_h (native cap)."""
    img = load_image(path)
    if img is None:
        return None
    iw, ih = img.get_size()
    scale = min(max_w / iw, max_h / ih, 1.0)
    if scale >= 0.999:
        return img
    return pygame.transform.smoothscale(img, (max(1, int(iw * scale)),
                                              max(1, int(ih * scale))))


# ---------------------------------------------------------------------------
# The UI


class AlphabetUI:
    def __init__(self, chan: Channel, fullscreen: bool) -> None:
        self.chan = chan
        flags = pygame.FULLSCREEN if fullscreen else 0
        self.screen = pygame.display.set_mode((WIN_W, WIN_H), flags)
        pygame.display.set_caption("Wini — Letters")
        self.running = True

        fpath = str(ROOT / "NunitoSans.ttf")
        self.f_instr = self._font(fpath, 34)
        self.f_btn = self._font(fpath, 32)
        self.f_status = self._font(fpath, 22)
        self.f_word = self._font(fpath, 34)
        self.f_big = self._font(fpath, 120)   # splash / fallback glyph

        # regions (absolute window coords)
        self.status_rect = pygame.Rect(PAD, PAD, WIN_W - 2 * PAD, STATUS_H)
        self.action_rect = pygame.Rect(PAD, WIN_H - PAD - ACTION_H,
                                       WIN_W - 2 * PAD, ACTION_H)
        instr_top = self.action_rect.top - GAP - INSTR_H
        self.instr_rect = pygame.Rect(PAD, instr_top, WIN_W - 2 * PAD, INSTR_H)
        content_top = self.status_rect.bottom + GAP
        self.content_rect = pygame.Rect(PAD, content_top, WIN_W - 2 * PAD,
                                        instr_top - GAP - content_top)
        self.close_rect = pygame.Rect(0, 0, 56, 56)
        self.close_rect.center = (self.status_rect.right - 28,
                                  self.status_rect.centery)

        # view state
        self.stage = "splash"
        self.status_text = ""
        self.instruction = ""
        self.fade_t0 = _now()

        self.letter_img = ""
        self.object_img = ""
        self.word = ""
        self.tiles: list[dict] = []          # {rect, letter, img}
        self.buttons: list[dict] = []        # {rect, label, event, primary}
        self.tile_pulse: dict | None = None  # {letter, t0}

        # activity drag
        self.robot_img = ""
        self.robot_happy = ""
        self.food_rect: pygame.Rect | None = None
        self.food_home = (0, 0)
        self.robot_rect: pygame.Rect | None = None
        self.dragging = False
        self.grab_off = (0, 0)
        self.fed = False
        self.food_anim: dict | None = None   # snap-back {from,to,t0}

        self._show_splash()

    @staticmethod
    def _font(path: str, size: int) -> pygame.font.Font:
        try:
            return pygame.font.Font(path, size)
        except Exception:
            return pygame.font.SysFont("segoeui,arial", size)

    # -- fade helper -------------------------------------------------------
    def _new_stage(self) -> None:
        self.fade_t0 = _now()

    def _fade_alpha(self) -> int:
        dt = _now() - self.fade_t0
        if dt >= FADE_MS:
            return 255
        return int(40 + (255 - 40) * (dt / FADE_MS))

    # -- command handlers (mirror apply_line) ------------------------------
    def apply(self, msg: dict) -> None:
        cmd = msg.get("cmd")
        if cmd == "ready":
            self._show_splash()
        elif cmd == "stage":
            self._apply_stage(msg)
        elif cmd == "status":
            self._apply_status(msg)
        elif cmd == "feedback":
            self._apply_feedback(msg)

    def _show_splash(self) -> None:
        self.stage = "splash"
        self.status_text = ""
        self.instruction = ""
        self.tiles = []
        self.buttons = [self._button("Start", {"event": "begin"}, primary=True)]
        self._layout_buttons()
        self._new_stage()

    def _apply_stage(self, m: dict) -> None:
        stage = m.get("stage", "")
        self.stage = stage
        self.instruction = m.get("text", "")
        self.letter_img = m.get("letter_img", "")
        self.object_img = m.get("object_img", "")
        self.word = m.get("word", "")
        self.tiles = []
        self.buttons = []
        self.tile_pulse = None
        self.food_rect = None
        self.robot_rect = None
        self.dragging = False
        self.fed = False
        self.food_anim = None

        if stage == "touch":
            self._build_touch(m.get("choices", []))
        elif stage == "activity":
            self._build_activity(m)
        elif stage == "complete":
            self.buttons = [
                self._button("Again", {"event": "again"}, primary=False),
                self._button("Next", {"event": "next"}, primary=True),
            ]
            self._layout_buttons()
        self._new_stage()

    def _apply_status(self, m: dict) -> None:
        v = m.get("value", "")
        self.status_text = {
            "speaking": "Wini is talking",
            "listening": "Wini is listening",
            "loading": "Getting ready",
            "error": "Wini needs help",
        }.get(v, "")

    def _apply_feedback(self, m: dict) -> None:
        # The spoken line carries the message. The only visible echo, exactly as
        # in the C build, is a gentle pulse of the content on a matched repeat.
        if m.get("kind") == "repeat_ok":
            self.tile_pulse = {"letter": "__content__", "t0": _now()}

    # -- builders ----------------------------------------------------------
    def _build_touch(self, choices: list) -> None:
        n = len(choices)
        cols = 2 if n > 1 else 1
        rows = (n + cols - 1) // cols
        gw = cols * TILE_PX + (cols - 1) * GAP
        gh = rows * TILE_PX + (rows - 1) * GAP
        x0 = self.content_rect.centerx - gw // 2
        y0 = self.content_rect.centery - gh // 2
        self.tiles = []
        for i, c in enumerate(choices):
            r, col = divmod(i, cols)
            rect = pygame.Rect(x0 + col * (TILE_PX + GAP),
                               y0 + r * (TILE_PX + GAP), TILE_PX, TILE_PX)
            self.tiles.append({"rect": rect, "letter": c.get("letter", ""),
                               "img": c.get("img", "")})

    def _build_activity(self, m: dict) -> None:
        self.robot_img = m.get("robot_open", "")
        self.robot_happy = m.get("robot_happy", "")
        cr = self.content_rect
        self.robot_rect = pygame.Rect(0, 0, ROBOT_PX, ROBOT_PX)
        self.robot_rect.midtop = (cr.centerx, cr.top)
        self.food_rect = pygame.Rect(0, 0, FOOD_PX, FOOD_PX)
        self.food_rect.midbottom = (cr.centerx, cr.bottom - 20)
        self.food_home = self.food_rect.topleft

    def _button(self, label: str, event: dict, primary: bool) -> dict:
        return {"rect": pygame.Rect(0, 0, 0, 0), "label": label,
                "event": event, "primary": primary}

    def _layout_buttons(self) -> None:
        if not self.buttons:
            return
        surf_labels = [self.f_btn.render(b["label"], True, COL["text"])
                       for b in self.buttons]
        widths = [max(200, s.get_width() + 72) for s in surf_labels]
        total = sum(widths) + GAP * (len(self.buttons) - 1)
        x = self.action_rect.centerx - total // 2
        y = self.action_rect.centery - 72 // 2
        for b, w in zip(self.buttons, widths):
            b["rect"] = pygame.Rect(x, y, w, 72)
            x += w + GAP

    # -- input -------------------------------------------------------------
    def handle_event(self, e: pygame.event.Event) -> None:
        if e.type == pygame.QUIT:
            self.running = False
        elif e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
            self.running = False
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            self._on_down(e.pos)
        elif e.type == pygame.MOUSEMOTION and self.dragging:
            self._on_drag(e.pos)
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            self._on_up(e.pos)

    def _on_down(self, pos) -> None:
        if self.close_rect.collidepoint(pos):
            self.running = False
            return
        if self.stage == "activity" and self.food_rect and not self.fed \
                and self.food_rect.collidepoint(pos):
            self.dragging = True
            self.food_anim = None
            self.grab_off = (pos[0] - self.food_rect.x, pos[1] - self.food_rect.y)

    def _on_drag(self, pos) -> None:
        if self.food_rect:
            self.food_rect.x = pos[0] - self.grab_off[0]
            self.food_rect.y = pos[1] - self.grab_off[1]

    def _on_up(self, pos) -> None:
        # tiles
        if self.stage == "touch":
            for t in self.tiles:
                if t["rect"].collidepoint(pos):
                    self.tile_pulse = {"letter": t["letter"], "t0": _now()}
                    self.chan.send({"event": "touch", "letter": t["letter"]})
                    return
        # buttons
        for b in self.buttons:
            if b["rect"].collidepoint(pos):
                self.chan.send(b["event"])
                if b["event"].get("event") == "begin":
                    self.status_text = "Starting"
                return
        # drag release
        if self.stage == "activity" and self.dragging and self.food_rect:
            self.dragging = False
            if self.robot_rect:
                hit = self.robot_rect.inflate(DROP_SLOP * 2, DROP_SLOP * 2)
                if hit.collidepoint(self.food_rect.center):
                    self.fed = True
                    self.robot_img = self.robot_happy or self.robot_img
                    self.chan.send({"event": "fed"})
                    return
            # dropped short: glide back home (movement only, nothing said)
            self.food_anim = {"from": self.food_rect.topleft,
                              "to": self.food_home, "t0": _now()}

    # -- per-frame update --------------------------------------------------
    def update(self) -> None:
        if self.food_anim and self.food_rect:
            dt = _now() - self.food_anim["t0"]
            k = min(1.0, dt / 420.0)
            k = k * k * (3 - 2 * k)          # smoothstep ~ ease-in-out
            fx, fy = self.food_anim["from"]
            tx, ty = self.food_anim["to"]
            self.food_rect.topleft = (int(fx + (tx - fx) * k),
                                      int(fy + (ty - fy) * k))
            if k >= 1.0:
                self.food_anim = None
        if self.tile_pulse and _now() - self.tile_pulse["t0"] > PULSE_MS:
            self.tile_pulse = None

    def _pulse_scale(self) -> float:
        if not self.tile_pulse:
            return 1.0
        dt = _now() - self.tile_pulse["t0"]
        k = min(1.0, dt / PULSE_MS)
        return 1.0 + 0.18 * (1.0 - abs(2 * k - 1))   # up to 1.18x and back

    # -- draw --------------------------------------------------------------
    def draw(self) -> None:
        s = self.screen
        s.fill(COL["bg"])
        self._draw_status()
        alpha = self._fade_alpha()
        if self.stage == "splash":
            self._draw_splash(alpha)
        elif self.stage in ("intro", "listen", "repeat"):
            self._draw_letter(alpha)
        elif self.stage == "touch":
            self._draw_touch(alpha)
        elif self.stage == "assoc":
            self._draw_assoc(alpha)
        elif self.stage == "activity":
            self._draw_activity(alpha)
        elif self.stage == "complete":
            self._draw_complete(alpha)
        self._draw_instruction()
        self._draw_buttons()
        pygame.display.flip()

    def _blit_alpha(self, img: pygame.Surface, center, alpha: int) -> None:
        if img is None:
            return
        if alpha < 255:
            img = img.copy()
            img.set_alpha(alpha)
        rect = img.get_rect(center=center)
        self.screen.blit(img, rect)

    def _draw_status(self) -> None:
        if self.status_text:
            lbl = self.f_status.render(self.status_text, True, COL["text_muted"])
            self.screen.blit(lbl, (self.status_rect.left,
                                   self.status_rect.centery - lbl.get_height() // 2))
        # close button: muted circle with a ×
        pygame.draw.circle(self.screen, COL["bg"], self.close_rect.center, 28)
        pygame.draw.circle(self.screen, COL["divider"], self.close_rect.center, 28, 2)
        x = self.f_btn.render("×", True, COL["text_muted"])
        self.screen.blit(x, x.get_rect(center=self.close_rect.center))

    def _draw_splash(self, alpha: int) -> None:
        cx = self.content_rect.centerx
        title = self.f_instr.render("Wini", True, COL["text_muted"])
        self._blit_alpha(title, (cx, self.content_rect.centery - 60), alpha)
        sub = self.f_instr.render("Let's meet some letters", True, COL["text"])
        self._blit_alpha(sub, (cx, self.content_rect.centery + 10), alpha)

    def _draw_letter(self, alpha: int) -> None:
        img = fit_within(self.letter_img,
                         int(self.content_rect.w * 0.95),
                         int(self.content_rect.h * 0.95))
        if img is None and self.letter_img == "":
            return
        if img is not None:
            self._blit_alpha(img, self.content_rect.center, alpha)
        # optional gentle content pulse on repeat_ok
        if img is not None and self.tile_pulse \
                and self.tile_pulse["letter"] == "__content__":
            k = self._pulse_scale()
            if k != 1.0:
                w, h = img.get_size()
                big = pygame.transform.smoothscale(img, (int(w * k), int(h * k)))
                self._blit_alpha(big, self.content_rect.center, alpha)

    def _draw_touch(self, alpha: int) -> None:
        pulse_letter = self.tile_pulse["letter"] if self.tile_pulse else None
        for t in self.tiles:
            rect = t["rect"]
            k = self._pulse_scale() if pulse_letter == t["letter"] else 1.0
            draw_rect = rect if k == 1.0 else rect.inflate(int(rect.w * (k - 1)),
                                                           int(rect.h * (k - 1)))
            # card
            card = pygame.Surface(draw_rect.size, pygame.SRCALPHA)
            pygame.draw.rect(card, COL["card"], card.get_rect(), border_radius=RADIUS)
            pygame.draw.rect(card, COL["divider"], card.get_rect(), width=2,
                             border_radius=RADIUS)
            img = scaled_to_box(t["img"], int(draw_rect.w * 0.72))
            if img is not None:
                card.blit(img, img.get_rect(center=card.get_rect().center))
            if alpha < 255:
                card.set_alpha(alpha)
            self.screen.blit(card, draw_rect)

    def _draw_assoc(self, alpha: int) -> None:
        cr = self.content_rect
        img = scaled_to_box(self.object_img, min(OBJECT_PX, cr.w, cr.h - 80))
        cy = cr.centery - 30
        if img is not None:
            self._blit_alpha(img, (cr.centerx, cy), alpha)
            cy = cr.centery + img.get_height() // 2 - 10
        if self.word:
            lbl = self.f_word.render(self.word, True, COL["text"])
            self._blit_alpha(lbl, (cr.centerx, cy + 40), alpha)

    def _draw_activity(self, alpha: int) -> None:
        if self.robot_rect:
            img = scaled_to_box(self.robot_img, ROBOT_PX)
            self._blit_alpha(img, self.robot_rect.center, alpha)
        if self.food_rect and not self.fed:
            img = scaled_to_box(self.object_img, FOOD_PX)
            # food follows the finger at full opacity (it is the live object)
            a = 255 if self.dragging else alpha
            self._blit_alpha(img, self.food_rect.center, a)

    def _draw_complete(self, alpha: int) -> None:
        cr = self.content_rect
        letter = fit_within(self.letter_img, int(cr.w * 0.8),
                            int(cr.h * 0.55))
        small = scaled_to_box(self.object_img, SMALL_PX)
        total_h = (letter.get_height() if letter else 0) + GAP + \
                  (small.get_height() if small else 0)
        y = cr.centery - total_h // 2
        if letter is not None:
            self._blit_alpha(letter, (cr.centerx, y + letter.get_height() // 2), alpha)
            y += letter.get_height() + GAP
        if small is not None:
            self._blit_alpha(small, (cr.centerx, y + small.get_height() // 2), alpha)

    def _draw_instruction(self) -> None:
        if not self.instruction:
            return
        lines = self._wrap(self.instruction, self.f_instr, self.instr_rect.w)
        lh = self.f_instr.get_linesize()
        total = lh * len(lines)
        y = self.instr_rect.centery - total // 2
        for ln in lines:
            surf = self.f_instr.render(ln, True, COL["text"])
            self.screen.blit(surf, (self.instr_rect.centerx - surf.get_width() // 2, y))
            y += lh

    def _draw_buttons(self) -> None:
        for b in self.buttons:
            rect = b["rect"]
            bg = COL["accent"] if b["primary"] else COL["card"]
            pygame.draw.rect(self.screen, bg, rect, border_radius=RADIUS)
            pygame.draw.rect(self.screen, COL["divider"], rect, width=2,
                             border_radius=RADIUS)
            lbl = self.f_btn.render(b["label"], True, COL["text"])
            self.screen.blit(lbl, lbl.get_rect(center=rect.center))

    @staticmethod
    def _wrap(text: str, font: pygame.font.Font, width: int) -> list[str]:
        words = text.split()
        lines: list[str] = []
        cur = ""
        for w in words:
            trial = w if not cur else cur + " " + w
            if font.size(trial)[0] <= width:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or [""]

    # -- main loop ---------------------------------------------------------
    def run(self) -> None:
        clock = pygame.time.Clock()
        while self.running:
            for e in pygame.event.get():
                self.handle_event(e)
            msg = self.chan.poll()
            while msg is not None:
                self.apply(msg)
                msg = self.chan.poll()
            self.update()
            self.draw()
            clock.tick(FPS)


def run(host: str = "127.0.0.1", port: int = 8160, fullscreen: bool = False) -> int:
    pygame.init()
    pygame.font.init()
    chan = Channel(host, port)
    ui = AlphabetUI(chan, fullscreen)
    try:
        ui.run()
    finally:
        chan.close()
        pygame.quit()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Wini alphabet UI (pygame)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8160)
    ap.add_argument("--fullscreen", action="store_true",
                    default=os.getenv("ALPHABET_FULLSCREEN") == "1")
    args = ap.parse_args()
    return run(args.host, args.port, args.fullscreen)


if __name__ == "__main__":
    raise SystemExit(main())
