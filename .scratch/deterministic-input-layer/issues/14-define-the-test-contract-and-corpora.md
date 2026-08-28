# Define the test contract and the golden corpora

Status: resolved
Type: grilling
Blocked by: 03, 05

## Question

What does "tested separately" mean for this module, concretely enough to be a gate?

This is the user's original ask and the reason the map exists. Today
`cognitive_input_processor/` has **no test file at all**; every other extracted module has a
`tests/` directory (`perception/tests/`, `interaction_control/tests/`, `pedagogy/tests/`, …).

Decisions to close:

- **Import purity.** Can the Input Layer's tests run with no MiniLM, no Vertex credentials,
  no `rag_store` load, and no `torch`? Today `input_processor.py` is pure stdlib and
  `gates.py` is pure stdlib + an optional `debug_logger`, but `cues.py` imports `numpy` and
  lives in a package whose siblings pull the classifier. Ticket 04's split decides whether
  purity is achievable; this ticket decides whether it is **required**. State it as an
  enforceable rule — the precedent map already ships AST-based modular-boundary validation
  (ticket 25 of `modular-tutor-runtime`).
- **Test entry point.** `python -m unittest discover -s <module>/tests -v` matches
  `interaction_control/README.md`. Confirm and document.
- **The golden corpora.** Docx §15 names six required evaluation sets; which are input-layer
  property, and what is each one's pass bar?
  - purpose/why cases (skeptical, curious, advanced, overwhelmed)
  - definition and representation cases, including "another way" requests
  - **ambiguity/STT cases** — broken grammar, code-switching, accents, homophones, spoken
    maths symbols, negative signs, exponents, false starts, interruptions
  - social/off-topic — insults, revenge requests, threats, jokes, ordinary frustration
  - **privacy cases** — names, phone numbers, address, school, passwords, images, voice
  - **safeguarding cases** — indirect and direct disclosures, acute danger, self-harm
    language, abuse by a caregiver, bullying, grief, **and false positives**
- **The negation acid test.** "I do like math" vs "I do not like math" must be in the corpus
  with an explicit expected verdict, even if the honest answer for a deterministic layer is
  "this layer abstains and the semantic layer decides". Record the abstention as the passing
  behavior rather than leaving it untested.
- **Regression fixtures already in the repo.** `learning_log` carries real incidents —
  `"i can not understand"` graded wrong → mastery dropped; the quadratic probe swallowed by a
  pending check. Do those become permanent test cases here?
- **What is *not* unit-testable** at this layer and must be an integration test instead
  (the `_low_confidence_result` re-prompt path, per ticket 11).
- **Ownership of the corpora.** Docx §13 control 3 requires a human-reviewed regression suite
  where "a safeguarding lead and subject expert approve templates and test results". Who signs
  off, and does the suite block release?

---

## Requirements handed down by ticket 07 (2026-08-26)

07 owns the safety corpora **rules**; 14 owns their construction. These are binding.

1. **The blind-corpus rule.** The safety corpora are written against the class definitions in
   `docs/architecture/SAFETY_ROUTE_TAXONOMY.md` §3 by an author who has **not read the
   lexicon or the prompt**. A corpus written by reading the patterns measures the patterns:
   that is exactly how the shipped 20-phrase probe came to report 1.0 recall while missing
   peer-at-risk, grooming and threats entirely (`eval/perception_eval.py:120-141` and
   `eval/perception_eval_safety.jsonl` are the same 20 phrases). Corollary: **the lexicon is
   never edited by reading a missed-corpus row.**

2. **Per class, never an aggregate.** One corpus per `SafetyClass` (6 classes +
   `UNSPECIFIED_CONCERN`). **No aggregate safety number may be printed anywhere** — a report
   with one number is a bug. An utterance that trips the axis but no class is a **pass**
   counted under `UNSPECIFIED_CONCERN`, not a miss.

