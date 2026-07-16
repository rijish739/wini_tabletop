"""Text cards for the display (loading / ready / awake / failed).

Port of jetson_platform/wini_touch_trigger.py `render()` minus the ROS bits:
returns an UN-FLIPPED 480x320 RGB uint8 array (the new display contract — the
driver owns panel orientation) instead of pre-flipped rgb8 bytes.
"""

from __future__ import annotations

import cv2
import numpy as np

W, H = 480, 320
FONT = cv2.FONT_HERSHEY_SIMPLEX

COLOR_INFO = (90, 200, 255)
COLOR_OK = (120, 230, 120)
COLOR_FAIL = (80, 80, 255)
COLOR_PARTIAL = (90, 200, 255)
COLOR_TEXT = (235, 235, 235)
BG = (12, 12, 32)


def render_card(text: str, sub: str = "", color=COLOR_INFO) -> np.ndarray:
    canvas = np.zeros((H, W, 3), np.uint8)
    canvas[:] = (12, 12, 32)
    (tw, _), _ = cv2.getTextSize(text, FONT, 1.5, 3)
    cv2.putText(canvas, text, ((W - tw) // 2, H // 2 - 8), FONT, 1.5,
                color, 3, cv2.LINE_AA)
    if sub:
        (sw, _), _ = cv2.getTextSize(sub, FONT, 0.7, 2)
        cv2.putText(canvas, sub, ((W - sw) // 2, H // 2 + 44), FONT, 0.7,
                    (200, 200, 200), 2, cv2.LINE_AA)
    return canvas


def loading_card(dots: int) -> np.ndarray:
    """Animated 'Loading.' .. 'Loading...' — pass an incrementing tick."""
    return render_card("Loading" + "." * (1 + (dots // 3) % 3),
                       "Wini is waking up")


def ready_card() -> np.ndarray:
    return render_card("Ready!", "say something to Wini", color=COLOR_OK)


def awake_card() -> np.ndarray:
    return render_card("Wini is awake!", "", color=COLOR_OK)


def failed_card(sub: str = "check server.log") -> np.ndarray:
    return render_card("Start failed", sub, color=COLOR_FAIL)


# ---------------------------------------------------------------------------
# Part 12 Stage 4 (§5.6): TEST question / score cards.
# The brain emits channel items {"kind": "question_card"|"score_card", ...};
# the DisplaySink resolves them here to the same UN-FLIPPED 480x320 RGB frame
# the crop path uses. Text is drawn with the built-in cv2 Hershey font (no
# glyph deps), so per-item marks are drawn as shapes, never unicode ticks.
# ---------------------------------------------------------------------------

def _wrap(text: str, scale: float, thickness: int, max_w: int) -> list[str]:
    """Greedy word-wrap `text` to lines that fit within `max_w` px at the given
    cv2 font scale/thickness. A single over-long token is left on its own line."""
    lines: list[str] = []
    cur = ""
    for word in str(text).split():
        trial = f"{cur} {word}".strip()
        (tw, _), _ = cv2.getTextSize(trial, FONT, scale, thickness)
        if tw > max_w and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def question_card(text: str, item_no=None, of=None) -> np.ndarray:
    """Persistent quiz-question card: header ('Question i of n') + wrapped body."""
    canvas = np.zeros((H, W, 3), np.uint8)
    canvas[:] = BG
    header = f"Question {item_no} of {of}" if item_no and of else "Question"
    cv2.putText(canvas, header, (16, 34), FONT, 0.7, COLOR_INFO, 2, cv2.LINE_AA)
    cv2.line(canvas, (16, 46), (W - 16, 46), (60, 60, 90), 1, cv2.LINE_AA)
    lines = _wrap(text, 0.85, 2, W - 32)
    if len(lines) > 6:                          # keep it on one screen; shrink to fit
        lines = _wrap(text, 0.62, 2, W - 32)[:8]
        scale, step, y = 0.62, 30, 84
    else:
        scale, step, y = 0.85, 38, 92
    for ln in lines:
        cv2.putText(canvas, ln, (16, y), FONT, scale, COLOR_TEXT, 2, cv2.LINE_AA)
        y += step
    return canvas


def _draw_mark(canvas, cx: int, cy: int, outcome: str) -> None:
    """One per-item result mark: filled green dot (correct), blue ring (partial),
    red cross (wrong). Shapes, not glyphs — cv2's font has no tick/cross."""
    if outcome == "correct":
        cv2.circle(canvas, (cx, cy), 13, COLOR_OK, -1, cv2.LINE_AA)
    elif outcome == "partial":
        cv2.circle(canvas, (cx, cy), 13, COLOR_PARTIAL, 3, cv2.LINE_AA)
    else:  # wrong / unknown
        cv2.line(canvas, (cx - 10, cy - 10), (cx + 10, cy + 10), COLOR_FAIL, 3, cv2.LINE_AA)
        cv2.line(canvas, (cx - 10, cy + 10), (cx + 10, cy - 10), COLOR_FAIL, 3, cv2.LINE_AA)


def score_card(score=0, of=0, per_item=None, gate=None) -> np.ndarray:
    """End-of-test summary: pass/keep-going banner, big score, per-item marks."""
    canvas = np.zeros((H, W, 3), np.uint8)
    canvas[:] = BG
    passed = gate == "pass"
    accent = COLOR_OK if passed else COLOR_FAIL
    title = "You passed!" if passed else "Keep going!"
    (tw, _), _ = cv2.getTextSize(title, FONT, 1.2, 3)
    cv2.putText(canvas, title, ((W - tw) // 2, 74), FONT, 1.2, accent, 3, cv2.LINE_AA)
    big = f"{score if score is not None else '?'} / {of if of is not None else '?'}"
    (bw, _), _ = cv2.getTextSize(big, FONT, 1.6, 3)
    cv2.putText(canvas, big, ((W - bw) // 2, 158), FONT, 1.6, COLOR_TEXT, 3, cv2.LINE_AA)
    marks = list(per_item or [])
    if marks:
        gap = 44
        x0 = (W - gap * len(marks)) // 2 + gap // 2
        for i, outcome in enumerate(marks):
            _draw_mark(canvas, x0 + i * gap, 224, outcome)
    return canvas


def render_display_card(item: dict):
    """Dispatch a brain display item (by `kind`) to its rendered 480x320 frame,
    or None if it is not a text card (the caller then tries the figure-crop path)."""
    kind = (item or {}).get("kind")
    if kind == "question_card":
        return question_card(item.get("text", ""), item.get("item_no"), item.get("of"))
    if kind == "score_card":
        return score_card(item.get("score", 0), item.get("of", 0),
                          item.get("per_item"), item.get("gate"))
    return None
