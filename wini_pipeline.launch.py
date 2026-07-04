#!/usr/bin/env python3
"""Wini — single full-system bringup (audio pipeline + SPI display + USB audio select).

One launch file starts EVERYTHING:

    [select_usb_audio.sh]  -> pins PulseAudio default sink+source to the USB PnP card
    wini_display_node      -> SPI face/figure screen   (/wini/display/image, ros2_ws pkg)
    wakeword_node          -> openWakeWord "weenee"     (/wake_word)
    fastwhisper_node       -> small.en CUDA ASR         (/speech_text, /session_active)
    wini_brain_node        -> TutorLoop + in-proc Qwen  (/llm_out, /robot_speaking, display)
    wini_tts_node          -> Kokoro af_heart (teaching-tuned)  -> USB speaker

State machine: "weenee" -> brain says "Hi!" + fastwhisper opens a session
(/session_active=True, wakeword self-gates). FastWhisper streams /speech_text per
utterance until ~5 s silence, then /session_active=False; brain says "Bye!" and the
wakeword re-arms. /robot_speaking is the half-duplex mic gate.

PREREQUISITE: both workspaces must be sourced before `ros2 launch` so display_controll
(ros2_ws) and the audio packages (ROS2WS_audio_pipeline) are both visible. Bring the
whole rig up with `bash ~/run_pipeline.sh`, which sources them and runs this file.

VRAM note: Qwen + Kokoro + Whisper on the 8 GB unified GPU is tight (~6-7 GB) — if OOM,
drop Whisper to base.en or run Kokoro on CPU.
"""

import os
from launch import LaunchDescription
from launch.actions import SetEnvironmentVariable, ExecuteProcess, TimerAction
from launch_ros.actions import Node

SELECT_USB = os.path.expanduser('~/ROS2WS_audio_pipeline/select_usb_audio.sh')


def generate_launch_description():
    # SPI display has no mic dependency — start it immediately so the face shows at once.
    display = Node(package='display_controll', executable='wini_display',
                   name='wini_display_node', output='screen')

    # Audio nodes start after the USB-audio selection has settled.
    audio_nodes = [
        Node(package='wakeword_pkg', executable='wakeword_node',
             name='wakeword_node', output='screen'),

        Node(package='fastwhisper_pkg', executable='fastwhisper_node',
             name='fastwhisper_node', output='screen',
             parameters=[{'model_size': 'small.en',
                          'device': 'cuda',
                          'compute_type': 'int8_float16'}]),

        Node(package='wini_brain_pkg', executable='brain_node',
             name='wini_brain_node', output='screen'),

        # Teaching-tuned TTS: af_heart, base speed 0.85, equations slower with pauses
        # (math_speed / math_pause_ms are node defaults).
        Node(package='wini_tts', executable='wini_tts_node',
             name='wini_tts_node', output='screen',
             parameters=[{'output_device': 'pulse',
                          'voice': 'af_heart',
                          'provider': 'CUDAExecutionProvider'}]),
    ]

    return LaunchDescription([
        # MiniLM (study-core) reads its model from the HF cache; keep it on CPU.
        SetEnvironmentVariable('HF_HOME', os.path.expanduser('~/.cache/huggingface')),
        SetEnvironmentVariable('WINI_MINILM_DEVICE', 'cpu'),
        # Kokoro: force the CUDA EP (skip TRT EP, which can't parse Kokoro's STFT op).
        SetEnvironmentVariable('ONNX_PROVIDER', 'CUDAExecutionProvider'),

        # Pin the USB PnP sound card as default mic + speaker BEFORE the audio nodes open
        # their streams (otherwise the onboard Tegra card grabs the Pulse default).
        ExecuteProcess(cmd=['bash', SELECT_USB], output='screen'),

        display,

        # Let the USB-audio selection settle, then bring up the audio nodes.
        TimerAction(period=2.5, actions=audio_nodes),
    ])
