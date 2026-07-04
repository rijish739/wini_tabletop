import sys, time
sys.path.insert(0, "/home/roavai/ROS2WS_audio_pipeline/cloud CLI")
import numpy as np
from wini_platform.display.wini_display_driver import WiniDisplayDriver, CANVAS_W, CANVAS_H

drv = WiniDisplayDriver()
colors = [("RED",(255,0,0)), ("GREEN",(0,255,0)), ("BLUE",(0,0,255)), ("WHITE",(255,255,255)), ("BLACK",(0,0,0))]
print("panel color test: 4 cycles of RED/GREEN/BLUE/WHITE/BLACK, 1s each", flush=True)
for cycle in range(4):
    for name, rgb in colors:
        frame = np.zeros((CANVAS_H, CANVAS_W, 3), np.uint8)
        frame[:] = rgb
        drv.invalidate()
        drv.push_landscape(frame)
        print(f"cycle {cycle} -> {name}", flush=True)
        time.sleep(1.0)
print("done", flush=True)
