#!/bin/bash
# Wini ROS-less platform bringup (WINI_ROSLESS_PLATFORM_PLAN.md Stages 3-4).
# ONE process: display + touch + chin-hold trigger + thin client; it spawns and
# monitors wini_server.py itself on a cold start. Replaces run_boot_platform.sh
# + run_thin.sh + run_client.sh. Detached launch per runbook 2.1.
source /home/roavai/wini_pipeline_test_env.sh
export WINI_FILLERS=0
export WINI_AUDIO_SELECT=/home/roavai/ROS2WS_audio_pipeline/select_usb_audio.sh
LOGS=/home/roavai/wini_test_logs
mkdir -p "$LOGS"
# stop old ROS platform nodes (if any)
pkill -f "wini_displa[y]|wini_head_nod[e]|touch_trigge[r]|chin_reactio[n]" 2>/dev/null
# stop a previous platform GRACEFULLY first: SIGTERM lets it finish the
# in-flight SPI write and park the panel (a SIGKILL mid-frame can make the
# next ST7796S init lose its reset race -> dark panel, no errors anywhere).
pkill -f "\-m wini_platfor[m]" 2>/dev/null
for i in $(seq 1 12); do
  pgrep -f "\-m wini_platfor[m]" > /dev/null || break
  sleep 1
done
# belt: force-kill whatever is left (platform + stray thin processes)
pkill -9 -f "wini_serv[e]r[.]py|wini_clie[n]t[.]client|-m wini_platfor[m]" 2>/dev/null
sleep 1
cd "/home/roavai/ROS2WS_audio_pipeline/cloud CLI"
nohup setsid /home/roavai/ROS2WS_audio_pipeline/.venv/bin/python -u -m wini_platform "$@" \
    > "$LOGS/platform.log" 2>&1 < /dev/null &
disown
sleep 1
echo "wini_platform launch done -> $LOGS/platform.log"
