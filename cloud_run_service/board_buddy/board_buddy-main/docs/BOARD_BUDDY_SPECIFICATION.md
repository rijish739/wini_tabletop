# Board Buddy v1.0 Master Specification & Architecture Guide

## Executive Summary

**Board Buddy** is the official 2D visual display engine for **Cloud Tutor** by **roavai**, a tabletop AI companion designed for kids (ages 4–12). Operating alongside Cloud Tutor's Socratic AI voice agent, Board Buddy renders real-time educational visual cards—including auto-LaTeX math typography, vector counting stickers, geometric polygons, function graphs, number lines, 2D area fraction models, parameter animations, and spatial hop motion—onto a 7" touchscreen display.

---

## 1. Product Vision & Hardware Specifications

### 🎯 Socratic Educational Objectives
- **Visual Scaffolding**: Provide real-time graphical reinforcement for spoken Socratic explanations.
- **Child Ergonomics**: High-contrast, vibrant child-friendly aesthetics with warm vanilla and pastel palettes.
- **Interactive Review**: A bubbly time scrubber bar at the bottom edge allows kids to replay animations or scrub back to verify steps.

### 💻 Hardware & Target SoC Architecture
- **Phase 0 Development Target**: Raspberry Pi 5 (8GB RAM, Broadcom BCM2712 Quad RISC-V/ARM64 2.4GHz, VideoCore VII GPU, Linux / X11).
- **Future Hardware Roadmap**: ESP32-P4NR32 (Dual RISC-V 400MHz, 32MB stacked PSRAM, MIPI-DSI + LVGL / Fast 2D rendering pipeline) to reduce hardware cost.
- **Physical Touchscreen Dimensions**: 7" Touchscreen (**600 × 1024** physical resolution).
- **Primary Visual Viewport**: **600 × 800** pixels ($Y = 0 \dots 800$).
- **Expanded Scrubber Viewport**: **600 × 845** pixels ($Y = 0 \dots 845$), allocating $Y = 800 \dots 845$ for the external time scrubber control panel when animations are present.

---

## 2. System Architecture & Audio-Visual Co-Execution

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

### ⚡ Double-Buffered Render Pipeline
1. **Engine**: Pygame double-buffered surface rendering at **60 FPS**.
2. **Auto-Scaling Guardrails**: Viewport boundaries automatically enforce $X \le 580, Y \le 780$ to guarantee visual elements never bleed off screen or get cropped.
3. **Non-Intrusive Diagnostic Feedback API**: `load_json(payload)` parses JSON payloads and returns diagnostic execution dictionaries:
   ```json
   {
     "status": "success",
     "loaded_count": 9,
     "element_ids": ["header", "stickers_1", "graph_1"],
     "warnings": [],
     "errors": []
   }
   ```
   If malformed JSON or unknown fields are encountered, Board Buddy returns soft diagnostic warnings without crashing or breaking valid visual elements.

### 🛑 Post-Animation Diagnostic Return & Agent Turn Choices
- **Static Payloads (`has_animation: false`)**: `load_json()` renders the visual scene immediately and returns `{"status": "success", "has_animation": false}` instantly.
- **Animated Payloads (`has_animation: true`)**: `load_json()` computes maximum animation duration $T_{\text{max}}$. Board Buddy executes the 60 FPS animation loop ($t = 0 \to T_{\text{max}}$). The diagnostic `{"status": "success", "has_animation": true}` response is returned **right after the animation completes** ($t = T_{\text{max}}$).
- **Agent Pedagogical Choice**:
  - **Option A (Interactive Child Pause)**: The agent pauses for the child to speak or touch the screen. The child can use the bubbly time scrubber at the bottom to inspect previous states ($0.0\text{s} \dots T_{\text{max}}$).
  - **Option B (Immediate Step Continuation)**: The agent proceeds immediately to the next teaching step without waiting.

---

## 3. `BoardBuddyCanvas` Engine API Reference

### Constructor
```python
canvas = BoardBuddyCanvas(width=600, height=800, theme="whiteboard")
```
- `width` (*int*): Visual canvas width in pixels (default: `600`).
- `height` (*int*): Visual canvas height in pixels (default: `800`).
- `theme` (*str*): Color theme preset:
  - `"whiteboard"`: Clean crisp white background (`#FFFFFF`), dark navy grid accents.
  - `"blackboard"`: Deep chalkboard green (`#1B2E1E`), chalk white grid accents.
  - `"paper"`: Warm parchment paper (`#FDFBF7`), subtle sepia grid accents.

