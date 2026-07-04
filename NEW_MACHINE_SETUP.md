# Wini — New Machine Setup Guide

How to bring the **overall system** up from a fresh clone, on either kind of machine:

- **Profile A — brain / dev machine**: runs `wini_server.py` (Cloud STT → TutorLoop
  with Gemini perception + generation → Cloud TTS), the evals, and the text/voice test
  rigs. Windows or Linux. This is also what a Cloud Run container needs.
- **Profile B — device (platform client)**: mic + speaker + display + touch. Today the
  Jetson Orin Nano (`JETSON_PIPELINE_RUNBOOK.md`); target ESP32-P4. Runs
  `wini_client/` + the display/touch platform, talks to a Profile-A brain over HTTP.

One box can be both (the Jetson currently is). Written 2026-07-04.

---

## 0. What you need before starting

| Item | Notes |
|---|---|
| Python 3.10+ | 3.10 is what both current machines run |
| A Google Cloud project | with billing; the pipeline is Vertex Gemini + Cloud STT/TTS (CLAUDE.md hard mandate — there is no offline mode for generation/perception) |
| `gcloud` CLI | for Application Default Credentials (ADC) |
| This repo | includes the runtime artifacts: `rag_store/` (chunks, graph, figure crops), `models/` (MiniLM heads, resolver, policy), `perception/build/` (schema + cached prompt block), `dataset/exemplar_dataset_10000_fixed.json` (canonical dataset) |
| Secrets — NOT in git | `.env` (see §2) and ADC json. Copy them over a secure channel, never commit them |

## 1. Clone + Python environment (both profiles)

```bash
git clone https://github.com/jainprathwi-stack/cloud-CLI.git "cloud CLI"
cd "cloud CLI"
python -m venv .venv
# Windows: .venv\Scripts\activate      Linux: source .venv/bin/activate
pip install -r requirements.txt              # core: genai, numpy, faiss, networkx, ...
# brain-side extras (Profile A, and today's Jetson which hosts the brain too):
pip install google-cloud-speech google-cloud-texttospeech    # Cloud STT / TTS
pip install torch sentence-transformers                       # MiniLM retrieval + HOPE
pip install opencv-python                                     # T9 figure handling
# client/voice extras (any machine with a mic/speaker or display):
pip install sounddevice
```

Versions known-good on the Jetson (2026-07-04): `google-genai 2.10.0`,
`google-cloud-speech 2.40.0`, `google-cloud-texttospeech 2.37.0`,
`sentence-transformers 5.5.1`, `torch 2.10.0`, `sounddevice 0.5.5`.

## 2. Google Cloud auth + environment

```bash
gcloud auth application-default login        # writes the ADC json
gcloud config set project <PROJECT_ID>
gcloud services enable aiplatform.googleapis.com speech.googleapis.com \
                       texttospeech.googleapis.com
```

Create `.env` in the repo root (keys used today; values are per-project):

```
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=<project-id>
GOOGLE_CLOUD_LOCATION=asia-south1
VERTEX_REGION=asia-south1
```

**Gotchas that bite every new machine** (verified, from CLAUDE.md):

- `GEN_BACKEND=gemini` must be a **real environment variable**, not only a `.env`
  line — `tutor_loop` reads it before dotenv loads. Export it in the shell profile /
  service unit that launches the server.
- Headless boxes: copy `~/.config/gcloud/application_default_credentials.json` from a
  machine where the browser login ran (this is exactly how the Jetson was set up).
- Client construction (`genai.Client`, STT/TTS clients) is the ~4–9 s cold-start cost,
  not the calls — services build clients once per process (already the case in
  `wini_server.py`); don't "fix" slow first turns by rebuilding clients.
- Windows consoles are cp1252: set `PYTHONIOENCODING=utf-8` when printing dataset text.
- Never pass `n_jobs=-1` to sklearn OneVsRest on Windows (loky crash) — the shipped
  scripts are already sequential.

## 3. Profile A — brain / dev machine verification ladder

Run these in order; each step gates the next. All commands from the repo root, venv
active, `GEN_BACKEND=gemini` exported.

| # | Command | Expect / notes |
|---|---|---|
| 1 | `python verify_store.py --fail-under 90` | store scorecard ≥ 90 — proves `rag_store/` artifacts are intact |
| 2 | `python -m perception.test_perception` | offline gate + belt tests pass (no billing) |
| 3 | `python -m perception.test_perception --integration` | first BILLED call; proves ADC + Vertex region work end-to-end |
| 4 | `python tutor_loop.py --once "explain zeroes of a quadratic polynomial"` | a grounded answer; perception route + retrieval + generation |
| 5 | `python wini_server.py --port 8123` then `curl http://127.0.0.1:8123/health` | `ready:true` after ~40 s warmup (TutorLoop + MiniLM load + client warmup) |
| 6 | `curl -s -X POST http://127.0.0.1:8123/turn -H "Content-Type: application/json" -d "{\"text\": \"show me the parabola graph\", \"speak\": false}"` | turn JSON with `display[].image_path` metadata (T9) |
| 7 | `python -m wini_client.client --display console --once-text "show me the graph of a quadratic polynomial"` | full client output path without any hardware |
| 8 | (mic test) `python -m wini_client.client --display console` | speak; expect transcript → answer → spoken reply |

