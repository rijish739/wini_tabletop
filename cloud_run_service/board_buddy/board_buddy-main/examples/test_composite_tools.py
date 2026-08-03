import os
import sys
import time
import pygame
from board_buddy import BoardBuddyCanvas

def main():
    os.environ["SDL_VIDEODRIVER"] = "x11"
    pygame.init()
    screen = pygame.display.set_mode((600, 800))
    pygame.display.set_caption("Composite Tools Test: NumberLine & 2D Fraction Grid")
    clock = pygame.time.Clock()

    # Public Minimal JSON Payload testing NumberLine and 2D Area Model Fraction Grid
    json_payload = [
        {
            "id": "header",
            "type": "text",
            "pos": [30, 15],
            "text": "Composite Tools (NumberLine & 2D Fraction Grid)",
            "size": "large",
            "color": "#1A237E"
        },

        # 1. Number Line with Dynamic Hop Arc Animation
        {
            "id": "numline_demo",
            "type": "numberline",
            "pos": [30, 60],
            "size": "medium",
            "min": 0,
            "max": 10,
            "hops": ["{hop:int}"],                        # Dynamic hop arc interval!
            "color": "#1976D2",
            "title": "Addition on Number Line: {hop:int} Hops"
        },
        {
            "id": "anim_hop",
            "type": "animate_param",
            "var": "hop",
            "from": 1,
            "to": 7,
            "duration": 3.0
        },

        # 2. 2D Area Model Fraction Grid with Dynamic 2D Numerator Sub-Block!
        {
            "id": "fraction_demo",
            "type": "fraction",
            "pos": [30, 260],
            "size": "medium",
            "numerator": ["{num_r:int}", 3],              # Dynamic 2D sub-grid: num_r x 3 filled!
            "denominator": [3, 4],                        # 3 rows x 4 cols = 12 total squares
            "color": "#E65100",
            "title": "2D Area Model Fraction Grid"
        },
        {
            "id": "anim_fraction_rows",
            "type": "animate_param",
            "var": "num_r",
            "from": 1,
            "to": 3,
            "duration": 3.0
        }
    ]

    canvas = BoardBuddyCanvas(width=600, height=800, theme="whiteboard")
    canvas.clear(theme="whiteboard")
    canvas.load_json(json_payload)

    start_time = time.time()
    duration = 3.0  # 3 seconds per cycle

    print("[CompositeToolsTest] Running live 60 FPS Composite Tools test on Pi 5 display...")

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return

        # Ping-pong oscillation loop for live 60FPS visualization
        elapsed = time.time() - start_time
        cycle = (elapsed % (duration * 2)) / duration
        if cycle > 1.0:
            anim_progress = 2.0 - cycle  # Reverse sweep
        else:
            anim_progress = cycle  # Forward sweep

        img = canvas.render(anim_progress=anim_progress)
        py_img = pygame.image.fromstring(img.tobytes(), img.size, img.mode)
        screen.blit(py_img, (0, 0))
        pygame.display.flip()
        clock.tick(60)

if __name__ == "__main__":
    main()
