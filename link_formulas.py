"""Chapter-wide concept -> formula links (derived artifact, 2026-07-20).

Problem: graph.json has 911 formula nodes (644 carry a rendered ``image_path``
crop under figure_crops/<doc>/formula_*.png), but the vision pass emitted
``likely_concept_ids`` almost nowhere — the 266 ``has_formula`` edges all hang
off the 7 jemh102 concepts, so the T9 display channel could never show a
formula image for any other chapter (tier-3 teaching visuals cover only
figure_caption chunks).

This script derives concept links for EVERY formula node deterministically
(no LLM, no embeddings — reproducible and free) and writes a NEW artifact,
``rag_store/formula_links.json``; graph.json / chunks.jsonl / concepts.json
stay untouched (read-only per project rules). TutorLoop merges the links into
its ``visuals_by_concept`` index at load time.

Per (formula, same-chapter concept) pair the score is:

    0.6 * page_score  — the concept's share of chunk concept_scores mass on
                        the formula's page (chunks.jsonl rows carry page +
                        concept_ids + concept_scores); the formula inherits
                        the concepts of the page it appears on
  + 0.4 * name_score  — fraction of the concept's name/alias/slug tokens found
                        in the formula's slug + formula text (plural-stripped,
                        with a small trig synonym table)
  + 0.1 definitional bonus   (slug says identity/theorem/definition/formula/…)
  - 0.25 worked-example penalty (slug says given/step/derived/calculation/… —
                        instance-specific equations from solved examples must
                        not outrank the definitional form)

Links with score >= 0.35 are kept, at most 3 concepts per formula. Per
concept, links are stored sorted by score desc, so consumers can take the
first image-bearing row as "the" formula visual.

Run:  python link_formulas.py          (prints per-chapter before/after coverage)
"""

from __future__ import annotations

import collections
import datetime
import json
import re
from pathlib import Path

STORE = Path(__file__).parent / "rag_store"
OUT = STORE / "formula_links.json"

WEIGHT_PAGE = 0.6
WEIGHT_NAME = 0.4
BONUS_DEFINITIONAL = 0.1
PENALTY_INSTANCE = 0.25
THRESHOLD = 0.35
TOP_K_CONCEPTS = 3

STOP_TOKENS = {"of", "the", "a", "an", "and", "for", "to", "in", "with",
               "angle", "angles", "s"}
DEFINITIONAL_WORDS = {"identity", "identities", "theorem", "definition",
                      "formula", "law", "lemma", "property", "relation",
                      "ratio", "ratios"}
INSTANCE_WORDS = {"given", "step", "calculation", "calculated", "derived",
                  "value", "substitution", "substituted", "simplified",
                  "lhs", "rhs", "initial", "final", "specific", "example",
                  "evaluation", "resulting", "rearrangement", "proof",
                  "verification"}
# slug-token synonyms so e.g. concept "fundamental_trig_ratios" meets
# formula text "tan A = sin A / cos A"
SYNONYMS = {"trig": "trigonometric", "sine": "sin", "cosine": "cos",
            "tangent": "tan", "cosecant": "cosec", "secant": "sec",
            "cotangent": "cot"}


def tokens(text: str) -> set[str]:
    out: set[str] = set()
    for t in re.findall(r"[a-z]+", text.lower()):
        if t in STOP_TOKENS:
            continue
        t = t.rstrip("s") or t
        out.add(t)
        if t in SYNONYMS:
            out.add(SYNONYMS[t])
    return out


