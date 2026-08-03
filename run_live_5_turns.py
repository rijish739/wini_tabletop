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
    print(f"=== LIVE TURN {i+1}: {inp} ===")
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
        print("Spoken Answer:", res.get("answer"))
        rl_vis = res.get("rl_visual", {})
        print("Allowed:", rl_vis.get("allowed"))
        print("Arm Scene:", rl_vis.get("arm_scene"))
        print("Board Payload present:", "board_payload" in rl_vis and bool(rl_vis.get("board_payload")))
        if "board_payload" in rl_vis and rl_vis.get("board_payload"):
            print("Board Payload:", json.dumps(rl_vis["board_payload"], indent=2))
        
        # Render the board to /tmp/live_board_<i+1>.png directly via BoardBuddyCanvas so we have a guaranteed rendered artifact
        if rl_vis.get("board_payload"):
            try:
                import sys
                sys.path.insert(0, "/home/winipi5/cloud_tutor/cloud-CLI/board_buddy/board_buddy-main")
                from board_buddy import BoardBuddyCanvas
                canvas = BoardBuddyCanvas(600, 800)
                canvas.load_json(rl_vis["board_payload"])
                img = canvas.render()
                img.save(f"/tmp/live_board_{i+1}.png", format="PNG")
                print(f"Rendered board saved to /tmp/live_board_{i+1}.png")
            except Exception as re_err:
                print("BoardBuddyCanvas render error:", re_err)

        time.sleep(2)
        # Take live screenshot of panel
        shot_cmd = f"cd /home/winipi5/cloud_tutor/cloud-CLI && . pi_game/display_env.sh && shot /tmp/shot_live_turn_{i+1}.png"
        subprocess.run(["bash", "-c", shot_cmd])
        print(f"Panel screenshot taken: /tmp/shot_live_turn_{i+1}.png")
    except Exception as e:
        print("Error during live turn:", e)
