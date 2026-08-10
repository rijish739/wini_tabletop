"""Learner-state persistence backend (Part 15 Phase E).

The brain keeps the learner model as an in-memory dict (`LearnerState.data`) and
today persists it as an atomic local JSON file (`learner_state.py` save/load). On
Cloud Run the local filesystem is ephemeral — an instance restart would lose the
learner's entire history — so a durable store is needed.

This module adds a pluggable durable backend selected by ``WINI_STATE_BACKEND``:

    json       (default) — no durable store here; the local JSON file IS the store.
                           Byte-for-byte today's behaviour; get_state_store() → None.
    firestore            — one document per learner in Firestore (regional), read at
                           startup and written at each TURN BOUNDARY by the server.

Contract (plan §6 Phase E, non-negotiable):
  * The in-memory ``state.data`` stays the working copy. Firestore is touched only
    at turn boundaries — NEVER mid-turn (a network hop inside the sub-100 ms state
    math is exactly what the plan forbids). The server calls ``save()`` once, after
    ``turn()`` returns and the lock is released.
  * Turns are half-duplex per learner (Cloud Run concurrency=1), so last-writer-wins
    on a single-field document set is safe and atomic.

The whole state is stored as ONE JSON string field (``state_json``) rather than a
native Firestore map. This is deliberate: it sidesteps every Firestore type
constraint (no nested arrays-of-arrays, no field-name restrictions, no 20-level
nesting cap) that the free-form learner dict would otherwise trip, and keeps the
write a single atomic document set. The 1 MiB document limit is far above any
learner state (measured well under 100 KiB).
"""

from __future__ import annotations

import json
import os
import hashlib
import re
from typing import Optional


def _backend_name() -> str:
    return os.getenv("WINI_STATE_BACKEND", "json").strip().lower()


def resolve_learner_id() -> str:
    """Resolve a non-shared learner key from deployment-authenticated identity.

    ``WINI_LEARNER_ID`` remains the explicit compatibility override. Otherwise a
    per-device or per-session identity injected by the authenticated deployment is
    pseudonymized before it becomes a document ID. Firestore fails closed instead
    of putting unrelated children in the historical ``default`` document.
    """
    explicit = os.getenv("WINI_LEARNER_ID", "").strip()
    if explicit and explicit.lower() != "default":
        return re.sub(r"[^A-Za-z0-9_.-]", "_", explicit)[:120]
    identity = (os.getenv("WINI_AUTHENTICATED_DEVICE_ID", "").strip()
                or os.getenv("WINI_AUTHENTICATED_SESSION_ID", "").strip())
    if not identity:
        raise RuntimeError(
            "Firestore requires WINI_LEARNER_ID or an authenticated device/session identity")
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"learner_{digest}"


def get_state_store() -> "Optional[FirestoreStateStore]":
    """Return the durable store, or None for the default JSON-file path.

    None means "no extra durable backend" — the caller keeps using the local JSON
    file exactly as before. A non-None store is an object with ``load() -> dict|None``
    and ``save(dict) -> None`` that the server drives at turn boundaries."""
    if _backend_name() == "firestore":
        return FirestoreStateStore()
    return None


class FirestoreStateStore:
    """One Firestore document per learner. Client built ONCE (ADC/channel setup is
    the dominant cost, CLAUDE.md) and reused for the life of the process."""

    def __init__(self) -> None:
        from google.cloud import firestore  # lazy: json backend pulls in no cloud dep

        project = os.getenv("GOOGLE_CLOUD_PROJECT") or None
        self.collection = os.getenv("WINI_FIRESTORE_COLLECTION", "learner_state")
        self.learner_id = resolve_learner_id()
        # A named database is allowed (regional Firestore is created with a name);
        # "(default)" is the unnamed default database.
        database = os.getenv("WINI_FIRESTORE_DATABASE", "(default)")
        self._db = firestore.Client(project=project, database=database)
        self._doc = self._db.collection(self.collection).document(self.learner_id)
        self._server_ts = firestore.SERVER_TIMESTAMP

    def load(self) -> Optional[dict]:
        """Read this learner's durable state, or None when the document does not
        exist yet (a brand-new learner → cold start). Any read failure raises so the
        caller can decide (the server logs and falls back to the local JSON path —
        it must never silently serve a wrong learner's state)."""
        snap = self._doc.get()
        if not snap.exists:
            return None
        d = snap.to_dict() or {}
        raw = d.get("state_json")
        if not raw:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("firestore state_json did not decode to a dict")
        data.setdefault("concept_states", {})
        data.setdefault("global", {})
        return data

    def save(self, data: dict) -> None:
        """Write the whole state as one atomic document set (last-writer-wins)."""
        self._doc.set({
            "state_json": json.dumps(data, ensure_ascii=False),
            "learner_id": self.learner_id,
            "updated": self._server_ts,
        })

    def describe(self) -> str:
        return (f"firestore://{self._db.project}/{os.getenv('WINI_FIRESTORE_DATABASE', '(default)')}"
                f"/{self.collection}/{self.learner_id}")
