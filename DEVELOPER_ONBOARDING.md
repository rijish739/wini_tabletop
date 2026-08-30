# Wini — Developer Onboarding

The shortest path from *no access* to *it runs on your machine*. For system
architecture start at [`docs/architecture/WINI_ARCHITECTURE.md`](docs/architecture/WINI_ARCHITECTURE.md); for the
full brain/device install see [`docs/runbooks/NEW_MACHINE_SETUP.md`](docs/runbooks/NEW_MACHINE_SETUP.md).
This page ties those together and gets a new developer productive fast.

---

## 1. Get access (the repo is PRIVATE)

- Repo: **https://github.com/rijish739/wini_tabletop**
- Ask the owner to add you as a collaborator (repo **Settings → Collaborators**). A link alone will not clone a private repo — you need to be granted access first.
- Authenticate git one of two ways:
  - **HTTPS** — use a GitHub Personal Access Token as the password when prompted.
  - **SSH** — add your public key to GitHub, then clone the `git@github.com:` URL.

## 2. Clone

```bash
git clone https://github.com/rijish739/wini_tabletop.git
cd wini_tabletop
```

The default branch holds the active codebase.

## 3. Pick your track

| You want to… | Go to |
|---|---|
| Run the **thin client / platform on your laptop** (no hardware) | **§4 below** — fastest |
| Run/develop the **brain** (`cloud_run_service`: perception, safety, pedagogy, evals) | [`docs/runbooks/NEW_MACHINE_SETUP.md`](docs/runbooks/NEW_MACHINE_SETUP.md) **Profile A** |
| Deploy the **device** (mic/speaker/display/touch on Jetson / Pi) | [`docs/runbooks/JETSON_PIPELINE_RUNBOOK.md`](docs/runbooks/JETSON_PIPELINE_RUNBOOK.md) + [`wini_platform/README.md`](wini_platform/README.md) |

## 4. Fast start — ROS-less platform on a laptop (no hardware)

`wini_platform` is the device orchestrator; the only hardware-bound parts (the
SPI panel and the STM32 touch board) are bypassed with `--fake-display` and
`--no-touch`, and audio auto-falls back to your OS default mic/speaker. Full
detail: [`wini_platform/README.md`](wini_platform/README.md) → "Running on
another OS".

**Prerequisites:** Python 3.10+ and the PortAudio runtime for `sounddevice`
(**Windows:** bundled in the wheel; **macOS:** `brew install portaudio`;
**Linux:** `sudo apt install libportaudio2`).

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r wini_platform/requirements.txt      # cross-OS core only
```

Then either **A** point at an existing brain, or **B** run the brain locally:

```bash
# A) reach a brain someone else is already running (or a Cloud Run URL):
python -m wini_platform --fake-display --no-touch --autostart --server <brain-url>

# B) run the brain locally too (needs Google Cloud creds — see below):
pip install -r requirements-cloud.txt
pip install google-cloud-speech google-cloud-texttospeech torch sentence-transformers opencv-python
#   ... create .env + `gcloud auth application-default login` (docs/runbooks/NEW_MACHINE_SETUP.md §2)
python cloud_run_service/wini_server.py --port 8123      # terminal 1 (ready after ~40 s)
python -m wini_platform --fake-display --no-touch --autostart \
       --server http://127.0.0.1:8123                    # terminal 2 — then just talk
```

Nothing installed, no brain, no hardware — just see the face render:

```bash
python -m wini_platform.display.demo --fake
```

## 5. What the clone does NOT include (bring your own)

- **`.env`** (Google Cloud project/region) and **ADC credentials** — gitignored;
  the brain needs them. Get them from the owner over a secure channel, or set up
  your own project per [`docs/runbooks/NEW_MACHINE_SETUP.md`](docs/runbooks/NEW_MACHINE_SETUP.md) §2.
  Generation/perception are cloud-only — there is no offline brain.
- **SPI-panel / STM32 deps** (`wini_platform/requirements-device.txt`) — install
  only on a Jetson / Raspberry-Pi-class board with the real hardware.
- **Learner data** (`learner_state.json`, logs, `safety_alerts.jsonl`) — a fresh
  deployment starts clean.

## 6. Repo map (the running system)

| Path | Role |
|---|---|
| `cloud_run_service/` | **Canonical Modular Brain** — Cloud STT → Intake → Safety → Perception & Pedagogy → Generation → Cloud TTS. |
| `wini_platform/` | **Tabletop device platform** — display + touch + in-proc client for physical hardware. |
| `wini_client/` | Thin-client library (mic → brain → speaker + display). CLI: `python -m wini_client.client`. |
| `wini_ui/` | Embedded LVGL C user interface client. |
| `rag_store/` | NCERT Class 10 Knowledge store + figure crops + page images. |
| `dataset/`, `models/` | Training exemplars, gold datasets, and MiniLM / HOPE models. |
| `docs/` | Architecture specifications, safety & privacy contracts, runbooks, and historical archives. |

---

Questions the docs don't answer → ask the owner. Welcome aboard.

