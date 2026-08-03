import urllib.request, json
r = urllib.request.urlopen("http://localhost:8123/debug/logs?tail=15", timeout=5)
data = json.loads(r.read())
print(f"Total entries in buffer: {len(data['entries'])}")
print()
for e in data["entries"]:
    layer = e.get("layer","??")
    event = e.get("event","")
    fields = {k:v for k,v in e.items() if k not in ("ts","layer","event")}
    fstr = "  ".join(f"{k}={v}" for k,v in fields.items())
    print(f"  [{layer:4s}]  {event:32s}  {fstr}")
