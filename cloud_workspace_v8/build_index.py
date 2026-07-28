from __future__ import annotations
import argparse, json, os, re, shutil
from pathlib import Path
from typing import Any, Dict, List
import numpy as np
import networkx as nx
import faiss
from tqdm import tqdm
from google import genai
from dotenv import load_dotenv

from rag_core import (
    chunk_text, normalize_text, make_client, embed_texts, cosine_faiss_index,
    build_bm25, simple_tokenize, embed_query, graph_expand, resolve_top_concepts,
    EmbedCache,
)
from pdf_vision import render_pdf_pages, summarize_page_with_vision
from pedagogy_enrich import enrich_chunks
# Phase 1-3 overlays (plan Phase 4): all cache-driven, so a full rebuild
# reproduces the enriched store without a single new LLM call.
from enrich_concepts import Cache as JsonlCache, IssueLog, apply_enrichment, repair_dangling_edges
from crop_figures import apply_crops, caption_chunk_rows
from build_bridges import run_detect as bridges_detect, run_graph as bridges_graph, \
    run_dangling as bridges_dangling

STORE_SCHEMA_VERSION = 2

ALLOWED = {".pdf", ".txt", ".md", ".docx"}

def read_text_file(path: Path) -> str:
    if path.suffix.lower() in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() == ".docx":
        try:
            from docx import Document
        except Exception as e:
            raise RuntimeError("Install python-docx for .docx support") from e
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    raise ValueError(f"Unsupported text file: {path}")

def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", str(s or "").strip())
    return s.strip("_").lower() or "unknown"

def load_seed(seed_path: Path):
    return json.loads(seed_path.read_text(encoding="utf-8"))

def build_base_graph(seed: Dict[str, Any]) -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_node("chapter_2", type="chapter", name=seed.get("chapter_name", "Chapter"), subject=seed.get("subject", ""), grade=seed.get("grade", ""))

    for c in seed.get("core_concepts", []):
        cid = c["concept_id"]
        G.add_node(cid, type="concept", **c)
        G.add_edge("chapter_2", cid, relation="contains")

        for p in c.get("prerequisites", []):
            G.add_edge(p, cid, relation="prerequisite_of")

        for rep in c.get("representations", []):
            rep_id = f"rep_{slugify(rep)}"
            if not G.has_node(rep_id):
                G.add_node(rep_id, type="representation", description=rep)
            G.add_edge(cid, rep_id, relation="represented_by")

        # Seed-declared misconceptions become first-class graph nodes. Previously
        # these were thrown away and only vision-extracted ones survived.
        for m in c.get("misconceptions", []):
            misc_id = f"misconception::{slugify(m)}"
            if not G.has_node(misc_id):
                G.add_node(misc_id, type="misconception", text=m, source="seed", status="active")
            G.add_edge(cid, misc_id, relation="has_misconception")

        # Curriculum transfer links (near/far). These give the Pedagogical Decision
        # Engine an explicit map for transfer problems across chapters/subjects.
        for t in c.get("transfer_links", []):
            target = t.get("target") if isinstance(t, dict) else str(t)
            if not target:
                continue
            tid = f"concept::{slugify(target)}"
            if not G.has_node(tid):
                G.add_node(tid, type="external_concept", name=target,
                           chapter=(t.get("target_chapter") if isinstance(t, dict) else ""))
            G.add_edge(cid, tid, relation="transfers_to",
                       transfer_type=(t.get("transfer_type", "near") if isinstance(t, dict) else "near"),
                       note=(t.get("note", "") if isinstance(t, dict) else ""))

    # Author-curated figure map: pin known figures to their concepts up front so a
    # vision miss on one page does not lose the figure->concept link.
    for fm in seed.get("figure_map", []):
        fid = f"figure::seed::{slugify(fm.get('label', ''))}"
        G.add_node(fid, type="figure", page=fm.get("page"), label=fm.get("label", ""),
                   description=fm.get("description", ""), source="seed")
        if fm.get("concept_id"):
            G.add_edge(fm["concept_id"], fid, relation="illustrated_by")

    return G