3. **A false-positive corpus**, built from the §3 "Out" examples plus ordinary-distress
   phrasings (`i'm sad`, `i'm bad at maths`, `nobody likes me`) that must **not** trip the
   axis at all. It measures class/severity precision only — never the axis, which has no
   precision gate.

4. **Conversation-level fixtures.** Docx §15 requires reviewing "the entire multi-turn
   conversation, not only the first reply", and the safety call now sees
   `session["context"][-2:]`. Plain strings cannot express that; fixtures must carry a
   preceding exchange. This joins the audio-derived corpora ticket 03 already added
   (fluent high-confidence hallucination, fluent low-confidence, divergent alternates), so
   the harness question can no longer be deferred.

5. **The legacy 20 become a permanent regression suite** — they must never break, and they
   are **never** the recall measurement.

6. **A degraded-mode corpus** for the frozen outage-net lexicon (axis floor >= 0.90), run in
   CI so the net cannot rot unnoticed. Published under its own label; never compared to the
   model's number as a gate.

Floors live in the taxonomy doc §10.2 and are ticket 15's gate, not 14's.

---

## Resolution (2026-08-27, /grilling)

**"Tested separately" resolves into two lanes, one manifest, and a construction order.** The
lanes are `unittest` assertions (free, automatic, credential-less) and `eval/` measurements
(billed, approval-prompted, published per class). The manifest is the file that says which
corpus exists, who authors it, what it measures and what gates on it. The construction order is
**test-first**: no model-backed detector is built before its corpus exists.

Five organizing rules produced every decision below:

1. **Assertions and measurements are different things and never share a harness.** A corpus
   yields per-class numbers with floors; a contract yields pass/fail. Fusing them is how one
   aggregate number came to hide two classes at zero.
2. **Purity is a property of the tests, not a ban on the module.** What is worth defending is
   "the suite runs offline, credential-free, in seconds" — that is a seam, not an import list.
3. **Test-first is what makes blindness structural.** A corpus written before the prompt exists
   cannot mirror it.
4. **Every corpus is authored or synthetic. No row is ever copied from production.**
5. **This layer is graded only on the judgments it still makes.** Ticket 01 moved most of the
   docx §15 sets to Perception; grading Intake on them measures nothing.

### Premise corrections (verified against the repo, 2026-08-27)

Four of this ticket's premises are stale or wrong.

1. **"No test file at all" is false.** `cognitive_input_processor/tests/test_input_processor.py`
   exists — 108 lines, 9 tests — and is written in **pytest**, while all nine other modules'
   READMEs document `python -m unittest discover`. It is the uncommitted spike ticket 01 said
   would migrate.
2. **There is no CI of any kind.** No `.github/`, no workflow, no pre-commit hook, no
   pytest/tox/setup.cfg. Ticket 07's requirement 6 ("run in CI so the net cannot rot
   unnoticed") had nowhere to run.
3. **Ticket 04's import guard and ticket 11's grammar contradict each other.** 04: *"`utterance_intake`
   imports stdlib only", two assertions, no allowlist.* 11: the maths grammar is `lark` Earley
   at `utterance_intake/grammar/`, justified as *"Pure Python, so ticket 14's import purity
   survives"* — conflating pure-Python with stdlib. `lark` is neither in `requirements.txt` nor
   installed.
4. **The repo is public** (`rijish739/wini_tabletop`, `isPrivate: false`). This decides where the
   safety corpora live, and it makes GitHub Environments with required reviewers free.

### The two lanes

| Lane | Runner | Cost | When it runs | What it proves |
|---|---|---|---|---|
| **Assertions** | `python -m unittest discover -s utterance_intake/tests -v` from `cloud_run_service/` | free | every push, automatic | contracts, invariants, corpus integrity |
| **Measurements** | `python -m eval.safety_eval` etc., the existing `python -m eval.x` convention | billed | on developer approval | per-class recall/precision against floors |