Optional (perf): create the perception context cache —
`python -m perception.vertex_cache --create --ttl-hours 24` (recreate after
`python -m perception.build_perception` or TTL expiry; calls fall back to the full
prompt automatically if absent).

Rebuild commands, evals, and the dataset/splits rules live in CLAUDE.md ("Quick
commands") — do not re-derive them here.

## 4. Profile B — device (platform client)

The device needs: the study core (for `wini_client/` + `rag_store/figure_crops/`), audio
I/O, and its display/touch platform. Today that platform is the ROS 2 stack documented
in `JETSON_PIPELINE_RUNBOOK.md`; the planned replacement is
`WINI_ROSLESS_PLATFORM_PLAN.md`. This section covers what is common + where each path
forks.

### 4.1 Common (any device)

1. Copy/clone the study core onto the device (Jetson path:
   `~/ROS2WS_audio_pipeline/cloud CLI`). Runtime needs: `wini_server.py`,
   `wini_client/`, `tutor_loop.py`, `perception/`, `voice/`, `pacing/`,
   `cognitive_*/`, `concept_resolver/`, `query.py`, `llm_vertex.py`, `persona.json`,
   `rag_store/`, `models/`, `learner_state.json`, `.env`.
2. Python deps as §1 (the Jetson venv uses `--system-site-packages` because ROS needs
   it; the ROS-less plan drops that).
3. ADC json + `.env` + `export GEN_BACKEND=gemini` (on the Jetson this lives in
   `~/wini_pipeline_test_env.sh`).
4. **Audio**: pin the USB mic/speaker as PulseAudio defaults. On the Jetson:
   `bash ~/ROS2WS_audio_pipeline/select_usb_audio.sh` (runbook §4) — the onboard card
   re-grabs the default, so launchers also export `PULSE_SINK`/`PULSE_SOURCE` and the
   client opens streams with `device="pulse"`.
5. Network: the device's network must reach Vertex/Cloud APIs (the phone-hotspot LAN
   the Jetson uses does).

### 4.2 Today's Jetson bring-up (ROS platform)

On-device pieces and their repo copies (deploy = `scp` + restart, runbook §10):

| On device | In repo |
|---|---|
| `~/run_thin.sh`, `~/run_client.sh`, `~/run_boot_platform.sh`, `~/wini_touch_trigger.py`, `~/wini_loading_text.py` | `jetson_platform/` |
| `~/Downloads/ros2_ws` display + head-bridge sources | `jetson_platform/device_snapshot/` (reference snapshot, 2026-07-04) |

Boot flow (installed via `crontab -e` → `@reboot bash /home/roavai/run_boot_platform.sh
>> /home/roavai/wini_test_logs/boot.log 2>&1`):

1. Power on → display node (face) + head node (touch) + touch-trigger node start.
2. **Hold the CHIN sensor ≥ 3 s** → "Loading…" card → `run_thin.sh` (server + client)
   → "Ready!" after ~40 s → talk to Wini.
3. During each turn the face shows the **thinking animation** (`CONFUSED 8` + wandering
   gaze via `/wini/thinking`); figures appear per the T9 display channel.
4. Say **"bye"** → farewell → client exits (sleep; mic off; brain stays warm).
5. **Hold CHIN again** → fast wake (~3–5 s, client-only restart via `run_client.sh`).
   A chin hold while everything is running just flashes "Wini is awake!" (idempotent).

Verify after boot: `pgrep -af "wini_display|wini_head_node|wini_touch_trigger"`, then
the §3 rows 5–7 against `http://127.0.0.1:8123`. Full troubleshooting table: runbook §12
(+ §15.3 thin-mode gotchas). SSH quirks (detached launches, quoting): runbook §2 —
read it before automating anything over SSH.

### 4.3 Future device (ROS-less / ESP32)

Follow `WINI_ROSLESS_PLATFORM_PLAN.md`. The HTTP + display-metadata contract is
identical (`wini_client/README.md` documents it, including the NDJSON voice-turn
stream, `--on-session-end exit` sleep, and the 4 porting seams); the ESP32 keeps
`figure_crops/` on its SD card and looks images up by `image_path` (runbook §14.3).

## 5. Secrets & privacy checklist when provisioning

- `.env`, ADC json: copy securely, never commit (`.env` is gitignored).
- `learner_state.json` and `rag_store/learning_log.jsonl` carry a real learner's
  session history — treat machines holding them accordingly; a brand-new deployment
  can start from the committed state or reset it deliberately.
- `rag_store/safety_alerts.jsonl` (safety-gate hits) is deliberately NOT committed.
