"""Check the live Wini brain from the LAPTOP — send a text turn to the Cloud Run
brain and print the learner cognitive state + pedagogy decision (the `diagnostics`
block, same data the device prints under --diag).

No key file and no device/mic needed: the laptop's own gcloud login authenticates
(the account has run.invoker on wini-brain), so auth is just a fresh identity token
minted per run via `gcloud auth print-identity-token`.

Stdlib only (urllib + subprocess) — no `requests`/`google-auth` install required.

Usage (from D:\\cloud CLI):
    python tools/laptop_diag.py "what is a quadratic equation"
    python tools/laptop_diag.py "I can't picture a parabola" "show me its graph"
    python tools/laptop_diag.py --mode EXPLAIN "how do I factorise x^2-5x+6"

Note: turns share the DEVICE's learner (same WINI_LEARNER_ID/Firestore state on the
service), so a laptop turn moves the same learner's cognitive state as the device.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request

DEFAULT_URL = "https://wini-brain-4qyd26pvsq-el.a.run.app"


def _gcloud() -> str:
    exe = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if not exe:
        sys.exit("gcloud not found on PATH — run from a shell where `gcloud` works "
                 "(e.g. the bundled google-cloud-sdk/bin on PATH).")
    return exe


def _id_token() -> str:
    """Mint a fresh Google identity token from the active gcloud user account."""
    out = subprocess.run([_gcloud(), "auth", "print-identity-token"],
                         capture_output=True, text=True)
    tok = (out.stdout or "").strip()
    if out.returncode != 0 or not tok:
        sys.exit(f"could not mint an identity token: {out.stderr.strip()[:300]}\n"
                 f"Try `gcloud auth login` first.")
    return tok


def _fmt_diag(d: dict) -> list[str]:
    """Same readout the device client prints (client._fmt_diag), kept in sync."""
    if not d:
        return ["  (no cognitive update — a non-learning turn)"]
    cog = d.get("cognitive") or {}
    lines = []
    why = f" ({d['why']})" if d.get("why") else ""
    mastery = d.get("mastery")
    mastery_s = f" mastery={mastery:.2f}" if isinstance(mastery, (int, float)) else ""
    lines.append(f"  action={d.get('action')}{why}")
    lines.append(f"  need={d.get('need')}  mode={d.get('mode')}  "
                 f"concept={d.get('concept')}{mastery_s}")
    if cog:
        order = ("cognitive_load", "frustration_risk", "confusion", "curiosity",
                 "engagement", "confidence", "boredom")
        parts = [f"{k.replace('_risk', '').replace('cognitive_', '')}={cog[k]:.2f}"
                 for k in order if k in cog]
        parts += [f"{k}={v:.2f}" for k, v in cog.items() if k not in order]
        lines.append("  cognitive: " + "  ".join(parts))
    vis = d.get("visual") or {}
    extras = []
    if d.get("signals"):
        extras.append(f"signals={d['signals']}")
    if vis.get("type"):
        extras.append(f"visual={vis.get('type')}(earned={vis.get('earned')})")
    if d.get("pending_check"):
        extras.append(f"pending_check={d['pending_check']}")
    if d.get("pending_hope"):
        extras.append(f"pending_hope={d['pending_hope']}")
    if d.get("writeback"):
        extras.append(f"graded={d['writeback']}")
    if extras:
        lines.append("  " + "  ".join(extras))
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description="Laptop cognitive-state probe for the "
                                             "live Wini Cloud Run brain.")
    ap.add_argument("texts", nargs="+", help="utterance(s) to send, in order")
    ap.add_argument("--url", default=DEFAULT_URL, help=f"brain URL (default {DEFAULT_URL})")
    ap.add_argument("--mode", default=None, help="X-Wini-Mode: EXPLAIN | PRACTICE | TEST")
    args = ap.parse_args()
    url = args.url.rstrip("/")
    token = _id_token()

    for text in args.texts:
        body = json.dumps({"text": text, "speak": False}).encode()
        req = urllib.request.Request(f"{url}/turn", data=body, method="POST")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json")
        if args.mode:
            req.add_header("X-Wini-Mode", args.mode)
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.loads(r.read().decode())
            ms = int((time.perf_counter() - t0) * 1000)
        except Exception as e:  # noqa: BLE001
            print(f"\n=== {text!r} ===\n  request failed: {e}")
            continue
        ans = (d.get("answer") or "").replace("\n", " ")
        print(f"\n=== {text!r}  ({ms} ms) ===")
        print(f"  Wini: {ans[:220]}{'…' if len(ans) > 220 else ''}")
        for line in _fmt_diag(d.get("diagnostics") or {}):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
