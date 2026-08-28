"""Behavioral state-trajectory eval for the Part 11 perception promotion
(PART11_PERCEPTION_EVAL_STATUS.md §5 fork #1 — the honest promotion arbiter).

WHY: the Stage 2 signal gate (label-reproduction F1 vs the heads) is won by the
heads by construction — they were trained on the dense gold (`curiosity` on 85%
of rows). What actually matters is the STATE MOVES a backend causes through the
deterministic math (`cognitive_analyzer.analyzer.derive_cognitive_update` ->
`derive_state_deltas` -> `apply_deltas`), which is unchanged across backends.

Two parts:

1. BEHAVIORAL PROBES (the gated arbiter, model-independent).
   ~50 authored utterances whose correct state move is unambiguous to a human
   ("can you give me a hint" MUST raise hint_requested; "the answer is 12" must
   fire NO flags). Both backends' signal scores run through the identical state
   math and are graded on:
     - expected target bands for the 4 global fields (high >=0.60 / low <=0.40 /
       mid 0.35-0.65), only on fields the utterance clearly speaks to;
     - must-fire flags and must-not-fire flags.
   Neither the dense gold nor the heads defines correctness here.

2. TEST REPLAY (descriptive evidence, offline/free, NOT gated).
   The 999 cached Gemini TEST predictions (perception_eval_raw.jsonl) + the
   heads scored locally + gold-as-binary, all pushed through the same state
   math: per-field target MAE, flag fire rates + agreement, and EMA
   pseudo-session terminal-state divergence. Not gated because grading state
   moves against gold-derived moves re-imports the density dispute.

ACCEPTANCE GATES (fixed BEFORE measurement; see _behavior_verdict):
   G1 field-direction accuracy: gemini >= 0.80 AND >= heads - 0.02
   G2 must-fire flag recall  : gemini >= 0.80 AND >= heads - 0.05
   G3 forbidden-flag rate    : gemini <= 0.05 AND <= heads + 0.02

Runs (PYTHONIOENCODING=utf-8 per CLAUDE.md):
    python -m eval.behavioral_eval --probes            # BILLED (~50 calls, resumable cache)
    python -m eval.behavioral_eval --replay            # offline (heads local + cached Gemini)
    python -m eval.behavioral_eval --run               # both -> eval/behavioral_eval_report.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cognitive_analyzer.analyzer import (  # noqa: E402 — the SAME math the runtime uses
    EMA,
    GLOBAL_FIELD_DEFAULTS,
    derive_cognitive_update,
    derive_state_deltas,
)

EVAL_DIR = ROOT / "eval"
RAW_EVAL = EVAL_DIR / "perception_eval_raw.jsonl"          # 999 cached Gemini TEST preds
BEHAVIOR_RAW = EVAL_DIR / "behavioral_eval_raw.jsonl"      # cached Gemini probe preds (resumable)
# --hardened: v2 caches collected AFTER the §5.5 concept hardening (prompt changed,
# so v1 predictions are not comparable and the caches must not be mixed).
RAW_EVAL_V2 = EVAL_DIR / "perception_eval_raw2.jsonl"
BEHAVIOR_RAW_V2 = EVAL_DIR / "behavioral_eval_raw2.jsonl"
DETAIL = EVAL_DIR / "behavioral_eval_detail.jsonl"         # per-probe grading audit trail
REPORT = EVAL_DIR / "behavioral_eval_report.md"

GLOBAL_FIELDS = ["confidence", "curiosity", "cognitive_load", "engagement"]
FLAGS = ["misconception_suspected", "transfer_ready_evidence", "hint_requested",
         "prerequisite_weakness_clue", "frustration_risk", "self_corrected"]
ALL = FLAGS  # shorthand for must_not on neutral probes

BANDS = {
    "high": lambda v: v >= 0.60,
    "low":  lambda v: v <= 0.40,
    "mid":  lambda v: 0.35 <= v <= 0.65,
}

SESSION_LEN = 12   # replay pseudo-session length for the EMA trajectory comparison

# --------------------------------------------------------------------------- #
# Behavioral probe set. Expectations authored from the UTTERANCE SEMANTICS and
# the documented state formulas — not tuned to either backend. Fields not
# clearly implied by the text are left ungraded.
# --------------------------------------------------------------------------- #
PROBES = [
    # --- confusion / cognitive load ---
    {"u": "i don't get it, this makes no sense to me",
     "fields": {"cognitive_load": "high"}, "must": [], "must_not": ["transfer_ready_evidence", "self_corrected"]},
    {"u": "wait i'm confused, where did the 4 come from",
     "fields": {"cognitive_load": "high"}, "must": [], "must_not": ["transfer_ready_evidence"]},
    {"u": "my brain hurts, there are way too many steps at once",
     "fields": {"cognitive_load": "high"}, "must": [], "must_not": []},
    {"u": "stop, that's too much information at once, i can't keep up",
     "fields": {"cognitive_load": "high"}, "must": [], "must_not": []},
    {"u": "can you say that again more slowly, it's a lot to take in",
     "fields": {"cognitive_load": "high"}, "must": [], "must_not": ["frustration_risk"]},
    # --- curiosity ---
    {"u": "whoa why does that trick always work? can we see more examples",
     "fields": {"curiosity": "high", "engagement": "high"}, "must": [], "must_not": ["frustration_risk"]},
    {"u": "that's so interesting, what happens if we use negative numbers instead",
     "fields": {"curiosity": "high", "engagement": "high"}, "must": [], "must_not": ["frustration_risk"]},
    {"u": "just tell me the steps so i can finish my homework",
     "fields": {"curiosity": "low"}, "must": [], "must_not": ["transfer_ready_evidence"]},
    # --- confidence up ---
    {"u": "i'm sure the answer is 42, i checked it twice",
     "fields": {"confidence": "high"}, "must": [], "must_not": ["frustration_risk", "hint_requested"]},
    {"u": "easy! the area is 24, i did it in my head",
     "fields": {"confidence": "high"}, "must": [], "must_not": ["frustration_risk", "hint_requested"]},
    # --- confidence down ---
    {"u": "i don't think i can do this one, it's too hard for me",
     "fields": {"confidence": "low"}, "must": [], "must_not": ["transfer_ready_evidence"]},
    {"u": "i'll probably get this wrong but maybe x is 5?",
     "fields": {"confidence": "low"}, "must": [], "must_not": []},
    {"u": "i'm so scared i'll fail the maths test tomorrow",
     "fields": {"confidence": "low"}, "must": [], "must_not": ["transfer_ready_evidence"]},
    {"u": "my heart races and i always freeze on word problems",
     "fields": {"confidence": "low"}, "must": [], "must_not": []},
    # --- misconception / recurring error ---
    {"u": "multiplying always makes numbers bigger, right?",
     "fields": {}, "must": ["misconception_suspected"], "must_not": []},
    {"u": "i divided by the smaller number because you always divide by the smaller one",
     "fields": {}, "must": ["misconception_suspected"], "must_not": []},
    {"u": "so a bigger denominator means a bigger fraction",
     "fields": {}, "must": ["misconception_suspected"], "must_not": []},
    {"u": "i keep making the same sign mistake every single time",
     "fields": {}, "must": ["misconception_suspected"], "must_not": []},
    {"u": "i got it wrong the same way again, i forgot the minus sign again",
     "fields": {}, "must": ["misconception_suspected"], "must_not": []},
    # --- transfer ---
    {"u": "this is just like the ratio problems we did with recipes, i can use the same idea here",
     "fields": {}, "must": ["transfer_ready_evidence"], "must_not": ["frustration_risk"]},
    {"u": "oh, so i can use the area formula from rectangles to figure out this garden problem",
     "fields": {}, "must": ["transfer_ready_evidence"], "must_not": ["frustration_risk"]},
    {"u": "i bet i can solve the next one using the distributive trick again",
     "fields": {"confidence": "high"}, "must": ["transfer_ready_evidence"], "must_not": []},
    # --- self-correction ---
    {"u": "oh wait, i made a mistake, it should be 15 not 12",
     "fields": {}, "must": ["self_corrected"], "must_not": []},
    {"u": "hold on, i forgot to carry the one. let me fix that, it's 132",
     "fields": {}, "must": ["self_corrected"], "must_not": []},
    {"u": "oh! i see it now, i was adding when i should have multiplied",
     "fields": {}, "must": ["self_corrected"], "must_not": []},
    # --- hint request ---
    {"u": "can you give me a hint please",
     "fields": {}, "must": ["hint_requested"], "must_not": []},
    {"u": "just a small clue, don't tell me the whole answer",
     "fields": {}, "must": ["hint_requested"], "must_not": []},
    # --- prerequisite weakness ---
    {"u": "i never really learned my times tables properly",
     "fields": {}, "must": ["prerequisite_weakness_clue"], "must_not": []},
    {"u": "i still don't know how to add fractions from last year",
     "fields": {}, "must": ["prerequisite_weakness_clue"], "must_not": []},
    # --- frustration ---
    {"u": "ugh i hate this, i've tried five times and it's still wrong!",
     "fields": {"engagement": "low"}, "must": ["frustration_risk"], "must_not": ["transfer_ready_evidence"]},
    {"u": "this is so annoying, nothing i do ever works",
     "fields": {}, "must": ["frustration_risk"], "must_not": []},
    # --- disengagement ---
    {"u": "whatever. can we just be done",
     "fields": {"engagement": "low"}, "must": [], "must_not": ["transfer_ready_evidence"]},
    {"u": "this is boring, i don't care about fractions",
     "fields": {"engagement": "low"}, "must": [], "must_not": ["transfer_ready_evidence"]},
    {"u": "i give up. just tell me the answer",
     "fields": {"engagement": "low"}, "must": [], "must_not": ["transfer_ready_evidence"]},
    # --- ready for next ---
    {"u": "that was easy, give me a harder one!",
     "fields": {"engagement": "high", "confidence": "high"}, "must": [], "must_not": ["frustration_risk", "hint_requested"]},
    {"u": "got it. what's next?",
     "fields": {"engagement": "high"}, "must": [], "must_not": ["frustration_risk"]},
    {"u": "can we do more of these puzzle ones? i love these",
     "fields": {"engagement": "high"}, "must": [], "must_not": ["frustration_risk"]},
    # --- neutral answer attempts: NO flags, mid confidence ---
    {"u": "the answer is 12",
     "fields": {"confidence": "mid"}, "must": [], "must_not": ALL},
    {"u": "x equals 7",
     "fields": {"confidence": "mid"}, "must": [], "must_not": ALL},
    {"u": "i think it's one half",
     "fields": {}, "must": [], "must_not": ["misconception_suspected", "hint_requested",
                                            "prerequisite_weakness_clue", "frustration_risk",
                                            "transfer_ready_evidence", "self_corrected"]},
    {"u": "the perimeter is 18 centimeters",
     "fields": {"confidence": "mid"}, "must": [], "must_not": ALL},
    # --- neutral learning questions: no distress flags ---
    {"u": "what is a prime number?",
     "fields": {}, "must": [], "must_not": ["misconception_suspected", "frustration_risk", "self_corrected"]},
    {"u": "how do i find the lcm of 4 and 6?",
     "fields": {}, "must": [], "must_not": ["misconception_suspected", "frustration_risk", "self_corrected"]},
    {"u": "thanks, that explanation made sense",
     "fields": {}, "must": [], "must_not": ["misconception_suspected", "frustration_risk", "hint_requested"]},
    {"u": "okay let's try the next question",
     "fields": {}, "must": [], "must_not": ["misconception_suspected", "frustration_risk"]},
    # --- mixed / harder cases ---
    {"u": "i tried the way you showed me on the new problem and i think it works, is that right?",
     "fields": {}, "must": ["transfer_ready_evidence"], "must_not": ["frustration_risk"]},
    {"u": "wait, is it always true that the angles add up to 180? even for really big triangles?",
     "fields": {}, "must": [], "must_not": ["frustration_risk", "self_corrected"]},
    {"u": "so the rule is you flip the second fraction and multiply, did i say it right?",
     "fields": {}, "must": [], "must_not": ["frustration_risk"]},
]


# --------------------------------------------------------------------------- #
# State move: the runtime path, verbatim math
# --------------------------------------------------------------------------- #
def state_move(scores: dict, signals: list[str]) -> dict:
    """scores+signals -> (global targets, flags) via the untouched runtime math.
    A dummy resolved concept is passed so concept_flags are not suppressed."""
    update = derive_cognitive_update(scores)
    deltas = derive_state_deltas(update, signals, {"concept_id": "_PROBE_"})
    return {"targets": deltas["global"], "flags": deltas["concept_flags"]}


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #
def _load_heads():
    # Ticket 11: InputProcessor deleted; normalization delegates to utterance_intake.
    from cognitive_classifier import ExemplarCognitiveClassifier
    return ExemplarCognitiveClassifier.load()


def heads_predict(clf, texts: list[str]) -> list[dict]:
    """Batch heads scoring exactly as the runtime consumes it: normalized text,
    calibrated per-label signal thresholds for the discrete signals list."""
    from cognitive_classifier.cues import cue_matrix
    from utterance_intake.intake import normalize_text
    norm = [normalize_text(t) for t in texts]
    mat = clf.score_matrix(clf.embed(norm), cue_matrix(norm))
    out = []
    for row in mat:
        scores = {lab: float(s) for lab, s in zip(clf.labels, row)}
        signals = [lab for lab, s in scores.items() if s >= clf.thresholds.get(lab, 0.5)]
        out.append({"scores": scores, "signals": signals})
    return out


def gemini_signals(pred: dict, threshold: float = 0.5) -> dict:
    """Cached Gemini prediction -> the runtime's classify() view (§ GeminiPerception)."""
    scores = {k: float(v) for k, v in (pred.get("signal_scores") or {}).items()}
    return {"scores": scores, "signals": [l for l, v in scores.items() if v >= threshold]}


