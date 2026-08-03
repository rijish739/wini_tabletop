#!/usr/bin/env python3
"""
Board Buddy IPC test — mirrors exactly what BoardBuddySink does in production:
  text=True, bufsize=1, reader thread with blocking readline, stdin.write+flush.

Run from ~/cloud_tutor/cloud-CLI:
    # headless (SSH):
    SDL_VIDEODRIVER=offscreen python tools/run_bb_ipc_test.py

    # real Wayland display (desktop session):
    WAYLAND_DISPLAY=wayland-0 SDL_VIDEODRIVER=wayland python tools/run_bb_ipc_test.py
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # cloud-CLI root
PLAYER_MOD = [sys.executable, "-u", "-m", "wini_client.board_buddy_player"]

env = dict(os.environ)
env.setdefault("SDL_VIDEODRIVER", "offscreen")
env.setdefault("WINI_BB_PATH", os.path.expanduser("~/board_buddy_sandbox"))
env.setdefault("WINI_BB_BORDERLESS", "1")
# Wayland needs WAYLAND_DISPLAY if SDL_VIDEODRIVER=wayland
if env.get("SDL_VIDEODRIVER") == "wayland":
    env.setdefault("WAYLAND_DISPLAY", "wayland-0")
    env.setdefault("XDG_RUNTIME_DIR", "/run/user/1000")

print(f"[test] SDL_VIDEODRIVER={env['SDL_VIDEODRIVER']}", flush=True)
print(f"[test] WINI_BB_PATH={env['WINI_BB_PATH']}", flush=True)
print(f"[test] cwd={BASE}", flush=True)
print(f"[test] spawning {' '.join(PLAYER_MOD)}", flush=True)

proc = subprocess.Popen(
    PLAYER_MOD,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    env=env,
    cwd=BASE,
    text=True,
    bufsize=1,
)
print(f"[test] player PID={proc.pid}", flush=True)

# ── ack reader thread (mirrors BoardBuddySink._read_acks exactly) ──────────────
ack_q: queue.Queue = queue.Queue()
err_q: queue.Queue = queue.Queue()

def _read_acks() -> None:
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            print(f"[player->] {obj}", flush=True)
            ack_q.put(obj)
        except Exception:
            print(f"[player raw] {line!r}", flush=True)
    ack_q.put(None)   # sentinel: stdout closed

def _read_stderr() -> None:
    for line in proc.stderr:
        err_q.put(line.rstrip())

threading.Thread(target=_read_acks, name="acks", daemon=True).start()
threading.Thread(target=_read_stderr, name="errs", daemon=True).start()


def send(obj: dict) -> None:
    try:
        proc.stdin.write(json.dumps(obj, separators=(",", ":")) + "\n")
        proc.stdin.flush()
    except OSError as e:
        print(f"[test] stdin write failed: {e}", flush=True)


def wait_ack(targets: set, timeout: float) -> dict | None:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            obj = ack_q.get(timeout=min(remaining, 1.0))
            if obj is None:   # stdout closed
                return None
            if obj.get("ack") in targets:
                return obj
        except queue.Empty:
            rc = proc.poll()
            if rc is not None:
                print(f"[test] player exited early: code={rc}", flush=True)
                return None


# ── 1. Ready ────────────────────────────────────────────────────────────────────
print("[test] waiting for ready (prewarm ~5 s) ...", flush=True)
t0 = time.monotonic()
ack = wait_ack({"ready", "unavailable"}, timeout=35)
if ack is None:
    print(f"[test] FAIL – no ready ack in 35 s", flush=True)
    # Dump any stderr
    time.sleep(0.3)
    while True:
        try: print(f"  stderr: {err_q.get_nowait()}", flush=True)
        except queue.Empty: break
    proc.kill()
    sys.exit(1)
if ack.get("ack") == "unavailable":
    print(f"[test] FAIL – renderer unavailable: {ack.get('error')}", flush=True)
    proc.kill()
    sys.exit(1)
print(f"[test] READY in {time.monotonic()-t0:.1f} s", flush=True)

# ── 2. Send board payload ───────────────────────────────────────────────────────
payload = [
    {"id": "el0", "type": "sticker", "item": "star", "pos": [450, 60], "size": 80},
    {"id": "el1", "type": "geometry", "shape": "rectangle",
     "color": "#1565c0", "pos": [100, 120], "width": 200, "height": 150},
    {"id": "el2", "type": "text", "text": "Board Buddy IPC Test",
     "size": 20, "color": "#271F18", "pos": [130, 80]},
    {"id": "el3", "type": "numberline", "min": -3, "max": 3,
     "pos": [50, 400], "width": 500,
     "hops": [{"start": -2, "end": -2, "color": "#e53935"},
               {"start": 1, "end": 1, "color": "#43a047"}]},
]
print(f"[test] sending payload ({len(payload)} elements) ...", flush=True)
t1 = time.monotonic()
send({"cmd": "board", "payload": payload, "tmax": 0})
ack2 = wait_ack({"animation_done", "render_error", "load_error"}, timeout=20)
ms = int((time.monotonic() - t1) * 1000)

if ack2 and ack2.get("ack") == "animation_done":
    print(f"[test] PASS – static render acked in {ms} ms", flush=True)
elif ack2 and ack2.get("ack") in ("load_error", "render_error"):
    print(f"[test] FAIL – render error: {ack2}", flush=True)
else:
    print(f"[test] FAIL – no animation_done in {ms} ms  ack={ack2}", flush=True)

# Dump any player stderr
time.sleep(0.2)
while True:
    try: print(f"  stderr: {err_q.get_nowait()}", flush=True)
    except queue.Empty: break

# ── 3. Screenshot (grim, only if real Wayland) ────────────────────────────────
if env["SDL_VIDEODRIVER"] != "offscreen":
    time.sleep(0.5)
    shot = "/tmp/bb_ipc_test.png"
    r = subprocess.run(["grim", "-g", "0,0 600 845", shot],
                       capture_output=True, timeout=10)
    if r.returncode == 0:
        sz = os.path.getsize(shot)
        print(f"[test] screenshot {sz//1024} KB → {shot}", flush=True)
    else:
        print(f"[test] grim: {r.stderr[:120]}", flush=True)

# ── 4. Close ───────────────────────────────────────────────────────────────────
send({"cmd": "close"})
try:
    proc.wait(timeout=5)
except subprocess.TimeoutExpired:
    proc.kill()
print(f"[test] player exit={proc.returncode}", flush=True)
