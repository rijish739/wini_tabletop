# Brain Architecture Audit — raw utterance, grounding contract, and 14 defects

> **STATUS: RESOLVED 2026-07-23.** All 16 findings below are fixed and verified on
> `winipi5`, in the "Suggested order of work" order at the end of this file. The
> contract decisions this audit deferred were made in
> `learner_cognitive_state_architecture.md` (§6.1, §6.4, §6.6, §6.7); execution
> status and measured before/after are in `complete_architecture_build_plan.md`
> **Part 14**; gotchas are in `rag_memory.md`.
>
> Two items are explicitly **not** closed, and Part 14 says so: **D-7** (the doc's
> action list is still missing the `WHY_IT_MATTERS`/`SOCRATIC_Q`/`QUIZ`/`TEST_*`
> family) is a documentation-only divergence left open, and `transfer_readiness`
> is now implemented but **rule 5 still routes on the perception signal** rather
> than the measured field — switching it is a pedagogy change that wants its own
> evaluation.
>
> The text below is left exactly as written, as the record of what was found.

**Date:** 2026-07-23
**Auditor:** Claude (Opus 4.8), on request
**Device under test:** `winipi5` (Raspberry Pi 5, `192.168.29.24`), repo at
`/home/winipi5/cloud_tutor/cloud-CLI`, commit `b7421b3` + local modifications.
**Runtime for all live probes:** `GEN_BACKEND=gemini`, `PERCEPTION_BACKEND=gemini`,
`.venv/bin/python tutor_loop.py --once "<utterance>"`.
**Scope:** the reference documents are `learner_cognitive_state_architecture.md`
(§ references below are to that file) and the deployed code.

> **Why this is a separate file.** Per the 4-doc lockstep rule in `CLAUDE.md`, the
> architecture document is a *contract* document. An audit is a finding, not a
> contract change, so it lives here; `learner_cognitive_state_architecture.md`
> carries a pointer to it. Nothing in the contracts was edited — every fix below
> is a **proposal**, not an applied change.

---

## Part 0 — Direct answers to the questions asked

### Q1. "The brain is not sending the raw student utterance to the response model."

**This premise is incorrect.** The raw utterance *is* sent, verbatim, and I confirmed
it on the device.

The generation prompt is assembled in `qwen_answer()` and ends with
([tutor_loop.py:526](tutor_loop.py:526)):

```python
f"{hist_text}{ev_text}\n\nSTUDENT: {question}\n\nWINI:"
```

and the call site passes the untouched `text` argument of `turn()`
([tutor_loop.py:1990](tutor_loop.py:1990)):

```python
answer = qwen_answer(text, action, blocks, chapter_hint, ...)
```

`text` is never reassigned anywhere between `turn()`'s signature at
[tutor_loop.py:1514](tutor_loop.py:1514) and that call. It is not the normalized
string, not the concept label, not a summary — it is exactly what the STT layer
produced.

**Live proof.** I sent an equation whose specific numbers appear nowhere in the
retrieved evidence:

```
input : solve x^2 - 5x + 6 = 0
output: "...We need to find two numbers that multiply to 6 and add up to -5.
         These numbers are -2 and -3. ... The roots ... are x = 2 and x = 3."
```

It could not have produced `-2, -3, 2, 3` from concept-level NCERT chunks. The
exact numerals reached the model.

**So the premise is wrong — but the instinct behind it is right, and points at
three real defects.** They are A-1, A-2 and A-3 below. In short: the raw text
arrives, but three other mechanisms then fight it — a "use only the evidence"
instruction that contradicts it, a decision engine that has no action meaning
"solve what the student brought", and a word budget that truncates a multi-step
solution before the answer is spoken.

### Q2. "Why is it just taking output of cognitive state / concept resolver / learner state — structured output only?"

It isn't *only* structured output. The prompt actually carries five things: the
pedagogical action + tone, the recent conversation, the evidence blocks, the pacing
contract, and the raw `STUDENT:` line. The cognitive state does not enter the prompt
as numbers at all — it enters indirectly, by having selected the `action` and the
evidence.

The part of the concern that *is* real: the structured layer decides **what
speech-act Wini performs**, and that decision is made without regard to whether the
student asked a direct, answerable question. See A-2.

### Q3. "What is the use of preserving the math in the input processor and not providing it as an input to the response generator?"

