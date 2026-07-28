#!/bin/bash
# stop_wini_package.sh — stop the Wini tutor package (brain + client + UI) and
# resume the always-on background touch-emotion service.
#
# The tutor and touch_service.py are mutually exclusive (one reSpeaker output
# substream, one GPIO22 claim), so stopping the tutor frees both and we bring
# the background touch-emotions back.

cd "$(dirname "$(readlink -f "$0")")" || exit 1
mkdir -p logs

echo "[wini] stopping tutor package..."
pkill -x wini_ui 2>/dev/null
pkill -f 'wini_[c]lient.client' 2>/dev/null
pkill -f 'wini_[s]erver.py' 2>/dev/null
sleep 1

# Resume background touch-emotions now that the speaker + GPIO are free.
if pgrep -f 'touch_[s]ervice.py' >/dev/null; then
    echo "[wini] touch-emotion service already running."
else
    setsid .venv/bin/python3 -u touch_service.py >> logs/touch.log 2>&1 </dev/null &
    echo "[wini] tutor stopped; background touch-emotions resumed -> logs/touch.log"
fi
