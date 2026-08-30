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
  - **Learner transcript reaches this sink only as a RedactedText** (see below).

PERSONAL DATA (PERSONAL_DATA_CONTRACT.md §6.2, §6.3, §8)
--------------------------------------------------------
This is a **converted sink**: it streams to SSE *and* writes to disk, and neither is
recallable once emitted.  §6.3 converts it for exactly that reason.

So a transcript-bearing field (see ``TRANSCRIPT_FIELDS``) may hold only a
``personal_data.RedactedText``.  A plain ``str`` under one of those keys is
**withheld** — replaced by ``WITHHELD`` — rather than emitted.  That is §8's fail-closed
rule: losing a debug line costs nothing, persisting a child's phone number costs
everything, and there is no retro-scrub for an SSE frame that has already gone out.

Two consequences worth stating rather than discovering:

  * ``voice/cloud_stt.py``'s ``stt_done`` emits the raw transcript *before* Utterance
    Intake has run, so no verdict can exist for it and it will always be withheld.
    That is correct and it is also a real loss of the live transcript view in the debug
    UI.  The fix is not to exempt it; it is for that call site to stop sending text.
  * Detection is by **duck-typing on ``redacted_text_marker``**, not by importing
    ``personal_data``.  This module is stdlib-only on purpose — ``personal_data.config``
    pulls ``dotenv``, and a debug sink that can fail to import is a debug sink that
    breaks a turn.
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

#: Field names that carry learner transcript. A plain ``str`` under one of these is
#: withheld; a ``RedactedText`` is emitted as its placeholder-substituted text plus its
#: class labels.
#:
#: This list is a judgement about *names*, which is weaker than a type — a future
#: `child_said=` would slip through. It is a belt for the fields that exist today, and
#: the braces are the four converted sinks in §6.3 that do take a type. If you are
#: adding a field here you are probably adding one that should not be emitted at all.
TRANSCRIPT_FIELDS: frozenset[str] = frozenset({
    "transcript",
    "text",
    "question",
    "utterance",
    "normalized_text",
    "learner_text",
    "student_text",
})

#: What a withheld field says. Deliberately not an empty string: "we chose not to write
#: this" and "there was nothing here" are different facts, and collapsing them is the
#: same mistake as letting an outage read as "no personal data".
WITHHELD: str = "[WITHHELD_UNREDACTED]"

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
            **_scrub(fields),
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

def _scrub(fields: dict) -> dict:
    """Apply the §6.3 conversion to one event's fields, before anything is serialized.

    Three cases, and nothing else:

    * a ``RedactedText`` (duck-typed on ``redacted_text_marker``) is emitted as its
      placeholder-substituted text, with its class labels alongside under
      ``<field>_privacy_classes`` — labels only, never a value (§9);
    * **anything else** under a transcript-bearing key is withheld (§8 fail-closed).
      Not only a ``str``: a ``GenerationText`` may legitimately hold the unredacted
      turn, and it would serialize through ``json.dumps(default=str)`` as exactly that.
      The rule is a whitelist for the same reason the sinks are typed — the next thing
      someone passes here will not be a ``str`` either;
    * every other key passes through untouched. Counts, durations, ids, model statuses
      and Wini's own reply are not learner transcript and were never in scope.
    """
    scrubbed: dict = {}
    for key, value in fields.items():
        if getattr(value, "redacted_text_marker", False):
            scrubbed[key] = value.text
            classes = getattr(value, "class_values", None)
            if classes:
                scrubbed[f"{key}_privacy_classes"] = list(classes)
        elif key in TRANSCRIPT_FIELDS:
            scrubbed[key] = WITHHELD
        else:
            scrubbed[key] = value
    return scrubbed


def _fan_out(entry: dict) -> None:
    """Append to ring, fan out to subscribers, optionally write to disk.

    Everything reaching here has already been through ``_scrub``. Do not add a caller
    that bypasses it — this function is the point of no return for an SSE frame.
    """
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
