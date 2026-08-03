"""Board Buddy tool-coverage + grounding eval (BOARD_BUDDY_FULL_FEATURE_PLAN.md Phase D).

Two modes, one report:

  * **offline (default)** — the deterministic guardrail. For every tool family we feed the
    belt (:func:`board_buddy_author.validate_board_call`) a GROUNDED payload (the tool must
    survive) and an UNGROUNDED variant (it must drop). This proves, with no Vertex and no
    billing, that (a) every tool is reachable and (b) the grounding belt never lets an
    ungrounded number/count/hop/coeff through — the "visuals must be text-aware" mandate.

  * **live (``--live``)** — the authoring coverage. It runs the real author on each concept's
    answer (``author_board_from_answer``, or ``--orchestrator`` for the segment loop) and
    checks the model actually PICKED the routing-table tool for that concept AND fired a
    grounded ``animate_param`` on the "moving" concepts. Billed (one+ Gemini call per case).

Run:
    python -m response_layer.eval_board_coverage              # offline, no Vertex
    python -m response_layer.eval_board_coverage --live       # billed authoring coverage
    python -m response_layer.eval_board_coverage --live --orchestrator
"""
from __future__ import annotations

import sys

from . import board_buddy_caps as caps
from .board_buddy_author import author_board_from_answer, validate_board_call
from .device_profile import WINIPI5_PROFILE

PI = WINIPI5_PROFILE.to_dict()


# name, expected tool, moving?(animation), answer, grounded payload, ungrounded payload
CASES: list[tuple] = [
    (
        "counting", "stickers", False,
        "Let us count seven apples on the board, then add two more to make nine.",
        [{"type": "stickers", "item": "apple", "count": 7, "pos": [40, 120]}],
        [{"type": "stickers", "item": "apple", "count": 8, "pos": [40, 120]}],
    ),
    (
        "add_subtract", "numberline", False,
        "Start at three and hop five to the right, landing on eight.",
        [{"type": "numberline", "min": 0, "max": 10, "hops": [{"start": 3, "end": 8}]}],
        [{"type": "numberline", "min": 0, "max": 10, "hops": [{"start": 3, "end": 9}]}],
    ),
    (
        "fractions", "fraction", False,
        "Three out of the four parts of the bar are shaded, so the fraction is three quarters.",
        [{"type": "fraction", "numerator": 3, "denominator": 4, "pos": [60, 200]}],
        [{"type": "fraction", "numerator": 3, "denominator": 7, "pos": [60, 200]}],
    ),
    (
        "quadratic", "graph", False,
        "The parabola y equals x squared minus five x plus six crosses the x-axis at its roots.",
        [{"type": "graph", "equation": "y = x^2 - 5*x + 6", "x_range": [-2, 6],
          "y_range": [-4, 8]}],
        [{"type": "graph", "equation": "y = 42*x^2"}],
    ),
    (
        "geometry", "geometry", False,
        "Here is a right triangle with the right angle at B and AC as the hypotenuse.",
        [{"type": "geometry", "shape": "right_triangle", "pos": [180, 220],
          "labels": ["A", "B", "C"]}],
        None,                                   # a qualitative shape has no ungrounded variant
    ),
    (
        "formula", "text", False,
        "We use the quadratic formula x equals minus b plus or minus root b squared minus "
        "four a c all over two a.",
        [{"type": "text", "text": "x = (-b ± √(b²-4ac)) / 2a", "pos": [40, 120]}],
        [{"type": "text", "text": "the answer is 4096", "pos": [40, 120]}],
    ),
    (
        "growing_value", "animate_param", True,
        "Watch the parabola open wider as the value a grows from one to three.",
        [{"type": "graph", "equation": "{a}*x^2", "title": "y = {a} x^2"},
         {"type": "animate_param", "var": "a", "from": 1, "to": 3, "duration": 2.5}],
        [{"type": "graph", "equation": "{a}*x^2"},
         {"type": "animate_param", "var": "a", "from": 1, "to": 9, "duration": 2.5}],
    ),
]


def _pass(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label:<34} {detail}")
    return ok


def run_offline() -> int:
    print("=== OFFLINE belt coverage (grounded kept / ungrounded dropped) ===")
    covered: set[str] = set()
    fails = 0
    for name, tool, moving, answer, grounded, ungrounded in CASES:
        kept, _ = validate_board_call(grounded, answer, profile=PI)
        kinds = [e["type"] for e in kept]
        ok = tool in kinds
        if ok:
            covered.add(tool)
        if moving:
            ok = ok and any(e["type"] == "animate_param" for e in kept)
        fails += not _pass(f"{name} -> {tool}", ok, f"kept={kinds}")

        if ungrounded is not None:
            bad, dropped = validate_board_call(ungrounded, answer, profile=PI)
            # A drop is correct: the tool must NOT survive carrying the ungrounded value.
            leaked = any(e["type"] == tool for e in bad)
            fails += not _pass(f"{name} ungrounded dropped", not leaked,
                               f"dropped={dropped[:2]}")

    missing = sorted(set(t for _, t, *_ in CASES) - covered)
    _pass("all tool families covered", not missing, f"missing={missing or 'none'}")
    fails += bool(missing)
    print(f"\noffline: {'OK' if not fails else str(fails) + ' FAIL'} "
          f"| tools covered: {sorted(covered)}")
    return 1 if fails else 0


def run_live(orchestrator: bool = False) -> int:
    print(f"=== LIVE authoring coverage (billed; orchestrator={orchestrator}) ===")
    author = None
    if orchestrator:
        from .board_buddy_orchestrator import author_board_orchestrated

        def author(ans):  # noqa: E306
            out = author_board_orchestrated(ans, profile=PI)
            return (out or {}).get("merged")
    else:
        def author(ans):  # noqa: E306
            return author_board_from_answer(ans, profile=PI)

    fails = 0
    for name, tool, moving, answer, *_ in CASES:
        payload = author(answer) or []
        kinds = sorted({e.get("type") for e in payload})
        ok = tool in kinds
        detail = f"tools={kinds}"
        if moving:
            anim = any(e.get("type") == "animate_param" for e in payload)
            ok = ok and anim
            detail += f" animated={anim}"
        fails += not _pass(f"{name} -> {tool}", ok, detail)
    print(f"\nlive: {'OK' if not fails else str(fails) + ' concept(s) missed the tool'}")
    print("(note: a Class-10 curriculum may route counting/fractions off-domain; a miss here "
          "is an authoring/routing signal, not a belt failure.)")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    live = "--live" in argv
    orch = "--orchestrator" in argv
    rc = run_offline()
    if live:
        print()
        rc |= run_live(orchestrator=orch)
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
