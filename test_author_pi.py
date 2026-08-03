import os
import sys
import json

ans_turn3 = "Look at the figure on the screen. It shows the prime factorisation of numbers. To find the numbers that multiply to 6, we can use prime factorisation."
ans_turn4 = "Watch the curve on your screen. It is a parabola, the graph of y = a x squared. As the value of 'a' grows from 1 to 3, the parabola will become narrower, getting steeper and closer to the y-axis."
ans_turn5 = "Imagine you have 6 marbles. You want to arrange them into a square shape, but you find you have 2 marbles left over."

from response_layer.board_buddy_author import author_board_from_answer, validate_board_call, _author_prompt
from llm_vertex import generate_json
from response_layer.board_buddy_author import _board_element_schema

for idx, (label, ans, want_anim, want_real) in enumerate([
    ("Turn 3", ans_turn3, False, False),
    ("Turn 4", ans_turn4, True, False),
    ("Turn 5", ans_turn5, False, True),
]):
    print(f"=== {label} Authoring Debug ===")
    prompt = _author_prompt(ans, concept_id=None, context=None, profile=None, want_animation=want_anim, want_real_life=want_real)
    try:
        res = generate_json(prompt, response_schema=_board_element_schema(), temperature=0.0, max_output_tokens=700)
        print("Raw LLM output:", json.dumps(res.data, indent=2))
        if res.ok and res.data:
            kept, dropped = validate_board_call(res.data, ans, profile=None)
            print("Kept elements:", json.dumps(kept, indent=2))
            print("Dropped reasons:", dropped)
        else:
            print("LLM call failed or returned empty res:", res)
    except Exception as e:
        print("Exception:", e)
    print()
