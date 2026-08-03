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

### BUG-9a The "headless" test suite makes live billed Gemini calls, and is a coin toss

Found while building the Stage 0 regression net. `test_board_buddy.py` states in its own
docstring: *"All headless (no Vertex, no pygame)"*. It is not.
`test_compiler_emits_board_payload_on_bb_device` and `test_runner_emits_board_lifecycle_verbs`
call `compile_response(... profile=PI)`, which prefers `author_board_from_answer` — a live
Vertex call. Measured on identical input, three consecutive calls:

```
call 1:  10.07s -> ['text', 'stickers', 'graph']    # graph present -> test passes
call 2:   1.87s -> ['text', 'stickers', 'graph']    # passes
call 3:   1.03s -> ['text']                          # no graph    -> test FAILS
```

So the reported "All 34 tests passing" was luck, not a result. Every run bills tokens and
the outcome depends on what the model chose to draw that second.

Two consequences worth separating:
- **For the test net:** fixed in Stage 0 — a `_deterministic_board()` seam stubs the author
  so the compiler's deterministic scene→payload path runs. The suite now passes 3/3
  consecutive runs on both py3.10 and py3.12.
- **For production (unfixed):** call 3 is the important one. The rich author returns a
  **text-only payload perfectly often**, which is precisely the state that produced the
  "look at the figure" mismatch, and it lands entirely on `_default_pos` (BUG-6/BUG-7).
  The text-only rate deserves direct measurement before Stage 3.

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

### Stage 0 — Freeze the baseline — **DONE 2026-08-02** (commit `19b3372`)

1. ✅ Restored the four missing suites from `cloud_workspace_v8/response_layer/`.
2. ✅ `test_scene_author_renders_without_skips` now SKIPs (rather than fails) when the
   device-only `figures/` package is absent; the bare harness gained skip support.
3. ✅ `cloud_run_service/` committed as `19b3372` — the revert point now exists. Only that
   directory was staged; the ~100 other modified paths in the repo were left untouched.
4. ✅ Added `response_layer/run_tests.py` — one command for all suites, non-zero exit on
   failure so it works as a pre-deploy gate.
5. ✅ Fixed BUG-9a (found during this stage): the suite was hitting live Gemini and
   flip-flopping between pass and fail. Now hermetic.

**Baseline: 72 passed, 0 failed, 1 skipped** — identical on py3.10 and py3.12, stable
across repeated runs.

```bash
cd "D:/cloud CLI/cloud_run_service" && py -3.12 -m response_layer.run_tests
```

### Stage 1 — Make the visual promise honest — **DONE 2026-08-02**

Deleted the post-hoc sanitizer; fixed the cause instead.

1. ✅ Removed the `sync_speech_with_visuals` call from `tutor_loop.turn()`. A comment marks
   the spot and explains why it can never work there, so it does not get re-added. The
   function and its unit test remain for the non-streaming path (Stage 4 tightens its
   regexes — BUG-8 is still open).
2. ✅ Split the screen cue in `qwen_answer` into two mutually exclusive branches:
   - `figure_on_screen` (crop genuinely on screen) → unchanged textbook cue, deixis allowed.
   - `board_pending` (new param) → a cue that asks for step-by-step structure so the board
     stays extractable, and **explicitly forbids** referring to a figure/board/diagram.
3. ✅ `_response_layer` now leaves `figure_on_screen = False` on the earned-visual branch;
   the pending board is signalled through the directive's existing `pending_draw`, passed at
   the call site as `board_pending=bool(rl_visual and rl_visual.get("pending_draw"))`. No
   return-signature change was needed.
4. ✅ Verified by capturing the real generated prompt on all three paths:

   | path | textbook deictic cue | stand-alone-speech cue |
   |---|---|---|
   | crop on screen | present | absent |
   | board pending | **absent** | present |
   | speech only | absent | absent |

5. ✅ Locked in as `response_layer/test_screen_cue.py` (4 tests), including one that reads
   `_response_layer`'s source to assert the earned branch never sets `figure_on_screen = True`
   again. SKIPs on the device venv where numpy is absent.

**Not yet done:** the fix is verified at the prompt level, not on a live mic turn against
the deployed brain. The generator is now *instructed* not to promise a figure; confirming it
complies needs a live run (and Cloud Run redeploy), which has not been done.

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

### Stage 2 — Restore the gate — **DONE 2026-08-02, verified live on winipi5**

1. ✅ Reverted `_VISUAL_CONCEPT_KEYWORDS` to the baseline tuple, with a comment recording
   why the widened set is wrong and where topic-specific needs belong instead
   (`_representation_remedy`, which is turn-scoped evidence).
2. ✅ `WINI_RESPONSE_LAYER` **stays default-ON**, now documented as a deliberate decision
   rather than a silent flip. The report's stated cause (a late `.env` load) was wrong —
   this repo's `.env` holds only the four `GOOGLE_*`/`VERTEX_*` keys and never set the flag.
   What made default-ON dangerous was BUG-3 beside it, not the flag itself.
