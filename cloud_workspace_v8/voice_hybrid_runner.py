"""Windows hybrid voice runner for Wini.

Only the voice edges use Gemini/Google Cloud:
  mic/audio -> STT -> local TutorLoop/Qwen -> TTS -> speaker

Examples:
  python voice_hybrid_runner.py --text "why do we check discriminant" --fake-voice --no-answer
  python voice_hybrid_runner.py --text "why do we check discriminant" --speak
  python voice_hybrid_runner.py --push-to-talk --speak
  python voice_hybrid_runner.py --auto --loop --speak
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from pacing import PacingController
from voice.audio_io import duration_ms, now_ms, play_wav, record_auto_endpoint, record_push_to_talk
from voice.config import ensure_run_dir, load_voice_config
from voice.fake_voice import FakeStt, FakeTts, SttResult


ROOT = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser(description="Hybrid cloud-voice/local-brain Wini runner")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--text", help="typed transcript; bypass STT")
    mode.add_argument("--audio-file", help="existing WAV file to transcribe")
    mode.add_argument("--push-to-talk", action="store_true", help="press Enter to start/stop recording")
    mode.add_argument("--auto", action="store_true", help="automatic RMS endpointing from microphone")
    mode.add_argument("--live", action="store_true", help="full-duplex Gemini Live transport (barge-in) with local brain")
    ap.add_argument("--loop", action="store_true", help="keep taking voice turns")
    ap.add_argument("--fake-voice", action="store_true", help="use fake STT/TTS; no cloud calls")
    ap.add_argument("--speak", action="store_true", help="synthesize and play/save speech")
    ap.add_argument("--no-play", action="store_true", help="do not play generated speech")
    ap.add_argument("--save-audio", default=None, help="save reply WAV path; defaults to .voice_runs/reply_*.wav")
    ap.add_argument("--no-answer", action="store_true", help="run local cognitive/retrieval path without Qwen answer")
    ap.add_argument("--display", choices=["none", "tk"], default="none",
                    help="T9 visual channel: 'tk' shows the figure crop in an always-on-top "
                         "pane while Wini speaks; 'none' (default) is plain text+voice")
    ap.add_argument("--state", default=str(ROOT / "learner_state.json"))
    ap.add_argument("--rms-threshold", type=float, default=0.018)
    ap.add_argument("--max-seconds", type=float, default=0.0, help="auto-stop --live after N seconds (0 = run until Ctrl+C)")
    ap.add_argument("--silence-ms", type=int, default=850, help="--live: end-of-turn silence before the tutor replies")
    args = ap.parse_args()

    run_dir = ensure_run_dir()
    cfg = load_voice_config()
    print(
        f"voice providers: STT={cfg.stt_provider}/{cfg.stt_model}, "
        f"TTS={cfg.tts_provider}/{cfg.tts_model}, voice={cfg.tts_voice}"
    )

    print("Loading local TutorLoop. This may take a moment the first time.")
    from tutor_loop import GEN_BACKEND, TutorLoop

    # Say which LLM will generate the answers — the transcript labels used to say
    # "qwen" even when Gemini was serving (qwen_chat is only the seam name).
    print(f"generation backend: {GEN_BACKEND}"
          + ("  (Gemini Flash on Vertex — no local Qwen server needed)"
             if GEN_BACKEND == "gemini" else "  (local llama.cpp :8080 — server must be running)"))

    # For live voice the cohesion judge (an extra big-prompt Qwen call per turn)
    # is disabled to cut generation latency; deep-state grading still runs.
    use_judge = (not args.no_answer) and not args.live
    loop = TutorLoop(state_path=Path(args.state), want_answer=not args.no_answer, use_judge=use_judge)
    # Pre-warm the resolver and the first MiniLM forward pass so the first
    # real turn does not pay ~7s of resolver load + first-call overhead.
    _t0 = now_ms()
    loop.analyze_only("warmup")
    print(f"analyzer warm: {now_ms() - _t0} ms")
    if args.live and not args.no_answer:
        # Warm the generation path so the FIRST real turn is not a cold-start
        # cliff (llama.cpp first prompt eval after idle ~11s; Gemini client
        # construction ~4-9s per the CLAUDE.md gotcha).
        from tutor_loop import qwen_chat
        try:
            _t0 = now_ms()
            qwen_chat("Reply with: ok", max_tokens=4)
            print(f"gen warm ({GEN_BACKEND}): {now_ms() - _t0} ms")
        except Exception as exc:  # noqa: BLE001
            print(f"gen warm ({GEN_BACKEND}) skipped: {exc}")
    if args.live:
        from voice.live_session import LiveTutorSession

        session = LiveTutorSession(cfg, loop, run_dir, silence_ms=args.silence_ms,
                                   rms_threshold=args.rms_threshold)
        try:
            session.run(max_seconds=args.max_seconds)
        except KeyboardInterrupt:
            print("\nStopped.")
        return

    # T9 display channel (opt-in). NullDisplaySink for --display none keeps plain
    # text+voice unchanged and imports no GUI deps.
    from voice.display import make_display_sink

    display = make_display_sink(args.display)

    pacing = PacingController()
    stt = FakeStt(args.text or "") if args.fake_voice else None
    tts = FakeTts() if args.fake_voice else None
    if not args.fake_voice:
        from voice.gemini_stt import GeminiStt
        from voice.gemini_tts import GeminiTts

        stt = GeminiStt(cfg)
        tts = GeminiTts(cfg)

    turn_no = 0
    while True:
        turn_no += 1
        try:
            transcript, stt_info, audio_in = get_transcript(args, stt, run_dir, turn_no, cfg.input_rate)
        except Exception as exc:  # noqa: BLE001
            print(f"STT/recording failed: {exc}")
            if not args.loop:
                break
            continue

        if not transcript:
            print("No transcript; skipping turn.")
            if not args.loop:
                break
            continue

        print(f"\nstudent> {transcript}")
        lat: dict[str, int] = {"stt_ms": int(getattr(stt_info, "latency_ms", 0))}

        t0 = now_ms()
        decision = pacing.before_turn(transcript, loop, stt_uncertain=bool(getattr(stt_info, "uncertain", False)))
        lat["triage_ms"] = now_ms() - t0

        result: dict[str, Any] | None = None
        answer = decision.direct_answer
        if decision.direct_answer is None:
            t0 = now_ms()
            try:
                result = loop.turn(
                    transcript,
                    answer_budget=decision.answer_budget.as_dict(),
                    precomputed_analysis=decision.analysis,
                )
                answer = result.get("answer")
            except Exception as exc:  # noqa: BLE001
                print(f"Local tutor turn failed: {exc}")
                answer = "I need a moment. Let us try that step again."
                result = {"error": str(exc), "answer": answer, "action": "ERROR"}
            lat["local_tutor_ms"] = now_ms() - t0
        else:
            lat["local_tutor_ms"] = 0

        pacing.after_turn(transcript, answer, result, loop, decision, latency=lat)
        print_turn(result, decision, answer)

        display_items = (result or {}).get("display") or []
        if display_items:
            print(f"display> {display_items[0]['image_path']}")

        if args.speak and answer and not args.no_answer:
            out = reply_path(args, run_dir, turn_no)
            t0 = now_ms()
            try:
                wav_path = tts.synthesize_to_wav(answer, out, pace=decision.tts_pace)
                lat["tts_ms"] = int(getattr(tts, "last_latency_ms", now_ms() - t0))
                lat["audio_duration_ms"] = duration_ms(wav_path)
                print(f"reply audio> {wav_path}")
                display.show(display_items)        # T9: crop up as speech begins
                if not args.no_play:
                    play_wav(wav_path)
                display.clear()                    # T9: crop down on playback end
            except Exception as exc:  # noqa: BLE001
                print(f"TTS/playback failed: {exc}")
        else:
            display.show(display_items)            # no speech this turn — surface it anyway (no-op for NullDisplaySink)

        log_turn(run_dir, transcript, answer, result, decision, lat, audio_in)
        if not args.loop:
            break

    display.close()


def get_transcript(args, stt, run_dir: Path, turn_no: int, rate: int):
    if args.text:
        return args.text.strip(), SttResult(args.text.strip(), uncertain=False), None
    if args.audio_file:
        audio = Path(args.audio_file)
    elif args.push_to_talk:
        audio = record_push_to_talk(run_dir / f"student_{turn_no:03d}.wav", rate=rate)
    elif args.auto:
        audio = record_auto_endpoint(
            run_dir / f"student_{turn_no:03d}.wav",
            rate=rate,
            threshold=args.rms_threshold,
        )
    else:
        text = input("student text> ").strip()
        return text, SttResult(text, uncertain=False), None
    result = stt.transcribe_wav(audio)
    return result.transcript, result, audio


def reply_path(args, run_dir: Path, turn_no: int) -> Path:
    if args.save_audio:
        path = Path(args.save_audio)
        if args.loop and turn_no > 1:
            return path.with_name(f"{path.stem}_{turn_no:03d}{path.suffix}")
        return path
    return run_dir / f"reply_{turn_no:03d}.wav"


def print_turn(result: dict[str, Any] | None, decision, answer: str | None) -> None:
    triage = decision.triage.as_dict()
    print(f"triage> {triage['primary_intent']} | route={triage['route']} | policy={triage['state_policy']}")
    if result:
        print(f"action> {result.get('action')} | concept={(result.get('concept') or {}).get('concept_id')}")
        if result.get("writeback"):
            print(f"writeback> {result['writeback']}")
    print(f"wini> {answer or '[no answer generated]'}")


def log_turn(run_dir: Path, transcript: str, answer: str | None, result, decision, latency, audio_in) -> None:
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "transcript": transcript,
        "answer": answer,
        "action": (result or {}).get("action"),
        "triage": decision.triage.as_dict(),
        "answer_budget": decision.answer_budget.as_dict(),
        "latency_ms": latency,
        "audio_in": str(audio_in) if audio_in else None,
    }
    with (run_dir / "voice_turn_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
