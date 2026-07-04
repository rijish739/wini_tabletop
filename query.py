"""Phase 5 of RAG_upgrade_plan.md — learner-snapshot-aware retrieval for the
Pedagogical Decision Engine (architecture §6.6/§6.7).

What changed from the 3-term version:

* Ranking is an explicit 7-term scored policy over the FULL learner snapshot
  (A2.1) — semantic relevance, ZPD difficulty fit, role match, representation-gap
  fit, misconception priority, hint-dependency penalty, HOPE-history boost —
  with per-turn `ranking_trace` logging so weights can later be tuned from the
  learning log (architecture §12.2).
* Misconception mechanics (A2.6): probe -> diagnose -> correct, never
  correction-first. Statuses follow architecture §10; the write-back is
  learner_state.apply_probe_result.
* Grade-9 bridge gate (Phase 3 step 7): learner_state.should_serve_bridge decides;
  activated bridges prepend recap + diagnostic to the evidence pack.
* KT/KI/CT needs follow the Phase-1/4 graph edges (transfers_to, integrates_with,
  probes) and serve problem_schema method steps / analogous worked examples /
  figure crops matched to the learner's representation gap.
* Every response returns an evidence-provenance manifest (A2.2) persisted to
  rag_store/learning_log.jsonl — the response layer must compose only from
  manifest items.
* Bundle cohesion check (A1.5, cost-gated): structural checks always; one cheap
  LLM self-check only when the bundle mixes >=3 source types.

CLI: --question, --need auto|explain|example|practice|challenge|review|transfer|
integrate|bridge|schema|reflect, --snapshot/--learner-state, --stuck-on <node_id>,
--mark-served, --no-answer, --no-judge.
"""

from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import networkx as nx

# faiss and python-dotenv are only needed by the standalone Gemini query path and
# the FAISS index. They are imported lazily (in load_store / main) so tutor_loop
# can import this module on the Jetson without installing them. rag_core's cloud
# symbols are likewise lazy; importing the names below does not pull in google-genai.
from rag_core import (GEN_MODEL, make_client, rank_hits, resolve_top_concepts,
                      answer_with_gemini)
from learner_state import (LearnerState, load_learner_state, mastery_to_band,
                           COLD_START_MASTERY)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Manual ZPD override bands (cold-start fallback; learner mastery is authoritative).
ZPD_BANDS: Dict[str, Tuple[int, int, float]] = {
    "beginner": (1, 4, 2.5),
    "intermediate": (3, 7, 5.0),
    "advanced": (6, 10, 8.0),
}

ROLE_PREFERENCE = {
    "auto": set(),
    "explain": {"explanation", "definition", "summary"},
    "example": {"worked_example"},
    "practice": {"practice"},
    "challenge": {"challenge", "practice"},
    "review": {"summary", "definition"},
    "transfer": {"application"},
    "integrate": {"explanation"},
    "bridge": {"bridge_recall"},
    "schema": {"worked_example"},
    "reflect": set(),
}

# Initial hand-set weights for the 7-term policy (A2.1); logged per turn so they
# can be tuned later from the append-only learning log.
WEIGHTS = {"w1_relevance": 0.40, "w2_difficulty_fit": 0.15, "w3_role_match": 0.10,
           "w4_repr_gap": 0.12, "w5_misconception": 0.10, "w6_hint_penalty": 0.08,
           "w7_hope_boost": 0.05}
HINT_DEPENDENCY_CUTOFF = 0.5
FAR_TRANSFER_MASTERY = 0.7
MAX_DIFFICULTY_SPREAD = 3
COHESION_HOPS = 2


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_store(store: Path, with_index: bool = True):
    chunks = load_jsonl(store / "chunks.jsonl")
    concepts = json.loads((store / "concepts.json").read_text(encoding="utf-8"))
    # graph.json stores edges under the "edges" key; networkx >=3.4 still defaults
    # node_link_graph to the deprecated "links" key, so name it explicitly.
    graph = nx.node_link_graph(
        json.loads((store / "graph.json").read_text(encoding="utf-8")), edges="edges")
    index = None
    if with_index:
        import faiss  # lazy: only the standalone Gemini query path needs the FAISS index
        index = faiss.read_index(str(store / "vector.faiss"))
    return chunks, concepts, graph, index