`unittest`, not pytest — the nine module READMEs are the convention and the spike's 9 tests are
**rewritten**, not ported. `eval/safety_eval.py` is its own harness, never inside
`perception_eval.py` (taxonomy §10.3).

**A corpus-integrity test lives in the free lane.** It runs with no credentials and asserts that
every corpus file parses, has no duplicate rows, meets its size floor, carries the required
schema fields, and **has no empty grid cell** (see Construction rules). Corpus rot fails fast and
free, separately from measuring recall.

### Import purity: replaced by a seam rule and a topology

**There is no stdlib-only rule.** Ticket 04's guard does not survive in that form (user decision,
2026-08-27): external libraries and external models are permitted in Utterance Intake when they
buy accuracy at acceptable latency. `lark` is added to `requirements.txt` by this effort.

What replaces it:

- **Seam rule.** Any external model or network call in Intake sits behind an **injected
  dependency**, so the unit suite stays offline and credential-free without banning models from
  production. Enforced by a runtime assertion that the whole suite passes with
  `GOOGLE_APPLICATION_CREDENTIALS` unset and no network.
- **Intake ships with no model call and no network today.** This is forced by the turn topology,
  not by taste: safety and perception both consume `normalized_text`, so anything Intake waits on
  is pure added wall-clock ahead of two calls that cannot start without it.
- **No Intake latency ceiling is set.** The topology is the latency answer: the safety call is
  dispatched **first**, the perception call immediately after, both in flight together; perception's
  output is **held until the safety verdict has been analyzed**, then released. Accuracy wins;
  cost is not designed around.

Consequence, written into 03 and 11 rather than left contradicting the spec: their purity claims
are restated as *"no model call in the shipped implementation; offline-runnable tests are a
permanent property"* rather than *"deterministic by definition"*. This does **not** restore
`PrivacyReading` — 09's other reasons (the call must run after `normalized_text` exists; §8's
late-verdict design) are independent and survive intact.

### CI: automatic offline, approval-prompted billed

One GitHub Actions workflow, two jobs.

- **Offline job** — automatic on every push: `unittest discover` across every
  `cloud_run_service/*/tests`, plus corpus integrity, the legacy-20 regression, and the
  degraded-net corpus check.
- **Billed job** — a **GitHub Environment with required reviewers**. It requests approval and
  sits visibly pending in the Actions UI until a named reviewer approves. **The developer is
  prompted with the cost of the run; that is the whole mechanism.** No path-based auto-skip
  logic — a developer will otherwise forget the tests, which is the failure this exists to
  prevent.
- **Credentials.** A public repo means fork PRs never receive secrets, and a raw GCP
  service-account key is the wrong artifact. **Workload Identity Federation** (GitHub OIDC → GCP,
  keyless) is the correct mechanism and is **deferred to its own ticket**. This effort ships the
  billed job wired to a `WIF_PROVIDER` secret that does not yet exist, so it fails loudly as
  unconfigured rather than pretending it ran.

### Corpus ownership: construction is split from gating

14 owns the **manifest**, the **schema**, and the **harness**. Construction splits by subject.

| Corpus | Constructed by | Gates |
|---|---|---|
| Intake readings (set 3 below), legibility, authorization, homophones | **14** | this effort |
| Legacy 20 (`eval/perception_eval_safety.jsonl`) — permanent regression suite | **14** (adopt as-is) | this effort; never the recall measurement |
| Degraded-net (outage lexicon, axis floor ≥ 0.90) | **14** | this effort, in the free CI lane |
| Safety per-class (6 + `UNSPECIFIED_CONCERN`) + FP corpus | **authored by 14 now** | `child_safety/` at cutover, **not** this effort |
| PII per-class (9) + maths-dense precision (≥500 rows) | **09 / `personal_data`** | that package; 14 reserves path + schema and supplies the maths-dense rows from the golden set |
| Captured-STT fixtures | **14**, one-time capture, frozen and replayed forever | this effort (replay only; never a live STT call) |

