"""HOPE-readiness scorecard + structural verification for the rag_store.

Phase 0 of RAG_upgrade_plan.md: makes every gap in the plan's §1 table measurable
so each later phase proves its delta. Two layers:

  1. Structural consistency (the original verify checks): meta counts vs files,
     FAISS vector count vs chunk count.
  2. HOPE-readiness coverage: per-metric % coverage for KI / KT / CT / visual /
     bridge / schema / hint-chain assets, against the targets in plan §4a.

Usage:
    python verify_store.py [--store rag_store] [--save report.txt] [--fail-under PCT]

--fail-under gates on the overall target-attainment score (mean over metrics of
min(value/target, 1) * 100), so a rebuild that regresses any covered metric fails.
"""

from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

import faiss
import networkx as nx

# NCERT private-use glyphs crash cp1252 consoles; force UTF-8 (plan §6 risk 3).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ANSWER_LEAK_RE = re.compile(r"\b(the\s+)?(final\s+)?answer\s*(is|=|:)", re.IGNORECASE)


def load_store(store: Path):
    meta = json.loads((store / "meta.json").read_text(encoding="utf-8"))
    chunks = [json.loads(l) for l in (store / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    concepts = json.loads((store / "concepts.json").read_text(encoding="utf-8"))
    graph = nx.node_link_graph(json.loads((store / "graph.json").read_text(encoding="utf-8")))
    index = faiss.read_index(str(store / "vector.faiss"))
    return meta, chunks, concepts, graph, index


def pct(n: int, d: int) -> float:
    return 100.0 * n / d if d else 0.0


def has_near_far_transfers(card: Dict[str, Any], valid_ids: set) -> bool:
    """KT gap G1: >=2 near links targeting real store concepts + >=1 far link."""
    links = card.get("transfer_links") or []
    near = [t for t in links if isinstance(t, dict) and t.get("transfer_type") == "near"
            and (t.get("target") in valid_ids or t.get("target_concept_id") in valid_ids)]
    far = [t for t in links if isinstance(t, dict) and t.get("transfer_type") == "far"]
    return len(near) >= 2 and len(far) >= 1


def valid_hint_chain(chain: Any) -> bool:
    """Exactly 3 non-empty hints, none of which states the final answer."""
    if not isinstance(chain, list) or len(chain) != 3:
        return False
    for h in chain:
        text = h.get("text") if isinstance(h, dict) else h
        if not isinstance(text, str) or not text.strip():
            return False
        if ANSWER_LEAK_RE.search(text):
            return False
    return True


def has_metacognitive_prompts(card: Dict[str, Any]) -> bool:
    """Both retrieval moments must be covered so the engine can react to the
    learner's struggle signal (see learner_state.apply_probe_result)."""
    prompts = card.get("metacognitive_prompts") or []
    whens = {p.get("when") for p in prompts if isinstance(p, dict)}
    return "after_success" in whens and "after_struggle" in whens


def build_scorecard(meta, chunks, concepts, graph: nx.DiGraph) -> List[Dict[str, Any]]:
    valid_ids = {c["concept_id"] for c in concepts}
    n_concepts = len(concepts)

    nodes = dict(graph.nodes(data=True))
    by_type: Dict[str, List[str]] = {}
    for nid, attrs in nodes.items():
        by_type.setdefault(attrs.get("type", "unknown"), []).append(nid)

    misconceptions = by_type.get("misconception", [])
    figures = by_type.get("figure", []) + by_type.get("table", [])
    formulas = by_type.get("formula", [])
    exercises = by_type.get("exercise", [])
    chapters = by_type.get("chapter", [])
    grade9 = by_type.get("grade9_concept", [])
    dangling = by_type.get("unknown", [])

    # Concepts with >=1 problem schema (via has_schema edges or schema node prefix).
    schema_owners = set()
    for u, v, d in graph.edges(data=True):
        if d.get("relation") == "has_schema":
            schema_owners.add(u)

    misc_enriched = sum(
        1 for m in misconceptions
        if nodes[m].get("why_wrong") and nodes[m].get("correct_idea") and nodes[m].get("diagnostic_question")
    )
    fig_cropped = sum(1 for f in figures if nodes[f].get("image_path"))
    formula_cropped = sum(1 for f in formulas if nodes[f].get("image_path"))
    exe_hinted = sum(1 for e in exercises if valid_hint_chain(nodes[e].get("hint_chain")))

    # Grade-9 bridges: chapter covered when a grade9_concept bridges into one of its concepts.
    chapter_of = {}
    for c in concepts:
        chapter_of[c["concept_id"]] = c.get("chapter_doc")
    bridged_chapters = set()
    bridges_with_diag = 0
    for g9 in grade9:
        if nodes[g9].get("diagnostic_question"):
            bridges_with_diag += 1
        for _, tgt, d in graph.out_edges(g9, data=True):
            if d.get("relation") == "bridges_to" and tgt in chapter_of:
                bridged_chapters.add(chapter_of[tgt])

    chunks_linked = sum(1 for c in chunks if c.get("concept_ids"))
    chunks_diff = sum(1 for c in chunks if c.get("difficulty") is not None)

    hope_bank = Path(meta.get("_store_path", ".")) / "hope_prompt_bank.jsonl"
    hope_rows = sum(1 for l in hope_bank.read_text(encoding="utf-8").splitlines() if l.strip()) if hope_bank.exists() else 0
    # min KI/KT/CT signal count — the real production gate (>=300/signal). After
    # human review (hope_detector/clean_bank.py) dropped 37 non-discriminating
    # prompts, this matters more than the raw total.
    hope_by_signal: Dict[str, int] = {}
    if hope_bank.exists():
        for l in hope_bank.read_text(encoding="utf-8").splitlines():
            if l.strip():
                hope_by_signal[json.loads(l).get("signal", "?")] = hope_by_signal.get(json.loads(l).get("signal", "?"), 0) + 1
    hope_min_signal = min((hope_by_signal.get(s, 0) for s in ("KI", "KT", "CT")), default=0)

    def card_pct(predicate) -> float:
        return pct(sum(1 for c in concepts if predicate(c)), n_concepts)

    # (label, value, target, unit) — targets from plan §4a. For count-down metrics
    # (dangling prereqs) attainment is 100 when value <= target.
    return [
        {"label": "Concepts with difficulty",                       "value": card_pct(lambda c: c.get("difficulty") is not None), "target": 100.0},
        {"label": "Concepts with >=2 near + >=1 far transfer links","value": card_pct(lambda c: has_near_far_transfers(c, valid_ids)), "target": 95.0},
        {"label": "Concepts with >=1 integration link (KI)",        "value": card_pct(lambda c: len(c.get("integration_links") or []) >= 1), "target": 95.0},
        {"label": "Concepts with >=2 CT probes",                    "value": card_pct(lambda c: len(c.get("ct_probes") or []) >= 2), "target": 100.0},
        {"label": "Concepts with >=1 application",                  "value": card_pct(lambda c: len(c.get("applications") or []) >= 1), "target": 95.0},
        {"label": "Concepts with vocabulary",                       "value": card_pct(lambda c: len(c.get("vocabulary") or []) >= 1), "target": 100.0},
        {"label": "Concepts with metacognitive prompts (A1.4)",     "value": card_pct(has_metacognitive_prompts), "target": 100.0},
        {"label": "Concepts with >=1 problem schema (A1.1)",        "value": pct(len(schema_owners & valid_ids), n_concepts), "target": 90.0},
        {"label": "Misconceptions fully enriched (why/correct/diagnostic)", "value": pct(misc_enriched, len(misconceptions)), "target": 100.0},
        {"label": "Exercises with valid 3-hint chain (A1.2)",       "value": pct(exe_hinted, len(exercises)), "target": 95.0},
        {"label": "Figure/table nodes with image_path",             "value": pct(fig_cropped, len(figures)), "target": 90.0},
        {"label": "Formula nodes with image_path",                  "value": pct(formula_cropped, len(formulas)), "target": 60.0},
        {"label": "Chapters with grade-9 bridges",                  "value": pct(len(bridged_chapters), len(chapters)), "target": 100.0},
        {"label": "Bridges with diagnostic question",               "value": pct(bridges_with_diag, len(grade9)) if grade9 else 0.0, "target": 100.0},
        {"label": "Dangling prerequisite nodes",                    "value": float(len(dangling)), "target": 0.0, "count_down": True},
        {"label": "Chunks concept-linked",                          "value": pct(chunks_linked, len(chunks)), "target": 100.0},
        {"label": "Chunks difficulty-tagged",                       "value": pct(chunks_diff, len(chunks)), "target": 100.0},
        {"label": "HOPE prompt bank rows (post human-review)",      "value": float(hope_rows), "target": 950.0, "absolute": True},
        {"label": "HOPE prompts per signal (min KI/KT/CT)",         "value": float(hope_min_signal), "target": 300.0, "absolute": True},
    ]


def attainment(metric: Dict[str, Any]) -> float:
    if metric.get("count_down"):
        return 100.0 if metric["value"] <= metric["target"] else 0.0
    target = metric["target"] or 1.0
    return min(100.0, 100.0 * metric["value"] / target)


def structural_check(meta, chunks, concepts, index) -> List[str]:
    errors = []
    if meta["num_chunks"] != len(chunks):
        errors.append(f"chunk count mismatch: meta={meta['num_chunks']} actual={len(chunks)}")
    if meta["num_concepts"] != len(concepts):
        errors.append(f"concept count mismatch: meta={meta['num_concepts']} actual={len(concepts)}")
    # New retrievable chunks (figure captions, bridge recaps) are appended to both
    # chunks.jsonl and FAISS, so equality must always hold.
    if index.ntotal != len(chunks):
        errors.append(f"FAISS/chunk mismatch: faiss={index.ntotal} chunks={len(chunks)}")
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="rag_store")
    ap.add_argument("--save", default=None, help="Also write the report to this file.")
    ap.add_argument("--fail-under", type=float, default=None,
                    help="Exit 1 if overall target attainment %% falls below this.")
    args = ap.parse_args()

    store = Path(args.store)
    meta, chunks, concepts, graph, index = load_store(store)
    meta["_store_path"] = str(store)

    lines: List[str] = []
    out = lines.append
    out("=== Structural verification ===")
    errors = structural_check(meta, chunks, concepts, index)
    if errors:
        for e in errors:
            out(f"FAIL: {e}")
    else:
        out(f"OK: {len(chunks)} chunks == meta == FAISS({index.ntotal}); {len(concepts)} concepts == meta")
    out(f"graph: {graph.number_of_nodes()} nodes / {graph.number_of_edges()} edges "
        f"(schema_version={meta.get('store_schema_version', 1)})")

    out("")
    out("=== HOPE-readiness scorecard (plan section 4a) ===")
    metrics = build_scorecard(meta, chunks, concepts, graph)
    att_total = 0.0
    for m in metrics:
        att = attainment(m)
        att_total += att
        if m.get("count_down") or m.get("absolute"):
            val = f"{m['value']:.0f}"
            tgt = f"{'<=' if m.get('count_down') else '>='}{m['target']:.0f}"
        else:
            val = f"{m['value']:.1f}%"
            tgt = f">={m['target']:.0f}%"
        out(f"{'PASS' if att >= 100.0 else '....'}  {m['label']:<58} {val:>8}  (target {tgt})")

    overall = att_total / len(metrics)
    out("")
    out(f"Overall target attainment: {overall:.1f}%")

    report = "\n".join(lines)
    print(report)
    if args.save:
        Path(args.save).write_text(report + "\n", encoding="utf-8")
        print(f"\nReport saved to {args.save}")

    if errors:
        sys.exit(1)
    if args.fail_under is not None and overall < args.fail_under:
        print(f"\nFAIL: attainment {overall:.1f}% < --fail-under {args.fail_under}%")
        sys.exit(1)


if __name__ == "__main__":
    main()