# ---------------------------------------------------------------------------
# Learner snapshot
# ---------------------------------------------------------------------------
class Snapshot:
    """The full learner picture the ranker consumes (A2.1)."""

    def __init__(self, learner: LearnerState, primary_cid: Optional[str],
                 concept_card: Optional[dict], graph: nx.DiGraph,
                 band: Tuple[float, float, float]):
        self.learner = learner
        self.primary = primary_cid
        self.band = band
        self.mastery = learner.mastery(primary_cid) if primary_cid else COLD_START_MASTERY
        self.hint_dependency = learner.hint_dependency(primary_cid) if primary_cid else 0.0
        reps = (concept_card or {}).get("representations") or []
        self.reps_missing = set(learner.representations_missing(primary_cid, reps)) if primary_cid else set()
        self.hope = learner.hope_rolling
        self.served = set(learner.served_items)
        # misconceptions of the primary concept with a live status
        self.active_misconceptions: Dict[str, str] = {}
        if primary_cid and primary_cid in graph:
            for m in graph.successors(primary_cid):
                if graph.nodes[m].get("type") != "misconception":
                    continue
                st = learner.misconception_status(m)
                if st in ("suspected", "active", "recurring"):
                    self.active_misconceptions[m] = st

    def summary(self) -> dict:
        lo, hi, center = self.band
        return {"primary_concept": self.primary, "mastery": round(self.mastery, 3),
                "zpd_band": [lo, hi, center], "hint_dependency": round(self.hint_dependency, 3),
                "representations_missing": sorted(self.reps_missing),
                "active_misconceptions": self.active_misconceptions,
                "hope_rolling": self.hope}


def resolve_band(concept_hits, learner: LearnerState, level_override):
    if level_override is not None:
        return ZPD_BANDS[level_override], f"manual level={level_override}"
    if not concept_hits:
        return mastery_to_band(COLD_START_MASTERY), f"cold start, mastery={COLD_START_MASTERY:.2f}"
    primary = concept_hits[0]["concept_id"]
    m = learner.mastery(primary)
    src = "learner state" if learner.is_known(primary) else "cold start (unseen concept)"
    return mastery_to_band(m), f"{src}, mastery({primary})={m:.2f}"


# ---------------------------------------------------------------------------
# 7-term re-ranking (A2.1)
# ---------------------------------------------------------------------------
def _difficulty_fit(difficulty: Any, center: float, spread: float = 4.0) -> float:
    if difficulty is None:
        return 0.5
    try:
        return max(0.0, 1.0 - abs(float(difficulty) - center) / spread)
    except (TypeError, ValueError):
        return 0.5


