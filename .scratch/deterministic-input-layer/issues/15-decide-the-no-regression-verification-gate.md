# Decide the no-regression verification gate

Status: resolved
Type: grilling
Blocked by: 14, 07

## Question

This effort deliberately changes behavior, so how do we prove nothing broke?

The precedent map solved the equivalent problem for a **behavior-preserving** split: it froze
a `baseline_oracle` (`cloud_run_service/baseline_oracle/`, tickets 02 and 11) with a frozen
corpus, a replay gateway, and observation comparison, then required byte-level equivalence.
That rule cannot transfer unchanged here — a six-way safety split, a PII detector, and an STT
uncertainty contract all change observable output by design.

Decisions to close:

- **What must stay identical, and what is allowed to change?** Candidate invariants: every
  utterance the current SAFETY lexicon trips must still trip (recall may only go up);
  `detect_student_problem`'s verdicts are unchanged; `normalize_input` stays idempotent and
  math-preserving; NONSENSE never gates a terse real answer.
- **Can `baseline_oracle` be reused** with a partition — an "unchanged" partition compared
  strictly, and a "deliberately changed" partition compared against new expectations? Or does
  this effort need its own harness?
- **The measurement rule.** CLAUDE.md: *"Never edit a number in a doc without re-measuring
  it."* Gate recall is measured with `python -m eval.perception_eval --gates`. What is the
  full command set, and what numbers must the spec carry?
- **The promotion-gate lesson.** CLAUDE.md records that the Part 11 signal promotion was
  gated on a *behavioral state-trajectory* eval, not label-F1, because label-F1 was won by
  construction — and warns "do not resurrect that gate." Is there an analogous trap here?
  A safety taxonomy scored against a labelled safety dataset may be the same mistake; docx
  §14's audit finding says as much: *"A test result showing very high recall on a controlled
  SAFETY dataset is encouraging but is not proof that real children will be protected."*
- **Release gating.** Docx §15 lists five release gates. Which of them does this layer's
  verification satisfy, and which are explicitly someone else's (safety operations, privacy
  sign-off, red-team)? The spec should say what it does **not** cover, so nobody reads a green
  test run as child-safety assurance.
- **Performance.** The precedent map required performance parity. Does a maths grammar plus a
  PII pass on every turn have a latency budget, given Cloud Run `min-instances=1` and the
  measured per-turn costs?

---

## Safety annex handed down by ticket 07 (2026-08-26)

This effort is deliberately not behavior-preserving, but safety behavior is not therefore
unconstrained. 07's change replaces the **primary** detector (regex lexicon -> a dedicated
Gemini call), so the usual equivalence instinct does not apply and these five clauses take
its place. They are 15's safety gate; 15 still owns the mechanism and the rest of the gate.

