# Board Buddy — Master Architecture & Implementation Plan (V1)
### Interactive 2D Digital Blackboard & AI Tool Suite for Cloud Tutor
**Author:** roavai Engineering Team & AI Assistant  
**Date:** July 28, 2026  
**Target Hardware:** Raspberry Pi 5 (`winipi5.local`) + Waveshare 7.0" DSI Touch Display (Portrait: 600×1024)  
**Target MCU (Phase 1):** ESP32-P4NR32 (32MB PSRAM, MIPI-DSI, ESP-PPA 2D Accel)

---

## 🎯 Executive Summary & Architectural Vision

**Board Buddy** is a high-performance, 2D digital blackboard and AI tool suite built from first principles for **Wini** (the tabletop AI educational tutor).

Instead of fragmented, pop-up UI widgets, Board Buddy provides a **single, unified 2D canvas container ($600 \times 800$ vertical resolution)**. AI agents (such as Gemini 2.5 Flash) call structured visual tools via LLM Function Calling. These tools emit vector primitives, function curves, stickers, and animations onto the shared Board Buddy canvas.

### Key Innovations:
1. **Sub-20ms Vector Rendering:** Replaces multi-second generative AI images with instant, mathematically precise vector graphics and plots.
2. **Seamless Floating Elements (No Forced Container Boxes):** By default, tools render their elements (triangles, graphs, fraction bars, sticker icons) directly onto the Board Buddy whiteboard without forced background boxes or borders (`show_border=False` by default). This allows Wini to combine multiple visual tools seamlessly on one board to explain complex concepts!
3. **Axis Markings & Coordinate Ticks Default:** The graph plotting tool displays Cartesian axis tick marks and coordinate number labels by default (`show_ticks=True`), with a simple toggle option to turn them off (`show_ticks=False`) for qualitative concept views.
4. **Audio-Visual Speech Synchronization:** Interleaved LLM function calls stream alongside spoken audio tokens, ensuring visual animations occur at the exact millisecond Wini speaks about them (<20 ms lag).
5. **Declarative Motion Engine (`animate_element`):** The AI agent specifies high-level movement paths (`line`, `polygon`, `curve`, `hop`). Board Buddy's client renderer interpolates smooth 60 FPS motion with zero AI compute overhead.

---

## 📈 Axis Tick Markings & Coordinate Labels

- **Default Setting:** `show_ticks = True`
- **Behavior:** Renders quantitative tick marks and coordinate number labels (e.g. $-4, -2, +2, +4$) along Cartesian X and Y axes so kids can read exact coordinate values off the graph.
- **Optional Toggle:** AI can pass `show_ticks = False` to render clean, qualitative axes for conceptual explanations.
