# Wini Local Brain & Debug Console Command Reference Guide

This document contains all the commands, environment variables, APIs, and scripts for running, debugging, testing, and managing the **Wini Local Brain** (`cloud_run_service`), **Debug Console**, and **Board Buddy Renderer**.

---

## 1. Starting the Wini Local Brain Server

The active brain server is located inside `d:\cloud CLI\cloud_run_service`. Always ensure `WINI_RESPONSE_LAYER="1"` and `GEN_BACKEND="gemini"` are set in your environment.

**Optional — board/speech time-sync (`WINI_SYNC_VISUAL="1"`, default off):** the on-screen board is drawn from the answer by a second LLM call that normally runs *after* generation, so the picture lands a beat or two into the speech that is already streaming. With this flag on, that draw is pre-warmed from the first spoken sentence and runs concurrently with the rest of generation, so the board and speech land at almost the same time. When off, the draw path is byte-identical to before; a missed/failed pre-warm falls back to the serial draw, so the worst case is never worse than today.

### PowerShell
```powershell
cd "d:\cloud CLI\cloud_run_service"
$env:GEN_BACKEND="gemini"
$env:WINI_RESPONSE_LAYER="1"
& "C:\Users\LENOVO\AppData\Local\Programs\Python\Python312\python.exe" wini_server.py --port 8123
```

### Command Prompt (cmd)
```cmd
cd /d "d:\cloud CLI\cloud_run_service"
set GEN_BACKEND=gemini
set WINI_RESPONSE_LAYER=1
"C:\Users\LENOVO\AppData\Local\Programs\Python\Python312\python.exe" wini_server.py --port 8123
```

---

## 2. Server Health & Readiness Check

Check if the brain components (Perception, Gemini Vertex client, MiniLM embeddings, Board Buddy authoring) are fully built and ready for turns:

### Python
```python
import urllib.request, json
res = urllib.request.urlopen("http://localhost:8123/health", timeout=5)
print(json.loads(res.read()))
# Expected when ready: {'ok': True, 'ready': True, 'error': None, 'gen_backend': 'gemini'}
```

### cURL / PowerShell
```powershell
Invoke-RestMethod -Uri "http://localhost:8123/health"
```

---

## 3. Opening & Running the Web Debug Console

The HTML Debug Console provides a real-time SSE stream of all brain layers (L1–L8), latency breakdowns, raw JSON event inspection, and a live 600×800 **Board Buddy Canvas Preview**.

### File Locations
- **Voice & Debug Console**: [`file:///d:/cloud%20CLI/cloud_workspace_v8/voice/test.html`](file:///d:/cloud%20CLI/cloud_workspace_v8/voice/test.html)
- **Standalone Tools Console**: [`file:///d:/cloud%20CLI/tools/debug_console.html`](file:///d:/cloud%20CLI/tools/debug_console.html)

> Simply double-click or open either file in Google Chrome / Edge. The console automatically connects to `http://localhost:8123`.

---

## 4. Real-time Debug Logs & SSE Streaming

### A. Fetch Ring Buffer Logs (JSON)
```python
import urllib.request, json
r = urllib.request.urlopen("http://localhost:8123/debug/logs")
logs = json.loads(r.read())
for e in logs.get("entries", []):
    print(f"[{e.get('layer'):<4}] {e.get('event'):<25} {e}")
```

### B. Print Specific Layer (e.g. L6 Response / Board Buddy)
```python
import urllib.request, json
r = urllib.request.urlopen("http://localhost:8123/debug/logs")
logs = json.loads(r.read())
for e in logs.get("entries", []):
    if e.get("layer") == "L6":
        print(e.get("event"), "::", {k: v for k, v in e.items() if k not in ("ts", "layer", "event", "image_data_url")})
```

### C. Clear Debug Logs Buffer
```python
import urllib.request
req = urllib.request.Request("http://localhost:8123/debug/clear", method="POST")
urllib.request.urlopen(req)
```

---

## 5. Board Buddy Rendering Commands

### A. POST to Server `/board/render` Endpoint
Render any Board Buddy JSON payload directly into a 600×800 PNG Data URL:

```python
import urllib.request, json

payload = [
    {"id": "g1", "type": "geometry", "shape": "right_triangle", "pos": [300, 400], "size": [220, 150], "labels": [{"text": "A"}, {"text": "B"}, {"text": "C"}], "color": "#1B69B6"},
    {"id": "s1", "type": "stickers", "item": "lightbulb", "pos": [480, 40]},
    {"id": "t1", "type": "text", "text": "Right Triangle (legs 3 & 4)", "pos": [40, 40], "size": "large", "color": "#1B69B6"}
]

data = json.dumps({"payload": payload}).encode()
req = urllib.request.Request("http://localhost:8123/board/render", data=data, headers={"Content-Type": "application/json"}, method="POST")
res = json.loads(urllib.request.urlopen(req).read())

print("Render Success:", res.get("ok"))
print("PNG Base64 Length:", len(res.get("image_data_url", "")))
```

### B. Run Standalone Board Buddy Renderer in Python
```python
import sys
sys.path.append(r"d:\cloud CLI\cloud_run_service\board_buddy\board_buddy-main")
from board_buddy import BoardBuddyCanvas
import io, base64

canvas = BoardBuddyCanvas(600, 800)
canvas.load_json([
    {"id": "g1", "type": "geometry", "shape": "circle", "pos": [300, 400], "color": "#1B69B6"},
    {"id": "t1", "type": "text", "text": "Understanding Circles", "pos": [40, 40], "size": "large"}
])

img = canvas.render()  # Returns PIL Image object
buf = io.BytesIO()
img.save(buf, format="PNG")
b64_str = base64.b64encode(buf.getvalue()).decode()
print("Generated Data URL:", f"data:image/png;base64,{b64_str[:50]}...")
```

---

## 6. Executing Test Turns

### A. Send Text Turn (`/turn`)
```python
import urllib.request, json

req_body = {
    "text": "I want to know about circles show me with some real time graph.",
    "speak": False
}

req = urllib.request.Request(
    "http://localhost:8123/turn",
    data=json.dumps(req_body).encode(),
    headers={"Content-Type": "application/json"},
    method="POST"
)
res = json.loads(urllib.request.urlopen(req).read())

print("Pedagogical Action:", res.get("action"))
print("Answer Text:", res.get("answer"))
print("Board Image Present:", "rendered_board_data_url" in res.get("rl_visual", {}))
```

### B. Send Voice Audio Turn (`/voice_turn`)
```python
import urllib.request

pcm_data = open("sample_16k.pcm", "rb").read()  # 16kHz 16-bit mono raw PCM

req = urllib.request.Request(
    "http://localhost:8123/voice_turn?rate=16000&mode=pcm",
    data=pcm_data,
    headers={"Content-Type": "application/octet-stream"},
    method="POST"
)
res = urllib.request.urlopen(req)
print("Voice Turn Status:", res.status)
```

---

## 7. Process Management & Utility Commands

### A. Stop Running Brain Server
```powershell
Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*wini_server*" } | Stop-Process -Force
```

### B. Check Active Listening Port 8123
```powershell
Get-NetTCPConnection -LocalPort 8123 -ErrorAction SilentlyContinue
```

### C. Sync `test.html` to `debug_console.html`
```powershell
python -c "import shutil; shutil.copy2(r'd:\cloud CLI\cloud_workspace_v8\voice\test.html', r'd:\cloud CLI\tools\debug_console.html'); print('Synced successfully')"
```