### Core Methods

| Method | Return Type | Description |
| :--- | :--- | :--- |
| `load_json(payload)` | `dict` | Ingests a raw JSON string or list payload. Computes $T_{\text{max}}$ and returns a diagnostic status dictionary. |
| `render(anim_progress=1.0)` | `PIL.Image` | Renders the 600×800 canvas (+ 45px external time scrubber if animated) at animation progress $t/T_{\text{max}} \in [0.0, 1.0]$. |
| `get_max_duration()` | `float` | Returns the maximum animation duration $T_{\text{max}}$ in seconds (0.0 if static). |
| `has_animation()` | `bool` | Returns `True` if any animation or parameter morph elements exist in the payload. |
| `set_scrub_time(t)` | `None` | Manually sets animation scrub time $t \in [0, T_{\text{max}}]$. |
| `handle_touch_scrub(x, y)` | `float` or `None` | Processes touchscreen tap/drag events on the bottom scrubber bar ($Y \ge 800$). Returns scrub time $t$. |

---

## 4. Master Tool Parameter Matrix & JSON Specifications

Board Buddy provides **8 visual tools**. A single `draw_board` tool call accepts a flat JSON array containing any combination of these tools simultaneously.

---

### Tool 1: `text` (Text & Auto-LaTeX Math)

#### Purpose & Pedagogical Use Case
Renders titles, Socratic prompts, and mathematical formulas. If text contains math symbols (`\frac`, `=`, `^`, `\sqrt`), Board Buddy automatically compiles and renders it using Matplotlib's LaTeX math engine with a safe text fallback if syntax is incomplete.

#### Parameter Matrix
| Parameter | Type | Required | Default | Bounds / Options | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `id` | `string` | **Yes** | — | Unique string | Identifier (e.g. `"header_1"`) |
| `type` | `string` | **Yes** | — | `"text"` | Tool type |
| `pos` | `array` | **Yes** | — | `[x, y]` ($0 \le x \le 580, 0 \le y \le 780$) | Canvas top-left coordinates |
| `text` | `string` | **Yes** | — | Any text or LaTeX string | Text content or formula (e.g. `"Fractions: \\frac{3}{4}"`) |
| `size` | `string` | No | `"medium"` | `"small"`, `"medium"`, `"large"`, `"xlarge"` | Typography size preset |
| `color` | `string` | No | `"#1A237E"` | Hex color string | Text color |

#### Working Example
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

---

### Tool 2: `stickers` (1D Count & 2D Grid Vector Icons)

#### Purpose & Pedagogical Use Case
Visual counting, grouping, and object stories for young learners. Supports 1D horizontal row counts or 2D grid arrays (e.g. 2 rows × 3 columns).

#### Vector Icon Library
`"apple"`, `"star"`, `"boy"`, `"girl"`, `"car"`, `"pencil"`, `"book"`.

#### Parameter Matrix
| Parameter | Type | Required | Default | Bounds / Options | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `id` | `string` | **Yes** | — | Unique string | Identifier (e.g. `"apples_group"`) |
| `type` | `string` | **Yes** | — | `"stickers"` | Tool type |
| `pos` | `array` | **Yes** | — | `[x, y]` | Top-left position on canvas |
| `name` | `string` | **Yes** | — | Icon name | Vector icon from library |
| `count` | `int` or `array` | No | `1` | `int` $\ge 1$ or `[rows, cols]` | 1D scalar count or 2D grid array |
| `size` | `string` | No | `"medium"` | `"small"`, `"medium"`, `"large"`, `"xlarge"` | Icon size preset |
| `color` | `string` | No | Theme default | Hex color string | Icon color override |

#### Working Example
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

---

### Tool 3: `geometry` (2D Polygon Shapes)

#### Purpose & Pedagogical Use Case
Teaches 2D geometric shapes, angles, and right-triangle hypotenuse concepts (with automatic right-angle square markers).

#### Supported Shapes
`"circle"`, `"square"`, `"rectangle"`, `"triangle"`, `"right_triangle"`, `"polygon"`.

