# Board Buddy v1.0 🧊

> **Board Buddy** is the visual display engine for **Cloud Tutor**, an AI-powered tabletop educational companion for kids (ages 4–12) by **roavai**. It renders 60 FPS interactive visual payloads (math graphs, number lines, 2D area fraction grids, vector stickers, geometry, and parameter animations) on a 7" touchscreen display.

---

## 🧊 Version Status: FROZEN v1.0

Board Buddy v1.0 is feature-complete, fully optimized, and frozen. All 7 visual tools, 2D multi-dimensional model support, pre-render variable placeholders, non-intrusive diagnostic feedback, and the bubbly external time scrubber are verified live on Raspberry Pi 5.

---

## 📚 Complete Documentation

- 📕 **[Master Specification & Architecture Guide](docs/BOARD_BUDDY_SPECIFICATION.md)**: Canonical specification covering product vision, canvas engine properties, diagnostic API, complete tool parameter matrix with JSON schemas, and empirical test suite details.
- 📄 **[Architectural & Technical Review](docs/board_buddy_architectural_review.md)**: In-depth analysis of LLM ergonomics, schema design, complexity isolation, 2D area models, 60 FPS rendering pipeline, and edge-case safeguards.
- 📘 **[LLM Integration & System Prompt Guide](docs/board_buddy_llm_integration_guide.md)**: Function calling JSON schemas (Gemini API / OpenAI), Tutor system prompt injection snippets, parameter reference, and 5 real-world Socratic teaching payloads.

---

## 🛠️ Visual Tool Matrix

| Tool `type` | Description & Key Schema Parameters |
| :--- | :--- |
| **`stickers`** | 62 pure vector icons (`apple`, `boy`, `girl`, `star`, `car`, etc.). Supports 1D count (`5`) or 2D grid (`[2, 3]`). |
| **`text`** | Typography with smart auto-LaTeX rendering (`\frac`, `=`, `^`). Supports size presets (`small`, `medium`, `large`, `xlarge`). |
| **`geometry`** | Vector polygon geometry (`circle`, `square`, `rectangle`, `triangle`, `right_triangle`) with relative vertices and vertex labels. |
| **`graph`** | Function plot canvas (`y = {a:2f} * x^2`, `y = sin(x)`) with math viewport ranges (`x_range`, `y_range`). |
| **`numberline`** | Number line axis with tick marks, labels, and curved hop arcs (`hops: [3, 5]` or `['{hop:int}']`). |
| **`fraction`** | 1D fraction bars or 2D area model grids (`denominator: [3, 4]`, `numerator: [2, 3]`). |
| **`animation`** | Low-level spatial path interpolation (`slide`, `hop`, `fade`). |
| **`animate_param`** | Universal pre-render variable interpolation engine (`{var:int}`, `{var:1f}`, `{var:2f}`). |

---

## 🚀 Quickstart & Example Execution

### Prerequisites
```bash
pip install -r requirements.txt
```

### Run Examples on Physical Screen (DISPLAY=:0)
```bash
# 1. Test NumberLine Hops & 2D Area Model Fraction Grid
python3 examples/test_composite_tools.py

# 2. Test Non-Intrusive Diagnostic Feedback API
python3 examples/test_feedback_api.py

# 3. Test Bubbly External Time Scrubber Bar (Single-pass & Touch Scrubbing)
python3 examples/test_time_scrubber.py
```

---

## 📐 Display Viewport & Control Bar Specifications

- **Primary Math Viewport**: 600×800 ($Y = 0 \dots 800$).
- **External Scrubber Bar**: Appended outside viewport ($Y = 800 \dots 845$) when animation elements exist, expanding total display surface to 600×845.

---

## 📄 License & Attribution

Developed by **roavai** for **Cloud Tutor**. All rights reserved.
