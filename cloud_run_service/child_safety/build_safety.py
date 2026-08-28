"""Materialize the prompt-of-record so a human and a cache can both read it.

``build()`` writes ``child_safety/build/safety_context.md`` (the exact static block
sent to Vertex) and ``child_safety/build/safety_prompt.json`` (the version stamps
and the prompt hash). Both are build artifacts: ``prompt.py`` is the source.

Why materialize at all: §14 requires a case record to be self-contained enough that
a reviewer never needs to reproduce the call, and §10.3 makes the prompt version a
gating fact. A hash in a JSON file that CI can diff is what makes "the prompt
changed" an observable event rather than a remembered one.

    python -m child_safety.build_safety [--print]
"""

from __future__ import annotations

import json

from . import config
from .prompt import (
    PROMPT_VERSION,
    SAFETY_CLASS_NAMES,
    SCHEMA_VERSION,
    STATIC_BLOCK,
    prompt_hash,
)
from .schema import REQUIRED_FIELDS

CONTEXT_PATH = config.BUILD_DIR / "safety_context.md"
MANIFEST_PATH = config.BUILD_DIR / "safety_prompt.json"


def manifest() -> dict:
    return {
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "prompt_hash": prompt_hash(),
        "classes": list(SAFETY_CLASS_NAMES),
        "schema_fields": list(REQUIRED_FIELDS),
        "model": config.resolved_model(),
        "model_pinned": config.model_pinned(),
        "location": config.VERTEX_SAFETY_LOCATION,
        "timeout_s": config.SAFETY_TIMEOUT_S,
    }


def build(write: bool = True) -> dict:
    payload = manifest()
    if write:
        config.BUILD_DIR.mkdir(parents=True, exist_ok=True)
        CONTEXT_PATH.write_text(STATIC_BLOCK, encoding="utf-8")
        MANIFEST_PATH.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    return payload


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build the child-safety prompt-of-record")
    parser.add_argument("--print", action="store_true", help="print the static block")
    args = parser.parse_args()
    payload = build(write=True)
    if args.print:
        print(STATIC_BLOCK)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
