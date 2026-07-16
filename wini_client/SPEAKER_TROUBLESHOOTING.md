# Wini Speaker Troubleshooting (winipi5 / reSpeaker Lite)

*Written 2026-07-16, after diagnosing "the screen paints the answer but I hear
nothing" on the Raspberry Pi 5 thin client.*

## TL;DR

The reSpeaker Lite is **one USB device with one playback substream and one
capture substream**. Exactly **one process may own the playback side**. Silence
almost always means someone else (usually PipeWire, on behalf of `wini_ui`'s
SDL audio) is holding `/dev/snd/pcmC2D0p` when the client tries to speak.

**Rules that keep it working:**
1. The **client owns the speaker exclusively**. `wini_ui` now **defaults its own
   SDL audio to the dummy driver** (main.c, unless `WINI_UI_AUDIO=1`), and the
   launcher (`run_wini_package.sh`) + supervisor `--ui` mode also export
   `SDL_AUDIODRIVER=dummy` — so no launch path can claim the playback PCM.
2. The client **primes the output stream before the first mic open**
   (`prime_output()` at the top of `run_session`) and keeps it open for the
   life of the process.
3. Any process that opened the output stream must **release it on exit**
   (the client registers `atexit(_close_out_stream)`); a leaked handle
   silences the *next* client launch.

## Symptoms → causes

| Symptom (in `logs/client.log`) | Cause |
|---|---|
| `output prime deferred (no usable output stream configuration)` at startup | Playback PCM already held by another process — check `fuser -v /dev/snd/pcmC2D0p`. If it's `pipewire`, `wini_ui` (SDL audio) is holding it: relaunch the UI with `SDL_AUDIODRIVER=dummy`. |
| `persistent playback failed ... fallback playback also failed (Error querying device -1)` per turn | Same as above, or a previous client died without releasing the stream (fixed by the `atexit` guard; a SIGKILL'd process still leaks until the kernel reaps it). |
| Silence but **no** errors in the log | Physical: speaker cable on the reSpeaker's speaker header, or volume. There is **no ALSA mixer** on this card (`amixer -c 2` shows no volume controls) — level is set in software only. |
| `sd.query_devices()` shows `out 0` or default `[-1,-1]` | The device is wedged from ownership contention. Kill every holder (`fuser -k` or stop client+UI), wait ~3 s; it recovers without a reboot or replug. |

## Quick diagnosis (over SSH, from the repo root)

```bash
# 1. Who holds the speaker? (should be the client's python, or nobody)
fuser -v /dev/snd/pcmC2D0p    # playback
fuser -v /dev/snd/pcmC2D0c    # capture

# 2. Does PortAudio see a playback device? (want: "out 2")
.venv/bin/python -c "import sounddevice as sd; d=sd.query_devices(0); \
print(d['name'], 'in', d['max_input_channels'], 'out', d['max_output_channels'])"

# 3. Play a test tone through the exact client path (must be audible)
.venv/bin/python -c "
import sys, numpy as np; sys.path.insert(0,'.')
from wini_client import client
t=np.linspace(0,1,24000,endpoint=False)
client.play_pcm((0.7*np.sin(2*np.pi*440*t)*32767).astype(np.int16).tobytes(),24000)"
```

Healthy state while a session runs: **both** `pcmC2D0p` and `pcmC2D0c` held by
the **same client PID** (single-owner full-duplex), and `grep -c 'playback
failed' logs/client.log` returns 0.

## Correct launch order

```bash
# brain
set -a; . ./.env; set +a
GEN_BACKEND=gemini .venv/bin/python wini_server.py --port 8123 &

# client — owns mic + speaker; primes output on session start
.venv/bin/python -u -m wini_client.client --server http://127.0.0.1:8123 \
  --display lvgl --ui-port 8140 --wait-for-mode --on-session-end exit &

# UI — audio DISABLED so it never steals the speaker
SDL_AUDIODRIVER=dummy DISPLAY=:0 ./wini_ui/build/wini_ui --port 8140 &
```

(The supervisor's `--ui` mode should export `SDL_AUDIODRIVER=dummy` when it
spawns `wini_ui` for the same reason.)

## What was changed in code (2026-07-16)

- `wini_client/client.py`
  - `prime_output()` — opens the persistent output stream **before** the first
    mic open; called at the top of `run_session()`. Output-first is what lets
    mic + speaker coexist on the single-PCM reSpeaker.
  - `_out_device_and_rate()` — resolves a *playback-capable* device by scanning
    `max_output_channels`, instead of trusting `sd.default.device[1]`, which
    transiently reads `-1` on this card; the old code then fell back to
    48 kHz, a rate the 16 kHz-only device rejects, so every open failed.
  - `_ensure_out_stream()` — tries the resolved device index at the TTS rate
    and its native rate (play_pcm resamples 24 k→16 k), with default-device
    fallbacks.
  - `atexit.register(_close_out_stream)` — always releases the speaker on exit
    so an unclean death can't silence the next launch.
- `wini_ui` beep cues are sacrificed (dummy audio). If UI cues are ever
  needed, route them **through the client** (a `{"event":"cue",...}` line on
  the mode channel) rather than giving the UI its own audio device.

## Known trade-offs

- UI sound effects (listen/correct/celebrate cues) are silent — the speaker is
  reserved for Wini's voice.
- Bare-SSH sessions have no PulseAudio/PipeWire route for PortAudio anyway
  (`device='pulse'` never matches); everything runs against raw `hw:2,0`,
  which is exactly why single ownership matters.
