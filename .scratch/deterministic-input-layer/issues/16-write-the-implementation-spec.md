# Write the implementation spec

Status: resolved
Type: task
Blocked by: 01, 02, 03, 04, 05, 07, 09, 11, 12, 13, 14, 15

## Question

Nothing left to decide — synthesize every resolution into `spec.md` and mark it
`ready-for-agent`, matching `.scratch/modular-tutor-runtime/spec.md`.

The spec must carry, at minimum:

- The module's name, location, public interface, and allowed dependencies (01, 04, 14).
- The input value type and the output observation, as typed definitions (02, 03).
- A file-by-file migration manifest: what moves, what is deleted, what is re-exported, and
  every consumer that must be updated (01, 04, 05, 13).
- The safety route taxonomy with per-route recall floors and the deterministic/model
  composition rule stated as an invariant (07).
- The personal-data contract (09) — **reference** `docs/architecture/PERSONAL_DATA_CONTRACT.md`
  rather than restating it, as with 07. Two bullets that stood here were **wrong and are
  corrected**: there is no redaction sink *order* (there is a four-site conversion list and one
  criterion — persists / streams / can speak it back), and there is **no**
  do-not-learn-from-this-turn rule (the §3 boundary lands on *fields, not turns*). See the note
  from ticket 09 below.
- The STT uncertainty contract: consequence gates, N-best propagation, grammar refusal
  semantics (11).
- Where coreference confidence lives and what evidence this layer supplies (12).
- The test contract, the six corpora, and the entry-point command (14).
- The verification gate: what stays identical, what is allowed to change, the exact
  measurement commands, and an explicit statement of what the gate does **not** assure (15).

Also settle the documentation obligation before closing: CLAUDE.md's four-document lockstep
rule applies to whatever contracts this spec changes, and those four documents currently sit
in `docs/archive/` rather than `docs/architecture/` (see the map's "Not yet specified").
Name which documents this effort must update, and log the work in `rag_memory.md`.

This map is plan-only. The spec is the handoff; no production code changes in this effort.

---

## Note from ticket 07 (2026-08-26)

07's contract is large enough that `spec.md` should **reference** rather than restate it:
`docs/architecture/SAFETY_ROUTE_TAXONOMY.md` is normative and is the artifact a corpus author
and an implementing agent both read. The spec's safety section carries only the seam-level
facts and points at the doc for the rest.

What the spec must nonetheless state in its own voice, because it changes the module manifest:

- **A new package, `cloud_run_service/child_safety/`** — a sibling of `perception/`, not part
  of Utterance Intake. It holds the primary safety detector: a dedicated Gemini call, every
  turn, in parallel with perception, own prompt-of-record / schema / context cache / eval,
  `VERTEX_SAFETY_MODEL` + `VERTEX_SAFETY_LOCATION` seam defaulting to
  `gemini-2.5-flash@asia-south1` with the version pinned, 5s hard wall-clock plus one retry,
  and **late verdicts that still count**.
- **The lexicon is demoted, not deleted** — degraded-mode outage net only, axis-only,
  `{UNSPECIFIED_CONCERN}` / `ELEVATED`, never `CRITICAL`, frozen and CI-maintained.
- **Intake's slot is `safety: SafetySignals`** (lexicon-only, no severity), per 03's amendment.
- **Deletions**: `RouteResult.safety_tier` and `.safety_category`; the hard-coded `handled`
  literal at `control.py:860`; `interactive_tester.py:42-44`'s invented `tier 1` /
  `"HARMFUL_CONTENT"` vocabulary.
- **One shared composition helper** in `interaction_control`, called from both sites that
  branch on `safety_alert` (`control.py:229-231`, `:310-312`).
- The five backlog items 07 spawned (see `map.md`) are **out of** this spec's scope but must
  be named in it, since two of them (the case store, the honest `handled`) sit on docx §15's
  stop-ship gate.

## Note from ticket 09 (2026-08-27)

Same pattern: `docs/architecture/PERSONAL_DATA_CONTRACT.md` is normative and is referenced, not
restated. What the spec must state in its own voice, because it changes the module manifest:

- **A new package, `cloud_run_service/personal_data/`** — a sibling of `perception/` and
  `child_safety/`, not part of Utterance Intake. A dedicated Gemini call fired immediately
  **after** Intake (it redacts by exact match on `normalized_text`, so the ordering is forced),
  own prompt-of-record / schema / context cache / eval, `VERTEX_PERSONAL_DATA_MODEL` +
  `VERTEX_PERSONAL_DATA_LOCATION` defaulting to `gemini-2.5-flash@asia-south1` with the version
  pinned, 5s hard wall-clock plus one retry. **There is no deterministic component and no
  outage net** — unlike safety, a Vertex outage means zero detection, and §8's fail-closed sinks
  are what make that safe.
- **`UtteranceObservation` loses its `privacy` slot**: six required readings become five, per
  03's amendment.
- **Four sinks are converted** to take `RedactedText` and lose their `str` overload:
  `_log_shift` (`tutor_loop.py:1853`), `_log_nonlearning` (`tutor_loop.py:1881`),
  `debug_logger._fan_out`, and the generation prompt. `RedactedText` lives in the new package,
  **not** `runtime/contracts.py`, so only the redactor can construct one.
- **Deletions**: `_log_nonlearning`'s `safety_alert`-only redaction special case, which the
  general rule absorbs.
- Two backlog items spawned: the grading prompt's logged output must not quote
  `LEARNER RESPONSE` (`evidence/grading.py:58`), and the standing rule that no raw utterance
  text may ever enter learner state — currently true by accident, and what protects the parent
  dashboard sink.

---

## Resolution (2026-08-27, /to-spec)

`spec.md` is written and marked `ready-for-agent`:
`.scratch/deterministic-input-layer/spec.md`.

Every carrier this ticket required is present:

| Required | Where in `spec.md` |
|---|---|
| Module name, location, public interface, allowed dependencies (01, 04, 14) | Implementation Decisions -> "Modules, boundaries, and dependencies" |
| Input value type + output observation as typed definitions (02, 03) | "The input value type", "The output observation" |
| File-by-file migration manifest (01, 04, 05, 13) | "The migration manifest" + "The inline turn-body derivations" |
| Safety taxonomy, referenced not restated; seam-level facts + the composition invariant (07) | "Safety - seam-level facts" |
| Personal-data contract, referenced not restated (09) | "Personal data - seam-level facts" |
| STT uncertainty: consequence gates, N-best propagation, grammar refusal semantics (11) | "The STT uncertainty contract" |
| Where coreference confidence lives and what this layer supplies (12) | "Coreference - where confidence lives" |
| Test contract, the six corpora, the entry-point command (14) | Testing Decisions |
| Verification gate: what stays identical, what may change, exact commands, what it does NOT assure (15) | "The verification gate" |
| Documentation obligation, named documents, `rag_memory.md` log | Further Notes -> "Documentation obligation" |

Two corrections this ticket carried are honoured in the spec's voice: there is **no redaction sink
order** (a four-site conversion list and one criterion - persists / streams / can speak it back),
and there is **no do-not-learn-from-this-turn rule** (the write boundary lands on *fields, not
turns*).

The documentation obligation resolves as: **none of the four lockstep documents is updated** - the
rule itself is retired by ticket 18 and the set stays in `docs/archive/`. What this effort must
update is the eleven-row table in the spec's Further Notes, headed by `CLAUDE.md` (loaded into every
session, currently carrying four false or stale statements) and the new
`docs/architecture/STT_CAPTURE_CONTRACT.md`. That pass is a **precondition of implementation**, not
a follow-up, and it is not yet discharged.
