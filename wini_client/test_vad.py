"""Endpointer test for record_utterance — no microphone, no device.

The bug this guards (2026-07-23): the old endpointer used ONE fixed RMS gate
(0.018) to both start and stop. In the room the Pi actually sits in, the noise
floor is ABOVE that gate, so "is it quiet again?" never became true and every
measured turn on the device ended with reason="hard_cap", capture_ms=15000 —
the child spoke for 3 s and then waited 12 s in silence before Wini even began
thinking, and STT was then handed 15 s of mostly-nothing to transcribe.

The fake InputStream below replays an RMS profile as white noise, so the gates
are exercised exactly as they are on the device.

Run:  python -m wini_client.test_vad
"""

from __future__ import annotations

import sys
import types

import numpy as np


class _FakeStream:
    """InputStream stand-in: yields blocks whose RMS follows a profile."""

    def __init__(self, profile, blocksize, **_kw):
        self.profile = profile
        self.block = blocksize
        self.i = 0
        self.rng = np.random.default_rng(7)

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def read(self, n):
        rms = self.profile[min(self.i, len(self.profile) - 1)]
        self.i += 1
        # white noise scaled to the requested RMS, as int16
        x = self.rng.normal(0.0, rms, size=n) * 32768.0
        return np.clip(x, -32767, 32767).astype(np.int16).reshape(-1, 1), False


def _install_fake_sd(profile, blocksize):
    fake = types.ModuleType("sounddevice")
    fake.PortAudioError = type("PortAudioError", (Exception,), {})
    fake.InputStream = lambda **kw: _FakeStream(profile, kw.get("blocksize", blocksize))
    sys.modules["sounddevice"] = fake


def _profile(block_ms, *segments):
    """[(seconds, rms), ...] -> a per-block RMS list."""
    out = []
    for secs, rms in segments:
        out += [rms] * int(secs * 1000 / block_ms)
    return out


def _run(name, segments, *, expect_reason, max_capture_ms, block_ms=30, **kw):
    from wini_client import client

    client._vad_noise = 0.005          # fresh room each case; deliberately a
                                       # seed BELOW every floor under test
    # Always bounded: a gate that never opens must report as a failed case, not
    # hang the suite (record_utterance blocks forever with no wait window, and
    # that is how a mistuned start gate first showed up here).
    kw.setdefault("wait_for_speech_s", 8.0)
    _install_fake_sd(_profile(block_ms, *segments), int(16000 * block_ms / 1000))
    pcm = client.record_utterance(**kw)
    if pcm is None:
        print(f"FAIL  {name}: never detected speech (start gate too high)")
        return False
    last = getattr(client.record_utterance, "last", {})
    ok = (last.get("reason") == expect_reason
          and last.get("capture_ms", 1e9) <= max_capture_ms)
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {last}")
    return ok


def main() -> int:
    ok = True

    # THE REGRESSION. Room noise 0.020 — above the old fixed 0.018 gate, so the
    # old code could never endpoint. 2 s of speech must end ~700 ms after it stops.
    ok &= _run("noisy room, 2s of speech",
               [(1.0, 0.020), (2.0, 0.090), (6.0, 0.020)],
               expect_reason="silence", max_capture_ms=3400)

    # Quiet room: same utterance, same prompt endpoint.
    ok &= _run("quiet room, 2s of speech",
               [(1.0, 0.003), (2.0, 0.060), (6.0, 0.003)],
               expect_reason="silence", max_capture_ms=3400)

    # THE DEVICE'S OWN NUMBERS (tools/mic_floor.py + tools/mic_speech_level.py on
    # winipi5): a 0.024 capture-chain noise floor, speech at its measured p50 of
    # 0.076. This is the case the shipped constants are tuned for.
    ok &= _run("winipi5 measured floor + measured speech",
               [(1.0, 0.024), (2.0, 0.076), (6.0, 0.024)],
               expect_reason="silence", max_capture_ms=3400)

    # Same floor, a QUIET child — and shaped like speech rather than a flat
    # tone: syllable onsets are several times the sentence's own median, and
    # they are what an energy gate actually latches on. A flat-RMS "quiet child"
    # is a strictly harder signal than any real one.
    ok &= _run("winipi5 floor + quiet child (onset-shaped)",
               [(1.0, 0.024), (0.15, 0.110), (0.35, 0.038), (0.20, 0.095),
                (0.30, 0.040), (0.15, 0.085), (6.0, 0.024)],
               expect_reason="silence", max_capture_ms=2600)

    # LOUD ROOM. Measured on the device at floor 0.050 / p90 0.070 / peaks 0.095.
    # This is the case that killed an absolute start-gate cap: with the gates
    # pinned at 0.045 they sat UNDER the room, so the room was heard as endless
    # speech and the turn ran to the 15 s cap. Floor-relative gates ride up with
    # the room and still endpoint.
    ok &= _run("loud room still endpoints",
               [(1.0, 0.050), (2.0, 0.200), (6.0, 0.050)],
               expect_reason="silence", max_capture_ms=3400)

    # ...and the same loud room with NOBODY speaking must start no turn at all.
    from wini_client import client as _c
    _c._vad_noise = 0.005
    _install_fake_sd(_profile(30, (12.0, 0.050)), 480)
    idle = _c.record_utterance(wait_for_speech_s=6.0)
    print(f"{'PASS' if idle is None else 'FAIL'}  loud room alone starts no turn:"
          f" {getattr(_c.record_utterance, 'last', {}) if idle else None}")
    ok &= idle is None

    # The seeding trap: _vad_noise starts BELOW this room's floor. If the floor
    # were only EMA'd toward, the stop gate would sit under the room and the turn
    # would run to the hard cap — the original bug, re-created on turn one.
    ok &= _run("floor is measured, not just seeded",
               [(0.5, 0.030), (1.5, 0.090), (6.0, 0.030)],
               expect_reason="silence", max_capture_ms=3000)

    # A soft child. 0.014 is BELOW the old fixed gate — it would never have
    # started a turn at all; the adaptive gate hears it over a 0.003 floor.
    ok &= _run("quiet room, soft speech",
               [(1.0, 0.003), (2.0, 0.014), (6.0, 0.003)],
               expect_reason="silence", max_capture_ms=3400)

    # Pauses mid-sentence must NOT split the utterance: a 400 ms gap is shorter
    # than the 700 ms hangover, so all of it is one turn.
    ok &= _run("pause mid-sentence stays one turn",
               [(1.0, 0.010), (1.5, 0.080), (0.4, 0.010), (1.5, 0.080),
                (6.0, 0.010)],
               expect_reason="silence", max_capture_ms=5000)

    # A click/thump shorter than VAD_MIN_SPEECH_MS must not latch a turn: the
    # wait window expires and we return None (the loop re-listens).
    from wini_client import client
    client._vad_noise = 0.005
    _install_fake_sd(_profile(30, (0.06, 0.20), (4.0, 0.004)), 480)
    got = client.record_utterance(wait_for_speech_s=3.0)
    print(f"{'PASS' if got is None else 'FAIL'}  click alone starts no turn: {got!r}")
    ok &= got is None

    # Continuous loud noise still bails at the hard cap rather than hanging.
    ok &= _run("runaway hits the hard cap",
               [(1.0, 0.010), (30.0, 0.120)],
               expect_reason="hard_cap", max_capture_ms=15100)

    print("ALL PASS" if ok else "FAILURES ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
