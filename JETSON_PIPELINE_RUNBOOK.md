# Wini Jetson Pipeline — Operations Runbook

End-to-end guide for the Wini voice + display pipeline running on the **Jetson Orin Nano**:
how to connect, how to run commands over SSH **reliably** (this is the part that bites you),
how to bring the whole system up, how to push images to the display, how to pin the USB
mic + speaker, and how to edit on-device code without corrupting it.

> The on-device code is **not** in this git repo. The Jetson holds a flat copy of the study
> core (`wini_core` → `cloud CLI`) plus the ROS 2 packages, edited live via
> `--symlink-install`. Treat workspace→Jetson as a 3-way merge, never a blind copy.

---

## 0. System at a glance (THIN-CLIENT mode, default since 2026-07-03 evening)

```
USB mic ─► wini_client (RMS VAD, no wakeword) ──POST /voice_turn (raw PCM)──► wini_server.py
USB spkr ◄─ 24 kHz TTS audio (base64) ◄──┐                                    (Cloud STT →
SPI screen ◄─ wini_display_node ◄─ /wini/display/image ◄─ display METADATA ◄─┘ TutorLoop/Gemini
             (display_controll)      (client's ROS sink)   {image_path, alt_text}  → Cloud TTS)
```

- **Host:** Jetson Orin Nano, aarch64, JetPack R36, hostname `ubuntu`, login user `roavai`.
- **NOTHING model-shaped runs on the device for voice**: no wakeword, no local ASR, no
  local TTS, no local LLM. The device is a *platform* — mic, speaker, display, (future)
  touch — exactly the ESP32 shape. Turn taking is a simple RMS voice-activity endpoint
  in `wini_client` (numpy, ~40 lines).
- **Brain service** (`wini_server.py`, port 8123): Cloud STT (en-US + maths phrases) →
  TutorLoop (Gemini perception + generation, Part 11) → Cloud TTS (en-IN Chirp3-HD).
  Runs on the board today; the SAME file is the Cloud Run deployment later. MiniLM
  (retrieval + HOPE) lives inside the server, not the client.
- **Thin client** (`wini_client/`, deps: numpy + sounddevice + requests): records one
  utterance, POSTs raw PCM, shows the returned figure crop via its ROS display sink
  (SD-card image-ID contract, §14.3), plays the returned speech. See
  `wini_client/README.md` for the HTTP contract and the 4 porting seams.
- **One command brings everything up:** `bash ~/run_thin.sh` (see §15).
- **Legacy stacks** (kept on disk, not launched): the full local ROS pipeline
  (`run_pipeline.sh`: wakeword + fastwhisper + brain node + Kokoro, §5–§6) and the
  in-proc Qwen brain (`GEN_BACKEND=qwen`). GPU note: thin mode uses ~no VRAM.

---

## 1. Connecting to the Jetson

| | |
|---|---|
| **SSH by name (preferred, IP-independent)** | `ssh roavai@ubuntu.local` |
| SSH by current home-LAN IP | `ssh roavai@192.168.29.39` |
| SSH in hotspot mode | `ssh roavai@10.42.0.1` (joined to `Wini-Robot`; see §17) |
| Tailscale (often down) | `ssh roavai@100.86.185.10` |
| File copy | `scp localfile roavai@ubuntu.local:/home/roavai/` |

> **IP note (updated 2026-07-09):** prefer the mDNS name **`ubuntu.local`** — avahi
> is now enabled (§17), so it resolves to whatever address the board currently holds
> (home Wi-Fi, hotspot, anywhere) with no IP hunting. It works from Windows/macOS/Linux.
> Today the board is on home Wi-Fi **`ROAVAI Pvt Ltd` at `192.168.29.39`**; when it
> falls back to its own **`Wini-Robot`** hotspot it is the gateway **`10.42.0.1`**. The
> earlier `172.20.10.2` phone-hotspot address is stale. Cloud-brain mode (§14) needs the
> active network to have internet (Vertex + Cloud APIs) — the `Wini-Robot` fallback does
> **not**, which is what §17's provisioning portal is for.
>
> **scp with spaces** (the study core is `…/cloud CLI/…`): modern scp uses SFTP and drops
> the quote trick — stage to a space-free path (`scp x roavai@…:/home/roavai/x`) then
> `ssh … 'cp /home/roavai/x "…/cloud CLI/…"'`.

