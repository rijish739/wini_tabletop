"""Parent dashboard server — runs ONLY on the laptop.

Nothing is installed on the Jetson. On each refresh this server pulls the raw
data files off the board over SSH (key auth, JETSON_PIPELINE_RUNBOOK.md §1):

    learner_state.json               — mastery / flags / misconceptions / mood
    rag_store/learning_log.jsonl     — recent activity (tailed remotely)
    rag_store/safety_alerts.jsonl    — wellbeing alerts

and builds the parent-friendly report locally via progress_report.py, joining
against THIS workspace's rag_store/concepts.json + graph.json (the store
metadata is identical on both machines). The last good snapshot is cached in
_parent_cache/ so the dashboard keeps working when the board is off.

Pure stdlib. Run:
    python parent_dashboard.py                          # Jetson per runbook
    python parent_dashboard.py --jetson roavai@ubuntu.local
    python parent_dashboard.py --local                  # this workspace's files
then open http://localhost:8300
"""

from __future__ import annotations

import argparse
import io
import json
import mimetypes
import subprocess
import tarfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import progress_report

ROOT = Path(__file__).resolve().parent
UI_DIR = ROOT / "parent_ui"
CACHE_DIR = ROOT / "_parent_cache"

JETSON = "roavai@ubuntu.local"
REMOTE_ROOT = "/home/roavai/ROS2WS_audio_pipeline/cloud CLI"
LOCAL_MODE = False
SSH_TIMEOUT_S = 20
MIN_FETCH_INTERVAL_S = 15   # UI polls every 30 s; never hammer the board
LOG_TAIL_LINES = 600

_last_fetch = {"t": 0.0, "ok": False}

REMOTE_FILES = ("learner_state.json",
                "rag_store/learning_log.jsonl",
                "rag_store/safety_alerts.jsonl")


def _pull_from_jetson() -> bool:
    """One SSH call: tar up the (existing) data files on the board — with the
    learning log pre-tailed so the transfer stays small — and unpack the bytes
    into _parent_cache/ with Python's tarfile (no local tar dependency).
    Returns True on a fresh snapshot."""
    remote_cmd = (
        f'cd "{REMOTE_ROOT}" && tmp=$(mktemp -d) && '
        f'mkdir -p "$tmp/rag_store" && '
        f'[ -f learner_state.json ] && cp learner_state.json "$tmp/" ; '
        f'[ -f rag_store/learning_log.jsonl ] && '
        f'tail -n {LOG_TAIL_LINES} rag_store/learning_log.jsonl > "$tmp/rag_store/learning_log.jsonl" ; '
        f'[ -f rag_store/safety_alerts.jsonl ] && '
        f'cp rag_store/safety_alerts.jsonl "$tmp/rag_store/" ; '
        f'tar cz -C "$tmp" . && rm -rf "$tmp"'
    )
    try:
        proc = subprocess.run(
            ["ssh", "-o", f"ConnectTimeout={SSH_TIMEOUT_S - 8}", JETSON, remote_cmd],
            capture_output=True, timeout=SSH_TIMEOUT_S)
        if proc.returncode != 0 or not proc.stdout:
            print(f"[dash] jetson fetch failed: {proc.stderr.decode(errors='replace')[:200]}")
            return False
        CACHE_DIR.mkdir(exist_ok=True)
        (CACHE_DIR / "rag_store").mkdir(exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:gz") as tf:
            for m in tf.getmembers():
                rel = m.name.lstrip("./")
                if rel not in REMOTE_FILES or not m.isfile():
                    continue  # only the three expected files, nothing else
                (CACHE_DIR / rel).write_bytes(tf.extractfile(m).read())
        (CACHE_DIR / "fetched_at.txt").write_text(
            time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
        return True
    except Exception as e:  # noqa: BLE001 — an offline board is a normal condition
        print(f"[dash] jetson fetch failed: {e}")
        return False


def fetch_progress() -> tuple[int, dict]:
    if LOCAL_MODE:
        report = progress_report.build_progress_report(ROOT)
        report["source"] = "this laptop (local mode)"
        return 200, report

    now = time.monotonic()
    if now - _last_fetch["t"] >= MIN_FETCH_INTERVAL_S:
        _last_fetch["ok"] = _pull_from_jetson()
        _last_fetch["t"] = now

    state = CACHE_DIR / "learner_state.json"
    if not state.exists():
        return 502, {"error": "Wini device not reachable and no saved data yet",
                     "offline": True}
    report = progress_report.build_progress_report(
        ROOT,
        state_path=state,
        log_path=CACHE_DIR / "rag_store" / "learning_log.jsonl",
        alerts_path=CACHE_DIR / "rag_store" / "safety_alerts.jsonl",
    )
    report["source"] = "Wini device"
    report["stale"] = not _last_fetch["ok"]
    fa = CACHE_DIR / "fetched_at.txt"
    report["fetched_at"] = fa.read_text(encoding="utf-8").strip() if fa.exists() else None
    return 200, report


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[dash] {fmt % args}")

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/progress":
            code, payload = fetch_progress()
            return self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                              "application/json; charset=utf-8")
        # static files from parent_ui/ only (resolve() blocks traversal)
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        f = (UI_DIR / rel).resolve()
        if not str(f).startswith(str(UI_DIR.resolve())) or not f.is_file():
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        return self._send(200, f.read_bytes(), ctype)


def main():
    global JETSON, REMOTE_ROOT, LOCAL_MODE
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8300)
    ap.add_argument("--jetson", default=JETSON, help="ssh target for the board")
    ap.add_argument("--remote-root", default=REMOTE_ROOT,
                    help="study-core path on the board")
    ap.add_argument("--local", action="store_true",
                    help="use this workspace's files (no Jetson; dev/demo)")
    args = ap.parse_args()
    JETSON, REMOTE_ROOT, LOCAL_MODE = args.jetson, args.remote_root, args.local
    src = "LOCAL workspace files" if LOCAL_MODE else f"{JETSON}:{REMOTE_ROOT}"
    print(f"[dash] Parent dashboard -> http://localhost:{args.port}  (data: {src})")
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