1. **Cutover gate — billed once, stop-ship.** Before cutover, the union of (safety model +
   perception's `safety` bit + degraded net) must trip on **every** utterance that trips
   today's shipped lexicon, measured on the union of the legacy 20, the per-class corpora and
   the FP corpus. A model that misses a disclosure the shipped system catches does not go
   out, however much better it is elsewhere.

2. **The legacy 20 are a permanent regression suite** (`eval/perception_eval_safety.jsonl`) —
   never the recall measurement, never allowed to break.

3. **Every tier-3 demotion is enumerated in advance** in the taxonomy doc §11 and the list is
   closed before the cutover eval runs. A demotion discovered at test time is a **test
   failure**, not a finding. (07 deliberately demotes bare ideation, un-marked "i'm in
   danger", and non-imminent abuse disclosure from tier 3 to `ELEVATED`.)

4. **No precision gate on the axis, ever.** The FP corpus may improve; it is never required
   to. A future recall broadening must never be blockable by precision.

5. **No flag-gated dual run.** Clause 1 makes the change a superset on the axis by
   construction, so a cutover is safe; a flag would recreate two safety lexicons drifting
   apart — the exact problem 07's "the lexicon runs once, in Intake" rule removed.

**Plus a standing gate, not a one-off:** `eval/safety_eval.py` must pass before **any** of a
safety-prompt change, schema change, `VERTEX_SAFETY_MODEL`/`VERTEX_SAFETY_LOCATION` change,
context-cache rebuild, or Vertex model-version pin change. Unlike a regex, a model's safety
recall moves **silently**; the model version is pinned explicitly for the same reason.

Floors: model axis >= 0.95 (stop-ship), model per-class >= 0.80 (stop-ship for that class —
below floor the class does not enter the enum), degraded net axis >= 0.90 (published, never a
gate on the model). See `docs/architecture/SAFETY_ROUTE_TAXONOMY.md` §10.

---

## Resolution (2026-08-27, /grilling)

**There is no equivalence gate, because there is no single change to be equivalent to.** The
effort lands in **three stages**, each with its own entry gate, over one **standing set** that
is never allowed to go red at any stage. What "nothing broke" means is stated per stage, and
the two things that legitimately change are not compared loosely — they are compared against a
**closed, symmetric expected-diff manifest**, so a deliberate change is distinguishable from a
bug unless someone forgot to write it down.

Five organizing rules produced every decision below.

1. **Stage the gate, or the gate stages you.** One all-or-nothing gate would make a green
   Intake wait on a safety cutover it does not depend on, and the pressure to waive it would
   arrive on cutover day.
2. **A deliberate behavior change is a claim, and a claim is checkable both ways.** An
   unlisted diff fails; a manifest row that stops producing a diff *also* fails.
3. **Byte-equality is only meaningful where nothing was meant to move.** After ticket 03 that
   is a very small set, and pretending otherwise is how an equivalence harness becomes a
   rubber stamp.
4. **Per-row label numbers never testify about turns.** This is the Part 11 promotion-gate
   lesson in its general form, and it has two live instances here.
5. **A green run is evidence about code, not assurance about children.** That sentence goes at
   the *top* of the spec's verification section, not the bottom.

### Premise corrections (verified against the repo, 2026-08-27)

Four of this ticket's premises are stale, wrong, or falsified by a later resolution.

1. **`baseline_oracle` cannot be reused as an equivalence gate — its frozen reference was
   never completed.** `reference/metadata.json` records `capture_mode:
   "offline_contract_characterization"`, `network_calls: 0`, `billed_model_calls: 0` and four
   `capture_limitations` (missing `policy_logreg.npz`, `signal_heads.npz`, the local chunk
   index, `model_boundary_replay_incomplete`). `verify.py:22` returns
   `status: "blocked", reason: "canonical_reference_incomplete"` unconditionally, and
   performance was never measured. The oracle has never once run green.
2. **This ticket's own candidate invariant is falsified.** *"`normalize_input` stays idempotent
   and math-preserving"* — ticket 03 **deleted NFKC** from the published form because ticket 10
   measured it destroying `x²`→`x2` and dropping U+2212. Today's `normalize_input` is not
   math-preserving; the new one is deliberately not byte-equal to it. Idempotence survives;
   equivalence does not.
3. **`detect_student_problem` is not Tier A either.** Ticket 03 (`03-...md:368`) already hands
   15 **three measurable deltas, none assumable**: `detect_student_problem` moving from raw to
   normalized text, the NFKC removal, and the `TurnPhase` insert — the last being a hard
   coordinator change, because `_validate_phase_trace` requires the executed trace to equal
   `LOGICAL_TURN_PHASES` **exactly** (`runtime/coordinator.py:385`).
4. **The perception promotion gate is entirely unrunnable, not just `--gates`.** `score()`
   calls `measure_gates()` (`eval/perception_eval.py:517`), which imports `perception.gates`
   (`:226`) — and there is no root `perception/` package. `--gates`, `--score` and `--run` have
   all been dead since the modules moved under `cloud_run_service/`. The shipped `1.0` was
   measured before that move, and the hard-coded `gates["safety_gate_recall"] >= 1.0`
   criterion (`:562`) has never been executable.

And a scoping correction: **ticket 14 already spent most of this ticket's mechanism budget** —
the two lanes, the CI topology, the manifest, the six invariant assertions, the integration
tier and the sign-off rule are decided there. 15 is the **assembly**, the **release mapping**
and the **numbers** — not a second harness design.

### The three stages

| Stage | Unit | Lane | Prerequisite | Entry gate |
|---|---|---|---|---|
| **1** | Utterance Intake — contracts, grammar, coordinator phase | free only, **no billed run at all** | none | below |
| **2** | `child_safety/` cutover | billed, team-approved | **WIF ticket landed** | 07 §10.5 + floors |
| **3** | `personal_data/` | billed, team-approved | **WIF ticket landed**, Stage 2 complete | 09 §12 floors + two structural assertions |

Stage 1 needs no credential of any kind — forced by 14's finding that Intake ships with no
model call and no network. **Stages 2 and 3 are blocked on the Workload Identity Federation
ticket** (14's spawned backlog item, owner TBD): the billed jobs are wired to a `WIF_PROVIDER`
secret that does not exist and fail loudly. This is stated on the stage entry line, not in a
footnote, so it is not discovered on cutover day.

**Stages 2 and 3 are ordered: safety first.** `PERSONAL_DATA_CONTRACT.md` §9.2 makes the safety
case record a *consumer* of the personal-data verdict (identifier **class labels**, never raw
values) but says the case record **never waits** — it is written with the privacy field stamped
`privacy_unavailable`, and a late verdict unions in. Between the two cutovers that stamp is
permanent rather than transient, which is a true statement about a system whose PII detector
does not exist yet. The reverse order would ship a PII detector whose most sensitive consumer
is unbuilt.

**Stage 1 pass set** — `unittest discover` green across every `cloud_run_service/*/tests`;
Tier A byte-identical; Tier B every diff row matching the closed manifest; the
`TurnPhase.UTTERANCE_INTAKE` insert passing `_validate_phase_trace`; the six source guards plus
ticket 04's surviving `cognitive_classifier.cues` import guard; the four stubbed turn-level
properties; corpus integrity green over **all** corpora, including those authored now for
Stages 2–3; the tier-3 exception list measured and closed; the perf baseline recorded; the
grammar's refusal rate measured over claimed maths spans and recorded.

**Stage 2 pass set** — standing set green; 07 §10.5 union cutover gate (billed once,
stop-ship); model axis recall >= 0.95; per-class >= 0.80; incremental recall and union recall
published as **separate** numbers; no mixed prompt-hash caches; corpora reviewed (no cutover on
unreviewed numbers, per 14).

**Stage 3 pass set** — standing set green; per-class recall >= 0.80; maths-dense FP <= 1%; and
the two structural assertions that are the actual contract: `RedactedText` unconstructable
without a landed verdict, and no raw identifier value in any `__str__`/`__repr__`.

**A class below its 0.80 floor does not block the cutover.** It stays out of the enum (07 §3),
and the compensating control is that it is **named in the release record and in the
not-covered statement**, not only filed in a backlog. Blocking on all seven would keep today's
measurably worse lexicon in production while we wait — a class at 0.75 beats a class at 0.0,
which is what ships now — but a held-out class is invisible downstream (indistinguishable from
"this never happens"), so it must be visible where a human reads it.

**The standing set** — never red at any stage: `unittest discover`; Tier A; corpus integrity;
the source guards; the legacy 20; the phase-trace assertion; the degraded net's **freeze**; the
perf regression guard.

**The legacy 20 are written against the composition function from day one.** The test calls the
union entry point — the shared helper in `interaction_control` (taxonomy §6.7) — whose
implementation is the lexicon reading plus perception's bit until `child_safety` lands, and
which gains the model verdict at cutover. The test file is never edited at the cutover; the
thing under it changes. This also exercises the composition seam months before it matters,
which is where composition bugs are cheap.

### The equivalence partition: three tiers

| Tier | Contents | Rule |
|---|---|---|
| **A — byte-identical** | `gate()`'s NONSENSE decisions over the 9-row probe **and** the terse-real-answer set (`5`, `x=3`, `no`, `½`) | asserted; any difference is a failure |
| **B — expected diff** | `normalize_input` (NFKC removal) and `detect_student_problem` (raw → normalized input) | every diff row matches the **closed** manifest, and every manifest row produces a diff |
| **C — unconstrained** | everything downstream of the two new model calls | measured by the Stage 2/3 floors, never by equivalence |

The safety lexicon's trip-set is **not** Tier A here. It is Stage 2's cutover gate (07 §10.5);
duplicating it into Stage 1 would gate Intake on a package that does not exist.

**The frozen input corpus** is authored fresh under `utterance_intake/tests/fixtures/`, >=150
rows, seeded from `baseline_oracle/fixtures/corpus.json`'s 27 Turn Inputs and extended against
what this effort actually changes — the 27 were written to exercise a *turn*, not a normalizer.
Must include: the maths typography NFKC destroyed (`x²`, `½`, U+2212, U+00A0, zero-width
joiners); ticket 11's four measured confident false negatives; the terse-real-answer set; the 9
`NONSENSE_PROBE` rows; ticket 10's 42 homophone rows; and equation / expression /
solve-verb+numerals rows for each `ProblemCue`. Same JSONL schema as every other corpus, so the
integrity test stays one validator. **Authored or synthetic only** — 14's no-production-rows
rule holds.

**The expected-diff manifest** is `utterance_intake/tests/fixtures/expected_diffs.jsonl`, rows
`{id, function, input_id, before, after, reason, ticket}`, `ticket` naming the resolution that
authorized the change (03 for both). Closed = committed before the comparison first runs.
**Symmetric:** an unlisted diff fails, *and* a manifest row that produces no diff fails. The
manifest is a claim about exactly which behaviors change; both halves are checkable, so both
are checked.

### No end-to-end equivalence oracle

`baseline_oracle` is **borrowed, not reused**: its corpus seeds the frozen input set, its
required-coverage pattern is already borrowed by 14, and its normalization-forbidden-surfaces
list informs Tier A. Its reference is **not** repaired by this effort, and the spec says so
explicitly — otherwise the next reader sees a `baseline_oracle/` in the tree and assumes
coverage that has never run. The Tier A/B comparison is a small offline characterization runner
over frozen JSONL in `utterance_intake/tests/`, in the free lane.

### The promotion-gate trap, and the four turn-level properties

The Part 11 trap was **grading a component on labels instead of on the trajectory it
produces**. 14's controls (blind authoring, TDD ordering, different-generator family,
exact-match-not-judge) defend against *corpus* mirroring; they do not defend against this. Two
live instances: an Intake suite 100% green on `LegibilityCue` labels while the repair loop
still loses the child's answer; and a safety detector at 0.97 axis recall whose findings never
reach a case record because the release path drops them. Both are pass-on-labels,
fail-in-turn.

**Four turn-level properties in `runtime/tests/`, free lane, no model calls** (injected stub
verdicts): the repair round-trip preserves `provenance.repairs`; a stubbed `CRITICAL` verdict
reaches the case record with perception held; a stubbed 5s timeout releases in degraded mode
with the `safety_model_unavailable` stamp; a terse real answer survives the full
Intake→`gate()` path. Plus a written rule in the spec: **no per-row label number is ever cited
as evidence that the turn behaves correctly**, with docx §14's audit finding quoted verbatim
beside it.

**Stubs are local hand-written fakes in `runtime/tests/`** — no shared testing package (it
becomes the dependency by which the offline guarantee eventually breaks) and no `mock`
patching (a patched test passes while the real injection point moves). **The fakes and tests
may be LLM-authored** (user, 2026-08-27), on a **local developer approval prompt**: generation
happens at authoring time and the output is committed static code, so nothing calls a model at
run time. Each generated file carries a one-line header naming the generating model and date —
a reviewer's aid, not a machine-checked field. 14's **different-generator-family** rule does
**not** apply: it exists to stop a safety corpus mirroring the safety model's priors, and test
code has no such prior. The GitHub Environment stays reserved for **spend**; conflating "may I
generate this file" with "may I spend money" is how a cost prompt becomes reflexive.

### Performance

**No absolute latency budget** — 14 set no Intake ceiling, there is no measured per-turn total
to regress against, and inventing one would violate CLAUDE.md's re-measure rule. Two concrete
guards instead:

1. **A hard per-utterance wall-clock cap on the grammar.** Exceeded => `PASSTHROUGH`, the same
   outcome as a refusal, so a pathological input degrades instead of hanging. `lark` Earley is
   the only unbounded-cost component in Intake. The cap's value is **provisional** until the
   captured-STT corpus exists, like every other ticket 11 threshold.
2. **A microbenchmark in the free lane** publishing Intake p50/p95 over the frozen corpus,
   failing on **p95 > 3x the recorded baseline** and **asserting only in CI** (on a developer
   machine the numbers print, the assertion is skipped). Baseline in a committed
   `utterance_intake/tests/fixtures/intake_perf_baseline.json`, updated only by a deliberate
   commit; every run also writes a dated record. The risk being guarded is Earley blowup —
   orders of magnitude, not percentages — and a 20% threshold would be a flake generator that
   teaches people to re-run until green.

The turn-level risk is already covered by 14's invariant 6 and its 5s bound, which is an
assertion, not a benchmark.

### The measurement rule

**Commands run from `cloud_run_service/`, and this effort's evals live in
`cloud_run_service/eval/`** — where the modules they import actually live. One working
directory for both lanes, so the free lane and the billed lane never disagree about what
imports. Root `eval/` is left alone as the Part 11 legacy record; **its `--gates` / `--score` /
`--run` paths are broken and this effort does not repair them** (handed to backlog). The spec's
command block carries only commands that have been executed once and observed to run.

**`spec.md` carries no measured number it did not itself produce.** Every floor is cited by
reference — taxonomy §10.2, personal-data §12 — never restated as a figure. What the spec does
carry is a **numbers register**: one row per number the gate depends on, as
`value | source doc+section | measured-on date | status`, where status is `MEASURED`,
`PROVISIONAL — calibrate against <corpus>`, or `UNMEASURED`. Every ticket 11 threshold, the
grammar's 5%–15% band and the grammar wall-clock cap enter as `PROVISIONAL`; the Stage 1 perf
baseline enters as `UNMEASURED` until its first run. **A register row with no source is a spec
bug.**

**The grammar band and the degraded-net floor do not block Stage 1.** Both are calibration
targets under 14's own words, so Stage 1 gates on *measured and recorded*; out-of-band triggers
re-calibration, not a red build. What the net **is** gated on is **freeze** — its trip-set over
the corpora must be byte-stable, since 07 demoted it to a frozen artifact.

### The retraction

The shipped `SAFETY recall 1.0` is false — measured on a 20-phrase corpus that mirrors the
lexicon — and is **deleted, not annotated** (user, 2026-08-27). Seven sites:

| Site | Action |
|---|---|
| `CLAUDE.md:37` | delete the figure; add *"safety recall is measured per-class against blind corpora; see `SAFETY_ROUTE_TAXONOMY.md` §10"* |
| `docs/runbooks/CLOUD_VOICE_STATUS_AND_GOTCHAS.md:285` | same |
| `eval/perception_eval_report.md:13, 60, 79` | delete the rows outright |
| `cloud_run_service/eval/perception_stress_report.md:39-40` | delete the rows outright |
| `eval/perception_eval.py:562` + `:518` | **delete the `safety_recall` criterion and the reported field**, now, not at Stage 2 — it guards nothing, because the code path cannot run. `no_false_gate` and the NONSENSE row stay |
| `.scratch/.../map.md` ticket-07 refinement block | **keep** — it quotes the number *as a finding*; deleting it would erase the evidence that the number was wrong |

Prose sites get a pointer (they are read as current truth, and a silent gap invites
re-filling); table rows and code lose the figure outright (a measurement table with a pointer
where a number was is just a slower way to write the number). The **retraction manifest in
`spec.md`** lists all seven with what was removed and why, and is the only place the string
survives.

### Where the gate lives, and where its results live

**The gate's definition is a section of `spec.md`; the CI workflow is its executable form.** No
fourth document — a `VERIFICATION.md` beside the spec would be a second authority that drifts,
which is exactly what ticket 18 diagnosed in the lockstep set. 14's manifest gains one field,
`record_path`, and stays the corpus instrument it already is. Binding rule: **every check named
in the spec's pass set corresponds to a job step in the workflow; a check with no step is a
spec bug.**

**Results are dated measurement records** —
`cloud_run_service/eval/records/<gate>-<YYYY-MM-DD>.md`, never edited after writing, following
ticket 18's model: a number lives in exactly one place, and re-measuring means writing a new
record. This **conflicts with taxonomy §10.3**, which requires passing numbers, model id,
prompt version and date to be *"written into §11 of this document"* — resolved in 18's favour,
and raised as an amendment to 07's doc rather than quietly contradicted: §11 and 14's manifest
carry a **pointer to the current record**; what stays in the taxonomy is the part that is a
contract rather than a measurement (the pinned model id and prompt version). **Case records
keep their embedded numbers unchanged** — a case record is a snapshot by design, which is 07's
whole reason for putting them there.

### CI topology, approval, and rollback

**Three jobs: `offline`, `billed-safety`, `billed-personal-data`.** Separate rather than one
parameterized job, so an approval approves exactly one cost against one corpus set and the
Actions history says which — which is where the team review gets its evidence. Both billed jobs
fail loudly on the absent `WIF_PROVIDER` secret rather than skipping.

**Approval is a GitHub Environment with required reviewers, reviewed by the team, managed
org-side** (user, 2026-08-27). Approving the Stage 2 billed job **is the attestation** that
07's tier-3 exception list is closed and the corpora are reviewed — which turns 07 clause 3
from an honour-system rule into a click with a name attached. Completing that list is a
**free, offline Stage 1 deliverable** (it needs no model and no credentials), so Stage 2 never
waits on it. The **named safeguarding owner** question is org-owned and is named as such in the
spec, not answered here.

**There is no rollback design and no kill switch, by decision** (user, 2026-08-27): if a safety
number breaks, the developer fixes it, and nothing is released before it reaches its floor. Red
never reaches production, so a post-merge rollback story would be designing for a state this
process does not produce. The absence of a fast pause path stays on the not-covered list below,
where docx §15's Monitoring gate can see it. One standing rule: **a red standing-set check on
`main` stops the effort** — the standing set is regression-only, so red there means something
that used to work no longer does, which is never a tuning question.

### Release gating: what this gate does and does not mean

| Docx §15 gate | This gate | Why |
|---|---|---|
| Content truth | **no** | subject-matter review and deterministic maths checks are the response/grounding layer's |
| Safety operations | **no, emphatically** | named owner, staffed rota, playbook, after-hours plan, drill evidence — none of it is here |
| Privacy | **partial, one line** | 09's redaction tests are one bullet of a gate that also needs a data map, consent review, retention design, vendor review and per-jurisdiction legal sign-off |
| Model and UX | **partial** | the STT/multilingual failure-testing bullet, via set 3 and the captured-STT fixtures. Red team, accessibility, usability study, appeal paths: not ours |
| Monitoring | **partial** | taxonomy §10.3's re-measurement triggers and §10.4's divergence metric satisfy "periodic re-validation after model/prompt changes". Dashboards, the pause path, the versioned template registry: not built here |

The statement, **verbatim, at the top of the spec's verification section** (a caveat under a
table of passing checks is read as a footnote; this one is the point):

> A green run of this gate means the code does what these specifications say, measured on
> corpora we wrote ourselves. It is not evidence that any child was protected. This gate does
> not cover: subject-matter review of tutoring content or deterministic checks on numerical
> answers; a named safeguarding owner, staffed escalation rota, incident playbook, after-hours
> plan or drill evidence; a data map, age/consent review, retention and deletion design, access
> control, vendor review, or per-jurisdiction legal sign-off; an independent red team,
> accessibility review, or usability study with children or educators; production dashboards
> for false negatives and positives, a fast pause path for a harmful response path, or a
> versioned template and resource registry. Until the Safety-operations gate has a named,
> staffed owner, the product must not claim that it monitors safety or alerts adults.

The last sentence is docx §15's stop-ship condition, which 14 also carries.

### Rejected, recorded so it is not re-argued

- **Reusing `baseline_oracle` as an end-to-end equivalence gate, with or without a partition.**
  Its reference has never run green, repairing it needs an artifact-complete checkout and a
  real capture, and this effort changes `normalized_text`, inserts a `TurnPhase` and adds two
  model calls — so most observation surfaces differ by design anyway.
- **Repairing the oracle's frozen reference as part of this effort.** Named as out of scope so
  its presence in the tree is not read as coverage.
- **An asymmetric expected-diff manifest** (unlisted diff fails, stale row shrugs). The stale
  row is the one that hides drift from what was authorized.
- **One all-or-nothing gate across the three units.** Makes a green Intake wait on a cutover it
  does not depend on, and manufactures waiver pressure.
- **Blocking the Stage 2 cutover until all seven classes clear 0.80.** Keeps a measurably worse
  lexicon in production while we wait; a class at 0.75 beats a class at 0.0.
- **A flag-gated dual run of the safety detector.** 07 clause 5 — it would recreate two safety
  lexicons drifting apart.
- **Deferring the `>= 1.0` criterion's deletion to Stage 2.** It guards nothing; the code path
  cannot execute.
- **Superseded banners on the dated eval reports** (user, 2026-08-27). The number is false and
  is deleted; the retraction manifest is the record.
- **A standalone `VERIFICATION.md`.** A second authority beside `spec.md` that drifts.
- **A shared testing/fakes package, and `unittest.mock` patching**, for the turn-level stubs.
- **A percentage-based perf threshold, and asserting perf on developer machines.** Flake
  generator; the risk being guarded is orders of magnitude.
- **An absolute Intake latency budget.** No measured per-turn total exists to derive one from.

### Consequences handed to other tickets

- **16** — lands **every** edit in this resolution: the gate section, the three stage pass
  sets, the numbers register, the retraction manifest (all seven sites), the not-covered
  statement verbatim at the top, the WIF prerequisite on the Stage 2/3 entry lines, and the
  `CLAUDE.md` **Quick-commands block** correction (scoped to that block only).
- **14** — manifest gains `record_path` per corpus.
- **07** — two amendments to `SAFETY_ROUTE_TAXONOMY.md`: §10.3's "written into §11" becomes a
  **pointer to the current measurement record** (numbers live in records, not in the doc; the
  pinned model id and prompt version stay); §11's exception list is **completed during Stage 1**
  and **closed at the Stage 2 approval**.
- **18** — untouched by this ticket. 15 edits only `CLAUDE.md`'s Quick-commands block; 18 owns
  the lockstep→source-of-truth block. They do not overlap textually; the spec says which ticket
  owns which block so neither "tidies" the other's territory.
- **The WIF ticket (owner TBD)** — gains two named dependents: Stages 2 and 3 cannot run their
  gates without it.
- **Backlog** — root `eval/`'s broken `--gates` / `--score` / `--run` import path; repairing
  `baseline_oracle`'s frozen reference.

### Explicitly not decided here

The safety prompt / schema / context cache (07, `child_safety/`); the personal-data prompt and
its floors (09); the calibrated values of the grammar's refusal band, the grammar wall-clock cap
and every ticket 11 threshold, which stay `PROVISIONAL` until the captured-STT corpus exists;
the WIF setup itself; the named safeguarding owner (org-owned); and the contents of the
corpora, which are 14's.