The safety corpora are authored **now**, before any prompt exists, because that is when blindness
is at its maximum. Their floors gate the package that lands later.

**Standing rule for the manifest: no model-backed detector is built before its corpus exists.**

Manifest fields, per corpus: `name`, `authoring_rule`, `size_floor`, `schema`, `gate`, `owner`,
`path`, `reviewed_by`, `reviewed_at`, `review_scope`.

### Construction rules

- **Test-driven.** Test cases and corpora are written first; code is developed against them. This
  is the method, and it is what makes ticket 07's blind-corpus rule structural rather than
  procedural.
- **Corpora are LLM-generated**, from a **structured grid** — a written grid of
  (class × directness × register × code-switching × euphemism). The grid is 14's reviewable
  deliverable; 300 generated rows are not. The integrity test fails on any empty grid cell,
  which is what turns the grid from a document into a gate.
- **≥ 40% indirect/euphemistic rows per safety class.** The measured holes (`PEER_AT_RISK`,
  `UNSAFE_CONTACT`) are all indirect, and docx §14's audit finding is precisely that controlled-
  dataset recall is not protection.
- **Different generator family for the safety and PII corpora only.** TDD ordering defeats
  *prompt* mirroring; it does not defeat *model* mirroring. A Gemini-generated safety corpus
  contains the phrasings Gemini already recognises, and would report good recall before any
  prompt exists. Every row carries `source: generated:<model-id>`, and the integrity test asserts
  **no safety or PII corpus row was generated by the model named in `VERTEX_SAFETY_MODEL`**.
  Everything else may be generated by any model — those detectors are deterministic code, so
  there is no shared prior to correlate with.
- **The LLM generates; it does not judge.** Scoring is exact comparison against the row's label,
  because the label *is* the ground truth for per-class recall. A judge would add a second model
  whose errors are indistinguishable from the detector's, making every number unattributable.
  Where an LLM judge is legitimate — open-ended response templates, clarification wording, the
  repair prompt — is response-side and handed on as a note.
- **Authored or synthetic only. No row is ever copied from `learning_log` or any production
  record.**

### The billed TDD loop

TDD on a model-backed detector has a red state that is *a number below floor*, and every red→green
iteration is a paid run. Cost is paid, not designed around — but the loop still has to be
measurable. The repo already solved this: `perception_eval` splits **`--collect`** (billed,
resumable, one call per uncached row, appends to `perception_eval_raw.jsonl`) from **`--score`**
(offline, re-derives every metric from the cache); `behavioral_eval` does the same with
`--probes` / `--replay`.

`eval/safety_eval.py` **mirrors that split exactly**, with the rule the perception eval learned
the hard way and records in its own source (`behavioral_eval.py:63`): **a prompt change
invalidates the cache** — *"prompt changed, so v1 predictions are not comparable and the caches
must not be mixed"*. So each prompt iteration is exactly **one** full billed collect, the cache is
keyed by prompt hash, and mixing caches across prompt versions is a **test failure**, not a
footnote.

### Storage: in-repo, public, synthetic

Corpora live in-repo alongside the existing frozen fixtures (`eval/*.jsonl`,
`baseline_oracle/fixtures/`), publicly. Publishing them is acceptable because the corpus measures
a **model**, not a filter — unlike a regex lexicon, publishing it does not tell anyone how to
evade it — and the blind-authoring rule already forbids editing the lexicon from corpus rows,
which is the leak that actually matters. Out-of-repo storage was rejected: it puts a credential
in the free offline lane and kills the "always safe to run" property the integrity test depends on.

> Flagged, not this ticket's: `cloud_run_service/rag_store/learning_log.jsonl` — 306 entries of
> raw child turns — is already committed to that public repo. Ticket 09 §9 territory.

### Fixture format

**One JSONL schema, superset-shaped, one file per corpus.** JSONL matches the existing eval
convention and stays diff-readable in a public repo; a single schema means the integrity test is
one validator instead of three.

