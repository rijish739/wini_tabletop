# Rewrite the architecture document set

Status: resolved (2026-08-27)
Type: documentation
Blocked by: —
Owner: TBD
Raised by: ticket 13 (2026-08-27), on the user's call that the lockstep set is contaminated

## Question

The four documents CLAUDE.md declares as a mandatory lockstep set describe an architecture
the system no longer has. What replaces them, and what does `CLAUDE.md` point at instead?

## Why this exists

The user's finding, 2026-08-27: `learner_cognitive_state_architecture.md` and its three
lockstep partners carry very old architecture and are contaminated. The instruction was to
remove them, write one new document, and point `CLAUDE.md` at it alone — following
`docs/architecture/WINI_LAYERED_ARCHITECTURE.md`.

Two facts make that instruction need a precise reading rather than a literal one.

**1. The lockstep set already left `docs/architecture/`.** All four now sit in
`docs/archive/` (`map.md:32`), so the mandatory-propagation rule in `CLAUDE.md` currently
points into the archive.

**2. `WINI_LAYERED_ARCHITECTURE.md` is a better skeleton than the four, but it is not
currently true.** Dated 2026-08-05, it predates every ticket in this map. Measured:

| Term | Occurrences in `WINI_LAYERED_ARCHITECTURE.md` |
|---|---|
| `Utterance Intake` | 0 |
| `UtteranceObservation` | 0 |
| `Feature Module` | 0 |
| `TurnPhase` | 0 |
| `child_safety` | 0 |
| `SafetyVerdict` | 0 |
| `personal data` | 0 |

And its L1 Admission section (`:308-341`) states, as a mandate:

> **Model usage: NONE by mandate** … What NOT to implement yet: *a model-based safety
> classifier as the primary gate*

which is exactly what ticket 07 decided to build. It also cites `DEC-044` as the STT floor's
authority — the reference ticket 11 proved appears once in the repo and was never written —
and mandates "gate recall measured directly", which `CLAUDE.md` already records as
**replaced**. Adopting it as-is would install a rule forbidding decided work.

## Decided (2026-08-27, /grilling on ticket 13)

**Skeleton, not supersession-in-place.** The new document is written fresh on the layer model
— L0–L9 plus X1/X2, the contracts-between-layers frame, the per-layer *Must not do*
discipline — and `WINI_LAYERED_ARCHITECTURE.md` is **archived** alongside the other four. Two
live documents with the same layer map is the contamination being cured. Revising in place
would also carry forward a header reading "Date: 2026-08-05", a workspace path from a
different machine, and an evidence base (FACT 1–3: 306 turns, 23 graded writebacks, empty
learner state) that is a **measurement from August** and must not be silently restated as
current. Take the structure; re-derive the content. The archived copy stays readable as the
reasoning that produced the layer model.

**One normative document, and the lockstep rule dies with the other three.** The new document
owns *the architecture and its contracts* and nothing else. The store-build plan and the
dataset/model report do not become chapters: they become **dated measurement records** that
the architecture document cites and never restates.

> The four documents rotted because a four-way manual propagation obligation is
> unmaintainable, so people stopped propagating and the documents drifted apart while all
> four still claimed authority. One normative document plus dated measurement records has no
> propagation obligation at all — a number lives in exactly one place, and re-measuring means
> writing a new record, not editing an old sentence.

**Cite the current contracts; never absorb them.** `docs/architecture/SAFETY_ROUTE_TAXONOMY.md`
and `docs/architecture/PERSONAL_DATA_CONTRACT.md` (both 2026-08-27, both measured, both already
normative in `CLAUDE.md`) stay authoritative for their own areas. The architecture document says
what a layer is *responsible for* and points at the contract for what a finding *is*. Absorbing
them would produce a second copy of the safety taxonomy and re-create the propagation obligation
this ticket exists to remove. Same for the seventeen ticket resolutions: the document states the
boundary; the resolutions stay the reasoning record.