def build_links() -> dict:
    graph = json.loads((STORE / "graph.json").read_text(encoding="utf-8"))
    concepts = json.loads((STORE / "concepts.json").read_text(encoding="utf-8"))
    chunk_rows = [json.loads(l) for l in
                  (STORE / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    concepts_by_doc: dict[str, list[dict]] = collections.defaultdict(list)
    for c in concepts:
        concepts_by_doc[c["concept_id"].split("__")[0]].append(c)
    concept_tokens = {
        c["concept_id"]: tokens(c["concept_id"].split("__", 1)[1].replace("_", " ")
                                + " " + c.get("name", "")
                                + " " + " ".join(c.get("aliases") or []))
        for c in concepts
    }

    # (doc, page) -> concept -> summed concept_scores mass across chunk rows
    page_weight: dict[tuple, dict[str, float]] = collections.defaultdict(
        lambda: collections.defaultdict(float))
    for r in chunk_rows:
        if r.get("page") is None:
            continue
        scores = r.get("concept_scores") or {}
        for cid in (r.get("concept_ids") or []):
            page_weight[(r["doc_id"], r["page"])][cid] += scores.get(cid, 0.5)

    formula_nodes = [n for n in graph["nodes"] if n.get("type") == "formula"]

    links: list[dict] = []
    for node in formula_nodes:
        _, doc, slug = node["id"].split("::", 2)
        slug_words = set(re.findall(r"[a-z]+", slug))
        is_instance = bool(slug_words & INSTANCE_WORDS)
        is_definitional = bool(slug_words & DEFINITIONAL_WORDS) and not is_instance
        formula_toks = tokens(slug.replace("_", " ") + " " + (node.get("formula") or ""))
        weights = page_weight.get((doc, node.get("page")), {})
        w_max = max(weights.values()) if weights else 0.0

        scored = []
        for c in concepts_by_doc.get(doc, []):
            cid = c["concept_id"]
            page_score = (weights.get(cid, 0.0) / w_max) if w_max else 0.0
            ctoks = concept_tokens[cid]
            name_score = len(ctoks & formula_toks) / len(ctoks) if ctoks else 0.0
            score = (WEIGHT_PAGE * page_score + WEIGHT_NAME * name_score
                     + (BONUS_DEFINITIONAL if is_definitional else 0.0)
                     - (PENALTY_INSTANCE if is_instance else 0.0))
            if score >= THRESHOLD:
                scored.append((round(score, 4), round(page_score, 4),
                               round(name_score, 4), cid))
        scored.sort(reverse=True)
        for score, page_score, name_score, cid in scored[:TOP_K_CONCEPTS]:
            links.append({
                "concept_id": cid,
                "formula_id": node["id"],
                "score": score,
                "page_score": page_score,
                "name_score": name_score,
                "page": node.get("page"),
                "has_image": bool(node.get("image_path")),
                "image_path": node.get("image_path"),
                "formula": node.get("formula") or "",
            })

    # stable order: per concept, best link first (consumers take pool[0])
    links.sort(key=lambda l: (l["concept_id"], -l["score"], l["formula_id"]))
    return {"graph": graph, "concepts": concepts, "links": links}


def coverage_table(concepts: list[dict], covered: set[str]) -> dict[str, dict]:
    per_ch: dict[str, dict] = {}
    for c in concepts:
        ch = c["concept_id"].split("__")[0]
        row = per_ch.setdefault(ch, {"concepts": 0, "with_formula_visual": 0})
        row["concepts"] += 1
        if c["concept_id"] in covered:
            row["with_formula_visual"] += 1
    return per_ch


def main() -> None:
    built = build_links()
    graph, concepts, links = built["graph"], built["concepts"], built["links"]

    # BEFORE: image-bearing formulas reachable via graph has_formula edges
    image_formulas = {n["id"]: n for n in graph["nodes"]
                      if n.get("type") == "formula" and n.get("image_path")}
    concept_ids = {c["concept_id"] for c in concepts}
    before_covered = {e["source"] for e in graph["edges"]
                      if e.get("relation") == "has_formula"
                      and e["source"] in concept_ids and e["target"] in image_formulas}
    after_covered = {l["concept_id"] for l in links if l["has_image"]}

    before = coverage_table(concepts, before_covered)
    after = coverage_table(concepts, after_covered)
    print(f"{'chapter':10s} {'concepts':>8s} {'before':>7s} {'after':>6s}")
    for ch in sorted(before):
        print(f"{ch:10s} {before[ch]['concepts']:8d} "
              f"{before[ch]['with_formula_visual']:7d} {after[ch]['with_formula_visual']:6d}")
    tot = len(concepts)
    print(f"{'TOTAL':10s} {tot:8d} {len(before_covered):7d} {len(after_covered):6d}")

    out = {
        "version": 1,
        "built": datetime.datetime.now().isoformat(timespec="seconds"),
        "params": {"weight_page": WEIGHT_PAGE, "weight_name": WEIGHT_NAME,
                   "bonus_definitional": BONUS_DEFINITIONAL,
                   "penalty_instance": PENALTY_INSTANCE,
                   "threshold": THRESHOLD, "top_k_concepts": TOP_K_CONCEPTS},
        "coverage": {"before_graph_edges": {k: v["with_formula_visual"] for k, v in before.items()},
                     "after": {k: v["with_formula_visual"] for k, v in after.items()}},
        "links": links,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    n_img = sum(1 for l in links if l["has_image"])
    print(f"\nwrote {OUT}  ({len(links)} links, {n_img} to image-bearing formulas)")


if __name__ == "__main__":
    main()
