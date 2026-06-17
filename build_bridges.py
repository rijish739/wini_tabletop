"""Phase 3 of RAG_upgrade_plan.md — Class-9 prerequisite bridge layer (closes G9 + G7).

Activating accurate prior knowledge before new instruction is one of the most
consistently supported effects in learning science; NCERT chapters are literally
written for it — nearly every chapter's intro recalls Class IX material. This
script turns that intro material into runtime-gated learner-state objects:

  detect    tag recall chunks (`pedagogical_role: "bridge_recall"`, original role
            preserved in `original_role`) and mark intro-section chunks (page <= 4).
  extract   one LLM call per chapter (16): the named Class-9 concepts the intro
            leans on (3-6 each) with `bridge_recap` (3-5 sentences grounded ONLY
            in the supplied intro chunks), `diagnostic_question` + `expected_answer`,
            Class-10 `target_concept_ids` (validated against the 108) and the
            evidence chunk ids. Cached in rag_store/bridge_cache.jsonl, resumable.
  graph     `grade9::<slug>` nodes (grade: 9, source: "generated") with
            grade9 -[bridges_to]-> class10_concept and
            bridge_chunk -[evidence_for]-> grade9_concept edges.
  dangling  G7: resolve the 29 untyped prerequisite nodes — same-doc prefix match,
            unique suffix match into the 108, fuzzy match into the new grade-9
            nodes, else convert to a typed `external_concept` (target: 0 unknown).
  write     embed every recap as a retrievable chunk (kind "bridge_recap") into
            chunks.jsonl + FAISS; patch graph.json; dump all recaps to
            rag_store/bridge_recaps_review.md for the full human read-through.

The runtime gating contract (activate when bridge mastery < 0.6 and ZPD center < 7
and not served this session; diagnostic outcome writes mastery back) lives in
learner_state.py (`should_serve_bridge` / `apply_bridge_result`); query.py wiring
is Phase 5.

Env: GOOGLE_GENAI_USE_VERTEXAI=True, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION=global.
"""

from __future__ import annotations
import argparse
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx
import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types
from rapidfuzz import fuzz
from tqdm import tqdm

from rag_core import GEN_MODEL, make_client, embed_texts

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RECALL_PAT = re.compile(
    r"class\s+ix|you have studied|studied in class|recall that|in the previous class"
    r"|you have already studied|we have learnt|you are already familiar", re.I)
INTRO_MAX_PAGE = 4
BRIDGE_DIFFICULTY = 3  # recaps are deliberately foundational on the 1-10 ZPD scale


class Cache:
    def __init__(self, path: Path):
        self.path = path
        self.mem: Dict[str, Any] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self.mem[rec["key"]] = rec["data"]

    def get(self, key):
        return self.mem.get(key)

    def put(self, key, data):
        self.mem[key] = data
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "data": data}, ensure_ascii=False) + "\n")


class IssueLog:
    def __init__(self, path: Path):
        self.path = path

    def log(self, where, msg):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(f"[{where}] {msg}\n")


def call_json(client, prompt, retries=2):
    last = None
    for _ in range(retries + 1):
        try:
            resp = client.models.generate_content(
                model=GEN_MODEL, contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"))
            return json.loads(resp.text or "{}")
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"LLM call failed after retries: {last}")


def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", str(s or "").strip())
    return s.strip("_").lower() or "unknown"


