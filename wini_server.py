"""Compatibility entrypoint for the canonical Wini HTTP server."""

from __future__ import annotations

import runpy
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_CANONICAL_ROOT = Path(__file__).resolve().parent / "cloud_run_service"
_CANONICAL_FILE = _CANONICAL_ROOT / "wini_server.py"


def _load_canonical() -> None:
    sys.path.insert(0, str(_CANONICAL_ROOT))
    previous = sys.modules.pop(__name__, None)
    spec = spec_from_file_location(__name__, _CANONICAL_FILE)
    if spec is None or spec.loader is None:
        if previous is not None:
            sys.modules[__name__] = previous
        raise ImportError(f"cannot load canonical server: {_CANONICAL_FILE}")
    module = module_from_spec(spec)
    sys.modules[__name__] = module
    spec.loader.exec_module(module)
    globals().update(module.__dict__)


if __name__ == "__main__":
    main()
