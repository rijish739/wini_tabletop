# Board Buddy LLM Integration & System Prompt Guide

## Executive Summary

**Board Buddy** is the official visual display engine for **Cloud Tutor** (by roavai). This guide defines how Cloud Tutor's AI voice agent (powered by Gemini 2.5 or compatible LLMs) calls Board Buddy, passes structured visual payloads, receives execution feedback, and drives Socratic visual tutoring on the 7" touchscreen display.

---

## 1. System Architecture & Socratic Audio-Visual Co-Execution Flow

```
                               ┌─────────────────────────┐
                               │  Child / Student Input  │
                               └────────────┬────────────┘
                                            │
                                            ▼
                               ┌─────────────────────────┐
                               │   AI Tutor Agent        │
                               │   (Default: Gemini 2.5) │
                               └────────────┬────────────┘
                                            │
               ┌────────────────────────────┴────────────────────────────┐
               │                                                         │
               ▼                                                         ▼
    [ 1. VISUAL TOOL CALL ]                                   [ 2. AUDIO VOICE STREAM ]
  draw_board(payload) with                                    Socratic spoken explanation
  animation duration T_max                                    synced with visual concepts
               │                                                         │
               ▼                                                         │
  Board Buddy 60 FPS Render                                              │
  Animates parameters {var}                                              │
  over T_max                                                             │
               │                                                         │
               └────────────────────────────┬────────────────────────────┘
                                            │
                                            ▼
                               ┌─────────────────────────┐
                               │ Synchronized Child      │
                               │ Experience on Screen    │
                               │ & Speaker               │
                               └─────────────────────────┘
```

### Diagnostic Success Return & Socratic Turn Choices (Static vs. Animated)

1. **Static vs. Animated Diagnostic Timing**:
   - **Static Board Payloads (`has_animation: false`)**: `load_json()` renders the visual scene **immediately** and returns `{"status": "success", "has_animation": false}` instantly.
   - **Animated Board Payloads (`has_animation: true`)**: `load_json()` computes $T_{\text{max}}$. Board Buddy executes the 60 FPS animation loop ($t = 0 \to T_{\text{max}}$). The diagnostic `{"status": "success", "has_animation": true}` response is returned **right after the animation completes** ($t = T_{\text{max}}$).

2. **Agent Turn Control Options**:
   Upon receiving `{"status": "success"}`, the agent chooses its next Socratic action based on teaching intent:
   - **Option A (Interactive Child Pause)**: The agent pauses and waits for the child to speak or touch the display. The child can use the bubbly time scrubber at the bottom to scrub back to any previous state ($0.0\text{s} \dots T_{\text{max}}$) to verify results before answering.
   - **Option B (Immediate Step Continuation)**: The agent immediately proceeds to the next Socratic teaching step or renders the next visual payload without waiting.

### Audio-Visual Co-Execution & Duration Handling
- **No Rigid Duration Limits**: Animation duration $T_{\text{max}}$ is specified by the agent in the payload.
- **Max Duration Rule**: The tutor platform simply waits for whichever is longer (speech audio stream or animation duration $T_{\text{max}}$), or pauses for child interaction if the agent is expecting a child response.

---

## 2. Board Buddy JSON Payload Specification & Tool Examples

Board Buddy is engineered for **single-call multi-tool composite rendering**. A single `draw_board` tool call accepts a flat JSON array (`payload`) containing **multiple visual elements and animations simultaneously**:

```json
[
  { "id": "header", "type": "text", "pos": [30, 20], "text": "Parabola & Number Line", "size": "large" },
  { "id": "stickers_1", "type": "stickers", "pos": [400, 20], "name": "star", "count": 2 },
  { "id": "graph_1", "type": "graph", "pos": [30, 80], "equation": "y = {a:2f} * x^2", "size": "medium" },
  { "id": "numline_1", "type": "numberline", "pos": [30, 480], "hops": ["{hop:int}"], "size": "medium" },
  { "id": "anim_a", "type": "animate_param", "var": "a", "from": -2.0, "to": 2.0, "duration": 4.0 },
  { "id": "anim_hop", "type": "animate_param", "var": "hop", "from": 1, "to": 5, "duration": 4.0 }
]
```

