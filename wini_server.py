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
                                 {"part":"filler", "filler", "bank", "transcript",
                                   "audio_b64", "audio_rate"} — optional, flushed
                                   early: a short cognitive-state phrase
                                   (voice/filler_banks.py) picked from the
                                   perception analysis and synthesised BEFORE
                                   generation. Filler audio only with WINI_FILLERS=1.
                                 {"part":"turn_meta", ...} — the whole turn minus
                                   audio, so the client can drive the display/UI.
                                 {"part":"audio","seq":N,"audio_b64","audio_rate"}
                                   — Part 13 Stage 1: the answer's PCM in order as
                                   it is synthesised, so playback starts ~0.3-1.0 s
                                   in rather than after the whole answer exists.
                                 last line: turn JSON + "audio_b64"/"audio_rate"
                                 (24 kHz PCM). Non-stream readers that parse only
                                 the final line still get the full turn — the
                                 complete audio rides on it even when it was also
                                 streamed. Streaming clients see "audio_streamed":
                                 true and must SKIP that final audio, or the answer
                                 is spoken twice.

                                 Ordering note: with streamed generation (Stage 2)
                                 the first audio chunk can precede "turn_meta" —
                                 speech starts before the turn is fully decided.
                                 Clients must handle either order.

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
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STT_TIMEOUT_S = 20.0
TTS_TIMEOUT_S = 30.0

_pool = ThreadPoolExecutor(max_workers=4)


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "")


