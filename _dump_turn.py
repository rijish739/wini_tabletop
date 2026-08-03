import urllib.request
import json

req = urllib.request.Request(
    "http://127.0.0.1:8123/turn",
    data=json.dumps({"text": "Can you show me how prime factorization works?", "speak": False}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST"
)
res = json.loads(urllib.request.urlopen(req, timeout=30).read())
print("KEYS:", list(res.keys()))
for k, v in res.items():
    if k != "answer":
        print(f"{k}: {json.dumps(v, indent=2) if isinstance(v, (dict, list)) else v}")
