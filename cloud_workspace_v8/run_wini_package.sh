#!/bin/bash
# run_wini_package.sh — one-press launcher for the complete Wini tutor package:
#   brain (wini_server.py) + voice client (wini_client, --display lvgl) + touch
#   UI (wini_ui) on the DSI panel.
#
# Made for the desktop icon on winipi5 (~/Desktop/Wini.desktop): launch it from
# the seat so the processes inherit DISPLAY/XAUTHORITY and the desktop audio
# session (a bare-SSH launch has no PipeWire session — the mic won't open).
#
# Idempotent: if all three pieces are already running it exits quietly; if only
# some are (a crash, a half start), it stops the leftovers and starts a coherent
# fresh set. Concurrent launches are serialized by a lock (see below).
#
# Start order is deliberate: brain + client first, then the UI ONLY once the
# brain reports ready. The panel therefore stays dark for the warmup (~15 s) and
# lights up working, instead of showing a picker that does nothing.
# Logs: logs/{launch,brain,client,wini_ui}.log (appended).

cd "$(dirname "$(readlink -f "$0")")" || exit 1
mkdir -p logs

# Single-launch lock. The desktop icon is silent (Terminal=false) and the panel
# now stays dark for the ~15 s warmup, so an impatient second tap is likely — and
# without this it would find "server+client up, UI not up", kill the healthy
# half-start and begin again, resetting the wait. -n: a second launch just exits.
#
# Every long-lived child below is spawned with `9>&-`. Without that they inherit
# the lock fd and hold the lock for the whole session — the launcher exits, the
# brain keeps fd 9 open, and the NEXT icon tap silently no-ops forever. Verified
# the hard way: a leaked poller held it and killed the following launch.
exec 9> logs/.launch.lock
if ! flock -n 9; then
    echo "[wini] another launch is already in progress — ignoring."
    exit 0
fi

# The desktop icon runs with Terminal=false, so this is the only record of what
# the launch did. Keep it with the other logs.
exec > >(tee -a logs/launch.log) 2>&1
echo "[wini] ---- launch $(date '+%F %T') ----"

# wini_ui is an X11 client (LVGL+SDL2) — it must reach the running desktop
# (Xorg :0 on seat0) to appear on the DSI panel. Launched from the desktop icon
# these are already in the env; over SSH they are NOT, and SDL then silently
# falls back to an offscreen/dummy video driver (window created, nothing shown).
# Default them so every launch path renders on the panel (matches run_wini_ui.sh).
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

# Load config early (Part 15): WINI_SERVER selects LOCAL vs CLOUD brain. A remote
# https URL (the Cloud Run service) means the brain runs in the cloud and this Pi is
# a pure thin client — no local wini_server.py. Anything else (default) is today's
# on-Pi brain. WINI_SA_KEY (a service-account key path) is how the client
# authenticates to the private Cloud Run service; it rides in .env.
set -a; [ -f ./.env ] && . ./.env; set +a
export GEN_BACKEND="${GEN_BACKEND:-gemini}"
WINI_SERVER="${WINI_SERVER:-http://127.0.0.1:8123}"
CLOUD_MODE=0
case "$WINI_SERVER" in https://*) CLOUD_MODE=1;; esac

if [ "$CLOUD_MODE" = 1 ]; then
    # Cloud brain: only the client + UI run locally.
    if pgrep -f 'wini_client\.client' >/dev/null && pgrep -x wini_ui >/dev/null; then
        echo "[wini] already running (cloud brain $WINI_SERVER) — nothing to do."
        exit 0
    fi
elif pgrep -f 'wini_server\.py' >/dev/null \
        && pgrep -f 'wini_client\.client' >/dev/null \
        && pgrep -x wini_ui >/dev/null; then
    echo "[wini] already running — nothing to do."
    exit 0
fi

# pkill -f with a [b]racket so the pattern never matches this script itself.
pkill -x wini_ui 2>/dev/null
pkill -f 'wini_[c]lient.client' 2>/dev/null
pkill -f 'wini_[s]erver.py' 2>/dev/null
# Stop the always-on background touch-emotion service: it owns GPIO22 + the
# single reSpeaker output substream, and the tutor client claims both itself
# (mutually exclusive). touch stays live during tutoring via the client's own
# engine; stop_wini_package.sh resumes the background service afterwards.
pkill -f 'touch_[s]ervice.py' 2>/dev/null
sleep 1

if [ "$CLOUD_MODE" = 1 ]; then
    echo "[wini] cloud brain: $WINI_SERVER (no local brain on this Pi)"
    [ -n "$WINI_SA_KEY" ] || echo "[wini] WARNING: WINI_SA_KEY unset — client calls to the cloud brain will 401."