The math *is* provided (see Q1), so the preservation is not wasted on the generator.
But the question exposes a genuine finding: **`InputProcessor` is 90% dead code.**

Of its 586 lines, the live pipeline calls exactly one method — `normalize_input()`
([analyzer.py:170](cognitive_analyzer/analyzer.py:170)). Everything the module was
built for and that §6.1 specifies as its responsibility —
the multi-label signal scores, `candidate_concepts`, and the metadata dict that
includes **`contains_formula`** — is computed by `process()`, which nothing in the
runtime ever calls. Verified: the only two importers are
[analyzer.py:152](cognitive_analyzer/analyzer.py:152) and
[gemini_perception.py:142](perception/gemini_perception.py:142), and both instantiate
it solely to normalize.

So the answer to "what is the use" is, today: **none beyond whitespace cleanup.**
The `contains_formula` flag that would let the system detect "this utterance contains
an equation to solve" is computed and thrown away. That flag is precisely the missing
input for fixing A-2. See D-1.

### Q4. "Sometimes the user wants the exact question passed to the response model, but here we are providing semantic meaning only. Is this the right way?"

The exact question *is* passed. But the design is still wrong in one specific way,
and it is worth stating precisely because it is the crux:

**Retrieval is semantic-only and concept-gated; generation is verbatim. The two
disagree, and nothing reconciles them.**

The retrieval query is the *normalized* text embedded by MiniLM
([tutor_loop.py:1918](tutor_loop.py:1918)):

```python
q_emb = self.analyzer.classifier.embed([analysis["normalized_text"]])
```

and the candidate pool is hard-filtered to chunks whose `concept_ids` intersect the
resolved concept ([tutor_loop.py:1915](tutor_loop.py:1915)). For
`solve x^2 - 5x + 6 = 0` this is fine. For a student-specific problem it means the
evidence pack can never contain anything about *their* numbers — so the generator is
handed a verbatim question plus evidence that cannot support answering it, and an
instruction saying to use only that evidence. The model resolves the contradiction
by ignoring the instruction. That works by luck, not by design.

**Verdict on "is this the right way": the transport is right, the contract is
wrong.** The fix is not to pass more raw text — it already gets it. The fix is to
make the *grounding contract conditional* on whether the turn is curriculum teaching
or student-problem solving, and to give the decision engine an action for the latter.

---

## Part 1 — Architecture-level bugs

### A-1 (High) — The grounding contract is stated absolutely but violated on every solve turn

§6.7 states: *"The response layer may compose only from manifest items"*, and the
prompt enforces it in words ([tutor_loop.py:522](tutor_loop.py:522)):

> `"Use ONLY the evidence below — if it does not support a claim, say less."`

**Live counter-example.** I gave a word problem that is not in the retrieved pack:

```
input : A train travels 63 km in the same time a car travels 72 km.
        The car is 6 km/h faster. Find the speeds.
output: "Let the speed of the train be x km/h ... 63(x+6) = 72x ... 378 = 9x ...
         x = 42. So, the speed of the train is 42 km/h. The speed of the car is 48 km/h."
```

Every numeral in that derivation came from Gemini's own arithmetic, not from a
manifest item. The stated contract is therefore **not enforced anywhere** — it is a
prose request to a model that outranks it whenever the student's question is more
concrete than the evidence.

Why this matters beyond pedantry: §6.7 justifies the manifest as what "makes
grounding auditable, and provides the labeled pairs the grounding-guard model trains
on." If the contract silently fails on solve turns, the learning log records a
manifest that did **not** produce the answer. Any future grounding-guard trained on
those pairs learns from mislabeled data.

**Proposed fix.** Split the contract in two and make the split explicit in §6.7:
- *curriculum teaching turns* — manifest-only, as today;
- *student-problem turns* — manifest grounds the **method**, the student's own
  numbers are authoritative for the **instance**, and the manifest records
  `grounding: "method_only"` so the log stays honest.

### A-2 (High) — No pedagogical action means "solve the problem the student brought"

The §6.6 action catalog is entirely curriculum-item-driven: explain, quiz, hint,
faded hint, counterexample, transfer problem, analogous worked example, isomorphic
practice, bridge recap, review, encourage, corrective explanation, representation
translation, metacognitive reflection. **Every one of them is served *from the
store*.** There is no action whose object is the utterance itself.

The consequence is not hypothetical. On the train/car problem the engine chose:

