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


def tutor_loop_guard_checks():
    """Regression for the 2026-06-20 tutor_loop fixes (build-plan Part 7 v5):
    non-attempt grading guard, clarification routing (rule 1b), ct_probe is
    HOPE-only (never graded as a misconception), and the T9 display channel.

    The two Qwen calls are monkeypatched so this needs no llama.cpp server and is
    deterministic; everything else (analyzer, retrieval, state machine) runs for real.
    """
    import tutor_loop
    from tutor_loop import TutorLoop

    judge_calls = []
    tutor_loop.judge_answer = lambda q, e, a: (judge_calls.append(a) or "wrong")
    tutor_loop.qwen_answer = lambda *a, **k: "(stub answer)"

    QCID = "jemh102__quadratic_zero_geometry"
    MID = "misconception::quadratic_always_has_two_real_zeroes"

    print("\n--- tutor_loop grading/display guards (T6-T9) ---")
    loop = TutorLoop(state_path=None, want_answer=True, use_judge=False)  # one heavy load, reused

    def armed_misconception_state(mastery=0.5):
        return {
            "concept_states": {QCID: {"mastery": mastery}},
            "misconception_states": {MID: {"status": "active", "consecutive_correct": 0,
                                           "consecutive_failures": 0}},
            "session": {"current_concept": QCID, "pending_check": {
                "kind": "misconception", "id": MID, "concept_id": QCID,
                "question": "How many zeroes can a quadratic polynomial have?",
                "expected_answer": "0, 1, or 2 real zeroes.", "hint_chain": None}},
            "global": {},
        }

    # T6: a non-attempt (confusion plea) must NOT be graded or move mastery.
    loop.state.data = armed_misconception_state()
    judge_calls.clear()
    before = loop.state.mastery(QCID)
    res = loop.turn("what did you mean by this, i can not understand")
    check("T6a non-attempt not graded (no judge, no writeback)",
          res.get("writeback") is None and not judge_calls)
    check("T6b non-attempt holds mastery", loop.state.mastery(QCID) == before,
          f"{before:.2f} -> {loop.state.mastery(QCID):.2f}")
    check("T6c non-attempt routes to EXPLAIN (rule 1b)", res["action"] == "EXPLAIN",
          f"action={res['action']}")

    # T7: a genuine answer attempt IS still graded (guard does not over-block).
    loop.state.data = armed_misconception_state()
    judge_calls.clear()
    res = loop.turn("i think the answer is it can have zero, one or two real zeroes")
    check("T7 real answer still graded", res.get("writeback") is not None and bool(judge_calls),
          f"judge_called={bool(judge_calls)}")

    # T8: a ct_probe must be HOPE-armed, never armed as a graded misconception.
    loop.state.data = {"concept_states": {QCID: {"mastery": 0.5}}, "misconception_states": {},
                       "session": {"current_concept": QCID}, "global": {}}
    analysis = {
        "raw_text": "give me a challenge", "normalized_text": "give me a challenge",
        "signals": ["curiosity"], "signal_scores": {},
        "concept": {"concept_id": QCID, "concept_confidence": 0.8, "abstained": False,
                    "secondary_concepts": []},
        "cognitive_update": {"confusion": 0.2, "curiosity": 0.7, "confidence": 0.5,
            "misconception_probability": 0.1, "transfer_attempt": 0.1, "abstraction_attempt": 0.1,
            "self_correction": 0.1, "cognitive_load": 0.2, "engagement": 0.6, "frustration_risk": 0.1},
        "state_deltas": {"global": {"confidence": 0.5, "curiosity": 0.7, "cognitive_load": 0.2,
                                    "engagement": 0.6}, "concept_id": QCID, "concept_flags": []},
    }
    res = loop.turn("give me a challenge", precomputed_analysis=analysis)
    pc_id = str((loop.state.data["session"].get("pending_check") or {}).get("id") or "")
    check("T8a Socratic turn served", res["action"] == "SOCRATIC_Q", f"action={res['action']}")
    check("T8b ct_probe HOPE-armed (CT)", res["pending_hope"] == "CT")
    check("T8c ct_probe NOT armed as a graded diagnostic", not pc_id.startswith("ct_probe"),
          f"pending_check={pc_id}")
    check("T8d no bogus ct_probe in misconception_states",
          not any(k.startswith("ct_probe") for k in loop.state.misconception_states))

    # T9: display channel surfaces ONE crop for a representation gap; audio-only otherwise.
    loop.state.data = {"concept_states": {QCID: {"mastery": 0.5,
                       "representations_known": ["symbolic", "verbal"]}}, "misconception_states": {},
                       "session": {"current_concept": QCID}, "global": {}}
    res = loop.turn("show me the graph of a quadratic with no real zeroes, i only think in equations")
    disp = res.get("display") or []
    check("T9a graphical-gap turn shows one crop",
          len(disp) == 1 and bool(disp[0].get("image_path")),
          f"display={[d.get('image_path') for d in disp]}")
    check("T9b crop file exists on disk", bool(disp) and (STORE / disp[0]["image_path"]).exists())
    # v5.1 (2026-07-20): plain teaching turns now carry a tier-3 teaching visual by
    # default (build plan Part 7 v5.1) — the audio-only guarantee moved to non-teaching
    # turns (TEST / mode-driven items), asserted directly on _build_display.
    loop.state.data = {"concept_states": {}, "misconception_states": {}, "session": {}, "global": {}}
    res = loop.turn("what is the quadratic formula")
    disp = res.get("display") or []
    check("T9c teaching turn carries at most ONE display item (tier-3 v5.1)",
          len(disp) <= 1, f"display={[d.get('image_path') for d in disp]}")
    check("T9c2 tier-3 crop (when shown) exists on disk",
          not disp or (STORE / disp[0]["image_path"]).exists())
    check("T9d non-teaching turn stays audio-only",
          loop._build_display([], "EXPLAIN", teaching=False) == []
          and loop._build_display([], "QUIZ", teaching=True, ranked=[],
                                  primary_concept=None) == [])


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

    # T6-T9: tutor_loop grading/routing/display guards (2026-06-20 regressions)
    tutor_loop_guard_checks()

    print(f"\nALL {PASS_COUNT} SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
