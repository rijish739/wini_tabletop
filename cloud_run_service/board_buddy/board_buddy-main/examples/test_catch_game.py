import os
import sys
import time
import pygame
from board_buddy import BoardBuddyCanvas

def main():
    os.environ["SDL_VIDEODRIVER"] = "x11"
    pygame.init()
    screen = pygame.display.set_mode((600, 800))
    pygame.display.set_caption("Full-Body Indian Kids Playing Catch Simulation")
    clock = pygame.time.Clock()

    # Pure Black-Box JSON Payload: Full-Body Boy and Girl Playing Catch!
    json_payload = [
        {
            "id": "header",
            "type": "text",
            "pos": [30, 20],
            "text": "Full-Body Indian Kids Playing Catch",
            "size": "large",
            "color": "#1A237E"
        },
        # Left Player: Full-Body Boy Sticker (Large Size)
        {
            "id": "boy_player",
            "type": "stickers",
            "pos": [30, 380],
            "item": "boy",
            "size": "large",
            "label": "Boy"
        },
        # Right Player: Full-Body Girl Sticker (Large Size)
        {
            "id": "girl_player",
            "type": "stickers",
            "pos": [450, 380],
            "item": "girl",
            "size": "large",
            "label": "Girl"
        },
        # Ball Sticker
        {
            "id": "ball",
            "type": "stickers",
            "pos": [75, 410],
            "item": "ball",
            "size": "small"
        },
        # Catch Motion: Parabolic Arc Jump from Boy to Girl!
        {
            "id": "catch_animation",
            "type": "animation",
            "target": "ball",
            "from": [75, 410],
            "to": [455, 410],
            "motion": "hop",
            "duration": 1.5
        }
    ]

    canvas = BoardBuddyCanvas(width=600, height=800, theme="whiteboard")
    canvas.clear(theme="whiteboard")
    canvas.load_json(json_payload)

    start_time = time.time()
    duration = 1.5  # 1.5 seconds per throw

    print("[FullBodyCatch] Running live 60 FPS Full-Body Catch game simulation on Pi 5 display...")

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return

        # Ping-pong loop: Ball throws back and forth between Boy and Girl!
        elapsed = time.time() - start_time
        cycle = (elapsed % (duration * 2)) / duration
        if cycle > 1.0:
            anim_progress = 2.0 - cycle  # Throw back from Girl to Boy
        else:
            anim_progress = cycle  # Throw from Boy to Girl

        img = canvas.render(anim_progress=anim_progress)
        py_img = pygame.image.fromstring(img.tobytes(), img.size, img.mode)
        screen.blit(py_img, (0, 0))
        pygame.display.flip()
        clock.tick(60)

if __name__ == "__main__":
    main()
