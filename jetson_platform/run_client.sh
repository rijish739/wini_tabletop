#!/bin/bash
# Relaunch JUST the thin client (wake from sleep — the brain server stays warm).
# Used by wini_touch_trigger.py on a chin hold when wini_server.py is already up.
source /home/roavai/wini_pipeline_test_env.sh
LOGS=/home/roavai/wini_test_logs
mkdir -p "$LOGS"

pkill -9 -f "wini_client[.]client" 2>/dev/null
sleep 0.5

# Belt: pin PULSE_SINK/PULSE_SOURCE (the onboard card re-grabs the default, §4)
eval "$(bash /home/roavai/ROS2WS_audio_pipeline/select_usb_audio.sh --export 2>/dev/null)"

nohup setsid bash -c "source /home/roavai/wini_pipeline_test_env.sh; cd '/home/roavai/ROS2WS_audio_pipeline/cloud CLI'; exec /home/roavai/ROS2WS_audio_pipeline/.venv/bin/python -u -m wini_client.client --display ros --on-session-end exit --store '/home/roavai/ROS2WS_audio_pipeline/cloud CLI/rag_store'" \
    > "$LOGS/client.log" 2>&1 < /dev/null &
disown
sleep 1
echo "client relaunched -> $LOGS/client.log"