# Part 13 stage flags. Each stage is independently revertible: rollback is one
# env var, not a revert. See PART13_LATENCY_STREAMING_PLAN.md §7.
STREAM_TTS = _flag("WINI_STREAM_TTS", "1")
STREAM_GEN = _flag("WINI_STREAM_GEN", "1")


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

    def _warm_gemini(self):
        """Build the Vertex client + make one tiny call, so the first real turn
        does not pay the 4-9 s ADC/channel setup."""
        if self.gen_backend != "gemini":
            return
        import llm_vertex
        llm_vertex.generate_reply("Say OK.", temperature=0.0, max_output_tokens=8)

    def _load(self):
        try:
            import tutor_loop
            from voice.cloud_stt import CloudStt
            from voice.cloud_tts import CloudTts

            self.gen_backend = getattr(tutor_loop, "GEN_BACKEND", "qwen")
            # Build the four independent pieces CONCURRENTLY. Every one of them is
            # dominated by a cost that is not CPU-bound on this box — Google client
            # construction is ADC/channel setup (4-9 s each, CLAUDE.md), TutorLoop
            # is file loads — so serialising them made boot the SUM of the waits
            # instead of the longest one.
            t_boot = time.perf_counter()
            with ThreadPoolExecutor(max_workers=4) as boot:
                f_tutor = boot.submit(tutor_loop.TutorLoop)
                f_stt = boot.submit(CloudStt)
                f_tts = boot.submit(CloudTts)
                # Warming Gemini here also builds the shared Vertex client that
                # perception will reuse (the memo is lock-guarded for exactly this).
                f_gem = boot.submit(self._warm_gemini)
                self.tutor = f_tutor.result()
                self.stt = f_stt.result()
                self.tts = f_tts.result()
                f_gem.result()
            print(f"[server] components built in "
                  f"{(time.perf_counter() - t_boot) * 1000:.0f} ms")
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
            # Second wave, also in parallel: the first perception call (which pulls
            # in the context cache + MiniLM) and the first TTS call. Neither needs
            # the other.
            t_warm = time.perf_counter()
            try:
                with ThreadPoolExecutor(max_workers=2) as warm:
                    fs = [warm.submit(_bounded, self.tts.synth, TTS_TIMEOUT_S, "Hi")]
                    if self.gen_backend == "gemini":
                        fs.append(warm.submit(self.tutor.analyze_only, "hello wini"))
                    for f in fs:
                        f.result()
            except Exception as e:  # noqa: BLE001
                print(f"[server] warmup failed (turns will retry live): {e}")
            print(f"[server] warmup in {(time.perf_counter() - t_warm) * 1000:.0f} ms")
            # A fresh brain process IS a fresh session (§6.4): drop the
            # session-scoped no-repeat sets so retrieval starts from the full
            # candidate pool again. Without this they persisted in
            # learner_state.json across every run and grew without bound —
            # 593 chunks were permanently blacklisted on the device (audit A-7).
            try:
                cleared = self.tutor.state.begin_session()
                self.tutor.state.save()
                print(f"[server] new session: cleared {cleared['served_items']} served items, "
                      f"{cleared['bridges_served']} served bridges")
            except Exception as e:  # noqa: BLE001 — never block readiness on this
                print(f"[server] session reset skipped: {e}")
            self.ready = True
            print(f"[server] brain ready (gen_backend={self.gen_backend})")
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            print(f"[server] FAILED to load brain: {e}")

    # ------------------------------------------------------------------
    def _start_speech_stream(self, emit):
        """Open the text -> chunker -> TTS -> NDJSON audio pipeline.

        Returns (feed, finish, was_fed). `feed(text)` hands over answer text as
        it is generated; `was_fed()` says whether anything has been handed over
        yet (so the caller does not re-feed an answer that streamed generation
        already delivered — that would speak it twice); `finish()` closes the
        text side and blocks until the last audio chunk has been emitted,
        returning (pcm, stats).

        The worker blocks on the text queue and only opens the TTS gRPC stream
        once there is something to say. Opening it earlier (to "pre-warm" it)
        leaves the input side idle for however long generation takes, and Cloud
        TTS drops an idle streaming input — which showed up as an intermittent
        zero-chunk turn that silently fell back to one-shot synthesis, more
        often the slower generation was.
        """
        from voice.chunker import ClauseChunker
        from voice.sanitize import sanitize_for_speech

        text_q: "queue.Queue[str | None]" = queue.Queue()
        state = {"seq": 0, "pcm": [], "first_ms": None, "fed": False,
                 "error": None, "t0": None}

        def _pieces(first: str):
            """Text queue -> speakable chunks, sanitized per piece.

            Sanitizing per piece (not per chunk) matters: sanitize_for_speech
            matches LaTeX delimiters with DOTALL, so it must see whole sentences
            — never a fragment that a chunk boundary cut in half.
            """
            chunker = ClauseChunker()
            piece = first
            while True:
                if piece is None:
                    tail = chunker.flush()
                    if tail:
                        yield tail + " "
                    return
                for c in chunker.feed(sanitize_for_speech(piece) + " "):
                    yield c + " "
                piece = text_q.get()

        def _worker():
            # Block here, NOT inside the open stream: nothing is sent to Cloud
            # TTS until the first sentence exists.
            first = text_q.get()
            if first is None:
                return
            state["t0"] = time.perf_counter()
            try:
                for pcm_chunk in self.tts.synth_stream(_pieces(first)):
                    if state["seq"] == 0:
                        state["first_ms"] = int(
                            (time.perf_counter() - state["t0"]) * 1000)
                    emit({"part": "audio", "seq": state["seq"],
                          "audio_b64": base64.b64encode(pcm_chunk).decode("ascii"),
                          "audio_rate": self.tts.rate})
                    state["pcm"].append(pcm_chunk)
                    state["seq"] += 1
            except Exception as e:  # noqa: BLE001 — reported to the caller
                state["error"] = e

        thread = threading.Thread(target=_worker, name="tts-emit", daemon=True)
        thread.start()

        def feed(text: str) -> None:
            if text and text.strip():
                state["fed"] = True
                text_q.put(text)

        def finish():
            text_q.put(None)
            thread.join(timeout=TTS_TIMEOUT_S * 2)
            total = int((time.perf_counter() - state["t0"]) * 1000) \
                if state["t0"] else 0
            return b"".join(state["pcm"]), {
                "chunks": state["seq"], "first_ms": state["first_ms"],
                "total_ms": total, "error": state["error"], "fed": state["fed"]}

        def was_fed() -> bool:
            return state["fed"]

        return feed, finish, was_fed

    def text_turn(self, text: str, speak: bool, answer_budget: dict | None = None,
                  precomputed_analysis: dict | None = None,
                  mode: str | None = None, emit=None) -> dict:
        from voice.sanitize import sanitize_for_speech

        import tutor_loop as _tl

        # Part 13 Stages 1+2: open the speech pipeline BEFORE the turn runs, and
        # hand the tutor a sink it can push the answer's first sentence into the
        # moment that sentence exists. Speech then starts while the rest of the
        # answer is still being generated, instead of after all of it.
        streaming = bool(emit) and STREAM_TTS and speak
        feed = finish = was_fed = None
        if streaming:
            feed, finish, was_fed = self._start_speech_stream(emit)
            if STREAM_GEN:
                _tl.set_answer_sink(feed)

        with self._lock:
            session = self.tutor.state.data.setdefault("session", {})
            # Pedagogy mode from the touch UI (Part 12 §5.9). Additive: recorded on
            # the session for Part 12's ModeController to consume — no pedagogy
            # behavior changes here. None/absent ⇒ EXPLAIN (today's behavior).
            # An ACTIVE TEST ignores mode taps: a stray touch mid-quiz must not
            # abandon the set unscored. The spoken "stop the test" cue (handled in
            # resolve_mode) stays the explicit way out.
            ts = session.get("test_state")
            test_active = ts is not None and ts.get("phase") != "done"
            if mode and not test_active:
                session["mode"] = mode
            t0 = time.perf_counter()
            try:
                result = self.tutor.turn(text, answer_budget=answer_budget,
                                         precomputed_analysis=precomputed_analysis)
            finally:
                # The sink is thread-local and turn-scoped — clear it before any
                # other turn can run on this thread.
                _tl.set_answer_sink(None)
            brain_ms = int((time.perf_counter() - t0) * 1000)
            # Part 13 Stage 0: how much of `brain` was generation, and over how
            # many serial Gemini calls (answer + grader + cohesion + persona can
            # all land in one turn — the 1.0 s vs 4.0 s `brain` spread).
            try:
                gen = _tl.gen_stats()
            except Exception:  # noqa: BLE001 — instrumentation must never cost a turn
                gen = {}
            # Read the mode AFTER the turn: turn() can move it itself — a spoken
            # "let's practice"/"test me"/"stop the test" cue (resolve_mode), a
            # PRACTICE->EXPLAIN ladder exit, or a failed-gate corrective EXPLAIN
            # (_drive_test). Reading it before the turn echoed a STALE mode and
            # left the touch UI one turn behind the brain (test_results.md Bug 3).
            resolved_mode = session.get("mode", "EXPLAIN")
        answer = (result.get("answer") or "").strip()
        # Slim writeback — just the graded outcome the UI needs for its correct/
        # almost feedback cue (the full writeback carries state internals).
        wb = result.get("writeback") or None
        out = {
            "transcript": text,
            "answer": answer,
            "display": result.get("display") or [],
            "session_ended": bool(result.get("session_ended")),
            "action": result.get("action"),
            "need": result.get("need"),
            "concept": (result.get("concept") or {}).get("concept_id"),
            "gen_backend": result.get("gen_backend"),
            "mode": resolved_mode,
            # Part 12 §5.6: the touch-UI (ModeChannelSink) drives its quiz progress
            # bar off `test` and its answer-feedback cue off `writeback.outcome`.
            "test": result.get("test"),
            "writeback": {"outcome": wb.get("outcome")} if wb else None,
            "latency_ms": {"brain": brain_ms, **gen},
        }
        pcm = None
        if streaming:
            # The turn is decided — push the UI metadata now. With streamed
            # generation speech has usually already started, so this can land a
            # second or two INTO the answer rather than before it; the client
            # handles either order. That trade is deliberate: the child hearing
            # Wini seconds sooner beats the figure card appearing at t=0, and
            # most turns carry no figure at all.
            meta = {k: v for k, v in out.items() if k != "audio_b64"}
            meta["part"] = "turn_meta"
            emit(meta)
            # A reply that never went through streamed generation (a scripted /
            # canned / farewell line, or GEN_BACKEND=qwen) reaches the speech
            # pipeline here instead. Guarded on was_fed(): re-feeding an answer
            # that _stream_answer already delivered would speak it TWICE.
            if speak and answer and not was_fed():
                feed(answer)
            pcm, stats = finish()
            if stats["error"] is not None:
                print(f"[server] streaming TTS failed: {stats['error']}")
            if stats["chunks"]:
                out["audio_streamed"] = True
                out["audio_chunks"] = stats["chunks"]
                out["latency_ms"]["tts_first_chunk"] = stats["first_ms"]
                out["latency_ms"]["tts"] = stats["total_ms"]
            elif stats["error"] is not None:
                pcm = None      # nothing was spoken — fall through to one-shot

        if speak and answer:
            if pcm is None:
                spoken = sanitize_for_speech(answer)
                t1 = time.perf_counter()
                pcm = _bounded(self.tts.synth, TTS_TIMEOUT_S, spoken)
                out["latency_ms"]["tts"] = int((time.perf_counter() - t1) * 1000)
            # The full audio also rides on the final line: a reader that parses
            # only the last line (the documented non-streaming contract) still
            # gets a complete turn. Streaming clients skip it via audio_streamed.
            out["audio_b64"] = base64.b64encode(pcm).decode("ascii")
            out["audio_rate"] = self.tts.rate
        return out

    def voice_turn(self, pcm: bytes, rate: int, emit=None,
                   mode: str | None = None) -> dict:
        """One voice turn. With `emit` (a callable taking one JSON-able dict per
        response line), the filler part is flushed to the client as soon as
        STT + perception are done — BEFORE generation — so it plays while the
        answer is being produced. The final turn dict is always returned (and
        emitted last when streaming).

        `mode` is the touch-UI pedagogy selection (X-Wini-Mode); it is recorded
        on the session and echoed back, no behavior change (Part 12 §5.9)."""
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
        perception_ms = 0
        if self.pacing is not None:
            tp = time.perf_counter()
            # Part 13 diagnostics: split the perception counter into its parts
            # (Gemini round-trip vs MiniLM candidate hints vs §5.5 cross-check).
            _gp = getattr(self.tutor, "analyzer", None)
            _gp = getattr(_gp, "classifier", None)
            if hasattr(_gp, "timing_reset"):
                _gp.timing_reset()
            try:
                decision = self.pacing.before_turn(transcript, self.tutor)
                budget = decision.answer_budget.as_dict()
                precomputed = decision.analysis
            except Exception as e:  # noqa: BLE001
                print(f"[server] pacing before_turn failed; plain turn: {e}")
                decision = None
            # Part 13 Stage 0 / RC-4: the perception Gemini call lives in here and
            # was counted NOWHERE — the client logged 14.7 s turns while latency_ms
            # summed to 7.2 s. It is memoized by NORMALIZED text, so a repeated
            # phrasing costs 0 and a fresh utterance pays ~2.2 s.
            perception_ms = int((time.perf_counter() - tp) * 1000)
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
                             precomputed_analysis=precomputed, mode=mode,
                             emit=emit)
        out["latency_ms"]["stt"] = stt_ms
        out["latency_ms"]["perception"] = perception_ms
        if hasattr(_gp, "timing"):
            for k, v in (_gp.timing or {}).items():
                out["latency_ms"][f"p_{k}"] = v
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
                mode = req.get("mode") or self.headers.get("X-Wini-Mode")
                return self._json(200, BRAIN.text_turn(
                    text, speak=bool(req.get("speak")), mode=mode))
            if self.path == "/voice_turn":
                if not body:
                    return self._json(400, {"error": "empty audio body"})
                rate = int(self.headers.get("X-Sample-Rate") or 16000)
                mode = self.headers.get("X-Wini-Mode")
                # NDJSON stream: the filler line is flushed mid-turn (masks
                # generation latency on the client); the final line is the turn.
                # HTTP/1.0 close-delimited body — no Content-Length needed.
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()

                # Two threads emit on this socket once generation streams: the
                # turn thread (filler / turn_meta / final) and the TTS worker
                # (audio chunks). Interleaved writes would corrupt lines, so
                # every emit is serialised — one whole JSON line at a time.
                emit_lock = threading.Lock()

                def emit(obj: dict):
                    line = json.dumps(obj).encode("utf-8") + b"\n"
                    with emit_lock:
                        self.wfile.write(line)
                        self.wfile.flush()

                BRAIN.voice_turn(body, rate, emit=emit, mode=mode)
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
