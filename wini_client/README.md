# Wini thin client

The device side of the Wini split. The device is a **platform** — mic in, speaker
out, display, (optional) touch — and nothing else. All intelligence (wakeword-free
turn taking, Cloud STT, the tutor brain with Gemini perception + generation, Cloud
TTS, figure selection) lives behind the brain service (`wini_server.py`), which runs
on the Jetson today and on Cloud Run later **without changing this client**.

```
mic ─► RMS endpoint ─► POST /voice_turn (raw PCM16 @16 kHz) ─► brain service
                                                                    │
display ◄─ metadata {image_path, alt_text} ◄────────────────────────┤
speaker ◄─ audio_b64 (LINEAR16 PCM @24 kHz) ◄───────────────────────┘
```

## Dependencies (keep it this small)

| dep | why |
|---|---|
| `numpy` | RMS energy + PCM buffers |
| `sounddevice` | mic + speaker (PortAudio) |
| `requests` | the HTTP contract |

Display sinks may add **platform-local** extras (Jetson ROS sink: `rclpy` + `cv2`,
already on the board). The client imports them lazily — a device without them still
runs audio-only.

## Run

```bash
# Jetson (server on the same board, SPI panel):
python -m wini_client.client --display ros --store "/home/roavai/ROS2WS_audio_pipeline/cloud CLI/rag_store"

# any laptop, audio only, brain elsewhere:
WINI_SERVER=http://<brain-host>:8123 python -m wini_client.client --display console

# smoke test without a mic (full output path: display + spoken audio):
python -m wini_client.client --display console --once-text "show me the graph of a quadratic polynomial"
```

Triggers: `--trigger vad` (default, always-listening RMS endpointing) or
`--trigger enter` (push-to-talk). A **touch sensor** trigger is the `enter` shape:
replace the blocking wait with the GPIO/touch callback.

## HTTP contract (what a new device must speak)

- `GET /health` → `{"ready": true, "gen_backend": "gemini"}` — poll until ready.
- `POST /voice_turn` — body: raw **LINEAR16 mono int16 PCM**, header
  `X-Sample-Rate: 16000` → **NDJSON stream** (one JSON object per line, HTTP/1.0
  close-delimited). An early line arrives as soon as STT + perception finish —
  seconds before the answer — so the device can react while the brain generates:

```json
{"part": "filler", "transcript": "show me the graph ..."}
```

  (When spoken fillers are enabled server-side with `WINI_FILLERS=1`, this line also
  carries `filler`/`bank` text and `audio_b64`/`audio_rate` to play immediately. The
  Jetson rig keeps them OFF and shows a thinking face instead — see below.)

  Then, with streaming on (Part 13, default), the turn's UI metadata and the answer's
  audio arrive **incrementally** — this is what makes Wini start speaking in ~3-4 s
  instead of ~10-20 s:

```json
{"part": "turn_meta", "answer": "...", "display": [...], "mode": "EXPLAIN", ...}
{"part": "audio", "seq": 0, "audio_b64": "<base64 PCM>", "audio_rate": 24000}
{"part": "audio", "seq": 1, "audio_b64": "...", "audio_rate": 24000}
```

  A device must:
  - play `audio` parts **in `seq` order**, writing into one persistent output stream
    (per-chunk open/close clicks on cheap USB codecs; per-chunk fades dip audibly —
    fade in on the first chunk and out on the last, not in between);
  - keep its "speaking" state (TTS-exclusivity for touch/emotion sounds) across the
    **whole** chunk sequence, not per chunk;
  - tolerate `audio` arriving **before** `turn_meta`. With streamed generation speech
    starts before the turn is fully decided, so either order is legal.

  The **last line** is the full turn. It still carries the complete `audio_b64` so a
  non-streaming reader that parses only this line works unchanged — but when
  `"audio_streamed": true` is present a streaming client **must not** play it again:



```json
{
  "transcript": "show me the graph ...",
  "answer": "Look at the figure on the screen. ...",
  "display": [{"image_path": "figure_crops/jemh102/fig_jemh102_fig_2_2.png",
               "alt_text": "...", "figure_id": "fig::jemh102::fig_2_2"}],
  "audio_b64": "<base64 LINEAR16 PCM>", "audio_rate": 24000,
  "session_ended": false,
  "action": "REPRESENTATION_TRANSLATION", "concept": "...", "latency_ms": {"stt": 900, "brain": 1300, "tts": 1800}
}
```

  A reader that ignores `"part"` lines and parses only the final line still gets the
  whole turn (that is how `curl | tail -1` behaves).

- `POST /turn` — `{"text": "...", "speak": true}` → single JSON object (test path).
- Empty `transcript` ⇒ STT heard nothing: re-listen, don't speak.
- `session_ended: true` ⇒ the farewell in `audio_b64` is the last clip. With
  `--on-session-end exit` (the Jetson default via `run_thin.sh`) the client process
  exits — "bye" puts the device to sleep, and the chin-hold trigger restarts it.
  Default (`listen`) just returns to idle listening.

## Turn-phase display cue (thinking face)

Around every voice turn the client signals the platform: **thinking starts** when the
utterance is POSTed and **stops** when the answer audio arrives, so the face can look
"thinking" during the dead air and return to the prior emotion while speaking. On the
Jetson this is the `/wini/thinking` Bool topic (rendered by
`jetson_platform/wini_touch_trigger.py` as `CONFUSED 8` + wandering up-gaze); other
platforms implement `sink.thinking(bool)` however they like (`NullSink` ignores it).

## Porting to a new device (ESP32 etc.) — the four seams

1. **Mic**: capture 16 kHz mono int16; endpoint on RMS energy (~40 lines here —
   `record_utterance`); stream the buffer as the POST body.
2. **Speaker**: play the returned 24 kHz PCM. Never record while playing
   (half-duplex is the loop's shape, not a feature).
3. **Display**: `display[].image_path` is a **stable image ID**. The device keeps
   its own copy of `rag_store/figure_crops/` (SD card, pre-scaled for its panel if
   needed) and blits by ID. Unknown ID ⇒ keep the face. Show before speech, clear
   after. No pixels ever cross the network.
4. **Trigger**: VAD, a button, or a touch sensor — anything that starts a capture.

There is no wakeword and no local model of any kind in this package.