def _load_behavior_cache() -> dict:
    if not BEHAVIOR_RAW.exists():
        return {}
    recs = [json.loads(l) for l in BEHAVIOR_RAW.read_text(encoding="utf-8").splitlines() if l.strip()]
    return {r["utterance"]: r["pred"] for r in recs}


def collect_probe_predictions() -> dict:
    """BILLED: one Gemini call per uncached probe utterance (resumable, same
    pattern as perception_eval --collect). Fallbacks are not cached -> retried."""
    from perception.gemini_perception import GeminiPerception

    cache = _load_behavior_cache()
    pending = [p["u"] for p in PROBES if p["u"] not in cache]
    print(f"probes: {len(pending)} Gemini calls to make ({len(cache)} cached)")
    if not pending:
        return {"new_calls": 0, "errors": 0}

    gp = GeminiPerception.load()
    n_new = errors = 0
    with open(BEHAVIOR_RAW, "a", encoding="utf-8") as f:
        for u in pending:
            r = gp.route(u, {})
            raw = r.raw or {}
            if raw.get("_source") != "gemini":
                errors += 1
                continue
            pred = {"intent": raw.get("intent"),
                    "signal_scores": {k: float(v) for k, v in (raw.get("signal_scores") or {}).items()}}
            f.write(json.dumps({"kind": "behavior", "utterance": u, "pred": pred},
                               ensure_ascii=False) + "\n")
            f.flush()
            n_new += 1
    return {"new_calls": n_new, "errors": errors}


