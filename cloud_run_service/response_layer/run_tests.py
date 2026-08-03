"""Run every Response Layer / Board Buddy suite in one command.

    python -m response_layer.run_tests

Offline: no Vertex, no torch, no pytest. Exit code is non-zero if any suite fails, so
this is usable as a pre-deploy gate. Skips (e.g. the device-only `figures/` renderer,
absent from the lean Cloud Run image) are reported but do not fail the run.

Baseline recorded 2026-08-02 after restoring the four suites that were missing from
cloud_run_service/: 68 passed, 0 failed, 1 skipped.
"""

from __future__ import annotations

import importlib

SUITES = (
    "test_board_buddy",
    "test_response_layer",
    "test_compilers",
    "test_runner_outcomes",
    "test_scene_adaptation",
)


def main() -> int:
    rc = 0
    results: list[tuple[str, int]] = []
    for name in SUITES:
        print(f"\n{'=' * 62}\n  {name}\n{'=' * 62}")
        try:
            mod = importlib.import_module(f".{name}", package="response_layer")
        except Exception as e:  # noqa: BLE001 — a missing suite is itself a failure
            print(f"  ERROR importing {name}: {e}")
            results.append((name, 1))
            rc = 1
            continue
        # the suites are not uniform: most expose main(), test_board_buddy exposes _run()
        entry = getattr(mod, "main", None) or getattr(mod, "_run", None)
        if entry is None:
            print(f"  ERROR: {name} has no main()/_run() entry point")
            results.append((name, 1))
            rc = 1
            continue
        code = entry()
        results.append((name, code))
        rc |= code

    print(f"\n{'=' * 62}\n  SUMMARY\n{'=' * 62}")
    for name, code in results:
        print(f"  {'ok  ' if code == 0 else 'FAIL'}  {name}")
    print("\nALL SUITES PASSED" if rc == 0 else "\nSOME SUITES FAILED")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