#### Parameter Matrix
| Parameter | Type | Required | Default | Bounds / Options | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `id` | `string` | **Yes** | — | Unique string | Identifier (e.g. `"triangle_1"`) |
| `type` | `string` | **Yes** | — | `"geometry"` | Tool type |
| `pos` | `array` | **Yes** | — | `[x, y]` | Top-left position on canvas |
| `shape` | `string` | **Yes** | — | Shape name | Geometry shape type |
| `size` | `string` | No | `"medium"` | `"small"`, `"medium"`, `"large"`, `"xlarge"` | Geometry size preset |
| `color` | `string` | No | `"#E91E63"` | Hex color string | Shape outline/fill color |
| `vertices` | `array` | No | `None` | `[[x1, y1], [x2, y2], ...]` | Custom polygon vertex offsets |

#### Working Example
```json
{
  "id": "triangle_1",
  "type": "geometry",
  "pos": [300, 80],
  "shape": "triangle",
  "size": "medium",
  "color": "#E91E63",
  "vertices": [[0, 100], [160, 100], [80, 10]]
}
```

---

### Tool 4: `graph` (Function Plotter)

#### Purpose & Pedagogical Use Case
Plots algebraic and trigonometric functions ($y = f(x)$) over Cartesian axes with auto-scaling guardrails. Supports parameter placeholders (`"y = {a:2f} * x^2"`).

#### Parameter Matrix
| Parameter | Type | Required | Default | Bounds / Options | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `id` | `string` | **Yes** | — | Unique string | Identifier (e.g. `"parabola_graph"`) |
| `type` | `string` | **Yes** | — | `"graph"` | Tool type |
| `pos` | `array` | **Yes** | — | `[x, y]` | Top-left position on canvas |
| `equation` | `string` | **Yes** | — | Math expression string | Function $y = f(x)$ (e.g. `"y = {a:2f} * x^2"`) |
| `x_range` | `array` | No | `[-5, 5]` | `[x_min, x_max]` | Math X-axis domain |
| `y_range` | `array` | No | `[-10, 10]` | `[y_min, y_max]` | Math Y-axis range |
| `size` | `string` | No | `"medium"` | `"small"`, `"medium"`, `"large"`, `"xlarge"` | Plot card size preset |
| `color` | `string` | No | `"#388E3C"` | Hex color string | Curve plot color |
| `title` | `string` | No | `None` | Any string | Auto-LaTeX card header title |

#### Working Example
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

---

### Tool 5: `numberline` (Axis $0 \dots N$ & Hop Arcs)

#### Purpose & Pedagogical Use Case
Visualizes counting, addition jumps, and subtraction hops along a horizontal number line with curved hop arcs.

#### Parameter Matrix
| Parameter | Type | Required | Default | Bounds / Options | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `id` | `string` | **Yes** | — | Unique string | Identifier (e.g. `"numline_1"`) |
| `type` | `string` | **Yes** | — | `"numberline"` | Tool type |
| `pos` | `array` | **Yes** | — | `[x, y]` | Top-left position on canvas |
| `min` | `int` | No | `0` | `int` | Number line minimum tick |
| `max` | `int` | No | `10` | `int` | Number line maximum tick |
| `step` | `int` | No | `1` | `int` $\ge 1$ | Tick mark interval step |
| `hops` | `array` | No | `[]` | List of ints or `{var}` strings | List of hop arc intervals (e.g. `["{hop:int}"]`) |
| `size` | `string` | No | `"medium"` | `"small"`, `"medium"`, `"large"`, `"xlarge"` | Number line size preset |
| `color` | `string` | No | `"#1976D2"` | Hex color string | Axis & hop arc color |
| `title` | `string` | No | `None` | Any string | Auto-LaTeX card title |

#### Working Example
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

---

### Tool 6: `fraction` (1D Bars & 2D Area Models)

#### Purpose & Pedagogical Use Case
Renders 1D fraction bars or 2D area grid models to visualize fractions and fraction multiplication (e.g. $\frac{2}{3} \times \frac{3}{4} = \frac{6}{12}$).

#### Parameter Matrix
| Parameter | Type | Required | Default | Bounds / Options | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `id` | `string` | **Yes** | — | Unique string | Identifier (e.g. `"area_grid_1"`) |
| `type` | `string` | **Yes** | — | `"fraction"` | Tool type |
| `pos` | `array` | **Yes** | — | `[x, y]` | Top-left position on canvas |
| `numerator` | `int` or `array` | **Yes** | — | `int` or `[rows, cols]` | 1D scalar filled or 2D sub-grid array |
| `denominator` | `int` or `array` | **Yes** | — | `int` or `[rows, cols]` | 1D scalar total or 2D grid array |
| `size` | `string` | No | `"medium"` | `"small"`, `"medium"`, `"large"`, `"xlarge"` | Model size preset |
| `color` | `string` | No | `"#E65100"` | Hex color string | Grid fill color |
| `title` | `string` | No | `None` | Any string | Auto-LaTeX card title |