# --------------------------------------------------------------------------- #
# Part 1 — probe grading (the gated arbiter)
# --------------------------------------------------------------------------- #
def grade_probes(moves_by_backend: dict[str, list[dict]]) -> dict:
    """moves_by_backend: backend -> list of state_move() dicts aligned with PROBES."""
    results = {}
    detail_rows = []
    for backend, moves in moves_by_backend.items():
        f_ok = f_tot = 0            # field-band expectations satisfied
        must_ok = must_tot = 0      # must-fire flags fired
        forb_bad = forb_tot = 0     # forbidden flags fired (violations)
        per_flag = {fl: {"must_ok": 0, "must_tot": 0, "false_fire": 0} for fl in FLAGS}
        for probe, mv in zip(PROBES, moves):
            fired = set(mv["flags"])
            row = {"backend": backend, "utterance": probe["u"],
                   "targets": {k: round(v, 3) for k, v in mv["targets"].items()},
                   "fired": sorted(fired), "field_miss": [], "must_miss": [], "false_fire": []}
            for field, band in probe["fields"].items():
                f_tot += 1
                if BANDS[band](mv["targets"][field]):
                    f_ok += 1
                else:
                    row["field_miss"].append(f"{field}={mv['targets'][field]:.2f} not {band}")
            for fl in probe["must"]:
                must_tot += 1
                per_flag[fl]["must_tot"] += 1
                if fl in fired:
                    must_ok += 1
                    per_flag[fl]["must_ok"] += 1
                else:
                    row["must_miss"].append(fl)
            for fl in probe["must_not"]:
                forb_tot += 1
                if fl in fired:
                    forb_bad += 1
                    per_flag[fl]["false_fire"] += 1
                    row["false_fire"].append(fl)
            detail_rows.append(row)
        results[backend] = {
            "field_acc": round(f_ok / f_tot, 4) if f_tot else None,
            "field_n": f_tot,
            "must_recall": round(must_ok / must_tot, 4) if must_tot else None,
            "must_n": must_tot,
            "forbidden_rate": round(forb_bad / forb_tot, 4) if forb_tot else None,
            "forbidden_n": forb_tot, "forbidden_violations": forb_bad,
            "per_flag": per_flag,
        }
    with open(DETAIL, "w", encoding="utf-8") as f:
        for row in detail_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return results