- **Single Tool Call, Multiple Elements**: You can combine text, stickers, geometry, graphs, number lines, fractions, and animations in one single JSON array payload.
- **Concurrent Parameter Animations**: Multiple `animate_param` elements run simultaneously over time $T_{\text{max}}$.
- **No Sequential Round-Trips**: The agent renders the entire multi-element scene at once without issuing multiple separate tool calls.

---

### 🎨 Tool JSON Formats & Examples

#### 1. Text & LaTeX Math (`"type": "text"`)
```json
{
  "id": "header_1",
  "type": "text",
  "pos": [30, 20],
  "text": "Fractions: \\frac{3}{4}",
  "size": "large",
  "color": "#1A237E"
}
```

#### 2. Vector Stickers (`"type": "stickers"`)
```json
{
  "id": "apples_group",
  "type": "stickers",
  "pos": [40, 80],
  "name": "apple",
  "count": [2, 3],
  "size": "large"
}
```

#### 3. Geometry Polygons (`"type": "geometry"`)
```json
{
  "id": "triangle_1",
  "type": "geometry",
  "pos": [300, 80],
  "shape": "triangle",
  "size": "medium",
  "color": "#E91E63"
}
```

#### 4. Function Plotter (`"type": "graph"`)
```json
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
}
```

#### 5. Number Line (`"type": "numberline"`)
```json
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
}
```

#### 6. 2D Area Model Fraction Grid (`"type": "fraction"`)
```json
{
  "id": "area_grid_1",
  "type": "fraction",
  "pos": [320, 480],
  "size": "medium",
  "numerator": ["{num_r:int}", 3],
  "denominator": [3, 4],
  "color": "#E65100",
  "title": "2D Area Model Fraction"
}
```

#### 7. Parameter Animation Engine (`"type": "animate_param"`)
```json
{
  "id": "anim_a",
  "type": "animate_param",
  "var": "a",
  "from": -2.0,
  "to": 2.0,
  "duration": 3.5
}
```

---

## 3. Tutor System Prompt Injection Snippet

Inject the following instruction block into Cloud Tutor's system prompt:

```markdown
### 🎨 VISUAL DISPLAY INSTRUCTIONS (BOARD BUDDY)

You are equipped with a 7" touchscreen display running Board Buddy. Whenever you explain a visual, mathematical, or spatial concept to a child, ALWAYS call the `draw_board` tool alongside your voice response.

#### 📜 Rules for Visual Generation:
1. **Flat Minimal Payloads**: Always pass a clean flat array of elements. Do NOT nest configuration sub-objects.
2. **Use Size Presets**: Use `size: "small"`, `"medium"`, `"large"`, or `"xlarge"`. Do not calculate pixel widths manually.
3. **Variable Placeholder Syntax `{var}`**:
   - To animate a parameter in text, graph equations, fraction numerators, or number lines, insert `{var:int}`, `{var:1f}`, or `{var:2f}` inside the text string.
   - Include a matching `animate_param` element specifying `var`, `from`, `to`, and `duration`.
   - Single curly braces `{}` inside text are automatically processed BEFORE LaTeX rendering.
4. **Triangles**: Use `shape: "triangle"` for standard polygons. Use `shape: "right_triangle"` ONLY when explaining right-angle math (hypotenuse line & square box).
5. **Titles**: Titles automatically render as LaTeX if math symbols are present (`\frac`, `=`, `^`). Do NOT use `\text{}` in titles.
6. **2D Area Model Fractions**: To teach fraction multiplication or grid areas, use 2D arrays: `denominator: [rows, cols]` (e.g. `[3, 4]` for 12 grid squares) and `numerator: [fill_rows, fill_cols]` (e.g. `[2, 3]`).
```

---

## 4. Master Tool Parameter Reference

