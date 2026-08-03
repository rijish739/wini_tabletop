"""Scene beat-player — plays an animated maths scene ON THE DEVICE: each beat's
visual is shown on the LVGL panel while its narration is spoken, in step.

This is the client half of the dynamic-visuals work (figures/SCENE_SYNC.md). It is
self-contained so a scene can be shown on the real panel + speaker WITHOUT the mic /
STT / brain path:

    for each beat:
        render the accumulated frame  -> /tmp/wini_scene_<i>.png
        push {"cmd":"figure","path":...} + {"cmd":"explain","body":narration} to the UI
        synth the narration (Cloud TTS) and PLAY it, blocking
        -> next beat

Sync is beat-level: the picture grows one step as each sentence is spoken. That is the
robust device cadence (each figure swap writes a PNG + reloads the LVGL card); smooth
intra-beat animation (the GIF draw-on) is a later enhancement.

The player hosts the SAME mode channel the client uses (:8140), so the existing
``wini_ui`` binary connects to it unchanged. Launch the UI separately (this module can
do it with --launch-ui). Reuses ``voice.cloud_tts`` for speech and the client's
``play_pcm`` for the reSpeaker-aware (24k->16k) playback.

    .venv/bin/python -m wini_client.scene_player \\
        rag_store/figure_specs/jemh104__quadratic_formula.scene.json --launch-ui

Flags: --port 8140, --theme light|dark, --no-audio (visual only), --launch-ui,
--ui-bin wini_ui/build/wini_ui, --hold 3 (seconds to hold the final frame).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from figures.scene_render import render_beat_frame
from .mode_channel import ModeState, ModeChannel

ROOT = Path(__file__).resolve().parent.parent
FIG_SLOTS = 6                          # /tmp/wini_scene_{0..5}.png, cycled


def _concept_title(scene: dict) -> str:
    return scene.get("title") or scene.get("concept_id", "").split("__")[-1].replace("_", " ").title()


# ── concept -> scene selection (the live mic path's tier-0 lookup, §4) ────────

_INDEX_CACHE: "dict | None" = None
_SCENE_CACHE: "dict[str, dict | None]" = {}


def load_scene_index(store_dir: "Path | str | None" = None) -> dict:
    """Read + memoize rag_store/concept_figures.json (the concept -> scene index
    build_chapter_scenes writes). Missing/broken index => empty map (the caller
    just falls through to today's T9 crop path)."""
    global _INDEX_CACHE
    if _INDEX_CACHE is not None:
        return _INDEX_CACHE
    store = Path(store_dir) if store_dir else (ROOT / "rag_store")
    idx_path = store / "concept_figures.json"
    try:
        _INDEX_CACHE = json.loads(idx_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 — no index just means no tier-0 scenes
        print(f"[scene] no scene index ({e}); tier-0 scenes disabled")
        _INDEX_CACHE = {}
    return _INDEX_CACHE


def scene_for_concept(concept_id: "str | None",
                      store_dir: "Path | str | None" = None) -> "dict | None":
    """Resolve a resolved-concept id to its authored, VALIDATED scene dict, or None
    (no entry / unreadable / structurally invalid — every miss degrades cleanly to
    the crop path). Result is memoized per concept id so a live turn's lookup is a
    dict hit after the first."""
    if not concept_id:
        return None
    if concept_id in _SCENE_CACHE:
        return _SCENE_CACHE[concept_id]
    scene = None
    entry = load_scene_index(store_dir).get(concept_id)
    if entry and entry.get("scene"):
        # Index paths are repo-root-relative ("rag_store/figure_specs/..."); also
        # accept an absolute path or one relative to the store's parent.
        cand = Path(entry["scene"])
        for p in (cand, ROOT / cand):
            try:
                if p.exists():
                    s = json.loads(p.read_text(encoding="utf-8"))
                    if s.get("beats"):
                        # Phase 2.5: do not accept a legacy scene whose narration
                        # can compete with Teaching-Script speech in a live turn.
                        from response_layer.scene_adaptation import review_scene
                        review = review_scene(s)
                        if review.ok:
                            scene = s
                        else:
                            print(f"[scene] {concept_id}: adaptation review failed "
                                  f"({'; '.join(review.issues)}); using crop path")
                    break
            except Exception as e:  # noqa: BLE001 — a bad scene must never cost a turn
                print(f"[scene] {concept_id}: unreadable scene ({e}); using crop path")
                break
    _SCENE_CACHE[concept_id] = scene
    return scene


def play_beat(scene: dict, i: int, chan: ModeChannel, theme: str,
              speaker: "_Speaker", tmp_dir: "Path | None" = None) -> None:
    """Render + show + speak ONE beat: the accumulated frame after beat i, its
    caption card, then its narration spoken to completion. Factored out of
    ``play_scene`` so the live client can drive beats from its STT/brain loop
    (SCENE_VISUALS_GUIDE §4.3) with the SAME cadence as the standalone demo."""
    tmp = tmp_dir or Path(os.environ.get("TMPDIR", "/tmp"))
    beat = scene["beats"][i]
    narr = (beat.get("narration") or "").strip()
    png = tmp / f"wini_scene_{i % FIG_SLOTS}.png"
    render_beat_frame(scene, i, theme, scale=2.0, out_path=str(png))
    chan.send({"cmd": "figure", "path": str(png)})
    if narr:
        chan.send({"cmd": "explain", "title": _concept_title(scene)[:40],
                   "body": narr[:800]})
    speaker.say(narr)
    time.sleep(0.25)               # small breath between steps


def _wait_ui(chan: ModeChannel, timeout: float = 20.0) -> bool:
    """Block until the UI connects to the mode channel (chan._conn set)."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        with chan._conn_lock:
            if chan._conn is not None:
                return True
        time.sleep(0.2)
    return False


class _Speaker:
    """Cloud TTS -> the client's reSpeaker-aware blocking playback. Falls back to a
    timed silent pause if TTS/audio is unavailable, so the visual demo still paces."""

    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.tts = None
        self.play = None
        if not enabled:
            return
        try:
            from voice.cloud_tts import CloudTts
            from wini_client.client import play_pcm, prime_output
            self.tts = CloudTts()
            self.play = play_pcm
            prime_output()             # open the persistent output stream up front
            print("[scene] audio ready (Cloud TTS + reSpeaker playback)")
        except Exception as e:  # noqa: BLE001 — never let audio setup stop the visual
            print(f"[scene] audio unavailable ({e}); playing visual-only with timed pacing")
            self.enabled = False

    def say(self, text: str) -> None:
        if self.enabled and self.tts and self.play:
            try:
                pcm = self.tts.synth(text)
                if pcm:
                    self.play(pcm, self.tts.rate)   # blocks until spoken
                    return
            except Exception as e:  # noqa: BLE001
                print(f"[scene] TTS/play failed ({e}); pausing instead")
        # visual-only pacing: ~55 ms per word, floor 1.4 s
        time.sleep(max(1.4, 0.055 * len(text.split())))


def play_scene(scene: dict, chan: ModeChannel, theme: str, speaker: _Speaker,
               hold: float = 3.0) -> None:
    tmp = Path(os.environ.get("TMPDIR", "/tmp"))
    chan.send({"cmd": "screen", "to": "explain"})
    chan.send({"cmd": "stage", "v": "explain"})
    chan.send({"cmd": "lines", "l1": _concept_title(scene)[:60]})
    chan.send({"cmd": "status", "v": "teaching"})
    time.sleep(0.3)

    n = len(scene["beats"])
    for i in range(n):
        narr = (scene["beats"][i].get("narration") or "").strip()
        print(f"[scene] beat {i+1}/{n}: {narr}")
        play_beat(scene, i, chan, theme, speaker, tmp_dir=tmp)

    print(f"[scene] done — holding final frame {hold:.0f}s")
    chan.send({"cmd": "status", "v": "idle"})
    time.sleep(hold)


def _launch_ui(ui_bin: str, port: int):
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    env.setdefault("XAUTHORITY", str(Path.home() / ".Xauthority"))
    env.setdefault("SDL_AUDIODRIVER", "dummy")     # client owns the speaker
    print(f"[scene] launching UI: {ui_bin} --port {port}")
    return subprocess.Popen([ui_bin, "--port", str(port)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def main() -> int:
    ap = argparse.ArgumentParser(description="Play a scene on the device (visual+audio).")
    ap.add_argument("scene")
    ap.add_argument("--port", type=int, default=8140)
    ap.add_argument("--theme", default="light", choices=["light", "dark"])
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--launch-ui", action="store_true", help="also start wini_ui")
    ap.add_argument("--ui-bin", default=str(ROOT / "wini_ui" / "build" / "wini_ui"))
    ap.add_argument("--hold", type=float, default=4.0)
    ap.add_argument("--loop", action="store_true", help="replay until Ctrl-C")
    args = ap.parse_args()

    scene = json.loads(Path(args.scene).read_text(encoding="utf-8"))

    state = ModeState()
    chan = ModeChannel(state, port=args.port).start()
    time.sleep(0.4)                    # let the listener bind before the UI connects

    ui_proc = _launch_ui(args.ui_bin, args.port) if args.launch_ui else None

    if not _wait_ui(chan, timeout=25.0):
        print("[scene] no UI connected on :%d — is wini_ui running? "
              "(run with --launch-ui, or start it separately)" % args.port)
        if ui_proc:
            ui_proc.terminate()
        return 1
    print("[scene] UI connected")
    chan.set_sticky({"cmd": "ready"})   # release the UI splash if it is gated

    speaker = _Speaker(enabled=not args.no_audio)
    try:
        while True:
            play_scene(scene, chan, args.theme, speaker, hold=args.hold)
            if not args.loop:
                break
    except KeyboardInterrupt:
        print("\n[scene] stopped")
    finally:
        if ui_proc:
            ui_proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
