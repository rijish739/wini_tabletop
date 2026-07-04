#!/bin/bash
# Wini THIN-CLIENT bringup (cloud brain; no wakeword, no local ASR/TTS).
#   USB audio select -> SPI display node -> brain service (wini_server.py)
#   -> thin client (mic/speaker/display platform loop, wini_client)
# Old full ROS pipeline (run_pipeline.sh) is legacy — this replaces it.
# Client runs --on-session-end exit: saying "bye" puts Wini to sleep; the
# chin-hold trigger (wini_touch_trigger.py) wakes it via run_client.sh.
source /home/roavai/wini_pipeline_test_env.sh
# Spoken fillers rejected (artificial) — the thinking FACE masks latency instead
# (client /wini/thinking -> wini_touch_trigger.py animation). Set 1 to re-enable.
export WINI_FILLERS=0
LOGS=/home/roavai/wini_test_logs
mkdir -p "$LOGS"

# stop anything stale (old pipeline nodes AND previous thin processes)
pkill -f "wakeword_node|fastwhisper_node|brain_node|wini_tts_node|wini_pipeline.launch" 2>/dev/null
# SIGKILL for the thin processes: a client blocked in a PortAudio read ignores TERM
pkill -9 -f "wini_server[.]py|wini_client[.]client" 2>/dev/null
sleep 1

bash /home/roavai/ROS2WS_audio_pipeline/select_usb_audio.sh > "$LOGS/audio_select.log" 2>&1
# Belt: pin THIS shell's PULSE_SINK/PULSE_SOURCE too — the onboard card is known
# to re-grab the PulseAudio default later (§4); the client/server inherit these.
eval "$(bash /home/roavai/ROS2WS_audio_pipeline/select_usb_audio.sh --export 2>/dev/null)"

# SPI display node (face + /wini/display/image overlay) — keep if already up
if ! pgrep -f "display_controll.*wini_display|wini_display$" > /dev/null; then
  nohup setsid bash -c "source /home/roavai/wini_pipeline_test_env.sh; exec ros2 run display_controll wini_display" \
      > "$LOGS/display.log" 2>&1 < /dev/null &
  disown
fi

# brain service (Cloud STT -> TutorLoop/Gemini -> Cloud TTS)
nohup setsid bash -c "source /home/roavai/wini_pipeline_test_env.sh; cd '/home/roavai/ROS2WS_audio_pipeline/cloud CLI'; exec /home/roavai/ROS2WS_audio_pipeline/.venv/bin/python -u wini_server.py --port 8123" \
    > "$LOGS/server.log" 2>&1 < /dev/null &
disown

# thin client (waits for /health ready by itself; exits on the "bye" farewell)
nohup setsid bash -c "source /home/roavai/wini_pipeline_test_env.sh; cd '/home/roavai/ROS2WS_audio_pipeline/cloud CLI'; exec /home/roavai/ROS2WS_audio_pipeline/.venv/bin/python -u -m wini_client.client --display ros --on-session-end exit --store '/home/roavai/ROS2WS_audio_pipeline/cloud CLI/rag_store'" \
    > "$LOGS/client.log" 2>&1 < /dev/null &
disown

sleep 1
echo "thin bringup done -> logs: $LOGS/{display,server,client}.log"
