#!/bin/bash
# run_alphabet.sh — one-press launcher for the alphabet learning module:
#   brain (pi_game/alphabet_server.py) + touch UI (pi_game/alphabet_ui) on the
#   DSI panel.
#
# Made for the desktop icon (~/Desktop/Wini-Letters.desktop). Launch it from the
# seat so the processes inherit DISPLAY/XAUTHORITY and the desktop audio session:
# a bare-SSH launch renders the UI fine but has no PipeWire session, so the MIC
# will not open and Stage 4 silently records nothing.
#
# Deliberately mirrors run_wini_package.sh — same lock, same ordering, same
# speaker-ownership handling — so there is one launch pattern on this device.
# Logs: logs/{alphabet_launch,alphabet,alphabet_ui}.log (appended).

cd "$(dirname "$(readlink -f "$0")")/.." || exit 1
mkdir -p logs

# Single-launch lock. The icon is silent (Terminal=false) and the panel stays
# dark through the warmup, so an impatient second tap is likely.
#
# Every long-lived child is spawned with `9>&-`: without it they inherit the lock
# fd and hold it for the whole session, and the NEXT icon tap silently no-ops
# forever. This bit is load-bearing — see PI_ACCESS.md §4.
exec 9> logs/.alphabet.lock
if ! flock -n 9; then
    echo "[letters] another launch is already in progress — ignoring."
    exit 0
fi

exec > >(tee -a logs/alphabet_launch.log) 2>&1
echo "[letters] ---- launch $(date '+%F %T') ----"

# Over SSH the display vars are unset and SDL silently falls back to an
# offscreen driver: the window is created and nothing ever appears on the panel.
# display_env.sh picks Wayland (winipi5's session since 2026-07-22) or X11 and
# exports what a GUI child needs, including SDL_VIDEODRIVER.
. pi_game/display_env.sh
echo "[letters] display backend: $WINI_BACKEND"

if pgrep -f 'pi_game.alphabet_server' >/dev/null && pgrep -x alphabet_ui >/dev/null; then
    echo "[letters] already running — nothing to do."
    exit 0
fi

# [b]racketed patterns so they never match this script's own command line.
pkill -x alphabet_ui 2>/dev/null
pkill -f 'pi_game.alphabet_[s]erver' 2>/dev/null
# The reSpeaker Lite exposes ONE playback substream and ONE GPIO22 claim, held by
# the always-on touch service while the device is idle. The brain needs the
# speaker, so stop it here; stop_alphabet.sh brings it back.
pkill -f 'touch_[s]ervice.py' 2>/dev/null
# The tutor owns the same speaker and the same panel — the two products cannot
# run at once.
pkill -x wini_ui 2>/dev/null
pkill -f 'wini_[c]lient.client' 2>/dev/null
pkill -f 'wini_[s]erver.py' 2>/dev/null
sleep 1

set -a; [ -f ./.env ] && . ./.env; set +a

echo "[letters] starting brain..."
setsid .venv/bin/python -u -m pi_game.alphabet_server >> logs/alphabet.log 2>&1 9>&- &

# Gate the UI on the real readiness signal, not a sleep: the brain builds its
# Google clients on boot (4-9 s of ADC/channel setup) and a picker you can tap
# while that is happening looks broken.
echo "[letters] waiting for the brain to warm up..."
.venv/bin/python - 9>&- <<'PY'
import sys, time, json, urllib.request
DEADLINE = time.monotonic() + 120
while time.monotonic() < DEADLINE:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8150/health", timeout=3) as r:
            h = json.load(r)
        if h.get("ready"):
            print("[letters] brain ready")
            sys.exit(0)
        if h.get("error"):
            print(f"[letters] brain has no cloud voice: {h['error']}")
            sys.exit(1)
    except Exception:
        pass
    time.sleep(0.5)
print("[letters] brain did not report ready within 120 s")
sys.exit(1)
PY
brain_ok=$?

echo "[letters] starting touch UI..."
# SDL_AUDIODRIVER=dummy: the brain owns the single playback substream and is what
# actually speaks; if SDL claims it for UI cues, Wini goes silent.
setsid env SDL_AUDIODRIVER=dummy \
    ALPHABET_STOP_CMD="$PWD/pi_game/stop_alphabet.sh" \
    ./pi_game/alphabet_ui/build/alphabet_ui >> logs/alphabet_ui.log 2>&1 9>&- &

if [ "$brain_ok" -eq 0 ]; then
    echo "[letters] launched — tap Start on the panel."
else
    echo "[letters] UI started, but the brain is NOT ready — see logs/alphabet.log."
fi
exit "$brain_ok"
