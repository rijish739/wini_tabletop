#!/bin/bash
# Wini PLATFORM bringup (runs at boot, no external command needed):
#   SPI display node + head node (touch/ears/IMU) + chin-hold trigger node.
# The cloud pipeline itself starts only when the chin is held 3 s
# (wini_touch_trigger.py -> run_thin.sh). Detached launches per runbook 2.1.
sleep 8   # let boot settle (USB serial + network up)
LOGS=/home/roavai/wini_test_logs
mkdir -p "$LOGS"

pkill -9 -f "wini_head_nod[e]|wini_touch_trigge[r]|touch_logge[r]" 2>/dev/null
sleep 1

if ! pgrep -f "display_controll.*wini_display|wini_display$" > /dev/null; then
  nohup setsid bash -c "source /home/roavai/wini_pipeline_test_env.sh; exec ros2 run display_controll wini_display" \
      > "$LOGS/display.log" 2>&1 < /dev/null &
  disown
fi

nohup setsid bash -c "source /home/roavai/wini_pipeline_test_env.sh; exec ros2 run wini_hw_bridge wini_head_node" \
    > "$LOGS/head_node.log" 2>&1 < /dev/null &
disown

nohup setsid bash -c "source /home/roavai/wini_pipeline_test_env.sh; exec python3 -u /home/roavai/wini_touch_trigger.py" \
    > "$LOGS/touch_trigger.log" 2>&1 < /dev/null &
disown

sleep 1
echo "platform bringup done -> logs: $LOGS/{display,head_node,touch_trigger}.log"
