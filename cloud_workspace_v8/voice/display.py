"""T9 multimodal display channel — DisplaySink adapters for the voice rig.

This is the *voice-side* renderer for the `display` list that `tutor_loop.turn()`
now returns (the web UI renders the same list in the browser). It mirrors the
STT/TTS adapter pattern: the runner calls

    sink.show(result["display"])   # when speech starts
    sink.clear()                   # when playback ends

so the textbook crop is shown *while Wini speaks* and cleared on turn end.

`image_path` values in the turn result are store-relative; every sink resolves
them against the store root (never hard-coded), exactly like the web `/store`
route and the planned Jetson `/display_image` node.

Sinks
-----
NullDisplaySink : no-op. This is the default, so `voice_hybrid_runner.py` runs
                  text+voice with NO visual unless you opt in (`--display tk`),
                  keeping plain voice testing unchanged.
TkDisplaySink   : a small always-on-top window (stdlib tkinter; Pillow used for
                  clean resizing if present, else tk.PhotoImage + subsample).
                  Runs its own UI thread so the audio hot path never blocks.

Pick one with `make_display_sink("none" | "tk")`.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# store root — `image_path` is relative to this (…/rag_store/figure_crops/…)
_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORE = _ROOT / "rag_store"


@runtime_checkable
class DisplaySink(Protocol):
    """Contract shared by every display surface (web, Tk pane, Jetson screen)."""

    def show(self, items: list[dict]) -> None:
        """Put the turn's primary visual up (one crop; items may be empty)."""

    def clear(self) -> None:
        """Take the visual down (turn/playback ended)."""

    def close(self) -> None:
        """Tear the sink down on shutdown."""


class NullDisplaySink:
    """Default no-op sink: text+voice with no visual, zero extra deps."""

    def show(self, items: list[dict]) -> None:  # noqa: D102
        pass

    def clear(self) -> None:  # noqa: D102
        pass

    def close(self) -> None:  # noqa: D102
        pass


class TkDisplaySink:
    """Always-on-top Windows pane. All Tk work happens on a dedicated thread;
    the runner thread only drops thread-safe commands on a queue, so showing or
    clearing an image never blocks STT/TTS/generation."""

    def __init__(self, store_root: Path | str = DEFAULT_STORE,
                 max_width: int = 480, title: str = "Wini — figure") -> None:
        self.store_root = Path(store_root)
        self.max_width = int(max_width)
        self.title = title
        self._q: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._ready = threading.Event()
        self._tk = None
        self._root = None
        self._img_label = None
        self._caption = None
        self._cur_img = None  # keep a ref so Tk does not GC the PhotoImage
        self._thread = threading.Thread(target=self._run, name="wini-display", daemon=True)
        self._thread.start()
        # if Tk cannot start (no display, missing tkinter) we silently degrade
        self._ready.wait(timeout=5.0)

    # ---- public API (runner thread) ------------------------------------
    def show(self, items: list[dict]) -> None:
        if not items:
            self._q.put(("clear", None))   # nothing to show this turn -> ensure pane is empty
            return
        self._q.put(("show", items[0]))    # one primary visual per turn (working-memory limit)

    def clear(self) -> None:
        self._q.put(("clear", None))

    def close(self) -> None:
        self._q.put(("close", None))

    # ---- Tk thread -----------------------------------------------------
    def _run(self) -> None:
        try:
            import tkinter as tk
        except Exception as exc:  # noqa: BLE001
            print(f"[display] tkinter unavailable, running without a visual pane: {exc}")
            self._ready.set()
            return
        self._tk = tk
        try:
            root = tk.Tk()
            root.title(self.title)
            root.attributes("-topmost", True)
            root.geometry("+48+48")
            root.configure(bg="#0d1117")
            self._caption = tk.Label(root, text="", wraplength=self.max_width, justify="left",
                                     fg="#9aa4b2", bg="#0d1117", font=("Segoe UI", 9))
            self._caption.pack(padx=10, pady=(8, 4))
            self._img_label = tk.Label(root, bg="#0d1117")
            self._img_label.pack(padx=10, pady=(0, 10))
            self._root = root
            root.withdraw()  # start hidden until the first show()
            self._ready.set()
            root.after(80, self._poll)
            root.mainloop()
        except Exception as exc:  # noqa: BLE001
            print(f"[display] Tk pane failed, continuing without a visual: {exc}")
            self._ready.set()

    def _poll(self) -> None:
        try:
            while True:
                cmd, payload = self._q.get_nowait()
                if cmd == "show":
                    self._do_show(payload)
                elif cmd == "clear":
                    self._do_clear()
                elif cmd == "close":
                    self._root.destroy()
                    return
        except queue.Empty:
            pass
        except Exception as exc:  # noqa: BLE001
            print(f"[display] command error: {exc}")
        if self._root is not None:
            self._root.after(80, self._poll)

    def _do_show(self, item: dict) -> None:
        rel = item.get("image_path")
        if not rel:
            return self._do_clear()
        path = self.store_root / rel
        if not path.exists():
            print(f"[display] crop not found: {path}")
            return self._do_clear()
        img = self._load(path)
        if img is None:
            return self._do_clear()
        self._cur_img = img
        self._img_label.configure(image=img)
        self._caption.configure(text=(item.get("alt_text") or "")[:200])
        self._root.deiconify()
        self._root.lift()

    def _do_clear(self) -> None:
        if self._root is None:
            return
        self._img_label.configure(image="")
        self._cur_img = None
        self._root.withdraw()

    def _load(self, path: Path):
        """Load + downscale the crop. Pillow for a clean resize if available,
        else stdlib tk.PhotoImage (PNG) with integer subsampling."""
        try:
            from PIL import Image, ImageTk
            im = Image.open(path)
            if im.width > self.max_width:
                h = max(1, round(im.height * self.max_width / im.width))
                im = im.resize((self.max_width, h))
            return ImageTk.PhotoImage(im)
        except Exception:
            try:
                ph = self._tk.PhotoImage(file=str(path))  # Tk 8.6 reads PNG natively
                if ph.width() > self.max_width:
                    ph = ph.subsample(max(1, ph.width() // self.max_width))
                return ph
            except Exception as exc:  # noqa: BLE001
                print(f"[display] could not load {path.name}: {exc}")
                return None


def make_display_sink(kind: str | None = "none", **kwargs) -> DisplaySink:
    """Factory. 'none' (default) -> NullDisplaySink; 'tk' -> Windows pane."""
    if kind in (None, "none", "off", ""):
        return NullDisplaySink()
    if kind == "tk":
        return TkDisplaySink(**kwargs)
    raise ValueError(f"unknown display kind {kind!r} (expected 'none' or 'tk')")
