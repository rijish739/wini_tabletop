#!/bin/bash
# Walk one lesson on the real panel and screenshot every stage.
#
# Runs the real UI and the real brain, driving touches synthetically, so what
# lands in /tmp/alpha_*.png is exactly what a child would see. Backend-agnostic:
# display_env.sh supplies shot/tap/ptr for Wayland (grim + wlrctl) or X11
# (scrot + xdotool).
#
# Stage changes are detected by WATCHING THE BRAIN LOG rather than by sleeping a
# guessed number of seconds. Timings are not stable: the first run of a letter
# pays for cloud TTS, every later run replays from the disk cache and is seconds
# faster, so fixed sleeps silently photograph the wrong stage (they did exactly
# that on the first attempt — intro and listen were missed entirely).
#
# Usage: pi_game/shoot_stages.sh [letter]
set -u
cd "$(dirname "$(readlink -f "$0")")/.." || exit 1
. pi_game/display_env.sh

LETTER="${1:-A}"
LOG=logs/alphabet.log

# Layout constants, mirrored from alpha_screens.c. Measured on the panel:
# the robot occupies y 140..499 and the food rests centred at y≈681.
TILE_X=178; TILE_Y=430          # top-left tile of the 2x2 board
FOOD_X=300; FOOD_Y=650          # food at BOTTOM_MID of the content area
ROBOT_X=300; ROBOT_Y=320        # robot face centre
START_X=300; START_Y=935

SHOT() { shot "/tmp/alpha_$1.png"; echo "  shot $1"; }

# The brain appends to one long-lived log across runs, so remember where THIS
# run starts and only ever look past that mark — otherwise the first wait_stage
# matches a stage from a previous lesson and every screenshot races ahead.
BASE=$(wc -l < "$LOG" 2>/dev/null || echo 0)

wait_stage() {
    local want="$1" limit="${2:-45}" start hits
    start=$(date +%s)
    while [ $(( $(date +%s) - start )) -lt "$limit" ]; do
        hits=$(tail -n "+$((BASE + 1))" "$LOG" 2>/dev/null \
               | grep -c "STAGEMARK $want" || true)
        [ "${hits:-0}" -gt 0 ] && { sleep 0.6; return 0; }   # settle the fade
        sleep 0.3
    done
    echo "  !! timed out waiting for stage '$want'"
    return 1
}

echo "[shoot] backend: $WINI_BACKEND"
SHOT 0_splash
tap $START_X $START_Y
echo "  tap Start"

for s in intro listen touch; do
    wait_stage "$s" 60 && SHOT "$s"
done

tap $TILE_X $TILE_Y
echo "  tap tile ($TILE_X,$TILE_Y)"
sleep 1.5
SHOT touch_ok

wait_stage repeat 30 && SHOT repeat
wait_stage assoc  60 && SHOT assoc
wait_stage activity 40 && SHOT activity

# Drag the food onto the robot's face. One process owns the whole gesture
# (press, motion, lift) — see display_env.sh for why that is load-bearing.
drag $FOOD_X $FOOD_Y $ROBOT_X $ROBOT_Y 10 0.06
echo "  dragged food onto the robot"
sleep 1.5
SHOT fed

wait_stage complete 40 && SHOT complete
echo "[shoot] done -> /tmp/alpha_*.png"
