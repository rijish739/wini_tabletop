import urllib.request
import json

inp = "Can you show me how prime factorization works?"
print(f"Sending turn: {inp}")

req = urllib.request.Request(
    "http://127.0.0.1:8123/turn",
    data=json.dumps({"text": inp, "speak": False}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST"
)
try:
    res = json.loads(urllib.request.urlopen(req, timeout=30).read())
    print("Action:", res.get("action"))
    print("Answer:", res.get("answer"))
    rl = res.get("rl_visual", {})
    print("allowed:", rl.get("allowed"))
    print("arm_scene:", rl.get("arm_scene"))
    print("board_payload:", json.dumps(rl.get("board_payload"), indent=2))
except Exception as e:
    print("Turn error:", e)