```
ACTION: TRANSFER_PROBLEM | rule 5: transfer readiness -> near transfer first (section 6.6)
```

and `TRANSFER_PROBLEM`'s tone instruction is
([tutor_loop.py:399-401](tutor_loop.py:399)):

> *"Give the student a NEW problem... State the problem in plain words and ask for
> their answer. **Do NOT solve it or give hints unless asked.**"*

A child handed the tutor a problem and asked for the speeds; the brain decided to
hand them a *different* problem and explicitly not solve theirs. It only came out
right because the model disobeyed.

The routing path is: a word problem trips the `transfer_attempt` signal (Gemini
scored it 0.70), which raises the `transfer_ready_evidence` flag
([analyzer.py:101](cognitive_analyzer/analyzer.py:101)), which rule 5 matches
([tutor_loop.py:135](tutor_loop.py:135)). **Any student-supplied word problem looks
like a transfer attempt**, because structurally it is one — the student is applying
the concept to a new situation. The signal is correct; the action mapped to it is
wrong.

Worth noting: the policy shadow disagreed with the rule engine on this turn
(`EXPLAIN` p=0.311 vs `TRANSFER_PROBLEM` p=0.2375). The shadow was right and is
logged-only.

**Proposed fix.** Add a `SOLVE_STUDENT_PROBLEM` action, ranked *above* rule 5, gated
on a deterministic cue (an equation, or an imperative solve/find/calculate verb plus
numerals) — exactly what `InputProcessor.metadata["contains_formula"]` already
computes and discards (D-1). Its contract: work the student's instance through to
the final result using the manifest's method, then check understanding.

### A-3 (High) — The spoken word budget makes multi-step solutions structurally impossible

`ACTION_BUDGETS` gives `EXPLAIN` **65 words / 4 sentences** and `TRANSFER_PROBLEM`
**45 words / 3 sentences** ([pacing_controller.py:20-27](pacing/pacing_controller.py:20)).
`_truncate_to_spoken_budget()` ([tutor_loop.py:574](tutor_loop.py:574)) then keeps
whole sentences up to those caps.

The train/car answer is ~190 words across ~15 short lines. Truncated to 4 sentences /
65 words the child hears:

> *"Let the speed of the train be x km/h. Since the car is 6 km/h faster, the speed
> of the car is (x+6) km/h. Time taken by the train to travel 63 km is 63/x hours.
> Time taken by the car..."*

**The student never hears `x = 42`.** The setup is delivered and the answer is
silently discarded. This is not a truncation edge case — it is the guaranteed outcome
for any problem needing more than ~4 sentences, and it will read to a child as the
tutor trailing off mid-thought.

Note this is *not* a licence to clamp answer length globally — the memory
`answer-length-stays-dynamic` is explicit that length must stay dynamic. The defect
is the opposite: the budget is applied **uniformly by action**, with no notion that a
derivation is atomic and must not be cut between its setup and its result.

**Proposed fix.** Make truncation *structure-aware*: if the reply contains a
terminal result line, that line is protected from the cap the way the trailing
micro-check question already is at [tutor_loop.py:601-607](tutor_loop.py:601). Give
the proposed `SOLVE_STUDENT_PROBLEM` action a derivation-sized budget.

### A-4 (Medium) — Retrieval has no absolute relevance floor and cannot abstain

In `snapshot_rerank()` the semantic term is normalized against the best item in the
pool ([query.py:171,176](query.py:171)):

```python
rel_max = max(r.get("score", 0.0) for r in ranked) or 1.0
rel = r.get("score", 0.0) / rel_max
```

So `w1_relevance` is **relative**, and the top item always scores 1.0 on it — even
when the entire pool is irrelevant. Combined with the hard concept-id pre-filter
([tutor_loop.py:1915](tutor_loop.py:1915)), a wrong concept resolution produces a
confidently-ranked pack of wrong evidence with no signal that anything went wrong.
There is no minimum-similarity gate and no "retrieved nothing useful" path.

§6.7 specifies the ranking contract but never specifies an abstention threshold —
this is a gap in the architecture, not just the code.

### A-5 (Medium) — `w4_repr_gap` is a dead term: 12% of the ranking score is a constant

