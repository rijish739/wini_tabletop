#!/bin/bash
# Drag stress test for the feed activity.
#
# The drag is the one gesture in the module that a synthetic tap cannot stand in
# for, and it has broken twice in ways a slow scripted drag did not reveal. This
# exercises the cases a real finger produces:
#
#   fast    a flick with almost no intermediate motion events — what broke the
#           original relative-vector code, which needed every step to accumulate
#   slow    a careful drag with many small steps
#   offset  grabbed by the object's edge rather than its centre
#   short   released well before the robot — must glide home, NOT feed
#
# Run with the module already up and sitting on the activity stage.
# Usage: pi_game/test_drag.sh [fast|slow|offset|short]
set -u
cd "$(dirname "$(readlink -f "$0")")/.." || exit 1
. pi_game/display_env.sh

LOG=logs/alphabet.log
FOOD_X=300; FOOD_Y=650
ROBOT_X=300; ROBOT_Y=320

MODE="${1:-fast}"
BASE=$(wc -l < "$LOG")
echo "[drag] backend: $WINI_BACKEND (input: kernel uinput)"

case "$MODE" in
  fast)   echo "[drag] fast flick (2 steps)"
          drag $FOOD_X $FOOD_Y $ROBOT_X $ROBOT_Y 2 0.02 ;;
  slow)   echo "[drag] slow drag (20 steps)"
          drag $FOOD_X $FOOD_Y $ROBOT_X $ROBOT_Y 20 0.06 ;;
  offset) echo "[drag] grabbed off-centre"
          drag $((FOOD_X-60)) $((FOOD_Y+50)) $ROBOT_X $ROBOT_Y 8 0.05 ;;
  short)  echo "[drag] released early (should NOT feed)"
          drag $FOOD_X $FOOD_Y $FOOD_X $((FOOD_Y-120)) 6 0.05 ;;
  *)      echo "unknown mode: $MODE"; exit 2 ;;
esac

sleep 2
if tail -n "+$((BASE + 1))" "$LOG" | grep -q 'FEDMARK ok'; then
    echo "  -> FED"
else
    echo "  -> not fed"
fi
