"""Eval harness for Phase 0 + Phase 1 of RAG_upgrade_plan.md.

Verifies every "done" claim with executable checks, READ-ONLY against the live
rag_store (safe to run while enrich_concepts.py is still enriching — that
pipeline only writes the store in its final `write` stage). Synthetic stores
and learner-state files go to a temp dir.

Sections:
  A  Phase 0 — verify_store.py scorecard: 18 metrics, baseline reproducibility,
     --fail-under gate exit codes, structural tamper detection, helper units.
  B  Phase 1 — learner_state.py: struggle thresholds, section-10 status machine,
     mastery write-back/clamping, hint EMA + per-problem reset, persistence.
  C  Phase 1 — enrich_concepts.repair_dangling_edges: synthetic unit test +
     in-memory repair of the live graph (expects the claimed 184 re-points and
     concept->example/exercise reachability going from 0 to >0).
  D  Phase 1 (in flight) — concept_enrich_cache.jsonl: every cached concept
     payload re-validated against the hard Phase-1 rules; per-stage progress.

Usage:  python eval_phase01.py [--store rag_store] [--report eval_phase01_report.md]
Exit 1 if any check fails.
"""

from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

import faiss
import networkx as nx

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import verify_store as vs
import learner_state as ls
import enrich_concepts as ec

RESULTS: list[dict] = []


def check(section: str, name: str, fn):
    try:
        detail = fn()
        RESULTS.append({"section": section, "name": name, "ok": True,
                        "detail": detail if isinstance(detail, str) else ""})
    except Exception as e:
        tb = traceback.format_exc(limit=2)
        RESULTS.append({"section": section, "name": name, "ok": False,
                        "detail": f"{e.__class__.__name__}: {e} | {tb.splitlines()[-2].strip()}"})


# ===========================================================================
# Section A — Phase 0 scorecard
# ===========================================================================
def run_verify(store: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HERE / "verify_store.py"), "--store", str(store), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(HERE),
    )

METRIC_LINE_RE = re.compile(r"^(PASS|\.\.\.\.)\s{2}")
OVERALL_RE = re.compile(r"Overall target attainment: ([\d.]+)%")


