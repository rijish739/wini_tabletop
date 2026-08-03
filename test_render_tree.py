import sys
sys.path.insert(0, "/home/winipi5/cloud_tutor/cloud-CLI")
sys.path.insert(0, "/home/winipi5/cloud_tutor/cloud-CLI/board_buddy/board_buddy-main")

import json
import subprocess
from board_buddy import BoardBuddyCanvas

# Render a factor tree payload on screen
payload = [
    {"id": "t1", "type": "text", "text": "Prime Factorization of 6", "pos": [40, 40], "size": "large", "color": "#1B69B6"},
    {
        "id": "tree1", "type": "tree", "root": "6", "pos": [150, 140], "title": "Factor Tree for 6",
        "branches": [{"parent": "6", "children": ["2", "3"]}]
    },
    {"id": "t2", "type": "text", "text": "6 = 2 \\times 3", "pos": [40, 380], "size": "medium", "color": "#271F18"}
]

print("Rendering factor tree payload via BoardBuddyCanvas...")
canvas = BoardBuddyCanvas(600, 800)
canvas.load_json(payload)
img = canvas.render()
img.save("/tmp/factor_tree_board.png", format="PNG")
print("Saved /tmp/factor_tree_board.png!")

# Also send a live turn query to winipi5 brain server
import urllib.request
inp = "But how to find those number?"
print(f"Sending turn query to brain: {inp}")
req = urllib.request.Request(
    "http://127.0.0.1:8123/turn",
    data=json.dumps({"text": inp, "speak": False}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST"
)
try:
    res = json.loads(urllib.request.urlopen(req, timeout=30).read())
    print("Action:", res.get("action"))
    print("Spoken Answer:", res.get("answer"))
    rl_vis = res.get("rl_visual", {})
    print("RL Visual payload:", json.dumps(rl_vis.get("board_payload"), indent=2))
except Exception as e:
    print("Turn error:", e)

# Take screenshot of screen
shot_cmd = "cd /home/winipi5/cloud_tutor/cloud-CLI && . pi_game/display_env.sh && shot /tmp/shot_tree.png"
subprocess.run(["bash", "-c", shot_cmd])
print("Took screenshot /tmp/shot_tree.png")
