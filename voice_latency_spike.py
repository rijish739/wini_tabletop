"""Latency spike: STT (Cloud vs Gemini Live, side by side) -> Gemini 2.5 Flash
reply -> Cloud TTS.

This is a throwaway experiment, NOT wired into tutor_loop.py or the
PERCEPTION_BACKEND flag -- it exists to get real numbers for each hop before
deciding how to build PART11_GEMINI_PERCEPTION_LAYER.md for real. See
voice/gemini_live_stt.py for why the Live STT leg is a probe, not a proven
adapter (Cloud STT was already the production choice as of 2026-06-18).

Clients are built ONCE and reused across turns so --loop shows the real warm
steady-state latency (the first turn still pays cold-start client construction;
see the CLAUDE.md gotcha).

Examples:
  python voice_latency_spike.py --push-to-talk --speak
  python voice_latency_spike.py --push-to-talk --speak --loop
  python voice_latency_spike.py --push-to-talk --speak --loop --no-live   # skip the slow Live leg
  python voice_latency_spike.py --audio ".voice_runs/student_005.wav"
  python voice_latency_spike.py --prompt "why is the discriminant negative" --speak
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path

from voice.audio_io import now_ms, play_wav, read_wav, record_push_to_talk, save_pcm_as_wav
from voice.cloud_stt import CloudStt
from voice.cloud_tts import CloudTts
from voice.config import ensure_run_dir, load_voice_config
from voice.gemini_live_stt import GeminiLiveStt

import llm_vertex

ROOT = Path(__file__).resolve().parent
SYSTEM_PROMPT = (
    "You are Wini, a warm, encouraging maths tutor for a school student. "
    "Reply in 1-2 short sentences."
)


@dataclass
class Clients:
    cloud_stt: CloudStt
    live_stt: GeminiLiveStt | None
    tts: CloudTts
    cfg: object


def build_clients(cfg, use_live: bool) -> Clients:
    return Clients(
        cloud_stt=CloudStt(),
        live_stt=GeminiLiveStt(cfg) if use_live else None,
        tts=CloudTts(voice_name=cfg.cloud_tts_voice, rate=cfg.output_rate),
        cfg=cfg,
    )


def run_turn(args, c: Clients, run_dir: Path, device, turn_no: int) -> bool:
    """One STT->Flash->TTS turn. Returns False when there is nothing to do
    (empty transcript / no speech) so the caller can decide whether to continue."""
    cfg = c.cfg
    audio_path: Path | None = None
    stt_row = {"cloud_ms": None, "cloud_text": None, "live_ms": None, "live_text": None, "live_error": None}

    if args.prompt:
        transcript = args.prompt.strip()
    else:
        if args.push_to_talk:
            audio_path = record_push_to_talk(run_dir / f"spike_{int(time.time())}.wav",
                                             rate=cfg.input_rate, device=device)
        elif args.audio:
            audio_path = Path(args.audio)
        else:
            raise SystemExit("pass --audio <wav>, --push-to-talk, or --prompt <text>")

        pcm, rate = read_wav(audio_path)

        print("Running Cloud STT...")
        t0 = now_ms()
        cloud_text = c.cloud_stt.recognize_pcm(pcm, rate)
        cloud_ms = now_ms() - t0
        print(f"  cloud> {cloud_text!r}  [{cloud_ms} ms]")

        if c.live_stt is not None:
            print("Running Gemini Live STT...")
            live_result = c.live_stt.transcribe_pcm(pcm, rate)
            print(f"  live>  {live_result.transcript!r}  [{live_result.latency_ms} ms]"
                  + (f"  ERROR: {live_result.error}" if live_result.error else ""))
            stt_row.update(live_ms=live_result.latency_ms, live_text=live_result.transcript,
                           live_error=live_result.error)
            live_text = live_result.transcript
        else:
            live_text = ""

        stt_row.update(cloud_ms=cloud_ms, cloud_text=cloud_text)
        transcript = cloud_text or live_text
        if not transcript:
            print("  (no transcript)\n")
            return False

    print(f"\nTranscript fed to Flash: {transcript!r}")
    t0 = now_ms()
    flash = llm_vertex.generate_reply(transcript, system=SYSTEM_PROMPT)
    flash_ms = now_ms() - t0
    print(f"flash> {flash.text!r}  [{flash_ms} ms]")

    print("Running Cloud TTS...")
    t0 = now_ms()
    pcm_out = c.tts.synth(flash.text)
    tts_ms = now_ms() - t0
    out_path = run_dir / f"spike_reply_{int(time.time())}.wav"
    save_pcm_as_wav(out_path, pcm_out, rate=cfg.output_rate)
    print(f"  saved> {out_path}  [{tts_ms} ms]")

    stt_used_ms = stt_row["cloud_ms"] or 0
    total_ms = stt_used_ms + flash_ms + tts_ms
    summary = {**stt_row, "flash_ms": flash_ms, "tts_ms": tts_ms, "total_ms_cloud_stt_path": total_ms}
    print(f"\n--- turn {turn_no} latency (ms) ---")
    print(json.dumps(summary, indent=2))
    print(f">>> end-to-end (Cloud STT + Flash + TTS): {total_ms} ms"
          + ("  [turn 1 includes cold-start client setup]" if turn_no == 1 else "  [warm]"))

    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "turn": turn_no,
        "audio_in": str(audio_path) if audio_path else None,
        "transcript": transcript,
        "reply": flash.text,
        **summary,
    }
    with (run_dir / "latency_spike_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    if args.speak:
        play_wav(out_path)
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="STT/Flash/TTS latency spike")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--audio", help="existing WAV file (mono 16-bit PCM)")
    src.add_argument("--push-to-talk", action="store_true", help="record a fresh clip")
    src.add_argument("--prompt", help="skip STT entirely; use this text")
    ap.add_argument("--speak", action="store_true", help="play the synthesized reply")
    ap.add_argument("--loop", action="store_true", help="keep taking turns (clients stay warm)")
    ap.add_argument("--no-live", action="store_true", help="skip the slow Gemini Live STT leg")
    ap.add_argument("--input-device", default=None,
                    help="mic device index or name substring (default: system default input)")
    ap.add_argument("--list-devices", action="store_true", help="list audio input devices and exit")
    args = ap.parse_args()

    if args.list_devices:
        import sounddevice as sd
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                default = "  <-- default" if i == sd.default.device[0] else ""
                print(f"[{i}] {d['name']}{default}")
        return

    device: int | str | None = args.input_device
    if isinstance(device, str) and device.isdigit():
        device = int(device)

    cfg = load_voice_config()
    run_dir = ensure_run_dir()
    live_label = "off" if args.no_live else cfg.live_model
    print(f"STT: cloud (used) | live-probe={live_label} | Flash={llm_vertex.DEFAULT_MODEL} "
          f"({llm_vertex.DEFAULT_REGION}) | TTS={cfg.cloud_tts_voice}")
    print("Building clients (first turn pays cold-start setup)...")
    clients = build_clients(cfg, use_live=not args.no_live)

    turn_no = 0
    while True:
        turn_no += 1
        try:
            did_work = run_turn(args, clients, run_dir, device, turn_no)
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        if not args.loop or args.prompt or args.audio:
            break
        if not did_work:
            turn_no -= 1  # do not count empty turns


if __name__ == "__main__":
    main()
