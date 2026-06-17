"""Wini Tutor UI — lightweight Flask bridge.

Imports the existing TutorLoop and exposes it as REST endpoints for the
browser-based test UI.  **No existing code is modified.**

Usage:
    pip install flask flask-cors       (one-time)
    python wini_ui_server.py           (starts on http://localhost:5050)

Requires: the Qwen llama.cpp server running at 127.0.0.1:8080 for full
answers (the cognitive pipeline still works without it — answers will be null).
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# ---------------------------------------------------------------------------
# Lazy globals — expensive imports happen once on first /api/turn call
# ---------------------------------------------------------------------------
_loop = None
ROOT = Path(__file__).resolve().parent
STORE = ROOT / "rag_store"
STATE_PATH = ROOT / "learner_state.json"
LOG_PATH = STORE / "learning_log.jsonl"


def _get_loop():
    """Lazy-init TutorLoop so the server starts fast and shows the UI
    immediately while models load on the first request."""
    global _loop
    if _loop is None:
        from tutor_loop import TutorLoop
        _loop = TutorLoop(state_path=STATE_PATH, want_answer=True, use_judge=True)
    return _loop


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder=None)
CORS(app)

UI_DIR = ROOT / "ui"


# ---- static files ----------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(str(UI_DIR), "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(str(UI_DIR), filename)


# ---- API endpoints ---------------------------------------------------------
@app.route("/api/turn", methods=["POST"])
def api_turn():
    """Run one tutor turn. Body: {"text": "student utterance"}."""
    body = request.get_json(force=True)
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "empty text"}), 400
    try:
        loop = _get_loop()
        result = loop.turn(text)
        # Serialize numpy/non-JSON types
        return jsonify(_sanitize(result))
    except Exception:
        return jsonify({"error": traceback.format_exc()}), 500


@app.route("/api/state")
def api_state():
    """Return the current learner state from disk."""
    try:
        if STATE_PATH.exists():
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            return jsonify(data)
        return jsonify({})
    except Exception:
        return jsonify({"error": traceback.format_exc()}), 500


@app.route("/api/log")
def api_log():
    """Return the last N learning-log entries."""
    n = int(request.args.get("n", 20))
    try:
        if not LOG_PATH.exists():
            return jsonify([])
        lines = LOG_PATH.read_text(encoding="utf-8").strip().splitlines()
        entries = []
        for line in lines[-n:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return jsonify(entries)
    except Exception:
        return jsonify({"error": traceback.format_exc()}), 500


@app.route("/api/health")
def api_health():
    """Check whether the Qwen LLM server is reachable."""
    import requests as req
    try:
        r = req.get("http://127.0.0.1:8080/v1/models", timeout=3)
        return jsonify({"qwen": r.status_code == 200, "status": "ok"})
    except Exception:
        return jsonify({"qwen": False, "status": "Qwen server unreachable"})


@app.route("/api/reset-session", methods=["POST"])
def api_reset_session():
    """Reset session state (context, served items, pending) without
    touching mastery or misconception data."""
    try:
        loop = _get_loop()
        session = loop.state.data.get("session", {})
        session.pop("context", None)
        session.pop("served_items", None)
        session.pop("bridges_served", None)
        session.pop("pending_check", None)
        session.pop("pending_hope", None)
        session.pop("last_action", None)
        session.pop("last_repr_targets", None)
        loop.state.data["session"] = session
        if loop.state.path:
            loop.state.save()
        return jsonify({"ok": True})
    except Exception:
        return jsonify({"error": traceback.format_exc()}), 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sanitize(obj):
    """Convert numpy types and other non-JSON-serializable objects."""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 56)
    print("  Wini Tutor UI  ->  http://localhost:5050")
    print("  (Models load on first /api/turn call)")
    print("=" * 56)
    app.run(host="0.0.0.0", port=5050, debug=False)