def snapshot_rerank(ranked: List[dict], snapshot: Snapshot, need: str, top_k: int,
                    figure_misconceptions: Dict[str, List[str]]) -> Tuple[List[dict], dict]:
    lo, hi, center = snapshot.band
    preferred = ROLE_PREFERENCE.get(need, set())
    low_ki = snapshot.hope["KI"] < 0.5
    low_kt = snapshot.hope["KT"] < 0.5
    low_ct = snapshot.hope["CT"] < 0.5
    if not ranked:
        return [], {}
    rel_max = max(r.get("score", 0.0) for r in ranked) or 1.0
    out = []
    for r in ranked:
        if r["chunk_id"] in snapshot.served:      # no-repeat within a session
            continue
        rel = r.get("score", 0.0) / rel_max
        fit = _difficulty_fit(r.get("difficulty"), center)
        role = r.get("pedagogical_role")
        role_match = 1.0 if (preferred and role in preferred) else 0.0
        repr_gap = 1.0 if snapshot.reps_missing & set(r.get("representations") or []) else 0.0
        linked_misc = figure_misconceptions.get(r.get("figure_id") or "", [])
        misc_pri = 1.0 if any(m in snapshot.active_misconceptions for m in linked_misc) else 0.0
        hint_pen = -1.0 if (snapshot.hint_dependency > HINT_DEPENDENCY_CUTOFF
                            and role == "worked_example") else 0.0
        hope = 0.0
        if low_ki and (r.get("kind") == "figure_caption" or len(r.get("representations") or []) >= 2):
            hope += 1.0
        if low_kt and role == "application":
            hope += 1.0
        if low_ct and (role == "challenge" or r.get("bloom_level") in ("analyze", "evaluate", "create")):
            hope += 1.0
        hope = min(1.0, hope)
        comp = {"w1_relevance": rel, "w2_difficulty_fit": fit, "w3_role_match": role_match,
                "w4_repr_gap": repr_gap, "w5_misconception": misc_pri,
                "w6_hint_penalty": hint_pen, "w7_hope_boost": hope}
        r = dict(r)
        r["ped_score"] = round(sum(WEIGHTS[k] * v for k, v in comp.items()), 4)
        r["score_components"] = {k: round(v, 3) for k, v in comp.items()}
        r["zpd_in_band"] = (r.get("difficulty") is not None and lo <= float(r["difficulty"]) <= hi)
        out.append(r)
    out.sort(key=lambda x: x["ped_score"], reverse=True)
    top = out[:top_k]
    trace = dict(WEIGHTS)
    if top:
        trace["top_item_components"] = top[0]["score_components"]
    return top, trace


# ---------------------------------------------------------------------------
# Evidence assembly
# ---------------------------------------------------------------------------
def ev(item_id: str, item_type: str, why: str, **extra) -> dict:
    e = {"id": item_id, "type": item_type, "why": why}
    e.update({k: v for k, v in extra.items() if v is not None})
    return e


def bridge_evidence(graph: nx.DiGraph, chunks_by_id: Dict[str, dict], snapshot: Snapshot,
                    concept_ids: List[str], force: bool) -> List[dict]:
    """Phase 3 step 7 gate: activate bridges whose mastery is unknown/low."""
    items = []
    lo, hi, center = snapshot.band
    seen = set()
    for cid in concept_ids:
        if cid not in graph:
            continue
        for g9, _, d in graph.in_edges(cid, data=True):
            if d.get("relation") != "bridges_to" or g9 in seen:
                continue
            seen.add(g9)
            serve = snapshot.learner.should_serve_bridge(g9, center)
            if force and not serve and snapshot.learner.mastery(g9) < 0.6 and center < 7.0:
                serve = True  # --need bridge bypasses only the served-this-session check
            if not serve:
                continue
            a = graph.nodes[g9]
            m = snapshot.learner.mastery(g9)
            recap_chunk = next((c for cidk, c in chunks_by_id.items()
                                if c.get("kind") == "bridge_recap" and c.get("grade9_id") == g9), None)
            why = f"prerequisite mastery {m:.2f} < 0.6; recall check before {cid}"
            if recap_chunk:
                items.append(ev(recap_chunk["chunk_id"], "bridge_recap", why,
                                text=recap_chunk["text"], grade9_id=g9))
            items.append(ev(g9, "bridge_diagnostic", "bridge outcome must write back via apply_bridge_result",
                            question=a.get("diagnostic_question"),
                            hint_chain=a.get("hint_chain"), target_concept=cid))
    return items


def misconception_evidence(graph: nx.DiGraph, snapshot: Snapshot) -> List[dict]:
    """A2.6 probe -> diagnose -> correct; correction never precedes the diagnostic."""
    items = []
    for mid, status in snapshot.active_misconceptions.items():
        a = graph.nodes[mid]
        failures = snapshot.learner.misconception_failures(mid)
        if failures == 0:
            # probe phase: diagnostic ONLY — why_wrong/correct_idea withheld
            items.append(ev(mid, "misconception", f"status={status}, diagnostic served",
                            diagnostic_question=a.get("diagnostic_question"),
                            hint_chain=a.get("hint_chain")))
        else:
            # corrective phase (diagnostic already failed via apply_probe_result)
            crop = next((f for f, fa in graph.nodes(data=True)
                         if mid in (fa.get("disambiguates_misconceptions") or [])
                         and fa.get("image_path")), None)
            items.append(ev(mid, "misconception",
                            f"status={status}, corrective after {failures} failed probe(s)",
                            why_wrong=a.get("why_wrong"), correct_idea=a.get("correct_idea")))
            if crop:
                fa = graph.nodes[crop]
                items.append(ev(crop, "figure", f"disambiguates {mid}",
                                image_path=fa.get("image_path"), alt_text=fa.get("alt_text")))
    return items