| Tool `type` | Essential Parameters | Description |
| :--- | :--- | :--- |
| `"text"` | `id`, `pos`, `text`, `size`, `color` | Typography & auto-LaTeX rendering. Supports `{var:int}` placeholders. |
| `"stickers"` | `id`, `pos`, `name`, `count`, `size` | 62 vector stickers (`apple`, `boy`, `girl`, `star`, `car`, etc.). `count` can be 1D (`5`) or 2D (`[2, 3]`). |
| `"geometry"` | `id`, `pos`, `shape`, `size`, `color`, `vertices`, `labels` | Polygon geometry (`circle`, `square`, `rectangle`, `triangle`, `right_triangle`). |
| `"graph"` | `id`, `pos`, `size`, `equation`, `x_range`, `y_range`, `color`, `title` | Function plot canvas (`y = {a:2f} * x^2`, `y = sin(x)`). |
| `"numberline"` | `id`, `pos`, `size`, `min`, `max`, `step`, `hops`, `color`, `title` | Number line axis with tick marks and curved hop arcs (`hops: [3, 5]` or `['{hop:int}']`). |
| `"fraction"` | `id`, `pos`, `size`, `numerator`, `denominator`, `color`, `title` | 1D fraction bars or 2D area grid models (`denominator: [3, 4]`, `numerator: [2, 3]`). |
| `"animation"` | `id`, `target`, `from`, `to`, `motion`, `duration` | Spatial path interpolation (`motion: "slide"`, `"hop"`, `"fade"`). |
| `"animate_param"` | `id`, `var`, `from`, `to`, `duration` | Universal pre-render variable interpolation engine. |

---

## 5. Diagnostic Feedback Return Handling

When Cloud Tutor executes `draw_board(payload)`, `load_json()` returns a diagnostic status dictionary:

```python
# Success Response
{
    "status": "success",
    "loaded_count": 3,
    "element_ids": ["header", "numline_1", "anim_1"],
    "warnings": [],
    "errors": []
}

# Partial Success Response (Soft Warning for LLM Self-Healing)
{
    "status": "partial_success",
    "loaded_count": 2,
    "element_ids": ["header", "numline_1"],
    "warnings": ["Unknown element type 'custom_chart' for id 'item_3'"],
    "errors": []
}
```

If the return status is `"partial_success"` or `"error"`, Cloud Tutor receives the exact warning message in its tool invocation return, allowing it to re-try or correct the payload on its next turn automatically.

---

## 6. Real-World Socratic Teaching Examples

### Example 1: Socratic Counting (5 Apples)
```json
[
  {
    "id": "header",
    "type": "text",
    "pos": [30, 20],
    "text": "Let's count apples together!",
    "size": "large",
    "color": "#2E7D32"
  },
  {
    "id": "apple_group",
    "type": "stickers",
    "pos": [30, 80],
    "name": "apple",
    "count": 5,
    "size": "medium"
  }
]
```

### Example 2: Parabola Morphing Animation ($y = a \cdot x^2$)
```json
[
  {
    "id": "header",
    "type": "text",
    "pos": [30, 20],
    "text": "Parabola Transformation: a = {a:2f}",
    "size": "large",
    "color": "#1A237E"
  },
  {
    "id": "graph_1",
    "type": "graph",
    "pos": [30, 80],
    "size": "medium",
    "equation": "y = {a:2f} * x^2",
    "x_range": [-3, 3],
    "y_range": [-10, 10],
    "color": "#D32F2F",
    "title": "y = {a:2f}x^2"
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
```

### Example 3: Number Line Addition ($3 + 5 = 8$)
```json
[
  {
    "id": "header",
    "type": "text",
    "pos": [30, 20],
    "text": "Addition on Number Line",
    "size": "large",
    "color": "#1565C0"
  },
  {
    "id": "numline_1",
    "type": "numberline",
    "pos": [30, 80],
    "size": "medium",
    "min": 0,
    "max": 10,
    "step": 1,
    "hops": [3, 5],
    "color": "#1976D2",
    "title": "Start at 3, Hop +5 -> Land on 8!"
  }
]
```

### Example 4: 2D Area Model Fraction Multiplication ($\frac{2}{3} \times \frac{3}{4} = \frac{6}{12}$)
```json
[
  {
    "id": "header",
    "type": "text",
    "pos": [30, 20],
    "text": "2D Area Model: \\frac{2}{3} \\times \\frac{3}{4} = \\frac{6}{12}",
    "size": "large",
    "color": "#E65100"
  },
  {
    "id": "fraction_grid",
    "type": "fraction",
    "pos": [30, 80],
    "size": "medium",
    "numerator": [2, 3],
    "denominator": [3, 4],
    "color": "#FF5722",
    "title": "Filled: 2 rows x 3 cols = 6 / 12 Total Squares"
  }
]
```