3. ✅ Restored the `WINI_BOARD_BUDDY` kill switch (`compilers._board_buddy_enabled`,
   default ON, read per call so it is flippable without a restart).
4. ✅ Regression cover added: `test_gate_algebra_concepts_are_not_blanket_visual` (five
   algebra concepts must be speech-only, plus a positive control that a *procedural*
   concept still earns — §12.1) and `test_board_buddy_kill_switch_disables_the_board_target`.

**Suite: 74 passed, 0 failed, 1 skipped.**

#### Live device verification (winipi5, 192.168.29.24)

Pushed `tutor_loop.py` (as a patch — the 204 KB file exceeds the base64-over-exec push),
`visual_gate.py` and `compilers.py` to the device; ran the local brain and drove it with
`POST /stream_turn` (bypasses STT, keeps the Response Layer + SYNC_VISUAL path live).

| turn | input | gate | board | deixis in speech |
|---|---|---|---|---|
| 1 | "how to find the area of a triangle?" | **declined** | none | clean |
| 2 | "I cannot picture what a parabola looks like…" | allow: *representation gap* | text-only | clean |
| 3 | "Show me the graph of y = x²−5x+6…" | allow: *representation gap* | text-only | clean |
| 4 | "I cannot picture it. Show me the graph…" | allow: *representation gap* | **5 elements incl. graph** | clean |
| 5 | same as 4, with `WINI_BOARD_BUDDY=0` | allow | **none (killed)** | clean |

Results:
- **Stage 1 holds live: 5/5 turns, zero deictic promises.** Turn 4 had a real board and
  still did not say "look at the graph" — the board illustrates the speech instead of being
  pointed at.
- **Stage 2 holds: the gate is a decision again.** Turn 1 declined. Turns 2–4 were allowed
  through `_representation_remedy` ("I cannot picture it") — the *correct* route — not
  through a blanket concept keyword.
- **The kill switch works on device** (turn 5): the gate still allows, but no board is
  compiled and the turn degrades to speech.
- Turn 4's payload rendered on the real panel via `wini_client/board_buddy_player.py`
  (`Loaded 5 elements from JSON payload (status: success)`).

#### New findings from the live run

**BUG-6b — `graph` is the one tool with no `pos` in its schema.** `TOOL_SCHEMAS["graph"]`
requires only `equation`, so `_normalise_element` never assigns it a position and the brain's
layout never places it. Board Buddy then draws it at its own default (top-left) — directly
on top of the title the brain *did* place at `[40, 80]`. The panel screenshot shows
"Parabola: Football's Path" written across the graph's y-axis. Fold this into Stage 3:
give `graph` a laid-out position (or reserve its box in the cursor) rather than leaving it
unpositioned.

