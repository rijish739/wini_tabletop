"""Turn-based voice loop: Cloud STT (English) -> local brain -> Cloud TTS.

Replaces the earlier Gemini-Live attempt, which was unreliable as both a verbatim
TTS (it paraphrased the local answer) and an English STT (it produced Indic
script). Each edge now uses a purpose-built, controllable service:

  mic --(RMS endpoint)--> Cloud STT (forced en-US) --> transcript
       -> MiniLM cognitive analysis -> state-based filler (spoken immediately)
       -> local brain (TutorLoop + Qwen, cohesion judge off for speed)
       -> Cloud TTS, sentence-by-sentence (first audio fast) --> speaker

Half-duplex by design: the mic only records between Wini's turns, so her own
audio can never echo back. Real barge-in is a later enhancement.
"""

from __future__ import annotations

import json
import queue
import re
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

from .audio_io import now_ms, read_wav, record_auto_endpoint
from .cloud_stt import CloudStt
from .cloud_tts import CloudTts
from .config import VoiceConfig
from .fillers import FillerBank, pick_bucket
from .live_tools import TutorTurnHandler

IN_RATE = 16000
OUT_RATE = 24000


class LiveTutorSession:
    def __init__(self, cfg: VoiceConfig, loop_brain, run_dir: Path,
                 silence_ms: int = 700, rms_threshold: float = 0.018) -> None:
        self.cfg = cfg
        self.handler = TutorTurnHandler(loop_brain)
        self.run_dir = run_dir
        self.rms_threshold = rms_threshold
        self.silence_ms = silence_ms
        self.tts = CloudTts(voice_name=cfg.cloud_tts_voice, rate=OUT_RATE)
        self.stt = CloudStt()
        self.fillers = FillerBank(self.tts)
        self._log = (run_dir / "live_turn_log.jsonl").open("a", encoding="utf-8")

    # ---- audio helpers -----------------------------------------------------
    def _play(self, pcm: bytes) -> None:
        if not pcm:
            return
        import sounddevice as sd
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        sd.play(audio, samplerate=OUT_RATE, blocking=True)

    def _speak_chunked(self, text: str) -> int:
        """Speak `text` sentence by sentence, synthesising the next sentence while
        the current one plays (first audio in ~one short-sentence synth)."""
        sentences = [s.strip() for s in re.findall(r"[^.!?]*[.!?]", text.strip()) if s.strip()] or [text.strip()]
        q: queue.Queue = queue.Queue()

        def producer() -> None:
            for s in sentences:
                q.put(self.tts.synth(s))
            q.put(None)

        threading.Thread(target=producer, daemon=True).start()
        total = 0
        while True:
            pcm = q.get()
            if pcm is None:
                break
            total += len(pcm)
            self._play(pcm)
        return int(1000 * (total / 2) / OUT_RATE)

    def _log_row(self, row: dict[str, Any]) -> None:
        row["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._log.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._log.flush()

    # ---- main loop ---------------------------------------------------------
    def run(self, max_seconds: float = 0.0) -> None:
        t0 = now_ms()
        print("Pre-synthesising fillers...")
        self.fillers.presynth()
        print(f"Fillers ready ({now_ms() - t0} ms). Voice tutor is listening. Ctrl+C to stop.")

        start = time.time()
        turn = 0
        while True:
            if max_seconds > 0 and time.time() - start > max_seconds:
                print("[run] max-seconds reached")
                break
            turn += 1
            try:
                wav = record_auto_endpoint(self.run_dir / f"student_{turn:03d}.wav",
                                           rate=IN_RATE, threshold=self.rms_threshold,
                                           silence_ms=self.silence_ms)
            except Exception as exc:  # noqa: BLE001 — no speech / device issue
                print(f"[mic] {exc}")
                continue

            t_stt = now_ms()
            pcm, rate = read_wav(wav)
            transcript = self.stt.recognize_pcm(pcm, rate)
            stt_ms = now_ms() - t_stt
            if not transcript:
                print("(could not transcribe; listening again)")
                continue
            print(f"\nstudent> {transcript}  [stt={stt_ms}ms]")

            # fast cognitive analysis -> state-based filler spoken while we generate
            decision = self.handler.analyze(transcript)
            phrase, filler_pcm = self.fillers.pick(decision)
            print(f"filler> {phrase}  (state={pick_bucket(decision)})")
            ft = threading.Thread(target=self._play, args=(filler_pcm,))
            ft.start()

            out = self.handler.respond(transcript, decision)
            ft.join()

            gen_tag = out.get("gen_backend") or "gen"
            print(f"action> {out['action']} | {gen_tag}={out['latency_ms'].get('qwen_ms')}ms")
            print(f"wini> {out['say']}")
            t_spk = now_ms()
            audio_ms = self._speak_chunked(out["say"]) if out["say"] else 0
            self._log_row({"event": "turn", "transcript": transcript, "filler": phrase,
                           "filler_state": pick_bucket(decision), "stt_ms": stt_ms,
                           "speak_wall_ms": now_ms() - t_spk, "audio_ms": audio_ms, **out})
            if out.get("session_ended"):
                # SESSION_CONTROL hard stop: the farewell was already spoken above;
                # honoring the goodbye means actually stopping the mic loop.
                print("(student ended the session — stopping)")
                break

        self._log.close()
        print("Voice session closed.")
