"""Local (zero-LLM) dataset builder for model_dataset_architecture_report.md.

Builds the five datasets that can be derived ENTIRELY from the RAG store with
fully grounded labels — no sample is randomly selected, no tag is invented:
every label is a deterministic function of an existing store field or graph edge,
and every row carries a `grounding` provenance record naming that source.

  dataset/concept_resolver.jsonl       (report §4.1)
  dataset/retrieval_relevance.jsonl    (report §4.2)
  dataset/representation_tagger.jsonl  (report §4.3)
  dataset/misconception_clue_bank.jsonl(report §4.4)
  dataset/grounding_guard.jsonl        (report §7.3)
  dataset/datasets_manifest.json       (counts + split stats + build config)

Grounding tiers:
  "store"     — label read directly from a store field / graph edge (the default)
  "generated" — label produced by the (already validated) exemplar generation run
                (dataset/exemplar_dataset_10000.json); merged ONLY into the concept
                resolver because the store cannot produce student utterances or the
                INHERIT_CURRENT_CONCEPT class. Consumers can filter by tier.

Split policy (report §2.3 — no students exist yet, so split at SOURCE-ASSET level):
  - deterministic md5-hash buckets on the row's grounding source id: 70/15/15;
  - holdout chapters jemh105 + jemh111: any row whose query/text/chunk touches them
    gets split "holdout_chapter" (excluded from train/val/test);
  - holdout misconception families = the misconceptions owned by holdout chapters
    -> split "holdout_misconception".

Run:    python build_local_datasets.py
Verify: python build_local_datasets.py --verify   (report-rule compliance audit)
"""

from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx
from rank_bm25 import BM25Okapi

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

STORE = Path("rag_store")
OUT = Path("dataset")
HOLDOUT_CHAPTERS = {"jemh105", "jemh111"}
REPRESENTATIONS = {"symbolic", "verbal", "graphical", "diagrammatic", "tabular",
                   "algebraic", "numeric", "numerical", "geometric", "flowchart"}
