# Wini Tutoring System — Complete Step-by-Step Flow

> **Based on**: `wini_server.py`, `wini_ui_server.py`, `tutor_loop.py`, `cognitive_classifier/cues.py`, `response_layer/`, `hope_detector/`, `learner_state.py`

---

## Architecture Overview

```
[Student speaks/types]
        │
        ▼
[wini_server.py] ← HTTP entry point (Cloud Run)
        │
        ├─ STT (Cloud Speech-to-Text)
        │
        ├─ Perception Layer (Gemini Flash)  ←────────── cues.py (regex gates)
        │
        ├─ Grader (speculative, parallel)   ←────────── cues.py (is_pure_ack, is_question)
        │
        ▼
[tutor_loop.TutorLoop.turn()]
        │
        ├─ Front Gate (safety / route)
        ├─ Cognitive Analyzer (learner state update)
        ├─ Pending check / Grade
        ├─ Cohesion check
        ├─ Hope Metrics (KI / KT / CT scoring)
        ├─ Policy / Rules Decision
        ├─ Evidence Retrieval
        ├─ [Response Layer] (Visual Gate → TeachingScript)
        ├─ LLM Answer Generation (Gemini Flash / Qwen)
        │
        ▼
[wini_server text_turn()]
        │
        ├─ TTS (Cloud TTS, Chirp3-HD, streamed)
        ├─ NDJSON stream: filler → audio chunks → turn_meta → final
        │
        ▼
[Board Buddy Orchestrator] (if visual earned)
        │
        ├─ segment loop: decide → draw (Board Buddy) + speak
        ▼
[Device: Pi display + speaker]
```

---

## The Two Servers

### `wini_ui_server.py` — Dev/Test UI (Flask, port 5050)
- A **lightweight Flask bridge** that exposes `TutorLoop` to a browser-based test UI.
- No STT/TTS: accepts raw `{ "text": "..." }` JSON, returns the full turn result.
- Used by developers and testers — **not** deployed to the child's device.
- Key endpoints: `/api/turn`, `/api/state`, `/api/log`, `/api/reset-session`.
- `TutorLoop` is lazy-loaded on the **first `/api/turn` call** (so the server is responsive immediately while models load).

### `wini_server.py` — Production Brain (ThreadingHTTPServer, port 8123)
- The **cloud brain** deployed on Cloud Run.
- The device (Pi) handles mic + speaker + display; **all intelligence runs here**.
- Two POST endpoints:
  - `/turn` — text-only, no audio
  - `/voice_turn` — raw LINEAR16 PCM audio → NDJSON stream
- Security: `X-Wini-Key` header checked before any billed cloud call.
- Brain components loaded **in parallel** on boot (STT, TTS, TutorLoop, Gemini warm-up).

---

## Example Utterance Walkthroughs

---

### 🟦 Example 1: "I don't understand what you mean" (Confusion / Clarification)

#### STEP 1 — HTTP Entry (`wini_server.py`)
- Client sends raw PCM audio to `POST /voice_turn`.
- Server checks `X-Wini-Key` → rejects 401 if wrong.
- Checks `BRAIN.ready` → returns 503 if still loading.
- Opens the NDJSON response stream and calls `BRAIN.voice_turn(pcm, rate, emit=emit)`.

#### STEP 2 — STT (`voice_turn`)
```python
transcript = _bounded(self.stt.recognize_pcm, STT_TIMEOUT_S, pcm, rate)
# → "I don't understand what you mean"
```
- Uses Cloud Speech-to-Text. Hard-bounded at 20 seconds.
- If blank result → returns immediately, client re-listens, no turn consumed.

