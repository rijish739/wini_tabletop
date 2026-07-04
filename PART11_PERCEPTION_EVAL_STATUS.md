# Part 11 — Perception Eval & Promotion Status

> **What this is:** a status/progress log for the Stage 2 → Stage 4 promotion work of
> the Gemini perception layer (`PART11_GEMINI_PERCEPTION_LAYER.md`). It is **not** a
> lockstep contract doc — it sits beside the four lockstep docs and carries no
> authoritative contracts (like `CLOUD_VOICE_STATUS_AND_GOTCHAS.md`).
>
> **Date:** 2026-07-01 (behavioral eval added 2026-07-02). **Repo:** `D:\cloud CLI`. **GCP:** `custom-model-training-493207`,
> Gemini `gemini-2.5-flash` @ `asia-south1`, `temperature=0`, enum-constrained schema
> (108 concepts + `INHERIT`, 38 signals, 8 intents).

---

## 1. Status at a glance

| Piece | State |
|---|---|
| Stages 0–3 (gates, `GeminiPerception`, front door, persona, harness) | ✅ built + verified |
| §5.5b signal-threshold calibration + resumable one-time eval | ✅ built + verified this session |
| **Full 999-row TEST collect (billed Gemini)** | ✅ **COMPLETE — 999/999 rows, 20/20 intent, 0 errors** |
| `--score` → calibrated threshold + verdict | ✅ ran → **NO-GO** (see §3) |
| **Re-scoped signal gate** (owner-chosen path, state-material subset) | ✅ **built + measured → still NO-GO; the gate itself is the problem (§5)** |
| **Behavioral state-trajectory eval (§5 fork #1, owner-approved 2026-07-02)** | ✅ **RAN → PASS all 3 gates (§7) — the signal blocker is CLEARED** (re-verified under the hardened prompt) |
| **§5.5 concept hardening + full 999-row re-collect (v2 cache)** | ✅ **DONE 2026-07-02 → concept top-1/top-3 0.930/0.990 — both gates PASS (§8)** |
| **Stage 4 flip (`PERCEPTION_BACKEND=gemini`)** | ✅ **FLIPPED 2026-07-02 — all promotion checks green; verified by tests + E2E turn (§8)** |
| Stage 5 (Vertex context cache) | ✅ **DONE 2026-07-02** — 6,062 static tokens cached; ~1.0–1.1 s/call warm vs ~1.3–1.5 s uncached (§9) |
| Stage 6 (lockstep doc propagation / head removal) | ✅ **DONE 2026-07-02** — docs propagated + MiniLM-heads runtime path retired (owner-directed); artifacts stay as eval baseline (§9) |

**Flipped 2026-07-02.** `PERCEPTION_BACKEND` default is `gemini` (perception/config.py);
`PERCEPTION_SIGNAL_THRESHOLD` stays `0.5` (sweep was flat; behavioral eval governs signals).
MiniLM heads remain on disk as fallback + eval baseline. Caches: `perception_eval_raw.jsonl`
(v1, pre-hardening provenance) and `perception_eval_raw2.jsonl` (v2, **prompt of record**) —
never mix across prompt versions; re-scoring either is free.

---

## 2. What was implemented this session (offline, no re-billing)

The remaining Part 11 blocker was the §5.5b calibration and a way to run the ~1000
billed calls **once**. Both are done in `eval/perception_eval.py` (full refactor; no
other runtime file changed).

- **`--collect [--limit N]`** — one Gemini call per uncached utterance → appended to
  `eval/perception_eval_raw.jsonl` (`f.flush()` per row). **Resumable** (keyed by
  `("test", row_id)` / `("intent", utterance)`); only `_source=="gemini"` rows cached, so
  fallbacks are retried. SAFETY probes are gate-caught offline, never billed.
- **`--score` / `--calibrate`** — every metric + the §5.5b threshold sweep (`t∈[0.05,0.95]`,
  micro-F1 optimal, macro tie-break) recompute **offline from the cache** — trying a new
  operating point never re-bills.
- **`_promotion_verdict()` + `write_report()`** — per-gate GO/NO-GO into
  `eval/perception_eval_report.md`.
- **Clean-exit guard** added after a known google-genai gRPC segfault-at-shutdown (exit
  139) made the completed background run falsely report "failed" (see §6 gotcha).
- **Verified offline** (synthetic preds, zero calls): concept/signal/intent scoring, the
  sweep (finds an interior optimum), and the report writer.

---

## 3. Measured result (999 TEST rows) — **NO-GO**

| Gate | Measured | Baseline | Verdict |
|---|---|---|---|
| Concept top-1 | **0.882** | ≥ 0.895 | FAIL (near-miss, −0.013) |
| Concept top-3 | **0.933** | ≥ 0.971 | FAIL (near-miss, −0.038) |
| Signal micro-F1 (calibrated t=0.5) | **0.398** | ≥ 0.77 | **FAIL (large)** |
| Signal macro-F1 (calibrated t=0.5) | **0.301** | ≥ 0.62 | **FAIL (large)** |
| Intent macro-F1 (non-safety, 20 probes) | **1.000** | ≥ 0.90 | PASS |
| SAFETY gate recall | **1.000** | ~1.0 | PASS |
| No LEARNING falsely gated | **0** | 0 | PASS |

Concept rows graded: 600/999 (the other 399 are `INHERIT`, not gradable).
Full report + threshold sweep: `eval/perception_eval_report.md`.

**Intent, safety, and the deterministic gates are solved. Concept is a near-miss.
Signals are the blocker — and the reason is structural, not a threshold problem.**

---

## 4. Root cause — labeling-philosophy mismatch, not a Gemini failure

The signal-threshold sweep is **flat at ~0.39 micro from t=0.05→0.5**, then declines: no
operating point recovers recall, because the gap is *what Gemini emits*, not where the
threshold sits.

- **Density mismatch:** gold averages **5.39 signals/row**; Gemini emits **2.62/row**.
  Micro **precision 0.61 / recall 0.30** — Gemini's picks are precise and sensible, it
  just doesn't emit the dense tail the classifier's gold rewards. This is Gemini doing
  exactly what §5.5b told it to: "default to absent… never generous… require a quotable
  span."
- **Degenerate high-base-rate labels dominate the miss.** `curiosity` is gold-labeled on
  **846/999 rows (85%)** at recall 0.06 (797 misses — 21% of all FN); `algebraic` 482
  rows @ 0.04; `representation_shift` @ 0.02; `diagrammatic` @ 0.03. These labels are
  applied so densely they carry little discriminative signal. On the signals that
  actually move state Gemini is fine: **confusion 0.79, question 0.70,
  request_representation 0.58, cognitive_overload 0.48, low_confidence 0.43.**
- **But excluding the degenerate labels does not close the gap** (free re-score from the
  cache, illustrative — NOT a redefinition of the official gate):

  | Scope | micro | P | R |
  |---|---|---|---|
  | ALL 38 labels (official gate) | 0.398 | 0.608 | 0.295 |
  | exclude 4 degenerate (recall<.07) | 0.494 | 0.597 | 0.421 |
  | exclude 8 low-signal labels | 0.530 | 0.609 | 0.468 |

  Even on the 30 "meaningful" labels, micro is 0.53 — Gemini is systematically sparser
  than dense gold across the board.

**The core tension:** the §5.5b design goal (conservative, precise, avoid spurious state
moves) is in **direct conflict** with the promotion gate (reproduce the classifier's
dense multi-label recall). A conservative perceiver *cannot* pass a dense-recall F1 gate,
and matching `curiosity`@85% would make the signal meaningless downstream anyway. So the
gate as written may be measuring the wrong thing.

---

## 5. Re-scope executed — outcome + the real fork

**Owner chose path (a)#1: re-scope the signal gate to state-material signals.** Done and
measured (`eval/perception_eval.py` `score_material` / `heads_material_micro`;
`eval/perception_eval_report.md`). The state-material subset is **16 labels derived from
code** (`analyzer.py` `derive_cognitive_update` reads confusion, curiosity,
high/low_confidence, anxiety, misconception_clue, recurring_error, transfer_attempt,
abstraction_attempt, self_correction, cognitive_overload, frustration, ready_for_next,
disengagement; `derive_state_deltas` adds request_hint, prerequisite_weakness), graded at
the code's own flag thresholds (0.5, 0.4 for misconception). Both models on the SAME scope:

| Scope | Heads micro-F1 | Gemini micro-F1 (P / R) |
|---|---|---|
| all 38 labels | 0.832 | 0.398 (0.61 / 0.30) |
| **state-material (16)** | **0.798** | **0.333 (0.56 / 0.24)** |
| state-material − curiosity | 0.702 | 0.426 (0.53 / 0.35) |

**Re-scoping did NOT rescue it — and that is the finding.** The heads win at every scope
because they were **trained to reproduce this dense gold** (`curiosity` gold-labeled on 85%
of rows: heads recall 0.95 by memorization vs Gemini 0.06), while Gemini is **conservative
by design** (§5.5b). A label-reproduction F1 gate cannot be won by a conservative perceiver
graded against a model trained on the labels — so the **gate itself, not Gemini, is the
wrong promotion arbiter.** I did not fudge the subset to force a pass.

**The real fork now:**
1. **Behavioral / state-trajectory eval (recommended).** Replay transcripts through both
   backends and compare the *state moves they cause* (`derive_*`/`apply_deltas` outputs:
   confidence/curiosity/cognitive_load/engagement EMAs, flags fired) rather than
   label-reproduction F1. Judge Gemini on whether it drives *better or equal pedagogy*, not
   on matching noisy labels. This is the honest promotion gate. Mostly free (heads local;
   Gemini preds already cached for the TEST rows; new transcripts need a small billed
   collect).
2. **Accept sparse-precise perception** on the strength of concept+intent+safety +
   spot-checks, treating signals as advisory continuous scores (which `derive_cognitive_
   update` already consumes) rather than a gated set.
3. **Loosen conservatism + re-collect** (billed) — raises recall toward the dense gold but
   re-introduces the over-firing §5.5b warned about; won't sanely fix `curiosity`@85%.
4. **Re-curate the dense gold** (touches read-only dataset; large effort).

**Concept near-miss (0.882/0.933) — still cheaply recoverable** and independent of the
signal question: Gemini returns **empty `secondary_concepts` on 74% of rows**, so top-3
collapses to top-1. The §5.5 concept-hardening hook (feed top-K MiniLM-similar concepts as
candidates / cross-check against the resolver / prompt for 2–3 secondaries) should clear
0.971. Needs a small billed re-collect to re-measure.

---

## 6. Files & gotcha

**Changed this session**
```
eval/perception_eval.py   resumable --collect, offline --score/--calibrate, §5.5b sweep,
                          promotion verdict, report writer, clean-exit guard
```
**Generated by the run (not hand-edited)**
```
eval/perception_eval_raw.jsonl    999 cached Gemini predictions (resumable; re-score free)
eval/perception_eval_report.md    measured metrics + NO-GO verdict + sweep table
eval/perception_eval_{signals,intent,safety}.jsonl   frozen eval sets
```
**Gotcha (new):** google-genai's gRPC C-core segfaults during interpreter shutdown on
Windows (exit **139**) — *after* work completes and the report is written, so it is
cosmetic. A completed `--run` therefore reported "failed" until the `os._exit(0)` guard
was added. Trust `eval/perception_eval_report.md` (written before teardown) and the raw
cache row count, not the process exit code.

---

## 7. Behavioral state-trajectory eval — **PASS** (2026-07-02, fork #1 executed)

Owner approved §5 fork #1. Built `eval/behavioral_eval.py`: both backends' signal outputs
run through the **unchanged** runtime state math (`derive_cognitive_update` →
`derive_state_deltas`) and are graded on the **state moves they cause**, not label F1.
Two parts; full numbers in `eval/behavioral_eval_report.md`, per-probe audit trail in
`eval/behavioral_eval_detail.jsonl`.

**Part 1 — 48 authored behavioral probes (the gated arbiter, model-independent).**
Expectations authored from utterance semantics (target bands for the 4 global fields +
must-fire / must-not-fire flags); neither the dense gold nor the heads defines
correctness. Gates were fixed in code **before** measurement. ~48 billed Gemini calls
(resumable cache `eval/behavioral_eval_raw.jsonl`; 1 timeout-fallback retried clean).

| Gate (rule) | Gemini | Heads | Verdict |
|---|---|---|---|
| G1 field-direction accuracy (≥0.80 and ≥heads−0.02), n=28 | **0.857** | 0.607 | **PASS** |
| G2 must-fire flag recall (≥0.80 and ≥heads−0.05), n=18 | **0.889** | 0.500 | **PASS** |
| G3 forbidden-flag rate (≤0.05 and ≤heads+0.02), n=62 | **0.000** | 0.016 | **PASS** |

Gemini is not merely "not worse" — it is **decisively better at driving the state
machine**: heads systematically missed misconception_suspected (2/5), transfer_ready
(3/4), prerequisite_weakness (2/2) and frustration_risk (2/2) musts; Gemini missed only
the two subtlest probes (implicit transfer "using the distributive trick again", implicit
prereq "still don't know how to add fractions from last year") and fired **zero**
forbidden flags on neutral answers/questions.

**Part 2 — 999-row TEST replay (descriptive, offline/free, NOT gated).** All cached
Gemini preds + heads scored locally + gold-as-binary through the same math. Outside the
degenerate `curiosity` label (85% gold base rate), Gemini's per-turn targets are *closer*
to the gold-derived moves than the heads': confidence MAE 0.129 vs 0.146, cognitive_load
0.177 vs 0.293 (engagement 0.310 vs 0.244, driven by the curiosity term). This part is
not gated because grading against gold-derived moves re-imports the density dispute.

**Consequence:** the §3/§5 signal NO-GO is superseded — the label-reproduction gate
measured memorization of dense gold (as §5 concluded), and on the honest behavioral
arbiter Gemini passes every gate. **The only remaining Stage 4 blocker is the concept
top-1/top-3 near-miss** (0.882/0.933 vs 0.895/0.971), addressable via the §5.5 concept
hardening (secondary-concepts prompt fix + small billed re-collect).

Reproduce: `python -m eval.behavioral_eval --run` (probes billed once, then cached;
`--replay` alone is fully offline).

---

## 8. §5.5 concept hardening + Stage 4 flip — **PROMOTED** (2026-07-02)

Owner directed: implement what was pending. Three concept-hardening pieces, then the flip:

1. **Prompt rule (build_perception.py):** when `concept_id` is a catalog id, ALWAYS fill
   `secondary_concepts` with the 2–3 next-most-plausible ids (few-shot anchors updated to
   demonstrate it). This alone fixed the top-3 collapse: Gemini had left secondaries empty
   on 74% of rows — an instruction gap, not a capability gap.
2. **Candidate hints (gemini_perception.py):** top-8 MiniLM-similar concepts injected per
   turn as `candidate_concepts` (resolver's `anchor_embeddings.npy` + shared embedder;
   `PERCEPTION_CANDIDATE_K`, best-effort, hints not a restriction).
3. **Deterministic resolver cross-check (`fuse_primary`,** `PERCEPTION_CONCEPT_CROSSCHECK`**):**
   in `GeminiPerception.resolve`, the local resolver's confident (≥ tau) top-1 is promoted to
   primary ONLY when it already sits in Gemini's {primary+secondaries}; never introduces a
   concept Gemini didn't list, never overrides INHERIT. Both candidate rules (R1 doc rule /
   R2 rank-by-resolver) were measured **offline, free, from the cache** before implementing —
   both scored 0.93; R1 (the §5.5-documented rule) was implemented and is mirrored in the
   eval (`crosscheck_map`) so the report grades runtime behavior (raw numbers shown alongside).

