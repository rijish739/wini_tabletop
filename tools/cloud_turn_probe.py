"""Probe the live Cloud Run brain's /turn (text) endpoint — for verifying the
Response Layer decision end-to-end (real Gemini perception + generation).

Mints a Google-signed ID token from the device service-account key ($WINI_SA_KEY,
audience = service URL), exactly like wini_client._cloud_run_auth, then POSTs one or
more text turns and prints the turn's `visual` directive + display + latency.

Run on the Pi (has WINI_SA_KEY + google-auth):
    set -a; . ./.env; set +a
    .venv/bin/python -m tools.cloud_turn_probe "what is a quadratic equation" \
        "I can't picture how a parabola looks" --url https://wini-brain-...run.app
"""

from __future__ import annotations

import argparse
import json
import os
import time

import requests


def _auth_header(url: str) -> dict:
    key = os.getenv("WINI_SA_KEY")
    if not key:
        raise SystemExit("WINI_SA_KEY unset — source .env first")
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    creds = service_account.IDTokenCredentials.from_service_account_file(
        key, target_audience=url.rstrip("/"))
    creds.refresh(Request())
    return {"Authorization": f"Bearer {creds.token}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("texts", nargs="+", help="utterances to send as text turns")
    ap.add_argument("--url", default=os.getenv(
        "WINI_SERVER", "https://wini-brain-4qyd26pvsq-el.a.run.app"))
    ap.add_argument("--mode", default=None, help="X-Wini-Mode (EXPLAIN/PRACTICE/TEST)")
    args = ap.parse_args()
    url = args.url.rstrip("/")
    hdr = _auth_header(url)
    hdr["Content-Type"] = "application/json"
    if args.mode:
        hdr["X-Wini-Mode"] = args.mode

    for text in args.texts:
        body = {"text": text, "speak": False}
        t0 = time.perf_counter()
        r = requests.post(f"{url}/turn", headers=hdr, data=json.dumps(body), timeout=60)
        ms = int((time.perf_counter() - t0) * 1000)
        print(f"\n=== '{text}'  (HTTP {r.status_code}, {ms} ms round-trip) ===")
        if r.status_code != 200:
            print(r.text[:400]); continue
        d = r.json()
        ans = (d.get("answer") or "").replace("\n", " ")
        print(f"  concept : {d.get('concept')}   action: {d.get('action')}   mode: {d.get('mode')}")
        print(f"  answer  : {ans[:200]}{'…' if len(ans) > 200 else ''}")
        disp = d.get("display") or []
        print(f"  display : {len(disp)} item(s)"
              + (f" -> {disp[0].get('image_path')}" if disp and isinstance(disp[0], dict)
                 and disp[0].get('image_path') else ""))
        vis = d.get("visual")
        if vis is None:
            print("  visual  : (none — Response Layer not engaged / non-learning turn)")
        else:
            print(f"  visual  : type={vis.get('type')} allowed={vis.get('allowed')} "
                  f"arm_scene={vis.get('arm_scene')} asset={vis.get('asset')}")
            print(f"  reason  : {vis.get('reason')}")
            scene = vis.get("scene")
            if scene and scene.get("beats"):
                lines = [b.get("in", [{}])[0].get("text", "") for b in scene["beats"]]
                print(f"  BOARD (drawn from answer): {lines}")
        lat = d.get("latency_ms") or {}
        keep = {k: lat[k] for k in ("brain", "perception", "answer", "tts_first_chunk", "t9")
                if k in lat}
        print(f"  latency : {keep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
