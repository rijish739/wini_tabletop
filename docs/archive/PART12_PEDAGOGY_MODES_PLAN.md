# Part 12 — Session Pedagogy Modes: EXPLAIN / PRACTICE / TEST

> **Status: Stages 1–4 + 6 BUILT + verified, 2026-07-15; Stage 5 DEFERRED by owner.** Written
> 2026-07-11 after a literature review + a module-level audit of the running system.
> Execution is staged (§8); each stage lands separately with its own acceptance gate,
> in the style of Part 11. Done: Stage 1 mode substrate (EXPLAIN byte-identical to
> pre-Part-12), Stage 2 PRACTICE ladder, Stage 3 TEST (runtime-generated quiz set +
> hardened deterministic grader + 0.8 gate + Bloom corrective) — see the §4.4 build
> note; Stage 4 T9 question/score cards + voice-plain question generation — see the
> §5.6 build note; Stage 6 reporting + the four-doc lockstep propagation (2026-07-15).
> **Stage 5 perception signals is DEFERRED by the owner** (2026-07-15) — it is billed and
> carries a design fork, and the deterministic cues already cover mode requests (optimization).
>
> **Lockstep note (CLAUDE.md):** this document is a *plan*. When a stage ships,
> its behavior/schema changes MUST be propagated to the four lockstep docs
> (`learner_cognitive_state_architecture.md`, `RAG_upgrade_plan.md`,
> `model_dataset_architecture_report.md`, `complete_architecture_build_plan.md`)
> plus a `rag_memory.md` log entry, in the same work session. §10 has the
> propagation checklist.

---

## 1. The proposal, and the verdict

**Proposal (owner, 2026-07-11):** structure tutoring into three sections —

1. **Explanation** — as the pipeline works today (introduce, explain, ground in NCERT).
2. **Practice** — worked examples; explain the same concept in different ways so the
   student masters it properly.
3. **Test** — quiz-style testing that grades the student.

**Verdict: YES — this is pedagogically correct, and it is exactly the layer the
current architecture is missing.** The three sections map directly onto the most
replicated results in instruction research (§2). The current system is a superb
*reactive* tutor: every turn it reads the student's cognitive state and picks one
best action (`rules_decide` v4, 14 actions). What it does **not** have is
*session-level intentionality* — a goal-directed arc that says "we are now
practicing toward mastery" or "this is a check, not a lesson". In ITS terms
(VanLehn 2006): the **inner loop is built; the outer loop is missing.** This plan
adds the outer loop without touching the inner loop's guarantees.

The literature demands **five refinements** to the naive three-section reading —
all adopted in this design:

| # | Refinement | Why (evidence, §2) |
|---|---|---|
| R1 | The sections form a **cycle with a mastery gate**, not a one-way pipeline: Explain → Practice → Test → (score < 80% ⇒ corrective Practice on exactly the missed pieces → parallel-form re-Test) | Bloom mastery learning: formative test + corrective instruction + re-test to an ~80% criterion is *the* mechanism behind the 1-sigma mastery result |
| R2 | Practice is a **participation ladder that fades with mastery**, not a flat stream of worked examples: full worked example → completion step ("you do the last step") → independent isomorphic problem → near transfer | Worked-example effect + **expertise-reversal effect**: full examples help novices and *hurt* students with prior mastery; **adaptive fading beats fixed fading beats pure problem-solving** (Renkl & Atkinson; Salden et al.) |
| R3 | The Test is **low-stakes retrieval practice** — a *learning event*, framed warmly, graded honestly, with immediate per-item feedback | Testing effect (Roediger & Karpicke 2006): retrieval beats re-reading for retention; low-stakes quizzing also improves self-calibration |
| R4 | Practice **interleaves** a second concept once one is available, and Test sets carry 1–2 **spaced review** items from earlier sessions | Interleaving doubles delayed-test scores in maths (Taylor & Rohrer 2010); spacing is the most robust effect in learning science; Rosenshine: begin with review |
| R5 | The modes are the **outer loop only** — the existing per-turn machinery (deterministic overrides, misconception probe-first, hint chains, bridge gates, non-attempt guardrails) stays authoritative *inside* every mode | VanLehn two-loop model; and the system's own hard-won regressions (grading-loop guardrails) must not be re-fought |

The user-visible shape ("explain same concept different ways" in Practice) is
also directly supported: multiple representations measurably deepen mathematical
understanding — and the store already carries the 8-type representation taxonomy
(§9 of the architecture doc), `representations_known/missing` tracking, and KI
integration links. Practice mode operationalizes them.

---

## 2. Research grounding (what the evidence says)

Findings that shaped this design, with the load-bearing claim each contributes:

- **Two-loop ITS model — VanLehn, "The Behavior of Tutoring Systems" (2006).**
  Effective tutors run an **outer loop** (select the next *task*: explain X,
  practice item Y, test Z) and an **inner loop** (within-task steps: feedback,
  hints, probes). Wini's B0–B7 pipeline + `rules_decide` is a strong inner loop;
  the modes are the outer loop. Meta-analyses find significant ITS learning gains
  when both loops exist.
- **Mastery learning — Bloom (1968; two-sigma 1984).** Formative assessment after
  each unit + **diagnostic corrective instruction** + re-assessment until an
  **~80% mastery criterion** produced ~1σ gains; tutoring + mastery produced ~2σ.
  The corrective loop is the point — a test that only *measures* wastes its main
  pedagogical value. TEST mode therefore always closes with either a mastery-gate
  pass or a targeted corrective plan.
- **Worked-example effect & faded examples — Sweller; Renkl & Atkinson (2003–2007).**
  Novices learn more from studying worked examples than from solving; support
  should **fade** (backward fading: learner does the last step first), and
  **adaptive** fading keyed to the individual's demonstrated understanding beats
  fixed fading (Cognitive Tutor experiments, Salden et al. 2009).
