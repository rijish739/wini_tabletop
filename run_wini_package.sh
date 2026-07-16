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
# fresh set. Logs: logs/{brain,client,wini_ui}.log (appended).

cd "$(dirname "$(readlink -f "$0")")" || exit 1
mkdir -p logs

if pgrep -f 'wini_server\.py' >/dev/null \
        && pgrep -f 'wini_client\.client' >/dev/null \
        && pgrep -x wini_ui >/dev/null; then
    echo "[wini] already running — nothing to do."
    exit 0
fi

# pkill -f with a [b]racket so the pattern never matches this script itself.
pkill -x wini_ui 2>/dev/null
pkill -f 'wini_[c]lient.client' 2>/dev/null
pkill -f 'wini_[s]erver.py' 2>/dev/null
sleep 1

set -a; [ -f ./.env ] && . ./.env; set +a
export GEN_BACKEND="${GEN_BACKEND:-gemini}"

echo "[wini] starting brain..."
setsid .venv/bin/python wini_server.py --port 8123 >> logs/brain.log 2>&1 &

# The client waits for the brain itself (wait_ready) and binds the UI channel
# (:8140) immediately, so both can start right away.
echo "[wini] starting voice client..."
setsid .venv/bin/python -u -m wini_client.client \
    --server http://127.0.0.1:8123 --display lvgl --ui-port 8140 \
    --wait-for-mode --on-session-end exit >> logs/client.log 2>&1 &

sleep 1
echo "[wini] starting touch UI..."
# SDL_AUDIODRIVER=dummy: the reSpeaker has ONE playback substream and the voice
# client owns it — the UI must never claim the speaker for its beep cues
# (wini_client/SPEAKER_TROUBLESHOOTING.md; main.c also defaults to dummy).
setsid env SDL_AUDIODRIVER=dummy ./wini_ui/build/wini_ui --port 8140 >> logs/wini_ui.log 2>&1 &

echo "[wini] launched — the panel shows the picker once the UI is up;"
echo "       the first voice turn works as soon as the brain reports ready."
exit 0