def _add_concept(G: nx.DiGraph, chap_id: str, c: Dict[str, Any]) -> None:
    """Attach one concept node (and its prereq/representation/misconception/transfer edges)."""
    cid = c["concept_id"]
    G.add_node(cid, type="concept", **c)
    G.add_edge(chap_id, cid, relation="contains")

    for p in c.get("prerequisites", []):
        G.add_edge(p, cid, relation="prerequisite_of")

    for rep in c.get("representations", []):
        rep_id = f"rep_{slugify(rep)}"
        if not G.has_node(rep_id):
            G.add_node(rep_id, type="representation", description=rep)
        G.add_edge(cid, rep_id, relation="represented_by")

    for m in c.get("misconceptions", []):
        misc_id = f"misconception::{slugify(m)}"
        if not G.has_node(misc_id):
            G.add_node(misc_id, type="misconception", text=m, source="seed", status="active")
        G.add_edge(cid, misc_id, relation="has_misconception")

    for t in c.get("transfer_links", []):
        target = t.get("target") if isinstance(t, dict) else str(t)
        if not target:
            continue
        tid = f"concept::{slugify(target)}"
        if not G.has_node(tid):
            G.add_node(tid, type="external_concept", name=target,
                       chapter=(t.get("target_chapter") if isinstance(t, dict) else ""))
        G.add_edge(cid, tid, relation="transfers_to",
                   transfer_type=(t.get("transfer_type", "near") if isinstance(t, dict) else "near"),
                   note=(t.get("note", "") if isinstance(t, dict) else ""))


def build_multi_graph(seed: Dict[str, Any]) -> nx.DiGraph:
    """Build a curriculum graph from a multi-chapter seed ({"chapters": [...]})."""
    G = nx.DiGraph()
    for ch in seed.get("chapters", []):
        doc = ch.get("doc_id", "")
        chap_id = f"chapter::{doc}"
        G.add_node(chap_id, type="chapter", name=ch.get("chapter_name", doc), doc_id=doc,
                   subject=seed.get("subject", ""), grade=seed.get("grade", ""))
        for c in ch.get("core_concepts", []):
            _add_concept(G, chap_id, c)
    return G


def is_multi_seed(seed: Dict[str, Any]) -> bool:
    return "chapters" in seed