#### Working Example
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

---

### Tool 7: `animate_param` (Parameter Morph Engine)

#### Purpose & Pedagogical Use Case
Smoothly morphs mathematical variables (`var`) from a starting value `from` to an ending value `to` over `duration` seconds. Dynamically updates string placeholders in `text`, `equation`, `title`, `hops`, and `numerator`.

#### Parameter Matrix
| Parameter | Type | Required | Default | Bounds / Options | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `id` | `string` | **Yes** | — | Unique string | Identifier (e.g. `"anim_a"`) |
| `type` | `string` | **Yes** | — | `"animate_param"` | Tool type |
| `var` | `string` | **Yes** | — | Variable name | Variable key (e.g. `"a"`, `"hop"`, `"num_r"`) |
| `from` | `number` | **Yes** | — | `float` or `int` | Starting value |
| `to` | `number` | **Yes** | — | `float` or `int` | Ending value |
| `duration` | `number` | **Yes** | — | `duration > 0.0` | Morph duration in seconds |

#### Working Example
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

### Tool 8: `animation` (Spatial Motion Engine)

#### Purpose & Pedagogical Use Case
Animates an element's spatial position `from` $[x_1, y_1]$ `to` $[x_2, y_2]$ with linear translation or curved `hop` arc trajectory.

#### Parameter Matrix
| Parameter | Type | Required | Default | Bounds / Options | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `id` | `string` | **Yes** | — | Unique string | Identifier (e.g. `"move_ball"`) |
| `type` | `string` | **Yes** | — | `"animation"` | Tool type |
| `target` | `string` | **Yes** | — | Target `id` | ID of element to animate |
| `from` | `array` | **Yes** | — | `[x1, y1]` | Starting position |
| `to` | `array` | **Yes** | — | `[x2, y2]` | Ending position |
| `motion` | `string` | No | `"linear"` | `"linear"`, `"hop"` | Trajectory type |
| `duration` | `number` | **Yes** | — | `duration > 0.0` | Motion duration in seconds |

#### Working Example
```json
{
  "id": "move_ball",
  "type": "animation",
  "target": "ball_1",
  "from": [120, 240],
  "to": [380, 240],
  "motion": "hop",
  "duration": 2.5
}
```

---

## 5. Complete Multi-Tool Composite Payload Example

```json
[
  {
    "id": "header",
    "type": "text",
    "pos": [30, 15],
    "text": "Board Buddy v1.0 Master Verification",
    "size": "large",
    "color": "#1A237E"
  },
  {
    "id": "stickers_demo",
    "type": "stickers",
    "pos": [30, 60],
    "name": "girl",
    "count": 2,
    "size": "large"
  },
  {
    "id": "triangle_demo",
    "type": "geometry",
    "pos": [320, 60],
    "shape": "triangle",
    "size": "medium",
    "color": "#E91E63",
    "vertices": [[0, 100], [160, 100], [80, 10]]
  },
  {
    "id": "numline_demo",
    "type": "numberline",
    "pos": [30, 240],
    "size": "medium",
    "min": 0,
    "max": 10,
    "hops": ["{hop:int}"],
    "color": "#1976D2",
    "title": "Number Line: {hop:int} Hops"
  },
  {
    "id": "fraction_demo",
    "type": "fraction",
    "pos": [30, 410],
    "size": "medium",
    "numerator": ["{num_r:int}", 3],
    "denominator": [3, 4],
    "color": "#E65100",
    "title": "2D Area Model Fraction Grid"
  },
  {
    "id": "graph_demo",
    "type": "graph",
    "pos": [30, 580],
    "size": "small",
    "equation": "y = {a:2f} * x^2",
    "x_range": [-3, 3],
    "y_range": [-10, 10],
    "color": "#388E3C",
    "title": "Parabola: a = {a:2f}"
  },
  {
    "id": "anim_hop",
    "type": "animate_param",
    "var": "hop",
    "from": 1,
    "to": 7,
    "duration": 4.0
  },
  {
    "id": "anim_a",
    "type": "animate_param",
    "var": "a",
    "from": -2.0,
    "to": 2.0,
    "duration": 4.0
  },
  {
    "id": "anim_rows",
    "type": "animate_param",
    "var": "num_r",
    "from": 1,
    "to": 3,
    "duration": 4.0
  }
]
```