### Example 5: Kids Catch Game (Spatial Hop Motion)
```json
[
  {
    "id": "boy_1",
    "type": "stickers",
    "pos": [40, 220],
    "name": "boy",
    "count": 1,
    "size": "large"
  },
  {
    "id": "girl_1",
    "type": "stickers",
    "pos": [380, 220],
    "name": "girl",
    "count": 1,
    "size": "large"
  },
  {
    "id": "ball_1",
    "type": "geometry",
    "pos": [120, 240],
    "shape": "circle",
    "size": "small",
    "color": "#FFD54F"
  },
  {
    "id": "throw_ball",
    "type": "animation",
    "target": "ball_1",
    "from": [120, 240],
    "to": [380, 240],
    "motion": "hop",
    "duration": 2.5
  }
]
```

---

## 7. Python Tutor Bridge Module (`tutor_board_bridge.py`)

### 🌉 Purpose & Architectural Role

`tutor_board_bridge.py` is the **lightweight connector module** that integrates Cloud Tutor's AI Voice Backend (Gemini 2.5 API / WebSocket Server) with the Board Buddy rendering engine on the Raspberry Pi 5.

#### Key Responsibilities:
1. **Tool Execution Bridge**: Receives raw JSON payload strings or lists from `draw_board(payload)` tool calls, passes them to `BoardBuddyCanvas.load_json()`, and returns diagnostic feedback (`{"status": "success"}`) back to the AI Agent.
2. **Display Buffer Management**: Allocates the 600×845 Pygame surface on physical screen `DISPLAY=:0` (leaving $Y=800 \dots 845$ for the external bubbly time scrubber bar).
3. **60 FPS Single-Pass Playback**: Runs the 60 FPS animation loop for duration $T_{\text{max}}$, freezes at 100% completion, and handles touchscreen scrubber taps/drags.

---

### 💻 Bridge Class Implementation

```python
import time
import pygame
from board_buddy import BoardBuddyCanvas

class TutorBoardBridge:
    def __init__(self, width=600, height=800, theme="whiteboard"):
        self.canvas = BoardBuddyCanvas(width=width, height=height, theme=theme)
        self.screen = None
        self.clock = None

    def init_pygame_display(self):
        """Initializes Pygame display buffer on physical screen (DISPLAY=:0)."""
        pygame.init()
        # Allocate 600x845 to accommodate external time scrubber bar if animation exists
        self.screen = pygame.display.set_mode((600, 845))
        self.clock = pygame.time.Clock()

    def handle_tool_call(self, payload):
        """
        Tool Execution Bridge: Ingests payload from Gemini API tool call.
        Returns diagnostic dictionary back to the LLM.
        """
        diagnostic_res = self.canvas.load_json(payload)
        return diagnostic_res

    def run_animation_loop(self):
        """Runs single-pass 60 FPS animation loop on Pi 5 display."""
        if not self.screen:
            return

        max_d = self.canvas.get_max_duration()
        start_time = time.time()
        is_scrubbing = False
        scrub_t = 0.0

        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    mx, my = event.pos
                    if my >= 800:
                        if mx <= 50:
                            start_time = time.time()
                            is_scrubbing = False
                        else:
                            st = self.canvas.handle_touch_scrub(mx, my)
                            if st is not None:
                                is_scrubbing = True
                                scrub_t = st
                elif event.type == pygame.MOUSEMOTION and pygame.mouse.get_pressed()[0]:
                    mx, my = event.pos
                    if my >= 800 and mx > 50:
                        st = self.canvas.handle_touch_scrub(mx, my)
                        if st is not None:
                            is_scrubbing = True
                            scrub_t = st

            if max_d > 0:
                if is_scrubbing:
                    progress = scrub_t / max_d
                else:
                    elapsed = time.time() - start_time
                    cur_t = min(elapsed, max_d)  # Single-pass freeze at end
                    progress = cur_t / max_d
            else:
                progress = 1.0

            img = self.canvas.render(anim_progress=progress)
            py_img = pygame.image.fromstring(img.tobytes(), img.size, img.mode)
            self.screen.blit(py_img, (0, 0))
            pygame.display.flip()
            self.clock.tick(60)

            # If static payload or animation completed and not scrubbing, break to yield control
            if max_d == 0 or (not is_scrubbing and time.time() - start_time >= max_d + 1.0):
                break
```
