import os
import sys
import time
import pygame
from board_buddy import BoardBuddyCanvas

def main():
    os.environ["SDL_VIDEODRIVER"] = "x11"
    pygame.init()

    # Board Buddy Viewport: 600 x 800, expanded to 600 x 845 with Time Scrubber control panel!
    screen = pygame.display.set_mode((600, 845))
    pygame.display.set_caption("Board Buddy Time Scrubber Test")
    clock = pygame.time.Clock()

    anim_payload = [
        {
            "id": "header",
            "type": "text",
            "pos": [30, 20],
            "text": "Single-Pass Animation & Time Scrubber",
            "size": "large",
            "color": "#1A237E"
        },
        {
            "id": "parabola",
            "type": "graph",
            "pos": [30, 80],
            "size": "medium",
            "equation": "y = {a:2f} * x^2",
            "x_range": [-3, 3],
            "y_range": [-10, 10],
            "color": "#D32F2F",
            "title": "Parabola Morph: a = {a:2f}"
        },
        {
            "id": "anim_a",
            "type": "animate_param",
            "var": "a",
            "from": -3.0,
            "to": 3.0,
            "duration": 4.0
        }
    ]

    canvas = BoardBuddyCanvas(width=600, height=800, theme="whiteboard")
    res = canvas.load_json(anim_payload)
    max_d = canvas.get_max_duration()

    print(f"[TimeScrubberTest] Payload loaded cleanly. Max Duration = {max_d}s")
    assert canvas.has_animation() is True
    assert max_d == 4.0

    start_time = time.time()
    is_scrubbing = False
    scrub_t = 0.0

    print("[TimeScrubberTest] Running live 60 FPS Time Scrubber test on Pi 5 display...")
    print("  -> Animation plays ONCE from 0.0s to 4.0s and freezes at the end.")
    print("  -> Click/Tap Play button (X <= 50, Y >= 800) to replay from 0.0s.")
    print("  -> Click/Drag along bar (X > 50, Y >= 800) to scrub time.")

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                if my >= 800:
                    if mx <= 50:
                        # Tapped Play/Replay icon on left
                        start_time = time.time()
                        is_scrubbing = False
                        print("[TimeScrubberTest] Replaying animation from 0.0s...")
                    else:
                        # Tapped along scrubber bar track
                        scrubbed_t = canvas.handle_touch_scrub(mx, my)
                        if scrubbed_t is not None:
                            is_scrubbing = True
                            scrub_t = scrubbed_t
                            print(f"[TimeScrubberTest] Touch scrubbed to t = {scrub_t:.2f}s")

            elif event.type == pygame.MOUSEMOTION and pygame.mouse.get_pressed()[0]:
                mx, my = event.pos
                if my >= 800 and mx > 50:
                    scrubbed_t = canvas.handle_touch_scrub(mx, my)
                    if scrubbed_t is not None:
                        is_scrubbing = True
                        scrub_t = scrubbed_t
                        print(f"[TimeScrubberTest] Drag scrubbed to t = {scrub_t:.2f}s")

        # Determine animation progress
        if is_scrubbing:
            anim_progress = scrub_t / max_d
        else:
            elapsed = time.time() - start_time
            cur_t = min(elapsed, max_d)  # Single-pass: stops at max_d!
            anim_progress = cur_t / max_d

        img = canvas.render(anim_progress=anim_progress)
        py_img = pygame.image.fromstring(img.tobytes(), img.size, img.mode)
        screen.blit(py_img, (0, 0))
        pygame.display.flip()
        clock.tick(60)

if __name__ == "__main__":
    main()
