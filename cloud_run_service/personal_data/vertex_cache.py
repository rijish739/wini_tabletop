"""Vertex context cache for the personal-data static block (§13).

Its own cache, its own record file, its own lifecycle — deliberately not shared with
``perception/vertex_cache.py`` or ``child_safety/vertex_cache.py``. The static block
(nine class definitions plus the maths-protection instructions) is byte-identical every
turn and is the largest part of the prompt, so caching it is where the cost goes; but a
personal-data prompt fused into another package's would be re-validated whenever that
package changed and could not be evaluated independently.

**A cache change re-runs §12.** Both corpora, not one.

Graceful by construction: a missing, expired or stale cache NEVER breaks a turn.
``active_name()`` returns a resource name only if the record exists, has not expired
(2-minute margin), the prompt hash still matches, and the model id still matches.
Otherwise the call sends the full system instruction and behaves identically, only
costing more.

CLI:
    python -m personal_data.vertex_cache --create [--ttl-hours 24]
    python -m personal_data.vertex_cache --status
    python -m personal_data.vertex_cache --delete
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import config
from .prompt import STATIC_BLOCK, prompt_hash

CACHE_RECORD = config.BUILD_DIR / "vertex_cache.json"
EXPIRY_MARGIN_S = 120


def _load_record() -> Optional[dict]:
    if not CACHE_RECORD.exists():
        return None
    try:
        return json.loads(CACHE_RECORD.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — a corrupt record is no record
        return None


def active_name() -> Optional[str]:
    """The usable cache resource name, or None (expired / stale prompt / absent)."""
    record = _load_record()
    if not record:
        return None
    try:
        expires = datetime.fromisoformat(record["expire_time"])
        if datetime.now(timezone.utc) >= expires - timedelta(seconds=EXPIRY_MARGIN_S):
            return None
        if record.get("prompt_hash") != prompt_hash():
            return None                  # prompt-of-record changed -> never serve stale
        if record.get("model") != config.resolved_model():
            return None
        return record["name"]
    except Exception:  # noqa: BLE001
        return None


def create(ttl_hours: float = 24.0) -> dict:
    """Create (replace) the cache from the current prompt-of-record. Billed: one-time
    cached-token ingestion plus small hourly storage while the TTL runs."""
    from google.genai import types
    import llm_vertex

    client = llm_vertex._client(config.VERTEX_PERSONAL_DATA_LOCATION)
    old = _load_record()

    cache = client.caches.create(
        model=config.resolved_model(),
        config=types.CreateCachedContentConfig(
            display_name="wini-personal-data-static",
            system_instruction=STATIC_BLOCK,
            ttl=f"{int(ttl_hours * 3600)}s",
        ),
    )
    record = {
        "name": cache.name,
        "model": config.resolved_model(),
        "model_pinned": config.model_pinned(),
        "region": config.VERTEX_PERSONAL_DATA_LOCATION,
        "created": datetime.now(timezone.utc).isoformat(),
        "expire_time": (
            cache.expire_time.isoformat() if cache.expire_time
            else (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
        ),
        "prompt_hash": prompt_hash(),
        "cached_tokens": getattr(
            getattr(cache, "usage_metadata", None), "total_token_count", None
        ),
    }
    config.BUILD_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_RECORD.write_text(json.dumps(record, indent=2), encoding="utf-8")

    if old and old.get("name") and old["name"] != record["name"]:
        try:
            client.caches.delete(name=old["name"])
        except Exception:  # noqa: BLE001 — already gone server-side is fine
            pass
    return record


def delete() -> bool:
    record = _load_record()
    if not record:
        return False
    try:
        import llm_vertex

        llm_vertex._client(config.VERTEX_PERSONAL_DATA_LOCATION).caches.delete(
            name=record["name"]
        )
    except Exception:  # noqa: BLE001
        pass
    CACHE_RECORD.unlink(missing_ok=True)
    return True


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Vertex context cache for the personal-data static block"
    )
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--ttl-hours", type=float, default=24.0)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args()

    if args.create:
        print(json.dumps(create(ttl_hours=args.ttl_hours), indent=2))
    elif args.delete:
        print("deleted" if delete() else "no cache record")
    else:
        name = active_name()
        print(json.dumps(
            {"record": _load_record(), "active": name is not None, "active_name": name},
            indent=2,
        ))


if __name__ == "__main__":
    main()
