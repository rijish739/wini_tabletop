# Behavioral state-trajectory eval (Part 11 promotion arbiter)

> **Measured 2026-07-02.** Both backends' signal outputs pushed through the UNCHANGED runtime state math (`derive_cognitive_update` → `derive_state_deltas`), graded on the state moves they cause — not on label-reproduction F1 (see the honest note in `perception_eval_report.md`). 48 authored behavioral probes (gated) + 999 TEST-row replay (descriptive). CLAUDE.md: numbers are measured, not hand-edited.

## Behavioral verdict: **PASS**

Gates fixed before measurement:

| Gate | Gemini | Heads | Rule | Verdict |
|---|---|---|---|---|
| G1 field-direction accuracy (n=28) | 0.8571 | 0.6071 | ≥0.80 and ≥heads−0.02 | PASS |
| G2 must-fire flag recall (n=18) | 0.8333 | 0.5000 | ≥0.80 and ≥heads−0.05 | PASS |
| G3 forbidden-flag rate (n=62) | 0.0161 | 0.0161 | ≤0.05 and ≤heads+0.02 | PASS |

Probe collection errors (Gemini fallbacks, uncached/retryable): 0

### Per-flag probe results (must-fire hits / probes; false fires on forbidden probes)

| Flag | Gemini must | Heads must | Gemini false | Heads false |
|---|---|---|---|---|
| misconception_suspected | 5/5 | 3/5 | 0 | 0 |
| transfer_ready_evidence | 2/4 | 1/4 | 0 | 0 |
| hint_requested | 2/2 | 2/2 | 0 | 0 |
| prerequisite_weakness_clue | 1/2 | 0/2 | 0 | 0 |
| frustration_risk | 2/2 | 0/2 | 0 | 0 |
| self_corrected | 3/3 | 3/3 | 1 | 1 |

Per-probe audit trail: `behavioral_eval_detail.jsonl` (targets, fired flags, misses per backend).

## TEST replay — descriptive evidence (NOT gated)

All 999 cached TEST rows replayed through the state math under three signal sources (heads local, Gemini cached, gold-as-binary). Gold-derived moves are shown for context only — grading against them would re-import the dense-gold dispute.

### Mean per-turn global targets

| Field | Heads | Gemini | Gold |
|---|---|---|---|
| confidence | 0.3701 | 0.4577 | 0.3966 |
| curiosity | 0.7676 | 0.0364 | 0.8468 |
| cognitive_load | 0.4249 | 0.1710 | 0.2512 |
| engagement | 0.5905 | 0.5327 | 0.8143 |

### Per-turn target MAE / EMA pseudo-session terminal MAE (84 sessions × 12 turns)

| Field | heads↔gemini turn | heads↔gold turn | gemini↔gold turn | heads↔gemini terminal | gemini↔gold terminal |
|---|---|---|---|---|---|
| confidence | 0.1224 | 0.1458 | 0.1309 | 0.0946 | 0.0832 |
| curiosity | 0.7315 | 0.2298 | 0.8104 | 0.7228 | 0.7876 |
| cognitive_load | 0.2747 | 0.2929 | 0.1764 | 0.2478 | 0.1178 |
| engagement | 0.1370 | 0.2440 | 0.3095 | 0.0882 | 0.2720 |

### Flag firing on real TEST rows

| Flag | Heads fires | Gemini fires | Gold-move fires | H↔G agree | Heads P/R vs gold-move | Gemini P/R vs gold-move |
|---|---|---|---|---|---|---|
| misconception_suspected | 285 | 10 | 102 | 0.7167 | 0.2880 / 0.8040 | 0.4000 / 0.0390 |
| transfer_ready_evidence | 78 | 61 | 84 | 0.8809 | 0.6920 / 0.6430 | 0.1310 / 0.0950 |
| hint_requested | 43 | 30 | 43 | 0.9510 | 1.0000 / 1.0000 | 0.4000 / 0.2790 |
| prerequisite_weakness_clue | 56 | 27 | 57 | 0.9189 | 0.6250 / 0.6140 | 0.1110 / 0.0530 |
| frustration_risk | 108 | 20 | 203 | 0.8819 | 0.9910 / 0.5270 | 0.6500 / 0.0640 |
| self_corrected | 8 | 0 | 9 | 0.9920 | 0.5000 / 0.4440 | — / 0.0000 |

## Reproduce
```powershell
cd "D:\cloud CLI"
$env:PYTHONIOENCODING="utf-8"
python -m eval.behavioral_eval --probes   # BILLED (~50 calls, resumable cache)
python -m eval.behavioral_eval --replay   # offline
python -m eval.behavioral_eval --run      # both -> this report
```
