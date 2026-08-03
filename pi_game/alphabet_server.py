"""Alphabet module brain — owns the lesson state machine and all cloud calls.

Mirrors the tutor's split (wini_server + wini_ui): this process holds the lesson
logic, the voice, and the progress store; the C/LVGL UI is a renderer that sends
touch events and draws what it is told. Two sockets, same shape as the tutor:

    :8150  HTTP  /health, /parent   — readiness for the launcher, parent report
    :8160  TCP   newline-delimited JSON, bidirectional, one UI connection

    UI  -> brain :  {"event":"begin"|"touch"|"fed"|"next"|"again"|"quit", ...}
    brain -> UI  :  {"cmd":"ready"|"stage"|"status"|"feedback", ...}

The state machine is the §12 sequence and nothing else — deterministic, no
branching, no failure state. A stage that needs the child ends by waiting on an
event; a stage that only speaks ends after a calm pause.

Run:  .venv/bin/python -m pi_game.alphabet_server [--prewarm-all]
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
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dotenv import load_dotenv                                   # noqa: E402

load_dotenv(REPO / ".env")

from pi_game import languages, progress, speech                  # noqa: E402
from pi_game.languages import Language                            # noqa: E402

ASSETS = ROOT / "assets"

UI_PORT = 8160
HTTP_PORT = 8150

# Calm pacing (§2.4). These are the pauses the child thinks in — do not trim them
# to make the lesson feel faster; feeling unhurried is the product.
PAUSE_AFTER_SPEECH = 0.7
PAUSE_INTRO = 1.4
PAUSE_STAGE = 0.9
ACTIVITY_WAIT_S = 30.0       # generous: the drag is exploratory, not timed
MAX_SPEECH_ATTEMPTS = 2      # §Stage 4 — then continue regardless


_state = {"ready": False, "error": None, "letter": None}


# ---------------------------------------------------------------------------
# Assets


def lesson_paths(letter: str, lang: Language) -> dict:
    d = ASSETS / lang.asset_root / "letters" / letter
    return {
        "letter_img": str(d / "letter_big.png"),
        "tile_img": str(d / "letter_tile.png"),
        "object_img": str(d / "object.png"),
    }


def load_lesson(letter: str, lang: Language) -> dict:
    p = ASSETS / lang.asset_root / "letters" / letter / "lesson.json"
    if not p.exists():
        raise FileNotFoundError(
            f"no lesson for {lang.code}:{letter} — run: "
            f".venv/bin/python -m pi_game.gen_assets --lang {lang.code}")
    return json.loads(p.read_text(encoding="utf-8"))


def all_lines(lang: Language) -> list[str]:
    out: list[str] = []
    for ch in lang.module.ORDER:
        out.extend(lang.module.lesson_lines(ch).values())
    return out


# ---------------------------------------------------------------------------
# The lesson session


class Session:
    """One UI connection: reads events, runs lessons, writes commands."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.events: queue.Queue[dict] = queue.Queue()
        self.alive = True
        self.run: progress.Run | None = None
        # The child's chosen alphabet, fixed for the session by the begin event.
        # English until then, so a bare CLI begin (no lang) behaves as it always did.
        self.lang: Language = languages.get(None)
        threading.Thread(target=self._reader, daemon=True).start()

    # -- transport ---------------------------------------------------------
    def _reader(self) -> None:
        buf = b""
        try:
            while self.alive:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        self.events.put(json.loads(line.decode("utf-8")))
                    except json.JSONDecodeError:
                        print(f"[alpha] bad event line: {line[:120]!r}", flush=True)
        except OSError:
            pass
        finally:
            self.alive = False
            self.events.put({"event": "quit"})

    def send(self, obj: dict) -> None:
        if not self.alive:
            return
        # One greppable line per stage. Screenshot and smoke runs synchronise on
        # these instead of on sleeps: a lesson's timing changes by seconds once
        # its audio is cached, so anything time-based photographs a stage late.
        if obj.get("cmd") == "stage":
            print(f"[alpha] STAGEMARK {obj['stage']} {obj.get('letter','')}",
                  flush=True)
            # LVGL can't shape Kannada, so for a non-Latin lesson the instruction
            # sentence and the object word travel as pre-rendered images the UI
            # blits; English keeps its native text labels. Rendering is cached on
            # disk (textimg), so this is a path lookup after the first time.
            if self.lang.code != "en":
                self._attach_text_images(obj)
        try:
            self.sock.sendall((json.dumps(obj) + "\n").encode("utf-8"))
        except OSError:
            self.alive = False

    def _attach_text_images(self, obj: dict) -> None:
        """Add text_img (instruction) and word_img (object word) for a non-Latin
        stage. Failures are swallowed: a missing image just falls back to the raw
        text field, which is never worse than the pre-image behaviour."""
        try:
            from pi_game import textimg
        except Exception as exc:                       # Pillow absent, etc.
            print(f"[alpha] textimg unavailable ({exc}) — sending raw text", flush=True)
            return
        fp = self.lang.font_path
        try:
            if obj.get("text"):
                obj["text_img"] = str(textimg.render(obj["text"], fp, px=38, max_w=540))
            if obj.get("word"):
                obj["word_img"] = str(textimg.render(obj["word"], fp, px=64, max_w=520))
        except Exception as exc:
            print(f"[alpha] text image render failed ({exc}) — raw text", flush=True)

    def drain(self) -> None:
        """Discard events queued before this moment.

        Called as each interactive stage opens. Without it, a child drumming on
        the panel during the intro leaves taps sitting in the queue that would
        silently auto-answer the touch stage the instant it appears — the child
        would never see the board, and the progress store would record a correct
        answer nobody gave.
        """
        while True:
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                return
            if ev.get("event") == "quit":     # never swallow a disconnect
                self.events.put(ev)
                return

    def wait(self, *names: str, timeout: float | None = None) -> dict | None:
        """Block until one of `names` arrives. None on timeout or disconnect.

        Events arriving while a line is being spoken ARE kept: once a stage is on
        screen, a child who answers before the robot finishes asking is
        answering deliberately. Stale events from earlier stages are cleared by
        drain() at stage entry instead.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.alive:
            budget = None if deadline is None else max(0.0, deadline - time.monotonic())
            if budget == 0.0:
                return None
            try:
                ev = self.events.get(timeout=budget if budget is not None else 3600)
            except queue.Empty:
                return None
            if ev.get("event") == "quit":
                self.alive = False
                return None
            if ev.get("event") in names:
                return ev
        return None

    # -- speaking ----------------------------------------------------------
    def speak(self, text: str, pause: float = PAUSE_AFTER_SPEECH) -> None:
        self.send({"cmd": "status", "value": "speaking", "text": text})
        try:
            speech.say(text, self.lang.voice)
        except Exception as exc:                       # cloud hiccup, keep going
            print(f"[alpha] TTS failed ({exc}) — continuing silently", flush=True)
        self.send({"cmd": "status", "value": "waiting"})
        if pause:
            time.sleep(pause)

    # -- the §12 state machine --------------------------------------------
    def lesson(self, letter: str) -> str | None:
        """Run one full lesson. Returns the next letter, or None to stop."""
        order = self.lang.module.ORDER
        lesson = load_lesson(letter, self.lang)
        lines = lesson["lines"]
        paths = lesson_paths(letter, self.lang)
        self.run = progress.Run(letter, self.lang.code)
        _state["letter"] = letter

        # This letter's audio must be local before the intro, or the first line
        # arrives after a visible cloud stall. Later letters are warmed in the
        # background while the child is busy here.
        self.send({"cmd": "status", "value": "loading"})
        try:
            speech.prewarm(list(lines.values()), self.lang.voice)
        except Exception as exc:
            print(f"[alpha] prewarm failed ({exc}) — lines will synth on demand", flush=True)
        _prewarm_ahead(letter, self.lang)

        idx = order.index(letter)
        # `letter` is the ASCII id on the wire; `char` is what the child sees/hears
        # (the akshara for Kannada, the same letter for English).
        base = {"letter": letter, "char": lesson.get("char", letter),
                "index": idx + 1, "total": len(order)}

        # Stage 1 — Introduction
        self.send({"cmd": "stage", "stage": "intro", "text": lines["intro"],
                   "letter_img": paths["letter_img"], **base})
        self.speak(lines["intro"], pause=PAUSE_INTRO)
        if not self.alive:
            return None

        # Stage 2 — Listen
        self.send({"cmd": "stage", "stage": "listen", "text": lines["listen"],
                   "letter_img": paths["letter_img"], **base})
        self.speak(lines["listen"], pause=PAUSE_STAGE)
        if not self.alive:
            return None

        # Stage 3 — Touch
        if not self._stage_touch(lesson, lines, base):
            return None

        # Stage 4 — Repeat
        if not self._stage_repeat(lesson, lines, base):
            return None

        # Stage 5 — Object association
        self.send({"cmd": "stage", "stage": "assoc", "text": lines["assoc"],
                   "object_img": paths["object_img"],
                   "word": lesson["objects"][0]["name"], **base})
        self.speak(lines["assoc"], pause=PAUSE_INTRO)
        if not self.alive:
            return None

        # Stage 6 — Mini activity
        if not self._stage_activity(lesson, lines, base, paths):
            return None

        # Stage 7 — Completion
        self.drain()
        self.send({"cmd": "stage", "stage": "complete", "text": lines["complete"],
                   "letter_img": paths["letter_img"],
                   "object_img": paths["object_img"], **base})
        self.speak(lines["complete"], pause=0.3)
        self.run.save(completed=True)
        self.run = None

        ev = self.wait("next", "again")
        if ev is None:
            return None
        return letter if ev["event"] == "again" else order[(idx + 1) % len(order)]

    def _stage_touch(self, lesson: dict, lines: dict, base: dict) -> bool:
        choices = [{"letter": c, "img": lesson_paths(c, self.lang)["tile_img"]}
                   for c in lesson["choices"]]
        self.drain()
        self.send({"cmd": "stage", "stage": "touch", "text": lines["touch_ask"],
                   "choices": choices, **base})
        self.speak(lines["touch_ask"], pause=0.2)

        while self.alive:
            ev = self.wait("touch")
            if ev is None:
                return False
            picked = ev.get("letter")
            self.run.touch_attempts += 1
            if picked == base["letter"]:
                self.run.touch_correct += 1
                self.send({"cmd": "feedback", "kind": "touch_ok", "letter": picked})
                self.speak(lines["touch_ok"], pause=PAUSE_STAGE)
                return self.alive
            # Wrong tap: no buzzer, no red, no counter — just an invitation to
            # look again (§Stage 3). The board stays exactly as it was.
            self.send({"cmd": "feedback", "kind": "touch_retry", "letter": picked})
            self.speak(lines["touch_retry"], pause=0.2)
        return False

    def _stage_repeat(self, lesson: dict, lines: dict, base: dict) -> bool:
        # Keep the letter on screen while the child speaks: this stage asks for
        # its sound, and an empty content area gives them nothing to say it to.
        self.send({"cmd": "stage", "stage": "repeat", "text": lines["repeat_ask"],
                   "letter_img": lesson_paths(base["letter"], self.lang)["letter_img"],
                   **base})
        self.speak(lines["repeat_ask"], pause=0.3)

        tmp = Path("/tmp/alpha_utterance.wav")
        for attempt in range(MAX_SPEECH_ATTEMPTS):
            if not self.alive:
                return False
            self.send({"cmd": "status", "value": "listening"})
            heard = speech.listen(tmp, stt_lang=self.lang.stt_lang)
            self.send({"cmd": "status", "value": "waiting"})
            self.run.speech_attempts += 1

            ok = speech.judge_attempt(heard, base["letter"], lesson["phoneme"],
                                      lesson["say"], lang=self.lang.code)
            print(f"[alpha] repeat {base['letter']} attempt {attempt + 1}: "
                  f"heard={heard!r} ok={ok}", flush=True)
            if ok:
                self.run.speech_matched += 1
                self.send({"cmd": "feedback", "kind": "repeat_ok"})
                self.speak(lines["repeat_ok"], pause=PAUSE_STAGE)
                return self.alive
            if attempt + 1 < MAX_SPEECH_ATTEMPTS:
                self.send({"cmd": "feedback", "kind": "repeat_retry"})
                self.speak(lines["repeat_retry"], pause=0.3)

        # Two attempts is the cap and there is NO failure state: move on warmly.
        # Deliberately NOT the "that was lovely" line — that praised a sound the
        # robot never heard, on every single lesson, which is both dishonest and
        # useless to a child who is struggling. progress.speech_matched stays
        # untouched here, so the parent report reflects what actually happened.
        self.send({"cmd": "feedback", "kind": "repeat_move_on"})
        self.speak(lines["repeat_move_on"], pause=PAUSE_STAGE)
        return self.alive

    def _stage_activity(self, lesson: dict, lines: dict, base: dict,
                        paths: dict) -> bool:
        common = ASSETS / "common"
        # An open mouth is an invitation to eat, so only show it for something
        # edible; for a drum or a zebra the robot simply waits to be handed it.
        waiting_face = "robot_open" if lesson.get("edible") else "robot_idle"
        self.drain()
        self.send({"cmd": "stage", "stage": "activity", "text": lines["activity_ask"],
                   "object_img": paths["object_img"],
                   "word": lesson["objects"][0]["name"],
                   "robot_open": str(common / f"{waiting_face}.png"),
                   "robot_happy": str(common / "robot_happy.png"), **base})
        self.speak(lines["activity_ask"], pause=0.2)

        ev = self.wait("fed", timeout=ACTIVITY_WAIT_S)
        if not self.alive:
            return False
        if ev is not None:
            print("[alpha] FEDMARK ok", flush=True)
            self.speak(lines["activity_ok"], pause=PAUSE_STAGE)
        else:
            # Nobody dragged anything. Not a failure — the robot simply moves on.
            # Logged distinctly because "the lesson finished" alone does not tell
            # you whether the drag worked or merely timed out.
            print("[alpha] FEDMARK timeout", flush=True)
            self.send({"cmd": "feedback", "kind": "activity_skip"})
        return self.alive

    # -- driver ------------------------------------------------------------
    def serve(self) -> None:
        # `langs` drives the start-screen toggle; `letters`/`completed` stay for a
        # pre-toggle UI, and default to English exactly as before. `kn_label_img`
        # is the pre-rendered "ಕನ್ನಡ" toggle label (a static gen_assets artifact
        # named label_<code>.png, so no Pillow is touched until a Kannada lesson
        # actually starts).
        kn_label = ASSETS / "common" / "label_kn.png"
        self.send({
            "cmd": "ready",
            "letters": list(languages.get("en").module.ORDER),
            "completed": progress.completed_letters("en"),
            "kn_label_img": str(kn_label) if kn_label.exists() else "",
            "langs": [
                {"code": l.code, "label": l.label,
                 "letters": list(l.module.ORDER),
                 "completed": progress.completed_letters(l.code)}
                for l in languages.LANGS.values()
            ],
        })
        ev = self.wait("begin")
        if ev is None:
            return
        # ALPHABET_LANG pins the whole process to one alphabet regardless of what
        # the UI asks for — the way to ship a Kannada launcher/desktop icon before
        # the start-screen toggle lands. When unset, the UI's begin.lang wins.
        forced = os.getenv("ALPHABET_LANG")
        self.lang = languages.get(forced) if forced else languages.get(ev.get("lang"))
        letter = ev.get("letter") or progress.next_letter(
            self.lang.module.ORDER, self.lang.code)
        while self.alive and letter:
            try:
                letter = self.lesson(letter)
            except Exception as exc:
                print(f"[alpha] lesson {letter} failed: {exc}", flush=True)
                self.send({"cmd": "status", "value": "error", "text": str(exc)})
                return
        if self.run is not None:
            self.run.save(completed=False)     # left mid-lesson; still practice


# ---------------------------------------------------------------------------
# Background prewarm of the next letter

_prewarm_lock = threading.Lock()
_prewarmed: set[str] = set()


def _prewarm_ahead(letter: str, lang: Language, depth: int = 1) -> None:
    """Cache the next `depth` letters' lines while the child works on this one."""
    order = lang.module.ORDER
    i = order.index(letter)
    targets = [order[(i + k) % len(order)] for k in range(1, depth + 1)]

    def _work() -> None:
        for ch in targets:
            key = f"{lang.code}:{ch}"          # the two alphabets share this set
            with _prewarm_lock:
                if key in _prewarmed:
                    continue
                _prewarmed.add(key)
            try:
                speech.prewarm(list(lang.module.lesson_lines(ch).values()), lang.voice)
            except Exception as exc:
                with _prewarm_lock:
                    _prewarmed.discard(key)     # let a later lesson retry
                print(f"[alpha] prewarm {ch} failed: {exc}", flush=True)

    threading.Thread(target=_work, daemon=True).start()