`representations_missing` is derived from `representations_known`
([learner_state.py:119-122](learner_state.py:119)). That field is written on exactly
one path ([tutor_loop.py:1761-1766](tutor_loop.py:1761)): the previous turn's action
must have been `REPRESENTATION_TRANSLATION` **and** the current utterance must be a
pure acknowledgment.

**On the live device, 0 of 40 concept states have `representations_known`.** So
`representations_known` is always `[]`, `representations_missing` is always the
concept's full representation list, and `repr_gap` evaluates to 1.0 for every chunk
that declares any representation ([query.py:180](query.py:180)). A 0.12-weighted term
that fires identically for nearly all candidates contributes no ordering information.

§9 ("Representation-Centric Learning") is, in practice, not operating.

### A-6 (Medium) — Cognitive flags are write-only for the tutor, and append-only forever

`apply_deltas()` accumulates concept flags and **never removes any**
([analyzer.py:135-139](cognitive_analyzer/analyzer.py:135)):

```python
existing = cs.setdefault("flags", [])
for flag in deltas["concept_flags"]:
    if flag not in existing:
        existing.append(flag)
```

Two separate problems follow.

**(a) The tutor never reads them.** I traced every reader of `concept_states[...]["flags"]`:
the only consumer is [progress_report.py:217](progress_report.py:217) — the parent
dashboard. `rules_decide` is passed `analysis["state_deltas"]["concept_flags"]`, the
**turn-local** flags ([tutor_loop.py:1831](tutor_loop.py:1831)), not the persisted
ones. So §6.4's per-concept flag memory does not influence a single pedagogical
decision. *(I initially suspected sticky flags were locking the router into
`TRANSFER_PROBLEM`; tracing the call site disproved that. The routing bug is A-2,
which is turn-local.)*

**(b) The parent dashboard reports them as current.** Because they never clear,
`progress_report.py` shows a transient one-turn signal as a standing condition. Live
state: `misconception_suspected` on 4 concepts, `hint_requested` on 6,
`transfer_ready_evidence` on 5 — with no timestamps and no decay. The dashboard even
sorts topics by flag count ([progress_report.py:242](progress_report.py:242)), so a
topic the child had one confused moment on months ago outranks a genuinely weak one
forever.

### A-7 (Medium) — The no-repeat set is session-scoped by name but permanent in practice

§6.4 specifies *"items already served **this session**"*. The implementation stores it
under `session.served_items` in the persisted learner state
([learner_state.py:154](learner_state.py:154)) and `snapshot_rerank` **drops** every
member from the candidate pool outright ([query.py:174](query.py:174)):

```python
if r["chunk_id"] in snapshot.served:      # no-repeat within a session
    continue
```

But `learner_state.json` persists across runs, and the only code that clears the set
is [wini_ui_server.py:139](wini_ui_server.py:139) — a *different* entry point. Neither
`run_wini_package.sh` nor `wini_server.py` resets it.

**Live count: 593 items permanently blacklisted.** This monotonically starves
retrieval: the best chunk for a concept is excluded from every future turn after the
first, forever, and quality degrades toward whatever is left over. It also breaks
re-explanation — rule 1b ("re-explain the same idea more simply") is denied the very
evidence that explains it.

A hard `continue` is also the wrong mechanism; a repeat penalty would let a strong
chunk resurface when nothing better exists.

### A-8 (Low) — Bridge selection is unstable and frequently irrelevant

Two runs of the *identical* train/car utterance produced different armed checks:

| Run | `pending_check` |
|---|---|
| 1 | `grade9::ratio_and_proportion` |
| 2 | `grade9::mean_average` |

and run 1 additionally listed `bridge::grade9::probability::jemh1a2` in `bridge_ids`.
Neither mean/average nor probability is a prerequisite for forming a quadratic from a
distance–speed–time relation. The §6.8 bridge gate is selecting on graph adjacency and
mastery, with no relevance check against the current utterance, and the resulting
Class-9 diagnostic is armed as a graded `pending_check`.

---

## Part 2 — Code vs. `learner_cognitive_state_architecture.md`