def _behavior_verdict(probe_results: dict) -> dict:
    """Acceptance gates — fixed before measurement (module docstring)."""
    g, h = probe_results["gemini"], probe_results["heads"]
    checks = {
        "G1_field_accuracy": g["field_acc"] >= 0.80 and g["field_acc"] >= h["field_acc"] - 0.02,
        "G2_must_fire_recall": g["must_recall"] >= 0.80 and g["must_recall"] >= h["must_recall"] - 0.05,
        "G3_forbidden_rate": g["forbidden_rate"] <= 0.05 and g["forbidden_rate"] <= h["forbidden_rate"] + 0.02,
    }
    return {"checks": checks, "pass": all(checks.values())}


# --------------------------------------------------------------------------- #
# Part 2 — TEST replay (descriptive, offline)
# --------------------------------------------------------------------------- #
def replay_test_rows(clf) -> dict:
    recs = [json.loads(l) for l in RAW_EVAL.read_text(encoding="utf-8").splitlines() if l.strip()]
    recs = [r for r in recs if r.get("kind") == "test" and r.get("pred")]
    if not recs:
        raise SystemExit(f"no cached TEST predictions in {RAW_EVAL.name}; run perception_eval --collect first.")

    texts = [r["utterance"] for r in recs]
    heads = heads_predict(clf, texts)
    moves = {"heads": [], "gemini": [], "gold": []}
    for r, h in zip(recs, heads):
        moves["heads"].append(state_move(h["scores"], h["signals"]))
        gz = gemini_signals(r["pred"])
        moves["gemini"].append(state_move(gz["scores"], gz["signals"]))
        gold = set(r["gold_signals"])
        moves["gold"].append(state_move({l: 1.0 for l in gold}, sorted(gold)))

    # per-field target MAE between sources
    def mae(a: str, b: str) -> dict:
        out = {}
        for f in GLOBAL_FIELDS:
            diffs = [abs(x["targets"][f] - y["targets"][f]) for x, y in zip(moves[a], moves[b])]
            out[f] = round(sum(diffs) / len(diffs), 4)
        return out

    # flag fire rates + pairwise agreement + P/R vs gold-derived flags (descriptive)
    n = len(recs)
    flag_stats = {}
    for fl in FLAGS:
        fire = {src: sum(1 for m in moves[src] if fl in m["flags"]) for src in moves}
        tp_h = sum(1 for h_, g_ in zip(moves["heads"], moves["gold"]) if fl in h_["flags"] and fl in g_["flags"])
        tp_g = sum(1 for x, g_ in zip(moves["gemini"], moves["gold"]) if fl in x["flags"] and fl in g_["flags"])
        agree = sum(1 for h_, x in zip(moves["heads"], moves["gemini"])
                    if (fl in h_["flags"]) == (fl in x["flags"]))
        def pr(tp, fires, golds):
            p = tp / fires if fires else None
            r = tp / golds if golds else None
            return p, r
        ph, rh = pr(tp_h, fire["heads"], fire["gold"])
        pg, rg = pr(tp_g, fire["gemini"], fire["gold"])
        flag_stats[fl] = {
            "fires": fire, "heads_vs_gemini_agreement": round(agree / n, 4),
            "heads_P_vs_goldmove": None if ph is None else round(ph, 3),
            "heads_R_vs_goldmove": None if rh is None else round(rh, 3),
            "gemini_P_vs_goldmove": None if pg is None else round(pg, 3),
            "gemini_R_vs_goldmove": None if rg is None else round(rg, 3),
        }

    # EMA pseudo-session terminal divergence
    def terminal_states(src: str) -> list[dict]:
        outs = []
        for i in range(0, n, SESSION_LEN):
            g = dict(GLOBAL_FIELD_DEFAULTS)
            for m in moves[src][i:i + SESSION_LEN]:
                for f in GLOBAL_FIELDS:
                    g[f] = (1.0 - EMA) * g[f] + EMA * m["targets"][f]
            outs.append(g)
        return outs

    term = {src: terminal_states(src) for src in moves}
    def term_mae(a: str, b: str) -> dict:
        out = {}
        for f in GLOBAL_FIELDS:
            diffs = [abs(x[f] - y[f]) for x, y in zip(term[a], term[b])]
            out[f] = round(sum(diffs) / len(diffs), 4)
        return out

    mean_targets = {src: {f: round(sum(m["targets"][f] for m in moves[src]) / n, 4)
                          for f in GLOBAL_FIELDS} for src in moves}
    return {
        "n_rows": n, "n_sessions": len(term["gold"]), "session_len": SESSION_LEN,
        "mean_targets": mean_targets,
        "target_mae": {"heads_vs_gold": mae("heads", "gold"),
                       "gemini_vs_gold": mae("gemini", "gold"),
                       "heads_vs_gemini": mae("heads", "gemini")},
        "terminal_mae": {"heads_vs_gold": term_mae("heads", "gold"),
                         "gemini_vs_gold": term_mae("gemini", "gold"),
                         "heads_vs_gemini": term_mae("heads", "gemini")},
        "flags": flag_stats,
    }


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def _fmt(x):
    return "—" if x is None else (f"{x:.4f}" if isinstance(x, float) else str(x))


