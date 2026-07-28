"""Part 13 latency replay harness — per-stage timers for one voice turn.

This is the instrument that produced the Part 13 §1 baseline, checked in so a
regression is one command away rather than a re-derivation. It replays the
`/voice_turn` pipeline in-process with a timer around every stage, including the
two the server never counted (perception, and generation split by call count).

SAFETY: it runs against a **copy** of learner_state.json. A probe must never
move a real child's mastery state — every run starts from the same snapshot, so
runs are comparable and repeatable.

Usage
    python -m voice.latency_probe --text "explain the discriminant"
    python -m voice.latency_probe --text "..." --turns 3      # memoization effects
    python -m voice.latency_probe --pcm capture.raw --rate 16000
    python -m voice.latency_probe --text "..." --compare-tts  # batch vs streaming

Env: GEN_BACKEND=gemini plus the usual Vertex vars (source .env first).
"""

from __future__ import annotations

import argparse
import base64
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _stage(label: str, fn):
    t0 = time.perf_counter()
    value = fn()
    return value, (time.perf_counter() - t0) * 1000, label


def run_once(tutor, pacing, stt, tts, *, text=None, pcm=None, rate=16000,
             compare_tts=False) -> dict:
    """One full turn with per-stage timings (ms)."""
    import tutor_loop as tl
    from voice.sanitize import sanitize_for_speech

    timings: dict[str, float] = {}

    # 1. STT ---------------------------------------------------------------
    if pcm is not None:
        transcript, ms, _ = _stage("stt", lambda: stt.recognize_pcm(pcm, rate))
        timings["stt"] = ms
    else:
        transcript = text
        timings["stt"] = 0.0
    if not transcript:
        return {"error": "STT returned nothing", "timings": timings}

    # 2. perception (pacing.before_turn) — RC-4, invisible before Part 13 ----
    budget = precomputed = None
    if pacing is not None:
        def _perceive():
            d = pacing.before_turn(transcript, tutor)
            return d.answer_budget.as_dict(), d.analysis
        (budget, precomputed), ms, _ = _stage("perception", _perceive)
        timings["perception"] = ms
    else:
        timings["perception"] = 0.0

    # 3. brain (retrieval + generation) -------------------------------------
    result, ms, _ = _stage("brain", lambda: tutor.turn(
        transcript, answer_budget=budget, precomputed_analysis=precomputed))
    timings["brain"] = ms
    gen = tl.gen_stats()

    answer = (result.get("answer") or "").strip()
    spoken = sanitize_for_speech(answer)

    # 4. TTS ----------------------------------------------------------------
    pcm_out, ms, _ = _stage("tts", lambda: tts.synth(spoken))
    timings["tts"] = ms

    # 5. transport ----------------------------------------------------------
    _, ms, _ = _stage("b64", lambda: base64.b64encode(pcm_out).decode("ascii"))
    timings["b64"] = ms

    out = {
        "transcript": transcript,
        "answer": answer,
        "answer_chars": len(answer),
        "speech_s": len(pcm_out) / 2 / getattr(tts, "rate", 24000),
        "timings": timings,
        "gemini_calls": gen.get("gemini_calls", 0),
        "gemini_ms": gen.get("gemini_ms", 0),
    }

    # Optional: what streaming TTS would have given us for the same text.
    if compare_tts and spoken:
        try:
            t0 = time.perf_counter()
            first_ms = None
            for _chunk in tts.synth_stream(iter([spoken])):
                if first_ms is None:
                    first_ms = (time.perf_counter() - t0) * 1000
            out["tts_stream_first_ms"] = first_ms
        except Exception as e:  # noqa: BLE001 — probe must not die on an optional path
            out["tts_stream_first_ms"] = f"unavailable: {e}"
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--text", default=None, help="skip STT and replay from text")
    ap.add_argument("--pcm", default=None, help="raw LINEAR16 mono int16 capture")
    ap.add_argument("--rate", type=int, default=16000)
    ap.add_argument("--turns", type=int, default=1,
                    help="repeat N times (shows perception memoization effects)")
    ap.add_argument("--compare-tts", action="store_true",
                    help="also time streaming TTS time-to-first-chunk")
    ap.add_argument("--state", default=str(ROOT / "learner_state.json"))
    args = ap.parse_args()

    if not args.text and not args.pcm:
        ap.error("one of --text / --pcm is required")

    # Work on a COPY — a probe must never move real learner state.
    tmpdir = Path(tempfile.mkdtemp(prefix="wini_latency_probe_"))
    state_copy = tmpdir / "learner_state.json"
    src = Path(args.state)
    if src.exists():
        shutil.copy2(src, state_copy)
    print(f"[probe] learner state copy: {state_copy}")

    pcm = Path(args.pcm).read_bytes() if args.pcm else None

    import tutor_loop
    from voice.cloud_stt import CloudStt
    from voice.cloud_tts import CloudTts

    t0 = time.perf_counter()
    tutor = tutor_loop.TutorLoop(state_path=state_copy)
    print(f"[probe] TutorLoop construction: {(time.perf_counter()-t0)*1000:.0f} ms "
          "(one-time boot cost, not per-turn)")
    stt = CloudStt()
    tts = CloudTts()
    try:
        from pacing.pacing_controller import PacingController
        pacing = PacingController()
    except Exception as e:  # noqa: BLE001
        print(f"[probe] pacing unavailable: {e}")
        pacing = None

    # Warm every cloud client — construction is the 4-9 s cold cost (CLAUDE.md),
    # and measuring it as per-turn latency is exactly the mistake this file exists
    # to prevent.
    print("[probe] warming clients ...")
    try:
        tts.synth("Hi")
        tutor.analyze_only("hello wini")
    except Exception as e:  # noqa: BLE001
        print(f"[probe] warmup failed: {e}")

    rows = []
    for i in range(args.turns):
        print(f"\n=== turn {i + 1}/{args.turns} ===")
        r = run_once(tutor, pacing, stt, tts, text=args.text, pcm=pcm,
                     rate=args.rate, compare_tts=args.compare_tts)
        if "error" in r:
            print(f"[probe] {r['error']}")
            continue
        rows.append(r)
        t = r["timings"]
        total = sum(t.values())
        print(f"You:  {r['transcript']}")
        print(f"Wini: {r['answer'][:160]}{'...' if len(r['answer']) > 160 else ''}")
        print(f"      {r['answer_chars']} chars -> {r['speech_s']:.1f}s of speech")
        for k in ("stt", "perception", "brain", "tts", "b64"):
            if k in t:
                print(f"  {k:<12} {t[k]:8.0f} ms")
        print(f"  {'-'*12} {'-'*8}")
        print(f"  {'TOTAL':<12} {total:8.0f} ms   <- time before ANY sound")
        print(f"  (of brain: {r['gemini_ms']} ms across "
              f"{r['gemini_calls']} generation call(s))")
        if "tts_stream_first_ms" in r:
            v = r["tts_stream_first_ms"]
            if isinstance(v, float):
                print(f"  streaming TTS first chunk: {v:.0f} ms "
                      f"(vs {t['tts']:.0f} ms batch)")
            else:
                print(f"  streaming TTS: {v}")

    if len(rows) > 1:
        print("\n=== medians across turns ===")
        for k in ("stt", "perception", "brain", "tts"):
            vals = [r["timings"][k] for r in rows if k in r["timings"]]
            if vals:
                print(f"  {k:<12} {statistics.median(vals):8.0f} ms")

    print(f"\n[probe] state copy left at {state_copy} (real state untouched)")


if __name__ == "__main__":
    sys.exit(main())