- Auth is **key-based** (`~/.ssh/id_ed25519` is in the Jetson's `authorized_keys`), so
  non-interactive `ssh`/`scp` work. Windows OpenSSH will **not** accept a password
  non-interactively — if the key ever breaks, re-bootstrap with `plink`/`paramiko`.
- Always pass `-o ConnectTimeout=12` so a dead link fails fast instead of hanging.
- `ROS_DOMAIN_ID` is unset (0); all workspaces share one DDS topic graph.

Quick liveness check:

```bash
ssh -o ConnectTimeout=8 roavai@ubuntu.local 'echo OK; hostname; uptime'
```

---

## 2. Running commands over SSH **reliably** (read this before automating)

The single biggest source of pain is launching long-running ROS nodes over SSH. Two rules:

### 2.1 Never background a process *and* poll it in the same SSH call

A command that does `nohup setsid ... & disown; sleep N; tail log` **intermittently returns
exit 255** (the SSH channel tears down while the detached child is still attached to it).
The child sometimes dies with it. Symptom: exit 255, empty/stale logs, node not running.

**Reliable pattern — a launcher script that returns immediately:**

1. Write a tiny `run_x.sh` *on the Jetson* that backgrounds the node and exits:

   ```bash
   #!/bin/bash
   nohup setsid bash -c "source /home/roavai/wini_pipeline_test_env.sh; exec <COMMAND>" \
       > /home/roavai/wini_test_logs/x.log 2>&1 < /dev/null &
   disown
   sleep 1; echo "launch done"
   ```

2. Launch it as its own short SSH call: `ssh ... 'bash /home/roavai/run_x.sh'`
3. **Poll the log in a separate SSH call.** Never tail in the launching call.

Key bits: `setsid` (new session, survives SSH hangup), `nohup`, `< /dev/null` (detach
stdin), `> log 2>&1` (so output survives a dropped session), `disown`, and a trailing
`echo` so the launcher exits 0.

### 2.2 Write outputs to log files, poll separately

Because any SSH call can drop, make every long action write to a file under
`~/wini_test_logs/` and read it back later. Poll readiness with a bounded loop:

```bash
ssh ... 'for i in $(seq 1 16); do
  grep -q "READY_STRING" /home/roavai/wini_test_logs/x.log && { echo READY; break; }
  sleep 10; done; tail -n 12 /home/roavai/wini_test_logs/x.log'
```

### 2.3 Quoting & backslashes (corrupts code silently)

- The command string is transported through JSON + the local shell + `ssh '...'`. **Double
  backslashes collapse** (`\\`→`\`) and break regex escapes (`\s`, `\(`, `\d`).
- **Single quotes inside `ssh '...'` terminate the quote.** If your remote snippet needs
  single quotes, you cannot wrap the SSH arg in single quotes.
- **Do not hand-edit on-device files that contain backslashes through a heredoc.** Instead:
  - write the file/patch **locally**, `scp` it, run it with `ssh host 'python3 /path'`; **or**
  - build any runtime backslash/newline with `chr(92)` / `chr(10)` so no literal backslash
    is ever typed (see §10).

---

## 3. Environment setup

Everything sources one prelude, `~/wini_pipeline_test_env.sh`:

```bash
export PATH=/usr/local/cuda-12.6/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda-12.6/lib64:$LD_LIBRARY_PATH
source /opt/ros/humble/setup.bash
source /home/roavai/ROS2WS_audio_pipeline/install/setup.bash      # audio pipeline workspace
source /home/roavai/Downloads/ros2_ws/install/setup.bash          # display workspace
export PYTHONPATH=$PYTHONPATH:/home/roavai/ROS2WS_audio_pipeline/.venv/lib/python3.10/site-packages
export PULSE_SINK=alsa_output.usb-C-Media_Electronics_Inc._USB_PnP_Sound_Device-00.analog-stereo-output
```

- **Both workspaces must be sourced** for `ros2 launch` to see `display_controll` (in
  `~/Downloads/ros2_ws`) *and* the audio packages (in `~/ROS2WS_audio_pipeline`).
- The venv has `system-site-packages=true`; it carries faster-whisper, kokoro-onnx,
  sounddevice, etc. faiss is intentionally **not** installed (the loop ranks with MiniLM).
- Audio packages are **`--symlink-install`**, so editing `src/.../*.py` is live after a node
  **restart** (a running Python process won't pick up the edit until relaunched).

Workspaces:

| Path | Contents |
|---|---|
| `~/ROS2WS_audio_pipeline/` | `src/`: wakeword_pkg, fastwhisper_pkg, wini_brain_pkg, wini_tts (+ retired intent/llm/aec). `wini_core` → `cloud CLI` study core. `.venv`. `select_usb_audio.sh`. |
| `~/Downloads/ros2_ws/` | `display_controll` (SPI screen), plus unrelated nav/slam packages. |
| `~/wini_test_logs/` | All run logs + tuning wavs/frames. |

---

## 4. USB mic + speaker as default audio

The board has the **USB PnP Sound Device** (C-Media / TI PCM2902, ALSA `card 0`, `hw:0,0`)
*and* the onboard Tegra `platform-sound` card. The onboard card keeps **grabbing the
PulseAudio default**, which silently routes audio to a port with no speaker → "no sound".

### 4.1 One script does it: `select_usb_audio.sh`

```bash
bash ~/ROS2WS_audio_pipeline/select_usb_audio.sh
```

It finds the USB sink + source by the `usb-C-Media` substring, sets them as the PulseAudio
**default sink and source**, and moves any live streams onto them. With `--export` it prints
`export PULSE_SINK=...` / `PULSE_SOURCE=...` to also pin a specific shell's clients:

```bash
eval "$(bash ~/ROS2WS_audio_pipeline/select_usb_audio.sh --export)"
```

This script is **run automatically first by the unified launch** (§5), so normally you don't
call it by hand.

### 4.2 Why not address the USB device directly?

- PortAudio opening the raw `hw:0,0` at Kokoro's 24 kHz fails with `paInvalidSampleRate`
  (the codec doesn't do 24 kHz natively). **Route through PulseAudio**, which resamples.
- ALSA's `default` PCM is pinned to the onboard `hw:APE,0` in `/etc/asound.conf`, so neither
  ALSA-default nor PA-default reaches the USB card until `select_usb_audio.sh` runs.
- TTS uses `output_device='pulse'`; with PA default (or `PULSE_SINK`) on the USB sink it
  plays out the USB speaker. Mic nodes open the default **source** (USB after the script).

### 4.3 Verify

```bash
pactl info | grep -E "Default Sink|Default Source"   # both should say ...usb-C-Media...
aplay -l                                             # card 0 = USB PnP Sound Device
# quick tone to the USB speaker:
python3 -c "import numpy as np,sounddevice as sd; t=np.linspace(0,.6,14400,False); \
sd.play((.2*np.sin(2*np.pi*440*t)).astype('float32'),24000,device='pulse',blocking=True)"
```

---

## 5. Bring up the whole system (one command)

> **LEGACY (2026-07-03):** this section describes the retired full-local ROS pipeline
> (wakeword + fastwhisper + brain node + Kokoro). The current bring-up is
> `bash ~/run_thin.sh` (§15). Kept for reference / fallback.

```bash
bash ~/run_pipeline.sh
```

`run_pipeline.sh` stops any stale nodes, sources both workspaces, and runs the **single
unified launch file** `wini_pipeline.launch.py`, which starts **everything**:

| Order | Action | Notes |
|---|---|---|
| 1 | `select_usb_audio.sh` (ExecuteProcess) | pins USB as default mic + speaker |
| 2 | `wini_display_node` | SPI face/figure screen (no mic dep → starts immediately) |
| 3 (after 2.5 s) | `wakeword_node` | openWakeWord "weenee" |
| 3 | `fastwhisper_node` | small.en, CUDA, int8_float16 |
| 3 | `wini_brain_node` | TutorLoop + cloud Gemini (Vertex clients warm in ~6 s; `GEN_BACKEND=qwen` restores the ~50 s in-proc Qwen pre-warm) |
| 3 | `wini_tts_node` | Kokoro `af_heart`, teaching-tuned |

Wait for readiness, then check (separate call):

```bash
ssh ... 'grep -iE "Wini Brain ready|Wini TTS ready|Whisper Model loaded|Say: weenee" \
  /home/roavai/wini_test_logs/pipeline.log | tail -8'
ssh ... 'source ~/wini_pipeline_test_env.sh; ros2 node list'
```

Stop everything:

```bash
ssh ... 'pkill -f "wakeword_node|fastwhisper_node|brain_node|wini_tts_node|wini_display"'
```

> The launch file is at `~/ROS2WS_audio_pipeline/src/wini_brain_pkg/launch/wini_pipeline.launch.py`
> and is reached by `ros2 launch` via the symlink-install chain. Old versions are backed up
> under `~/ROS2WS_audio_pipeline/_wini_backups/`.

---

## 6. Runtime topic graph & conversation state machine

| Topic | Type | From → To | Meaning |
|---|---|---|---|
| `/wake_word` | Bool | wakeword → fastwhisper, brain | "weenee" detected |
| `/session_active` | Bool | fastwhisper → wakeword, brain | a listening session is open |
| `/speech_text` | String | fastwhisper → brain | one recognized utterance |
| `/llm_out` | String | brain → tts | one reply sentence |
| `/tts_done` | Bool | brain → tts | end of reply (release gate after playback) |
| `/robot_speaking` | Bool | brain True / tts False | **half-duplex mic gate** |
| `/wini/display/image` | Image | brain → display | figure crop to show (§7) |
| `/wini/emotion`, `/wini/eyes_target` | String, Point | → display | face emotion / gaze |

**Lifecycle (verified):**

1. User says **"weenee"** → `wakeword_node` fires `/wake_word`.
2. `wini_brain_node` says **"Hi!"** (audible ack); `fastwhisper_node` opens a session and
   publishes `/session_active=True`.
3. **Wakeword self-gates** — the node keeps running but stops detecting while
   `/session_active` or `/robot_speaking` is True (no kill/relaunch, which would be slow).
4. FastWhisper takes the mic (RMS-VAD, multi-command), publishing each utterance to
   `/speech_text`; brain replies; TTS speaks (gating the mic via `/robot_speaking`).
5. After ~5 s of silence FastWhisper ends the session → `/session_active=False`.
6. Brain says **"Bye!"** on that True→False edge; once it finishes speaking the wakeword
   **re-arms**. Back to step 1.

Tunables: wakeword threshold `0.5` (`wakeword_node.py`); `silence_exit=5.0`,
`command_silence=2.0`, `max_command_duration=10.0` (`fastwhisper_node.py`).

---

## 7. Sending data to the display node

The SPI screen is the `display_controll` `wini_display` node. It shows the animated face by
default and overlays any image published to `/wini/display/image`.

### 7.1 Contract

| Field | Value |
|---|---|
| Topic | `/wini/display/image` |
| Type | `sensor_msgs/msg/Image` |
| Encoding | `rgb8` |
| Size | **480 × 320 (landscape)** — `width=480, height=320, step=1440` |
| Keepalive | publish **> 2 Hz** (the node reverts to the face if no frame for 0.5 s) |

The node ignores frames whose encoding ≠ `rgb8` or size ≠ 480×320, so match exactly.

### 7.2 Orientation: the panel mirrors **left–right** — pre-flip on the sending side

The physical panel renders **horizontally mirrored** (vertical is correct — it is *not* a
180° rotation and *not* a vertical flip). **Fix on the publisher only** — flip horizontally
before sending; the `display_controll` node is left untouched:

```python
canvas = cv2.flip(canvas, 1)   # horizontal mirror; panel un-mirrors it on screen
```

> This was nailed down with an on-screen calibration card (a labelled TOP/BOTTOM + an
> asymmetric "F"): rot180 → upside-down+backwards; no-transform → TOP correct but F
> backwards; `cv2.flip(.,1)` → fully upright. Keep `wini_display_cal.py` /
> `wini_display_crop.py` on the Jetson to re-verify if the panel is ever re-seated.

### 7.3 The brain does this automatically

`wini_brain_node._render_crop` loads the chosen figure crop (store-relative path), letterboxes
it onto a 480×320 black canvas (`cv2.resize` + center), applies `cv2.flip(.,1)`, and a 5 Hz
timer republishes it while Wini speaks; it clears on the `/robot_speaking` False edge.

### 7.4 Publish a standalone image (template)

```python
import numpy as np, cv2, rclpy, time
from rclpy.node import Node
from sensor_msgs.msg import Image

W, H = 480, 320
def render(path):
    bgr = cv2.imread(path, cv2.IMREAD_COLOR)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]; sc = min(W/w, H/h)
    nw, nh = max(1,int(w*sc)), max(1,int(h*sc))
    canvas = np.zeros((H, W, 3), np.uint8)
    y0, x0 = (H-nh)//2, (W-nw)//2
    canvas[y0:y0+nh, x0:x0+nw] = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(cv2.flip(canvas, 1))    # <-- horizontal flip

rclpy.init(); n = rclpy.create_node("img_pub")
pub = n.create_publisher(Image, "/wini/display/image", 10)
frame = render("/home/roavai/ROS2WS_audio_pipeline/cloud CLI/rag_store/figure_crops/jemh102/fig_jemh102_fig_2_2.png")
m = Image(); m.height=H; m.width=W; m.encoding="rgb8"; m.is_bigendian=0; m.step=W*3; m.data=frame.tobytes()
while rclpy.ok():        # keepalive at 5 Hz so it stays up
    pub.publish(m); time.sleep(0.2)
```

Figure crops live under `~/ROS2WS_audio_pipeline/cloud CLI/rag_store/figure_crops/`.

---

## 8. Sending & receiving on `/speech_text` (bypass the mic for testing)

To test brain → TTS → display without speaking, publish straight to `/speech_text` — this
skips wakeword + Whisper entirely:

```bash
ros2 topic pub --once -w 1 /speech_text std_msgs/msg/String \
  "{data: 'explain the zeroes of a quadratic polynomial'}"
```

- **`-w 1` (wait for 1 matching subscriber) is essential** — a fresh publisher's very first
  message is otherwise dropped by DDS discovery before the brain's subscription matches.
  (When publishing from a long-lived node, send one throwaway/empty message and wait ~2 s
  first.)
- The brain has **no wake gate on `/speech_text`** — any message triggers a turn — so this is
  a clean test injection point.
- To observe a turn, subscribe to `/llm_out` (reply sentences), `/robot_speaking` (True→False
  marks turn end), and `/wini/display/image` (figure frames). `wini_pipeline_test_driver.py`
  does exactly this over a batch of utterances and writes a JSON report.

---

## 9. TTS teaching tuning (Kokoro)

`wini_tts_node.py` is tuned for a Class-10 listener:

| Param | Value | Effect |
|---|---|---|
| `voice` | `af_heart` | warm, expressive US voice |
| `speed` | `0.85` | base/prose pace (slower than default 1.0) |
| `math_speed` | `0.70` | equations spoken slower than prose |
| `math_pause_ms` | `240` | short silence on each side of an equation |

Per sentence, `_synth_teaching` splits on the LLM's inline-math delimiters
(`\( ... \)`, `\[ ... \]`, `$...$`), speaks **prose at `speed`** and **equations at
`math_speed`** with pauses, then concatenates. `speak_math` spells math out:
`x^2`→"x squared", `=`→"equals", `/`→"over", `-`→"minus", `\frac{a}{b}`→"a over b",
`\sin`→"sine", `3x`→"3 x". The launch passes `voice: af_heart`; the speeds are node defaults
and are exposed as ROS params (override at launch without editing code).

Re-tune interactively with `~/run_tune.sh` (env vars `TUNE_VOICE / TUNE_BASE / TUNE_MATH /
TUNE_PAUSE_MS`, `TUNE_COMPARE=1` to A/B voices); wavs land in `~/wini_test_logs/tune/`.

---

## 10. Editing on-device code safely

The audio packages are symlink-install, so editing `src/.../*.py` then **restarting that
node** is enough (no rebuild). But the transport mangles backslashes (§2.3), so:

- **Preferred:** write the patch script **locally**, `scp` it, run it:
  `ssh host 'python3 /home/roavai/patch.py'`. In the patch, build any literal backslash with
  `chr(92)` and any newline in injected text with `chr(10)` — never type a literal backslash.
- Always **back up first**: `cp file ~/ROS2WS_audio_pipeline/_wini_backups/file.bak_$(date +%Y%m%d_%H%M%S)`.
- After editing, **restart the node** (a running Python process keeps the old code in memory):
  `pkill -f brain_node` then `bash ~/run_brain.sh` (or relaunch the whole pipeline).
- The study core (`tutor_loop.py`, `cues.py`, …) is `wini_core` → `cloud CLI`; the brain node
  imports it. It is the in-process llama.cpp branch — workspace↔Jetson is a 3-way merge.

---

## 11. Helper scripts on the Jetson (`~`)

| Script | Purpose |
|---|---|
| `run_pipeline.sh` | **Full system** bringup (mic-select + all nodes via the unified launch) |
| `run_tts_brain.sh` / `run_brain.sh` | restart just TTS+brain / just brain |
| `wini_pipeline_test_driver.py` + `run_driver.sh` | publish a batch of utterances to `/speech_text`, log replies/display/tim’g |
| `wini_display_cal.py` + `run_cal.sh` | calibration card to `/wini/display/image` (`none|rot180|flipud|fliplr`) |
| `wini_display_crop.py` + `run_crop.sh` | publish a real figure crop (with the flip) for a stable on-screen check |
| `wini_tts_tune.py` + `run_tune.sh` | Kokoro tuning harness (voice/pace A/B, plays on USB) |
| `wini_pipeline_test_env.sh` | the env prelude every script sources |
| `~/ROS2WS_audio_pipeline/select_usb_audio.sh` | pin USB as default mic+speaker |

All logs: `~/wini_test_logs/`. Backups: `~/ROS2WS_audio_pipeline/_wini_backups/`.

---

## 12. Troubleshooting

| Symptom | Check / fix |
|---|---|
| SSH command returns **255**, node not up | You backgrounded + polled in one call — use the launcher-script pattern (§2.1). Re-check with a fresh `pgrep -af`. |
| **No sound** | `pactl info \| grep Default` → both must be `...usb-C-Media...`. Run `select_usb_audio.sh`. TTS must use `output_device='pulse'`. |
| TTS `paInvalidSampleRate` | You pinned raw `hw:0,0`; route via `pulse` instead (§4.2). |
| **Works after a manual restart but NOT on a fresh boot** — brain/display/touch come up ("pipeline ready") but the mic client dies. Two distinct stages, fixed together: | Both are boot-only because a manual restart from an SSH shell inherits a warm, fully-set-up session. |
| &nbsp;&nbsp;① `Error opening InputStream: Invalid sample rate [-9997]` / `No input device matching 'pulse'` | Cron `@reboot` has **no login session** → `XDG_RUNTIME_DIR` unset → the ALSA `pulse` device can't find `/run/user/UID/pulse/native`, so the mic falls back to the onboard card and rejects 16 kHz. Fixed in `run_wini_platform.sh`: `export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"` + `DBUS_SESSION_BUS_ADDRESS`. (`pactl`/libpulse derive the path from the uid themselves, so `select_usb_audio.sh` still succeeds at boot — only the ALSA pulse plugin needs the var.) |
| &nbsp;&nbsp;② `PaAlsaStream_WaitForFrames … failed` → `Unanticipated host error [-9999]: 'Input/output error' [ALSA error -5]` | Even with pulse reachable, PulseAudio's USB source is still **settling** the instant a fast chin-hold starts the client; the first capture read EIOs and killed the session. Fixed in `supervisor._wait_capture_ready()`: it probes a one-block capture and retries (~1 s, up to 25 s) before `run_session`, so a cold source is waited out instead of fatal. A warm source passes on the first try. |
| Display shows **face only** | Publisher stopped (need >2 Hz keepalive), or wrong size/encoding (must be 480×320 rgb8). |
| Display **mirrored / upside-down** | Apply `cv2.flip(canvas, 1)` on the **sender** (§7.2). Re-verify with `run_cal.sh`. |
| First `/speech_text` publish ignored | DDS discovery drop — use `ros2 topic pub -w 1`, or warm up with a throwaway message. |
| Code edit "didn't take" | The node caches imported code — **restart the node** after editing. |
| OOM / VRAM | Cloud-brain mode (§14, the default) fits easily (~4.4 GB total). Only in legacy `GEN_BACKEND=qwen` mode does Qwen+Kokoro+Whisper ≈ 6–7 GB pinch — drop Whisper to `base.en` or run Kokoro on CPU. |
| Brain says "Vertex warmup failed" / turns error | The hotspot network lost internet, or ADC creds expired. Check `curl -sI https://asia-south1-aiplatform.googleapis.com` from the board and `~/.config/gcloud/application_default_credentials.json`. Turns degrade (gates + inherit-concept perception fallback) but generation needs the cloud. |
| Wakeword won't re-arm | It only re-arms when **both** `/session_active` and `/robot_speaking` are False; confirm the "Bye!" finished and the session closed. |

---

## 13. Quick reference

```bash
# connect
ssh -o ConnectTimeout=12 roavai@172.20.10.2

# bring up everything — THIN-CLIENT mode (mic-select + display + brain service + client)
ssh ... 'bash ~/run_thin.sh'
ssh ... 'tail -f ~/wini_test_logs/server.log ~/wini_test_logs/client.log'

# LEGACY full-local pipeline (wakeword + whisper + local brain + kokoro):
ssh ... 'bash ~/run_pipeline.sh'
ssh ... 'tail -f ~/wini_test_logs/pipeline.log'      # watch readiness

# verify audio routing
ssh ... 'pactl info | grep -E "Default Sink|Default Source"'

# inject a turn without the mic
ssh ... 'source ~/wini_pipeline_test_env.sh; \
  ros2 topic pub --once -w 1 /speech_text std_msgs/msg/String "{data: \"explain quadratic zeroes\"}"'

# stop everything
ssh ... 'pkill -f "wakeword_node|fastwhisper_node|brain_node|wini_tts_node|wini_display"'
```

> `pkill -f brain_node` from an SSH one-liner that itself *mentions* brain_node in its
> command string will match and kill the SSH shell too (exit 255 after the kill). Put the
> pkill last, or run it from a launcher script.

---

## 14. Cloud-brain mode (default since 2026-07-03)

The Jetson now runs the **same Part 11 cloud pipeline as the Windows rig**: ONE structured
Vertex **Gemini 2.5 Flash perception** call (intent + signals + concept, deterministic
SAFETY/NONSENSE gates first) and **Gemini Flash generation**, with the unchanged
deterministic state math, retrieval, and T9 display channel. ROS, mic/TTS, and the SPI
display stay exactly as in §0–§7 — only the brain's model calls moved to the cloud.

### 14.1 What was set up on the board

| Piece | Where |
|---|---|
| Study-core sync (Part 11 files) | `tutor_loop.py`, `perception/` (+ `perception/build/` artifacts), `llm_vertex.py`, `persona.json`, `cognitive_classifier/cues.py`, `pacing/{ledger,pacing_controller}.py` copied from the workspace (2026-07-03). `query.py` is now **identical in both branches** (the workspace adopted the Jetson's lazy-faiss/`with_index` version). `llm_local.py` + `device_config.py` remain Jetson-only. |
| SDK | `google-genai` + `python-dotenv` in `~/ROS2WS_audio_pipeline/.venv` |
| Auth | ADC user credentials at `~/.config/gcloud/application_default_credentials.json` (copied from the workspace machine) |
| Project/env | `"cloud CLI"/.env` (GOOGLE_CLOUD_PROJECT etc.) + `export GEN_BACKEND=gemini` in `~/wini_pipeline_test_env.sh` (GEN_BACKEND **must** be a real env var — `tutor_loop` reads it before dotenv loads) |
| Brain node | `brain_node.py`: no llm_local import/pre-warm in gemini mode; warms the Vertex clients instead (~6 s, best-effort); the whole cloud reply is split into sentences (decimal- and abbreviation-safe) and published per sentence to `/llm_out`, T9 figure goes up **before** the first sentence. Legacy qwen streaming path kept behind `GEN_BACKEND=qwen`. |

Measured on the board (2026-07-03): brain ready ~6 s after TutorLoop load; utterance →
first TTS sentence ~4 s warm; display frames 5.0 Hz; full pipeline ≈ 4.4 GB used /
2.8 GB free (no OOM risk).

### 14.2 Visual-cue path (T9) — how a diagram reaches the screen

`TutorLoop.turn()` returns `display: [{image_path, alt_text, why, figure_id, ...}]`
(at most ONE store-relative figure crop; chosen by the pedagogy rules — representation
gap, active-misconception disambiguation, or a visualization plea via rule 1a-vis).
The brain node resolves `image_path` against `rag_store/`, letterboxes to 480×320,
pre-flips (§7.2), and keeps it on `/wini/display/image` at 5 Hz while Wini speaks; the
generation prompt gets the "refer to the figure on screen" cue on display turns.

### 14.3 Forward design — ESP32 / thin-client display (no local processing)

When the brain moves to Cloud Run and the device shrinks to an ESP32-class client, the
device cannot render or fetch crops. The contract is **metadata-only**, and it already
holds today:

- The **store-relative `image_path` is the stable image ID** (e.g.
  `figure_crops/jemh102/fig_jemh102_fig_2_2.png`). The cloud turn result carries only
  this metadata — never pixels.
- The device's **SD card holds the pre-provisioned `figure_crops/` tree** (copied once
  from `rag_store/`; ~a few MB of PNGs), pre-sized/pre-flipped for its panel if needed.
- On a display turn the cloud sends `{figure_id, image_path, alt_text}`; the client
  looks the file up on the SD card by path and blits it. Unknown path ⇒ keep the face
  (same graceful behavior as today's missing-crop warning).
- Store updates that add/rename crops must re-provision the SD card **and** keep old
  paths stable (paths are IDs — treat renames as breaking changes).

The Jetson rig is the reference implementation of this contract: the brain node is
already consuming exactly the metadata the ESP32 will receive.

> **§14.1–14.2 update (2026-07-03 evening):** the ROS brain node described above was
> itself retired the same day in favor of the thin-client split (§15). The T9 visual-cue
> path is unchanged in shape — `turn()`'s `display` metadata → 480×320 rgb8 frames on
> `/wini/display/image` — but the renderer/publisher now lives in
> `wini_client/display_sinks.py` (RosDisplaySink), not in a brain node. §14.3 (the ESP32
> contract) is unaffected and remains the design of record.

---

## 15. Thin-client mode (manual bring-up — superseded at boot by §16)

> **2026-07-04:** the boot default is now the ROS-less platform (§16). `run_thin.sh` /
> `run_client.sh` still work as a manual/legacy path alongside the ROS display+head
> nodes, but nothing launches them automatically anymore — do NOT run both stacks at
> once (one owner per panel/serial port).

No wakeword, no fastwhisper, no Kokoro, no brain node — see §0. Two processes + the
display node:

| Piece | File (study core) | Runs as |
|---|---|---|
| Brain service | `wini_server.py` | `.venv` python, port 8123, `GEN_BACKEND=gemini` |
| Thin client | `wini_client/` (client.py, display_sinks.py, README.md) | `.venv` python, `--display ros` |
| SPI display | `display_controll wini_display` (unchanged) | ros2 run |

### 15.1 Bring up / stop / watch

```bash
ssh ... 'bash ~/run_thin.sh'          # audio pin + display + server + client
ssh ... 'tail -f ~/wini_test_logs/server.log'    # brain ready (gen_backend=gemini)
ssh ... 'tail -f ~/wini_test_logs/client.log'    # "[client] listening (trigger=vad)"
ssh ... 'pkill -9 -f "wini_serv[e]r|wini_clie[n]t"'   # stop (see 15.3 for [e] trick)
```

Readiness ≈ 40 s (TutorLoop + MiniLM load + Vertex/STT/TTS client warmup). Speak
normally — the RMS endpoint opens a turn when speech energy is detected and closes it
after ~1.2 s of silence. Half-duplex is structural (the client never records while
playing). A `session_ended` farewell returns the client to idle listening.

### 15.2 Test without a mic

```bash
# server only (turn + display metadata + TTS audio size):
curl -s -X POST http://127.0.0.1:8123/turn -H 'Content-Type: application/json' \
     -d '{"text": "show me the parabola graph", "speak": false}'
# full audio path with a canned utterance (fake_mic.pcm = 16 kHz mono int16):
curl -s -X POST http://127.0.0.1:8123/voice_turn -H 'X-Sample-Rate: 16000' \
     --data-binary @/home/roavai/fake_mic.pcm
# full client output path (display + speaker), one turn, then exit:
cd '~/ROS2WS_audio_pipeline/cloud CLI' && .venv/bin/python -u -m wini_client.client \
     --display ros --once-text 'show me the graph of a quadratic polynomial'
```

Measured (2026-07-03, warm-ish): STT ~1.5–2 s + brain ~2.5–5 s + TTS ~3–4.5 s per turn;
display frames ~4–5 Hz while speaking.

**Since Part 13 (2026-07-20) `/voice_turn` streams NDJSON** — an early transcript line, a
`turn_meta` line, then `{"part":"audio","seq":N,…}` chunks as the answer is synthesized.
`curl` above still works, but pass **`-N`** or curl buffers the body and you will conclude
streaming is broken when it is not. The final line still carries the complete `audio_b64`,
so a reader that parses only the last line is unaffected; a streaming reader must skip that
final audio when `"audio_streamed": true` or the answer is spoken twice. Measured
time-to-first-audio on winipi5: **3.3–4.4 s** (was 10.5–19.9 s) — build plan §15.

### 15.3 Thin-mode gotchas (all hit during bring-up)

- **PulseAudio default re-grab:** the onboard card steals the default sink/source back
  even after `select_usb_audio.sh`. Belt: `run_thin.sh` also `eval`s
  `select_usb_audio.sh --export` so the client/server inherit `PULSE_SINK`/`PULSE_SOURCE`,
  and the client opens BOTH streams with `device="pulse"` (raw ALSA default is pinned to
  the onboard card and has no mic).
- **A client blocked in a PortAudio read ignores SIGTERM** — always `pkill -9` the thin
  processes (run_thin.sh does).
- **pkill self-match:** any `ssh 'pkill -f X ...'` one-liner whose command string contains
  X kills its own shell (exit 255). Break the literal with a bracket class:
  `pkill -f "wini_serv[e]r"`.
- **Buffered logs:** run the detached python with `-u` or the log files stay empty.
- **`ros2 topic hz` from a cold CLI can print nothing inside a short `timeout`** — warm
  the daemon (`ros2 topic list`) first, or you will chase phantom "no frames" bugs.
- The RMS VAD listens to EVERYTHING (no wakeword by design) — TV/background speech will
  open turns. The touch-sensor trigger (`--trigger enter` shape) is the planned gate.

---

## 16. ROS-less platform (CURRENT bring-up, boot default since 2026-07-04)

The five platform ROS nodes (display, head, chin-reaction, touch trigger + the
`ros2 run` wrappers) are replaced by ONE process — `python -u -m wini_platform` from
the study core — per `WINI_ROSLESS_PLATFORM_PLAN.md`. No colcon, no DDS, no keepalive,
no pre-flip contract: the render thread owns the panel, the serial thread owns the
STM32, the client loop runs in-process, and `wini_server.py` is spawned/monitored as
the one separate process (it is the Cloud Run artifact).

### 16.1 Bring up / stop / watch

```bash
ssh ... 'bash ~/run_wini_platform.sh'                # face up, idle; chin hold 3 s starts/wakes
ssh ... 'bash ~/run_wini_platform.sh --autostart'    # also cold-start brain + client immediately
ssh ... 'tail -f ~/wini_test_logs/platform.log'      # "[platform] up:", head connect, turns
ssh ... 'pkill -9 -f "\-m wini_platfor[m]|wini_serv[e]r[.]py"'   # stop everything
```

Boot: the `@reboot` crontab line runs `run_wini_platform.sh` (the old
`run_boot_platform.sh` line is kept commented as rollback). The launcher sources
`wini_pipeline_test_env.sh`, exports `WINI_FILLERS=0` + `WINI_AUDIO_SELECT`, and
detaches the platform per §2.1. Server log: `"cloud CLI"/logs/server.log`.

### 16.2 Stage demos (acceptance tools, from `"cloud CLI"`)

```bash
.venv/bin/python -u -m wini_platform.display.demo    # emotions/gaze/cards/figure crop
.venv/bin/python -u -m wini_platform.touch.demo      # chin/head edges + press counts
```

⚠️ One owner per device: stop the ROS display/head nodes before ANY of the above, and
stop the platform before relaunching the old stack.

### 16.3 Measured (2026-07-04)

Old platform 5 processes ≈ 286 MB RSS → new platform 1 process 69 MB idle / 85 MB with
the client live (~200 MB reclaimed). Ambient-noise turn through the new stack: 8.1 s
(stt 3993 ms / brain 2 ms NONSENSE / tts 2592 ms) — same as §15.2 thin-mode numbers.

### 16.4 Overlay orientation + speaker pops (fixed 2026-07-04)

- **The §7.2 panel mirror still applies** in ROS-less mode — the plan's original
  "renderer owns orientation, no flip needed" claim was wrong (the glass itself
  mirrors; the near-symmetric face masked it until the Loading card came up
  backwards). The pre-flip now lives in exactly ONE place:
  `DisplayThread.show_overlay` — every sender (cards, `InProcSink` figure crops,
  demos) composes un-flipped.
- **TTS start/stop "dot" pops:** the C-Media USB codec clicks every time an output
  stream opens/closes, and `sd.play()` opened one per utterance. `wini_client`'s
  `play_pcm` now keeps ONE persistent `OutputStream` open across turns (survives
  sleep), adds a 10 ms fade-in/out, and writes a 150 ms silence tail so speech is
  fully out of the buffer before the mic reopens.

### 16.5 Gotcha: dark panel with zero errors after a relaunch (fixed 2026-07-04)

If the platform is killed **mid-SPI-write** (SIGKILL while rendering) and restarted
immediately, the ST7796S can miss its init (SWRESET/SLPOUT sent with no settle delay)
and stay **asleep**: every write then goes into display RAM invisibly — no exception,
normal CPU, dark glass. Fixed with 150 ms settles after 0x01/0x11 in
`wini_platform/display/wini_display_driver.py` (verified by 3× SIGKILL-mid-render +
relaunch), and `run_wini_platform.sh` now TERMs the old instance (platform handles
SIGTERM cleanly) before the `-9` belt. If a panel ever looks dead while logs are clean:
`python3 /home/roavai/panel_color_test.py` flashes full-screen colors via a fresh
driver init — colors visible ⇒ hardware fine, re-init the owner process.

---

## 17. Wi-Fi hotspot failover + provisioning (move the board to a new network, headless)

The board runs a **failover watchdog** (`wifi-watchdog.service` →
`/usr/local/bin/wifi-failover.sh`): when no known Wi-Fi is in range it raises a WPA2
hotspot **`Wini-Robot`** (NM profile `WiniHotspot`, `ipv4.method=shared` ⇒ the board is
the gateway **`10.42.0.1`**). That state has **no internet and no obvious IP**, which used
to strand the board. Two layers fix it (repo: `jetson_platform/wifi_provisioning/`,
installed 2026-07-09):

1. **mDNS (`avahi-daemon`, now enabled):** reach the board as **`ubuntu.local`** on ANY
   network — home Wi-Fi, the hotspot (`ubuntu.local` → `10.42.0.1`), anywhere. No IP hunting.
2. **A captive provisioning portal** (`wini-provision.service`, root, binds `:80`): join
   `Wini-Robot`, open **`http://10.42.0.1`** (or `http://ubuntu.local`) — a "Sign in to
   network" page pops up automatically (dnsmasq catch-all `wini-captive.conf`). Enter your
   Wi-Fi **name + password → Connect**; the board switches onto it and the hotspot drops.

### 17.1 How the switch stays sane (single radio + the watchdog)

`POST /connect` shells `/usr/local/bin/wini-wifi-connect.sh <ssid> <pw>`, which:
`touch /dev/shm/wifi_lock` (the watchdog **skips its check while this exists** — the
override was already built into `wifi-failover.sh`) → `nmcli con down WiniHotspot` (free the
single radio) → `nmcli dev wifi connect …` → write `/dev/shm/wini_wifi_status` (`ok|failed`)
→ `rm` the lock. On success the watchdog sees a real network and leaves the hotspot down; on
failure it re-raises `Wini-Robot` in ~30 s so you can retry. The portal's `/connect` only
acts in hotspot mode (a read-only status page otherwise), so the LAN can't reprovision it.

### 17.2 Operate / verify

```bash
# install onto a fresh board (needs sudo once — roavai has NO passwordless sudo):
scp -r jetson_platform/wifi_provisioning roavai@ubuntu.local:/home/roavai/
ssh roavai@ubuntu.local 'cd ~/wifi_provisioning && sudo bash install.sh'   # --with-failover if the watchdog is missing
# health:
ssh roavai@ubuntu.local 'systemctl is-active wini-provision avahi-daemon wifi-watchdog'
curl -s http://ubuntu.local/status        # {"hotspot":false|true,"ip":…,"host":"ubuntu"}
ping ubuntu.local                          # mDNS from Windows/macOS/Linux
```

Verified end-to-end 2026-07-09: raise `Wini-Robot` → portal answered at `10.42.0.1`
(`hotspot:true`) → `wini-wifi-connect.sh` rejoined `ROAVAI Pvt Ltd` (`ok|…|192.168.29.39`),
whole cycle ~28 s. Test it yourself with `wifi_provisioning/test_switch.sh` — a
**self-healing** detached root script that always rejoins home Wi-Fi (90 s safety net), so a
dropped SSH can't lock you out (there is no Tailscale lifeline — it was down that day).
Full design + end-user flow: `jetson_platform/wifi_provisioning/README.md`.