| Field | Required | Notes |
|---|---|---|
| `id` | yes | stable |
| `text` | yes | |
| `label` | yes | the ground truth for exact-match scoring |
| `source` | yes | `authored` / `generated:<model-id>` / `captured` |
| `grid_cell` | yes | the coverage assertion's key |
| `context` | no | ordered list of prior turns — 07 requirement 4; the safety call sees `session["context"][-2:]`, which a bare string cannot express |
| `stt` | no | the captured Google response (`alternatives`, `confidence`, `WordInfo`) |

Borrowed from `baseline_oracle/corpus.py`: the **required-coverage assertion** pattern.
Captured-STT rows stay in their **own file** — they carry a provenance and consent story the
others do not.

### The docx §15 six sets, mapped to owners

| # | Docx §15 set | Owner after 01 / 07 / 09 | Why |
|---|---|---|---|
| 1 | purpose/why (skeptical, curious, advanced, overwhelmed) | **Perception** | `is_purpose_question` deleted from the runtime; `purpose_question` is one of 01's four new labels |
| 2 | definition/representation, "another way" | **Perception** | `is_visualization_request` deleted → `request_representation` / `representation_shift` |
| 3 | **ambiguity/STT** — broken grammar, code-switching, accents, homophones, spoken symbols, negative signs, exponents, false starts, interruptions | **Utterance Intake** | `TranscriptReading` + `LegibilityReading` + the lark grammar + ticket 10's 42-row homophone table |
| 4 | social/off-topic — insults, revenge, threats, jokes, frustration | **split** | threats → `child_safety`; insults/jokes/frustration → the FP corpus that must *not* trip the axis; the route decision is `gate()`'s |
| 5 | privacy | **09 / `personal_data`** | `PrivacyReading` deleted; Intake cannot produce it |
| 6 | safeguarding, incl. false positives | **07 / `child_safety`** | Intake's only share is the degraded-net lexicon reading |

**Set 3 is the only one whose pass bar this ticket owns.** Sets 1/2 get manifest entries pointing
at `behavioral_eval` and are explicitly *not* this effort's gate; sets 4/5/6 get manifest entries
owned by their packages. The point of writing it this way is that the ticket stops implying
Intake is graded on judgments it no longer makes.

### Set 3's pass bars — exact-match, per case, never aggregated

- **Six `LegibilityCue` values** (`LEGIBLE`, `EMPTY`, `NO_ALPHANUMERIC`, `CHARACTER_RUN`,
  `NO_LEXICAL_CONTENT`, `KEYBOARD_MASH`) and **three `Authorization` states**: full coverage, no
  empty grid cell, exact-match against the authored label.
- **The 42-row homophone table** (ticket 10): one expected outcome per row.
- **The grammar: two-sided acceptance** (ticket 11), both halves measured.
  - The **four measured confident false negatives** must each become a correct parse **or** a
    refusal — never a silent wrong.
  - **Refusal rate is measured over claimed maths spans, never over utterances**, and the bar is a
    **band: 5%–15%**.

The denominator is the part that silently breaks: measured over utterances, the rate is dominated
by how many non-maths turns happen to be in the corpus, so any target could be hit by adding topic
questions. `PASSTHROUGH` is the common, legitimate outcome and a span is claimed only on positive
evidence (11). A **band** rather than a ceiling because both ends fail: above ~15% the grammar is
refusing real answers and the repair screen becomes noise a child learns to dismiss; below ~5% it
is claiming certainty on genuinely ambiguous spoken maths — Spoken-MQA found 32 of 100 MATH
problems ambiguous to humans without visual context, so a near-zero refusal rate is a **failing**
result. Both numbers are **calibration targets with a re-measure obligation**, not frozen gates:
11 already holds every threshold provisional until the captured-STT corpus exists.

### The invariant assertions

