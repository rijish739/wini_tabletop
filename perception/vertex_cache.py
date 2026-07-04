"""Vertex context cache for the perception static block (Part 11 Stage 5).

The static block (~21k chars: intent taxonomy + 38 signal definitions + 108-concept
catalog + few-shot anchors) was being re-sent as `system_instruction` on every
perception call — the dominant per-turn token cost. This module creates a Vertex
**cached content** resource holding it, so each call sends only the tiny dynamic
prompt; cached input tokens are billed at the reduced rate.

Design (graceful by construction — a missing/expired/stale cache NEVER breaks a turn):
  - `create(ttl_hours)` builds the cache from the CURRENT built context
    (`perception/build/perception_context.md`) and persists its resource name +
    expiry + a sha of the context to `perception/build/vertex_cache.json`.
  - `active_name()` returns the resource name only if the record exists, is not
    expired (2-min safety margin), AND the context sha still matches the built
    artifact (a rebuilt prompt invalidates the cache — never serve a stale block).
  - `GeminiPerception._gemini_call` consults this once per process and ALSO retries
    once without the cache if a cached call fails (server-side expiry mid-process),
    then stops using it for the rest of the process.

Ops note: the cache is pinned to the model id it was created with
(`VERTEX_PERCEPTION_MODEL`); storage cost at ~6k tokens is negligible. On Cloud Run,
run `python -m perception.vertex_cache --create` at deploy (or let calls fall back
to the full system instruction — correctness is identical either way).

CLI:
    python -m perception.vertex_cache --create [--ttl-hours 24]
    python -m perception.vertex_cache --status
    python -m perception.vertex_cache --delete
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import config

CACHE_RECORD = config.BUILD_DIR / "vertex_cache.json"
CONTEXT_PATH = config.BUILD_DIR / "perception_context.md"
EXPIRY_MARGIN_S = 120


def _context() -> str:
    if not CONTEXT_PATH.exists():
        from .build_perception import build
        build(write=True)
    return CONTEXT_PATH.read_text(encoding="utf-8")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _load_record() -> Optional[dict]:
    if not CACHE_RECORD.exists():
        return None
    try:
        return json.loads(CACHE_RECORD.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — corrupt record == no record
        return None


def active_name() -> Optional[str]:
    """The usable cache resource name, or None (expired / stale prompt / absent)."""
    rec = _load_record()
    if not rec:
        return None
    try:
        expires = datetime.fromisoformat(rec["expire_time"])
        if datetime.now(timezone.utc) >= expires - timedelta(seconds=EXPIRY_MARGIN_S):
            return None
        if rec.get("context_sha") != _sha(_context()):
            return None                      # prompt rebuilt since cache creation -> stale
        if rec.get("model") != config.VERTEX_PERCEPTION_MODEL:
            return None
        return rec["name"]
    except Exception:  # noqa: BLE001
        return None


def create(ttl_hours: float = 24.0) -> dict:
    """Create (replace) the cache from the current built context. Billed: one-time
    cached-token ingestion + small hourly storage while the TTL runs."""
    from google.genai import types
    import llm_vertex

    ctx = _context()
    client = llm_vertex._client(config.VERTEX_REGION)
    old = _load_record()

    cache = client.caches.create(
        model=config.VERTEX_PERCEPTION_MODEL,
        config=types.CreateCachedContentConfig(
            display_name="wini-perception-static",
            system_instruction=ctx,
            ttl=f"{int(ttl_hours * 3600)}s",
        ),
    )
    rec = {
        "name": cache.name,
        "model": config.VERTEX_PERCEPTION_MODEL,
        "region": config.VERTEX_REGION,
        "created": datetime.now(timezone.utc).isoformat(),
        "expire_time": cache.expire_time.isoformat() if cache.expire_time
                       else (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat(),
        "context_sha": _sha(ctx),
        "cached_tokens": getattr(getattr(cache, "usage_metadata", None), "total_token_count", None),
    }
    config.BUILD_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_RECORD.write_text(json.dumps(rec, indent=2), encoding="utf-8")

    # Best-effort cleanup of the superseded resource (stops its storage billing).
    if old and old.get("name") and old["name"] != rec["name"]:
        try:
            client.caches.delete(name=old["name"])
        except Exception:  # noqa: BLE001
            pass
    return rec


def delete() -> bool:
    rec = _load_record()
    if not rec:
        return False
    try:
        import llm_vertex
        llm_vertex._client(config.VERTEX_REGION).caches.delete(name=rec["name"])
    except Exception:  # noqa: BLE001 — already gone server-side is fine
        pass
    CACHE_RECORD.unlink(missing_ok=True)
    return True


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Vertex context cache for perception (Stage 5)")
    ap.add_argument("--create", action="store_true")
    ap.add_argument("--ttl-hours", type=float, default=24.0)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--delete", action="store_true")
    args = ap.parse_args()

    if args.create:
        rec = create(ttl_hours=args.ttl_hours)
        print(json.dumps(rec, indent=2))
    elif args.delete:
        print("deleted" if delete() else "no cache record")
    else:
        rec = _load_record()
        name = active_name()
        print(json.dumps({"record": rec, "active": name is not None, "active_name": name}, indent=2))


if __name__ == "__main__":
    main()