| # | §  | Document says | Code does | Severity |
|---|----|---|---|---|
| D-1 | §6.1 | The Cognitive Input Processor detects question / answer attempt / explanation / confusion / misconception clue / transfer attempt / topic shift, and must "not reduce the utterance to one label too early" | Only `normalize_input()` is ever called. `process()` — all signals, `candidate_concepts`, and the `contains_formula` metadata — is dead code. Signals actually come from Gemini perception. | High |
| D-2 | §6.7 | "The response layer may compose only from manifest items" | The raw utterance is appended after the evidence and the model answers from its own knowledge whenever the evidence can't support the ask (A-1) | High |
| D-3 | §6.4 | Per-concept tracking of: mastery, misconception map, representation coverage, recent correctness, hint dependency **and hint-chain position**, **cold recall strength**, **transfer readiness**, **confidence trend**, last practiced | Live device: 40 concept states carrying only `flags`(16), `mastery`(10), `last_practiced`(10), `item_history`(1), `test_history`(1), `mastery_gate`(1), `struggle`(2), `hints_used_current`(2). **Cold recall strength, confidence trend, transfer readiness, and hint-chain position have no field and no API at all.** `representations_known` has a getter but effectively no writer (A-5). | High |
| D-4 | §6.4 | Mastery is the authoritative per-concept memory | **Only 10 of 40 concepts have a `mastery` value.** The other 30 fall back to `COLD_START_MASTERY`, so the ZPD band (`resolve_band`) is cold-start for 75% of touched concepts — the learner model is far sparser than the ranking layer assumes. | High |
| D-5 | §6.4 | "items already served **this session**" | Persisted across every session and never cleared on the device launch path; 593 entries (A-7) | Medium |
| D-6 | §6.6 | Flags/state feed the decision engine's "Decision inputs" list | Persisted flags are read only by the parent dashboard; the engine sees turn-local flags only (A-6a) | Medium |
| D-7 | §6.6 | Action catalog | Code adds `WHY_IT_MATTERS`, `SOCRATIC_Q`, `QUIZ` and the Part-12 `TEST_*`/`COMPLETION_STEP`/`ISOMORPHIC_PRACTICE` family; the doc's list is stale and omits them. Conversely the doc lists "faded hint" and "cold recall" behaviours with no corresponding action in `rules_decide`. | Low |
| D-8 | §6.2 | `apply_deltas` docstring claims it writes "flags + `last_signals` on the concept state" | `last_signals` is never written anywhere | Low |

---

## Part 3 — Other bugs found

### B-1 (High) — `\frac{}{}` survives the speech sanitizer and corrupts spoken maths

`sanitize_for_speech()` strips `\command` names ([voice/sanitize.py:77](voice/sanitize.py:77))
but **never strips braces** — unlike `_plainify_math()` in `tutor_loop`, which does
([tutor_loop.py:694](tutor_loop.py:694)). Verified locally against the actual text the
device generated:

```
'Time is $\frac{63}{x}$ hours.'   ->  'Time is {63}{x} hours.'
'x = $\frac{378}{9}$ = 42'        ->  'x equals {378}{9} equals 42'
```

The fraction is not just mispronounced — **its meaning is destroyed**. "63 over x"
becomes "63 x". On a voice-first device teaching maths, this silently teaches the
wrong thing. `_plainify_math` and `sanitize_for_speech` are two divergent
implementations of the same job; the weaker one is on the spoken path.

**Fix:** add brace stripping and a `\frac{a}{b}` → "a over b" rule to
`voice/sanitize.py`, and add these two strings to its `__main__` samples.

### B-2 (Medium) — Gemini emits LaTeX despite the pipeline being voice-first

Both live solve turns returned `$...$`, `\frac`, and `\\` markup. Nothing in
`qwen_answer`'s prompt tells the generator not to — the "no LaTeX, no $ signs, no
backslash commands" instruction exists **only** in `generate_quiz_item`
([tutor_loop.py:738](tutor_loop.py:738)). The main answer prompt is missing it, so the
system relies entirely on the downstream sanitizer that B-1 shows is incomplete.

**Fix:** add the plain-words instruction to the `style_cue` block at
[tutor_loop.py:503](tutor_loop.py:503). Cheaper and more reliable than sanitizing after
the fact — and it also fixes the display card, which runs its own separate `_delatex`
([display_sinks.py:264](wini_client/display_sinks.py:264)) — a *third* implementation
of the same de-LaTeX job.

### B-3 (Medium) — The T9 teaching visual shows an unrelated figure

On `solve x^2 - 5x + 6 = 0` the display channel pushed:

```
figure_crops/jemh104/fig_jemh104_fig_4_1.png
alt: "a rectangular prayer hall ... breadth 'x' and length '2x + 1' ... area 300 m²"
why: "teaching visual: most relevant crop for this explain turn"
```

