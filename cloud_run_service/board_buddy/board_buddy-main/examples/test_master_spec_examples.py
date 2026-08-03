import os
import sys
import time
import json
import pygame

# Ensure parent directory is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from board_buddy import BoardBuddyCanvas

def run_test_suite():
    os.environ["SDL_VIDEODRIVER"] = "x11"
    pygame.init()

    print("==========================================================")
    print("  BOARD BUDDY MASTER SPECIFICATION EMPIRICAL TEST SUITE   ")
    print("==========================================================")

    # Define test cases for every tool example documented in BOARD_BUDDY_SPECIFICATION.md
    test_cases = [
        ("Tool 1: text (LaTeX Math)", [
            {
                "id": "header_1",
                "type": "text",
                "pos": [30, 20],
                "text": "Fractions: \\frac{3}{4}",
                "size": "large",
                "color": "#1A237E"
            }
        ]),
        ("Tool 2: stickers (2D Grid Vector Icons)", [
            {
                "id": "apples_group",
                "type": "stickers",
                "pos": [40, 80],
                "name": "apple",
                "count": [2, 3],
                "size": "large"
            }
        ]),
        ("Tool 3: geometry (Triangle Polygon)", [
            {
                "id": "triangle_1",
                "type": "geometry",
                "pos": [300, 80],
                "shape": "triangle",
                "size": "medium",
                "color": "#E91E63",
                "vertices": [[0, 100], [160, 100], [80, 10]]
            }
        ]),
        ("Tool 4: graph (Function Plotter)", [
            {
                "id": "parabola_graph",
                "type": "graph",
                "pos": [30, 240],
                "size": "medium",
                "equation": "y = {a:2f} * x^2",
                "x_range": [-3, 3],
                "y_range": [-10, 10],
                "color": "#388E3C",
                "title": "Parabola: a = {a:2f}"
            },
            {
                "id": "anim_a",
                "type": "animate_param",
                "var": "a",
                "from": -2.0,
                "to": 2.0,
                "duration": 2.0
            }
        ]),
        ("Tool 5: numberline (Hop Arcs)", [
            {
                "id": "numline_1",
                "type": "numberline",
                "pos": [30, 480],
                "size": "medium",
                "min": 0,
                "max": 10,
                "hops": ["{hop:int}"],
                "color": "#1976D2",
                "title": "Number Line: {hop:int} Hops"
            },
            {
                "id": "anim_hop",
                "type": "animate_param",
                "var": "hop",
                "from": 1,
                "to": 5,
                "duration": 2.0
            }
        ]),
        ("Tool 6: fraction (2D Area Grid Model)", [
            {
                "id": "area_grid_1",
                "type": "fraction",
                "pos": [320, 480],
                "size": "medium",
                "numerator": ["{num_r:int}", 3],
                "denominator": [3, 4],
                "color": "#E65100",
                "title": "2D Area Model Fraction"
            },
            {
                "id": "anim_rows",
                "type": "animate_param",
                "var": "num_r",
                "from": 1,
                "to": 3,
                "duration": 2.0
            }
        ]),
        ("Tool 8: animation (Spatial Motion)", [
            {
                "id": "ball_1",
                "type": "geometry",
                "pos": [120, 240],
                "shape": "circle",
                "size": "small",
                "color": "#FFD54F"
            },
            {
                "id": "move_ball",
                "type": "animation",
                "target": "ball_1",
                "from": [120, 240],
                "to": [380, 240],
                "motion": "hop",
                "duration": 2.0
            }
        ])
    ]

    screen = pygame.display.set_mode((600, 845))
    pygame.display.set_caption("Board Buddy Master Specification Test Suite")
    clock = pygame.time.Clock()

    passed_count = 0
    total_count = len(test_cases)

    for idx, (name, payload) in enumerate(test_cases, start=1):
        print(f"\n[{idx}/{total_count}] Testing {name}...")
        canvas = BoardBuddyCanvas(width=600, height=800, theme="whiteboard")
        feedback = canvas.load_json(payload)

        # Assert diagnostic status success and zero errors
        assert feedback["status"] == "success", f"Failed status for {name}: {feedback}"
        assert len(feedback["errors"]) == 0, f"Errors found for {name}: {feedback['errors']}"
        print(f"  -> Diagnostic Response: status='{feedback['status']}', elements={feedback['loaded_count']}, warnings={len(feedback['warnings'])}")

        # Render start frame (t = 0.0) and end frame (t = 1.0)
        img_start = canvas.render(anim_progress=0.0)
        img_end = canvas.render(anim_progress=1.0)
        assert img_start is not None and img_end is not None

        py_img = pygame.image.fromstring(img_end.tobytes(), img_end.size, img_end.mode)
        screen.blit(py_img, (0, 0))
        pygame.display.flip()
        time.sleep(0.5)

        passed_count += 1
        print(f"  -> PASSED ✓ ({name})")

    # Final Master Composite Payload Test
    print(f"\n[{total_count + 1}/{total_count + 1}] Testing Master Composite Payload...")
    master_path = os.path.join(os.path.dirname(__file__), "master_test_payload.json")
    with open(master_path, "r", encoding="utf-8") as f:
        master_payload = json.load(f)

    canvas_master = BoardBuddyCanvas(width=600, height=800, theme="whiteboard")
    master_feedback = canvas_master.load_json(master_payload)
    assert master_feedback["status"] == "success"
    assert len(master_feedback["errors"]) == 0
    print(f"  -> Diagnostic Response: status='{master_feedback['status']}', elements={master_feedback['loaded_count']}")
    
    img_master = canvas_master.render(anim_progress=1.0)
    py_img_master = pygame.image.fromstring(img_master.tobytes(), img_master.size, img_master.mode)
    screen.blit(py_img_master, (0, 0))
    pygame.display.flip()
    time.sleep(1.0)
    print("  -> PASSED ✓ (Master Composite Payload)")

    print("\n==========================================================")
    print(f"  ALL {total_count + 1} TEST CASES PASSED WITH 100% SUCCESS!")
    print("==========================================================")

if __name__ == "__main__":
    run_test_suite()