def write_report(probe_results: dict, verdict: dict, replay: dict | None,
                 probe_errors: int) -> None:
    g, h = probe_results["gemini"], probe_results["heads"]
    ch = verdict["checks"]
    lines = [
        "# Behavioral state-trajectory eval (Part 11 promotion arbiter)",
        "",
        f"> **Measured {time.strftime('%Y-%m-%d')}.** Both backends' signal outputs pushed through "
        "the UNCHANGED runtime state math (`derive_cognitive_update` → `derive_state_deltas`), "
        "graded on the state moves they cause — not on label-reproduction F1 "
        "(see the honest note in `perception_eval_report.md`). "
        f"{len(PROBES)} authored behavioral probes (gated) + {replay['n_rows'] if replay else 0} "
        "TEST-row replay (descriptive). CLAUDE.md: numbers are measured, not hand-edited.",
        "",
        f"## Behavioral verdict: **{'PASS' if verdict['pass'] else 'FAIL'}**",
        "",
        "Gates fixed before measurement:",
        "",
        "| Gate | Gemini | Heads | Rule | Verdict |",
        "|---|---|---|---|---|",
        f"| G1 field-direction accuracy (n={g['field_n']}) | {_fmt(g['field_acc'])} | {_fmt(h['field_acc'])} | "
        f"≥0.80 and ≥heads−0.02 | {'PASS' if ch['G1_field_accuracy'] else 'FAIL'} |",
        f"| G2 must-fire flag recall (n={g['must_n']}) | {_fmt(g['must_recall'])} | {_fmt(h['must_recall'])} | "
        f"≥0.80 and ≥heads−0.05 | {'PASS' if ch['G2_must_fire_recall'] else 'FAIL'} |",
        f"| G3 forbidden-flag rate (n={g['forbidden_n']}) | {_fmt(g['forbidden_rate'])} | {_fmt(h['forbidden_rate'])} | "
        f"≤0.05 and ≤heads+0.02 | {'PASS' if ch['G3_forbidden_rate'] else 'FAIL'} |",
        "",
        f"Probe collection errors (Gemini fallbacks, uncached/retryable): {probe_errors}",
        "",
        "### Per-flag probe results (must-fire hits / probes; false fires on forbidden probes)",
        "",
        "| Flag | Gemini must | Heads must | Gemini false | Heads false |",
        "|---|---|---|---|---|",
    ]
    for fl in FLAGS:
        pg, ph = g["per_flag"][fl], h["per_flag"][fl]
        lines.append(f"| {fl} | {pg['must_ok']}/{pg['must_tot']} | {ph['must_ok']}/{ph['must_tot']} | "
                     f"{pg['false_fire']} | {ph['false_fire']} |")
    lines += [
        "",
        f"Per-probe audit trail: `{DETAIL.name}` (targets, fired flags, misses per backend).",
    ]

    if replay:
        lines += [
            "",
            "## TEST replay — descriptive evidence (NOT gated)",
            "",
            f"All {replay['n_rows']} cached TEST rows replayed through the state math under three "
            "signal sources (heads local, Gemini cached, gold-as-binary). Gold-derived moves are "
            "shown for context only — grading against them would re-import the dense-gold dispute.",
            "",
            "### Mean per-turn global targets",
            "",
            "| Field | Heads | Gemini | Gold |",
            "|---|---|---|---|",
        ]
        mt = replay["mean_targets"]
        for f in GLOBAL_FIELDS:
            lines.append(f"| {f} | {_fmt(mt['heads'][f])} | {_fmt(mt['gemini'][f])} | {_fmt(mt['gold'][f])} |")
        lines += [
            "",
            "### Per-turn target MAE / EMA pseudo-session terminal MAE "
            f"({replay['n_sessions']} sessions × {replay['session_len']} turns)",
            "",
            "| Field | heads↔gemini turn | heads↔gold turn | gemini↔gold turn | heads↔gemini terminal | gemini↔gold terminal |",
            "|---|---|---|---|---|---|",
        ]
        tm, xm = replay["target_mae"], replay["terminal_mae"]
        for f in GLOBAL_FIELDS:
            lines.append(f"| {f} | {_fmt(tm['heads_vs_gemini'][f])} | {_fmt(tm['heads_vs_gold'][f])} | "
                         f"{_fmt(tm['gemini_vs_gold'][f])} | {_fmt(xm['heads_vs_gemini'][f])} | "
                         f"{_fmt(xm['gemini_vs_gold'][f])} |")
        lines += [
            "",
            "### Flag firing on real TEST rows",
            "",
            "| Flag | Heads fires | Gemini fires | Gold-move fires | H↔G agree | Heads P/R vs gold-move | Gemini P/R vs gold-move |",
            "|---|---|---|---|---|---|---|",
        ]
        for fl, st in replay["flags"].items():
            fr = st["fires"]
            lines.append(f"| {fl} | {fr['heads']} | {fr['gemini']} | {fr['gold']} | "
                         f"{_fmt(st['heads_vs_gemini_agreement'])} | "
                         f"{_fmt(st['heads_P_vs_goldmove'])} / {_fmt(st['heads_R_vs_goldmove'])} | "
                         f"{_fmt(st['gemini_P_vs_goldmove'])} / {_fmt(st['gemini_R_vs_goldmove'])} |")

    lines += [
        "",
        "## Reproduce",
        "```powershell",
        'cd "D:\\cloud CLI"',
        '$env:PYTHONIOENCODING="utf-8"',
        "python -m eval.behavioral_eval --probes   # BILLED (~50 calls, resumable cache)",
        "python -m eval.behavioral_eval --replay   # offline",
        "python -m eval.behavioral_eval --run      # both -> this report",
        "```",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {REPORT}")


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Behavioral state-trajectory eval (Part 11)")
    ap.add_argument("--probes", action="store_true", help="BILLED: collect Gemini probe preds + grade probes")
    ap.add_argument("--replay", action="store_true", help="offline TEST replay (heads local + cached Gemini)")
    ap.add_argument("--run", action="store_true", help="probes + replay -> report")
    ap.add_argument("--hardened", action="store_true",
                    help="use the post-§5.5-hardening v2 caches (raw2 files)")
    args = ap.parse_args()
    if not (args.probes or args.replay or args.run):
        ap.print_help()
        return
    if args.hardened:
        global RAW_EVAL, BEHAVIOR_RAW
        RAW_EVAL = RAW_EVAL_V2
        BEHAVIOR_RAW = BEHAVIOR_RAW_V2

    clf = proc = None
    probe_results = verdict = None
    replay = None
    probe_errors = 0

    if args.probes or args.run:
        stats = collect_probe_predictions()
        probe_errors = stats["errors"]
        print(f"probe collection: {stats}")
        cache = _load_behavior_cache()
        missing = [p["u"] for p in PROBES if p["u"] not in cache]
        if missing:
            raise SystemExit(f"{len(missing)} probes still uncached (Gemini fallbacks) — rerun --probes: {missing[:3]}")
        clf = _load_heads()
        heads = heads_predict(clf, [p["u"] for p in PROBES])
        moves = {
            "heads": [state_move(h["scores"], h["signals"]) for h in heads],
            "gemini": [],
        }
        for p in PROBES:
            gz = gemini_signals(cache[p["u"]])
            moves["gemini"].append(state_move(gz["scores"], gz["signals"]))
        probe_results = grade_probes(moves)
        verdict = _behavior_verdict(probe_results)
        print(json.dumps({"probes": {b: {k: v for k, v in r.items() if k != "per_flag"}
                                     for b, r in probe_results.items()},
                          "verdict": verdict}, indent=2))

    if args.replay or args.run:
        if clf is None:
            clf = _load_heads()
        replay = replay_test_rows(clf)
        print(json.dumps({k: v for k, v in replay.items() if k != "flags"}, indent=2))

    if probe_results is not None:
        write_report(probe_results, verdict, replay, probe_errors)


if __name__ == "__main__":
    main()
    # google-genai gRPC C-core segfaults at interpreter shutdown on Windows (exit 139)
    # AFTER all work is done — cosmetic, but it makes a completed run report "failed"
    # (see PART11_PERCEPTION_EVAL_STATUS.md §6). Flush and exit hard.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
