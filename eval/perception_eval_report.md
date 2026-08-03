# Perception eval report (Part 11 Stage 2)

> **Measured 2026-07-25** over **999 cached TEST rows** (`perception_eval_raw2.jsonl`) — **§5.5-hardened** (always-fill secondary_concepts, MiniLM candidate_concepts hints, resolver cross-check on the primary) + 20 authored intent probes. Gemini `gemini-2.5-flash` @ `asia-south1`, `temperature=0`, enum-constrained schema (108 concepts + INHERIT, 38 signals, 8 intents). CLAUDE.md: these numbers are re-measured, not hand-edited.

## Promotion to Stage 4: **GO**

| Gate | Measured | Baseline | Verdict |
|---|---|---|---|
| Concept top-1 | 0.9300 | ≥ 0.895 | PASS |
| Concept top-3 | 0.9900 | ≥ 0.971 | PASS |
| Signals — behavioral state-trajectory eval (`behavioral_eval_report.md`) | PASS | 3 pre-fixed gates | PASS |
| Intent macro-F1 (non-safety) | 1.0000 | ≥ 0.9 | PASS |
| SAFETY recall (gate floor) | 1.0000 | ~1.0 | PASS |
| No LEARNING falsely gated | 0 | 0 | PASS |
| Concept rows graded | 600 | — | — |

> Concept is graded **with the §5.5 resolver cross-check** — the runtime behavior (`GeminiPerception.resolve` applies the same `fuse_primary`). Raw Gemini primary before fusion: top-1 0.8900 / top-3 0.9900. The cross-check never introduces a concept Gemini didn't list and never overrides INHERIT.

## Re-scoped signal gate — state-material signals only (owner decision 2026-07-01)

Grades signals only on the **16 labels the state math reads** (`analyzer.py` `derive_cognitive_update` + `derive_state_deltas`), at the code's own flag thresholds (0.5, 0.4 for misconception). Both models scored on the SAME subset:

| Scope | Heads micro-F1 | Gemini micro-F1 (P / R) |
|---|---|---|
| state-material (16) | 0.7982 | 0.3263  (0.5562 / 0.2309) |
| state-material − curiosity | 0.7015 | 0.4148  (0.5286 / 0.3413) |

> **Honest note (why this is NO-GO and what it means).** Re-scoping to signals that matter does NOT close the gap — the heads win at every scope. The reason is that the heads were **trained to reproduce this dense gold** (e.g. `curiosity` is gold-labeled on 85% of rows; heads recall 0.95 by memorization, Gemini 0.06 by applying the label's meaning), while Gemini is **conservative by design** (§5.5b: 2.6 signals/row vs gold's 5.4, precision 0.56 / recall 0.24 on the subset). A label-reproduction F1 gate — at any scope — cannot be won by a conservative perceiver graded against a model trained on the labels. **Conclusion: signal-F1-vs-heads is the wrong promotion arbiter; a behavioral state-trajectory eval is needed** (Part 11 §8 Stage 2 was a proxy). Concept/intent/safety are unaffected by this.

## §5.5b signal-threshold calibration (full 38-label sweep — retained for transparency)

Pre-calibration operating point t=0.5: micro **0.3896** / macro **0.2927**.  
Calibrated operating point **t=0.5**: micro **0.3896** / macro **0.2927** (max micro-F1, macro tie-break).

> Set `PERCEPTION_SIGNAL_THRESHOLD` to the calibrated value before flipping the backend (config.py default / .env). Note (eval honesty): the threshold is fit on the TEST split per the Part 11 §5.5b design, so the post-calibration F1 is an upper bound on that operating point.

| t | micro-F1 | macro-F1 |
|---|---|---|
| 0.05 | 0.3742 | 0.2877 |
| 0.1 | 0.3742 | 0.2877 |
| 0.15 | 0.3747 | 0.2879 |
| 0.2 | 0.3747 | 0.2879 |
| 0.25 | 0.3771 | 0.2889 |
| 0.3 | 0.3771 | 0.2889 |
| 0.35 | 0.3836 | 0.2904 |
| 0.4 | 0.3836 | 0.2905 |
| 0.45 | 0.3895 | 0.2927 |
| 0.5 | 0.3896 | 0.2927  ← calibrated |
| 0.55 | 0.3849 | 0.2857 |
| 0.6 | 0.3848 | 0.2854 |
| 0.65 | 0.3486 | 0.2472 |
| 0.7 | 0.3491 | 0.2477 |
| 0.75 | 0.2689 | 0.1830 |
| 0.8 | 0.2697 | 0.1836 |
| 0.85 | 0.1517 | 0.0614 |
| 0.9 | 0.1513 | 0.0624 |
| 0.95 | 0.0007 | 0.0050 |

## Deterministic gate coverage (offline, model-independent — the safety floor, §4.2)
- SAFETY gate recall: **1.0** (20/20)
- NONSENSE gate recall: **1.0** (9/9)
- LEARNING utterances falsely gated: **0** (must be 0)

## Reproduce
```powershell
cd "D:\cloud CLI"
$env:PYTHONIOENCODING="utf-8"
python -m eval.perception_eval --build            # write eval jsonl from the frozen TEST split
python -m eval.perception_eval --gates            # measured gate coverage (offline)
python -m eval.perception_eval --collect          # BILLED: cache Gemini preds (resumable)
python -m eval.perception_eval --score            # offline metrics + calibration -> this report
python -m eval.perception_eval --collect --limit 8  # small smoke
```

## Promotion gate to Stage 4 (do not skip; CLAUDE.md)
1. Full `--collect` (all 999 TEST rows) then `--score`.
2. Concept top-1 ≥ 0.895 and top-3 ≥ 0.971 (near-miss now; empty-secondary artifact — recoverable via §5.5 concept hardening).
3. Signals: the state-material-vs-heads gate above is a **label-reproduction proxy the heads win by construction** — supersede it with a **behavioral state-trajectory eval** before promoting (see the honest note).
4. Intent macro-F1 acceptable; SAFETY gate recall ~1.0. (Both PASS.)
5. Re-measure, then edit the four lockstep docs with the measured numbers.
