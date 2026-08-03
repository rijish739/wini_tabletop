# Board Buddy / tutor_loop Regression Audit — 2026-08-02

Audit scope: `cloud_run_service/` only. Reference baseline for comparison is the committed
`cloud_workspace_v8/response_layer` + `cloud_workspace_v8/tutor_loop.py` at `d48fc60`
(`cloud_run_service/` is entirely untracked, so it has no git baseline of its own).

Reviewed against the two agent reports in this folder:
`walkthrough_agent_gemini.md` and `board_buddy_resolution_and_learner_state_report.md`.

## Verdict up front

The core Response Layer contracts are **not** broken. I restored the four regression test
files that are missing from this copy and ran them against the current code:

| Suite | Result |
|---|---|
| `test_board_buddy.py` (present) | **34 passed, 0 failed** |
| `test_response_layer.py` (restored) | 25 passed, 1 failed — env-only |
| `test_compilers.py` (restored) | 2 passed |
| `test_runner_outcomes.py` (restored) | 3 passed |
| `test_scene_adaptation.py` (restored) | 4 passed |

The single failure is `test_scene_author_renders_without_skips`, which imports
`figures.scene_render`. `figures/` is deliberately absent from the lean cloud image
(server-side rendering is not available on Cloud Run). **Not a logic regression.**

So the damage is narrower than "thousands of broken changes" — but it is real, and it is
concentrated in **pedagogy control surfaces** rather than in crashes. The headline problem:
*the report's Issue 1 is documented as resolved and is not resolved.*

---

## P0 — Claimed fixes that do not work

### BUG-1 `sync_speech_with_visuals` runs after the speech has already been spoken

`tutor_loop.py:3282-3284` sanitizes `answer` **after** generation is complete. But the
answer is streamed to TTS *during* generation:

- `_stream_answer` pushes sentence 0 to the TTS sink at `tutor_loop.py:412`, and the
  remainder at `:445` / `:449`.
- `tutor_loop.py:3130` states it plainly: *"the streamed audio is already playing on
  another thread"*.

By line 3282 the child has already heard *"look at the figure on the screen."* Rewriting
the string there changes only the transcript, `turn_meta`, and session context.

Two consequences:
1. **The reported fix has no effect on audio.** Issue 1 in
   `board_buddy_resolution_and_learner_state_report.md` is still open.
2. **It introduces a new defect:** the recorded answer now diverges from the spoken audio.
   `tutor_loop.py:852-853` establishes the opposite invariant — the streamed prefix
   *"has already been spoken … so it must stay a prefix of the result."* This edit breaks it,
   which corrupts follow-up continuity (the model reasons over a transcript the child
   never heard).
3. The call is the **only** unguarded statement in that block — every neighbouring
   integration point is wrapped in `try/except` with a "never costs a turn" comment. An
   exception in the regex or the import fails the whole turn.

### BUG-2 (root cause of BUG-1) `figure_on_screen=True` is asserted before the board exists

`tutor_loop.py:1791` sets `figure_on_screen = True` the moment the gate says *earned*, while
the directive is still `{"pending_draw": True, "scene": None}`. The draw does not happen
until §5c, after generation.

`tutor_loop.py:655-664` then injects this into the generation prompt:

> "A FIGURE FROM THE TEXTBOOK IS BEING SHOWN ON THE STUDENT'S SCREEN RIGHT NOW.
> Refer to it directly ('look at the figure on the screen' …)"

So the prompt **instructs** the model to emit the exact phrase the sanitizer later tries to
strip. If the draw subsequently declines (`tutor_loop.py:3179`, `draw declined -> speech only`)
or returns a text-only payload, the promise is already in the audio.

Secondary defect in the same cue: on the draw-the-answer path there *is* no textbook figure —
it is an authored board. The cue is factually wrong and biases the answer toward textbook
framing. The code already recognises this for animation/real-life turns
(`if figure_on_screen and not (animate or real_life)`), but not for the ordinary earned-visual path.

---

## P1 — Visual Benefit Gate erosion

### BUG-3 `_VISUAL_CONCEPT_KEYWORDS` expansion defeats the gate

`response_layer/visual_gate.py:34-35` added:
`factor, factorization, equation, quadratic, algebra, polynomial, expression, root, zero`.

These are substring matches over `concept_type + concept_id`. `equation`, `expression`,
`root` and `zero` match essentially every Class-10 algebra concept, so `_is_visual_concept()`
returns True for nearly any maths turn and `decide()` degenerates to always-allow.

That is a direct regression against the module's own stated purpose (`visual_gate.py:1-15`,
*"visuals are earned, not default"*) and against the standing project feedback that canned
per-concept visuals mislead. The gate's job is to decide **when a visual helps**, not
whether the turn is maths.

### BUG-4 `WINI_RESPONSE_LAYER` default silently flipped 0 → 1

Baseline `cloud_workspace_v8/tutor_loop.py:71` → `os.getenv("WINI_RESPONSE_LAYER", "0")`.
Current `cloud_run_service/tutor_loop.py:78` → `"1"`.

