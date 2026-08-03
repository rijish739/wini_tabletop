"""Verify the LLM Board Buddy authoring end-to-end (schema -> belt -> payload).

For each representative tutor ANSWER, call the REAL author (one structured Gemini
call + the grounding belt) and report:
  - which tools the LLM picked
  - whether it triggered animation (animate_param / animation)
  - what the belt kept vs dropped (grounding)
  - the final payload (written to /tmp/bb_payloads/<name>.json for rendering)

Run from the repo root:  .venv/bin/python test_bb_author.py
"""
import json, os, sys, time

sys.path.insert(0, os.path.expanduser("~/cloud_tutor/cloud-CLI"))
from bb_authoring.board_buddy_author import (
    author_board_from_answer, validate_board_call,
    payload_has_animation, tmax_hint,
)

OUT = "/tmp/bb_payloads"
os.makedirs(OUT, exist_ok=True)

# (name, concept, answer) — each chosen to invite a DIFFERENT tool + some animation.
CASES = [
    ("stickers_count",
     "counting_addition",
     "If you have 3 apples and I give you 2 more apples, you now have 5 apples "
     "altogether. Let's count them one by one: 1, 2, 3, 4, 5."),
    ("fraction_half",
     "fractions",
     "One half means 1 part out of 2 equal parts. If we cut a chapati into 2 equal "
     "pieces and take 1 piece, that shaded piece is one half."),
    ("numberline_hop",
     "addition_on_number_line",
     "To add 2 and 3 on a number line, we start at 2 and then hop 3 steps to the "
     "right. Starting at 2 and jumping to 5 lands us on the answer, 5."),
    ("graph_parabola",
     "quadratic_graph",
     "The graph of y = x^2 is a parabola, a U-shaped curve. As the coefficient a "
     "grows from 1 to 3, the parabola becomes narrower and steeper."),
    ("geometry_triangle",
     "triangle_angles",
     "A triangle has 3 sides and 3 angles. No matter its shape, the 3 angles always "
     "add up to 180 degrees."),
    ("animate_hops",
     "skip_counting",
     "Watch the hops grow on the number line from 0. We hop by 2 each time: the "
     "number of hops increases from 1 to 4, landing on 2, 4, 6, and 8."),
]


def brief(payload):
    if not payload:
        return "None"
    return ", ".join(f"{el.get('type')}"
                     f"({','.join(k for k in el if k not in ('id','type','pos','size','color'))})"
                     for el in payload)


def main():
    print("=" * 72)
    for name, concept, answer in CASES:
        print(f"\n### {name}  (concept={concept})")
        print(f"ANSWER: {answer}")
        t0 = time.time()
        try:
            payload = author_board_from_answer(answer, concept_id=concept)
        except Exception as e:  # noqa: BLE001
            print(f"  !! author raised: {type(e).__name__}: {e}")
            continue
        dt = time.time() - t0
        if not payload:
            print(f"  -> author returned None ({dt:.1f}s) — no math-worthy visual")
            continue
        tools = [el.get("type") for el in payload]
        print(f"  tools picked : {tools}")
        print(f"  animation?   : {payload_has_animation(payload)}  tmax={tmax_hint(payload)}s")
        print(f"  detail       : {brief(payload)}")
        with open(f"{OUT}/{name}.json", "w") as f:
            json.dump(payload, f, indent=2)
        print(f"  ({dt:.1f}s)  -> {OUT}/{name}.json")
    print("\n" + "=" * 72)
    print("payloads written to", OUT)


if __name__ == "__main__":
    main()
