import os
import sys
import time
import json
import pygame

# Ensure parent directory is in sys.path for importing board_buddy
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from board_buddy import BoardBuddyCanvas

def main():
    os.environ["SDL_VIDEODRIVER"] = "x11"
    pygame.init()

    payload_path = os.path.join(os.path.dirname(__file__), "master_test_payload.json")
    if not os.path.exists(payload_path):
        payload_path = "examples/master_test_payload.json"

    with open(payload_path, "r", encoding="utf-8") as f:
        raw_json_str = f.read()

    print("==================================================")
    print("[BLACK-BOX JSON TEST] Loading payload from JSON...")
    print("==================================================")

    canvas = BoardBuddyCanvas(width=600, height=800, theme="whiteboard")

    # Ingest raw JSON payload and print returned diagnostic status dictionary
    feedback = canvas.load_json(raw_json_str)

    print("\n[DIAGNOSTIC FEEDBACK RETURNED BY BOARD BUDDY]:")
    print(json.dumps(feedback, indent=2))

    max_d = canvas.get_max_duration()
    print(f"\n[CANVAS STATE] Max Animation Duration = {max_d:.1f}s")
    assert feedback["status"] == "success"
    assert canvas.has_animation() is True

    # Allocate 600 x 845 display surface to fit external bubbly time scrubber bar
    screen = pygame.display.set_mode((600, 845))
    pygame.display.set_caption("Board Buddy Master JSON Black-Box Test")
    clock = pygame.time.Clock()

    start_time = time.time()
    is_scrubbing = False
    scrub_t = 0.0

    print("\n[RUNNER] Running live 60 FPS Master JSON test on Pi 5 display...")
    print("  -> Animation plays ONCE from 0.0s to 4.0s and freezes at completion.")
    print("  -> Tap Play button orb (X <= 50, Y >= 800) to replay.")
    print("  -> Tap/Drag along bottom bar (X > 50, Y >= 800) to scrub time.")

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                if my >= 800:
                    if mx <= 50:
                        start_time = time.time()
                        is_scrubbing = False
                        print("[RUNNER] Replaying animation from 0.0s...")
                    else:
                        st = canvas.handle_touch_scrub(mx, my)
                        if st is not None:
                            is_scrubbing = True
                            scrub_t = st
                            print(f"[RUNNER] Touch scrubbed to t = {scrub_t:.2f}s")

            elif event.type == pygame.MOUSEMOTION and pygame.mouse.get_pressed()[0]:
                mx, my = event.pos
                if my >= 800 and mx > 50:
                    st = canvas.handle_touch_scrub(mx, my)
                    if st is not None:
                        is_scrubbing = True
                        scrub_t = st
                        print(f"[RUNNER] Drag scrubbed to t = {scrub_t:.2f}s")

        if is_scrubbing:
            progress = scrub_t / max_d
        else:
            elapsed = time.time() - start_time
            cur_t = min(elapsed, max_d)  # Single-pass freeze at completion
            progress = cur_t / max_d

        img = canvas.render(anim_progress=progress)
        py_img = pygame.image.fromstring(img.tobytes(), img.size, img.mode)
        screen.blit(py_img, (0, 0))
        pygame.display.flip()
        clock.tick(60)

if __name__ == "__main__":
    main()