# ---------------------------------------------------------------------------
# HTTP: readiness + the parent report


class _Health(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):        # keep the console for lesson logs
        pass

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"ok": True, **_state})
        elif self.path == "/parent":
            self._json(200, progress.parent_summary())
        else:
            self._json(404, {"error": "not found"})


def _http_thread(port: int) -> None:
    HTTPServer(("127.0.0.1", port), _Health).serve_forever()


# ---------------------------------------------------------------------------


def warm_clients() -> None:
    """Build the cloud clients and prove credentials work, before the UI opens.

    Client construction is 4-9 s (CLAUDE.md); doing it here means the first
    spoken line of the first lesson is not the thing that pays for it.
    """
    speech.synth("Hello.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=UI_PORT)
    ap.add_argument("--http-port", type=int, default=HTTP_PORT)
    ap.add_argument("--prewarm-all", action="store_true",
                    help="synthesize every line of every lesson, all languages, then exit")
    ap.add_argument("--prewarm-lang", choices=sorted(languages.LANGS),
                    help="restrict --prewarm-all to one language")
    args = ap.parse_args()

    progress.init()

    if args.prewarm_all:
        langs = ([languages.get(args.prewarm_lang)] if args.prewarm_lang
                 else list(languages.LANGS.values()))
        total_made = total_cached = 0
        for lang in langs:
            lines = all_lines(lang)
            print(f"[alpha] prewarming {len(lines)} lines for {lang.code} "
                  f"({lang.voice.name})...", flush=True)
            made, cached = speech.prewarm(lines, lang.voice)
            print(f"[alpha]   {lang.code}: {made} synthesized, {cached} already cached")
            total_made += made
            total_cached += cached
        print(f"[alpha] done: {total_made} synthesized, {total_cached} already cached")
        return 0

    threading.Thread(target=_http_thread, args=(args.http_port,), daemon=True).start()

    try:
        warm_clients()
        _state["ready"] = True
        print("[alpha] cloud voice warm", flush=True)
    except Exception as exc:
        _state["error"] = str(exc)
        print(f"[alpha] WARNING: cloud voice not available: {exc}", flush=True)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", args.port))
    srv.listen(1)
    print(f"[alpha] lesson channel on :{args.port}, health on :{args.http_port}",
          flush=True)

    try:
        while True:
            conn, _ = srv.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print("[alpha] UI connected", flush=True)
            try:
                Session(conn).serve()
            finally:
                conn.close()
                print("[alpha] UI disconnected", flush=True)
    except KeyboardInterrupt:
        print("\n[alpha] bye")
    finally:
        srv.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
