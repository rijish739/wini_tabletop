"""Wini brain service — the whole tutoring pipeline behind one HTTP endpoint.

This is the cloud side of the thin-client design: the device handles only mic +
speaker + display + touch, and everything a turn needs runs HERE on the server.

    audio in ──► Cloud STT ──► TutorLoop (Gemini perception + generation,
                 (en-US)       retrieval, learner state, teaching-figure pick)
                                    │
              JSON out ◄── Cloud TTS (en-IN Chirp3-HD) ◄── sanitize_for_speech
              {transcript, answer, display[metadata], audio_b64, session_ended}

The client never calls Google APIs and never touches a model SDK — its entire
contract is the two POST routes below. The service runs on Cloud Run (PORT env);
per-learner state lives in Firestore when WINI_STATE_BACKEND=firestore, otherwise
in a local JSON file.

Endpoints
    GET  /health              -> {"ok": true, "ready": true|false, ...}
    POST /turn                <- {"text": "...", "speak": false}
                              -> turn JSON (display metadata always included)
    POST /voice_turn          <- raw LINEAR16 mono int16 PCM body,
                                 header X-Sample-Rate (default 16000)
                              -> NDJSON stream, one JSON object per line (see below)

/voice_turn stream lines, in the order the client usually sees them:

    {"part":"filler", ...}    Flushed early, as soon as STT + perception finish and
                              BEFORE the answer is generated, so the client can react
                              (show the transcript / a "thinking" face). Carries the
                              resolved concept. Includes a short spoken cognitive-state
                              phrase (voice/filler_banks.py) only when WINI_FILLERS=1.
    {"part":"audio","seq":N}  Answer PCM streamed in order as it is synthesised, so
                              playback starts ~0.3-1.0 s in instead of after the whole
                              answer exists (Part 13 Stage 1).
    {"part":"turn_meta", ...} The whole turn minus audio, so the client can drive the
                              display / UI.
    final line                Turn JSON plus the complete answer audio ("audio_b64" /
                              "audio_rate", 24 kHz PCM). A non-stream reader that parses
                              only this last line still gets a full turn. Streaming
                              clients see "audio_streamed":true here and MUST skip this
                              audio, or the answer plays twice.

    Ordering note: with streamed generation (Stage 2) the first audio chunk can arrive
    before "turn_meta" — speech starts before the turn is fully decided. Clients must
    handle either order.

Display contract: the response carries METADATA ONLY — `display[].image_path` is a
stable image ID the device resolves against its own local copy of the figure crops.

Run:  python wini_server.py [--port 8123]
Env:  GEN_BACKEND=gemini, WINI_SERVER_PORT / PORT, plus the usual Vertex vars.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from runtime_flags import RESPONSE_LAYER, STT_WRITE_CONFIDENCE_MIN

STT_TIMEOUT_S = 20.0
TTS_TIMEOUT_S = 30.0

_pool = ThreadPoolExecutor(max_workers=4)


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "")


# Part 13 stage flags. Each stage is independently revertible: rollback is one
# env var, not a revert. See PART13_LATENCY_STREAMING_PLAN.md §7.
STREAM_TTS = _flag("WINI_STREAM_TTS", "1")
STREAM_GEN = _flag("WINI_STREAM_GEN", "1")
# Part 15 Phase B: grade the armed pending_check CONCURRENTLY with perception
# instead of serially after it (the grader needs neither perception nor state).
# Removes the RC-3 serial-grader block from `brain`. Revertible: WINI_PARALLEL_GRADER=0.
PARALLEL_GRADER = _flag("WINI_PARALLEL_GRADER", "1")
# Response Layer (response_layer_architecture_plan.md). Shared default/source with tutor.
# rides "rl":true on the early filler line (so the client waits for the authoritative
# visual directive on turn_meta instead of concept-default-arming a scene) and forwards
# the turn's `visual` directive. Same env var tutor_loop.RESPONSE_LAYER reads.

# Part 15: app-level shared-secret gate for a publicly-reachable Cloud Run service.
# When WINI_API_KEY is set, every POST (the billed /turn and /voice_turn) must carry
# a matching `X-Wini-Key` header or it is rejected with 401 BEFORE any Gemini/STT/TTS
# work — so an unauthenticated hit costs nothing. Unset ⇒ no check (a private/local
# brain behind IAM or on localhost is unchanged). /health stays open for probes.
API_KEY = os.getenv("WINI_API_KEY", "").strip()


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
                try:
                    f_gem.result()
                except Exception as _ge:  # noqa: BLE001
                    print(f"[server] gemini warm note: {_ge}")
            print(f"[server] components built in "
                  f"{(time.perf_counter() - t_boot) * 1000:.0f} ms")
            # Pacing governor: runs the before_turn / turn / after_turn sequence
            # that sets each turn's answer budget. Best-effort — any failure falls
            # back to a plain, unbudgeted turn.
            try:
                from pacing.pacing_controller import PacingController
                self.pacing = PacingController()
            except Exception as e:  # noqa: BLE001
                print(f"[server] pacing unavailable: {e}")
                self.pacing = None
            # SPOKEN fillers are opt-in (WINI_FILLERS=1): in testing they felt
            # artificial, so by default the client masks generation latency with a
            # "thinking" face instead. The early NDJSON transcript line is streamed
            # either way.
            self.fillers = None
            if os.getenv("WINI_FILLERS", "0").lower() not in ("0", "false", ""):
                try:
                    from voice.filler_banks import FillerComposer
                    self.fillers = FillerComposer()
                except Exception as e:  # noqa: BLE001
                    print(f"[server] fillers unavailable: {e}")
            self._filler_pcm_cache: dict[str, bytes] = {}
            # Warm every cloud call a real turn makes, now, in parallel — client
            # CONSTRUCTION is the 4-9 s cost (CLAUDE.md) but each distinct RPC
            # method still pays its own first-call handshake, and readiness is
            # what releases the UI splash. Anything left cold here is paid by the
            # child on their first sentence, which is what "warmup" is supposed
            # to prevent. Best-effort: a failed warmup must not block readiness —
            # turns degrade per call, never at startup.
            #
            # Covered: STT recognize (was NEVER warmed — the client was built and
            # the first recognize_pcm paid the full handshake), streaming TTS
            # (a different gRPC method from synth(); every turn uses the streaming
            # one), one-shot TTS (the fallback), and perception (context cache +
            # MiniLM).
            t_warm = time.perf_counter()

            def _warm_stt():
                # Half a second of digital silence: a real recognize round-trip
                # that transcribes to "" — the handshake is the whole point.
                self.stt.recognize_pcm(b"\x00\x00" * 8000, 16000)

            def _warm_tts_stream():
                for _ in self.tts.synth_stream(iter(["Hello."])):
                    pass

            try:
                with ThreadPoolExecutor(max_workers=5) as warm:
                    fs = [warm.submit(_bounded, self.tts.synth, TTS_TIMEOUT_S, "Hi"),
                          warm.submit(_bounded, _warm_stt, STT_TIMEOUT_S),
                          warm.submit(_bounded, _warm_tts_stream, TTS_TIMEOUT_S),
                          # T9 teaching-visual matrix (~8 s incl. the MiniLM load
                          # it waits on). Without this leg it finished AFTER
                          # readiness and the first teaching turn ate the encode.
                          warm.submit(self.tutor.warm_visuals)]
                    if self.gen_backend == "gemini":
                        fs.append(warm.submit(self.tutor.analyze_only, "hello wini"))
                    for f in fs:
                        try:
                            f.result()
                        except Exception as _e:  # noqa: BLE001 — one cold path failing must never stop brain startup
                            print(f"[server] warmup leg note: {_e}")
            except Exception as e:  # noqa: BLE001
                print(f"[server] warmup failed (turns will retry live): {e}")
            print(f"[server] warmup in {(time.perf_counter() - t_warm) * 1000:.0f} ms")
            # Part 15 Phase E: durable learner state. With WINI_STATE_BACKEND=firestore
            # the learner's history lives in a regional Firestore document, not the
            # (ephemeral on Cloud Run) local JSON file. Read it ONCE here, at startup,
            # so a cold instance picks up the learner mid-session; the server then
            # writes it back at each TURN BOUNDARY (never mid-turn — plan §6 E).
            self._state_store = None
            try:
                import state_backend
                self.learner_id = state_backend.resolve_runtime_learner_id()
                state_backend.bind_state_identity(self.tutor.state.data, self.learner_id)
                self._state_store = state_backend.get_state_store()
                if self._state_store is not None:
                    loaded = self._state_store.load()
                    if loaded is not None:
                        # Replace the working copy wholesale — LearnerState reads
                        # everything through data.setdefault accessors, so swapping
                        # .data is a complete, side-effect-free state load.
                        from evidence import migrate_state_data
                        self.tutor.state.data = migrate_state_data(loaded)
                        state_backend.bind_state_identity(self.tutor.state.data, self.learner_id)
                        print(f"[server] loaded learner state from "
                              f"{self._state_store.describe()}")
                    else:
                        print(f"[server] no durable state yet at "
                              f"{self._state_store.describe()} — cold start")
            except Exception as e:  # noqa: BLE001 — never block readiness on the store
                # Never fall into a shared local/default learner after an identity
                # or durable-store failure: evidence isolation fails closed.
                self.error = f"learner identity/state backend unavailable: {e}"
                self.ready = False
                print(f"[server] {self.error}; refusing learner turns")
                return
            # A fresh brain process IS a fresh session (§6.4): drop the
            # session-scoped no-repeat sets so retrieval starts from the full
            # candidate pool again. Without this they persist in learner_state.json
            # across every run and grow without bound — an earlier bug left 593
            # chunks permanently blacklisted (audit A-7).
            def _commit_turn_state() -> None:
                self.tutor.state.save()
                self._persist_state(raise_on_failure=True)

            self.tutor._turn_commit_state = _commit_turn_state
            try:
                cleared = self.tutor.state.begin_session()
                self.tutor.state.save()
                self._persist_state()   # ensure a durable doc exists for a fresh learner
                print(f"[server] new session: cleared {cleared['served_items']} served items, "
                      f"{cleared['bridges_served']} served bridges")
            except Exception as e:  # noqa: BLE001 — never block readiness on this
                print(f"[server] session reset skipped: {e}")
            self.ready = True
            print(f"[server] brain ready (gen_backend={self.gen_backend})")
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            self.ready = True
            print(f"[server] brain initialized with warning (gen_backend={self.gen_backend}): {e}")

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
                  precomputed_grade: dict | str | None = None,
                  mode: str | None = None, emit=None,
                  stt_confidence: float | None = None,
                  turn_id: str | None = None,
                  learner_id: str | None = None) -> dict:
        from voice.sanitize import sanitize_for_speech

        import tutor_loop as _tl

        turn_id = turn_id or f"turn_{uuid.uuid4().hex}"
        learner_id = learner_id or getattr(self, "learner_id", None)
        if learner_id != getattr(self, "learner_id", learner_id):
            raise PermissionError("learner identity does not match the bound state")

        # Part 13 Stages 1+2: open the speech pipeline BEFORE the turn runs, and
        # hand the tutor a sink it can push the answer's first sentence into the
        # moment that sentence exists. Speech then starts while the rest of the
        # answer is still being generated, instead of after all of it.
        streaming = bool(emit) and STREAM_TTS and speak
        feed = finish = was_fed = None
        meta_emitted = [False]
        if streaming:
            feed, finish, was_fed = self._start_speech_stream(emit)
            if STREAM_GEN:
                _tl.set_answer_sink(feed)
                def _early_meta(meta_obj):
                    if not meta_emitted[0]:
                        meta_emitted[0] = True
                        m = {k: v for k, v in meta_obj.items() if k != "audio_b64"}
                        m["part"] = "turn_meta"
                        m["transcript"] = text
                        emit(m)
                _tl.set_meta_sink(_early_meta)

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
                                         precomputed_analysis=precomputed_analysis,
                                         precomputed_grade=precomputed_grade,
                                         stt_confidence=stt_confidence,
                                         turn_id=turn_id,
                                         learner_id=learner_id)
            finally:
                # The sink is thread-local and turn-scoped — clear it before any
                # other turn can run on this thread.
                _tl.set_answer_sink(None)
                _tl.set_meta_sink(None)
            brain_ms = int((time.perf_counter() - t0) * 1000)
            # Part 13 Stage 0: how much of `brain` was generation, and over how
            # many serial Gemini calls (answer + grader + cohesion + persona can
            # all land in one turn — the 1.0 s vs 4.0 s `brain` spread).
            try:
                gen = _tl.gen_stats()
                # How long the T9 figure pick took. It scores every crop in the
                # store against the utterance, so it is exactly the kind of stage
                # that can grow quietly — RC-4 was an uncounted stage hiding 2.2 s.
                t9 = getattr(self.tutor, "_last_t9_ms", None)
                if t9 is not None:
                    gen["t9"] = t9
                gen.update(result.get("layer_latency_ms") or {})
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
        # Per-turn learner diagnostics: the cognitive state + pedagogy decision behind
        # this turn, forwarded so the client can print it (its `--diag` readout). Purely
        # observational — it never moves learner state. Small; rides turn_meta too.
        _cid = (result.get("concept") or {}).get("concept_id")
        _cog = result.get("cognitive_update") or {}
        diagnostics = {
            "action": result.get("action"),
            "why": result.get("action_reason"),
            "need": result.get("need"),
            "mode": resolved_mode,
            "mode_reason": result.get("mode_reason"),
            "concept": _cid,
            "mastery": (round(self.tutor.state.mastery(_cid), 3) if _cid else None),
            "signals": result.get("signals") or [],
            "cognitive": {k: round(float(v), 3) for k, v in _cog.items()
                          if isinstance(v, (int, float))},
            "pending_check": result.get("pending_check"),
            "pending_hope": result.get("pending_hope"),
            "n_evidence": result.get("n_evidence"),
            "writeback": (wb or {}).get("outcome") if wb else None,
            "hope": result.get("hope_update"),
            "visual": ({"type": (result.get("visual") or {}).get("type"),
                        "earned": (result.get("visual") or {}).get("allowed")}
                       if result.get("visual") else None),
        }
        out = {
            "turn_id": turn_id,
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
            # Response Layer visual directive (None unless WINI_RESPONSE_LAYER=1). Rides
            # turn_meta via the meta dict below; the client arms/suppresses the scene off it.
            "visual": result.get("visual"),
            "diagnostics": diagnostics,
            "latency_ms": {"brain": brain_ms, **gen},
        }
        pcm = None
        if streaming:
            # The turn is decided — push the UI metadata now if it was not already
            # emitted early via set_meta_sink.
            if not meta_emitted[0]:
                meta = {k: v for k, v in out.items() if k != "audio_b64"}
                meta["part"] = "turn_meta"
                emit(meta)
                meta_emitted[0] = True

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

    def _persist_state(self, *, raise_on_failure: bool = False) -> None:
        """Write the working learner state to the durable backend (Part 15 Phase E).
        Called at TURN BOUNDARIES only — never mid-turn. Startup calls are best-effort;
        a coordinator commit call sets ``raise_on_failure`` and fails the Turn closed.
        No-op unless WINI_STATE_BACKEND=firestore."""
        store = getattr(self, "_state_store", None)
        if store is None:
            return
        try:
            store.save(self.tutor.state.data)
        except Exception as e:  # noqa: BLE001
            if raise_on_failure:
                raise
            print(f"[server] durable state write failed (retried next turn): {e}")

    def _maybe_speculate_grade(self, transcript: str, stt_confidence: float = 1.0,
                               *, turn_id: str, learner_id: str):
        """Part 15 Phase B: submit the answer grader for the armed pending_check
        so it runs CONCURRENTLY with the perception call in before_turn().

        Returns a Future[str outcome] or None when there is nothing to grade. The
        grader is a pure function of (question, expected, transcript) — the values
        are captured now, so later state mutation can't change the result. A cheap
        deterministic pre-gate skips the obvious non-attempts (empty / pure ack /
        bare question) and the turns a pending_* offer will consume before grading,
        so speculation almost never wastes a call; anything it lets through that
        turn() later rules a non_attempt is simply discarded (identical outcome)."""
        try:
            session = self.tutor.state.data.get("session", {}) or {}
            if session.get("pending_shift") or session.get("pending_mode_offer") \
                    or session.get("pending_test_resume"):
                return None
            pending = session.get("pending_check") or {}
            q, exp = pending.get("question"), pending.get("expected_answer")
            if not q or not exp:
                return None
            norm = (transcript or "").strip()
            if not norm:
                return None
            try:
                from cognitive_classifier.cues import is_pure_ack, is_question
                if is_pure_ack(norm.lower()) or is_question(transcript):
                    return None
            except Exception:  # noqa: BLE001 — pre-gate is optional, never fatal
                pass
            import tutor_loop as _tl
            from evidence import make_idempotency_key
            grade_key = make_idempotency_key(
                learner_id, turn_id,
                str(pending.get("item_id") or pending.get("id") or ""), transcript)
            return _pool.submit(
                _tl.judge_answer, q, exp, transcript, pending.get("rubric") or "",
                stt_confidence=stt_confidence,
                idempotency_key=grade_key,
                misconception_probe=pending.get("kind") == "misconception")
        except Exception as e:  # noqa: BLE001 — speculation must never break a turn
            print(f"[server] grade speculation skipped: {e}")
            return None

    def voice_turn(self, pcm: bytes, rate: int, emit=None,
                   mode: str | None = None, *, turn_id: str | None = None,
                   learner_id: str | None = None) -> dict:
        """One voice turn. With `emit` (a callable taking one JSON-able dict per
        response line), the filler part is flushed to the client as soon as
        STT + perception are done — BEFORE generation — so it plays while the
        answer is being produced. The final turn dict is always returned (and
        emitted last when streaming).

        `mode` is the touch-UI pedagogy selection (X-Wini-Mode); it is recorded
        on the session and echoed back, no behavior change (Part 12 §5.9)."""
        t0 = time.perf_counter()
        turn_id = turn_id or f"turn_{uuid.uuid4().hex}"
        learner_id = learner_id or getattr(self, "learner_id", None)
        if hasattr(self.stt, "recognize_pcm_evidence"):
            stt_evidence = _bounded(
                self.stt.recognize_pcm_evidence, STT_TIMEOUT_S, pcm, rate)
            transcript = stt_evidence.transcript
            stt_confidence = float(stt_evidence.confidence)
        else:  # compatibility with existing test/device adapters
            transcript = _bounded(self.stt.recognize_pcm, STT_TIMEOUT_S, pcm, rate)
            stt_confidence = 1.0
        stt_ms = int((time.perf_counter() - t0) * 1000)
        if not transcript:
            # nothing recognized — the client just re-listens; don't burn a turn
            out = {"transcript": "", "answer": "", "display": [],
                   "session_ended": False, "latency_ms": {"stt": stt_ms}}
            if emit:
                emit(out)
            return out

        # P0 front door: safety/nonsense must settle before either speculative
        # grading or pacing perception can call a model. TutorLoop repeats the
        # pure gate as defense in depth when it consumes the turn.
        from perception import gate as deterministic_gate
        front_route = deterministic_gate(transcript)
        trusted_input = stt_confidence >= STT_WRITE_CONFIDENCE_MIN

        # Part 15 Phase B: kick the grader off NOW, before perception, so the two
        # Gemini calls overlap. Joined just before text_turn below.
        grade_future = None
        if (front_route is None and trusted_input and PARALLEL_GRADER
                and getattr(self.tutor, "want_answer", True)):
            grade_future = self._maybe_speculate_grade(
                transcript, stt_confidence, turn_id=turn_id, learner_id=learner_id)

        # Pacing before_turn (analysis + answer budget) -> cognitive filler.
        # Best-effort: a failure here must never cost the turn itself.
        budget = precomputed = decision = None
        perception_ms = 0
        if front_route is None and trusted_input and self.pacing is not None:
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
            if RESPONSE_LAYER:
                # Tell the client the Response Layer is driving this turn: it should
                # wait for the authoritative visual directive on turn_meta rather than
                # concept-default-arming a scene off the early `concept` line.
                part["rl"] = True
            # Perception has resolved the concept by now (before generation), so
            # ride it on this early line. The client uses it to pick a tier-0
            # teaching scene and suppress the streamed answer BEFORE its first
            # audio chunk — turn_meta lands too late for that (it can arrive a
            # second into the answer). Additive; older clients ignore it.
            early_cid = ((precomputed or {}).get("concept") or {}).get("concept_id")
            if early_cid:
                part["concept"] = early_cid
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

        # Join the speculative grader (ran concurrently with perception above). A
        # failure or timeout just falls back to turn()'s serial grade — never worse.
        precomputed_grade = None
        grade_ms = 0
        if grade_future is not None:
            tg = time.perf_counter()
            try:
                precomputed_grade = grade_future.result(timeout=STT_TIMEOUT_S)
            except Exception as e:  # noqa: BLE001
                print(f"[server] speculative grade failed; serial fallback: {e}")
            grade_ms = int((time.perf_counter() - tg) * 1000)

        out = self.text_turn(transcript, speak=True, answer_budget=budget,
                             precomputed_analysis=precomputed,
                             precomputed_grade=precomputed_grade, mode=mode,
                             emit=emit, stt_confidence=stt_confidence,
                             turn_id=turn_id, learner_id=learner_id)
        out["latency_ms"]["stt"] = stt_ms
        out["stt_confidence"] = round(stt_confidence, 4)
        out["latency_ms"]["perception"] = perception_ms
        # grade_ms is the JOIN wait after perception — near-0 means the grader
        # finished inside the perception window (the whole point of Phase B).
        if grade_future is not None:
            out["latency_ms"]["grade_join"] = grade_ms
            out["latency_ms"]["grade_parallel"] = 1 if precomputed_grade is not None else 0
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


try:
    import debug_logger as _dbg
except ImportError:
    _dbg = None  # type: ignore[assignment]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter default log line
        print(f"[http] {self.address_string()} {fmt % args}")

    def _cors(self):
        """Emit CORS headers so the debug console HTML works from file:// or any origin.
        These only cover developer-facing routes; the API key gate still protects /turn."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, X-Wini-Key, X-Sample-Rate, X-Wini-Mode, X-Wini-Turn-Id")

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        """Handle CORS preflight for POST routes (browser sends OPTIONS before POST
        from a file:// page or a cross-origin page)."""
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            from runtime.supervisor import RuntimeHealth

            if not BRAIN.ready:
                runtime_health = (
                    RuntimeHealth.UNAVAILABLE if BRAIN.error else RuntimeHealth.STARTING
                )
            elif BRAIN.tutor is not None:
                runtime_health = BRAIN.tutor.runtime_health.health
            elif BRAIN.error:
                runtime_health = RuntimeHealth.DEGRADED
            else:
                runtime_health = RuntimeHealth.READY
            return self._json(200, {"ok": True, "ready": BRAIN.ready,
                                    "error": BRAIN.error,
                                    "runtime_health": runtime_health.value,
                                    "gen_backend": getattr(BRAIN, "gen_backend", None)})

        # ── Debug routes (developer-only, no auth gate — same as /health) ──────
        if self.path.startswith("/debug/logs"):
            if not _dbg:
                return self._json(503, {"error": "debug_logger not loaded"})
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(self.path).query)
            tail_n = int((qs.get("tail") or ["200"])[0])
            return self._json(200, {"entries": _dbg.tail(tail_n)})

        if self.path == "/debug/stream":
            if not _dbg:
                return self._json(503, {"error": "debug_logger not loaded"})
            # Server-Sent Events: streams structured log lines until disconnected.
            # Each event: "data: <json>\n\n"
            q = _dbg.subscribe()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")  # nginx: disable proxy buf
                self._cors()
                self.end_headers()
                # Replay the last 100 entries so the console shows recent history
                for entry in _dbg.tail(100):
                    self.wfile.write(f"data: {json.dumps(entry)}\n\n".encode("utf-8"))
                self.wfile.flush()
                while True:
                    try:
                        msg = q.get(timeout=15)
                        if msg is None:
                            break
                        self.wfile.write(f"data: {msg}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        # Periodic comment keepalive stops proxy connection drops
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except (ConnectionResetError, BrokenPipeError):
                pass
            finally:
                _dbg.unsubscribe(q)
            return None

        return self._json(404, {"error": "unknown route"})

    def do_POST(self):
        if self.path == "/debug/clear":
            count = _dbg.clear() if _dbg else 0
            return self._json(200, {"cleared": count})

        if self.path.split("?", 1)[0] == "/board/render":
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            try:
                from urllib.parse import parse_qs, urlparse
                req = json.loads(body.decode("utf-8")) if body else {}
                payload = req.get("payload") or req.get("elements") or req
                if not payload:
                    return self._json(400, {"error": "empty payload"})
                q = parse_qs(urlparse(self.path).query)
                mode = (req.get("mode") or (q.get("mode") or [""])[0]).strip().lower()
                from board_buddy_renderer import (render_board_payload,
                                                  render_board_payload_animated)
                data_url = None
                animated = mode in ("animated", "apng", "anim")
                if animated:
                    # Animated APNG; falls back to a static frame for a non-animating board.
                    data_url = render_board_payload_animated(payload)
                    if not data_url:
                        animated = False
                if not data_url:
                    data_url = render_board_payload(payload)
                if not data_url:
                    return self._json(500, {"error": "rendering failed"})
                return self._json(200, {"ok": True, "animated": animated,
                                        "image_data_url": data_url})
            except Exception as _e:  # noqa: BLE001
                return self._json(500, {"error": str(_e)})

        # App-secret gate (Part 15): reject before touching the brain or any billed
        # cloud call. Constant-time compare so the check can't be timed.
        if API_KEY:
            import hmac
            if not hmac.compare_digest(self.headers.get("X-Wini-Key", ""), API_KEY):
                return self._json(401, {"error": "unauthorized"})
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
                turn_id = req.get("turn_id") or self.headers.get("X-Wini-Turn-Id")
                return self._json(200, BRAIN.text_turn(
                    text, speak=bool(req.get("speak")), mode=mode,
                    turn_id=turn_id, learner_id=BRAIN.learner_id))
            if self.path == "/stream_turn":
                # Streaming text turn: same JSON input as /turn, same NDJSON output
                # as /voice_turn (filler / audio-chunks / turn_meta / final line).
                # Bypasses STT so WINI_STREAM_GEN + WINI_SYNC_VISUAL activate on
                # plain text. Use for latency measurement and CI without a mic.
                req = json.loads(body.decode("utf-8"))
                text = (req.get("text") or "").strip()
                if not text:
                    return self._json(400, {"error": "empty text"})
                mode = req.get("mode") or self.headers.get("X-Wini-Mode")
                turn_id = req.get("turn_id") or self.headers.get("X-Wini-Turn-Id")
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self._cors()
                self.end_headers()
                emit_lock = threading.Lock()

                def emit_st(obj: dict):
                    line = json.dumps(obj).encode("utf-8") + b"\n"
                    with emit_lock:
                        self.wfile.write(line)
                        self.wfile.flush()

                # Synthetic filler so the stream starts immediately
                emit_st({"part": "filler", "transcript": text})
                result = BRAIN.text_turn(
                    text, speak=True, mode=mode, emit=emit_st,
                    turn_id=turn_id, learner_id=BRAIN.learner_id)
                emit_st(result)
                return None
            if self.path == "/voice_turn":

                if not body:
                    return self._json(400, {"error": "empty audio body"})
                rate = int(self.headers.get("X-Sample-Rate") or 16000)
                mode = self.headers.get("X-Wini-Mode")
                turn_id = self.headers.get("X-Wini-Turn-Id")
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

                BRAIN.voice_turn(
                    body, rate, emit=emit, mode=mode, turn_id=turn_id,
                    learner_id=BRAIN.learner_id)
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
