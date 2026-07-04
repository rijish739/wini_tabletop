"""Wini brain service — the WHOLE pipeline behind one HTTP endpoint.

This is the cloud side of the thin-client split (CLAUDE.md deployment mandate:
device = mic + speaker + display + touch, no brain on device). Everything a turn
needs happens HERE, server-side:

    audio in ──► Cloud STT ──► TutorLoop (Gemini perception + generation,
                 (en-US)       retrieval, state, T9 display pick)
                                    │
              JSON out ◄── Cloud TTS (en-IN Chirp3-HD) ◄── sanitize_for_speech
              {transcript, answer, display[metadata], audio_b64, session_ended}

The client never talks to Google APIs and never sees model SDKs — its whole
contract is this server's two POST routes (see wini_client/README.md). Today the
server runs on the Jetson beside the client; on Cloud Run the SAME file runs
unchanged (PORT env, learner state moves to Firestore later).

Endpoints
    GET  /health              -> {"ok": true, "ready": true|false, ...}
    POST /turn                <- {"text": "...", "speak": false}
                              -> turn JSON (display metadata always included)
    POST /voice_turn          <- raw LINEAR16 mono int16 PCM body,
                                 header X-Sample-Rate (default 16000)
                              -> NDJSON stream, one JSON object per line:
                                 line 1 (optional, flushed early): {"part":
                                   "filler", "filler", "bank", "transcript",
                                   "audio_b64", "audio_rate"} — a short
                                   cognitive-state phrase (voice/filler_banks.py)
                                   picked from the perception analysis and
                                   synthesised BEFORE generation, so the client
                                   can speak it while the answer is produced.
                                 last line: turn JSON + "audio_b64"/"audio_rate"
                                 (24 kHz PCM). Non-stream readers that parse only
                                 the final line still get the full turn.

Display contract (ESP32 SD-card design, JETSON_PIPELINE_RUNBOOK.md §14.3): the
response carries METADATA ONLY — `display[].image_path` is the stable image ID the
device resolves against its own copy of rag_store/figure_crops/.

Run:  python wini_server.py [--port 8123]
Env:  GEN_BACKEND=gemini (the point), WINI_SERVER_PORT, plus the usual Vertex vars.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STT_TIMEOUT_S = 20.0
TTS_TIMEOUT_S = 30.0

_pool = ThreadPoolExecutor(max_workers=4)


def _bounded(fn, timeout_s, *args, **kwargs):
    """Hard wall-clock timeout around every cloud call (CLAUDE.md gotcha: SDK
    deadlines have stalled for hours — the caller-side future is what bounds it)."""
    return _pool.submit(fn, *args, **kwargs).result(timeout=timeout_s)


class Brain:
    """Owns the TutorLoop + STT/TTS clients; one turn at a time (half-duplex)."""

    def __init__(self):
        self.ready = False
        self.error = None
        self._lock = threading.Lock()
        self.tutor = None
        self.stt = None
        self.tts = None
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            import tutor_loop
            from voice.cloud_stt import CloudStt
            from voice.cloud_tts import CloudTts

            self.gen_backend = getattr(tutor_loop, "GEN_BACKEND", "qwen")
            self.tutor = tutor_loop.TutorLoop()
            self.stt = CloudStt()
            self.tts = CloudTts()
            # Pacing governor — same before_turn/turn/after_turn sequence the
            # retired ROS brain node ran. Best-effort: any failure falls back
            # to a plain, unbudgeted turn.
            try:
                from pacing.pacing_controller import PacingController
                self.pacing = PacingController()
            except Exception as e:  # noqa: BLE001
                print(f"[server] pacing unavailable: {e}")
                self.pacing = None
            # SPOKEN fillers are opt-in (WINI_FILLERS=1) — rejected on the Jetson
            # rig as artificial; the client masks generation latency with a
            # "thinking" face instead (/wini/thinking, see wini_touch_trigger.py).
            # The early NDJSON transcript line is streamed either way.
            self.fillers = None
            if os.getenv("WINI_FILLERS", "0").lower() not in ("0", "false", ""):
                try:
                    from voice.filler_banks import FillerComposer
                    self.fillers = FillerComposer()
                except Exception as e:  # noqa: BLE001
                    print(f"[server] fillers unavailable: {e}")
            self._filler_pcm_cache: dict[str, bytes] = {}
            # Warm every cloud client now (client construction is the 4-9 s
            # cold-start cost, paid once). Best-effort: a failed warmup must not
            # block readiness — turns degrade per call, never at startup.
            try:
                if self.gen_backend == "gemini":
                    import llm_vertex
                    llm_vertex.generate_reply("Say OK.", temperature=0.0, max_output_tokens=8)
                    self.tutor.analyze_only("hello wini")
                _bounded(self.tts.synth, TTS_TIMEOUT_S, "Hi")
            except Exception as e:  # noqa: BLE001
                print(f"[server] warmup failed (turns will retry live): {e}")
            self.ready = True
            print(f"[server] brain ready (gen_backend={self.gen_backend})")
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            print(f"[server] FAILED to load brain: {e}")

    # ------------------------------------------------------------------
    def text_turn(self, text: str, speak: bool, answer_budget: dict | None = None,
                  precomputed_analysis: dict | None = None) -> dict:
        from voice.sanitize import sanitize_for_speech

        with self._lock:
            t0 = time.perf_counter()
            result = self.tutor.turn(text, answer_budget=answer_budget,
                                     precomputed_analysis=precomputed_analysis)
            brain_ms = int((time.perf_counter() - t0) * 1000)
        answer = (result.get("answer") or "").strip()
        out = {
            "transcript": text,
            "answer": answer,
            "display": result.get("display") or [],
            "session_ended": bool(result.get("session_ended")),
            "action": result.get("action"),
            "need": result.get("need"),
            "concept": (result.get("concept") or {}).get("concept_id"),
            "gen_backend": result.get("gen_backend"),
            "latency_ms": {"brain": brain_ms},
        }
        if speak and answer:
            spoken = sanitize_for_speech(answer)
            t1 = time.perf_counter()
            pcm = _bounded(self.tts.synth, TTS_TIMEOUT_S, spoken)
            out["latency_ms"]["tts"] = int((time.perf_counter() - t1) * 1000)
            out["audio_b64"] = base64.b64encode(pcm).decode("ascii")
            out["audio_rate"] = self.tts.rate
        return out

    def voice_turn(self, pcm: bytes, rate: int, emit=None) -> dict:
        """One voice turn. With `emit` (a callable taking one JSON-able dict per
        response line), the filler part is flushed to the client as soon as
        STT + perception are done — BEFORE generation — so it plays while the
        answer is being produced. The final turn dict is always returned (and
        emitted last when streaming)."""
        t0 = time.perf_counter()
        transcript = _bounded(self.stt.recognize_pcm, STT_TIMEOUT_S, pcm, rate)
        stt_ms = int((time.perf_counter() - t0) * 1000)
        if not transcript:
            # nothing recognized — the client just re-listens; don't burn a turn
            out = {"transcript": "", "answer": "", "display": [],
                   "session_ended": False, "latency_ms": {"stt": stt_ms}}
            if emit:
                emit(out)
            return out

        # Pacing before_turn (analysis + answer budget) -> cognitive filler.
        # Best-effort: a failure here must never cost the turn itself.
        budget = precomputed = decision = None
        if self.pacing is not None:
            try:
                decision = self.pacing.before_turn(transcript, self.tutor)
                budget = decision.answer_budget.as_dict()
                precomputed = decision.analysis
            except Exception as e:  # noqa: BLE001
                print(f"[server] pacing before_turn failed; plain turn: {e}")
                decision = None
        if emit:
            # Early line: transcript as soon as STT + perception are done, so
            # the client can react (print / thinking face) before generation.
            # Filler audio rides on it only when WINI_FILLERS=1.
            part = {"part": "filler", "transcript": transcript}
            if self.fillers is not None:
                try:
                    bank, phrase = self.fillers.pick(precomputed)
                    if phrase:
                        fpcm = self._filler_pcm_cache.get(phrase)
                        if fpcm is None:
                            fpcm = _bounded(self.tts.synth, TTS_TIMEOUT_S, phrase)
                            self._filler_pcm_cache[phrase] = fpcm
                        part.update({
                            "filler": phrase, "bank": bank,
                            "audio_b64": base64.b64encode(fpcm).decode("ascii"),
                            "audio_rate": self.tts.rate})
                        print(f"[server] filler [{bank}]: {phrase}")
                except Exception as e:  # noqa: BLE001
                    print(f"[server] filler skipped: {e}")
            emit(part)

        out = self.text_turn(transcript, speak=True, answer_budget=budget,
                             precomputed_analysis=precomputed)
        out["latency_ms"]["stt"] = stt_ms
        if decision is not None:
            try:
                self.pacing.after_turn(transcript, out.get("answer"), out,
                                       self.tutor, decision)
            except Exception as e:  # noqa: BLE001
                print(f"[server] pacing after_turn failed: {e}")
        if emit:
            emit(out)
        return out


BRAIN: Brain | None = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter default log line
        print(f"[http] {self.address_string()} {fmt % args}")

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._json(200, {"ok": True, "ready": BRAIN.ready,
                                    "error": BRAIN.error,
                                    "gen_backend": getattr(BRAIN, "gen_backend", None)})
        return self._json(404, {"error": "unknown route"})

    def do_POST(self):
        if not BRAIN.ready:
            return self._json(503, {"error": "brain not ready", "detail": BRAIN.error})
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        try:
            if self.path == "/turn":
                req = json.loads(body.decode("utf-8"))
                text = (req.get("text") or "").strip()
                if not text:
                    return self._json(400, {"error": "empty text"})
                return self._json(200, BRAIN.text_turn(text, speak=bool(req.get("speak"))))
            if self.path == "/voice_turn":
                if not body:
                    return self._json(400, {"error": "empty audio body"})
                rate = int(self.headers.get("X-Sample-Rate") or 16000)
                # NDJSON stream: the filler line is flushed mid-turn (masks
                # generation latency on the client); the final line is the turn.
                # HTTP/1.0 close-delimited body — no Content-Length needed.
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()

                def emit(obj: dict):
                    self.wfile.write(json.dumps(obj).encode("utf-8") + b"\n")
                    self.wfile.flush()

                BRAIN.voice_turn(body, rate, emit=emit)
                return None
            return self._json(404, {"error": "unknown route"})
        except Exception as e:  # noqa: BLE001  — a turn error must never kill the server
            print(f"[server] turn failed: {e}")
            return self._json(500, {"error": str(e)})


def main():
    global BRAIN
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int,
                    default=int(os.getenv("PORT", os.getenv("WINI_SERVER_PORT", "8123"))))
    args = ap.parse_args()
    BRAIN = Brain()
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"[server] listening on 0.0.0.0:{args.port} (brain loading in background)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