**BUG-9a is worse than the test flake suggested.** The rich author path is *not* dead — run
in isolation with spaced calls it succeeded 4/4 on the same long answer. But under the call
volume of a real turn (perception + generation + grader + scene author + board author) it
returned `ok=False` and silently degraded to the conservative scene→payload translation,
which is why turns 2 and 3 produced a single prose sentence at `[300, 128]`
(`0.5×600, 0.16×800` — the scene translator's centre, not `_default_pos`). Turn 4, on a
freshly restarted brain, got the rich path. So the board a child sees depends on transient
Vertex pressure. This needs a retry/backoff around the author call and a logged reason on
decline — currently `author_board_from_answer` swallows the failure with a bare
`except Exception: return None` and prints nothing.

*(Method note: an earlier reading of this as "long answers fail deterministically" was my own
probe rate-limiting itself — 3 back-to-back calls per iteration. Spaced retries disproved it.)*

### Stage 3 — Layout engine — **DONE 2026-08-03, verified live on winipi5**

Replaced the flat 115 px pitch with a height-aware column in `board_buddy_author.py`:

1. ✅ Per-tool nominal heights read off the **frozen renderer's own `size_presets`**
   (`board_buddy.py`: text 16–36 px/line, graph 200, fraction 160, numberline 120,
   stickers 32, geometry from `_CANON_VERTS`, tree 28+44+70·levels+20) — measured, not guessed.
2. ✅ `_layout_payload` lays out with a cursor (`y += height + gutter`) instead of a constant.
3. ✅ Overflow is **dropped and recorded** (`layout-overflow:<tool>`) rather than clamped
   into a pile.
4. ✅ BUG-6b: `graph`/`numberline` carry no `pos` in their schema, so the layout now assigns
   them one instead of leaving placement to the renderer.
5. ✅ A model layout that already fits and does not collide is left alone
   (`_model_layout_is_sane`) — we only re-flow a broken board.

Regression cover: `test_layout_positions_the_unpositioned_graph`,
`test_layout_no_overlap_across_mixed_tools`,
`test_layout_drops_overflow_instead_of_piling_them`,
`test_layout_keeps_a_sane_model_layout`.

Measured: the live turn-4 payload now lays out with **zero overlapping bounding boxes**; a
12-graph payload keeps 3 and drops 9 with `max bottom = 762 ≤ POS_Y_MAX = 780` (previously
five elements stacked on `[40, 780]`).

**Live on the panel:** same prompt as the Stage 2 run. Before, the title was drawn across the
graph's y-axis; after, title → sticker → graph → two text lines stack cleanly, with the graph
at a brain-assigned `[40, 174]`. Screenshots: `shot_stage2_board_live.png` (before),
`shot_stage3_board_live.png` (after).

### Stage 4 — Sanitizer, author resilience, consolidation — **DONE 2026-08-03**

1. ✅ **BUG-8 sanitizer rewritten.** The old patterns allowed a bare `see` and then consumed
   `[^.!?]*` to the end of the sentence, so *"you can see the graph is a parabola with its
   vertex at the origin."* was deleted whole. Now only imperative/deictic openers match
   (`look at`, `watch`, `check out`, `as you can see`), the match stops after the visual noun
   plus a short prepositional tail, and sentence case is restored.
   `test_sanitizer_never_deletes_the_mathematics` asserts three real tutoring lines survive
   intact while genuine pointers are still removed.
2. ✅ **BUG-9a author resilience.** `author_board_from_answer` now retries once with backoff
   and — critically — **logs why it declined**. The previous bare
   `except Exception: return None` printed nothing, which is why a board silently degrading
   to a one-sentence prose card went unnoticed. Budget kept deliberately small (2 attempts,
   1.5 s) because this runs after generation with audio already streaming.
   `JsonResult` also gained a `reason` field (`llm_vertex._json_failure_reason`): callers
   previously saw only `ok=False` and could not distinguish a `MAX_TOKENS` truncation from a
   safety block from an empty candidate. Live logs now read e.g.
   `author declined (ok=False, reason='max-tokens (raise max_output_tokens)')`.
   **This mitigates but does not eliminate BUG-9a** — the board a child sees still depends on
   Vertex succeeding within 2 attempts. It is now diagnosable instead of silent, which is the
   precondition for tuning it properly.
3. ✅ **BUG-11 checked, currently benign.** All three `board_buddy.py` copies (repo,
   device repo, `~/board_buddy_sandbox`) are byte-identical (`d9b68792`, 1956 lines) and all
   support `tree`. `ALL_TOOLS`, `TOOL_SCHEMAS` and `WINIPI5_PROFILE.board_buddy_tools` agree
   exactly. The capability-negotiation mechanism (`allowed_tools_for_profile`) is sound; the
   residual risk is that the profile *claims* rather than *verifies*. Left as a known gap
   rather than inventing a handshake the device does not implement.
4. ◻️ **BUG-10 consolidation — deliberately NOT done as a code move.** See below.

#### On BUG-10 (four divergent `response_layer` copies)

`cloud_run_service/` is the authoritative copy — it is the deployed brain and is now the one
under version control with a green suite. The device copy at
`/home/winipi5/cloud_tutor/cloud-CLI/` was verified content-identical for every file this
work touched, and the four changed files were pushed to it.

Physically merging `cloud_workspace_v8/`, the repo-root `response_layer/` and
`pi_client_package/` is a large structural change that would touch working device paths for
no behavioural gain, so it is **left for a deliberate, separately-tested change** rather than
folded into a bug-fix pass. The sync procedure that matters today:

```bash
# authoritative -> device (the 204 KB tutor_loop.py exceeds the base64-over-exec push;
# send a patch instead, and normalise CRLF first — the device copy is CRLF)
MSYS_NO_PATHCONV=1 PI_PASS=... PI_HOST=192.168.29.24 python tools/pi.py push \
  "D:/cloud CLI/cloud_run_service/response_layer/<file>.py" \
  /home/winipi5/cloud_tutor/cloud-CLI/response_layer/<file>.py
```

### Stage 5 — Doc reconciliation — **DONE 2026-08-03**

Correction notices added to the two reports in this folder. Both claimed fixes that the code
or their own evidence contradicts:

- `board_buddy_resolution_and_learner_state_report.md` — Issue 1 did not work (post-stream
  mutation cannot change audio), Issue 4's stated root cause is wrong (`.env` never set that
  flag), and the keyword widening it describes as a fix was the main regression. Issue 3
  (`tree`) holds.
- `walkthrough_agent_gemini.md` — §1.1 holds; §1.4/§2.1's "verified" payload demonstrates the
  collision rather than a fix.

**Remaining (outside this folder):** the 4-doc lockstep in `CLAUDE.md` also wants
`complete_architecture_build_plan.md` updated with the measured Part status and
`rag_memory.md` updated with the gotchas. Those live in the repo root, outside the
`cloud_run_service` scope agreed for this pass.

---

## Original Stage 3 plan (superseded by the DONE section above)

### Stage 3 — Fix the layout engine (fixes BUG-6, BUG-6b, BUG-7)

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
