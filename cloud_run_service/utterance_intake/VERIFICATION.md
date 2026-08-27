# Verification — the deterministic input layer

> **A green run of this gate means the code does what these specifications say,
> measured on corpora we wrote ourselves. It is not evidence that any child was
> protected. This gate does not cover: subject-matter review of tutoring content
> or deterministic checks on numerical answers; a named safeguarding owner,
> staffed escalation rota, incident playbook, after-hours plan or drill evidence;
> a data map, age/consent review, retention and deletion design, access control,
> vendor review, or per-jurisdiction legal sign-off; an independent red team,
> accessibility review, or usability study with children or educators; production
> dashboards for false negatives and positives, a fast pause path for a harmful
> response path, or a versioned template and resource registry. Until the
> Safety-operations gate has a named, staffed owner, the product must not claim
> that it monitors safety or alerts adults.**

That statement is at the **top** of this document deliberately. A caveat under a
table of passing checks is read as a footnote; this one is the point. Its last
sentence is the stop-ship condition, carried verbatim.

## Stages

The effort lands in **three stages over one standing set** that is never allowed
to go red. This document and the `ci.yml` workflow are the gate's definition and
its executable form; there is no third `VERIFICATION`-authority that can drift.

| Stage | Unit | Lane | Prerequisite |
|---|---|---|---|
| **1** | Utterance Intake — contracts, coordinator phase, composition seam | free only, no billed run | none |
| **2** | `child_safety/` cutover | billed, team-approved | the WIF ticket has landed |
| **3** | `personal_data/` | billed, team-approved | the WIF ticket has landed, Stage 2 complete |

Stages 2 and 3 are **blocked on the Workload Identity Federation ticket** — stated
on the stage line, not in a footnote, so it is not discovered on cutover day.

## Stage 1 pass set (this ticket — ticket 01 delivers the walking-skeleton subset)

Run from `cloud_run_service/`, free lane:

```
python -m unittest discover -s utterance_intake/tests -v
python -m unittest discover -s runtime/tests -v
python -m unittest discover -s . -p "test_*.py" -v
```

Delivered by ticket 01:

- `unittest discover` green across every `cloud_run_service/*/tests`.
- The frozen observation contract and its construction invariants (raise-not-clamp).
- The shared golden-fixture conformance suite; nobody hand-rolls an observation shape.
- Corpus integrity over the intake fixtures, and the **empty-but-live**
  expected-diff manifest mechanism (`fixtures/expected_diffs.jsonl`).
- Tier A: `gate()` over the observation is **byte-identical** to `gate()` over
  text for the terse-real-answer set and the nine nonsense probes.
- The `TurnPhase.UTTERANCE_INTAKE` insert passing `_validate_phase_trace`.
- Turn-level property #1: a terse real answer survives the full Intake -> `gate()`
  path.
- The legacy-20 safety regression, written against the shared composition helper
  from day one — **the test file is never edited at the `child_safety` cutover.**

## What stays identical, what may change

| Tier | Contents | Rule |
|---|---|---|
| **A — byte-identical** | `gate()`'s SAFETY / NONSENSE decisions over the nonsense probes and the terse-real-answer set | asserted; any difference is a failure |
| **B — expected diff** | `normalize_input` (NFKC removal) and `detect_student_problem` (raw -> normalized) | every diff row matches the **closed** manifest, and every manifest row produces a diff |
| **C — unconstrained** | everything downstream of the two new model calls | measured by the Stage 2/3 floors, never by equivalence |

The expected-diff manifest (`fixtures/expected_diffs.jsonl`) is **closed**
(committed before the comparison first runs) and **symmetric** (an unlisted diff
fails, *and* a manifest row that produces no diff fails). Ticket 01 ships it
empty-but-live; later slices add rows.

## A written rule

**No per-row label number is ever cited as evidence that the turn behaves
correctly.** The turn-level properties, not the label suites, are what say the
turn keeps the child's answer.