**Measured (full 999-row re-collect into `perception_eval_raw2.jsonl`, 0 errors):**

| Gate | v1 (2026-07-01) | v2 hardened (2026-07-02) | Baseline | Verdict |
|---|---|---|---|---|
| Concept top-1 | 0.882 | **0.930** (raw 0.890 + cross-check) | ≥ 0.895 | **PASS** |
| Concept top-3 | 0.933 | **0.990** | ≥ 0.971 | **PASS** |
| Signals | — | behavioral eval re-run under hardened prompt → **PASS** (0.857 / 0.833 / 0.016) | 3 pre-fixed gates | **PASS** |
| Intent macro-F1 | 1.000 | 1.000 | ≥ 0.90 | PASS |
| SAFETY / false-gates | 1.0 / 0 | 1.0 / 0 | ~1.0 / 0 | PASS |

The 66 remaining raw top-1 misses were 88% same-chapter granularity picks with gold in the
secondaries — which is exactly what the cross-check exploits (fused top-1 0.930 beats the
resolver-alone 0.895: the two rankers correct each other's adjacent-concept confusions).

**Flip executed:** `PERCEPTION_BACKEND` default → `gemini` (perception/config.py). Verified:
offline + `--integration` perception tests PASS; headless `tutor_loop.py --once` E2E turn on
the new default (correct concept + secondaries, sensible signals, unchanged state math).
`_promotion_verdict` now reads the behavioral verdict as the signals gate (the label-F1
comparison is retained in the report as context only). Lockstep docs propagated this session:
build plan §13/§13.2, architecture §6.2, report §3.3 note, WINI_ARCHITECTURE front-door note,
CLAUDE.md mandate + quick commands, rag_memory.md work log.

**Open:** Stage 5 Vertex context cache (~21k-char static block re-sent per call today — cost/
latency only, no correctness impact); Stage 6 head removal (owner decision after a stability
window); production firing-rate monitoring during that window.

---

## 9. Stage 5 (context cache) + Stage 6 (head retirement) — **DONE** (2026-07-02, owner-directed)

**Stage 5 — Vertex context cache (`perception/vertex_cache.py`).** The static block
(intent taxonomy + 38 signal defs + 108-concept catalog + anchors, **6,062 tokens**) now
lives in a Vertex cached-content resource; each call sends only the dynamic prompt +
response schema. Graceful by construction: `active_name()` returns the resource only if
unexpired (2-min margin), the **context sha still matches the built prompt** (a rebuild
invalidates the cache — never serve a stale block), and the model id matches; a failed
cached call is retried once with the full system instruction and the cache is dropped for
the process. `PERCEPTION_CACHED_CONTENT` env still overrides. CLI:
`python -m perception.vertex_cache --create [--ttl-hours 24] | --status | --delete`
(re-run `--create` after any `build_perception` rebuild or TTL expiry; superseded resources
are deleted to stop storage billing).

**Measured gate (same utterance, warm client, real schema):** correctness identical (same
concept pick); **cached ~1.0–1.1 s/call vs uncached ~1.3–1.5 s**; token meter shows
**6,062 of ~9,155 prompt tokens (66%) billed at the cached rate** — the un-cacheable
remainder is the dynamic prompt + the per-call `response_schema` (generation config cannot
be cached). Per-turn input cost ≈ $0.0014. Within budget → gate green.

**Stage 6 — MiniLM heads retired from the runtime path (`tutor_loop.py`).** The
`qwen_heads` authoritative branch, the Stage-1 shadow hook (`PERCEPTION_SHADOW`), and the
front-door backend check are removed; `TutorLoop` always injects `GeminiPerception`. A
stale `PERCEPTION_BACKEND=qwen_heads` env degrades to a printed notice + gemini (never a
crash). The learning-path fallback on a failed Gemini call is now gates + inherit-concept +
neutral signals, exactly as Stage 6 specified. **Retained:** all head artifacts
(`models/exemplar_classifier/`, `models/concept_resolver/`) — the eval harnesses load them
directly as baselines, and the resolver artifacts are part of the runtime §5.5 cross-check
(numpy scoring on the shared embedder, not the retired classifier path). MiniLM itself
stays in-process for retrieval + HOPE (CLAUDE.md mandate, unchanged).

**Verified:** offline + `--integration` perception tests PASS; headless E2E
`tutor_loop.py --once` hint-request turn on the cached+retired stack (request_hint fired →
rule 3 hint path, correct concept + secondaries). Part 11 is **complete**; the only
standing watch is production firing-rate monitoring during the stability window.
