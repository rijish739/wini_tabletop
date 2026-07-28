"""Generate a full-textbook curriculum seed from existing page summaries.

The hand-written seed (chapter_seed_polynomials.json) only covers Chapter 2, so
when the index is built over the whole book every chunk gets force-linked to a
Polynomials concept. This script consolidates the per-page `concise_summary`
fields already stored in rag_store/page_summaries.json into a clean per-chapter
concept list, producing a multi-chapter seed (`curriculum_seed_full.json`).

It reuses the vision summaries we already paid for: one generation call per
chapter, no re-rendering and no re-vision cost.
"""

from __future__ import annotations
import argparse, json, re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from google.genai import types

from rag_core import make_client, GEN_MODEL

# Answer keys / appendices carry little conceptual content; skip concept mining.
SKIP_DOCS = {"jemh1an"}


def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", str(s or "").strip())
    return s.strip("_").lower() or "concept"


def chapter_prompt(doc_id: str, summaries: List[str]) -> str:
    joined = "\n".join(f"- {s}" for s in summaries if s)
    return f"""
You are building a curriculum knowledge graph for a Class 10 (NCERT) Mathematics textbook chapter.
Below are page-level summaries for ONE chapter (document id: {doc_id}).

From them, identify the chapter's core concepts. Return STRICT JSON:
{{
  "chapter_name": string,
  "core_concepts": [
    {{
      "concept_id": short snake_case slug unique within this chapter (e.g. "euclid_division_lemma"),
      "name": human readable concept name,
      "aliases": [string],
      "summary": one or two sentence definition,
      "prerequisites": [concept_id],   // ONLY ids that also appear in this same core_concepts list
      "representations": subset of ["symbolic","verbal","graphical","diagrammatic","algebraic","tabular"],
      "misconceptions": [short string describing a likely student misconception]
    }}
  ]
}}

Rules:
- Produce between 4 and 10 concepts that genuinely define the chapter's content.
- prerequisites must reference only concept_ids you list in THIS chapter (no external ids).
- Keep concepts conceptual (ideas/skills), not individual exercises or figures.

Page summaries:
{joined}
"""


def generate(page_summaries_path: Path, out_path: Path, subject: str, grade: int) -> None:
    load_dotenv()
    client = make_client()
    ps = json.loads(page_summaries_path.read_text(encoding="utf-8"))

    by_doc: "OrderedDict[str, List[str]]" = OrderedDict()
    for p in ps:
        doc = p.get("doc_id")
        if not doc:
            continue
        by_doc.setdefault(doc, []).append(p.get("concise_summary") or "")

    chapters: List[Dict[str, Any]] = []
    for doc_id, summaries in by_doc.items():
        if doc_id in SKIP_DOCS:
            print(f"  skip {doc_id} (answer key / non-conceptual)")
            continue
        print(f"  mining concepts for {doc_id} ({len(summaries)} pages)...")
        data: Dict[str, Any] = {}
        for attempt in range(3):  # LLM JSON is occasionally malformed; retry before giving up
            try:
                resp = client.models.generate_content(
                    model=GEN_MODEL,
                    contents=chapter_prompt(doc_id, summaries),
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        max_output_tokens=8192,
                    ),
                )
                data = json.loads(resp.text or "{}")
                break
            except Exception as e:  # noqa: BLE001
                print(f"    attempt {attempt + 1} failed for {doc_id}: {e}")
        if not data.get("core_concepts"):
            print(f"    GIVING UP on {doc_id} after 3 attempts.")
            continue

        raw_concepts = data.get("core_concepts") or []
        # Namespace ids per chapter so they are globally unique and traceable to a doc.
        id_map: Dict[str, str] = {}
        for c in raw_concepts:
            local = slugify(c.get("concept_id") or c.get("name"))
            id_map[local] = f"{doc_id}__{local}"
            # also map the raw (unslugified) id in case prerequisites used it verbatim
            if c.get("concept_id"):
                id_map[c["concept_id"]] = f"{doc_id}__{local}"

        concepts: List[Dict[str, Any]] = []
        for c in raw_concepts:
            local = slugify(c.get("concept_id") or c.get("name"))
            gid = f"{doc_id}__{local}"
            prereqs = []
            for p in (c.get("prerequisites") or []):
                mapped = id_map.get(p) or id_map.get(slugify(p))
                if mapped and mapped != gid:
                    prereqs.append(mapped)
            concepts.append({
                "concept_id": gid,
                "chapter_doc": doc_id,
                "name": c.get("name") or local.replace("_", " ").title(),
                "aliases": [a for a in (c.get("aliases") or []) if isinstance(a, str)],
                "summary": c.get("summary") or "",
                "prerequisites": list(dict.fromkeys(prereqs)),
                "representations": [r for r in (c.get("representations") or []) if isinstance(r, str)] or ["verbal"],
                "misconceptions": [m for m in (c.get("misconceptions") or []) if isinstance(m, str)],
            })

        chapters.append({
            "doc_id": doc_id,
            "chapter_name": data.get("chapter_name") or doc_id,
            "core_concepts": concepts,
        })
        print(f"    -> {len(concepts)} concepts ({data.get('chapter_name')})")

    # Prefer the hand-curated Polynomials seed for its chapter (jemh102): it has
    # vetted concepts, prerequisites, misconceptions, and near/far transfer links.
    curated = Path("chapter_seed_polynomials.json")
    poly_doc = "jemh102"
    if curated.exists() and poly_doc in by_doc:
        cs = json.loads(curated.read_text(encoding="utf-8"))
        cmap = {c["concept_id"]: f"{poly_doc}__{c['concept_id']}" for c in cs.get("core_concepts", [])}
        concepts = []
        for c in cs.get("core_concepts", []):
            c2 = dict(c)
            c2["concept_id"] = cmap[c["concept_id"]]
            c2["chapter_doc"] = poly_doc
            c2["prerequisites"] = [cmap.get(p, p) for p in c.get("prerequisites", [])]
            concepts.append(c2)
        chapters = [ch for ch in chapters if ch["doc_id"] != poly_doc]
        chapters.append({"doc_id": poly_doc, "chapter_name": cs.get("chapter_name", "Polynomials"),
                         "core_concepts": concepts})
        print(f"  injected curated Polynomials seed for {poly_doc}: {len(concepts)} concepts.")

    chapters.sort(key=lambda ch: ch["doc_id"])
    seed = {"subject": subject, "grade": grade, "chapters": chapters}
    out_path.write_text(json.dumps(seed, indent=2, ensure_ascii=False), encoding="utf-8")
    total = sum(len(ch["core_concepts"]) for ch in chapters)
    print(f"\nWrote {out_path} : {len(chapters)} chapters, {total} concepts.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--summaries", default="rag_store/page_summaries.json")
    ap.add_argument("--out", default="curriculum_seed_full.json")
    ap.add_argument("--subject", default="mathematics")
    ap.add_argument("--grade", type=int, default=10)
    args = ap.parse_args()
    generate(Path(args.summaries), Path(args.out), args.subject, args.grade)
