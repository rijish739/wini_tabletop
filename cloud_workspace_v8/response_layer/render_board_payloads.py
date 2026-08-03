"""Render each LLM-authored Board Buddy payload through the REAL board_buddy canvas
(headless PIL) to verify the LLM output schema plots correctly. Also stitches a
labeled montage so all boards are viewable at once.
"""
import json, os, sys, glob

BB = os.path.expanduser("~/board_buddy_sandbox")
sys.path.insert(0, BB)
from board_buddy import BoardBuddyCanvas
from PIL import Image, ImageDraw

SRC = "/tmp/bb_payloads"
OUT = "/tmp/bb_renders"
os.makedirs(OUT, exist_ok=True)

files = sorted(glob.glob(f"{SRC}/*.json"))
tiles = []
for fp in files:
    name = os.path.splitext(os.path.basename(fp))[0]
    payload = json.load(open(fp))
    canvas = BoardBuddyCanvas(width=600, height=800, theme="light")
    diag = canvas.load_json(payload) or {}
    animated = canvas.has_animation()
    # final frame (progress=1.0). For an animated board also grab a mid frame.
    frames = [("final", 1.0)] + ([("mid", 0.5)] if animated else [])
    for tag, prog in frames:
        try:
            img = canvas.render(prog)
        except Exception as e:  # noqa: BLE001 — a render crash is an integration defect to report
            print(f"{name:18s} {tag:5s} RENDER-CRASH: {type(e).__name__}: {e}")
            continue
        out = f"{OUT}/{name}_{tag}.png"
        img.save(out)
        print(f"{name:18s} {tag:5s} animated={animated} warnings={diag.get('warnings')} -> {out}")
        if tag == "final":
            tiles.append((name, out))

# montage: 3 cols
cols = 3
tw, th = 300, 400          # thumbnail size
rows = (len(tiles) + cols - 1) // cols
LABEL = 22
mont = Image.new("RGB", (cols * tw, rows * (th + LABEL)), (255, 255, 255))
d = ImageDraw.Draw(mont)
for i, (name, path) in enumerate(tiles):
    im = Image.open(path).resize((tw, th))
    r, c = divmod(i, cols)
    x, y = c * tw, r * (th + LABEL)
    d.rectangle([x, y, x + tw, y + LABEL], fill=(30, 30, 60))
    d.text((x + 6, y + 4), name, fill=(255, 255, 255))
    mont.paste(im, (x, y + LABEL))
mont.save(f"{OUT}/montage.png")
print("montage ->", f"{OUT}/montage.png")