def need_evidence(graph: nx.DiGraph, concepts_by_id: Dict[str, dict], snapshot: Snapshot,
                  need: str, stuck_on: Optional[str]) -> List[dict]:
    items: List[dict] = []
    cid = snapshot.primary
    if not cid or cid not in graph:
        return items
    lo, hi, center = snapshot.band
    card = concepts_by_id.get(cid, {})

    if stuck_on and snapshot.hint_dependency > HINT_DEPENDENCY_CUTOFF:
        # w6 contract: hint-dependent learners get hint step k+1, never the worked example
        a = graph.nodes.get(stuck_on, {})
        chain = a.get("hint_chain") or []
        cs = snapshot.learner.concept_states.get(cid, {})
        used = int(cs.get("hints_used_current", 0)) if cs.get("current_problem_id") == stuck_on else 0
        if chain:
            nxt = chain[min(used, len(chain) - 1)]
            items.append(ev(f"hint::{stuck_on}::{nxt.get('level', used + 1)}", "hint",
                            f"hint_dependency {snapshot.hint_dependency:.2f} > {HINT_DEPENDENCY_CUTOFF}: "
                            f"faded hint {nxt.get('level')} instead of a worked example",
                            hint=nxt))
        return items
    if stuck_on:  # A1.1: analogous worked example via the problem schema, not re-explanation
        for s in graph.successors(cid):
            if graph.nodes[s].get("type") != "problem_schema":
                continue
            inst = graph.nodes[s].get("instance_ids") or []
            if stuck_on in inst or stuck_on in (graph.nodes[s].get("chunk_instance_ids") or []):
                items.append(ev(s, "problem_schema", f"method steps for the problem type of {stuck_on}",
                                name=graph.nodes[s].get("name"),
                                method_steps=graph.nodes[s].get("method_steps"),
                                trap_steps=graph.nodes[s].get("trap_steps")))
                analog = next((i for i in inst
                               if i != stuck_on and graph.nodes.get(i, {}).get("type") == "example"), None)
                if analog:
                    items.append(ev(analog, "analogous_example",
                                    "same schema, different surface variables",
                                    text=graph.nodes[analog].get("text")))
                break

    if need == "transfer":
        for _, tgt, d in graph.out_edges(cid, data=True):
            if d.get("relation") != "transfers_to":
                continue
            ttype = d.get("transfer_type", "near")
            if ttype == "far" and snapshot.mastery < FAR_TRANSFER_MASTERY:
                continue  # near-transfer first, far only at high mastery (§6.6)
            items.append(ev(tgt, "transfer_target",
                            f"{ttype}-transfer from {cid} (mastery {snapshot.mastery:.2f})",
                            note=d.get("note", "")))
    elif need == "integrate":
        for _, tgt, d in graph.out_edges(cid, data=True):
            if d.get("relation") == "integrates_with" or d.get("also_integrates"):
                items.append(ev(tgt, "integration_target",
                                f"KI link, representation pair {d.get('representation_pair','')}",
                                note=d.get("integration_note") or d.get("note", "")))
        for f in graph.successors(cid):
            fa = graph.nodes[f]
            if (fa.get("image_path") and snapshot.reps_missing
                    & set(fa.get("supports_representation") or [])):
                items.append(ev(f, "figure",
                                f"representation gap: {sorted(snapshot.reps_missing)}",
                                image_path=fa.get("image_path"), alt_text=fa.get("alt_text")))
                break
    elif need == "challenge":
        for p in graph.successors(cid):
            pa = graph.nodes[p]
            if pa.get("type") == "ct_probe" and abs(float(pa.get("difficulty") or center) - center) <= 2:
                items.append(ev(p, "ct_probe", f"CT probe ({pa.get('kind')}) at ZPD center {center:.1f}",
                                question=pa.get("question"),
                                expected_insight=pa.get("expected_insight")))
        items = items[:3]
    elif need == "schema":
        for s in graph.successors(cid):
            if graph.nodes[s].get("type") == "problem_schema":
                items.append(ev(s, "problem_schema", "problem-type method steps",
                                name=graph.nodes[s].get("name"),
                                method_steps=graph.nodes[s].get("method_steps")))
    elif need == "reflect":
        when = snapshot.learner.metacognitive_when(cid)
        prompt = next((p for p in (card.get("metacognitive_prompts") or [])
                       if p.get("when") == when), None)
        if prompt:
            items.append(ev(f"meta::{cid}::{when}", "metacognitive_prompt",
                            f"self-explanation, {when}", prompt=prompt["prompt"]))
    return items


