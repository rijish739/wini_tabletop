"""Cloud voice tutor: the latency spike, but wired to the REAL pedagogical brain.

Pipeline (all cloud edges verified in voice_latency_spike.py; brain is local
MiniLM perception + retrieval, generation on Gemini when GEN_BACKEND=gemini):

    mic --(push-to-talk)--> Cloud STT (forced en-US, maths hints)
        -> PacingController + TutorLoop  (cognitive analysis, state, evidence
           retrieval, manifest-grounded prompt)  [voice.live_tools.TutorTurnHandler]
        -> generation: Gemini 2.5 Flash (GEN_BACKEND=gemini) or Qwen :8080 (=qwen)
        -> sanitize for speech -> Cloud TTS -> speaker

This differs from voice_latency_spike.py only in the middle: that used a throwaway
single Flash call with a fixed system prompt; this runs the actual tutor. Clients
are built once (turn 1 pays cold-start; turns 2+ are warm). Unlike
voice_hybrid_runner.py's --live path this is push-to-talk with explicit per-hop
timing, for controlled testing; --live remains the hands-free, sentence-streamed
runner.

Run with NO local Qwen server needed when GEN_BACKEND=gemini:
    GEN_BACKEND=gemini python voice_cloud_tutor.py --loop
    (PowerShell:  $env:GEN_BACKEND="gemini"; python voice_cloud_tutor.py --loop)
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np

from voice.audio_io import now_ms, read_wav, record_push_to_talk, write_wav
from voice.cloud_stt import CloudStt
from voice.cloud_tts import CloudTts
from voice.config import ensure_run_dir, load_voice_config

ROOT = Path(__file__).resolve().parent


def play_pcm(pcm: bytes, rate: int) -> None:
    if not pcm:
        return
    import sounddevice as sd
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    sd.play(audio, samplerate=rate, blocking=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Cloud voice tutor (Cloud STT -> brain -> Cloud TTS)")
    ap.add_argument("--loop", action="store_true", help="keep taking push-to-talk turns")
    ap.add_argument("--once", default=None, help="run one turn from this text (skip mic/STT)")
    ap.add_argument("--no-speak", action="store_true", help="do not play the reply (still synthesizes)")
    ap.add_argument("--input-device", default=None,
                    help="mic device index or name substring (default: system default input)")
    ap.add_argument("--state", default=str(ROOT / "learner_state.json"))
    args = ap.parse_args()

    device: int | str | None = args.input_device
    if isinstance(device, str) and device.isdigit():
        device = int(device)

    cfg = load_voice_config()
    run_dir = ensure_run_dir()
    backend = os.getenv("GEN_BACKEND", "qwen").strip().lower()
    print(f"generation backend: {backend}"
          + ("  (Gemini Flash — no local Qwen server needed)" if backend == "gemini"
             else "  (local Qwen :8080 — server must be running)"))
    print(f"STT=CloudStt(en-US) | TTS={cfg.cloud_tts_voice} | brain=TutorLoop (MiniLM perception)")

    print("Loading brain (MiniLM analyzer, chunk index, HOPE)...")
    from tutor_loop import TutorLoop, qwen_chat
    from voice.live_tools import TutorTurnHandler

    # Judge OFF for voice latency (matches the --live path); deep-state grading still runs.
    loop = TutorLoop(state_path=Path(args.state), want_answer=True, use_judge=False)
    handler = TutorTurnHandler(loop)

    # Warm the slow paths so turn 1 is not a cold-start cliff: MiniLM first forward
    # pass, the generation client (Gemini ADC/channel or Qwen server), Cloud STT and
    # Cloud TTS clients.
    t0 = now_ms()
    loop.analyze_only("warmup")
    print(f"  analyzer warm: {now_ms() - t0} ms")
    stt = CloudStt()
    tts = CloudTts(voice_name=cfg.cloud_tts_voice, rate=cfg.output_rate)
    try:
        t0 = now_ms()
        qwen_chat("Reply with: ok", max_tokens=4)
        print(f"  generation warm: {now_ms() - t0} ms")
    except Exception as exc:  # noqa: BLE001
        print(f"  generation warm skipped: {exc}")
    try:
        tts.synth("ok")  # warms the TTS client channel
    except Exception:  # noqa: BLE001
        pass

    log_path = run_dir / "cloud_tutor_log.jsonl"
    turn_no = 0
    while True:
        turn_no += 1
        lat: dict[str, int] = {}

        # ---- 1. get transcript ------------------------------------------------
        if args.once:
            transcript = args.once.strip()
        else:
            try:
                audio = record_push_to_talk(run_dir / f"ct_student_{turn_no:03d}.wav",
                                            rate=cfg.input_rate, device=device)
            except KeyboardInterrupt:
                print("\nStopped.")
                break
            except Exception as exc:  # noqa: BLE001
                print(f"[mic] {exc}")
                if not args.loop:
                    break
                turn_no -= 1
                continue
            pcm, rate = read_wav(audio)
            t0 = now_ms()
            transcript = stt.recognize_pcm(pcm, rate)
            lat["stt_ms"] = now_ms() - t0
            print(f"\nstudent> {transcript!r}  [stt={lat['stt_ms']}ms]")
        if not transcript:
            print("  (no speech; listening again)" if args.loop else "  (no speech)")
            if not args.loop:
                break
            turn_no -= 1
            continue

        # ---- 2. brain (analysis + state + retrieval + generation) -------------
        t0 = now_ms()
        out = handler.handle(transcript)
        lat["brain_ms"] = now_ms() - t0
        lat["gen_ms"] = int(out["latency_ms"].get("qwen_ms", 0))
        say = out["say"]
        print(f"action> {out['action']} | gen={lat['gen_ms']}ms (brain total {lat['brain_ms']}ms)")
        print(f"wini> {say}")

        # ---- 3. TTS + playback ------------------------------------------------
        if say:
            t0 = now_ms()
            pcm_out = tts.synth(say)
            lat["tts_ms"] = now_ms() - t0
            out_path = run_dir / f"ct_reply_{turn_no:03d}.wav"
            write_wav(out_path, pcm_out, rate=cfg.output_rate)
            total = lat.get("stt_ms", 0) + lat["brain_ms"] + lat["tts_ms"]
            tag = "  [turn 1: includes cold-start warmups already paid above]" if turn_no == 1 else "  [warm]"
            print(f"tts> {lat['tts_ms']}ms | end-to-end (STT+brain+TTS) {total}ms{tag}")
            if not args.no_speak:
                play_pcm(pcm_out, cfg.output_rate)

        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "turn": turn_no,
                "transcript": transcript, "answer": say, "action": out["action"],
                "backend": backend, "latency_ms": lat,
            }, ensure_ascii=False) + "\n")

        if out.get("session_ended"):
            print("(student ended the session — stopping)")
            break
        if args.once or not args.loop:
            break


if __name__ == "__main__":
    main()