def load_store(store: Path):
    chunks = [json.loads(l) for l in (store / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    concepts = json.loads((store / "concepts.json").read_text(encoding="utf-8"))
    graph = nx.node_link_graph(json.loads((store / "graph.json").read_text(encoding="utf-8")))
    return chunks, concepts, graph


# ---------------------------------------------------------------------------
# Stage: detect
# ---------------------------------------------------------------------------
def run_detect(chunks: List[dict]) -> Dict[str, List[dict]]:
    """Tag recall chunks in place; return {doc_id: [intro-material chunks]} for extraction."""
    tagged = 0
    material: Dict[str, List[dict]] = {}
    for c in chunks:
        if c.get("kind") not in ("page_text", "page_summary"):
            continue
        is_recall = bool(RECALL_PAT.search(c.get("text", "")))
        is_intro = c.get("kind") == "page_text" and (c.get("page") or 99) <= INTRO_MAX_PAGE
        if is_recall and c.get("pedagogical_role") != "bridge_recall":
            c["original_role"] = c.get("pedagogical_role")
            c["pedagogical_role"] = "bridge_recall"
            tagged += 1
        if is_intro:
            c["intro_section"] = True
        if is_recall or is_intro:
            material.setdefault(c["doc_id"], []).append(c)
    print(f"[detect] tagged {tagged} chunks bridge_recall; "
          f"intro material spans {len(material)} docs")
    return material


# ---------------------------------------------------------------------------
# Stage: extract (one call per chapter)
# ---------------------------------------------------------------------------
def extract_prompt(chapter_name: str, doc_id: str, concept_list: List[dict],
                   material: List[dict], feedback: str = "") -> str:
    mat = "\n".join(f"- [{c['chunk_id']}] (p.{c.get('page','?')}) {(c.get('text') or '')[:700]}"
                    for c in material[:14])
    fb = f"\nYOUR PREVIOUS ATTEMPT HAD ERRORS — fix them:\n{feedback}\n" if feedback else ""
    return f"""You are building the Class-9 prerequisite BRIDGE layer for one chapter of the NCERT
Class 10 Mathematics textbook. From the chapter's introduction material below, identify the
named Class-9 concepts this chapter leans on (3-6 of them; fewer only if the intro genuinely
names fewer). Return STRICT JSON:
{{"bridges": [
  {{
    "name": "<the Class-9 concept, e.g. 'Heron's formula' or 'linear equations in two variables'>",
    "grade9_topic": "<the NCERT Class-9 chapter/topic it comes from>",
    "bridge_recap": "<3-5 sentence recall explanation written ONLY from facts stated in the
        supplied intro material — do not add Class-9 detail the intro does not mention>",
    "diagnostic_question": "<one short question checking the learner actually recalls this;
        answerable by a student who remembers the Class-9 idea>",
    "expected_answer": "<brief correct answer>",
    "target_concept_ids": ["<Class-10 concept ids from the list below that this bridge feeds>"],
    "evidence_chunk_ids": ["<chunk ids from the intro material that name/use this dependency>"]
  }}
]}}
Hard rules:
- target_concept_ids must be copied exactly from the CHAPTER CONCEPTS list.
- evidence_chunk_ids must be copied exactly from the bracketed ids in the intro material.
- bridge_recap must stay within the supplied text's content (NCERT-grounding rule); it may
  rephrase but never introduce new formulas/facts.
- Keep bridges coarse: one per NAMED dependency, not one per sentence.
{fb}
CHAPTER: {chapter_name} (doc {doc_id})

CHAPTER CONCEPTS (the only legal target_concept_ids):
{json.dumps([{'id': c['concept_id'], 'name': c['name']} for c in concept_list], ensure_ascii=False)}

INTRO MATERIAL:
{mat}
"""


def validate_bridges(payload: Any, valid_targets: set, valid_chunks: set) -> Tuple[List[dict], List[str]]:
    errors: List[str] = []
    out: List[dict] = []
    items = payload.get("bridges") if isinstance(payload, dict) else payload
    for b in items if isinstance(items, list) else []:
        if not isinstance(b, dict):
            continue
        name = str(b.get("name") or "").strip()
        recap = str(b.get("bridge_recap") or "").strip()
        diag = str(b.get("diagnostic_question") or "").strip()
        ans = str(b.get("expected_answer") or "").strip()
        if not (name and recap and diag and ans):
            errors.append(f"bridge {name!r}: missing name/recap/diagnostic/answer")
            continue
        if len(re.findall(r"[.!?]", recap)) < 2:
            errors.append(f"bridge {name!r}: recap shorter than 3 sentences")
        targets = [t for t in (b.get("target_concept_ids") or []) if t in valid_targets]
        bad_t = [t for t in (b.get("target_concept_ids") or []) if t not in valid_targets]
        if bad_t:
            errors.append(f"bridge {name!r}: invalid target ids {bad_t}")
        if not targets:
            errors.append(f"bridge {name!r}: no valid target_concept_ids")
            continue
        evidence = [e for e in (b.get("evidence_chunk_ids") or []) if e in valid_chunks]
        out.append({"name": name, "grade9_topic": str(b.get("grade9_topic") or ""),
                    "bridge_recap": recap, "diagnostic_question": diag, "expected_answer": ans,
                    "target_concept_ids": targets, "evidence_chunk_ids": evidence})
    if not out:
        errors.append("no valid bridges produced")
    return out, errors


def run_extract(client, cache: Cache, issues: IssueLog, G: nx.DiGraph, concepts: List[dict],
                material: Dict[str, List[dict]], limit=None):
    chapters = sorted(n for n, a in G.nodes(data=True) if a.get("type") == "chapter")
    todo = [ch for ch in chapters if cache.get(f"bridges::{ch}") is None]
    if limit:
        todo = todo[:limit]
    print(f"[extract] {len(chapters)} chapters, {len(todo)} to extract")
    for ch in tqdm(todo, desc="bridge extraction"):
        doc_id = G.nodes[ch].get("doc_id") or ch.split("::", 1)[1]
        chapter_name = G.nodes[ch].get("name", doc_id)
        concept_list = [c for c in concepts if c.get("chapter_doc") == doc_id]
        mat = material.get(doc_id) or []
        if not mat or not concept_list:
            issues.log("extract", f"{doc_id}: no intro material or no concepts; skipped")
            cache.put(f"bridges::{ch}", {"bridges": [], "reason": "no material"})
            continue
        valid_targets = {c["concept_id"] for c in concept_list}
        valid_chunks = {c["chunk_id"] for c in mat}
        payload = call_json(client, extract_prompt(chapter_name, doc_id, concept_list, mat))
        bridges, errors = validate_bridges(payload, valid_targets, valid_chunks)
        if errors:
            payload = call_json(client, extract_prompt(chapter_name, doc_id, concept_list, mat,
                                                       feedback="\n".join(f"- {e}" for e in errors)))
            bridges2, errors2 = validate_bridges(payload, valid_targets, valid_chunks)
            if bridges2:
                bridges, errors = bridges2, errors2
            if errors:
                issues.log("extract", f"{doc_id}: kept valid subset; remaining: {errors}")
        cache.put(f"bridges::{ch}", {"bridges": bridges, "doc_id": doc_id,
                                     "chapter_name": chapter_name})


# ---------------------------------------------------------------------------
# Stage: graph
# ---------------------------------------------------------------------------
def run_graph(G: nx.DiGraph, cache: Cache) -> List[dict]:
    """Create grade9_concept nodes + edges. Returns recap rows for the embed stage.

    The same Class-9 dependency may anchor several chapters; the node is global
    (one per named dependency) — later chapters add bridges_to edges and their own
    chapter-specific recap chunk (bridge::<g9>::<doc>), while the node keeps the
    first chapter's diagnostic.
    """
    recap_rows: List[dict] = []
    n_nodes, n_edges = 0, 0
    for key, data in sorted(cache.mem.items()):
        if not key.startswith("bridges::"):
            continue
        doc_id = data.get("doc_id") or key.split("::", 2)[-1]
        for b in data.get("bridges") or []:
            g9 = f"grade9::{slugify(b['name'])}"
            if g9 not in G or G.nodes[g9].get("type") != "grade9_concept":
                G.add_node(g9, type="grade9_concept", name=b["name"], grade=9,
                           topic=b["grade9_topic"], bridge_recap=b["bridge_recap"],
                           diagnostic_question=b["diagnostic_question"],
                           expected_answer=b["expected_answer"], source="generated")
                n_nodes += 1
            for t in b["target_concept_ids"]:
                if not G.has_edge(g9, t):
                    G.add_edge(g9, t, relation="bridges_to", source_chapter=doc_id)
                    n_edges += 1
            for ev in b["evidence_chunk_ids"]:
                ev_node = f"bridge_chunk::{ev}"
                if ev_node not in G:
                    G.add_node(ev_node, type="bridge_chunk", chunk_id=ev)
                if not G.has_edge(ev_node, g9):
                    G.add_edge(ev_node, g9, relation="evidence_for")
            recap_rows.append({
                "chunk_id": f"bridge::{g9}::{doc_id}",
                "doc_id": doc_id, "source_path": "", "page": None,
                "text": f"Recall from Class 9 — {b['name']}: {b['bridge_recap']}",
                "kind": "bridge_recap", "grade9_id": g9,
                "concept_ids": b["target_concept_ids"],
                "pedagogical_role": "bridge_recall",
                "difficulty": BRIDGE_DIFFICULTY,
                "diagnostic_question": b["diagnostic_question"],
                "expected_answer": b["expected_answer"],
            })
    print(f"[graph] {n_nodes} grade9_concept nodes, {n_edges} bridges_to edges, "
          f"{len(recap_rows)} recap rows")
    return recap_rows


# ---------------------------------------------------------------------------
# Stage: dangling (G7)
# ---------------------------------------------------------------------------
def run_dangling(G: nx.DiGraph, concepts: List[dict], issues: IssueLog):
    valid_ids = {c["concept_id"] for c in concepts}
    grade9 = {n: G.nodes[n].get("name", "") for n in G.nodes if G.nodes[n].get("type") == "grade9_concept"}
    dangling = [n for n, a in G.nodes(data=True) if not a.get("type")]
    stats = {"prefix": 0, "suffix": 0, "grade9": 0, "external": 0}

    def repoint(old: str, new: str):
        for _, v, d in list(G.out_edges(old, data=True)):
            if new != v and not G.has_edge(new, v):
                G.add_edge(new, v, **{**d, "repaired_from": old})
        for u, _, d in list(G.in_edges(old, data=True)):
            if u != new and not G.has_edge(u, new):
                G.add_edge(u, new, **{**d, "repaired_from": old})
        G.remove_node(old)

    for n in dangling:
        slug = slugify(n)
        # (a) same-doc prefix: a neighbor concept's chapter_doc resolves <doc>__<n>
        neigh_docs = set()
        for _, v in G.out_edges(n):
            if v in valid_ids:
                neigh_docs.add(str(v).split("__", 1)[0])
        for u, _ in G.in_edges(n):
            if u in valid_ids:
                neigh_docs.add(str(u).split("__", 1)[0])
        cand = [f"{d}__{slug}" for d in neigh_docs if f"{d}__{slug}" in valid_ids]
        if len(cand) == 1:
            repoint(n, cand[0])
            stats["prefix"] += 1
            continue
        # (b) unique suffix match anywhere in the 108
        suffix_hits = [c for c in valid_ids if c.split("__", 1)[-1] == slug]
        if len(suffix_hits) == 1:
            repoint(n, suffix_hits[0])
            stats["suffix"] += 1
            continue
        # (c) fuzzy match into the new grade-9 layer (these refs ARE prior-grade ideas)
        best, best_score = None, 0.0
        for g9, name in grade9.items():
            score = max(fuzz.token_set_ratio(slug.replace("_", " "), name.lower()),
                        fuzz.token_set_ratio(slug, g9.split("::", 1)[-1]))
            if score > best_score:
                best, best_score = g9, score
        if best and best_score >= 85:
            repoint(n, best)
            stats["grade9"] += 1
            continue
        # (d) genuine external: type it so it is no longer dangling
        G.nodes[n].update(type="external_concept", name=n.replace("_", " "),
                          grade="9_or_external", source="g7_resolution")
        stats["external"] += 1
        issues.log("dangling", f"{n}: typed as external_concept (no match)")
    remaining = [n for n, a in G.nodes(data=True) if not a.get("type")]
    print(f"[dangling] resolved {len(dangling)} nodes: {stats}; remaining untyped: {len(remaining)}")


# ---------------------------------------------------------------------------
# Stage: write
# ---------------------------------------------------------------------------
def run_write(store: Path, G: nx.DiGraph, chunks: List[dict], recap_rows: List[dict], client):
    import faiss
    for fname in ("graph.json", "chunks.jsonl", "vector.faiss", "meta.json"):
        bak = store / f"{fname}.phase3.bak"
        if not bak.exists():
            shutil.copyfile(store / fname, bak)

    existing = {c["chunk_id"] for c in chunks}
    new_rows = [r for r in recap_rows if r["chunk_id"] not in existing]
    if new_rows:
        vecs = embed_texts(client, [r["text"] for r in new_rows], "RETRIEVAL_DOCUMENT")
        index = faiss.read_index(str(store / "vector.faiss"))
        index.add(np.ascontiguousarray(vecs.astype(np.float32)))
        faiss.write_index(index, str(store / "vector.faiss"))

    out_rows = chunks + new_rows  # chunks were tag-updated in place by run_detect
    (store / "chunks.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in out_rows), encoding="utf-8")
    (store / "graph.json").write_text(json.dumps(nx.node_link_data(G), ensure_ascii=False, indent=2),
                                      encoding="utf-8")

    meta_path = store / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["num_chunks"] = len(out_rows)
    counts: Dict[str, int] = {}
    for _, a in G.nodes(data=True):
        counts[a.get("type", "unknown")] = counts.get(a.get("type", "unknown"), 0) + 1
    meta["node_type_counts"] = counts
    meta["graph_nodes"] = G.number_of_nodes()
    meta["graph_edges"] = G.number_of_edges()
    meta["phase3_bridges"] = {
        "date": date.today().isoformat(), "model": GEN_MODEL,
        "grade9_concepts": counts.get("grade9_concept", 0),
        "bridge_recap_chunks": len(new_rows),
        "bridge_recall_tagged": sum(1 for r in out_rows if r.get("pedagogical_role") == "bridge_recall"),
        "dangling_remaining": counts.get("unknown", 0),
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # full human read-through file (plan: "read all ~60 recaps once")
    lines = ["# Bridge recaps — full review file\n"]
    for n, a in sorted(G.nodes(data=True)):
        if a.get("type") != "grade9_concept":
            continue
        targets = [v for _, v in G.out_edges(n) if G.nodes[v].get("type") == "concept"]
        lines += [f"## {a['name']}  (`{n}`)",
                  f"*Class-9 topic:* {a.get('topic','')}  |  *bridges to:* {', '.join(targets)}",
                  f"\n**Recap:** {a.get('bridge_recap','')}",
                  f"\n**Diagnostic:** {a.get('diagnostic_question','')}",
                  f"\n**Expected answer:** {a.get('expected_answer','')}\n"]
    (store / "bridge_recaps_review.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[write] +{len(new_rows)} bridge_recap chunks (total {len(out_rows)}); "
          f"review file: {store / 'bridge_recaps_review.md'}")


# ---------------------------------------------------------------------------
def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="rag_store")
    ap.add_argument("--limit", type=int, default=None, help="Chapter cap for smoke tests.")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    store = Path(args.store)
    chunks, concepts, G = load_store(store)
    cache = Cache(store / "bridge_cache.jsonl")
    issues = IssueLog(store / "bridge_issues.log")
    client = make_client()

    material = run_detect(chunks)
    run_extract(client, cache, issues, G, concepts, material, limit=args.limit)
    recap_rows = run_graph(G, cache)
    run_dangling(G, concepts, issues)
    if not args.no_write:
        run_write(store, G, chunks, recap_rows, client)


if __name__ == "__main__":
    main()
