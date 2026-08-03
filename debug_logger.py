"""debug_logger — real-time, structured per-layer event bus for the Wini brain.

Usage (in any layer module):
    from debug_logger import emit as debug_emit
    debug_emit("L1", "stt_done", transcript="hello wini", ms=1240)

The events go to:
  1. A thread-safe in-memory circular ring buffer (last MAXLEN entries)
  2. All currently-open SSE subscriber queues (wini_server.py /debug/stream)
  3. Optionally a JSONL file on disk (set WINI_DEBUG_FILE=/tmp/wini_debug.jsonl)

Design rules:
  - Never raises.  A debug_emit() that blows up must never break a turn.
  - No external dependencies — stdlib only.
  - Zero overhead when no SSE subscriber is open and no file sink is set.
"""

from __future__ import annotations

import collections
import json
import os
import queue
import threading
from datetime import datetime, timezone

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────
MAXLEN: int = 2000          # ring buffer depth (entries)
_DEBUG_FILE: str | None = os.getenv("WINI_DEBUG_FILE", "").strip() or None

# ──────────────────────────────────────────────────────────────────────────────
# Internal state — all access must hold _lock
# ──────────────────────────────────────────────────────────────────────────────
_lock = threading.Lock()
_ring: collections.deque[dict] = collections.deque(maxlen=MAXLEN)
_subscribers: list[queue.Queue] = []     # one queue per open SSE connection
_file_sink = None                        # open file object or None

# ──────────────────────────────────────────────────────────────────────────────
# Optional disk sink
# ──────────────────────────────────────────────────────────────────────────────
if _DEBUG_FILE:
    try:
        _file_sink = open(_DEBUG_FILE, "a", encoding="utf-8", buffering=1)  # noqa: WPS515 — line-buffered
        print(f"[debug_logger] disk sink → {_DEBUG_FILE}")
    except Exception as _e:  # noqa: BLE001
        print(f"[debug_logger] WARNING: could not open disk sink {_DEBUG_FILE}: {_e}")
        _file_sink = None


# ──────────────────────────────────────────────────────────────────────────────
# Layer constants (kept here so callers can import from one place)
# ──────────────────────────────────────────────────────────────────────────────
L0 = "L0"   # server / connection
L1 = "L1"   # STT
L2 = "L2"   # perception / intent gate
L3 = "L3"   # learner state read
L4 = "L4"   # pedagogy decision
L5 = "L5"   # retrieval (RAG)
L6 = "L6"   # generation (LLM)
L7 = "L7"   # TTS
L8 = "L8"   # state write-back
LSRV = "SRV"  # server-level (not a turn layer)


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def emit(layer: str, event: str, **fields) -> None:
    """Emit a structured debug event.  Never raises.

    Args:
        layer:  One of L0–L8 or LSRV.
        event:  Short snake_case name, e.g. "stt_done", "rules_decide".
        **fields: Arbitrary key/value pairs — keep values JSON-serialisable.
    """
    try:
        entry: dict = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "layer": layer,
            "event": event,
            **fields,
        }
        _fan_out(entry)
    except Exception:  # noqa: BLE001 — debug must never break a turn
        pass


def tail(n: int = 200) -> list[dict]:
    """Return the last *n* entries from the ring buffer (oldest first)."""
    with _lock:
        entries = list(_ring)
    return entries[-n:] if n < len(entries) else entries


def clear() -> int:
    """Flush the ring buffer.  Returns the number of entries discarded."""
    with _lock:
        count = len(_ring)
        _ring.clear()
    return count


def subscribe() -> queue.Queue:
    """Register a new SSE subscriber.  Returns a Queue to read events from.

    Each event is a JSON-encoded string (ready to write as ``data: …\\n\\n``).
    The sentinel ``None`` signals the stream should close.
    """
    q: queue.Queue = queue.Queue(maxsize=500)
    with _lock:
        _subscribers.append(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    """Remove a subscriber queue (called when the SSE connection closes)."""
    with _lock:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass
    # Drain to unblock any blocked put() in _fan_out
    try:
        while True:
            q.get_nowait()
    except queue.Empty:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fan_out(entry: dict) -> None:
    """Append to ring, fan out to subscribers, optionally write to disk."""
    line = json.dumps(entry, default=str)
    with _lock:
        _ring.append(entry)
        dead: list[queue.Queue] = []
        for q in _subscribers:
            try:
                q.put_nowait(line)
            except queue.Full:
                dead.append(q)   # slow consumer — drop it
        for q in dead:
            try:
                _subscribers.remove(q)
            except ValueError:
                pass
        if _file_sink is not None:
            try:
                _file_sink.write(line + "\n")
            except Exception:  # noqa: BLE001
                pass