A prayer-hall area diagram while the tutor factorises an unrelated quadratic. The
tier-3 default-on teaching visual (per the `t9-teaching-visual` memory) picks the
best-ranked crop **within the concept** with no relevance floor against the actual
utterance — the same absent-threshold problem as A-4, surfacing on the display
channel where a child sees it. A visual that contradicts the spoken content is worse
than no visual.

### B-4 (Low) — Pacing ledger fields are stale, cross-topic, and unread

Both quadratics runs reported pacing state left over from a **trigonometry** session:

```
"last_explanation_summary": "Trigonometry is about finding unknown sides or angles..."
"pending_micro_check": {"question": "Do you see the right angle at B?"}
"explanation_step": 230
```

`explanation_step` is incremented at [pacing_controller.py:169](pacing/pacing_controller.py:169)
and **never reset** on topic change. I checked every reader: `explanation_step` and
`last_explanation_summary` are written and never read by any decision path, so this is
dead state rather than a behavioural bug. It is still worth fixing — it is emitted in
every turn's diagnostic JSON and in the `/health` surface, where it will mislead the
next person debugging a live session into chasing a topic the child left long ago.

### B-5 (Low) — Duplicated, divergent math-to-text implementations

Three separate implementations of "make maths readable", each with different
coverage: `_plainify_math` (tutor_loop, quiz questions — strips braces),
`sanitize_for_speech` (voice path — does not strip braces, B-1), and `_delatex`
(display_sinks, panel — handles `\frac`). They will keep drifting apart. One shared
module with one test suite.

---

## Severity summary

| ID | Title | Severity | Kind |
|---|---|---|---|
| A-2 | No action means "solve the student's problem" | **High** | Architecture |
| A-3 | Word budget truncates away the answer | **High** | Architecture |
| A-1 | Grounding contract stated absolutely, violated routinely | **High** | Architecture |
| B-1 | `\frac{}{}` corrupts spoken maths | **High** | Code |
| D-1 | InputProcessor 90% dead; `contains_formula` discarded | **High** | Divergence |
| D-3 | Four §6.4 per-concept fields have no implementation | **High** | Divergence |
| D-4 | Only 10/40 concepts have measured mastery | **High** | Divergence |
| A-7 | 593 chunks permanently blacklisted from retrieval | Medium | Architecture |
| A-4 | No relevance floor, no abstention | Medium | Architecture |
| A-5 | `w4_repr_gap` is a constant | Medium | Architecture |
| A-6 | Flags append-only; parent dashboard reports stale conditions | Medium | Architecture |
| B-2 | Answer prompt lacks the no-LaTeX instruction | Medium | Code |
| B-3 | T9 shows an unrelated figure | Medium | Code |
| A-8 | Bridge selection unstable and irrelevant | Low | Architecture |
| B-4 | Stale cross-topic pacing ledger | Low | Code |
| B-5 | Three divergent math-to-text implementations | Low | Code |

## Suggested order of work

1. **B-1** — one-file fix, and it is currently teaching wrong maths aloud. Do it first.
2. **A-2 + A-3 together** — they are one user-visible failure ("I asked Wini to solve
   my problem and it changed the subject / trailed off"). A-2 needs D-1's
   `contains_formula` revived.
3. **A-7** — a one-line reset in the launch path recovers retrieval quality that is
   currently degrading with every session.
4. **B-2, B-3** — prompt and threshold changes, low risk.
5. **A-1, A-5, A-6, D-3/D-4** — these need contract decisions in
   `learner_cognitive_state_architecture.md` before code, and per the lockstep rule
   the change must propagate to `complete_architecture_build_plan.md` and
   `model_dataset_architecture_report.md` in the same session.

## Reproducing the live probes

```bash
MSYS_NO_PATHCONV=1 PI_PASS=roavai python tools/pi.py run "cd /home/winipi5/cloud_tutor/cloud-CLI && GEN_BACKEND=gemini PYTHONIOENCODING=utf-8 .venv/bin/python tutor_loop.py --once 'solve x^2 - 5x + 6 = 0'"
```

Note the brain was **not** running during the audit (`/health` unreachable,
no `wini_server` process); every probe was a direct `tutor_loop --once` invocation
against the same code the server imports. Each probe makes billed Vertex calls.
