"""Perception-layer STRESS harness (Part 11 front door).

Drives the *real* front door exactly as tutor_loop does —
    route = gate(text)                       # deterministic SAFETY / NONSENSE
    if route is None:
        route = GeminiPerception.route(text, session)   # the one structured call
— over a balanced, adversarial probe suite (see perception_stress_probes.py) that
covers all 8 intents, all 38 signals, and all 108 concepts. It exists to measure
the model on a distribution the single-learner dev log never produced, and to
answer the open question left by cognitive_signals_bias_analysis.md: for the
under-fired high-order signals, is the score genuinely low ("rare / not elicited")
or does it hover just under threshold ("miscalibrated")?

MODES
  --dry-run   build the suite, print the coverage plan. ZERO Gemini calls. (default)
  --collect   run the live front door on every probe. BILLED (one Gemini call per
              non-gated probe). Caches every raw result to the JSONL sidecar.
  --replay    re-grade from the cached JSONL. ZERO Gemini calls. Use after a
              --collect to re-run the analysis without paying again.

USAGE
  python -m eval.perception_stress                       # dry-run plan
  python -m eval.perception_stress --collect             # full billed run (~180 calls)
  python -m eval.perception_stress --collect --axis signal,intent   # subset
  python -m eval.perception_stress --replay --threshold-sweep
  python -m eval.perception_stress --collect --limit 20  # smoke test

Outputs: eval/perception_stress_raw.jsonl (cache) + eval/perception_stress_report.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval import perception_stress_probes as probes  # noqa: E402

RAW_PATH = ROOT / "eval" / "perception_stress_raw.jsonl"
REPORT_PATH = ROOT / "eval" / "perception_stress_report.md"

# Threshold sweep range for the calibration analysis (report Rec 1 asks about 0.35).
SWEEP = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]


# --------------------------------------------------------------------------- #
# Enums / catalog
# --------------------------------------------------------------------------- #
def load_enums() -> dict:
    p = ROOT / "perception" / "build" / "perception_enums.json"
    return json.loads(p.read_text(encoding="utf-8"))


def chapter_of(cid: Optional[str]) -> Optional[str]:
    if not cid or "__" not in cid:
        return None
    return cid.split("__", 1)[0]


# --------------------------------------------------------------------------- #
# Live front door — replicates tutor_loop.py:2221-2223 exactly.
# --------------------------------------------------------------------------- #
def run_live(suite: List[dict], device: str, threshold: float) -> List[dict]:
    from perception import gate as front_gate
    from perception.gemini_perception import GeminiPerception

    t0 = time.perf_counter()
    print(f"[stress] loading GeminiPerception (device={device}) ...", flush=True)
    gp = GeminiPerception.load(device=device, signal_threshold=threshold)
    print(f"[stress] loaded in {time.perf_counter() - t0:.1f}s", flush=True)

    results: List[dict] = []
    n = len(suite)
    calls = 0
    for i, p in enumerate(suite, 1):
        text = p["text"]
        session = dict(p.get("session") or {})
        r = front_gate(text)
        gated = r is not None
        if r is None:
            r = gp.route(text, session)
            calls += 1
        rec = {
            "id": p["id"],
            "axis": p["axis"],
            "text": text,
            "expect_intent": p.get("expect_intent"),
            "expect_concept": p.get("expect_concept"),
            "expect_signals": p.get("expect_signals") or [],
            "forbid_signals": p.get("forbid_signals") or [],
            "note": p.get("note", ""),
            # observed
            "primary": r.primary,
            "source": r.source,
            "gated": gated,
            "safety_alert": bool(r.safety_alert),
            "concept_id": r.concept_id,
            "concept_confidence": round(float(r.concept_confidence), 4),
            "secondary_concepts": list(r.secondary_concepts),
            "signal_scores": {k: round(float(v), 4) for k, v in (r.signal_scores or {}).items()},
        }
        results.append(rec)
        if i % 10 == 0 or i == n:
            print(f"[stress] {i}/{n} probes  ({calls} billed calls)", flush=True)
    print(f"[stress] done: {calls} billed Gemini calls, {n - calls} gate-only", flush=True)
    return results


def write_raw(results: List[dict]) -> None:
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RAW_PATH.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[stress] wrote raw -> {RAW_PATH}")


def read_raw() -> List[dict]:
    if not RAW_PATH.exists():
        sys.exit(f"[stress] no cache at {RAW_PATH}; run --collect first.")
    out = []
    for line in RAW_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


# --------------------------------------------------------------------------- #
# Grading
# --------------------------------------------------------------------------- #
def fired(rec: dict, threshold: float) -> Dict[str, float]:
    """Signals whose raw score >= threshold, with their scores."""
    return {k: v for k, v in rec.get("signal_scores", {}).items() if v >= threshold}


def grade(results: List[dict], enums: dict, threshold: float) -> dict:
    labels = enums["labels"]
    intents = enums["intents"]
    concept_ids = set(enums["concept_ids"])

    report: dict = {"threshold": threshold, "n": len(results)}

    # ---- INTENT axis ----
    intent_recs = [r for r in results if r["axis"] in ("intent", "safety", "nonsense", "adversarial")]
    intent_graded = [r for r in intent_recs if r["expect_intent"]]
    intent_hits = [r for r in intent_graded if r["primary"] == r["expect_intent"]]
    intent_conf = [(r["expect_intent"], r["primary"], r["id"]) for r in intent_graded
                   if r["primary"] != r["expect_intent"]]
    report["intent"] = {
        "graded": len(intent_graded),
        "correct": len(intent_hits),
        "acc": (len(intent_hits) / len(intent_graded)) if intent_graded else None,
        "misroutes": intent_conf,
        # coverage: did each of the 8 intents get PRODUCED at least once anywhere?
        "produced": Counter(r["primary"] for r in results),
        "all_intents": intents,
    }

    # ---- SAFETY gate recall (must be near-total on the gate alone) ----
    safety = [r for r in results if r["axis"] == "safety"]
    safety_caught = [r for r in safety if r["primary"] == "SAFETY"]
    safety_by_gate = [r for r in safety if r["primary"] == "SAFETY" and r["gated"]]
    safety_missed = [r for r in safety if r["primary"] != "SAFETY"]
    safety_model_only = [r for r in safety if r["primary"] == "SAFETY" and not r["gated"]]
    report["safety"] = {
        "n": len(safety),
        "recall": (len(safety_caught) / len(safety)) if safety else None,
        "gate_recall": (len(safety_by_gate) / len(safety)) if safety else None,
        "missed": [(r["id"], r["text"]) for r in safety_missed],
        "model_only": [(r["id"], r["text"]) for r in safety_model_only],
    }

    # ---- NONSENSE boundary (recall on mash + precision on terse-real) ----
    non = [r for r in results if r["axis"] == "nonsense"]
    non_should = [r for r in non if r["expect_intent"] == "NONSENSE"]
    non_shouldnt = [r for r in non if r["expect_intent"] is None]
    non_recall_hits = [r for r in non_should if r["primary"] == "NONSENSE"]
    non_false_trips = [r for r in non_shouldnt if r["primary"] == "NONSENSE"]
    report["nonsense"] = {
        "recall": (len(non_recall_hits) / len(non_should)) if non_should else None,
        "recall_n": len(non_should),
        "false_trips": [(r["id"], r["text"]) for r in non_false_trips],
        "false_trip_n": len(non_shouldnt),
    }

    # ---- CONCEPT axis ----
    con = [r for r in results if r["axis"] == "concept"]
    exact = [r for r in con if r["concept_id"] == r["expect_concept"]]
    chap = [r for r in con if chapter_of(r["concept_id"]) == chapter_of(r["expect_concept"])]
    abstained = [r for r in con if r["concept_id"] is None]
    resolved_ids = {r["concept_id"] for r in con if r["concept_id"] in concept_ids}
    report["concept"] = {
        "n": len(con),
        "exact": len(exact),
        "exact_rate": (len(exact) / len(con)) if con else None,
        "chapter": len(chap),
        "chapter_rate": (len(chap) / len(con)) if con else None,
        "abstain": len(abstained),
        "abstain_rate": (len(abstained) / len(con)) if con else None,
        "catalog_coverage": len(resolved_ids),
        "catalog_total": len(concept_ids),
    }

    # ---- SIGNAL axis: recall + raw-score diagnostics ("rare vs miscalibrated") ----
    sig_recs = [r for r in results if r.get("expect_signals")]
    per_signal: Dict[str, dict] = defaultdict(lambda: {"expected": 0, "fired": 0, "scores": []})
    forbid_violations: List[tuple] = []
    for r in sig_recs:
        scores = r.get("signal_scores", {})
        for s in r["expect_signals"]:
            v = float(scores.get(s, 0.0))
            per_signal[s]["expected"] += 1
            per_signal[s]["scores"].append(v)
            if v >= threshold:
                per_signal[s]["fired"] += 1
    for r in results:
        scores = r.get("signal_scores", {})
        for s in (r.get("forbid_signals") or []):
            v = float(scores.get(s, 0.0))
            if v >= threshold:
                forbid_violations.append((r["id"], s, round(v, 3), r["text"]))

    sig_rows = []
    for s in sorted(per_signal):
        d = per_signal[s]
        scores = d["scores"]
        mean_s = sum(scores) / len(scores) if scores else 0.0
        recall = d["fired"] / d["expected"] if d["expected"] else 0.0
        # verdict: distinguishes the two failure modes the bias report couldn't.
        if recall >= 0.5:
            verdict = "ok"
        elif mean_s >= threshold - 0.15:      # scores sit just under the line
            verdict = "MISCALIBRATED (near threshold)"
        elif mean_s >= 0.15:
            verdict = "WEAK (partial signal)"
        else:
            verdict = "GAP (barely scored)"
        sig_rows.append({
            "signal": s, "expected": d["expected"], "fired": d["fired"],
            "recall": recall, "mean_score": mean_s,
            "max_score": max(scores) if scores else 0.0,
            "verdict": verdict,
        })
    report["signal"] = {"rows": sig_rows, "forbid_violations": forbid_violations}

    # signal PRODUCTION coverage across the whole suite (which of 38 ever fired)
    produced_signals = Counter()
    for r in results:
        for s, v in r.get("signal_scores", {}).items():
            if v >= threshold:
                produced_signals[s] += 1
    report["signal"]["produced"] = produced_signals
    report["signal"]["all_labels"] = labels

    # ---- THRESHOLD SWEEP over all expected-signal (label, rec) pairs ----
    # micro recall/precision across the engineered signal probes.
    pos_pairs = []   # (rec, expected_label) — a place the signal SHOULD fire
    for r in sig_recs:
        for s in r["expect_signals"]:
            pos_pairs.append((r, s))
    sweep = []
    for th in SWEEP:
        tp = sum(1 for r, s in pos_pairs if float(r["signal_scores"].get(s, 0.0)) >= th)
        recall = tp / len(pos_pairs) if pos_pairs else 0.0
        # precision proxy: of all fires on the signal-probe set, how many were expected?
        fires = 0
        good = 0
        for r in sig_recs:
            exp = set(r["expect_signals"])
            for s, v in r["signal_scores"].items():
                if v >= th:
                    fires += 1
                    if s in exp:
                        good += 1
        precision = (good / fires) if fires else None
        sweep.append({"th": th, "recall": recall, "precision": precision, "fires": fires})
    report["sweep"] = sweep

    return report


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{100 * x:.1f}%"


def render_report(rep: dict, enums: dict) -> str:
    L: List[str] = []
    L.append("# Perception Layer — Stress Test Report")
    L.append("")
    L.append(f"- Probes graded: **{rep['n']}**  ·  signal threshold: **{rep['threshold']}**")
    L.append(f"- Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    L.append("")
    L.append("> Balanced/adversarial suite — NOT the production log. Measures the model, "
             "not developer test-typing habits.")
    L.append("")

    # Intent
    it = rep["intent"]
    L.append("## 1. Intent routing")
    L.append("")
    L.append(f"Accuracy on graded intent probes: **{it['correct']}/{it['graded']} = {pct(it['acc'])}**")
    L.append("")
    L.append("Intent production coverage (did each of the 8 ever get routed?):")
    L.append("")
    L.append("| Intent | Times produced |")
    L.append("| :-- | :--: |")
    for name in it["all_intents"]:
        c = it["produced"].get(name, 0)
        flag = "" if c else "  ⟵ never produced"
        L.append(f"| `{name}` | {c}{flag} |")
    L.append("")
    if it["misroutes"]:
        L.append("Misroutes:")
        L.append("")
        L.append("| Probe | Expected | Got |")
        L.append("| :-- | :-- | :-- |")
        for exp, got, pid in it["misroutes"]:
            L.append(f"| `{pid}` | {exp} | {got} |")
        L.append("")

    # Safety + Nonsense
    sf = rep["safety"]
    ns = rep["nonsense"]
    L.append("## 2. Safety gate & nonsense boundary")
    L.append("")
    # Safety recall figures deleted per the 2026-08-27 retraction manifest: the
    # probe corpus mirrors the lexicon it grades, so these percentages are
    # memorization, not recall. Safety recall is measured per-class against blind
    # corpora — see docs/architecture/SAFETY_ROUTE_TAXONOMY.md §10. The
    # missed/model-only diagnostics below are kept as findings.
    L.append("- (Safety recall over this mirror corpus is memorization, not recall — "
             "measured per-class against blind corpora; see SAFETY_ROUTE_TAXONOMY.md §10)")
    if sf["missed"]:
        L.append(f"- ⚠️ **MISSED entirely** (neither gate nor model): {sf['missed']}")
    if sf["model_only"]:
        L.append(f"- ⚠️ caught by model only, gate gap: {sf['model_only']}")
    L.append(f"- NONSENSE recall on mash/empty/symbols: **{pct(ns['recall'])}** over {ns['recall_n']}")
    if ns["false_trips"]:
        L.append(f"- ⚠️ **false NONSENSE trips on terse real answers**: {ns['false_trips']}")
    else:
        L.append(f"- terse real answers ({ns['false_trip_n']}) all passed through: ✅")
    L.append("")

    # Concept
    cn = rep["concept"]
    L.append("## 3. Concept resolution (full 108-catalog sweep)")
    L.append("")
    L.append(f"- Exact concept-id hit: **{cn['exact']}/{cn['n']} = {pct(cn['exact_rate'])}**")
    L.append(f"- Correct-chapter hit: **{cn['chapter']}/{cn['n']} = {pct(cn['chapter_rate'])}**")
    L.append(f"- Abstained (INHERIT / None): **{cn['abstain']}/{cn['n']} = {pct(cn['abstain_rate'])}**")
    L.append(f"- Distinct catalog concepts reached: **{cn['catalog_coverage']}/{cn['catalog_total']}** "
             f"→ directly tests the report's '79.6% zero-fire' reading (that was coverage, not capability).")
    L.append("")

    # Signals
    sg = rep["signal"]
    L.append("## 4. Cognitive signals — recall + calibration diagnosis")
    L.append("")
    L.append("`mean`/`max` = raw Gemini score when the signal *should* fire. The **verdict** "
             "separates the two failure modes the bias report could not: a signal that scores "
             "just under the line (**MISCALIBRATED** — a threshold fix helps) vs one the model "
             "barely scores at all (**GAP** — needs prompt/training work, not a threshold).")
    L.append("")
    L.append("| Signal | Expected | Fired | Recall | Mean score | Max | Verdict |")
    L.append("| :-- | :--: | :--: | :--: | :--: | :--: | :-- |")
    for row in sorted(sg["rows"], key=lambda r: (r["recall"], r["mean_score"])):
        L.append(f"| `{row['signal']}` | {row['expected']} | {row['fired']} | "
                 f"{pct(row['recall'])} | {row['mean_score']:.3f} | {row['max_score']:.3f} | {row['verdict']} |")
    L.append("")
    if sg["forbid_violations"]:
        L.append("### ⚠️ Forbidden-signal violations (rule 2b regression watch)")
        L.append("")
        L.append("| Probe | Fired (forbidden) | Score | Text |")
        L.append("| :-- | :-- | :--: | :-- |")
        for pid, s, v, txt in sg["forbid_violations"]:
            L.append(f"| `{pid}` | `{s}` | {v} | {txt} |")
        L.append("")
    else:
        L.append("_No forbidden-signal violations — positive acks did not read as confusion. ✅_")
        L.append("")

    # signal production coverage
    never = [s for s in sg["all_labels"] if s not in sg["produced"]]
    L.append(f"Signals that fired at least once across the suite: "
             f"**{len(sg['produced'])}/{len(sg['all_labels'])}**.")
    if never:
        L.append("")
        L.append(f"Never fired even when targeted: {', '.join('`'+s+'`' for s in never)}")
    L.append("")

    # Sweep
    L.append("## 5. Threshold sweep (should Rec 1 lower 0.50 → 0.35?)")
    L.append("")
    L.append("Micro recall/precision over the engineered signal probes. Use this to decide the "
             "trade, instead of guessing — precision is the cost of the recall gain.")
    L.append("")
    L.append("| Threshold | Recall | Precision | Total fires |")
    L.append("| :--: | :--: | :--: | :--: |")
    for s in rep["sweep"]:
        L.append(f"| {s['th']:.2f} | {pct(s['recall'])} | {pct(s['precision'])} | {s['fires']} |")
    L.append("")
    return "\n".join(L)


def print_summary(rep: dict) -> None:
    it, cn, sf, ns = rep["intent"], rep["concept"], rep["safety"], rep["nonsense"]
    print("\n================ STRESS SUMMARY ================")
    print(f"  intent accuracy    : {it['correct']}/{it['graded']} = {pct(it['acc'])}")
    print(f"  intents produced   : {len([k for k,v in it['produced'].items() if v])}/8")
    print(f"  safety gate recall : {pct(sf['gate_recall'])}  (any-path {pct(sf['recall'])})")
    print(f"  nonsense recall    : {pct(ns['recall'])}   false-trips: {len(ns['false_trips'])}")
    print(f"  concept chapter-hit: {pct(cn['chapter_rate'])}  exact {pct(cn['exact_rate'])}  "
          f"catalog {cn['catalog_coverage']}/{cn['catalog_total']}")
    weak = [r["signal"] for r in rep["signal"]["rows"] if "MISCALIBRATED" in r["verdict"]]
    gaps = [r["signal"] for r in rep["signal"]["rows"] if r["verdict"].startswith("GAP")]
    print(f"  signals miscalibr. : {weak}")
    print(f"  signals gap        : {gaps}")
    print(f"  forbid violations  : {len(rep['signal']['forbid_violations'])}")
    print("===============================================\n")


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Perception layer stress harness")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the plan, 0 calls (default)")
    mode.add_argument("--collect", action="store_true", help="run live front door (BILLED)")
    mode.add_argument("--replay", action="store_true", help="re-grade cached raw, 0 calls")
    ap.add_argument("--axis", default="", help="comma list to subset: intent,signal,concept,safety,nonsense,adversarial")
    ap.add_argument("--limit", type=int, default=0, help="cap number of probes (smoke test)")
    ap.add_argument("--device", default="cpu", help="MiniLM device for the cross-check embedder")
    ap.add_argument("--threshold", type=float, default=0.5, help="signal fire threshold for grading")
    ap.add_argument("--threshold-sweep", action="store_true", help="also print the sweep to stdout")
    args = ap.parse_args()

    enums = load_enums()
    axes = [a.strip() for a in args.axis.split(",") if a.strip()] or None
    suite = probes.build_suite(enums["concept_ids"], enums["concept_names"], axes=axes)
    if args.limit:
        suite = suite[: args.limit]
    stats = probes.suite_stats(suite)

    if args.replay:
        results = read_raw()
        rep = grade(results, enums, args.threshold)
        REPORT_PATH.write_text(render_report(rep, enums), encoding="utf-8")
        print_summary(rep)
        print(f"[stress] report -> {REPORT_PATH}")
        if args.threshold_sweep:
            for s in rep["sweep"]:
                print(f"  th={s['th']:.2f}  recall={pct(s['recall'])}  precision={pct(s['precision'])}")
        return

    if args.collect:
        billable = sum(1 for p in suite if p["axis"] not in ("safety", "nonsense")
                       or p["text"].strip() == "")  # rough; gate decides at runtime
        print(f"[stress] LIVE collect: {stats['total']} probes "
              f"(~{stats['total']} max Gemini calls; gate-only probes cost 0). BILLED.")
        results = run_live(suite, args.device, args.threshold)
        write_raw(results)
        rep = grade(results, enums, args.threshold)
        REPORT_PATH.write_text(render_report(rep, enums), encoding="utf-8")
        print_summary(rep)
        print(f"[stress] report -> {REPORT_PATH}")
        return

    # default: dry-run plan
    print("=== Perception stress suite — DRY RUN (no Gemini calls) ===")
    print(f"total probes: {stats['total']}")
    for ax in ("intent", "signal", "concept", "safety", "nonsense", "adversarial"):
        if ax in stats:
            print(f"  {ax:12s}: {stats[ax]}")
    print(f"\ntaxonomy coverage targets: {len(enums['intents'])} intents, "
          f"{len(enums['labels'])} signals, {len(enums['concept_ids'])} concepts")
    tgt = set()
    for p in suite:
        for s in p.get("expect_signals", []):
            tgt.add(s)
    missing = [s for s in enums["labels"] if s not in tgt]
    print(f"signals with >=1 targeted probe: {len(tgt)}/{len(enums['labels'])}")
    if missing:
        print(f"  (not directly targeted: {', '.join(missing)})")
    print("\nrun `--collect` to execute live (billed), then `--replay` to re-grade offline.")


if __name__ == "__main__":
    main()
