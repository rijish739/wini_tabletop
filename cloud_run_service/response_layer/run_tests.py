"""Run every Response Layer / Board Buddy suite in one command.

    python -m response_layer.run_tests

Offline: no Vertex, no torch, no pytest. Exit code is non-zero if any suite fails, so
this is usable as a pre-deploy gate. Skips (e.g. the device-only `figures/` renderer,
absent from the lean Cloud Run image) are reported but do not fail the run.

Baseline recorded 2026-08-02 (Stages 0+1 of BOARD_BUDDY_REGRESSION_AUDIT.md):

    test_board_buddy       34 passed
    test_response_layer    25 passed, 1 skipped (device-only figures/ renderer)
    test_compilers          2 passed
    test_runner_outcomes    3 passed
    test_scene_adaptation   4 passed
    test_screen_cue         4 passed
    ------------------------------------------------
    72 passed, 0 failed, 1 skipped

Verified identical on py3.10 (device-like) and py3.12 (cloud-like), and stable across
repeated runs — test_board_buddy used to be a coin toss because two of its tests reached
live Gemini (see _deterministic_board in that file).
"""

from __future__ import annotations

import importlib

SUITES = (
    "test_board_buddy",
    "test_response_layer",
    "test_compilers",
    "test_runner_outcomes",
    "test_scene_adaptation",
    "test_screen_cue",     # imports tutor_loop; SKIPs on the device venv (no numpy)
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
