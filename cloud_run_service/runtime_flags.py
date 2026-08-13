"""Shared runtime feature flags.

Keep defaults in one place so the HTTP server and tutor cannot silently run
different architectures.  Values are read at import time, matching the existing
deployment contract: changing a flag requires a process restart.
"""
from __future__ import annotations

import os


def env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "")


# The response layer is the shipped architecture; 0 is the documented rollback.
RESPONSE_LAYER = env_flag("WINI_RESPONSE_LAYER", "1")

def confidence_floor(name: str, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(os.getenv(name, str(default)))))
    except (TypeError, ValueError):
        return default


STT_WRITE_CONFIDENCE_MIN = confidence_floor("WINI_STT_WRITE_CONFIDENCE_MIN", 0.60)
GRADER_WRITE_CONFIDENCE_MIN = confidence_floor("WINI_GRADER_WRITE_CONFIDENCE_MIN", 0.70)