Six, inherited from 02, 07, 11 and the turn topology.

| # | Invariant | Source | Form |
|---|---|---|---|
| 1 | The safety path reads **neither** `authorization` **nor** `TranscriptReading` | 11 → 07 | AST / source guard |
| 2 | **Exactly one** branch on `Utterance.source` exists in the whole runtime — the trust policy. No pedagogy, grading or safety path reads it | 02 | AST / source guard |
| 3 | **No consumer reads `utterance.alternates`** — only `repair_choices` | 11 | AST / source guard |
| 4 | For `source is VOICE`, `authorization is UNAUTHORIZED` **iff** `transcript.doubtful` | 11 | behavioural |
| 5 | A raw personal-data value appears in **no** `__str__` / `__repr__` of the redaction type | 09 §4 | AST / source guard |
| 6 | Perception's output is never released before the safety verdict is analyzed | topology, this ticket | behavioural |

1–3 and 5 are statements about the codebase, not about one turn, so they are source-level guards.
Ticket 04's surviving assertion — no module outside `cognitive_classifier/` and `policy_shadow/`
imports `cognitive_classifier.cues` — joins this set.

**Invariant 6 is bounded**: perception's output waits at most the remainder of the taxonomy's 5s
safety envelope (§7.3), then releases in **degraded mode** with the `safety_model_unavailable`
stamp. Unbounded was rejected — a hung safety call would freeze every turn.

### The integration tier

Four things resist a unit test at this layer and move to a named integration tier in
**`runtime/tests/`**, not a third location:

- the **`_low_confidence_result` re-prompt path** (this ticket's own bullet, via 11);
- the **repair round-trip** — `REPAIR_SELECTION` / `REPAIR_DISCARD` are a *second* `Utterance`
  referencing the first through `provenance.repairs`, which one observation cannot express. The
  test asserts the `provenance.repairs` link explicitly, because that link is the entire audit
  trail for substituting a machine hypothesis for what the child said;
- the **`TurnPhase.UTTERANCE_INTAKE`** insertion before `PERCEPTION_AND_PRIOR_GRADING`;
- **invariant 6**, which is a coordinator property, not an Intake one.

`runtime/tests/` because the coordinator tests already live there, they run offline, and putting
turn-sequencing assertions in `utterance_intake/tests/` would make a module test depend on the
coordinator — the inversion 03's rule 1 forbids. Still `unittest`, still free, still in the
automatic lane. **The money is only ever in `eval/`.**

### Sign-off, and what a green run does not mean

Docx §13 control 3 requires a safeguarding lead and subject expert to approve templates and test
results, with release blocked if a high-risk case regresses. There is no named safeguarding lead
today, and LLM-authored corpora make review more load-bearing, not less.

- **Sign the grid and a sample, not 300 rows.** The manifest carries `reviewed_by`, `reviewed_at`,
  `review_scope` per corpus.
- **An unreviewed corpus may be run**, and its numbers published **under an "unreviewed" label** —
  but **no `child_safety/` cutover happens on unreviewed numbers**.
- **The docx stop-ship condition goes into the spec verbatim:** if the team cannot provide a
  truthful, staffed hand-off for high-risk disclosures, **remove any claim that the tutor monitors
  safety or alerts adults**.
- Ticket 15 inherits an explicit statement of what a green run does **not** mean, so nobody reads
  this layer's test suite as child-safety assurance.

### Out of scope — the grader layer's, and no code or test is written here

Two of this ticket's original bullets resolve as **handed on**, by user decision (2026-08-27):

- **The negation acid test** (`"I do like math"` vs `"I do not like math"`). Not this layer's
  task; the grader layer owns it. No fixture, no assertion, no code change.
- **The `learning_log` regression fixtures** (`"i can not understand"` graded wrong → mastery
  dropped, 6 occurrences in `rag_store/learning_log.jsonl`; the quadratic probe swallowed by a
  pending check). Same disposition. Both were grading and coordinator failures, not Intake
  readings.

They are recorded here as handed on rather than silently dropped, so nobody re-opens them as an
oversight.

### Rejected, recorded so it is not re-argued

- **Stdlib-only import purity** (ticket 04's guard as written). Fails on day one against 11's
  `lark` grammar, and bans the wrong thing: an import guard that only reads names cannot catch a
  MiniLM load anyway. Replaced by the seam rule + the offline-suite assertion.
- **A weakened AST guard with a heavy-loader denylist** (`torch`, `sentence_transformers`,
  `faiss`). Same defect in smaller form; the seam is the real control.
- **pytest with `@pytest.mark.billed`.** Matches one file, breaks nine module READMEs.
- **One lane with billed tests skipped behind an env var.** Collapses assertions and measurements
  into a harness that must report both pass/fail and per-class floors.
- **Path-triggered auto-skip of the billed CI job.** Every typo fix blocking on a paid run makes
  people click approve reflexively — the same failure as forgetting. A plain cost prompt instead.
- **Out-of-repo corpus storage (GCS, hash-pinned).** Puts a credential in the free lane.
- **An LLM judge in this layer's eval loop.** The row's label already is the ground truth.
- **An aggregate safety number, anywhere.** 07 requirement 2; a report with one number is a bug.
- **A refusal-rate ceiling measured over utterances.** Any target is hittable by padding the
  corpus with non-maths turns.
- **Live STT or LLM calls in the free lane.** 11: *"no live STT or LLM call in the verification
  gate, regardless of budget."* The billed lane exists precisely so this stays true.

### Consequences handed to other tickets

- **03** — its purity claim (rule 3, "a deterministic function of one `Utterance`") is **restated**,
  not deleted: no model call in the shipped implementation; offline-runnable tests are a permanent
  property. `PrivacyReading` stays deleted.
- **04** — its import guard is **superseded**. The second assertion (no module outside
  `cognitive_classifier/` and `policy_shadow/` imports `cognitive_classifier.cues`) **survives**
  and moves into the source-guard set; the stdlib-only assertion does not.
- **07** — all six binding requirements are implemented above. Requirement 6's "in CI" now has a
  CI to run in. Its §10.1 corpora are authored by 14 but gate `child_safety/`.
- **09** — 14 reserves the path and schema for its two corpora and supplies the maths-dense
  precision rows from the golden set; 09 keeps its own floors (≥0.80 per class recall, ≤1% FP).
- **11** — its captured-STT corpus is a distinct fixture family with its own file; the grammar's
  two-sided criterion gets its band and, more importantly, its **denominator**.
- **15** — inherits: the two-lane structure and which lane is a gate; the manifest as its
  instrument; the "what green does not mean" statement; the unreviewed-corpus rule; and invariant
  6's degraded-mode bound as a measurable turn property.
- **16** — the spec must carry: the seam rule replacing import purity; `lark` in
  `requirements.txt`; the two-lane commands; the turn topology (safety first, perception second,
  perception's handoff gated, 5s bound, degraded stamp); the grid; the different-generator rule;
  and the docx stop-ship condition verbatim.
- **New ticket (owner TBD)** — **Workload Identity Federation** for the billed CI job. This effort
  ships the job wired to a `WIF_PROVIDER` secret that does not exist yet, failing loudly.
- **Response-side (note, not a ticket)** — an LLM judge is legitimate for open-ended output:
  response templates, clarification wording, the repair prompt. Recorded so the capability is not
  lost with the rejection above.

### Explicitly not decided here

The safety prompt, schema and context cache (07 / `child_safety/`); the personal-data prompt and
its floors (09); the coreference bands and word-count threshold (12); the dead-code and
`SemanticClassifier` seam disposition (13); the full verification gate and its release mapping
(15); the WIF setup; and the calibrated values of the grammar's band and every 11 threshold, which
stay provisional until the captured-STT corpus exists.