def seed_concepts(seed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flat list of all concept cards, for either seed format. Carries chapter_doc when present."""
    if is_multi_seed(seed):
        return [c for ch in seed.get("chapters", []) for c in ch.get("core_concepts", [])]
    return seed.get("core_concepts", [])


def _concept_id_list(seed: Dict[str, Any]) -> List[str]:
    return [c["concept_id"] for c in seed_concepts(seed)]

# Non-pedagogical documents to keep out of the store (preface, etc.). jemh1ps is
# just the textbook preface; it adds noise and no concepts.
DEFAULT_EXCLUDE_DOCS = {"jemh1ps"}

def discover_files(root: Path, exclude: set | None = None) -> List[Path]:
    exclude = exclude or set()
    return sorted([p for p in root.rglob("*")
                   if p.is_file() and p.suffix.lower() in ALLOWED and p.stem not in exclude])


def emit_enrichment_edges(G: nx.DiGraph, concept_rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """Plan Phase 4 step 1: first-class graph edges from the enriched card fields.

    - concept -[transfers_to]-> concept   (typed near; far links get external nodes)
    - concept -[integrates_with]-> concept (carries the representation pair, KI)
    - concept -[probes]-> ct_probe nodes   (CT probes as retrievable graph objects)
    """
    valid = {c["concept_id"] for c in concept_rows}
    stats = {"transfers_to": 0, "integrates_with": 0, "probes": 0}
    for c in concept_rows:
        cid = c["concept_id"]
        for t in c.get("transfer_links") or []:
            if not isinstance(t, dict) or not t.get("target"):
                continue
            tgt, ttype = t["target"], t.get("transfer_type", "near")
            if tgt in valid:
                if not G.has_edge(cid, tgt):
                    G.add_edge(cid, tgt, relation="transfers_to", transfer_type=ttype,
                               note=t.get("note", ""))
                    stats["transfers_to"] += 1
            elif ttype == "far":
                ext = f"external::{slugify(tgt)}"
                if ext not in G:
                    G.add_node(ext, type="external_concept", name=tgt,
                               chapter=t.get("target_chapter", ""))
                if not G.has_edge(cid, ext):
                    G.add_edge(cid, ext, relation="transfers_to", transfer_type="far",
                               note=t.get("note", ""))
                    stats["transfers_to"] += 1
        for l in c.get("integration_links") or []:
            tgt = l.get("concept_id") if isinstance(l, dict) else None
            if tgt not in valid:
                continue
            if not G.has_edge(cid, tgt):
                G.add_edge(cid, tgt, relation="integrates_with",
                           representation_pair=l.get("representation_pair", ""),
                           note=l.get("note", ""))
            else:
                # DiGraph holds one edge per pair; when a transfers_to edge already
                # exists, carry the KI link as attributes on it instead of dropping it.
                G[cid][tgt].update(also_integrates=True,
                                   representation_pair=l.get("representation_pair", ""),
                                   integration_note=l.get("note", ""))
            stats["integrates_with"] += 1
        for k, p in enumerate(c.get("ct_probes") or []):
            if not isinstance(p, dict) or not p.get("question"):
                continue
            pid = f"ct_probe::{cid}::{k}"
            if pid not in G:
                G.add_node(pid, type="ct_probe", kind=p.get("kind", "why"),
                           question=p["question"], expected_insight=p.get("expected_insight", ""),
                           difficulty=c.get("difficulty"), source="generated")
                stats["probes"] += 1
            if not G.has_edge(cid, pid):
                G.add_edge(cid, pid, relation="probes")
    return stats

def ingest(root: Path, out: Path, seed_path: Path, exclude: set | None = None,
           with_crops: bool = False, with_bridges: bool = False):
    print(f"Starting ingestion...")
    print(f"Looking for documents in: {root.absolute()}")
    print(f"Looking for seed file at: {seed_path.absolute()}")

    exclude = (exclude or set()) | DEFAULT_EXCLUDE_DOCS
    load_dotenv()
    client = make_client()

    try:
        seed = load_seed(seed_path)
        print("Successfully loaded seed file.")
    except Exception as e:
        print(f"FAILED to load seed file: {e}")
        return

    multi = is_multi_seed(seed)
    G = build_multi_graph(seed) if multi else build_base_graph(seed)
    print(f"Seed format: {'multi-chapter' if multi else 'single-chapter'}")
    print(f"Excluding docs: {sorted(exclude)}")
    out.mkdir(parents=True, exist_ok=True)

    docs = discover_files(root, exclude=exclude)
    print(f"Found {len(docs)} supported files.")

    if not docs:
        print("EXITING: No documents found. Check your --docs path.")
        return

    chunk_rows = []
    concept_rows = seed_concepts(seed)
    known_concept_ids = _concept_id_list(seed)
    page_summaries = []
    image_dir = out / "page_images"
    image_dir.mkdir(exist_ok=True)

    # --- RECOVERY & CACHE MECHANISM ADDED HERE ---
    cache_path = out / "vision_cache.jsonl"
    cached_pages = set()
    if cache_path.exists():
        print("Found existing vision cache. Loading previously processed pages...")
        with open(cache_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                data = json.loads(line)
                if data.get("doc_id") in exclude:  # keep preface/excluded docs out of the graph
                    continue
                page_summaries.append(data)
                cached_pages.add(f"{data['doc_id']}::p{data['page']}")
        print(f"Loaded {len(cached_pages)} pages from cache. These will be skipped to save API costs.")

    # 1. Vision Extraction Phase
    for pdf in [p for p in docs if p.suffix.lower() == ".pdf"]:
        pages = render_pdf_pages(pdf, image_dir / pdf.stem)
        for p in tqdm(pages, desc=f"Vision parsing: {pdf.name}"):
            cache_key = f"{pdf.stem}::p{p['page']}"
            
            # Skip if already processed in a previous crashed run
            if cache_key in cached_pages:
                continue
                
            try:
                summary = summarize_page_with_vision(client, p["image_path"], p["text"], p["page"], known_concept_ids)
                summary["source_path"] = str(pdf)
                summary["doc_id"] = pdf.stem
                page_summaries.append(summary)
                
                # Append to cache instantly
                with open(cache_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(summary, ensure_ascii=False) + "\n")
                    
            except Exception as e:
                err_summary = {
                    "page": p["page"], "source_path": str(pdf), "doc_id": pdf.stem,
                    "concise_summary": "", "concept_candidates": [], "equations": [],
                    "tables": [], "figures": [], "examples": [], "exercises": [], 
                    "misconceptions": [f"vision_error:{e}"], "retrieval_tags": []
                }
                page_summaries.append(err_summary)
                with open(cache_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(err_summary, ensure_ascii=False) + "\n")

    # 2. Text Chunking Phase
    print("Chunking documents...")
    for path in docs:
        if path.suffix.lower() == ".pdf":
            pages = render_pdf_pages(path, image_dir / path.stem)
            for p in pages:
                for j, ch in enumerate(chunk_text(normalize_text(p["text"]))):
                    chunk_rows.append({
                        "chunk_id": f"{path.stem}::page_{p['page']:03d}::chunk_{j:03d}",
                        "doc_id": path.stem,
                        "source_path": str(path),
                        "page": p["page"],
                        "text": ch,
                        "kind": "page_text",
                    })
        else:
            txt = read_text_file(path)
            for j, ch in enumerate(chunk_text(normalize_text(txt))):
                chunk_rows.append({
                    "chunk_id": f"{path.stem}::chunk_{j:03d}",
                    "doc_id": path.stem,
                    "source_path": str(path),
                    "page": None,
                    "text": ch,
                    "kind": "document_text",
                })

    # 3. Dynamic Graph Building from Vision Extraction
    print("Building Knowledge Graph Nodes...")
    for ps in page_summaries:
        doc_id = ps["doc_id"]
        page_num = ps["page"]
        
        # BULLETPROOF PARSING: Handle LLM returning Strings instead of Dicts
        # Figures
        for fig in ps.get("figures", []):
            if isinstance(fig, dict):
                label = fig.get('label') or f'p{page_num}'
                desc = fig.get("what_it_shows") or ""
                cids = fig.get("likely_concept_ids") or []
            else:
                label = f'p{page_num}_{str(fig)[:10]}'
                desc = str(fig)
                cids = []
                
            fig_id = f"fig::{doc_id}::{slugify(label)}"
            G.add_node(fig_id, type="figure", page=page_num, label=label, description=desc)
            for cid in cids:
                G.add_edge(cid, fig_id, relation="illustrated_by")
                
        # Equations / Formulas
        for eq in ps.get("equations", []):
            if isinstance(eq, dict):
                eq_name = eq.get('name') or f'p{page_num}'
                formula = eq.get("formula") or ""
                cids = eq.get("likely_concept_ids") or []
            else:
                eq_name = f'p{page_num}_{str(eq)[:10]}'
                formula = str(eq)
                cids = []
                
            eq_id = f"formula::{doc_id}::{slugify(eq_name)}"
            G.add_node(eq_id, type="formula", page=page_num, formula=formula)
            for cid in cids:
                G.add_edge(cid, eq_id, relation="has_formula")

        # Misconceptions
        for misc in ps.get("misconceptions", []):
            if isinstance(misc, dict):
                misc_text = misc.get("text") or ""
                cids = misc.get("likely_concept_ids") or []
            else:
                misc_text = str(misc)
                cids = []
            if misc_text and not misc_text.startswith("vision_error"):
                misc_id = f"misconception::{slugify(misc_text[:20])}"
                G.add_node(misc_id, type="misconception", text=misc_text)
                for cid in cids:
                    G.add_edge(cid, misc_id, relation="has_misconception")

        # Worked Examples (now carry ZPD difficulty + Bloom level for the decision engine)
        for ex in ps.get("examples", []):
            if isinstance(ex, dict):
                label = ex.get('label') or f'p{page_num}'
                content = ex.get("content") or ""
                cids = ex.get("likely_concept_ids") or []
                difficulty = ex.get("difficulty")
                bloom = ex.get("bloom_level") or ""
            else:
                label = f'p{page_num}_{str(ex)[:10]}'
                content = str(ex)
                cids = []
                difficulty = None
                bloom = ""

            ex_id = f"example::{doc_id}::{slugify(label)}"
            G.add_node(ex_id, type="example", page=page_num, text=content,
                       difficulty=difficulty, bloom_level=bloom, pedagogical_role="worked_example")
            for cid in cids:
                G.add_edge(cid, ex_id, relation="has_example")

        # Exercises (difficulty lets us pick practice vs. challenge by learner ZPD)
        for exe in ps.get("exercises", []):
            if isinstance(exe, dict):
                label = exe.get('label') or f'p{page_num}'
                content = exe.get("content") or ""
                cids = exe.get("likely_concept_ids") or []
                difficulty = exe.get("difficulty")
                bloom = exe.get("bloom_level") or ""
                role = exe.get("pedagogical_role") or "practice"
            else:
                label = f'p{page_num}_{str(exe)[:10]}'
                content = str(exe)
                cids = []
                difficulty = None
                bloom = ""
                role = "practice"

            exe_id = f"exercise::{doc_id}::{slugify(label)}"
            G.add_node(exe_id, type="exercise", page=page_num, text=content,
                       difficulty=difficulty, bloom_level=bloom, pedagogical_role=role)
            for cid in cids:
                G.add_edge(cid, exe_id, relation="has_exercise")

        # Tables
        for tab in ps.get("tables", []):
            if isinstance(tab, dict):
                label = tab.get("label") or f"p{page_num}"
                shows = tab.get("what_it_shows") or ""
                cids = tab.get("likely_concept_ids") or []
            else:
                label = f"p{page_num}_{str(tab)[:10]}"
                shows = str(tab)
                cids = []
            tab_id = f"table::{doc_id}::{slugify(label)}"
            G.add_node(tab_id, type="table", page=page_num, label=label, description=shows)
            for cid in cids:
                G.add_edge(cid, tab_id, relation="illustrated_by")

        # Applications -> transfer edges (near/far). This is the cross-concept
        # bridging the architecture asks for but the old pipeline never extracted.
        for app in ps.get("applications", []):
            if not isinstance(app, dict):
                continue
            text = app.get("text") or ""
            if not text:
                continue
            app_id = f"application::{doc_id}::{slugify(text[:24])}"
            G.add_node(app_id, type="application", page=page_num, text=text,
                       target_domain=app.get("target_domain") or "",
                       transfer_type=app.get("transfer_type") or "near")
            for cid in (app.get("source_concept_ids") or []):
                G.add_edge(cid, app_id, relation="transfers_to",
                           transfer_type=app.get("transfer_type") or "near")

    # Add summary chunks to the chunking list
    for ps in page_summaries:
        if isinstance(ps, dict) and ps.get("concise_summary"):
            chunk_rows.append({
                "chunk_id": f"{ps.get('doc_id', 'unknown')}::page_{ps.get('page', 0):03d}::summary",
                "doc_id": ps.get("doc_id", "unknown"),
                "source_path": ps.get("source_path", ""),
                "page": ps.get("page", 0),
                "text": ps.get("concise_summary"),
                "kind": "page_summary",
            })

    # 4. Bulk Vectorization & Semantic Linking
    print("Vectorizing concepts and chunks in bulk...")
    embed_cache = EmbedCache(out)  # plan scope rule: never re-embed existing content

    concept_vocab = []
    concept_doc = []  # parallel to concept_vocab: the chapter doc_id each concept belongs to
    for c in concept_rows:
        text_rep = f"{c['name']} {c.get('summary', '')} {' '.join(c.get('aliases', []))}"
        concept_vocab.append((c["concept_id"], text_rep))
        concept_doc.append(c.get("chapter_doc"))

    concept_texts = [t for _, t in concept_vocab]
    concept_vectors = embed_cache.embed(client, concept_texts, "RETRIEVAL_DOCUMENT")

    chunk_texts = [r["text"] for r in chunk_rows]
    chunk_vectors = embed_cache.embed(client, chunk_texts, "RETRIEVAL_DOCUMENT")

    chunk_vecs_np = np.array(chunk_vectors, dtype=np.float32)
    concept_vecs_np = np.array(concept_vectors, dtype=np.float32)
    
    similarity_matrix = chunk_vecs_np @ concept_vecs_np.T

    # Assign concepts to each chunk. We always keep the single best concept (so no
    # chunk is left orphaned and query-time concept filtering can't collapse to a
    # full scan), then add up to two more that are both reasonably similar AND close
    # to the top match. Scores are persisted so the retrieval layer can weight them.
    FLOOR = float(os.getenv("CHUNK_CONCEPT_FLOOR", "0.30"))
    MARGIN = float(os.getenv("CHUNK_CONCEPT_MARGIN", "0.08"))
    # For a multi-chapter seed, a chunk may only link to concepts of its OWN chapter
    # (matched by doc_id). This is what stops e.g. a Real Numbers chunk being tagged
    # with a Polynomials concept. Single-chapter seeds have chapter_doc=None for all
    # concepts, so the candidate set is global (original behaviour).
    doc_to_cols: Dict[str, List[int]] = {}
    for j, d in enumerate(concept_doc):
        doc_to_cols.setdefault(d, []).append(j)
    all_cols = list(range(len(concept_vocab)))

    for i, row in enumerate(chunk_rows):
        cols = doc_to_cols.get(row.get("doc_id")) or all_cols
        sims = similarity_matrix[i][cols]
        local_order = np.argsort(sims)[::-1]
        best = float(sims[local_order[0]])
        kept = [cols[local_order[0]]]
        for li in local_order[1:3]:
            s = float(sims[li])
            if s >= FLOOR and (best - s) <= MARGIN:
                kept.append(cols[li])
        row["concept_ids"] = [concept_vocab[idx][0] for idx in kept]
        row["concept_scores"] = {concept_vocab[idx][0]: round(float(similarity_matrix[i][idx]), 4) for idx in kept}

    # Pedagogical enrichment: tag every chunk with role / difficulty / representation /
    # Bloom level so the Pedagogical Decision Engine can filter evidence by learner need.
    enrich_chunks(client, chunk_rows, out / "pedagogy_cache.jsonl")

    # ------------------------------------------------------------------
    # Phase 1-3 overlays (plan Phase 4 step 2) — all cache-driven
    # ------------------------------------------------------------------
    issues = IssueLog(out / "build_issues.log")
    overlay_meta: Dict[str, Any] = {}

    enrich_path = out / "concept_enrich_cache.jsonl"
    if enrich_path.exists():
        ecache = JsonlCache(enrich_path)
        repaired = repair_dangling_edges(G, set(known_concept_ids), issues)
        stats = apply_enrichment(concept_rows, G, ecache.mem)
        stats["edges"] = emit_enrichment_edges(G, concept_rows)
        stats["repaired_edges"] = repaired
        overlay_meta["phase1_enrichment"] = stats
        print(f"Enrichment overlay: {stats}")

    extra_rows: List[Dict[str, Any]] = []
    bridge_path = out / "bridge_cache.jsonl"
    if with_bridges and bridge_path.exists():
        bridges_detect(chunk_rows)  # tags bridge_recall roles on intro/recall chunks
        bcache = JsonlCache(bridge_path)
        recap_rows = bridges_graph(G, bcache)
        bridges_dangling(G, concept_rows, issues)
        extra_rows += recap_rows
        overlay_meta["phase3_bridges"] = {
            "grade9_concepts": sum(1 for _, a in G.nodes(data=True) if a.get("type") == "grade9_concept"),
            "bridge_recap_chunks": len(recap_rows),
        }

    manifest_path = out / "figure_crops" / "crops_manifest.json"
    if with_crops and manifest_path.exists():
        fcache = JsonlCache(out / "fig_crop_cache.jsonl")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        patched, sem_count = apply_crops(G, manifest, fcache.mem)
        figcap_rows = caption_chunk_rows(G, manifest, fcache.mem, chunk_rows)
        extra_rows += figcap_rows
        overlay_meta["phase2_visual_assets"] = {"cropped_nodes": patched,
                                                "semantic_enriched": sem_count,
                                                "caption_chunks": len(figcap_rows)}

    if extra_rows:
        print(f"Embedding {len(extra_rows)} overlay chunks (figure captions + bridge recaps)...")
        extra_vecs = embed_cache.embed(client, [r["text"] for r in extra_rows], "RETRIEVAL_DOCUMENT")
        chunk_rows = chunk_rows + extra_rows
        chunk_texts = [r["text"] for r in chunk_rows]
        chunk_vecs_np = np.vstack([chunk_vecs_np, np.array(extra_vecs, dtype=np.float32)])

    # 5. Build Final FAISS & BM25 Indexes
    print("Building local indexes...")
    faiss_vectors = np.ascontiguousarray(chunk_vecs_np.astype(np.float32))
    index = cosine_faiss_index(faiss_vectors)
    bm25 = build_bm25(chunk_texts)

    # 6. Save State
    (out / "chunks.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in chunk_rows), encoding="utf-8")
    (out / "concepts.json").write_text(json.dumps(concept_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "graph.json").write_text(json.dumps(nx.node_link_data(G), ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "page_summaries.json").write_text(json.dumps(page_summaries, indent=2, ensure_ascii=False), encoding="utf-8")
    faiss.write_index(index, str(out / "vector.faiss"))
    
    node_type_counts: Dict[str, int] = {}
    for _, attrs in G.nodes(data=True):
        node_type_counts[attrs.get("type", "unknown")] = node_type_counts.get(attrs.get("type", "unknown"), 0) + 1
    edge_type_counts: Dict[str, int] = {}
    for _, _, attrs in G.edges(data=True):
        rel = attrs.get("relation", "unknown")
        edge_type_counts[rel] = edge_type_counts.get(rel, 0) + 1
    role_counts: Dict[str, int] = {}
    for r in chunk_rows:
        role_counts[r.get("pedagogical_role", "unknown")] = role_counts.get(r.get("pedagogical_role", "unknown"), 0) + 1

    (out / "meta.json").write_text(json.dumps({
        "store_schema_version": STORE_SCHEMA_VERSION,
        "docs_root": str(root),
        "num_docs": len(docs),
        "num_chunks": len(chunk_rows),
        "seed": (f"{len(seed.get('chapters', []))} chapters" if multi else seed.get("chapter_name", "unknown")),
        "num_concepts": len(concept_rows),
        "embedding_model": os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001"),
        "generation_model": os.getenv("GEMINI_GEN_MODEL", "gemini-2.5-flash"),
        "graph_nodes": G.number_of_nodes(),
        "graph_edges": G.number_of_edges(),
        "node_type_counts": node_type_counts,
        "edge_type_counts": edge_type_counts,
        "chunk_role_counts": role_counts,
        **overlay_meta,
    }, indent=2), encoding="utf-8")

    print(f"Built index at: {out}")
    print(f"Total Chunks: {len(chunk_rows)}")
    print(f"Graph Entities Built: {G.number_of_nodes()} Nodes, {G.number_of_edges()} Edges")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", required=True)
    ap.add_argument("--out", default="rag_store")
    ap.add_argument("--seed", default="chapter_seed_polynomials.json")
    ap.add_argument("--exclude", default="", help="Comma-separated doc stems to exclude (added to defaults).")
    ap.add_argument("--with-crops", action="store_true",
                    help="Apply Phase 2 visual assets from figure_crops/crops_manifest.json + fig_crop_cache.jsonl.")
    ap.add_argument("--with-bridges", action="store_true",
                    help="Apply Phase 3 grade-9 bridges from bridge_cache.jsonl.")
    args = ap.parse_args()
    extra = {s.strip() for s in args.exclude.split(",") if s.strip()}
    ingest(Path(args.docs), Path(args.out), Path(args.seed), exclude=extra,
           with_crops=args.with_crops, with_bridges=args.with_bridges)