# ---------------------------------------------------------------------------
# Bundle cohesion (A1.5)
# ---------------------------------------------------------------------------
def cohesion_filter(graph: nx.DiGraph, evidence: List[dict], chunk_items: List[dict],
                    concept_ids: List[str], center: float, client, use_judge: bool) -> List[str]:
    """Structural checks always; LLM self-check only on >=3 source types. Returns log lines."""
    log: List[str] = []
    # 2-hop ego set around the resolved concepts
    ego = set(concept_ids)
    UG = graph.to_undirected(as_view=True)
    for cid in concept_ids:
        if cid in UG:
            ego |= set(nx.ego_graph(UG, cid, radius=COHESION_HOPS).nodes)

    def in_scope(e: dict) -> bool:
        eid = e["id"]
        # derived ids reference a base store object: hint::<node_id>::<level>, meta::<cid>::<when>
        if eid.startswith("hint::"):
            eid = eid.split("::", 1)[1].rsplit("::", 1)[0]
        elif eid.startswith("meta::"):
            eid = eid.split("::")[1]
        if eid in ego:
            return True
        ch = next((c for c in chunk_items if c["chunk_id"] == e["id"]), None)
        if ch is not None:
            return bool(set(ch.get("concept_ids") or []) & ego) or (ch.get("figure_id") in ego) \
                or (ch.get("grade9_id") in ego)
        return False

    for e in list(evidence):
        if not in_scope(e):
            evidence.remove(e)
            log.append(f"cohesion: dropped {e['id']} (outside {COHESION_HOPS}-hop scope)")

    # difficulty spread <= 3 bands among instructional chunks (bridges exempt: they
    # are deliberately foundational)
    diffs = [(e, next(c for c in chunk_items if c["chunk_id"] == e["id"]))
             for e in evidence if e["type"] == "chunk"]
    diffs = [(e, c) for e, c in diffs if c.get("difficulty") is not None]
    while diffs:
        vals = [float(c["difficulty"]) for _, c in diffs]
        if max(vals) - min(vals) <= MAX_DIFFICULTY_SPREAD:
            break
        worst = max(diffs, key=lambda ec: abs(float(ec[1]["difficulty"]) - center))
        evidence.remove(worst[0])
        diffs.remove(worst)
        log.append(f"cohesion: dropped {worst[0]['id']} (difficulty spread > {MAX_DIFFICULTY_SPREAD})")

    # correct_idea never without its misconception in the bundle
    misc_in_bundle = {e["id"] for e in evidence if e["type"] == "misconception"}
    for e in list(evidence):
        if e.get("correct_idea") and e["id"] not in misc_in_bundle:
            evidence.remove(e)
            log.append(f"cohesion: dropped {e['id']} (correct_idea without misconception)")

    types = {e["type"] for e in evidence}
    if use_judge and len(types) >= 3 and client is not None:
        brief = [{"id": e["id"], "type": e["type"],
                  "gist": (e.get("text") or e.get("question") or e.get("why"))[:200]} for e in evidence]
        try:
            from google.genai import types as gtypes
            resp = client.models.generate_content(
                model=GEN_MODEL,
                contents="Do any of these tutoring evidence items CONTRADICT each other "
                         "mathematically or pedagogically? Reply STRICT JSON "
                         '{"contradiction": true|false, "offending_id": "<id or null>"}\n'
                         + json.dumps(brief, ensure_ascii=False),
                config=gtypes.GenerateContentConfig(response_mime_type="application/json"))
            verdict = json.loads(resp.text or "{}")
            if verdict.get("contradiction") and verdict.get("offending_id"):
                oid = verdict["offending_id"]
                for e in list(evidence):
                    if e["id"] == oid:
                        evidence.remove(e)
                        log.append(f"cohesion: judge dropped {oid} (contradiction)")
        except Exception as exc:  # noqa: BLE001 - judge failure must never break retrieval
            log.append(f"cohesion: judge call failed ({exc}); structural checks only")
    return log


