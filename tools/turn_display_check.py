"""Ask the LIVE brain a question and print which figure it chose.

The end-to-end check for the T9 teaching visual: `tools/t9_probe.py` reasons over
the store offline, this one goes through the running server, so it also covers
concept resolution — which crop is right depends entirely on which concept the
turn resolved to.

    .venv/bin/python tools/turn_display_check.py "explain the qutub minar example"

NOTE: this runs a REAL turn against the live learner state (unlike
voice/latency_probe.py, which works on a copy). Fine on the dev device; don't
point it at a child's state expecting it to be inert.
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8123"

CASES = [
    "can you explain the qutub minar example in trigonometry",
    "what is the angle of elevation",
    "what is the fundamental theorem of arithmetic",
]


def one(text: str) -> None:
    body = json.dumps({"text": text, "speak": False}).encode("utf-8")
    req = urllib.request.Request(f"{BASE}/turn", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    print(f"\n> {text}")
    print(f"  concept : {d.get('concept')}   action: {d.get('action')}")
    disp = d.get("display") or []
    if not disp:
        print("  FIGURE  : (none)")
    for x in disp:
        print(f"  FIGURE  : {x.get('image_path')}")
        print(f"  why     : {x.get('why')}")
        print(f"  alt     : {(x.get('alt_text') or '')[:100]}")
    lat = d.get("latency_ms") or {}
    print(f"  brain   : {lat.get('brain')} ms")
    print(f"  answer  : {(d.get('answer') or '')[:130]}")


def main() -> int:
    for text in (sys.argv[1:] or CASES):
        try:
            one(text)
        except Exception as e:  # noqa: BLE001
            print(f"\n> {text}\n  FAILED: {e}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