#### STEP 3 — Speculative Grader (Parallel, Phase B)
```python
grade_future = self._maybe_speculate_grade(transcript)
```
- Looks at `session["pending_check"]` — was a question armed?
- If yes: checks `cues.py`:
  - `is_pure_ack("i don't understand what you mean")` → **False** (has WH context → not an ack)
  - `is_question(...)` → **False** (no `?`, doesn't start with interrogative)
- But: `is_clarification_request(...)` will match (CLARIFY_RE matches "don't understand")
  → This is a **clarification plea**, not an answer attempt → **`grade_future = None`** (grader skipped for obvious non-attempts)

#### STEP 4 — Perception Layer (`pacing.before_turn`)
```python
decision = self.pacing.before_turn(transcript, self.tutor)
```
The **Gemini Flash** perception call runs here. It returns:
```json
{
  "concept": { "concept_id": "jemh101_quadratic", "confidence": 0.7 },
  "signals": ["confusion", "simplification_request"],
  "normalized_text": "i don't understand what you mean",
  "intent": "LEARNING",
  "state_deltas": {
    "confusion": +0.25,
    "curiosity": -0.1
  }
}
```

**Parameters Perception Layer is Dependent On:**
- The raw transcript text
- Current session context (last concept, mode)
- The **9-dimensional cue feature vector** from `cues.py`:
  ```python
  cue_features("I don't understand what you mean")
  # → [0, 0, 1, 0, 0, 0, 0, 0, 0]
  #     q  hint simpl exmpl modl sc-c ans-try nxt conf
  ```
  `simplify_ask` cue fires (SIMPLIFY_RE matches "understand"). This rides as an extra signal alongside the MiniLM embedding for the logistic head in the classifier.
- `CLARIFY_RE` in `cues.py` matches → sets `clarification=True` downstream
- The concept from context (what are we currently explaining?)

#### STEP 5 — Early Filler Emit
```python
emit({"part": "filler", "transcript": "I don't understand what you mean", "concept": "jemh101_quadratic"})
```
- Client gets this **before** the answer is generated.
- Shows transcript, can display "thinking" face, arms the scene for the concept.

#### STEP 6 — `tutor_loop.TutorLoop.turn()` — The Brain
```python
result = self.tutor.turn(text, answer_budget=budget, precomputed_analysis=precomputed)
```

**6a. Front Gate** — `_front_gate(text)`:
- Checks for safety/nonsense/non-learning patterns (deterministic regex).
- "I don't understand" → not safety, not off-domain → `route = None` → falls through to LEARNING.

**6b. Cognitive Analysis + State Update:**
```python
analysis = self.analyzer.analyze_and_apply(text, self.state, ...)
# → applies state_deltas: confusion += 0.25
```
- Learner state now has: `confusion = 0.68`, `curiosity = 0.3`, `frustration_risk = 0.51`

**6c. Cue Extraction** (from `cues.py`):
```python
clarification = is_clarification_request(text)  # True — CLARIFY_RE matches
visualization = is_visualization_request(text)   # False
acknowledged = is_pure_ack(text)                 # False (not an ack)
learning_start = is_learning_request(text)       # False
purpose = is_purpose_question(text)              # False
```

**6d. Pending Check / Grader:**
- There was a pending check (`pending_check = { question: "what is the discriminant?" }`)
- `precomputed_grade = None` (grader was skipped — obvious non-attempt)
- So grade = `not_an_attempt` → **mastery is NOT modified**
- The check remains armed for the next turn.

#### STEP 7 — Cohesion Check
- Cohesion filter runs to ensure retrieved evidence matches the current concept.
- For a clarification, we need the same concept's evidence, **simplified**.
- Cohesion check examines semantic similarity between query and candidate chunks.
- Low-similarity chunks are filtered out.

#### STEP 8 — HOPE Metrics
- `pending_hope` was armed (the last question asked the student to explain in their own words).
- But `"I don't understand"` is not an answer → `is_answer_attempt(text)` = **False**
- HOPE scoring (`KI`/`KT`/`CT`) is **skipped** (no answer to score).
- `hope_update = None`

> **What HOPE scores:**
> - `KI` = Knowledge Integration (can the student connect ideas?)
> - `KT` = Knowledge Transfer (can they apply to new situations?)
> - `CT` = Critical Thinking (can they evaluate/explain reasoning?)
> - Each is an ordinal **0–3**, scored via logistic regression on MiniLM embeddings + scalar features.

#### STEP 9 — Policy / Rules Decision (`rules_decide`)
```python
action, need, reason = rules_decide(
    update={"confusion": 0.68, "frustration_risk": 0.51, ...},
    signals=["confusion", "simplification_request"],
    flags=["simplification_request"],
    abstained=False,
    clarification=True,   # ← This is the KEY flag
    acknowledged=False
)
# → ("EXPLAIN", "explain", "rule 1b: learner did not understand → re-explain...")
```

**Rule Priority Order:**
1. `visual` and not ack → REPRESENTATION_TRANSLATION
2. `purpose` and not ack → WHY_IT_MATTERS
3. **`clarification` and not ack → EXPLAIN** ← **THIS FIRES**
4. learning_start → EXPLAIN
5. misconception_suspected → MISCONCEPTION_PROBE
6. hint_requested → ANALOGOUS_EXAMPLE
7. acknowledged → METACOGNITIVE_REFLECT
8. high load/frustration → ENCOURAGE
9. student_problem → SOLVE_STUDENT_PROBLEM
10. transfer_ready → TRANSFER_PROBLEM
11. representation signals → REPRESENTATION_TRANSLATION
...etc.

#### STEP 10 — Evidence Retrieval
```python
items = need_evidence("explain", concept="jemh101_quadratic", ...)
```
- Retrieves the same concept's chunks, re-ranked by 7-term snapshot (mastery, confusion history, served items filter).
- `served_items` in session prevents re-serving the same evidence block.
- Bridge evidence runs first (prior knowledge activation).
- Cohesion filter ensures the evidence block is semantically coherent with the query.

#### STEP 11 — Response Layer (if `WINI_RESPONSE_LAYER=1`)
- `ResponseContext` is built with: `clarification=True`, `pedagogical_action="EXPLAIN"`, `mode="EXPLAIN"`, `cognitive_load=0.68`
- **Visual Benefit Gate** (`visual_gate.decide(ctx)`):
  - `mode == "EXPLAIN"` ✓
  - `high_load (0.68 >= 0.7)?` → no (just below threshold)
  - `clarification=True` → `wants_visual=False` here (it's a confusion plea, not a picture request)
  - `_is_visual_concept("jemh101_quadratic")?` → depends on concept slug keywords
  - Result → `VisualIntent(allowed=False, reason="reject: concept is better taught verbally this turn")`
- No visual this turn. TeachingScript has one beat: `pedagogical_step="explain"`, `visual_intent.allowed=False`

#### STEP 12 — LLM Answer Generation
```python
answer = qwen_answer(
    question=text,
    action="EXPLAIN",
    evidence_blocks=[...],
    clarify=True,     # ← re-explain more simply flag
    answer_budget={"max_words": 35, "max_sentences": 2}
)
```
- The tone instruction for EXPLAIN with `clarify=True`: re-explain more simply, not a quiz, not a probe.
- The answer is **manifest-grounded** — composed only from the evidence blocks.
- First sentence is released to TTS **before** the full answer exists (streaming path).

#### STEP 13 — TTS + Streaming
```python
feed(first_sentence)  # → Cloud TTS starts synthesizing immediately
emit({"part": "audio", "seq": 0, "audio_b64": ..., "audio_rate": 24000})
```
- Audio chunks stream to client as they are synthesized.
- `turn_meta` line emitted with full turn metadata (concept, mode, visual=None, diagnostics).
- Final line with complete audio.

**Turn result sent back to device:**
```json
{
  "transcript": "I don't understand what you mean",
  "answer": "Let me say it another way. The discriminant tells us how many roots a quadratic has — positive means two real roots, zero means one, negative means none.",
  "action": "EXPLAIN",
  "concept": "jemh101_quadratic",
  "mode": "EXPLAIN",
  "display": [],
  "visual": null,
  "writeback": null,
  "diagnostics": {
    "action": "EXPLAIN",
    "why": "rule 1b: learner did not understand → re-explain more simply",
    "signals": ["confusion", "simplification_request"]
  }
}
```

---

### 🟩 Example 2: "I think the answer is 25" (Answer Attempt with Pending Check)

#### STEP 1-2 — HTTP + STT → `"I think the answer is 25"`

#### STEP 3 — Speculative Grader (PARALLEL)
```python
grade_future = self._maybe_speculate_grade(transcript)
```
- `session["pending_check"] = { "question": "what is 5 squared?", "expected_answer": "25" }`
- Checks `cues.py`:
  - `is_pure_ack("I think the answer is 25")` → **False** (no ACK_RE match)
  - `is_question(...)` → **False** (no `?`)
  - Not a non-attempt → **submit grader concurrently**:
    ```python
    grade_future = _pool.submit(_tl.judge_answer, "what is 5 squared?", "25", "I think the answer is 25")
    ```
- This Gemini call for grading **runs at the same time as perception** — saves ~2s.

#### STEP 4 — Perception Layer
```python
cue_features("I think the answer is 25")
# → [0, 0, 0, 0, 0, 0, 1, 0, 0]
#                         ^answer_try fires (ANSWER_RE matches "i think the answer")
```
- Perception Gemini sees: answer attempt, high confidence
- Signals: `["answer_attempt", "high_confidence"]`

#### STEP 5 — Filler Emit → Client shows "thinking" face

#### STEP 6 — Join Grader
```python
precomputed_grade = grade_future.result(timeout=20)
# → "correct"
```
- Grader ran concurrently; `grade_ms` ≈ 0 (it finished during perception window).
- Result: **"correct"**

#### STEP 7 — `turn()` — Grader writeback
- `is_answer_attempt("I think the answer is 25")` → True
- `is_pure_ack(...)` → False
- `acknowledged = False`
- `precomputed_grade = "correct"` → skips serial grader call
- **Writeback**: mastery EMA updated upward for `jemh101_quadratic`
- `pending_check` cleared from session

#### STEP 8 — HOPE Metrics
- `pending_hope` was set (this was a KT-level question about transfer)
- `HopeDetector.score("KT", prompt="what is 5 squared?", answer="I think the answer is 25", rubric_anchor="...")`
- Returns: `{ "label": 2, "score": 2.1 }` → decent transfer score
- `hope_update = { "KT": 2.1 }` → rolling EMA updated

#### STEP 9 — Policy Rules
```python
rules_decide(update={confusion: 0.2, curiosity: 0.6}, ...)
# → ("METACOGNITIVE_REFLECT", "reflect", "rule 2b: understanding confirmed → reflect + advance")
```
- Wait — `acknowledged=False` (they didn't say "ok I get it", they gave an answer)
- But `update["curiosity"] >= 0.6 and update["confusion"] < 0.4` → rule 7
- Actually: correct answer + low confusion → **SOCRATIC_Q or TRANSFER_PROBLEM**
- `"transfer_ready_evidence" in flags` → True (mastery crossed gate) → **TRANSFER_PROBLEM**

#### STEP 10–12 — Evidence + Answer + TTS
- Evidence: transfer-level chunk (near-transfer problem)
- Answer: poses a new isomorphic problem
- `writeback: { "outcome": "correct" }` → client shows green "✓" feedback cue

---

### 🟥 Example 3: "Show me the animation of parabola" (Visualization Request → Board Buddy)

#### STEP 3 — Speculative Grader
```python
is_pure_ack("show me the animation of parabola") → False
is_question(...) → False
ANSWER_RE.search(...) → False  # no "I think", "= N", etc.
```
- Also `VISUALIZE_RE` matches → but grader check only uses `is_pure_ack` + `is_question`
- `grade_future = None` (no pending check, or skip for non-attempts)

#### STEP 4 — Perception
```python
cue_features("show me the animation of parabola")
# → [0, 0, 0, 0, 1, 0, 0, 0, 0]
#              modality_ask fires (MODALITY_RE matches "animation")
```
- Signals: `["request_representation", "graphical"]`

**New in cues.py (2026-07-30):**
```python
is_visualization_request("show me the animation of parabola")
# VISUALIZE_RE matches: "show ... animation"
# → True ← DIRECT VISUAL REQUEST
```
This is the **dominant Board Buddy no-launch cause** that was recently fixed. Previously `wants_visual` stayed `False` because the old gate only looked at "I cannot picture it" — now `VISUALIZE_RE` catches **direct imperative visual requests** like "show me the animation".

#### STEP 5 — Filler: `{ "rl": true, "concept": "jemh102_parabola" }`
- `rl=True` tells the client: **wait for turn_meta's visual directive** before arming a scene.
- Don't concept-default-arm a scene yet — the Response Layer will decide.

#### STEP 6–7 — `turn()` Cue Analysis
```python
visualization = is_visualization_request("show me the animation of parabola")
# → True
```
- `visual=True` → passed to `rules_decide`

#### STEP 9 — Policy Rules
```python
rules_decide(visual=True, acknowledged=False, ...)
# rule 1a-vis fires:
# → ("REPRESENTATION_TRANSLATION", "integrate", "rule 1a-vis: learner cannot picture it → switch representation")
```

#### STEP 10 — Response Layer (`WINI_RESPONSE_LAYER=1`)
**`ResponseContext` built with:**
```python
ctx = ResponseContext(
    pedagogical_action="REPRESENTATION_TRANSLATION",
    wants_visual=True,          # ← set because VISUALIZE_RE fired
    concept_id="jemh102_parabola",
    concept_type="graph",       # ← concept graph node type
    available_scene_concept_id="jemh102_parabola",  # authored scene exists
    cognitive_load=0.3,
    mode="EXPLAIN",
    device_profile={"display_present": True, "renderer": "pillow_lvgl", "supports_board_buddy": True}
)
```

**Visual Benefit Gate (`visual_gate.decide(ctx)`):**
```python
remedy = _representation_remedy(ctx)
# ctx.wants_visual = True → True

visual_concept = _is_visual_concept(ctx)
# "graph" + "parabola" in concept → True

high_load = 0.3 >= 0.7 → False

# ALLOW CONDITIONS:
# remedy = True → "allow: representation gap — a picture closes it"

return VisualIntent(
    visual_type=VisualType.GENERATED_DECLARATIVE_SCENE_SPEC,
    allowed=True,
    reason="allow: representation gap — a picture closes it",
    asset_ref=None,
    representation_target="graph"
)
```

**TeachingScript produced:**
```
beats:
  - beat_id: "beat_001"
    pedagogical_step: "representation_translation"
    visual_intent: { visual_type: "generated_declarative_scene_spec", allowed: true }
    assessment_hook: null
```

#### STEP 11 — Board Buddy Orchestrator
After the answer is generated, the `BoardSegmentOrchestrator` is invoked **because visual was earned**:

```python
brief = """
Teaching goal: Show the parabola animation for y = x²
Concept: jemh102_parabola (quadratic equation)
Grounding evidence: "A parabola y = x² is a U-shaped curve symmetric about the y-axis..."
"""

orchestrator = BoardSegmentOrchestrator(
    brief=brief,
    profile=device_profile,
    decide=vertex_segment_decider(brief, profile),  # Gemini Flash
    emit=emit_to_device,    # wire verb callback
    wait_ack=wait_for_device_ack,
    max_segments=6,
    board_budget=4
)
orchestrator.run()
```

**Segment Loop (controlled by LLM, not audio):**

**Segment 1 — LLM decides:**
```python
# _segment_prompt provides:
# - Teaching brief (goal + grounding)
# - Drawing tools manifest (TOOL_SCHEMAS)
# - Routing hints (TOOL_ROUTING: "quadratic/parabola/plot → graph")
# - Budget info: 6 segments left, 4 board draws left
# - Spoken so far: (nothing)

# LLM returns:
{
  "speech": "A parabola is a U-shaped curve. Let me show you y equals x squared.",
  "board_call": {
    "elements": [
      { "type": "graph", "id": "g1", "equation": "x^2", "x_range": [-4, 4], "y_range": [0, 16], "title": "y = x²" }
    ]
  },
  "done": false
}
```

**Grounding Belt (`validate_board_call`):**
- Checks every element against `TOOL_SCHEMAS["graph"]` — required params present? ✓
- Checks `grounded_text`: `equation="x^2"` → must be traceable to spoken text or answer
  - "x squared" is in the speech → ✓
- Position clamped to drawable area (600×800px)
- `kept = [{ "type": "graph", "equation": "x^2", ... }]`

**Wire Verbs emitted:**
```python
emit({"cmd": "board_open"})
emit({"cmd": "board", "payload": [{"type": "graph", "equation": "x^2", ...}], "tmax": 2.5, "animated": False})
emit({"cmd": "speak", "text": "A parabola is a U-shaped curve. Let me show you y equals x squared."})
wait_ack({"speech": True, "animation": False})
```

**Segment 2 — LLM decides:**
```python
# State handed to LLM:
{
  "brief": "...",
  "spoken_so_far": "A parabola is a U-shaped curve. Let me show you y equals x squared.",
  "segments_done": 1,
  "segments_left": 5,
  "board_calls_left": 3,
  "board_open": true
}

# LLM returns:
{
  "speech": "See how both sides of the curve go upward? That is because squaring any number gives a positive result.",
  "board_call": {
    "elements": [
      { "type": "text", "id": "t1", "text": "(-3)² = 9 and (3)² = 9", "pos": [60, 50], "size": "medium" }
    ]
  },
  "done": false
}
```

**Segment 3 — LLM decides `done: true`** → loop ends.

**Board Buddy `board_close` emitted.** TurnResult logged.

---

## How Response Layer Connects to Board Buddy

```
tutor_loop.turn()
    └─ _response_layer(ctx) [WINI_RESPONSE_LAYER=1]
           │
           ├─ build_response_context(turn_state)  → ResponseContext
           │
           ├─ TeachingScriptPlanner.plan(ctx)
           │         └─ visual_gate.decide(ctx)   → VisualIntent (allowed/not)
           │
           ├─ ScriptValidator.validate(script)     → script.validation["ok"]
           │
           └─ returns TeachingScript
                      │
                      └─ first_visual_beat().visual_intent.allowed == True?
                                 │
                                 ▼ YES
                         BoardSegmentOrchestrator(brief, profile, ...)
                                 │
                                 └─ vertex_segment_decider(brief)  → Gemini Flash
                                           │
                                           ▼ per segment:
                                    { "board_call": {...}, "speech": "...", "done": bool }
                                           │
                                    validate_board_call(belt) → kept, dropped
                                           │
                                    emit: board_open / board / speak / board_close
```

---

## Parameters Passed by Response Layer to Board Buddy

The `BoardSegmentOrchestrator` receives:

| Parameter | Source | Description |
|-----------|--------|-------------|
| `brief` | TeachingScript + evidence manifest | The teaching goal, concept, grounding evidence, representation target |
| `profile` | DeviceCapabilityProfile | `board_buddy_tools`, `board_buddy_sticker_names`, `display_present`, `supports_board_buddy`, renderer |
| `decide` | `vertex_segment_decider(brief, profile)` | Gemini Flash closure, one structured call per segment |
| `emit` | wini_server wire verb callback | `board_open`, `board`, `speak`, `board_close` |
| `wait_ack` | Device round-trip callback | Blocks until `{speech: True, animation: True}` or interrupt |
| `max_segments` | `DEFAULT_MAX_SEGMENTS = 6` | Budget cap on LLM turns |
| `board_budget` | `DEFAULT_BOARD_BUDGET = 4` | Cap on board draw calls per turn |

---

## What Board Buddy Can Take as Input

Board Buddy is a **pure executor** — it receives **wire verbs** from the orchestrator:

| Wire Verb | Params | What it does |
|-----------|--------|--------------|
| `board_open` | — | Opens the board surface (LVGL/pygame) |
| `board` | `payload: [elements]`, `tmax: float`, `animated: bool` | Renders the element list on screen |
| `board_close` | — | Closes/hides the board |
| `speak` | `text: str` | Routes to Cloud TTS, plays audio |

**Board elements** (`board` payload) use these 8 tools (from `board_buddy_caps.py`):

| Tool | Teaching Use | Required Params |
|------|-------------|-----------------|
| `text` | Formula / definition / worked step (LaTeX-capable) | `text`, `pos` |
| `stickers` | Counting / grouping (icon arrays) | `item`, `count`, `pos` |
| `geometry` | Shapes, angles, triangles, area | `shape`, `pos` |
| `graph` | Plot y=f(x) (parabola/line) | `equation` |
| `numberline` | Addition/subtraction hops | `hops` |
| `fraction` | Fraction bar / grid | `numerator`, `denominator`, `pos` |
| `animate_param` | Morph a `{var}` placeholder over time | `var`, `from`, `to`, `duration` |
| `animation` | Move an element (slide/hop/bounce) | `target`, `to` |

**Viewport:** 600×800 px; coordinates clamped to `[0..580, 0..780]`.
**Max elements per board call:** 12 (legibility constraint).

---

## How Board Buddy is Controlled

1. **LLM is the master clock** — not audio duration, not a fixed timer.
2. Each segment, the LLM independently sees: `brief`, `spoken_so_far`, `segments_left`, `board_calls_left`, `board_open`.
3. LLM decides: draw + speak, speak only, draw only, or `done=true`.
4. After each segment, `wait_ack` blocks until the device signals completion (speech done + animation done), OR signals `interrupt`.
5. On interrupt → `result.interrupted = True`, loop exits.
6. On budget exhaustion (`segments >= max_segments`) → `stop_reason = "budget"`.
7. `board_open` and `board_close` are **emitted once per turn** — the LLM reuses the open board across segments (never re-draws what's already shown).
8. The **grounding belt** (`validate_board_call`) deterministically drops any element whose numeric values are not traceable to what was spoken — so the LLM cannot put "x = 5" on the board unless "five" or "5" appeared in the speech.

---

## cues.py Dependency Map

`cues.py` is used in **two distinct roles**:

### Role 1: Feature Vector for the MiniLM Classifier
```python
cue_features(text) → np.ndarray([9 binary floats])
# [q_form, hint_ask, simplify_ask, example_ask, modality_ask,
#  self_corr, answer_try, move_next, confident]
```
- Appended to the MiniLM sentence embedding for the **logistic regression head**.
- These 9 cues re-surface signals that the mean-pool embedding dilutes (e.g., "just give hint" = 4 weak tokens overwhelmed by 20 words of louder content).
- **Note:** changing CUE_NAMES requires a full classifier + policy shadow rebuild.

### Role 2: Standalone Runtime Guards (outrank the classifier)
These are **deterministic and can never be wrong** by design:

| Cue Function | Regex | Purpose |
|---|---|---|
| `is_pure_ack()` | `ACK_RE` | Pure acknowledgment → consolidate, never re-explain |
| `is_question()` | `INTERROGATIVE_FIRST` + `?` | Question form → answer the question |
| `is_clarification_request()` | `CLARIFY_RE` | Confusion plea → re-explain simply |
| `is_visualization_request()` | `VISUALIZE_RE` | "Show me"/"I can't picture" → switch to visual |
| `is_purpose_question()` | `PURPOSE_RE` | "Why learn this?" → answer why |
| `is_learning_request()` | `LEARN_REQUEST_RE` | "Teach me X" → explain, never quiz |
| `extract_topic_request()` | `TOPIC_REQUEST_RE` | "I asked about X" → topic shift |
| `wants_different_topic()` | `DIFFERENT_TOPIC_RE` | "Something else" → chapter menu |
| `is_bare_topic()` | shape rules | "Trigonometry." → infer topic shift |
| `is_answer_attempt()` | `ANSWER_RE` | "I think it's 5" → protect from non-attempt guard |
| `is_stop_test_request()` | `STOP_TEST_RE` | "Stop the test" → exit to EXPLAIN |
| `is_test_request()` | `TEST_REQUEST_RE` | "Test me" → switch to TEST mode |
| `is_practice_request()` | `PRACTICE_REQUEST_RE` | "Let's practice" → switch to PRACTICE |
| `is_explain_request()` | `EXPLAIN_REQUEST_RE` | "Back to learning" → switch to EXPLAIN |

---

## Learner State & Grade

### Learner State (`learner_state.py`)
The `state.data` dict holds:
- `mastery[concept_id]` — EMA float `[0, 1]`, updated on graded turns
- `misconceptions[concept_id]` — list of confirmed misconception IDs
- `session` — turn-scoped: `current_concept`, `context` (last 8 exchanges), `pending_check`, `pending_hope`, `test_state`, `practice_plan`, `served_items`, `bridges_served`
- `hope` — rolling HOPE EMA per signal (KI, KT, CT)

### Grade
- `judge_answer(question, expected, transcript)` — Gemini Flash returns one of:
  - `"correct"`, `"incorrect"`, `"partially_correct"`, `"not_an_answer"`
- **Writeback** on correct/incorrect: mastery EMA updated, misconception flags cleared/set.
- **Not updated** on `not_an_answer` or clarification pleas.
- State persisted to **Firestore** (Cloud Run) or local JSON at every turn boundary.

---

## Cohesion Check

- `cohesion_filter(candidates, query, threshold)` — filters retrieved evidence chunks.
- Uses MiniLM cosine similarity between the query embedding and candidate chunk embeddings.
- Chunks below the threshold are dropped before being passed to the LLM.
- Prevents the model from generating an answer grounded in an off-topic chunk that happened to be in the same chapter.

---

## Streaming Architecture (Part 13 Stages 1 + 2)

```
turn()
  → first sentence generated
      → feed(first_sentence) to text_q
          → TTS worker opens gRPC stream
              → emit({"part": "audio", "seq": 0, ...})   ← client hears Wini
  → rest of answer generated
      → feed(rest) to text_q
          → more audio chunks → emit
  → full answer decided
      → emit({"part": "turn_meta", ...})   ← client updates display
  → finish()
      → emit(final turn JSON with audio_streamed: true)
```

Child **hears the first sentence** while the rest of the answer is still being generated. `turn_meta` (which carries the visual directive) can land a second or two into the answer — the trade is deliberate: hearing Wini faster > seeing the figure at t=0.

---

## Key Env Flags

| Flag | Default | Effect |
|------|---------|--------|
| `WINI_STREAM_TTS=1` | ON | Stream TTS audio chunks as they synthesize |
| `WINI_STREAM_GEN=1` | ON | Release first sentence to TTS before full answer exists |
| `WINI_PARALLEL_GRADER=1` | ON | Grade concurrently with perception (saves ~2s) |
| `WINI_RESPONSE_LAYER=1` | OFF | Enable TeachingScript + Visual Benefit Gate + Board Buddy |
| `WINI_FILLERS=1` | OFF | Spoken filler audio before answer (else: "thinking" face only) |
| `WINI_STATE_BACKEND=firestore` | local | Persist learner state to Firestore |
| `GEN_BACKEND=gemini` | qwen | Use Vertex Gemini Flash instead of local Qwen |