**`CLAUDE.md` changes; `CONTEXT.md` does not.** The 4-doc lockstep table is replaced by a short
**source-of-truth block**: the new architecture document for boundaries and contracts; the two
contracts for safety and personal data; `CONTEXT.md` for vocabulary; dated records for numbers.
Plus one line naming which document loses when two disagree. `CONTEXT.md` is **not touched** and
gets no pointer — it is the domain model, it is already current (it carries `Utterance` and
`Utterance Intake` from tickets 01–02), it is upstream of the architecture document rather than
an index to it, and a "refer only to X" line inside a glossary makes it look like a routing
document.

**Nothing blocks on this ticket.** Ticket 13 closed without it; ticket 16's spec cites the new
document rather than waiting for it. The reason to keep them separate is not tidiness: if 18
blocked 16, a documentation rewrite would gate the implementation spec, and the pressure to rush
18 is precisely what produced four contaminated documents.

**Every file in `docs/architecture/` gets a one-line status header** — *normative* /
*research (dated; superseded by findings only)* / *explainer* — and the two competing
architecture documents are archived.

## Work items

1. Write the new normative architecture document on the L0–L9 + X1/X2 skeleton, reconciled
   against every resolved ticket in this map. The reconciliation is the work; the structure is
   inherited.
2. Archive `WINI_LAYERED_ARCHITECTURE.md` and `FINAL_WINI_PEDAGOGICAL_ARCHITECTURE_PLAN.md`.
3. Add status headers to every remaining `docs/architecture/` file.
4. Replace `CLAUDE.md`'s lockstep block with the source-of-truth block, including the
   precedence line.
5. Carry ticket 13's two promoted Perception rules into the new document: **never softmax /
   independent per-label thresholds**, and **do not strip stop words**. Plus the open eval
   question: **compound-utterance chunking** (a turn that both explains and asks currently
   yields one signal set).

## Known reconciliation points

Each is a place `WINI_LAYERED_ARCHITECTURE.md` states something a resolved ticket overturned.
Not exhaustive — the sweep is item 1's job.

| Section | Says | Overturned by |
|---|---|---|
| L1 Admission | "Model usage: NONE by mandate"; do not build a model-based primary safety gate | 07 |
| L1 Admission | "gate recall measured directly" | 07 (blind per-class corpora; no aggregate number) |
| L1 Admission | STT floor "start 0.6, calibrate per DEC-044" | 11 (`DEC-044` never existed; `latest_short` confidence is not a confidence score) |
| L1 Admission | PII as a safety risk tier | 07 + 09 (personal data leaves the safety axis) |
| L1/L2 boundary | no Intake layer; Admission reads `transcript` + `stt_confidence` | 01, 02, 03 |
| L2 Perception | no `UtteranceObservation` input | 03 |
| throughout | no `Feature Module` / `TurnPhase` / `ModuleOutcome` vocabulary | `CONTEXT.md`, precedent map |

## Disposition of the archived set

| Document | Was | Becomes |
|---|---|---|
| `learner_cognitive_state_architecture.md` | lockstep 1 — source of truth for schemas/signals/contracts | superseded by the new document |
| `RAG_upgrade_plan.md` | lockstep 2 — store build/verify plan | dated measurement record |
| `model_dataset_architecture_report.md` | lockstep 3 — datasets + models | dated measurement record |
| `complete_architecture_build_plan.md` | lockstep 4 — execution status | dated measurement record |
| `rag_memory.md` | append-style work log | unchanged; still the work log |
| `WINI_LAYERED_ARCHITECTURE.md` | de-facto current architecture | archived; the reasoning behind the layer model |
| `FINAL_WINI_PEDAGOGICAL_ARCHITECTURE_PLAN.md` | competing architecture plan | archived — it reviews commit `8343074` on a branch of a *different* repository and cannot be reconciled against this history |
| `AUDIO_END_TO_END_FLOW.md` | unlabelled | survives in place, labelled **explainer**; the only end-to-end walk of the audio path, useful precisely because it is not a contract |

## Not decided here

The new document's section list beyond the inherited skeleton; whether the three demoted
measurement records are re-measured or shipped with their existing dates stated plainly;
whether `docs/adr/` absorbs any of the ticket resolutions.