def section_a(store: Path, tmp: Path):
    live = run_verify(store)

    def a1():
        assert live.returncode == 0, f"exit {live.returncode}: {live.stderr[-300:]}"
        metric_lines = [l for l in live.stdout.splitlines() if METRIC_LINE_RE.match(l)]
        assert len(metric_lines) == 18, f"expected 18 metric lines, got {len(metric_lines)}"
        m = OVERALL_RE.search(live.stdout)
        assert m, "no overall attainment line"
        assert "OK:" in live.stdout, "structural check did not pass on live store"
        return f"18 metrics, overall {m.group(1)}%, structural OK"
    check("A", "scorecard runs: 18 metrics + overall + structural OK", a1)

    def a2():
        baseline = (store / "scorecard_baseline.txt").read_text(encoding="utf-8")
        base_metrics = [l for l in baseline.splitlines() if METRIC_LINE_RE.match(l)]
        live_metrics = [l for l in live.stdout.splitlines() if METRIC_LINE_RE.match(l)]
        diffs = [f"{b!r} -> {l!r}" for b, l in zip(base_metrics, live_metrics) if b != l]
        assert not diffs, f"{len(diffs)} metric lines differ from baseline: {diffs[:3]}"
        bo, lo = OVERALL_RE.search(baseline), OVERALL_RE.search(live.stdout)
        assert bo.group(1) == lo.group(1), f"overall {bo.group(1)} vs {lo.group(1)}"
        return f"reproduces baseline exactly (overall {lo.group(1)}%) — deterministic"
    check("A", "baseline reproducibility (store unchanged until write-back)", a2)

    def a3():
        hi = run_verify(store, "--fail-under", "99")
        assert hi.returncode == 1, f"--fail-under 99 should exit 1, got {hi.returncode}"
        assert "FAIL: attainment" in hi.stdout
        lo = run_verify(store, "--fail-under", "5")
        assert lo.returncode == 0, f"--fail-under 5 should exit 0, got {lo.returncode}"
        return "exit 1 when below gate, exit 0 when above"
    check("A", "--fail-under gate exit codes", a3)

    def a4():
        out = tmp / "saved_report.txt"
        r = run_verify(store, "--save", str(out))
        assert r.returncode == 0 and out.exists() and OVERALL_RE.search(out.read_text(encoding="utf-8"))
        return "--save writes the full report"
    check("A", "--save writes report file", a4)

    def a5():
        bad = tmp / "tampered_store"
        bad.mkdir(parents=True, exist_ok=True)
        (bad / "meta.json").write_text(json.dumps({"num_chunks": 99, "num_concepts": 0}), encoding="utf-8")
        (bad / "chunks.jsonl").write_text(json.dumps({"chunk_id": "c1", "text": "x"}) + "\n", encoding="utf-8")
        (bad / "concepts.json").write_text("[]", encoding="utf-8")
        (bad / "graph.json").write_text(json.dumps(nx.node_link_data(nx.DiGraph())), encoding="utf-8")
        faiss.write_index(faiss.IndexFlatL2(4), str(bad / "vector.faiss"))
        r = run_verify(bad)
        assert r.returncode == 1, f"tampered store should exit 1, got {r.returncode}"
        assert "chunk count mismatch" in r.stdout
        return "meta/chunk mismatch detected, exit 1"
    check("A", "structural tamper detection (count mismatch -> exit 1)", a5)

    def a6():
        ok = ["think about coefficients", "recall the quadratic formula", "set up a+b first"]
        assert vs.valid_hint_chain(ok)
        assert vs.valid_hint_chain([{"text": t} for t in ok]), "dict-form hints must pass"
        assert not vs.valid_hint_chain(ok[:2]), "2 hints must fail"
        assert not vs.valid_hint_chain(ok + ["extra"]), "4 hints must fail"
        assert not vs.valid_hint_chain(["the answer is 5", ok[1], ok[2]]), "answer leak must fail"
        assert not vs.valid_hint_chain(["Answer: 5", ok[1], ok[2]]), "'Answer:' leak must fail"
        assert not vs.valid_hint_chain(["", ok[1], ok[2]]), "empty hint must fail"
        return "3-exactly, non-empty, leak regex, dict/str forms"
    check("A", "unit: valid_hint_chain", a6)

    def a7():
        ids = {"a", "b", "c"}
        near = lambda t: {"transfer_type": "near", "target": t}
        far = {"transfer_type": "far", "target": "physics"}
        assert vs.has_near_far_transfers({"transfer_links": [near("a"), near("b"), far]}, ids)
        assert not vs.has_near_far_transfers({"transfer_links": [near("a"), far]}, ids), "1 near must fail"
        assert not vs.has_near_far_transfers({"transfer_links": [near("a"), near("zz"), far]}, ids), \
            "near target outside store must not count"
        assert not vs.has_near_far_transfers({"transfer_links": [near("a"), near("b")]}, ids), "no far must fail"
        both = {"metacognitive_prompts": [{"when": "after_success", "prompt": "x"},
                                          {"when": "after_struggle", "prompt": "y"}]}
        assert vs.has_metacognitive_prompts(both)
        assert not vs.has_metacognitive_prompts({"metacognitive_prompts": both["metacognitive_prompts"][:1]})
        return "near/far counting, invalid-target rejection, both whens required"
    check("A", "unit: transfer-link + metacognitive predicates", a7)

    def a8():
        assert vs.attainment({"value": 0.0, "target": 0.0, "count_down": True}) == 100.0
        assert vs.attainment({"value": 29.0, "target": 0.0, "count_down": True}) == 0.0
        assert vs.attainment({"value": 500.0, "target": 1000.0, "absolute": True}) == 50.0
        assert vs.attainment({"value": 120.0, "target": 100.0}) == 100.0, "attainment must cap at 100"
        assert abs(vs.attainment({"value": 50.0, "target": 95.0}) - 100.0 * 50 / 95) < 1e-9
        return "count-down binary, absolute ratio, 100% cap"
    check("A", "unit: attainment math", a8)


# ===========================================================================
# Section B — learner_state struggle thresholds + status machine
# ===========================================================================
def fresh() -> ls.LearnerState:
    return ls.LearnerState(path=None, data={"concept_states": {}, "global": {}})


