# Board Buddy ↔ Wini UI Display & Layout Fixes — Complete Technical Summary

## Executive Overview
This document details the root causes identified, code fixes implemented, and live hardware verifications completed for the **Board Buddy** visual display system on Raspberry Pi 5 (`winipi5`).

---

## 1. Key Root Causes & Architectural Fixes

### 1.1 UnboundLocalError in Response Compiler (`tutor_loop.py`)
- **Root Cause**: In `cloud_run_service/tutor_loop.py`, the variables `visuals` and `bb_visual` were instantiated inside an `if _dbg:` block. In production (where `_dbg` is `None`), response compilation threw an unhandled `UnboundLocalError` and silently fell back to a 1-sentence text payload (*"Look at the figure on the screen."*).
- **Fix**: Extracted `bundle`, `beats`, `visuals`, and `bb_visual` outside the `if _dbg:` condition so full Board Buddy payloads (titles, geometry diagrams, step-by-step math equations) are **always compiled and shipped** regardless of debug state.

### 1.2 Native Wayland Surface & Compositor Focus (`board_buddy_sink.py` & `rc.xml`)
- **Root Cause**: `board_buddy_player.py` inherited `DISPLAY=:0` without `WAYLAND_DISPLAY`, causing SDL to default to X11/Xwayland. Additionally, `~/.config/labwc/rc.xml` contained `ignoreFocusRequest="yes"` for `wini-board-buddy`, preventing `labwc` from bringing the Pygame surface to the front.
- **Fix**:
  - Injected `WAYLAND_DISPLAY=wayland-0` and `SDL_VIDEODRIVER=wayland` into `_child_env()` in [board_buddy_sink.py](file:///D:/cloud%20CLI/wini_client/board_buddy_sink.py).
  - Updated `rc.xml` to remove `ignoreFocusRequest="yes"` and added `<action name="Focus"/>` and `<action name="Raise"/>`.

### 1.3 Master UI Card Suppression (`wini_ui/app/app_state.c`)
- **Root Cause**: `wini_ui` (the C/LVGL touch master) was re-rendering `s_explain.explanation` (the "Ask me anything" card) over the 0–845 region during turn events.
- **Fix**: Updated `board_open` and `board_close` handlers in `app_state.c` to explicitly flag `s_explain.explanation` as `LV_OBJ_FLAG_HIDDEN` while `s_board_active == 1`. Recompiled `wini_ui` on `winipi5` (`[100%] Built target wini_ui`).

### 1.4 Board Layout Alignment & Margins (`board_buddy_author.py`)
- **Root Cause**: `_default_pos()` assigned default $X = 300$ (canvas center). Because Pillow draws text starting from the left edge of coordinates, $X = 300$ caused text lines to start at the center line and overflow the right screen border.
- **Fix**: Updated default $X$ to `40` (left margin) in [board_buddy_author.py](file:///D:/cloud%20CLI/cloud_run_service/response_layer/board_buddy_author.py#L162-L167).

---

## 2. Live Verification Results

### 2.1 Multi-Element Payload Generation (Verified 6/6 Elements)
On live execution for the Prayer Hall quadratic prompt:
```json
[
  {
    "id": "el0",
    "type": "text",
    "text": "Quadratic Equation from Area",
    "color": "#271F18",
    "pos": [40, 80]
  },
  {
    "id": "el1",
    "type": "stickers",
    "item": "star",
    "count": 1,
    "pos": [40, 195]
  },
  {
    "id": "el2",
    "type": "geometry",
    "shape": "rectangle",
    "labels": [
      { "text": "x", "pos": [-22, -20] },
      { "text": "2x + 1", "pos": [228, -20] }
    ],
    "pos": [40, 310]
  },
  {
    "id": "el3",
    "type": "text",
    "text": "Area = Length \\times Breadth",
    "color": "#271F18",
    "pos": [40, 425]
  },
  {
    "id": "el4",
    "type": "text",
    "text": "300 = (2x + 1)x",
    "color": "#271F18",
    "pos": [40, 540]
  },
  {
    "id": "el5",
    "type": "text",
    "text": "2x^2 + x = 300",
    "color": "#271F18",
    "pos": [40, 655]
  }
]
```

---

## 3. Modified Code Files

| File Path | Description of Changes |
|---|---|
| [tutor_loop.py](file:///D:/cloud%20CLI/cloud_run_service/tutor_loop.py) | Extracted `visuals` and `bb_visual` outside `if _dbg:` block to fix payload compilation. |
| [board_buddy_sink.py](file:///D:/cloud%20CLI/wini_client/board_buddy_sink.py) | Injected `WAYLAND_DISPLAY=wayland-0` and `SDL_VIDEODRIVER=wayland` in `_child_env()`. |
| [board_buddy_author.py](file:///D:/cloud%20CLI/cloud_run_service/response_layer/board_buddy_author.py) | Aligned default text stack $X$ coordinate to left margin ($X = 40$). |
| `wini_ui/app/app_state.c` | Suppressed `s_explain.explanation` when `s_board_active == 1`. |
