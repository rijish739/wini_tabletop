#!/bin/bash
# stop_alphabet.sh — stop the alphabet module and hand the hardware back.
#
# Mirrors stop_wini_package.sh: kill both halves, then resume the always-on touch
# service that owns GPIO22 and the single reSpeaker playback substream while the
# device is idle. Skipping that last step is why "the robot stopped reacting to
# touch" usually turns out to be a launcher problem, not a hardware one.

cd "$(dirname "$(readlink -f "$0")")/.." || exit 1

echo "[letters] stopping..."
pkill -x alphabet_ui 2>/dev/null
pkill -f 'pi_game.alphabet_[s]erver' 2>/dev/null
sleep 1

# Release the launch lock holder if one leaked (a stale holder makes every later
# launch a silent no-op — PI_ACCESS.md §4).
if [ -f logs/.alphabet.lock ] && command -v fuser >/dev/null 2>&1; then
    fuser -k logs/.alphabet.lock 2>/dev/null
fi

if [ -f touch_service.py ] && ! pgrep -f 'touch_[s]ervice.py' >/dev/null; then
    echo "[letters] resuming the background touch service..."
    setsid .venv/bin/python3 -u touch_service.py >> logs/touch.log 2>&1 </dev/null &
fi

echo "[letters] stopped."