# ---------------------------------------------------------------------------
# Main turn
# ---------------------------------------------------------------------------
def run_turn(store: Path, question: str, need: str, learner: LearnerState,
             top_k: int = 8, level_override=None, stuck_on: Optional[str] = None,
             use_judge: bool = True, want_answer: bool = True, mark_served: bool = False):
    chunks, concepts, graph, index = load_store(store)
    concepts_by_id = {c["concept_id"]: c for c in concepts}
    chunks_by_id = {c["chunk_id"]: c for c in chunks}
    figure_misconceptions = {n: (a.get("disambiguates_misconceptions") or [])
                             for n, a in graph.nodes(data=True) if a.get("image_path")}
    client = make_client()

    concept_hits = resolve_top_concepts(question, concepts, client, k=4)
    concept_ids = [c["concept_id"] for c in concept_hits]
    primary = concept_ids[0] if concept_ids else None
    band, band_reason = resolve_band(concept_hits, learner, level_override)
    lo, hi, center = band
    snapshot = Snapshot(learner, primary, concepts_by_id.get(primary), graph, band)

    # prerequisite pull-in for weak learners (1 level for chunk candidates; the
    # bridge gate walks 2 levels because chapter bridges anchor on the chapter's
    # intro concepts, which sit above the specific concept a query resolves to)
    def prereq_ancestors(cids: List[str], depth: int) -> List[str]:
        seen, frontier = [], list(cids)
        for _ in range(depth):
            nxt = []
            for c in frontier:
                if c in graph:
                    for p in graph.predecessors(c):
                        if (graph.get_edge_data(p, c) or {}).get("relation") == "prerequisite_of" \
                                and p not in seen:
                            seen.append(p)
                            nxt.append(p)
            frontier = nxt
        return seen

    prereq_ids: List[str] = prereq_ancestors(concept_ids, 1) if (center <= 5.0 and primary) else []

    evidence: List[dict] = []
    # 1. bridge gate first — prior knowledge is activated BEFORE new instruction
    bridge_scope = list(dict.fromkeys(concept_ids + prereq_ancestors(concept_ids, 2)))
    evidence += bridge_evidence(graph, chunks_by_id, snapshot, bridge_scope, force=(need == "bridge"))
    # 2. misconception mechanics (probe before correction, A2.6)
    evidence += misconception_evidence(graph, snapshot)
    # 3. need-specific graph evidence (KT/KI/CT/schema/reflection)
    evidence += need_evidence(graph, concepts_by_id, snapshot, need, stuck_on)

    # 4. chunk retrieval
    search_ids = list(dict.fromkeys(concept_ids + prereq_ids))
    candidates = [r for r in chunks if any(c in (r.get("concept_ids") or []) for c in search_ids)]
    if not candidates:
        candidates = chunks
    ranked = rank_hits(question, candidates, client, k=top_k * 3)
    top, trace = snapshot_rerank(ranked, snapshot, need, top_k, figure_misconceptions)
    for r in top:
        why = (f"semantic+pedagogic match (role={r.get('pedagogical_role')}, "
               f"difficulty={r.get('difficulty')}, {'in' if r.get('zpd_in_band') else 'out of'} ZPD)")
        evidence.append(ev(r["chunk_id"], "chunk", why,
                           image_path=r.get("image_path") if r.get("kind") == "figure_caption" else None))

    # 5. cohesion check (A1.5)
    cohesion_log = cohesion_filter(graph, evidence, chunks, search_ids, center, client, use_judge)

    manifest = {
        "evidence": evidence,
        "bridge_ids": [e["id"] for e in evidence if e["type"].startswith("bridge")],
        "schema_ids": [e["id"] for e in evidence if e["type"] == "problem_schema"],
        "ranking_trace": trace,
        "cohesion_log": cohesion_log,
        "snapshot": snapshot.summary(),
        "band_reason": band_reason,
    }

    # 6. persist the turn (architecture §12.2 append-only learning log)
    log_row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "question": question, "need": need,
               "manifest": manifest}
    with open(store / "learning_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(log_row, ensure_ascii=False) + "\n")

    if mark_served:
        learner.mark_served([e["id"] for e in evidence])
        for b in manifest["bridge_ids"]:
            if b.startswith("grade9::") and b not in learner.bridges_served:
                learner.bridges_served.append(b)
        learner.save()

    answer = None
    if want_answer:
        # response layer composes ONLY from manifest items (grounding guarantee)
        blocks = []
        for e in evidence:
            row = chunks_by_id.get(e["id"])
            text = (row or {}).get("text") or e.get("text") or e.get("question") \
                or e.get("why_wrong") or e.get("prompt") or e.get("note") or ""
            blocks.append({"source_path": e["id"], "page": (row or {}).get("page", ""),
                           "concept_ids": (row or {}).get("concept_ids", []), "text": text})
        chapter_hint = "Class 10 Mathematics"
        if primary:
            doc = graph.nodes.get(primary, {}).get("chapter_doc")
            chap = graph.nodes.get(f"chapter::{doc}", {}) if doc else {}
            if chap.get("name"):
                chapter_hint = f"Class 10 Mathematics, Chapter: {chap['name']}"
        answer = answer_with_gemini(client, question, blocks, chapter_hint=chapter_hint)

    return concept_hits, manifest, answer


def main():
    from dotenv import load_dotenv  # lazy: standalone CLI only
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="rag_store")
    ap.add_argument("--question", required=True)
    ap.add_argument("--top_k", type=int, default=8)
    ap.add_argument("--snapshot", "--learner-state", dest="snapshot", default="learner_state.json",
                    help="Learner-state JSON; the full snapshot drives the 7-term ranking.")
    ap.add_argument("--level", choices=list(ZPD_BANDS), default=None)
    ap.add_argument("--need", choices=list(ROLE_PREFERENCE), default="auto")
    ap.add_argument("--stuck-on", default=None, help="Exercise/example node id the learner is stuck on.")
    ap.add_argument("--mark-served", action="store_true",
                    help="Record served evidence + bridges into the learner state file.")
    ap.add_argument("--no-answer", action="store_true")
    ap.add_argument("--no-judge", action="store_true", help="Disable the LLM cohesion self-check.")
    args = ap.parse_args()

    learner = load_learner_state(Path(args.snapshot) if args.snapshot else None)
    concept_hits, manifest, answer = run_turn(
        Path(args.store), args.question, args.need, learner,
        top_k=args.top_k, level_override=args.level, stuck_on=args.stuck_on,
        use_judge=not args.no_judge, want_answer=not args.no_answer,
        mark_served=args.mark_served,
    )

    print("\n=== Snapshot ===")
    print(json.dumps(manifest["snapshot"], ensure_ascii=False, indent=2))
    print(f"band source: {manifest['band_reason']}")
    print("\n=== Concept resolution ===")
    for c in concept_hits:
        print(f"- {c['concept_id']} | {c['name']} | score={c['score']:.4f}")
    print("\n=== Evidence manifest ===")
    print(json.dumps({k: manifest[k] for k in ("evidence", "bridge_ids", "schema_ids",
                                               "ranking_trace", "cohesion_log")},
                     ensure_ascii=False, indent=2))
    if answer is not None:
        print("\n=== Answer ===")
        print(answer)


if __name__ == "__main__":
    main()
