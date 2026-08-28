"""Regression cover for the generation-time screen cue (Stage 1 of
BOARD_BUDDY_REGRESSION_AUDIT.md).

The bug this guards: `_response_layer` used to set `figure_on_screen=True` the moment the
Visual Benefit Gate said "earned", while the directive was still
`{"pending_draw": True, "scene": None}`. That emitted the TEXTBOOK cue, which instructs the
generator to say "look at the figure on the screen" — and speech is streamed to TTS
sentence-by-sentence DURING generation (`_stream_answer` -> `sink()`), so the promise was
already spoken before we knew whether a board existed. No post-generation sanitizer can
retract it, which is why `sync_speech_with_visuals` was removed from that path.

So the invariant under test is: a deictic promise is only ever put in the prompt when a
visual is ALREADY on the screen (the crop path), never when one is merely pending.

Imports tutor_loop, which needs numpy/torch — absent from the Pi venv, so this SKIPs there
and runs on the cloud image.

    python -m response_layer.test_screen_cue
"""

from __future__ import annotations

import traceback
from unittest import SkipTest

# The exact phrase the textbook cue tells the model to use, and a phrase unique to the
# pending-board cue. If either literal is reworded in tutor_loop, update it here too.
DEICTIC = "look at the figure on the screen"
NON_DEICTIC = "must stand on their own"

_BLOCKS = [{"source_path": "x", "text": "A quadratic equation is ax^2 + bx + c = 0."}]


def _prompt_for(**kwargs) -> str:
    """Build a real generation prompt, capturing it instead of calling Vertex."""
    try:
        import tutor_loop as T
    except Exception as e:  # noqa: BLE001 — numpy/torch absent on the device venv
        raise SkipTest(f"tutor_loop not importable here: {e}") from e

    captured: dict[str, str] = {}
    original = T.qwen_chat

    def _fake_chat(prompt, temperature=0.3, max_tokens=400, **kw):
        captured["prompt"] = prompt
        return "ok"

    T.qwen_chat = _fake_chat
    try:
        T.qwen_answer("explain quadratics", "EXPLAIN", _BLOCKS,
                      "Class 10 Mathematics", **kwargs)
    finally:
        T.qwen_chat = original
    return captured["prompt"]


def test_crop_on_screen_keeps_the_deictic_cue():
    # A textbook crop really is on the screen before the first word -> pointing is correct.
    p = _prompt_for(figure_on_screen=True, board_pending=False)
    assert DEICTIC in p, "crop path lost its deictic cue"
    assert NON_DEICTIC not in p, "crop path wrongly got the pending-board cue"


def test_pending_board_never_promises_a_figure():
    # THE REGRESSION: board earned but not yet drawn -> must not promise a picture.
    p = _prompt_for(figure_on_screen=False, board_pending=True)
    assert DEICTIC not in p, \
        "pending-board path promises a figure that may never render (streamed to TTS!)"
    assert NON_DEICTIC in p, "pending-board path lost its stand-alone-speech instruction"


def test_speech_only_turn_gets_no_screen_cue():
    p = _prompt_for(figure_on_screen=False, board_pending=False)
    assert DEICTIC not in p and NON_DEICTIC not in p, \
        "speech-only turn should carry no screen cue at all"


def test_response_layer_earned_visual_does_not_set_figure_on_screen():
    """The directive that reaches generation must say pending_draw, not figure_on_screen.

    Guards the specific line that regressed: `figure_on_screen = True` inside the
    `if allowed:` branch of `_response_layer`.
    """
    try:
        import inspect

        import tutor_loop as T
    except Exception as e:  # noqa: BLE001
        raise SkipTest(f"tutor_loop not importable here: {e}") from e

    src = inspect.getsource(T.TutorLoop._response_layer)
    assert '"pending_draw": allowed' in src or '"pending_draw": True' in src, \
        "earned-visual branch must mark the draw as pending"
    assert "return list(mode_cards), False, directive" in src or "figure_on_screen = False" in src, \
        "must NOT claim a figure is on screen before the draw"


# ---------------------------------------------------------------------------
def main() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = failed = skipped = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  PASS {t.__name__}")
        except SkipTest as e:
            skipped += 1
            print(f"  SKIP {t.__name__} ({e})")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped ({len(tests)} total)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
