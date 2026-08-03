#!/usr/bin/env python3
"""Quick test: send a text turn and pretty-print the debug layer events."""
import json, subprocess, sys, urllib.request

BASE = "http://127.0.0.1:8123"

# 1. Clear debug buffer
urllib.request.urlopen(urllib.request.Request(BASE+"/debug/clear", data=b"", method="POST"), timeout=5)
print("[clear] debug buffer cleared")

# 2. Send text turn
req = urllib.request.Request(
    BASE+"/turn",
    data=json.dumps({"text": "hello wini, what is a quadratic equation?", "speak": False}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
resp = urllib.request.urlopen(req, timeout=90)
d = json.loads(resp.read())

print("\n=== TURN RESULT ===")
print("ACTION  :", d.get("action"))
print("CONCEPT :", d.get("concept"))
print("MODE    :", d.get("mode"))
ans = (d.get("answer") or "").strip()
print("ANSWER  :", ans[:300] + ("..." if len(ans)>300 else ""))
lms = d.get("latency_ms") or {}
print("LATENCY :", "  ".join(f"{k}={v}ms" for k,v in lms.items()))
diag = d.get("diagnostics") or {}
print("WHY     :", diag.get("why"))
print("SIGNALS :", diag.get("signals"))

# 3. Fetch debug layer events
print("\n=== DEBUG LAYER EVENTS ===")
raw = urllib.request.urlopen(BASE+"/debug/logs?tail=50", timeout=5).read()
entries = json.loads(raw).get("entries", [])
for e in entries:
    ts = (e.get("ts",""))[-12:]
    layer = e.get("layer","??")
    event = e.get("event","")
    fields = {k:v for k,v in e.items() if k not in ("ts","layer","event")}
    fstr = "  ".join(f"{k}={repr(v)}" for k,v in fields.items())
    print(f"  {ts}  [{layer:4s}]  {event:30s}  {fstr}")