def section_b(tmp: Path):
    def b1():
        assert ls.STRUGGLE_HINT_THRESHOLD == 3 and ls.STRUGGLE_FAIL_THRESHOLD == 2
        return "STRUGGLE_HINT_THRESHOLD=3, STRUGGLE_FAIL_THRESHOLD=2"
    check("B", "struggle thresholds are the documented constants", b1)

    def b2():
        st = fresh()
        seq = []
        seq.append(st.apply_probe_result("m1", "wrong", "c1")["misconception_status"])    # active
        seq.append(st.apply_probe_result("m1", "correct", "c1")["misconception_status"])  # weakening
        seq.append(st.apply_probe_result("m1", "correct", "c1")["misconception_status"])  # resolved
        seq.append(st.apply_probe_result("m1", "wrong", "c1")["misconception_status"])    # recurring
        seq.append(st.apply_probe_result("m1", "correct", "c1")["misconception_status"])  # weakening
        seq.append(st.apply_probe_result("m1", "correct", "c1")["misconception_status"])  # resolved
        want = ["active", "weakening", "resolved", "recurring", "weakening", "resolved"]
        assert seq == want, f"{seq} != {want}"
        return " -> ".join(seq)
    check("B", "status machine: active->weakening->resolved->recurring cycle", b2)

    def b3():
        st = fresh()
        st.apply_probe_result("m2", "correct", "c1")   # weakening
        r = st.apply_probe_result("m2", "wrong", "c1")
        assert r["misconception_status"] == "active", r["misconception_status"]
        return "weakening + wrong -> back to active"
    check("B", "status machine: weakening regresses to active on failure", b3)

    def b4():
        st = fresh()
        r = st.apply_probe_result("m3", "correct", "c1", hints_used=3)
        assert r["struggled"] is True and r["metacognitive_when"] == "after_struggle"
        assert st.is_struggling("c1") and st.metacognitive_when("c1") == "after_struggle"
        return "hints_used=3 -> struggled even on a correct answer"
    check("B", "struggle via hint exhaustion (>=3 hints on one problem)", b4)

    def b5():
        st = fresh()
        r1 = st.apply_probe_result("m4", "wrong", "c1")
        assert r1["struggled"] is False, "one failure is not yet struggle"
        r2 = st.apply_probe_result("m4", "wrong", "c1")
        assert r2["struggled"] is True and r2["metacognitive_when"] == "after_struggle"
        return "1st fail no, 2nd consecutive fail yes"
    check("B", "struggle via 2 consecutive diagnostic failures", b5)

    def b6():
        st = fresh()
        st.apply_probe_result("m5", "partial", "c1")
        r = st.apply_probe_result("m5", "partial", "c1")
        assert r["struggled"] is True, "two partials count as consecutive failures (documented behavior)"
        return "partial counts as failure for the struggle/status machine (by design)"
    check("B", "partial outcomes count toward consecutive failures", b6)

    def b7():
        st = fresh()
        r = st.apply_probe_result("m6", "correct", "c1", hints_used=1)
        assert r["struggled"] is False and r["metacognitive_when"] == "after_success"
        assert st.metacognitive_when("c1") == "after_success"
        return "clean solve -> after_success"
    check("B", "success path returns after_success", b7)

    def b8():
        st = fresh()
        r = st.apply_probe_result("m7", "wrong", "c_new")
        assert abs(r["mastery"] - (ls.COLD_START_MASTERY - 0.10)) < 1e-9, r["mastery"]
        st.update_mastery("c_hi", 0.95)
        r2 = st.apply_probe_result("m7", "correct", "c_hi")
        assert r2["mastery"] == 1.0, "must clamp at 1.0"
        st.update_mastery("c_lo", 0.05)
        r3 = st.apply_probe_result("m7", "wrong", "c_lo")
        assert r3["mastery"] == 0.0, "must clamp at 0.0"
        r4 = st.apply_probe_result("m7", "partial", "c_mid")
        assert abs(r4["mastery"] - (ls.COLD_START_MASTERY + 0.05)) < 1e-9
        return "cold-start 0.30 base; +0.15/+0.05/-0.10 deltas; [0,1] clamp"
    check("B", "mastery write-back deltas + clamping", b8)

    def b9():
        st = fresh()
        assert st.record_hint_request("c1", "p1") == 1
        assert abs(st.concept_states["c1"]["hint_dependency"] - 0.1) < 1e-9
        assert st.record_hint_request("c1", "p1") == 2
        assert st.record_hint_request("c1", "p1") == 3
        ema3 = st.concept_states["c1"]["hint_dependency"]
        assert abs(ema3 - 0.489) < 1e-6, ema3
        assert st.record_hint_request("c1", "p2") == 1, "new problem must reset the per-problem counter"
        st.apply_probe_result("m8", "correct", "c1")
        cs = st.concept_states["c1"]
        assert cs["hints_used_current"] == 0 and "current_problem_id" not in cs, \
            "probe completion must reset the per-problem counter"
        return "per-problem reset works; EMA 0.1 -> 0.27 -> 0.489 as specified"
    check("B", "hint counter resets per problem; hint_dependency EMA correct", b9)

    def b10():
        st = fresh()
        try:
            st.apply_probe_result("m9", "sort_of", "c1")
        except ValueError:
            return "invalid outcome raises ValueError"
        raise AssertionError("invalid outcome accepted")
    check("B", "invalid outcome rejected", b10)

    def b11():
        p = tmp / "learner_roundtrip.json"
        st = ls.LearnerState(path=p, data={"concept_states": {}, "global": {}})
        st.apply_probe_result("m10", "wrong", "c1", hints_used=3)
        st.save()
        re_loaded = ls.load_learner_state(p)
        assert re_loaded.is_struggling("c1")
        assert re_loaded.misconception_states["m10"]["status"] == "active"
        return "struggle + misconception status survive save/load"
    check("B", "persistence round-trip", b11)

    def b12():
        assert ls.mastery_to_band(0.0) == (1.0, 4.0, 2.0)
        assert ls.mastery_to_band(0.5) == (3.5, 7.5, 5.5)
        assert ls.mastery_to_band(1.0) == (7.0, 10.0, 9.0)
        return "0->band 1-4, 0.5->3.5-7.5, 1->7-10"
    check("B", "ZPD band mapping endpoints", b12)


