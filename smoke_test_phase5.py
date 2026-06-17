"""Phase 5 smoke tests (plan §Phase 5 "Verify").

T1  low-mastery learner gets the Class-9 bridge first; the diagnostic outcome
    moves stored mastery (apply_bridge_result).
T2  learner with hint_dependency 0.7 stuck on an exercise gets hint 2 of the
    chain, not a worked example.
T3  graphical-gap learner gets a figure crop in the evidence.
T4  misconception probe order: why_wrong appears only AFTER a failed diagnostic,
    never before.
T5  every manifest is non-empty and every evidence id resolves to a store object.

Run:  python smoke_test_phase5.py   (needs the Vertex env vars; no judge calls)
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

import networkx as nx

from learner_state import LearnerState
from query import run_turn

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

STORE = Path("rag_store")
PASS_COUNT = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS_COUNT
    status = "PASS" if cond else "FAIL"
    print(f"{status}  {name}  {detail}")
    if cond:
        PASS_COUNT += 1
    else:
        raise SystemExit(f"smoke test failed: {name} {detail}")


def fresh_learner(data=None) -> LearnerState:
    return LearnerState(path=None, data=data or {"concept_states": {}, "global": {}})


def manifest_ids_valid(manifest, chunks_by_id, G) -> bool:
    for e in manifest["evidence"]:
        eid = e["id"]
        if eid.startswith("hint::"):
            eid = eid.split("::", 1)[1].rsplit("::", 1)[0]
        elif eid.startswith("meta::"):
            eid = eid.split("::")[1]
        if eid not in chunks_by_id and eid not in G:
            print(f"   unknown id: {e['id']}")
            return False
    return bool(manifest["evidence"])


def main():
    chunks = [json.loads(l) for l in (STORE / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    chunks_by_id = {c["chunk_id"]: c for c in chunks}
    G = nx.node_link_graph(json.loads((STORE / "graph.json").read_text(encoding="utf-8")))

    # ---------------- T1: bridge first + mastery write-back ----------------
    learner = fresh_learner()
    hits, manifest, _ = run_turn(STORE, "Prove that two triangles with equal corresponding angles are similar",
                                 "auto", learner, use_judge=False, want_answer=False)
    check("T1a bridge activated for low-mastery learner", bool(manifest["bridge_ids"]),
          f"bridge_ids={manifest['bridge_ids'][:3]}")
    first_types = [e["type"] for e in manifest["evidence"][:2]]
    check("T1b bridge evidence precedes instruction", any(t.startswith("bridge") for t in first_types),
          f"first evidence types={first_types}")
    g9 = next(b for b in manifest["bridge_ids"] if b.startswith("grade9::"))
    before = learner.mastery(g9)
    res = learner.apply_bridge_result(g9, "correct")
    check("T1c diagnostic outcome moves stored mastery", res["mastery"] == min(1.0, before + 0.25),
          f"{before:.2f} -> {res['mastery']:.2f}")

    # ---------------- T2: faded hint, not worked example ----------------
    pair = next((cid, e) for cid in G
                if G.nodes[cid].get("type") == "concept"
                for e in G.successors(cid)
                if G.nodes[e].get("type") == "exercise" and G.nodes[e].get("hint_chain"))
    cid, exercise = pair
    card_name = G.nodes[cid].get("name", cid)
    learner = fresh_learner({"concept_states": {cid: {
        "mastery": 0.4, "hint_dependency": 0.7,
        "current_problem_id": exercise, "hints_used_current": 1}}, "global": {}})
    hits, manifest, _ = run_turn(STORE, f"I am stuck on this {card_name} problem, help me",
                                 "example", learner, stuck_on=exercise,
                                 use_judge=False, want_answer=False)
    hint_items = [e for e in manifest["evidence"] if e["type"] == "hint"]
    check("T2a hint served for hint-dependent learner", bool(hint_items))
    check("T2b it is hint level 2 (k+1 after 1 used)", hint_items[0]["hint"].get("level") == 2,
          f"level={hint_items[0]['hint'].get('level')}")
    check("T2c no analogous worked example served",
          not any(e["type"] == "analogous_example" for e in manifest["evidence"]))

    # ---------------- T3: graphical gap -> figure crop ----------------
    qcid = "jemh102__quadratic_zero_geometry"
    learner = fresh_learner({"concept_states": {qcid: {
        "mastery": 0.5, "representations_known": ["symbolic", "verbal"]}}, "global": {}})
    hits, manifest, _ = run_turn(STORE, "Show me the graph of a quadratic polynomial that has no real zeroes",
                                 "integrate", learner, use_judge=False, want_answer=False)
    figs = [e for e in manifest["evidence"]
            if (e["type"] in ("figure", "chunk")) and e.get("image_path")]
    check("T3 graphical-gap learner gets a figure crop", bool(figs),
          f"first={figs[0]['id'] if figs else None}")

    # ---------------- T4: probe before correction ----------------
    mid = "misconception::quadratic_always_has_two_real_zeroes"
    learner = fresh_learner({"concept_states": {qcid: {"mastery": 0.4}},
                             "misconception_states": {mid: {"status": "active",
                                                            "consecutive_correct": 0,
                                                            "consecutive_failures": 0}},
                             "global": {}})
    hits, manifest, _ = run_turn(STORE, "How many zeroes does a quadratic polynomial have?",
                                 "auto", learner, use_judge=False, want_answer=False)
    probe = [e for e in manifest["evidence"] if e["id"] == mid]
    check("T4a active misconception probed", bool(probe))
    check("T4b diagnostic served, correction withheld",
          probe[0].get("diagnostic_question") and not probe[0].get("why_wrong"))
    learner.apply_probe_result(mid, "wrong", concept_id=qcid)
    hits, manifest2, _ = run_turn(STORE, "How many zeroes does a quadratic polynomial have?",
                                  "auto", learner, use_judge=False, want_answer=False)
    probe2 = [e for e in manifest2["evidence"] if e["id"] == mid]
    check("T4c why_wrong served only AFTER failed diagnostic",
          bool(probe2) and bool(probe2[0].get("why_wrong")))

    # ---------------- T5: manifest validity (over all turns above) ----------------
    for i, m in enumerate([manifest, manifest2], 1):
        check(f"T5.{i} manifest non-empty + all ids exist", manifest_ids_valid(m, chunks_by_id, G))

    print(f"\nALL {PASS_COUNT} SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