The stated root cause in the report is wrong. It claims `.env` was loaded too late for the
flag — but `.env` in this folder contains only four keys
(`GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `VERTEX_REGION`)
and has never set `WINI_RESPONSE_LAYER`. The `load_dotenv()` addition does nothing for this
flag; **the default flip is doing all the work.** Combined with BUG-3, the board is now
armed on nearly every turn by default.

(For the record: `load_dotenv` is safe in itself — `python-dotenv==1.2.2` *is* in
`requirements-cloud.txt:16`, and `.env` *is* excluded in both `.gcloudignore:32` and
`.dockerignore:32`. No deployment break, no secret baked into the image.)

### BUG-5 `WINI_BOARD_BUDDY` kill switch removed

No occurrence of `WINI_BOARD_BUDDY` remains anywhere in `cloud_run_service/`. Board Buddy is
now gated only by the device profile (`compilers.py:133`,
`renderer == "board_buddy" or supports_board_buddy`). There is no runtime way to disable it
on a board-capable device without editing the profile.

---

## P2 — Layout defects

`pos` is a **required** field for `text`, `geometry`, `stickers` and `tree`, so
`_default_pos()` (`board_buddy_author.py:162-166`, via `:412`) is the effective layout
engine whenever the model's own position fails `clamp_pos`. The payload printed as
"verified" in `walkthrough_agent_gemini.md` §2.1 is entirely default positions, confirming
this is the common path — not a rare fallback.

### BUG-6 The default stack is height-unaware → overlapping elements

Pitch is a flat `y = 80 + index * 115`, but elements are not 115px tall. The canonical
rectangle is 140px (`_CANON_VERTS["rectangle"] = [[0,0],[220,0],[220,140],[0,140]]`).

In the walkthrough's own verified payload: `el2` geometry rectangle at `[40, 310]` spans
y=310–450, and `el3` text sits at `[40, 425]` — **inside the rectangle**. The document
presents this as a successful verification; it is a collision. `graph` and `tree` elements
are taller still.

### BUG-7 The default stack saturates and piles elements on one point

`MAX_ELEMENTS = 12` but `POS_Y_MAX = 780`, so:

```
0 [40, 80]    4 [40, 540]   8  [40, 780]
1 [40, 195]   5 [40, 655]   9  [40, 780]
2 [40, 310]   6 [40, 770]   10 [40, 780]
3 [40, 425]   7 [40, 780]   11 [40, 780]
```

Indices 7–11 are all `[40, 780]` — five elements drawn on top of each other, and index 6
(770) overlaps index 7 by 10px.

---

## P3 — Robustness and process risk

### BUG-8 The regex sanitizer can delete correct mathematics

`_VISUAL_REF_PATTERNS` (`board_buddy_author.py:697-700`) matches
`(?:look at|see|watch|check out)\s+(?:the\s+)?(?:figure|…|graph|…)\b[^.!?]*[.!?]?` and
deletes through to the end of the sentence. `see` is extremely common in tutoring speech:

> "you can see the graph is a parabola with its vertex at the origin."

The entire mathematical statement is deleted. This is the same failure class already
documented at `tutor_loop.py:681` (a downstream sanitizer that *"silently destroyed
fractions"*). `[^.!?]*` also terminates early on decimals ("x = 2.5").

### BUG-9 Four of five test files are missing from this copy

`cloud_run_service/response_layer/` ships only `test_board_buddy.py`. The suites covering
the planner, validator, compilers, runner outcomes and scene adaptation exist in
`cloud_workspace_v8/response_layer/` but were not carried over. The report's "All 34 tests
passing" therefore describes Board Buddy alone, with **no standing regression net** on the
Phase 1–5 contracts it sits on top of.

### BUG-10 Four divergent copies of `response_layer`

| Copy | `board_buddy_author.py` | `compilers.py` | `scene_author.py` |
|---|---|---|---|
| `cloud_run_service/` | 753 | 247 | 423 |
| `cloud_workspace_v8/` | 543 | 195 | 364 |
| repo root `response_layer/` | absent | 145 | 364 |
| `pi_client_package/` | absent | absent | absent |

Fixes applied to one copy do not reach the others, and it is no longer obvious which is
authoritative.

### BUG-11 The vendored renderer was modified

`board_buddy/board_buddy-main/board_buddy.py` gained `tree` support (`:263`, `:1858`). The
author-side comments describe this renderer as **frozen v1.0** and encode assumptions about
it (`_CANON_VERTS`, the right-angle indicator at vertex index 1). The report also states the
same file was pushed separately to `/home/winipi5/board_buddy_sandbox/board_buddy.py`, so
the server can now author payloads a device renderer does not understand, with no version
handshake.

---

## Fix plan

Ordered so that each stage is independently verifiable. Stages 1–2 are the ones that change
what a child actually hears.

### Stage 0 — Freeze the baseline (do first, ~10 min)

1. Copy the four missing test files from `cloud_workspace_v8/response_layer/` into
   `cloud_run_service/response_layer/`.
2. Record the current pass line (expected 34 + 25/26 + 2 + 3 + 4, with the one `figures/`
   import failure). Either vendor `figures/scene_render.py` into the image or mark that test
   `skipUnless(figures importable)` so the suite is green-on-green and a real break is visible.
3. Get `cloud_run_service/` under version control (it is entirely untracked — there is
   currently no way to diff or revert this work).

### Stage 1 — Make the visual promise honest (fixes BUG-1, BUG-2)

Delete the post-hoc sanitizer; fix the cause instead.

1. Remove the `sync_speech_with_visuals` call at `tutor_loop.py:3282-3284`. It cannot affect
   audio and it corrupts the transcript. Keep the function and its unit test for now, but
   stop calling it on the streaming path.
2. Split the prompt cue at `tutor_loop.py:655-664` into two variants:
   - **crop path** (a real textbook figure is already on screen) — keep today's wording.
   - **draw-the-answer path** (`pending_draw=True`) — a cue that does *not* promise a
     specific figure and does not say "from the textbook". Language should work whether or
     not the board lands, e.g. "work the steps in order, one idea per sentence" — the board
     then illustrates what was said rather than being referenced deictically.
3. Only set `figure_on_screen=True` at `:1791` for the crop path. For the drawn path pass a
   separate flag so the two cues cannot be confused.
4. Verify: run a turn with the draw forced to decline (stub `author_scene_from_answer` to
   return `None`) and confirm the spoken text contains no visual deixis.

### Stage 2 — Restore the gate (fixes BUG-3, BUG-4, BUG-5)

1. Revert `visual_gate.py:34-35` to the baseline keyword tuple. If factorisation genuinely
   needs a visual, add it as a **narrow** `_representation_remedy` condition (an explicit
   ask, or a misconception target), not as a blanket concept keyword. Never add substrings
   as generic as `root`, `zero`, `equation`, `expression`.
2. Decide `WINI_RESPONSE_LAYER` deliberately. If default-on is now intended, say so in the
   comment and in the build plan; do not leave the baseline's "unset ⇒ byte-identical to
   answer-first" comment standing, since it is no longer true.
3. Reinstate a `WINI_BOARD_BUDDY` kill switch around board compilation.
4. Verify: replay a set of EXPLAIN turns and check the earned/not-earned split is a
   *decision* again, not ~100% allow. `[tutor] response-layer [...] earned=` already logs this.

### Stage 3 — Fix the layout engine (fixes BUG-6, BUG-7)

Replace `_default_pos(index)` with a height-aware cursor:

1. Add a per-tool nominal height table (text ≈ 60, geometry = shape bbox height + label
   padding, graph/tree ≈ their rendered box).
2. Lay out by accumulating `y += height(el) + gutter` instead of a flat 115 pitch.
3. When the cursor would exceed `POS_Y_MAX`, **drop the remaining elements** (and record
   them in `dropped_elements`, which the debug emitter at `tutor_loop.py:3225` already reads)
   rather than clamping them into a pile.
4. Verify: extend `test_position_is_clamped_or_laid_out` with a 12-element payload and
   assert no two elements' bounding boxes intersect.

### Stage 4 — Sanitizer and consolidation (BUG-8, BUG-10, BUG-11)

1. If `sync_speech_with_visuals` is kept for the non-streaming path, tighten the regexes:
   drop the bare `see` alternative, anchor to sentence start, and never consume past the
   matched clause. Add tests asserting that "you can see the graph is a parabola with vertex
   at the origin" survives intact.
2. Pick one authoritative `response_layer` copy (`cloud_run_service/` is the deployed brain →
   make it the source) and reduce the others to a documented sync step.
3. Stamp a capability/schema version into the board payload and have the device renderer
   reject/ignore unknown tools, so an author-side `tree` cannot reach a renderer that lacks it.

### Stage 5 — Doc reconciliation

Both reports in this folder assert fixes that are unverified (Issue 1) or that their own
evidence contradicts (the §2.1 payload demonstrates BUG-6). Correct them, and propagate the
outcome per the 4-doc lockstep rule in `CLAUDE.md` — `complete_architecture_build_plan.md`
gets the measured Part status, and `rag_memory.md` gets the gotchas (post-stream mutation
cannot change audio; gate keywords must stay narrow).

## What I did not find

Worth stating explicitly, since the concern was "thousands of broken changes":

- No syntax errors — every `.py` in `cloud_run_service/` compiles.
- The `UnboundLocalError` described in `walkthrough_agent_gemini.md` §1.1 **is genuinely
  fixed**; `bundle`/`beats`/`visuals`/`bb_visual` are hoisted out of the `if _dbg:` block
  (`tutor_loop.py:3210-3213`) and the remaining `elements`/`raw_payload` uses are correctly
  paired inside `if _dbg:` guards.
- `compilers.py:124` still honours the gate verdict
  (`if intent is None or not intent.allowed or intent.visual_type == VisualType.NONE: return None`),
  so the `allowed=True` / `arm_scene=True` overrides at `tutor_loop.py:3253-3254` cannot
  resurrect a visual on a TEST turn or a high-cognitive-load turn. That override is
  redundant rather than dangerous — but it should still be removed for clarity.
- No secrets baked into the image; `python-dotenv` is correctly declared.
