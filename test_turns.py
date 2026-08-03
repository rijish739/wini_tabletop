import urllib.request
import json
import subprocess
import time

inputs = [
    "Can you explain x^2 - 5x + 6 equation, and show me how it is to be solved.",
    "Why you choose -2 and -3? What if I don't know that number?",
    "But how to find those number?",
    "Show me with a real time animation how y = a x squared changes as a grows from 1 to 3.",
    "Give me a real life example of quadratics with everyday objects I can count and see."
]

for i, inp in enumerate(inputs):
    print(f"\n==========================================")
    print(f"=== TURN {i+1}: {inp} ===")
    print(f"==========================================")
    req_body = {"text": inp, "speak": False}
    req = urllib.request.Request(
        "http://127.0.0.1:8123/turn",
        data=json.dumps(req_body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        res = json.loads(urllib.request.urlopen(req, timeout=60).read())
        print("Action:", res.get("action"))
        print("Answer:", res.get("answer"))
        rl_vis = res.get("rl_visual", {})
        print("RL Visual keys:", list(rl_vis.keys()) if rl_vis else None)
        if rl_vis:
            if "bb_payload" in rl_vis:
                print("BB Payload:", json.dumps(rl_vis["bb_payload"], indent=2))
            if "payload" in rl_vis:
                print("Payload:", json.dumps(rl_vis["payload"], indent=2))
            if "raw_tool_call" in rl_vis:
                print("Raw Tool Call:", json.dumps(rl_vis["raw_tool_call"], indent=2))
            if "rendered_board_data_url" in rl_vis:
                print("Rendered Board Data URL present, length:", len(rl_vis["rendered_board_data_url"]))
        
        time.sleep(2)
        # Take screenshot
        shot_cmd = f"cd /home/winipi5/cloud_tutor/cloud-CLI && . pi_game/display_env.sh && shot /tmp/shot_{i+1}.png"
        subprocess.run(["bash", "-c", shot_cmd])
        print(f"Screenshot taken: /tmp/shot_{i+1}.png")
    except Exception as e:
        print("Error during turn:", e)