# ===========================================================================
# Section C — deterministic edge repair
# ===========================================================================
def section_c(store: Path, tmp: Path):
    def c1():
        G = nx.DiGraph()
        valid = {"jemh102__quad"}
        G.add_node("jemh102__quad", type="concept")
        G.add_node("example::jemh102::ex1", type="example", text="...")
        G.add_node("example::jemh103::ex2", type="example", text="...")
        G.add_edge("quad", "example::jemh102::ex1", relation="has_example")        # repairable
        G.add_edge("lin", "example::jemh102::ex1", relation="prerequisite_of")     # Phase 3 territory
        G.add_edge("foo", "example::jemh103::ex2", relation="has_example")         # cross-doc, no match
        issues = ec.IssueLog(tmp / "repair_issues.log")
        n = ec.repair_dangling_edges(G, valid, issues)
        assert n == 1, f"expected 1 repair, got {n}"
        assert G.has_edge("jemh102__quad", "example::jemh102::ex1")
        assert G["jemh102__quad"]["example::jemh102::ex1"]["repaired_from"] == "quad"
        assert not G.has_edge("quad", "example::jemh102::ex1")
        assert G.has_edge("lin", "example::jemh102::ex1"), "prerequisite_of must be untouched"
        assert G.has_edge("foo", "example::jemh103::ex2"), "unresolvable cross-doc edge must be untouched"
        return "re-points matching edges, preserves relation data, skips prereqs + cross-doc"
    check("C", "unit: repair_dangling_edges on synthetic graph", c1)

    def c2():
        chunks, concepts, G = ec.load_store(store)
        valid = {c["concept_id"] for c in concepts}

        def concept_to_instance_edges():
            return sum(1 for u, v, d in G.edges(data=True)
                       if u in valid and G.nodes[v].get("type") in ("example", "exercise"))

        before = concept_to_instance_edges()
        issues = ec.IssueLog(tmp / "live_repair_issues.log")
        n = ec.repair_dangling_edges(G, valid, issues)
        after = concept_to_instance_edges()
        assert before == 0, f"expected 0 reachable instances pre-repair, found {before}"
        assert n == 184, f"claimed 184 re-pointed edges, repair found {n}"
        assert after > 0, "repair did not connect any examples/exercises to concepts"
        reachable_concepts = {u for u, v, d in G.edges(data=True)
                              if u in valid and G.nodes[v].get("type") in ("example", "exercise")}
        return (f"live graph (in-memory): {n} edges re-pointed; concept->example/exercise edges "
                f"0 -> {after}; {len(reachable_concepts)} concepts gain instances")
    check("C", "live graph: 184 dangling-source edges repaired, instances reachable", c2)