- **Expertise-reversal effect — Kalyuga et al.** The same worked example that
  helps a novice becomes redundant and *harmful* at higher mastery. Practice mode
  must therefore key its ladder on `mastery`, never serve a flat diet.
- **Testing effect / retrieval practice — Roediger & Karpicke (2006); Roediger,
  Agarwal et al. (2011).** Retrieval beats restudy for long-term retention (61% vs
  40% after a week in the classic study); classroom quizzing with feedback produces
  durable gains and better self-knowledge. Tests are *learning events*.
- **Interleaving & spacing — Taylor & Rohrer (2010); Rohrer et al. (2014, 2019 RCT).**
  Interleaved maths practice impairs practice-session performance but **doubled**
  scores a day later, by forcing strategy *selection* (which procedure goes with
  which problem). Spacing is "arguably the largest and most robust effect known
  to learning scientists". Practice/Test sets should mix, not block, once ≥2
  concepts are in play.
- **Direct-instruction structure — Rosenshine's Principles of Instruction.**
  Present in small steps → **guided practice** → **independent practice** →
  weekly/monthly **review**, holding an ~**80% success rate** during guided
  practice (below it, errors get embedded). This is the classical warrant for the
  Explanation → Practice → Test arc itself, and for keeping practice success high
  (ZPD banding already does this).
- **Formative assessment — Black & Wiliam ("Inside the Black Box").** Assessment
  evidence must change the *next teaching move*; feedback should be specific,
  task-focused, non-judgmental. Immediate feedback prevents misconception
  reinforcement in young learners (procedural skills) — TEST gives immediate
  per-item feedback, plus an end-of-set summary.
- **Multiple representations (NCTM; SERP).** Seeing a concept as objects,
  drawings, words, symbols, graphs measurably deepens understanding — the store's
  8-type representation taxonomy + `representations_missing` tracking is the
  machinery; Practice rotates through it deliberately.
- **LLM-tutor practice (LearnLM; Khanmigo; BEA 2025 shared task).** Current
  LLM-tutor literature converges on: don't give direct answers during practice
  (productive struggle), ground in materials, adapt to learner level, and make
  pedagogy *modes* explicit rather than hoping the model infers them. Wini
  already enforces grounding (manifest-only generation) and no-answer-leak (hint
  chains); modes make the remaining piece explicit.

Sources are listed at the end of this file (§11).

---

## 3. Current state (what exists today, verified in code)

One reactive loop, no session arc:

- **Front door** (`perception/`): deterministic SAFETY/NONSENSE gates → one Gemini
  call → 8-way intent; only `LEARNING` enters the pipeline. **Mode requests have
  no home**: "test me" / "let's practice" today lands in LEARNING and gets
  whatever `rules_decide` picks (often QUIZ via rule 10b, or EXPLAIN).
- **Per-turn pedagogy** (`tutor_loop.rules_decide` v4): deterministic overrides
  (1a-vis, 1w, 1b, 1c) → misconception probe → hint → ack-reflect → distress →
  transfer → representation → example → Socratic → explain → **fallback QUIZ**.
  All 14 actions exist, including WORKED_EXAMPLE, TRANSFER_PROBLEM, QUIZ — but
  they fire *reactively, one turn at a time*; nothing sequences them toward
  mastery, and nothing remembers "we are mid-practice-set".
- **Grading loop** (turn steps 1a–1c): `pending_check` (bridge/misconception
  diagnostics → `judge_answer` → `apply_probe_result`/`apply_bridge_result`),
  `pending_hope` (CT/KT/KI probes → HOPE detector, never mastery). Guardrails:
  non-attempts never grade; CT probes are HOPE-only; hint requests escalate the
  chain, never grade. **These are the inner loop and are kept verbatim.**
- **Learner state** (`learner_state.py`): per-concept `mastery` (moves ONLY via
  the two evidence APIs), misconception status machine, `hint_dependency`,
  `representations_known`, rolling HOPE, ZPD banding (`mastery_to_band`).
- **Retrieval** (`query.py`): 7-term learner-aware ranking; `need_evidence`
  branches for transfer/integrate/challenge/schema/reflect; problem schemas carry
  `method_steps`, `instance_ids`, `isomorphic_variables`, `trap_steps`; examples/
  exercises carry 3-step `hint_chain`s. **No branch builds a practice *set* or a
  quiz *set*; `need == "practice"` falls through to chunks.**
- **Pacing** (`pacing/pacing_controller.py`): per-action spoken budgets +
  micro-check ledger. No mode awareness beyond `_mode_for_action`'s cosmetic map.
- **Display (T9)** (`tutor_loop._build_display` → `wini_client` sinks →
  `wini_platform` DisplayThread): shows ONE pedagogy-gated figure crop per turn;
  math rendering exists. No question-card / score-card display type.
- **Reporting**: `progress_report.py` + `parent_dashboard.py` (laptop) read
  learner state + learning log. No per-quiz results to show yet.

**Gap summary:** everything below the line "pick one good action for THIS turn"
exists and is battle-tested. Everything above it — session goal, mode arc,
practice sets, test sets, scores, mastery gates — does not exist.

---

## 4. Target design — the mode layer (outer loop)

### 4.1 The three modes and the session arc

```
                 ┌────────────────────────────────────────────────┐
                 │            SESSION (per concept)                │
                 │                                                 │
   entry ──────► │  EXPLAIN ──offer──► PRACTICE ──offer──► TEST    │
                 │     ▲                  ▲                  │     │
                 │     │   corrective     │   score < gate   │     │
                 │     └──(concept gap)───┴──(item gaps)─────┘     │
                 │                        score ≥ gate ⇒ mastery   │
                 │                        gate PASS ⇒ next concept │
                 └────────────────────────────────────────────────┘
```