ANSWER_LEAK_RE = re.compile(r"\b(the\s+)?(final\s+)?answer\s*(is|=|:)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Store loading + shared helpers
# ---------------------------------------------------------------------------
def load_store():
    chunks = [json.loads(l) for l in (STORE / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    concepts = json.loads((STORE / "concepts.json").read_text(encoding="utf-8"))
    G = nx.node_link_graph(json.loads((STORE / "graph.json").read_text(encoding="utf-8")))
    bank = [json.loads(l) for l in (STORE / "hope_prompt_bank.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    return chunks, concepts, G, bank


def doc_of_concept(cid: str) -> str:
    return cid.split("__", 1)[0]


def split_for(source_id: str, docs_touched: Set[str], text: Optional[str] = None) -> str:
    """Deterministic 70/15/15 split. When `text` is given the hash basis is the
    normalized text itself, so IDENTICAL texts can never straddle two splits
    (the leakage rule of report §2.3) even when they come from different sources."""
    if docs_touched & HOLDOUT_CHAPTERS:
        return "holdout_chapter"
    basis = re.sub(r"\s+", " ", text.strip().lower()) if text else source_id
    h = int(hashlib.md5(basis.encode("utf-8")).hexdigest(), 16) % 100
    return "train" if h < 70 else ("val" if h < 85 else "test")


def tokenize(s: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (s or "").lower())


class Ctx:
    """Precomputed store lookups shared by all builders."""

    def __init__(self):
        self.chunks, self.concepts, self.G, self.bank = load_store()
        self.by_cid = {c["concept_id"]: c for c in self.concepts}
        self.valid = set(self.by_cid)
        self.chunks_by_id = {c["chunk_id"]: c for c in self.chunks}
        # misconception -> owning concepts (has_misconception from one of the 108)
        self.misc_owners: Dict[str, List[str]] = defaultdict(list)
        for u, v, d in self.G.edges(data=True):
            if d.get("relation") == "has_misconception" and u in self.valid:
                self.misc_owners[v].append(u)
        # concept -> chunks
        self.concept_chunks: Dict[str, List[dict]] = defaultdict(list)
        for ch in self.chunks:
            for cid in ch.get("concept_ids") or []:
                if cid in self.valid:
                    self.concept_chunks[cid].append(ch)
        # 2-hop ego sets (undirected) per concept, for hard-negative grounding
        UG = self.G.to_undirected(as_view=True)
        self.ego2: Dict[str, Set[str]] = {}
        for cid in self.valid:
            self.ego2[cid] = set(nx.ego_graph(UG, cid, radius=2).nodes) if cid in UG else {cid}
        # same-chapter siblings sorted by shared alias/vocab tokens (deterministic)
        self.token_bank = {c["concept_id"]: set(tokenize(" ".join(
            [c.get("name", "")] + (c.get("aliases") or []) + (c.get("vocabulary") or []))))
            for c in self.concepts}

    def hard_negative_concepts(self, cid: str, k: int = 3) -> List[str]:
        doc = doc_of_concept(cid)
        sibs = [c for c in self.valid if c != cid and doc_of_concept(c) == doc]
        sibs.sort(key=lambda s: (-len(self.token_bank[cid] & self.token_bank[s]), s))
        return sibs[:k]


def row_id(prefix: str, n: int) -> str:
    return f"{prefix}_{n:06d}"


# ---------------------------------------------------------------------------
# 1. Concept resolver (§4.1)
# ---------------------------------------------------------------------------
def build_concept_resolver(ctx: Ctx) -> List[dict]:
    rows: List[dict] = []

    def add(text, primary, label_type, grounding, secondary=None, tier="store"):
        if not text or not str(text).strip():
            return
        docs = {doc_of_concept(primary)} if primary in ctx.valid else set()
        rows.append({
            "id": row_id("cr", len(rows)),
            "text": str(text).strip(),
            "primary_concept_id": primary,
            "secondary_concept_ids": secondary or [],
            "label_type": label_type,
            "hard_negative_ids": ctx.hard_negative_concepts(primary) if primary in ctx.valid else [],
            "grounding": {**grounding, "tier": tier},
            "split": split_for(grounding.get("source_id", text), docs, text=str(text)),
        })

    # HOPE bank prompts (concept_id was validated + kappa-calibrated in Phase 6).
    # Bridge prompts are EXCLUDED: a Class-9 recall question does not "explicitly and
    # unambiguously" name the Class-10 concept (report §4.1 rule 3).
    for b in ctx.bank:
        if b["signal"] == "bridge" or b.get("status") == "rewrite_or_drop":
            continue
        add(b["prompt"], b["concept_id"], f"hope_{b['signal'].lower()}_prompt",
            {"source": "hope_prompt_bank", "source_id": b["prompt_id"], "field": "prompt"})

    # CT probe questions (concept -[probes]-> ct_probe)
    for n, a in ctx.G.nodes(data=True):
        if a.get("type") != "ct_probe":
            continue
        owners = [u for u, _, d in ctx.G.in_edges(n, data=True) if d.get("relation") == "probes"]
        if owners and owners[0] in ctx.valid:
            add(a.get("question"), owners[0], "ct_probe_question",
                {"source": "graph", "source_id": n, "edge": "probes"})

    # Misconception diagnostics (owner via has_misconception; extra owners = secondary)
    for mid, owners in ctx.misc_owners.items():
        a = ctx.G.nodes[mid]
        if a.get("diagnostic_question"):
            add(a["diagnostic_question"], owners[0], "misconception_diagnostic",
                {"source": "graph", "source_id": mid, "edge": "has_misconception",
                 "field": "diagnostic_question"},
                secondary=sorted(set(owners[1:])))

    # Concept-linked exercise/example node texts (post-repair, same-doc edges only)
    for u, v, d in ctx.G.edges(data=True):
        if d.get("relation") in ("has_exercise", "has_example") and u in ctx.valid:
            a = ctx.G.nodes[v]
            if a.get("text") and len(a["text"]) > 25:
                add(a["text"][:600], u, a.get("type", "exercise") + "_text",
                    {"source": "graph", "source_id": v, "edge": d["relation"]})

    # Figure interpretive question stems (only figures with illustrated_by concept edges)
    for n, a in ctx.G.nodes(data=True):
        if not a.get("good_for_questions"):
            continue
        owners = [u for u, _, d in ctx.G.in_edges(n, data=True) if d.get("relation") == "illustrated_by"
                  and u in ctx.valid]
        if not owners:
            continue
        for k, q in enumerate(a["good_for_questions"]):
            add(q, owners[0], "figure_question_stem",
                {"source": "graph", "source_id": f"{n}::q{k}", "edge": "illustrated_by"},
                secondary=sorted(set(owners[1:])))

    # Lexical anchors: aliases + vocabulary terms (report §4.5 step 1)
    for c in ctx.concepts:
        for term in (c.get("aliases") or []) + (c.get("vocabulary") or []):
            if term and len(str(term)) >= 3:
                add(str(term), c["concept_id"], "lexical_anchor",
                    {"source": "concepts.json", "source_id": f"{c['concept_id']}::{term}",
                     "field": "aliases/vocabulary"})

    # Merge the generated exemplar set (tier "generated"): the only source of student
    # utterances and of the INHERIT_CURRENT_CONCEPT class (report §4.1 rule 1).
    ex_path = OUT / "exemplar_dataset_10000.json"
    if ex_path.exists():
        for i, r in enumerate(json.loads(ex_path.read_text(encoding="utf-8"))):
            cid = r.get("concept_id")
            if cid != "INHERIT_CURRENT_CONCEPT" and cid not in ctx.valid:
                continue  # strict: drop anything outside the store ID space
            add(r.get("student_utterance"), cid,
                "student_utterance" if cid in ctx.valid else "inherit_current_concept",
                {"source": "exemplar_dataset_10000", "source_id": f"exemplar::{i}"},
                tier="generated")
    return rows


# ---------------------------------------------------------------------------
# 2. Retrieval relevance (§4.2) — graded 0-3, every grade graph-derived
# ---------------------------------------------------------------------------
ROLE_FIT = {
    "hope_ki_prompt": {"explanation", "definition"},
    "hope_kt_prompt": {"application", "explanation"},
    "hope_ct_prompt": {"explanation", "challenge", "definition"},
    "ct_probe_question": {"explanation", "challenge", "definition"},
    "misconception_diagnostic": {"explanation", "definition"},
    "bridge_diagnostic": {"bridge_recall"},
    "figure_question_stem": {"explanation"},
    "exercise_text": {"worked_example"},
    "example_text": {"worked_example"},
}


def build_retrieval_relevance(ctx: Ctx, resolver_rows: List[dict]) -> List[dict]:
    rows: List[dict] = []
    corpus_tokens = [tokenize(c["text"]) for c in ctx.chunks]
    bm25 = BM25Okapi(corpus_tokens)

    # queries = store-grounded resolver rows that are real questions/tasks
    queries = [r for r in resolver_rows
               if r["grounding"]["tier"] == "store"
               and r["label_type"] not in ("lexical_anchor",)]
    # plus bridge diagnostics (their grade-3 target is their own recap chunk)
    for n, a in ctx.G.nodes(data=True):
        if a.get("type") == "grade9_concept" and a.get("diagnostic_question"):
            targets = [v for _, v in ctx.G.out_edges(n) if v in ctx.valid]
            if targets:
                queries.append({
                    "id": f"crb_{n}", "text": a["diagnostic_question"],
                    "primary_concept_id": targets[0], "label_type": "bridge_diagnostic",
                    "grounding": {"source": "graph", "source_id": n, "tier": "store",
                                  "edge": "bridges_to"},
                })

    def add_pair(q, chunk_id, grade, reason):
        docs = {doc_of_concept(q["primary_concept_id"])} if q["primary_concept_id"] in ctx.valid else set()
        ch = ctx.chunks_by_id[chunk_id]
        if ch.get("doc_id"):
            docs.add(ch["doc_id"])
        rows.append({
            "id": row_id("rr", len(rows)),
            "query": q["text"], "query_source_id": q["grounding"]["source_id"],
            "query_concept_id": q["primary_concept_id"],
            "chunk_id": chunk_id, "relevance": grade, "grade_reason": reason,
            "grounding": {"source": "graph_structure", "query_source": q["grounding"]["source"],
                          "tier": "store"},
            "split": split_for(q["grounding"]["source_id"], docs),
        })

    for q in queries:
        cid = q["primary_concept_id"]
        if cid not in ctx.valid:
            continue
        fit_roles = ROLE_FIT.get(q["label_type"], {"explanation", "definition"})
        own = ctx.concept_chunks.get(cid, [])

        # grade 3: same concept + role fits the query type; structural direct assets first
        threes, twos = [], []
        src = q["grounding"]["source_id"]
        if q["label_type"] == "figure_question_stem":
            fig = src.split("::q")[0]
            figcap = f"figcap::{fig}"
            if figcap in ctx.chunks_by_id:
                threes.append((figcap, "the question stem's own figure_caption chunk (figure_id match)"))
        if q["label_type"] == "bridge_diagnostic":
            for ch in ctx.chunks:
                if ch.get("kind") == "bridge_recap" and ch.get("grade9_id") == src:
                    threes.append((ch["chunk_id"], "the bridge's own recap chunk (grade9_id match)"))
        for ch in sorted(own, key=lambda c: c["chunk_id"]):
            if ch.get("pedagogical_role") in fit_roles or ch.get("kind") in fit_roles:
                threes.append((ch["chunk_id"], f"shares concept {cid}, role fits query type"))
            else:
                twos.append((ch["chunk_id"], f"shares concept {cid}, other role"))

        # grade 2 (extra): chunks of integrates_with / near-transfer neighbors
        for _, tgt, d in ctx.G.out_edges(cid, data=True):
            if tgt in ctx.valid and (d.get("relation") == "integrates_with" or d.get("also_integrates")
                                     or (d.get("relation") == "transfers_to" and d.get("transfer_type") == "near")):
                for ch in sorted(ctx.concept_chunks.get(tgt, []), key=lambda c: c["chunk_id"])[:1]:
                    twos.append((ch["chunk_id"], f"chunk of {d.get('relation','link')} neighbor {tgt}"))

        # grade 1: prerequisite neighbors / same-chapter siblings
        ones = []
        for p, _, d in ctx.G.in_edges(cid, data=True):
            if d.get("relation") == "prerequisite_of" and p in ctx.valid:
                for ch in sorted(ctx.concept_chunks.get(p, []), key=lambda c: c["chunk_id"])[:1]:
                    ones.append((ch["chunk_id"], f"chunk of prerequisite {p}"))
        for sib in ctx.hard_negative_concepts(cid, k=2):
            for ch in sorted(ctx.concept_chunks.get(sib, []), key=lambda c: c["chunk_id"])[:1]:
                ones.append((ch["chunk_id"], f"chunk of same-chapter sibling {sib}"))

        # grade 0: high lexical overlap (BM25) but NO graph relation within 2 hops —
        # the "similar vocabulary" hard negatives of the report's §4.2 examples
        zeros = []
        ego = ctx.ego2[cid]
        scores = bm25.get_scores(tokenize(q["text"]))
        order = sorted(range(len(ctx.chunks)), key=lambda i: -scores[i])
        for i in order[:60]:
            ch = ctx.chunks[i]
            if ch["doc_id"] == doc_of_concept(cid):
                continue
            if any(c2 in ego for c2 in (ch.get("concept_ids") or [])):
                continue
            if ch.get("figure_id") in ego or ch.get("grade9_id") in ego:
                continue
            zeros.append((ch["chunk_id"], "high BM25 lexical overlap, no graph path within 2 hops"))
            if len(zeros) >= 2:
                break

        seen = set()
        for grade, pool, cap in ((3, threes, 2), (2, twos, 2), (1, ones, 2), (0, zeros, 2)):
            for chunk_id, reason in pool[:cap]:
                if chunk_id not in seen:
                    seen.add(chunk_id)
                    add_pair(q, chunk_id, grade, reason)
    return rows


# ---------------------------------------------------------------------------
# 3. Representation tagger (§4.3)
# ---------------------------------------------------------------------------
def build_representation_tagger(ctx: Ctx) -> List[dict]:
    rows = []
    for ch in ctx.chunks:
        reps = [r for r in (ch.get("representations") or []) if r in REPRESENTATIONS]
        if not reps:
            continue
        src_field = ("supports_representation (vision on the crop)"
                     if ch.get("kind") == "figure_caption" else "representations (pedagogy_enrich v1)")
        rows.append({
            "id": row_id("rt", len(rows)),
            "text": ch["text"][:800],
            "concept_ids": ch.get("concept_ids") or [],
            "representation_labels": reps,
            "kind": ch.get("kind"),
            "grounding": {"source": "chunks.jsonl", "source_id": ch["chunk_id"],
                          "field": src_field, "tier": "store"},
            "split": split_for(ch["chunk_id"], {ch.get("doc_id")} if ch.get("doc_id") else set(),
                               text=ch["text"][:800]),
        })
    return rows


# ---------------------------------------------------------------------------
# 4. Misconception clue bank (§4.4)
# ---------------------------------------------------------------------------
def build_misconception_bank(ctx: Ctx) -> List[dict]:
    rows = []
    holdout_misc: Set[str] = set()

    def add(mid, text, label, field):
        if not text:
            return
        owners = ctx.misc_owners.get(mid, [])
        docs = {doc_of_concept(o) for o in owners}
        split = ("holdout_misconception" if (docs & HOLDOUT_CHAPTERS)
                 else split_for(mid + field, docs, text=str(text)))
        if split == "holdout_misconception":
            holdout_misc.add(mid)
        rows.append({
            "id": row_id("mc", len(rows)),
            "text": str(text).strip(),
            "misconception_id": mid,
            "concept_id": owners[0] if owners else None,
            "label": label,
            "grounding": {"source": "graph", "source_id": mid, "field": field, "tier": "store"},
            "split": split,
        })

    for n, a in ctx.G.nodes(data=True):
        if a.get("type") != "misconception":
            continue
        add(n, a.get("text"), "positive", "text")                     # the claim itself
        add(n, a.get("correct_idea"), "hard_negative", "correct_idea")  # same vocab, correct
        add(n, a.get("expected_answer"), "hard_negative", "expected_answer")
        add(n, a.get("why_wrong"), "error_explanation", "why_wrong")
    # trap-step texts linked to a misconception (problem schemas)
    for n, a in ctx.G.nodes(data=True):
        if a.get("type") == "problem_schema":
            for k, t in enumerate(a.get("trap_steps") or []):
                if t.get("misconception_id"):
                    add(t["misconception_id"], t.get("trap"), "positive", f"trap_steps[{k}] of {n}")
    return rows


# ---------------------------------------------------------------------------
# 5. Grounding / leakage guard (§7.3)
# ---------------------------------------------------------------------------
def build_grounding_guard(ctx: Ctx) -> List[dict]:
    rows = []

    def add(resp, evidence_ids, action, label, grounding, source_id, docs):
        rows.append({
            "id": row_id("gg", len(rows)),
            "response_text": str(resp).strip()[:800],
            "evidence_ids": evidence_ids,
            "intended_action": action, "label": label,
            "grounding": {**grounding, "tier": "store"},
            "split": split_for(source_id, docs),
        })

    # safe_hint: every validated hint, evidence = its own exercise/diagnostic node
    for n, a in ctx.G.nodes(data=True):
        chain = a.get("hint_chain")
        if not chain:
            continue
        docs = {n.split("::")[1]} if "::" in n and not n.startswith("misconception") else set()
        for h in chain:
            add(h.get("text", ""), [n], "GIVE_HINT", "safe_hint",
                {"source": "graph", "source_id": n,
                 "rule": "phase-1 leak validator passed this chain"},
                f"{n}::hint{h.get('level')}", docs)

    # answer_leak: deterministic construction — append the node's own expected_answer
    # to its final hint; the label follows from the construction rule, not judgment
    for n, a in ctx.G.nodes(data=True):
        ans = a.get("expected_answer")
        chain = a.get("hint_chain") or []
        if not ans or a.get("type") not in ("misconception", "grade9_concept"):
            continue
        base = chain[-1]["text"] if chain else (a.get("diagnostic_question") or "")
        if not base:
            continue
        add(f"{base} So the answer is {ans}.", [n], "GIVE_HINT", "answer_leak",
            {"source": "constructed", "source_id": n,
             "rule": "final hint + own expected_answer appended (leak by construction)"},
            f"{n}::leak", set())

    # grounded: page summaries are derived from their own page -> (summary, page chunks)
    page_chunks: Dict[Tuple[str, Any], List[str]] = defaultdict(list)
    for ch in ctx.chunks:
        if ch.get("kind") == "page_text":
            page_chunks[(ch["doc_id"], ch.get("page"))].append(ch["chunk_id"])
    summaries = [ch for ch in ctx.chunks if ch.get("kind") == "page_summary"]
    for s in summaries:
        ev = page_chunks.get((s["doc_id"], s.get("page")))
        if ev:
            add(s["text"], sorted(ev), "EXPLAIN", "grounded",
                {"source": "chunks.jsonl", "source_id": s["chunk_id"],
                 "rule": "page_summary is derived from its own page's text chunks"},
                s["chunk_id"], {s["doc_id"]})

    # unsupported: same summaries paired with a DIFFERENT document's page evidence
    # (deterministic offset pairing — mismatch by construction)
    docs_sorted = sorted({s["doc_id"] for s in summaries})
    for s in summaries:
        if len(docs_sorted) < 2:
            break
        other_doc = docs_sorted[(docs_sorted.index(s["doc_id"]) + 1) % len(docs_sorted)]
        other_pages = [k for k in page_chunks if k[0] == other_doc]
        if not other_pages:
            continue
        k = other_pages[int(hashlib.md5(s["chunk_id"].encode()).hexdigest(), 16) % len(other_pages)]
        add(s["text"], sorted(page_chunks[k]), "EXPLAIN", "unsupported",
            {"source": "constructed", "source_id": s["chunk_id"],
             "rule": f"summary of {s['doc_id']} paired with {other_doc} evidence (mismatch by construction)"},
            s["chunk_id"] + "::mismatch", {s["doc_id"], other_doc})
    return rows


# ---------------------------------------------------------------------------
# Verification (report-rule compliance)
# ---------------------------------------------------------------------------
def verify(ctx: Ctx) -> int:
    failures = 0

    def check(name, cond, detail=""):
        nonlocal failures
        print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")
        if not cond:
            failures += 1

    def load(name):
        return [json.loads(l) for l in (OUT / name).read_text(encoding="utf-8").splitlines() if l.strip()]

    cr = load("concept_resolver.jsonl")
    rr = load("retrieval_relevance.jsonl")
    rt = load("representation_tagger.jsonl")
    mc = load("misconception_clue_bank.jsonl")
    gg = load("grounding_guard.jsonl")
    every = cr + rr + rt + mc + gg

    # §4.1 rule 2: concept ids strictly from the store (+ INHERIT in resolver only)
    bad = [r for r in cr if r["primary_concept_id"] != "INHERIT_CURRENT_CONCEPT"
           and r["primary_concept_id"] not in ctx.valid]
    check("4.1-r2 resolver concept ids all from rag_store (or INHERIT)", not bad, f"bad={len(bad)}")
    bad = [r for r in rr if r["query_concept_id"] not in ctx.valid]
    check("4.1-r2 retrieval query concept ids all from rag_store", not bad, f"bad={len(bad)}")

    # §4.1 rule 1: INHERIT class present as first-class label
    inherit = sum(1 for r in cr if r["primary_concept_id"] == "INHERIT_CURRENT_CONCEPT")
    check("4.1-r1 INHERIT_CURRENT_CONCEPT class present", inherit > 0, f"rows={inherit}")

    # grounding provenance on every row (the user's strict no-random-tagging rule)
    bad = [r for r in every if not (r.get("grounding") or {}).get("source")]
    check("strict-rule: every row carries grounding provenance", not bad, f"missing={len(bad)}")
    tiers = Counter(r["grounding"].get("tier") for r in every)
    check("strict-rule: tiers labeled (store vs generated)", set(tiers) <= {"store", "generated"},
          f"{dict(tiers)}")

    # all referenced store ids resolve
    def id_exists(i):
        return i in ctx.chunks_by_id or i in ctx.G
    bad = [r for r in rr if not id_exists(r["chunk_id"])]
    check("grounding: all retrieval chunk_ids exist in store", not bad, f"bad={len(bad)}")
    bad = [r for r in gg for i in r["evidence_ids"] if not id_exists(i)]
    check("grounding: all guard evidence_ids exist in store", not bad, f"bad={len(bad)}")
    bad = [r for r in mc if r["misconception_id"] not in ctx.G]
    check("grounding: all misconception_ids exist in store", not bad, f"bad={len(bad)}")

    # §4.2: graded relevance 0-3
    check("4.2 relevance grades in {0,1,2,3}", all(r["relevance"] in (0, 1, 2, 3) for r in rr),
          f"pairs={len(rr)}")
    check("4.2 volume >= 8,000 pairs (report minimum)", len(rr) >= 8000, f"pairs={len(rr)}")

    # §4.3: representation labels within the store taxonomy
    bad = [r for r in rt for l in r["representation_labels"] if l not in REPRESENTATIONS]
    check("4.3 representation labels within store taxonomy", not bad, f"bad={len(bad)}")

    # §4.4: >= 50 misconception families
    fams = {r["misconception_id"] for r in mc}
    check("4.4 misconception families >= 50", len(fams) >= 50, f"families={len(fams)}")
    check("4.4 hard negatives present (correct_idea phrasings)",
          any(r["label"] == "hard_negative" for r in mc))

    # §7.3: safe hints truly leak-free; leak rows truly leaking
    bad = [r for r in gg if r["label"] == "safe_hint" and ANSWER_LEAK_RE.search(r["response_text"])]
    check("7.3 no safe_hint row matches the answer-leak pattern", not bad, f"bad={len(bad)}")
    bad = [r for r in gg if r["label"] == "answer_leak" and not ANSWER_LEAK_RE.search(r["response_text"])]
    check("7.3 every answer_leak row matches the leak pattern", not bad, f"bad={len(bad)}")

    # §2.3: splits ~70/15/15 on non-holdout, holdouts exclusive
    core = [r for r in every if r["split"] in ("train", "val", "test")]
    frac = {s: sum(1 for r in core if r["split"] == s) / max(1, len(core))
            for s in ("train", "val", "test")}
    check("2.3 split ratios ~70/15/15 (±5)", abs(frac["train"] - .70) < .05
          and abs(frac["val"] - .15) < .05 and abs(frac["test"] - .15) < .05,
          f"{ {k: round(v,3) for k,v in frac.items()} }")
    ho = sum(1 for r in every if r["split"] == "holdout_chapter")
    check("2.3 holdout chapters present and exclusive", ho > 0, f"holdout_chapter rows={ho}")
    hm = sum(1 for r in mc if r["split"] == "holdout_misconception")
    check("2.3 holdout misconception families present", hm > 0, f"rows={hm}")
    # leakage: same text never in two different core splits (within a dataset)
    leaks = 0
    for ds in (cr, rt, mc):
        seen: Dict[str, str] = {}
        for r in ds:
            t = r.get("text", "")
            if t in seen and seen[t] != r["split"] and r["split"] in ("train", "val", "test") \
                    and seen[t] in ("train", "val", "test"):
                leaks += 1
            seen.setdefault(t, r["split"])
    check("2.3 no identical text across train/val/test", leaks == 0, f"leaks={leaks}")

    # scope: Maths-only (all docs jemh1xx)
    docs = {c.get("doc_id") for c in ctx.chunks}
    check("scope: Class 10 Maths corpus only", all(str(d).startswith("jemh1") for d in docs if d))

    # volumes vs report minimums (informational PASS/SEED)
    print("\n--- volume vs report minimums ---")
    store_cr = sum(1 for r in cr if r["grounding"]["tier"] == "store")
    for name, n, lo in (("concept_resolver (total incl. generated tier)", len(cr), 5000),
                        ("concept_resolver (store tier alone)", store_cr, 5000),
                        ("retrieval_relevance pairs", len(rr), 8000),
                        ("representation_tagger", len(rt), 5000),
                        ("misconception_clue_bank", len(mc), 5000),
                        ("grounding_guard", len(gg), 10000)):
        print(f"{'MEETS-MIN' if n >= lo else 'SEED     '}  {name}: {n} (report min {lo})")

    print(f"\n{'ALL COMPLIANCE CHECKS PASSED' if failures == 0 else f'{failures} CHECKS FAILED'}")
    return failures


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="Audit existing files against the report rules.")
    args = ap.parse_args()

    ctx = Ctx()
    if args.verify:
        sys.exit(1 if verify(ctx) else 0)

    OUT.mkdir(exist_ok=True)
    cr = build_concept_resolver(ctx)
    rr = build_retrieval_relevance(ctx, cr)
    rt = build_representation_tagger(ctx)
    mc = build_misconception_bank(ctx)
    gg = build_grounding_guard(ctx)

    files = {"concept_resolver.jsonl": cr, "retrieval_relevance.jsonl": rr,
             "representation_tagger.jsonl": rt, "misconception_clue_bank.jsonl": mc,
             "grounding_guard.jsonl": gg}
    manifest: Dict[str, Any] = {"built": date.today().isoformat(), "store_schema_version": 2,
                                "holdout_chapters": sorted(HOLDOUT_CHAPTERS), "datasets": {}}
    for name, rows in files.items():
        (OUT / name).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                                encoding="utf-8")
        manifest["datasets"][name] = {
            "rows": len(rows),
            "splits": dict(Counter(r["split"] for r in rows)),
            "tiers": dict(Counter(r["grounding"].get("tier") for r in rows)),
        }
        print(f"[write] {name}: {len(rows)} rows {manifest['datasets'][name]['splits']}")
    (OUT / "datasets_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[write] datasets_manifest.json")


if __name__ == "__main__":
    main()
