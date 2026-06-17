# Phase 0 + Phase 1 Eval Report

- Date: 2026-06-10T14:07:08
- Store: `D:\cloud CLI\rag_store` (read-only; enrichment pipeline write-back not yet applied)
- Result: **25/25 checks passed**

## A. Phase 0 — HOPE-readiness scorecard (verify_store.py)

- PASS — scorecard runs: 18 metrics + overall + structural OK — 18 metrics, overall 11.1%, structural OK
- PASS — baseline reproducibility (store unchanged until write-back) — reproduces baseline exactly (overall 11.1%) — deterministic
- PASS — --fail-under gate exit codes — exit 1 when below gate, exit 0 when above
- PASS — --save writes report file — --save writes the full report
- PASS — structural tamper detection (count mismatch -> exit 1) — meta/chunk mismatch detected, exit 1
- PASS — unit: valid_hint_chain — 3-exactly, non-empty, leak regex, dict/str forms
- PASS — unit: transfer-link + metacognitive predicates — near/far counting, invalid-target rejection, both whens required
- PASS — unit: attainment math — count-down binary, absolute ratio, 100% cap

## B. Phase 1 — learner_state.py struggle + status machine

- PASS — struggle thresholds are the documented constants — STRUGGLE_HINT_THRESHOLD=3, STRUGGLE_FAIL_THRESHOLD=2
- PASS — status machine: active->weakening->resolved->recurring cycle — active -> weakening -> resolved -> recurring -> weakening -> resolved
- PASS — status machine: weakening regresses to active on failure — weakening + wrong -> back to active
- PASS — struggle via hint exhaustion (>=3 hints on one problem) — hints_used=3 -> struggled even on a correct answer
- PASS — struggle via 2 consecutive diagnostic failures — 1st fail no, 2nd consecutive fail yes
- PASS — partial outcomes count toward consecutive failures — partial counts as failure for the struggle/status machine (by design)
- PASS — success path returns after_success — clean solve -> after_success
- PASS — mastery write-back deltas + clamping — cold-start 0.30 base; +0.15/+0.05/-0.10 deltas; [0,1] clamp
- PASS — hint counter resets per problem; hint_dependency EMA correct — per-problem reset works; EMA 0.1 -> 0.27 -> 0.489 as specified
- PASS — invalid outcome rejected — invalid outcome raises ValueError
- PASS — persistence round-trip — struggle + misconception status survive save/load
- PASS — ZPD band mapping endpoints — 0->band 1-4, 0.5->3.5-7.5, 1->7-10

## C. Phase 1 — deterministic edge repair (enrich_concepts.py)

- PASS — unit: repair_dangling_edges on synthetic graph — re-points matching edges, preserves relation data, skips prereqs + cross-doc
- PASS — live graph: 184 dangling-source edges repaired, instances reachable — live graph (in-memory): 184 edges re-pointed; concept->example/exercise edges 0 -> 44; 8 concepts gain instances

## D. Phase 1 — LLM enrichment cache (in flight)

- PASS — cached concept enrichments re-validate against hard rules — 26/108 cached; 26 pass ALL hard rules, 0 partial
- PASS — pipeline progress snapshot — progress: concept=26, misc=0, schema=0, hints=0; unreadable/partial lines=0 (in-flight, expected 0-1)
- PASS — issues log contains no validation failures — 1 line(s), all expected ([repair] notice only)

## Findings & notes (beyond pass/fail)

1. **Repaired-edge breakdown** — the 184 re-pointed edges land on: 104 formula,
   35 example, 29 figure, 9 exercise, 6 table, 1 application nodes
   (relations: has_formula 104, has_example 35, illustrated_by 35,
   has_exercise 9, transfers_to 1). Only 8 concepts gain *graph* example/exercise
   instances, but the schema stage also harvests chunk instances
   (worked_example/practice/challenge roles): 102/108 concepts have at least one
   schema instance available, so schema clustering will not starve.
2. **Partial-outcome semantics** — `apply_probe_result` counts "partial" as a
   consecutive failure for the status machine and struggle test while still
   *adding* +0.05 mastery. Verified as implemented; documented here as a design
   decision (two partials in a row -> struggled=True).
3. **Cache quality so far** — every cached concept enrichment (26/108 at eval
   time) re-validates with ZERO errors against the hard rules (>=2 valid near +
   >=1 far transfer, >=1 integration link, >=2 CT probes incl. counterexample,
   both metacognitive whens, difficulty 1-9, no self/invalid ID targets). The
   retry-with-feedback loop is holding the line; nothing in the issues log but
   the expected [repair] notice.
4. **Baseline integrity** — the live store still reproduces the 11.1% baseline
   exactly (write-back has not run), so the post-pipeline scorecard delta will be
   attributable to Phase 1 alone.
5. **Re-run after write-back** — once enrich_concepts.py finishes, re-run
   `python eval_phase01.py` plus `python verify_store.py --fail-under 60`:
   section A2 (baseline equality) is EXPECTED to fail at that point (attainment
   should jump), and section C2's pre-repair count will become non-zero since
   the repair will then be persisted. Both are success signals, not regressions.