- **EXPLAIN** — the default; **byte-for-byte today's behavior** (rules v4,
  including intro tone, bridges, misconception probes, representation switches).
  Stage 1 must be regression-neutral: a session that never leaves EXPLAIN is
  indistinguishable from the current system.
- **PRACTICE** — a per-concept **practice plan** (§4.3): an adaptive ladder of
  items served one at a time, each graded through the existing pending-check
  machinery, with representation rotation and interleaving. Hints available
  (chain-faded, rule 10). Goal: bring first-attempt success into the 70–85% band
  (Rosenshine) and mastery toward the gate.
- **TEST** — a fixed short **quiz set** (§4.4): N items selected up front, no
  teaching between items, no hint-chain descent (a hint request gets a warm
  deferral), immediate right/wrong feedback per item, a spoken + displayed score
  summary at the end, mastery write-back per item, and the Bloom corrective loop
  on a sub-gate score.

**Mode transitions** (all logged; all conservative):

| Trigger | Transition | Notes |
|---|---|---|
| Explicit student request ("let's practice", "give me problems", "test me", "quiz me", "explain again") | any → requested mode | deterministic cues first (§5.1); perception signal later (Stage 5) |
| EXPLAIN: concept intro done + positive ack + no distress + no active misconception | **offer** PRACTICE ("want to try a few together?") | offer, never force; consumed like `pending_shift` (bare yes/no) |
| PRACTICE: plan complete (ladder top reached, ≥ M items, recent success ≥ 80%) | **offer** TEST | |
| PRACTICE: 2 consecutive wrong at ladder bottom OR misconception probe fires active | → EXPLAIN (corrective) | inner loop already does the probe; mode follows the evidence |
| TEST: set complete, score ≥ gate (default 80%) | mastery-gate PASS → offer next concept (teaching-order successor) or end | |
| TEST: set complete, score < gate | → PRACTICE (corrective plan built from exactly the missed items' schemas/misconceptions), then parallel-form re-TEST | Bloom loop; parallel forms via `isomorphic_variables` |
| SESSION-CONTROL (bye / break) | mode state frozen in session dict | existing hard-stop contract untouched; resume restores mode |
| SAFETY | scripted path, mode irrelevant | front door precedes modes — unchanged |

**Student agency rule:** a mode is never a cage. Any LEARNING utterance that the
inner loop reads as confusion / representation gap / why-question is answered in
place (the overrides stay mode-independent); only *graded, item-serving flow*
differs per mode. A child who asks "why?" mid-test gets the question parked
warmly ("hold that thought — after the quiz, promise"), and TEST mode queues it
(`parked_questions`) for after the summary.

### 4.2 Session-state contract (new fields, `session` dict)

```jsonc
"session": {
  // existing: current_concept, pending_check, pending_hope, pending_shift,
  //           context, status, last_action, ...
  "mode": "EXPLAIN" | "PRACTICE" | "TEST",       // default EXPLAIN
  "pending_mode_offer": {"mode": "PRACTICE", "concept_id": "..."},  // yes/no, one turn
  "practice_plan": {                              // present only in PRACTICE
    "concept_id": "...",
    "ladder_level": 0,          // 0 worked_example · 1 completion · 2 isomorphic · 3 transfer
    "items_served": [{"id": "...", "outcome": "correct", "hints": 1, "repr": "graphical"}],
    "interleave_pool": ["<other concept ids with due items>"],
    "reps_rotated": ["verbal", "graphical"]
  },
  "test_state": {                                 // present only in TEST
    "concept_id": "...",
    "items": [{"id": "...", "question": "...", "expected_answer": "...",
               "difficulty": 4, "kind": "fresh|review|parallel_retest"}],
    "index": 2,
    "results": [{"id": "...", "outcome": "correct", "answer": "..."}],
    "parked_questions": ["why does the parabola touch the axis?"],
    "started_at": "..."
  }
}
```

Learner-state additions (persisted, outside `session`):

```jsonc
"concept_states": { "<cid>": {
   // existing fields ... plus:
   "item_history": {"<item_id>": {"last_seen": "...", "outcomes": ["wrong","correct"]}},
   "test_history": [{"date": "...", "score": 0.8, "n": 5, "gate": "pass",
                     "item_results": [...]}],
   "mastery_gate": "none" | "passed" | "failed_pending_retest"
}}
```

`item_history` is what makes "never re-serve yesterday's exact question" and
spaced review selection possible; `test_history` feeds the parent dashboard.

### 4.3 PRACTICE mode — the adaptive ladder

Per turn, the mode controller (not `rules_decide`) picks the next item:

1. **Ladder level from evidence** (adaptive fading, R2):
   - level 0 `WORKED_EXAMPLE` — full example from the matching `problem_schema`'s
     `instance_ids`, narrated step-by-step, closing with a self-explanation
     micro-check (`metacognitive_prompts`; self-explanation is what makes
     examples work — Renkl).
   - level 1 `COMPLETION_STEP` — same schema, but Wini works all steps except the
     last; the student does the final step (backward fading). *New action label.*
   - level 2 `ISOMORPHIC_PRACTICE` — an independent problem regenerated from
     `isomorphic_variables` (same `method_steps`, new surface); hint chain
     available, graded.
   - level 3 `TRANSFER_PROBLEM` — near transfer via `transfers_to` (far only at
     mastery ≥ the existing `FAR_TRANSFER_MASTERY`).
   - **Entry level** keyed on mastery (≈ <0.45 → 0; 0.45–0.6 → 1; 0.6–0.75 → 2;
     ≥0.75 → 3), **movement** keyed on outcomes: correct-no-hints ⇒ up one;
     wrong or 3-hint struggle ⇒ down one; two consecutive wrong at level 0 ⇒
     exit to corrective EXPLAIN. (Expertise reversal both ways.)
2. **Representation rotation** (the owner's "explain the same concept different
   ways"): each level-0/1 serve picks the next representation from
   `representations_missing` (KI machinery, `integration_links`, figure crops via
   T9). A representation confirmed by a correct follow-up is written to
   `representations_known` (the write-back already exists for
   REPRESENTATION_TRANSLATION acks — extend to practice confirmations).
3. **Interleaving** (R4): once a second concept has due items (practiced earlier
   this session, or `item_history` shows a concept due for review), mix ~1 review
   item per 2–3 current items. Blocked first two items always (protect early
   success rate), interleave after.
4. **Grading**: every level-1/2/3 item arms `pending_check` with
   `kind: "practice"`; the existing non-attempt guardrails apply verbatim; the
   outcome flows through the **new** `apply_item_result` API (§5.3) — mastery
   moves by evidence, discounted by hints used (already the `apply_probe_result`
   pattern).

Inner-loop overrides that fire mid-practice (confusion plea → rule 1b re-explain;
visualization plea → rule 1a-vis; misconception suspected → probe-first) execute
normally; the plan just doesn't advance that turn.

### 4.4 TEST mode — the quiz protocol

> **BUILT + on-brain verified 2026-07-15 (Stage 3).** Item source changed from the
> plan's original assumption after a **store audit**: `rag_store/graph.json` carries
> **zero** stored `expected_answer` (0/245 problem_schema instances; only 43 instance
> refs total, all example/exercise `text` with no structured answer), and **no**
> concept has ≥5 problem_schemas (median 2, max 4). So a stored/pre-built quiz bank is
> not assemblable, and **`build_quiz_bank.py` is NOT needed** — the billed batch
> long-pole is designed away. Instead items are **generated at serve time** from the
> concept's `problem_schema`s (`generate_quiz_item` in tutor_loop, one structured
> Gemini call biased to a single numeric/short-exact answer so `math_grade` grades
> deterministically without a second call), each carrying its own `expected_answer`.
> Planning stays pure in `session_modes` (`build_quiz_set` / `advance_test` /
> `score_quiz`); tutor_loop owns generation, grading and the state machine
> (`_drive_test`). The set is **concept-locked** for its whole length — the student's
> short answers re-classify to other concepts turn-to-turn, and honouring that drift
> restarted the set every item (bug caught in the live smoke, fixed). A TEST item OWNS
> the pending_check slot (4a-test) — probe-before-correct does NOT preempt an
> assessment. On a **fail** the mode drops to a corrective EXPLAIN and the concept
> carries `mastery_gate: "failed_pending_retest"` so a later "test me" is a
> parallel-form re-test (fresh generation = inherently parallel). Live smoke: 5/5 on
> `fundamental_theorem_of_arithmetic`, gate pass, `test_history` written. Not yet
> built: spaced-review swap-in (R4), `parked_questions`, the displayed score card
> (Stage 4).

1. **Set construction** (`build_quiz_set`, in the new mode module):
   - N = 5 items default (voice-friendly; configurable).
   - Sources, in preference order: exercise/example nodes with an
     `expected_answer` + the concept's `diagnostic_question`s not currently
     armed + isomorphic regenerations for parallel forms. **`ct_probe` nodes are
     EXCLUDED** — CT/KT/KI probes are HOPE-scored, never mastery-graded (standing
     guardrail).
   - Difficulty: centered on the ZPD band, one easier (confidence opener — always
     first), one stretch.
   - Coverage: prefer items spanning different `problem_schema`s / facets of the
     concept over five isomorphs of one skill.
   - Exclusions: any item in `item_history` seen in the last K sessions
     (default 3), unless explicitly a `parallel_retest` regeneration.
   - Spaced review (R4): if any *other* concept passed its gate ≥ 1 session ago,
     swap in 1 review item from it.
2. **Serving loop**: one item per turn; question spoken AND displayed (§5.6);
   answer graded (§5.4); **immediate, brief, warm feedback** ("Yes! nailed it." /
   "Not quite — we'll come back to that one, next question:") — no teaching
   between items (that's what corrective practice is for); non-attempt guardrail:
   a confusion plea or counter-question is parked, never graded wrong; a hint
   request gets the scripted deferral (no hint-chain descent in TEST).
3. **Scoring & gate**: score = correct / N (partial = 0.5). Gate default **0.8**
   (Bloom/Rosenshine). End-of-set: spoken summary + displayed score card +
   `test_history` write + per-item `apply_item_result(kind="test")` (full-weight
   mastery evidence, no hint discount) + gate outcome:
   - **pass** → `mastery_gate: "passed"`, celebrate, offer the teaching-order
     next concept, answer `parked_questions`.
   - **fail** → `mastery_gate: "failed_pending_retest"`, NO shaming (low-stakes
     framing: "good practice — two of these we'll work on together"), controller
     builds the corrective PRACTICE plan **from exactly the missed items'**
     schemas + any misconception the wrong answers matched (`why_wrong`
     matching), then a **parallel-form re-test** (isomorphic regenerations, never
     the same surface questions — otherwise the re-test measures memory of the
     answer, not mastery).
4. **Session-end**: an unfinished test freezes (`test_state` persists); resume
   offers "finish the quiz or start fresh?".

---

## 5. Changes required, module by module

| # | Module | Change | Size |
|---|---|---|---|
| 1 | **`session_modes.py` (NEW)** | ModeController: transition table §4.1, `practice_plan` ladder §4.3, `build_quiz_set` + test loop §4.4, corrective-plan builder, mode offers | the core of Part 12 |
| 2 | `cognitive_classifier/cues.py` | NEW standalone helpers `is_practice_request`, `is_test_request`, `is_explain_request`, `is_stop_test_request` | small ⚠ NOT in `CUE_NAMES` |
| 3 | `tutor_loop.py` | mode dispatch in `turn()` (§5.2); `judge_answer` hardening (§5.4); new actions in prompt builder (`qwen_answer` styles for COMPLETION_STEP / TEST_QUESTION / TEST_FEEDBACK / TEST_SUMMARY); `_build_display` question/score cards (§5.6) | medium |
| 4 | `learner_state.py` | `apply_item_result` (§5.3), `item_history`, `test_history`, `mastery_gate`, spaced-review due query | medium |
| 5 | `query.py` | `need_evidence` gains `practice_item` + `quiz_item` branches (schema instances, isomorphic regeneration, difficulty/coverage filters, item-history exclusion) | medium |
| 6 | `pacing/pacing_controller.py` | budgets for the new actions; `_mode_for_action` extended; TEST questions stay ≤30 words | small |
| 7 | `perception/` (Stage 5, gated) | `practice_request` / `test_request` signals in the enum catalog + few-shots → `build_perception` → Vertex cache recreate → perception eval re-run | small code, mandatory eval |
| 8 | `rag_store/` + build | ~~audit `expected_answer` coverage; `build_quiz_bank.py` if thin~~ **DONE 2026-07-15: audited — coverage is ZERO** (0/245 schema instances carry `expected_answer`; 0 concepts have ≥5 schemas). Conclusion: no stored bank is possible → **items generated at serve time** (`generate_quiz_item`, §4.4 build note). `build_quiz_bank.py` NOT built (the long pole is designed away); the store is unchanged. | ~~long pole~~ resolved by runtime generation |
| 9 | `wini_server.py` / `wini_client` | pass-through of the new display metadata + `mode` in turn results (thin-client contract additive, ESP32-safe) | small |
| 10 | `progress_report.py`, `parent_dashboard.py` | quiz results table, mastery-gate per concept, practice minutes vs test scores | small |
| 11 | `eval/` | `grader_eval.py` (NEW), `behavioral_eval.py` mode-trajectory cases (§7) | medium |
| 12 | docs | lockstep propagation §10 | per stage |

### 5.1 Mode-intent detection — deterministic first, model later

Stage 1 detects mode requests with **deterministic cues** (regex/lexicon helpers
in `cues.py`, same pattern as `is_learning_request` / `is_visualization_request`):
"let's practice", "give me a problem/sums to solve", "test me", "quiz me",
"can we do a test", "explain it again", "back to learning", "stop the test".
Two hard reasons for this order:

- ⚠ **`CUE_NAMES` gotcha (CLAUDE.md):** the cue *feature vector* length is baked
  into the shipped logreg widths — adding a cue **feature** forces rebuilding the
  classifier bank AND the policy shadow. The new helpers are therefore standalone
  functions only, never `CUE_NAMES` entries. Zero rebuilds.
- ⚠ **Perception enum gotcha:** adding signals to the Gemini `response_schema`
  requires `build_perception` → context-cache recreate (`perception/vertex_cache.py`)
  → the full offline perception eval + behavioral signal eval before promotion.
  That's Stage 5, *after* the modes demonstrably work; the deterministic layer
  stays as the belt afterwards (schema stops invented values, not wrong ones).

Front-door interaction: mode requests are LEARNING-adjacent utterances; the
8-way intent routing is untouched. Cues run inside the LEARNING path (turn step
1a, where the other deterministic cues already run). "Stop the test" is NOT
session-control (the child wants to keep learning, just not test) — it exits to
EXPLAIN; "bye" mid-test stays a SESSION_CONTROL hard stop.

### 5.2 `tutor_loop.turn()` integration — one dispatch point, inner loop intact

The mode layer slots in at exactly one place — **after** step 1c (pending
check/HOPE grading, which must stay mode-independent) and **around** step 3
(`rules_decide`):

```
turn():
  -1..2b  unchanged (pending_shift, front door, analysis, topic shift,
          attempt detection, pending_check/pending_hope grading, ack handling)
  3a NEW  mode = ModeController.resolve(session, text, cues, analysis)
          - consumes pending_mode_offer (bare yes/no, like pending_shift)
          - applies explicit mode-request cues
          - applies evidence transitions (§4.1 table) using the writeback
            that step 1b just produced
  3b      if mode == EXPLAIN:  action, need, why = rules_decide(...)   # UNCHANGED
          if mode == PRACTICE: action, need, why = controller.next_practice(...)
                               # overrides 1a-vis/1w/1b + misconception probe
                               # still win — controller defers to them
          if mode == TEST:     action, need, why = controller.next_test_item(...)
                               # only SAFETY/session-control/non-attempt parking
                               # outrank the test loop
  4..7    unchanged (retrieval honors the controller's need; pending_check armed
          by the controller for practice/test items; generation; write-backs;
          persistence — session now carries mode state)
```

Deterministic-override precedence *inside* modes (explicit contract):

| Override | EXPLAIN | PRACTICE | TEST |
|---|---|---|---|
| SAFETY / NONSENSE / SESSION_CONTROL (front door) | wins | wins | wins |
| rule 1b confusion plea | wins | wins (plan pauses) | parked, item repeated once, then marked wrong-with-help — never silently graded |
| rule 1a-vis / 1w | wins | wins (plan pauses) | parked to `parked_questions` |
| misconception probe-first | wins | wins (plan pauses) | suppressed during the set; missed items do the diagnosis after |
| hint chain | rule 10 | rule 10 | deferral script, no descent |

### 5.3 New write-back API — `apply_item_result` (state moves on evidence, extended)

`learner_state.py` gains the third evidence API, sibling to
`apply_probe_result` / `apply_bridge_result`:

```python
def apply_item_result(self, item_id, outcome, concept_id, *,
                      kind,             # "practice" | "test" | "parallel_retest"
                      difficulty=None,  # item band, for gain scaling
                      hints_used=0):    # practice only; tests are hint-free
    """Mastery moves by graded item evidence. Practice gains are discounted by
    hints_used (same curve as apply_probe_result); test items carry full weight.
    Updates item_history; never touches misconception status (that stays with
    apply_probe_result). Returns the writeback record for the learning log."""
```

Invariants preserved: mastery still *only* moves through evidence APIs; the
analyzer still writes only soft state; HOPE stays its own channel; misconception
status stays with the probe API. The learning log gains `item_result` records —
which is precisely the data the deferred neural knowledge tracing (Part 6) has
been waiting for.

### 5.4 Grader hardening (TEST-grade `judge_answer`)

Today `judge_answer` is a single weak LLM call (correct/partial/wrong). Fine for
one diagnostic per few turns; not fine when five graded items decide a mastery
gate. Hardened grader, deterministic-first (mirrors the safety-gate philosophy —
never lean on the model for the floor):

1. **Deterministic numeric/expression equivalence first**: parse both sides for
   Class-10 answer shapes — numbers ("13", "thirteen", "13.0"), fractions,
   simple pairs ("x = 2 and x = 3" in any order), yes/no, and unit tolerance.
   STT reality: "root two" vs "√2", "one by three" vs "1/3" — normalize via the
   existing math-preserving `InputProcessor` conventions.
2. **LLM rubric grading only for verbal/conceptual answers** (Gemini path via
   `GEN_BACKEND`, temperature 0, hard wall-clock timeout per the bulk-LLM
   mandate), with the expected answer AND the item's `trap_steps`/`why_wrong` in
   the rubric so partials are principled.
3. **Non-attempt guardrail runs before both** (unchanged — the 1a machinery).

Measured, not assumed: the grader ships with `eval/grader_eval.py` (§7.2).

### 5.5 Pacing budgets (new actions)

Additions to `ACTION_BUDGETS` (checking actions stay tight by design):

| Action | max_words | max_sentences | micro_check |
|---|---|---|---|
| `COMPLETION_STEP` | 75 | 5 | try_step |
| `ISOMORPHIC_PRACTICE` | 40 | 2 | answer |
| `TEST_QUESTION` | 30 | 2 | answer |
| `TEST_FEEDBACK` | 20 | 2 | none |
| `TEST_SUMMARY` | 60 | 4 | yes_no |
| `MODE_OFFER` | 25 | 2 | yes_no |

`_mode_for_action` maps the TEST_* family to `probe`, COMPLETION_STEP to
`explain`.

### 5.6 Display (T9) — question & score cards

`_build_display` today returns at most one figure-crop item. Two additive display
item types (channel contract stays ESP32-compatible — the sink either renders or
ignores):

- `{"kind": "question_card", "text": "<item text>", "item_no": 3, "of": 5}` —
  TEST/ISOMORPHIC items rendered as a text card (the math-rendering path from
  f6b0071 already draws equations); on-screen persistence solves the voice-only
  "can you repeat the question" problem.
- `{"kind": "score_card", "score": 4, "of": 5, "per_item": ["✓","✓","✗","✓","✓"]}`
  — end-of-test summary.

`wini_platform`'s `ui_cards.py` already renders text cards (loading/ready/awake);
extend with these two layouts. Figure-crop display behavior is unchanged.

> **§5.6 build note (Stage 4, 2026-07-15, verified live on winipi5).**
> - `tutor_loop._mode_display(mode_item)` emits the card items; `turn()` prepends
>   them to `_build_display(...)` so a TEST turn's card is `display[0]` (a test turn
>   carries no figure). `_drive_test` now returns `question`/`item_no`/`of` on a
>   TEST_QUESTION and `results`/`correct`/`of` on a TEST_SUMMARY for the cards.
> - `ui_cards.py` gained `question_card` (header + word-wrapped body, auto-shrink to
>   one screen), `score_card` (pass/keep-going banner + big score + per-item marks
>   drawn as **shapes** — green dot / blue ring / red cross — because cv2's Hershey
>   font has no tick/cross glyph), and a `render_display_card(item)` dispatcher.
> - `wini_client/display_sinks.py` gained `render_item_frame(...)` which routes a
>   `kind` item through `ui_cards` and otherwise falls back to the figure crop;
>   Console/InProc/Ros sinks all use it. Unknown `kind` ⇒ ignored (ESP32/audio-safe).
> - **Voice/panel plain-text fix:** the generator was emitting LaTeX (`$12x^2y$`),
>   which both the cv2 card and the TTS render/read verbatim (neither speaks LaTeX).
>   Fixed at the source — `generate_quiz_item` now requires plain, already-evaluated,
>   spoken-style answers/questions — plus a `_plainify_math` belt on the question
>   (`\times`→"times", `^2`→"squared", strips `$`/delimiters). Live: 5/5 questions
>   came through as clean speech ("What is the HCF of 12x squared y and 18xy squared?").
> - KaTeX math rendering exists only in the **web UI** (f6b0071); the DSI/panel path
>   is cv2 plain text, which is why the source-side plain-text fix (not a panel LaTeX
>   renderer) is the right layer. **Deferred:** rendering these cards on the winipi5
>   DSI is the reserved client→UI `show_card` LVGL message (see the LVGL plan) — a
>   device-integration follow-on; the brain-side contract + the 480×320 render path
>   (Jetson / ROS-less panel) are done and verified.

---

## 6. What does NOT change (protection list)

Explicit, because every item here was a fought-and-won regression:

1. Front-door SAFETY/NONSENSE gates, scripted farewells, session-end hard stop.
2. Non-attempts never grade; confusion is never "wrong" (1a machinery).
3. CT/KT/KI probes are HOPE-scored only — never mastery, never misconceptions.
4. Probe-before-correct ordering; bridge gating; hint chains never leak answers.
5. Manifest-only generation (rule 12) — test questions and feedback also compose
   from evidence items, never model memory.
6. Analyzer writes soft state only; mastery moves only via the (now three)
   evidence APIs.
7. `pending_shift` topic-shift machinery; `rule 1a-vis/1w/1b/1c` overrides.
8. Perception runtime (gemini-only, cache, thresholds) — untouched until Stage 5,
   and then only additively with the full eval gate.

---

## 7. Evaluation plan (measure, never assert)

### 7.1 Unit/integration — `test_session_modes.py`
Transition-table coverage (every §4.1 row), offer/consume semantics
(bare yes/no, like `pending_shift` tests), ladder up/down movement, quiz-set
constraints (N, difficulty spread, coverage, exclusions, no `ct_probe`), freeze/
resume, corrective-plan construction from missed items, protection list §6
(regression asserts: a confusion plea mid-test grades nothing; a CT probe never
enters a quiz set; EXPLAIN mode output identical to pre-Part-12 on a scripted
transcript).

### 7.2 Grader eval — `eval/grader_eval.py` (NEW, offline-first)
A labeled set (~150–200 rows) of realistic child answers per item type: correct
(worded five ways, STT-mangled), partial, wrong, wrong-matching-a-known-
misconception, non-attempts (acks, confusion pleas, counter-questions,
off-topic). Sources: hand-written + the existing dataset's answer-attempt rows +
STT-noise transforms. **Gates:** ≥ 0.90 exact on correct/wrong; **zero**
non-attempts graded as wrong (hard gate — this is the standing guardrail);
partial disagreements reviewed, not gated, on v1. Cache the LLM calls (the
`--hardened --collect` vs `--score` pattern from `eval/perception_eval.py`);
wall-clock timeout on every call.

### 7.3 Behavioral state-trajectory eval — extend `eval/behavioral_eval.py`
Per CLAUDE.md, behavioral trajectory evals are the promotion instrument — not
label-F1-style proxies. New scripted multi-turn sessions asserting *state
trajectories*:

- **Practice ladder**: novice (mastery 0.3) gets a worked example first (never a
  cold problem); two clean solves ⇒ ladder rises; a 3-hint struggle ⇒ it falls;
  mastery strictly increases across a clean practice arc and the increase per
  item is bounded (no single-item mastery jumps).
- **Expertise reversal**: mastery 0.8 learner entering PRACTICE gets
  transfer/isomorphic items, never a full worked example.
- **Mastery gate**: scripted 5/5 test ⇒ gate pass + `test_history` row + next-
  concept offer; scripted 3/5 ⇒ corrective plan contains exactly the missed
  items' schemas, re-test items are isomorphic (surface differs, schema
  matches), and a re-test pass flips the gate.