# ===========================================================================
# Section D — in-flight enrichment cache validation
# ===========================================================================
def section_d(store: Path):
    cache_path = store / "concept_enrich_cache.jsonl"
    entries: dict[str, dict] = {}
    bad_lines = 0
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                entries[rec["key"]] = rec["data"]
            except (json.JSONDecodeError, KeyError):
                bad_lines += 1  # pipeline may be mid-append on the last line

    concepts = json.loads((store / "concepts.json").read_text(encoding="utf-8"))
    valid_set = {c["concept_id"] for c in concepts}
    by_stage = {"concept": {}, "misc": {}, "schema": {}, "hints": {}}
    for k, v in entries.items():
        stage = k.split("::", 1)[0]
        if stage in by_stage:
            by_stage[stage][k.split("::", 1)[1]] = v

    def d1():
        done = by_stage["concept"]
        assert done, "no concept enrichments cached yet"
        fully, partial = 0, []
        for cid, data in done.items():
            assert cid in valid_set, f"cached enrichment for unknown concept {cid!r}"
            _, errors = ec.validate_concept_payload(data, cid, valid_set)
            if errors:
                partial.append((cid, errors))
            else:
                fully += 1
        for data in done.values():
            for t in data.get("transfer_links", []):
                if t["transfer_type"] == "near":
                    assert t["target"] in valid_set, f"leaked invalid near target {t['target']!r}"
            whens = {m["when"] for m in data.get("metacognitive_prompts", [])}
            if whens:
                assert whens <= {"after_success", "after_struggle"}
        msg = f"{len(done)}/108 cached; {fully} pass ALL hard rules, {len(partial)} partial"
        if partial:
            msg += f" (e.g. {partial[0][0]}: {partial[0][1][:2]})"
        assert fully >= max(1, int(0.9 * len(done))), f"<90% fully valid: {msg}"
        return msg
    check("D", "cached concept enrichments re-validate against hard rules", d1)

    def d2():
        counts = {s: len(v) for s, v in by_stage.items()}
        total_target = {"concept": 108}
        msg = ", ".join(f"{s}={n}" for s, n in counts.items())
        return f"progress: {msg}; unreadable/partial lines={bad_lines} (in-flight, expected 0-1)"
    check("D", "pipeline progress snapshot", d2)

    def d3():
        log = store / "concept_enrich_issues.log"
        if not log.exists():
            return "no issues log yet"
        lines = [l for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
        hard = [l for l in lines if not l.startswith("[repair]")]
        assert not hard, f"{len(hard)} non-repair issues logged: {hard[:3]}"
        return f"{len(lines)} line(s), all expected ([repair] notice only)"
    check("D", "issues log contains no validation failures", d3)


# ===========================================================================
def render_report(store: Path) -> str:
    from datetime import datetime
    n_pass = sum(1 for r in RESULTS if r["ok"])
    lines = [
        "# Phase 0 + Phase 1 Eval Report",
        "",
        f"- Date: {datetime.now().isoformat(timespec='seconds')}",
        f"- Store: `{store}` (read-only; enrichment pipeline write-back not yet applied)",
        f"- Result: **{n_pass}/{len(RESULTS)} checks passed**",
        "",
    ]
    titles = {"A": "A. Phase 0 — HOPE-readiness scorecard (verify_store.py)",
              "B": "B. Phase 1 — learner_state.py struggle + status machine",
              "C": "C. Phase 1 — deterministic edge repair (enrich_concepts.py)",
              "D": "D. Phase 1 — LLM enrichment cache (in flight)"}
    for sec in ("A", "B", "C", "D"):
        lines += [f"## {titles[sec]}", ""]
        for r in (x for x in RESULTS if x["section"] == sec):
            mark = "PASS" if r["ok"] else "**FAIL**"
            lines.append(f"- {mark} — {r['name']}" + (f" — {r['detail']}" if r["detail"] else ""))
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="rag_store")
    ap.add_argument("--report", default="eval_phase01_report.md")
    args = ap.parse_args()
    store = Path(args.store)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        section_a(store, tmp)
        section_b(tmp)
        section_c(store, tmp)
        section_d(store)

    report = render_report(store)
    print(report)
    Path(args.report).write_text(report + "\n", encoding="utf-8")
    print(f"Report saved to {args.report}")
    if any(not r["ok"] for r in RESULTS):
        sys.exit(1)


if __name__ == "__main__":
    main()