else
    echo "[wini] starting brain..."
    # -u: without it the brain's stdout is block-buffered into the log file, so the
    # boot/warmup/per-turn timing lines sit in a 4 KB buffer for the whole session
    # and only the handler's stderr [http] lines show up — the timings you most want
    # when a turn feels slow are exactly the ones that go missing.
    setsid .venv/bin/python -u wini_server.py --port 8123 >> logs/brain.log 2>&1 9>&- &
fi

# The client waits for the brain itself (wait_ready) and binds the UI channel
# (:8140) immediately, so both can start right away. In cloud mode it targets the
# Cloud Run URL and authenticates with WINI_SA_KEY (both from .env).
echo "[wini] starting voice client (server=$WINI_SERVER)..."
# Scenes ENABLED (2026-07-27): the cloud brain now runs the Response Layer
# (WINI_RESPONSE_LAYER=1). A tier-0 scene is no longer armed by concept alone —
# the Visual Benefit Gate earns it per turn and the brain rides an authoritative
# `visual` directive (arm_scene) on turn_meta, so the client only shows a scene
# when it is genuinely warranted for THIS turn's claim (and the spoken answer is
# told a figure is on screen). That fixes the concept-default mismatch --no-scenes
# was guarding against. Absent the directive (brain flag off) the client falls back
# to today's behavior, so this is safe either way.
#
# Board Buddy ENABLED (2026-07-29): when the brain emits a board_buddy_payload on
# turn_meta (requires WINI_RESPONSE_LAYER=1 on the brain side — already set on
# Cloud Run), the client spawns the pygame Board Buddy child (board_buddy_player.py)
# under labwc as a second Wayland surface at (0,0)/600×845. WINI_BOARD_BUDDY=1 is
# the client-side gate; WINI_BB_PATH points to the frozen v1.0 renderer.
export WINI_BOARD_BUDDY=1
export WINI_BB_PATH="$HOME/board_buddy_sandbox"
setsid .venv/bin/python -u -m wini_client.client \
    --server "$WINI_SERVER" --display lvgl --ui-port 8140 \
    --wait-for-mode --on-session-end exit >> logs/client.log 2>&1 9>&- &

# The UI must not appear until the whole pipeline is warm: a picker you can tap
# while the brain is still loading looks broken (that WAS the "the desktop icon
# doesn't start everything" report — same script, but the panel came up ~1 s in
# against a ~2 min boot). Warmup is ~15 s now; we still gate on the real signal,
# not a sleep. Poll /health rather than the log so a crash-restart still counts.
if [ "$CLOUD_MODE" = 1 ]; then
    # The Cloud Run brain runs min-instances=1 (always warm), and the client does
    # its own authenticated wait_ready — so there is no local warmup to gate on.
    echo "[wini] cloud brain is warm (min-instances=1); client handles readiness."
    brain_ok=0
else
echo "[wini] waiting for the brain to warm up..."
.venv/bin/python - 9>&- <<'PY'
import sys, time, json, urllib.request
DEADLINE = time.monotonic() + 180
while time.monotonic() < DEADLINE:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8123/health", timeout=3) as r:
            h = json.load(r)
        if h.get("ready"):
            print(f"[wini] brain ready (gen_backend={h.get('gen_backend')})")
            sys.exit(0)
        if h.get("error"):
            print(f"[wini] brain failed to load: {h['error']}")
            sys.exit(1)
    except Exception:
        pass          # not listening yet
    time.sleep(0.5)
print("[wini] brain did not report ready within 180 s")
sys.exit(1)
PY
brain_ok=$?
fi

echo "[wini] starting touch UI..."
# SDL_AUDIODRIVER=dummy: the reSpeaker has ONE playback substream and the voice
# client owns it — the UI must never claim the speaker for its beep cues
# (wini_client/SPEAKER_TROUBLESHOOTING.md; main.c also defaults to dummy).
# WINI_STOP_CMD: what the on-screen Close button runs (widgets/close_button.c).
# Started even if the wait timed out — the UI then holds its splash and says so,
# which beats a black panel with no explanation.
setsid env SDL_AUDIODRIVER=dummy \
    WINI_STOP_CMD="$PWD/stop_wini_package.sh" \
    ./wini_ui/build/wini_ui --port 8140 >> logs/wini_ui.log 2>&1 9>&- &

if [ "$brain_ok" -eq 0 ]; then
    echo "[wini] launched — the panel shows the picker and the first voice turn works."
else
    echo "[wini] UI started, but the brain is NOT ready — see logs/brain.log."
fi
exit "$brain_ok"