- **Guardrails under modes**: mid-test confusion plea moves zero state; "bye"
  mid-test hard-stops with the scripted farewell and freezes `test_state`;
  resume restores it.
- **Interleave/spacing**: session with two practiced concepts produces a mixed
  set; a gate-passed concept resurfaces as exactly one review item next session.

**Promotion gate for each stage:** all its behavioral cases PASS + §7.1 green +
(for Stage 3) grader gates met + the pre-existing behavioral eval still PASS.

### 7.4 Store/bank verification
`verify_store.py` gains: every concept has ≥ 5 test-eligible items (question +
expected answer + difficulty), ≥ 2 distinct schemas or facets among them, and
≥ 1 isomorphic-regenerable schema (parallel-form capability). Run
`--fail-under 90` unchanged.

### 7.5 Live pilot metrics (once real learners run it)
Logged per session into the learning log, reported on the parent dashboard:
first-attempt correctness trend within practice; test score vs prior test on the
same concept (the learning-gain proxy); retention on spaced review items
(the metric retrieval practice predicts should rise); mastery-gate pass rate;
mode-time split. These are observational v1 — no gates until data exists
(the same "pilot metrics await real learners" stance as Part 8).

---

## 8. Execution stages (build one by one, each independently shippable)

| Stage | Contents | Acceptance gate |
|---|---|---|
| **0. Design freeze** | This document reviewed by the owner; contracts §4.2/§5.3 frozen | owner sign-off |
| **1. Mode substrate** ✅ | `session["mode"]` + ModeController skeleton + deterministic cues + mode offers/consumption + EXPLAIN==today | ✅ §7.1 transition tests green; EXPLAIN byte-equality on-brain (2026-07-14); no perception/classifier rebuilds |
| **2. PRACTICE** ✅ | ladder + representation rotation + `apply_item_result` + pacing budgets + interleaving | ✅ ladder + `apply_item_result` unit tests PASS; live PRACTICE dispatch verified on-brain (2026-07-14) |
| **3. TEST** ✅ | quiz-set builder (runtime generation) + hardened grader + serving loop + scoring/gate + corrective loop + `test_history` | ✅ §7.2 grader gates met (26/26, 0 non-attempts wrong); quiz-set/score/advance unit + `_drive_test` integration tests PASS; live 5/5 pass on-brain (2026-07-15). §7.4 store-bank metric N/A — audit found zero coverage, replaced by runtime generation. Pending: parked_questions, R4 spaced-review swap-in |
| **4. Voice + display polish** ✅ | T9 question/score cards (`ui_cards.py` + `_mode_display` + sink routing); voice-plain question generation; TEST_* pacing budgets in place | ✅ card render + routing unit tests GREEN (PNGs eyeballed); live on winipi5 — every TEST turn emits `question_card[i/5]`, summary emits `score_card` with per-item marks, questions come through as clean speech; per-turn latency 1.3–4.5 s. **Deferred:** on-DSI LVGL `show_card` (reserved client→UI message); full explain→practice→test spoken rig session |
| **4b. Test hardening (production review, 2026-07-16)** ✅ | (a) **active-test protection**: a mode tap (`X-Wini-Mode`, wini_server) or spoken mode cue (`resolve_mode`, session_modes) is BLOCKED while `test_state.phase != "done"`; only the explicit STOP cue abandons; a blocked spoken switch gets the acknowledgment line prepended to the next question. (b) **frozen-test resume (§4.4.4)**: on the first LEARNING turn after a session restart, `check_frozen_test` offers "Want to continue it?" — bare yes resumes the intact set (re-asking the pending question), bare no / ambiguous drops it and returns to EXPLAIN (leaving `mode=TEST` with no set would rebuild a quiz on the next unrelated question). (c) **atomic learner-state save**: tmp+fsync+rename with a `.bak` generation and corrupt→backup→cold-start recovery (`.corrupt` preserved). | ✅ 5 new test groups in `test_session_modes.py` GREEN (laptop + winipi5); live on-brain verification 2026-07-16: mid-test tap ignored (test echo kept serving), spoken "let's practice" blocked + acknowledged, bye→restart produced TEST_RESUME_OFFER → "yes" → TEST_RESUME re-asking question 2/5 |
| **5. Perception signals (gated)** ⏸ **DEFERRED (owner, 2026-07-15)** | `practice_request`/`test_request` into the enum catalog + few-shots; `build_perception`; Vertex cache recreate; hardened perception eval re-score + behavioral signal eval | Deferred: deterministic cues (Stage 1) already detect mode requests, so this is an optimization not a dependency. Design fork — INTENT enum (no `label_space` change) vs SIGNAL (moves trained `label_space` 38→40 + head eval baselines via the build's exact-cover drift guard); either validation is **billed**. Acceptance if built: perception eval ≥ current promoted numbers; behavioral eval PASS; cues kept as belt |
| **6. Reporting + docs** | parent dashboard quiz/gate views; `progress_report.py`; lockstep propagation §10; `rag_memory.md` entry | dashboard renders real `test_history`; all four lockstep docs consistent |

Suggested order rationale: 1→2→3 is strictly incremental risk; 4 first exercises
real voice UX where pacing problems surface; 5 is deliberately late because the
deterministic cues make Gemini signal detection an *optimization*, not a
dependency; 6 closes the loop for the actual stakeholder (the parent).

Dataset/bank work (Stage 3's long pole) can start in parallel any time: audit
`expected_answer` coverage per concept now; if thin, `build_quiz_bank.py` is an
offline Gemini batch job (hard wall-clock timeouts, `PYTHONIOENCODING=utf-8`,
outputs to a NEW file per the read-only-dataset mandate, human spot-check before
the store rebuild).

---

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Test anxiety / demotivation in a young learner | low-stakes framing everywhere ("let's see what stuck"), confidence opener item, no shaming on fail, celebrate gate passes; ENCOURAGE stays reachable in PRACTICE |
| Weak grader mis-grades → wrong mastery movement | deterministic-first grading; grader eval hard gates; partial credit conservative (0.5); non-attempt guardrail supreme |
| Quiz bank too thin per concept | §7.4 verification *before* Stage 3 ships; `build_quiz_bank.py` fallback; isomorphic regeneration stretches coverage |
| Mode layer fights the inner loop (two deciders) | single dispatch point §5.2 with an explicit precedence table; overrides always win; behavioral eval asserts it |
| Voice quiz UX friction (repeats, mishearing answers) | question card on screen (T9); STT-aware answer normalization in the grader; one free repeat per item |
| Session bloat in `session` dict / state file | mode structs are compact; `test_state.items` capped at N; learner-state additions are per-concept and bounded |
| Regression to today's UX for a child who just wants to chat and learn | EXPLAIN is default and byte-identical; modes only engage on offer-accept or explicit request |

---

## 10. Lockstep propagation checklist (run per shipped stage)

1. `learner_cognitive_state_architecture.md` — §6.4 (new state fields + third
   evidence API), §6.6 (mode layer + new actions + precedence table), §12
   (test_history/item_history stores), §13 (new rules: mastery gate, test
   conduct), §21 (new pacing budgets).
2. `RAG_upgrade_plan.md` — quiz-bank build/verify additions (if Stage 3 adds a
   bank builder), verify_store metric.
3. `model_dataset_architecture_report.md` — grader eval dataset, quiz bank
   derivation, (later) the knowledge-tracing data now being collected.
4. `complete_architecture_build_plan.md` — Part 12 section with **measured**
   stage results (never unmeasured numbers).
5. `rag_memory.md` — work-log entry per stage with gotchas.
6. `WINI_ARCHITECTURE.md` — external shape changed (modes) ⇒ update §2/§3 sketch.

---

## 11. Sources (literature reviewed 2026-07-11)

- VanLehn, K. (2006). *The Behavior of Tutoring Systems.* IJAIED 16(3). (two-loop model)
- Bloom, B. (1984). *The 2 Sigma Problem.* Educational Researcher. (mastery learning + tutoring)
- Roediger & Karpicke (2006). *Test-Enhanced Learning.* Psych. Science; Roediger, Agarwal et al. (2011) JEP:Applied. (testing effect, classroom quizzing)
- Renkl & Atkinson (2003–2007); Salden et al. (2009). *Faded worked examples; adaptive fading in Cognitive Tutors.* (worked-example effect, adaptive fading > fixed)
- Kalyuga, Ayres, Chandler & Sweller. *Expertise Reversal Effect.* (fade with mastery)
- Taylor & Rohrer (2010) *The Effects of Interleaved Practice*; Rohrer et al. (2014; 2019 RCT). (interleaving/spacing in maths)
- Rosenshine, B. (2012). *Principles of Instruction.* (guided→independent practice, review, ~80% success)
- Black & Wiliam (1998). *Inside the Black Box.* (formative assessment changes the next move)
- NCTM / SERP on multiple representations in mathematics.
- LearnLM technical report (Google, 2024); Khanmigo design notes; BEA 2025 shared task on pedagogical ability of AI tutors. (LLM-tutor pedagogy: modes, grounding, no answer-leak)
