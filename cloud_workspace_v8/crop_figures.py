"""Phase 2 of RAG_upgrade_plan.md — visual asset extraction (closes G8, developer point 1).

Crops every figure/table (and as many display formulas as text-search finds) out of
the NCERT PDFs and links the crop into the graph so retrieval can SERVE the book's
own visual instead of describing it. Pipeline per page (local PyMuPDF, no API):

  * candidate boxes  = vector drawing clusters (page.cluster_drawings, padded,
    merged, tiny strokes dropped) + raster image rects (full-page watermark
    backgrounds excluded);
  * caption anchors  = "Fig. X.Y" / "Table X.Y" word spans (word-level, so two
    side-by-side captions on one printed line stay separate anchors);
  * each caption claims the nearest candidate box above/around it; when several
    captions share one composite box it is split between them (vertical split for
    side-by-side captions, horizontal bands for stacked ones);
  * crops are rendered straight from the PDF at 2x zoom into
    rag_store/figure_crops/<doc_id>/<safe_node_id>.png.

Stages (resumable; LLM results cached in rag_store/fig_crop_cache.jsonl):
  crops      local figure/table extraction + node matching (no API)
  formulas   text-span crops for formula nodes (no API; misses skipped silently)
  fallback   one Gemini bbox call per page that still has unmatched figure/table
             nodes (returns [y0,x0,y1,x1] in 0-1000 space)
  semantics  batched vision calls on the CROPS (A2.5): alt_text,
             supports_representation, disambiguates_misconceptions,
             good_for_questions; addresses_gap is derived from those
  sheet      HTML contact sheet for the 5-minute human review
  write      patch graph.json; embed caption mini-chunks (kind "figure_caption")
             into chunks.jsonl + FAISS; update meta.json

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

import fitz
import networkx as nx
import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types
from tqdm import tqdm

from rag_core import GEN_MODEL, make_client, embed_texts

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

VISION_MODEL = GEN_MODEL  # gemini-2.5-flash handles both
ZOOM = 2.0                # matches the existing page_images renders
PAD = 8.0                 # pdf-space padding around candidate boxes
MIN_AREA_PCT = 1.0        # clusters below this % of page area are rules/strokes
MAX_AREA_PCT = 65.0       # boxes above this are page background / watermark
CAPTION_RE = re.compile(r"^(fig|table)\.?$", re.IGNORECASE)
NUM_RE = re.compile(r"^\d+\.\d+")
REPRESENTATIONS = ["symbolic", "verbal", "graphical", "diagrammatic", "tabular",
                   "algebraic", "numeric", "geometric"]


# ---------------------------------------------------------------------------
# Shared cache / issue log (same pattern as enrich_concepts.py)
# ---------------------------------------------------------------------------
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


def call_json(client, contents, retries=2):
    last = None
    for _ in range(retries + 1):
        try:
            resp = client.models.generate_content(
                model=VISION_MODEL, contents=contents,
                config=types.GenerateContentConfig(response_mime_type="application/json"))
            return json.loads(resp.text or "{}")
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"LLM call failed after retries: {last}")


# ---------------------------------------------------------------------------
# Store / node helpers
# ---------------------------------------------------------------------------
def load_graph(store: Path) -> nx.DiGraph:
    return nx.node_link_graph(json.loads((store / "graph.json").read_text(encoding="utf-8")))


def doc_of_node(node_id: str) -> Optional[str]:
    parts = node_id.split("::")
    return parts[1] if len(parts) >= 3 else None


def safe_name(node_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", node_id)[:120]


def norm_label(s: str) -> str:
    """'Fig. 2.3 (i)' -> 'fig 2.3 (i)'; tolerant join key between captions and node labels."""
    s = str(s or "").lower().replace("figure", "fig")
    s = re.sub(r"[^a-z0-9().]+", " ", s).strip()
    s = re.sub(r"\bfig\b\.?", "fig", s)
    return re.sub(r"\s+", " ", s)


def visual_nodes(G: nx.DiGraph) -> Dict[str, List[Tuple[str, dict]]]:
    """{doc_id: [(node_id, attrs)]} for figure+table nodes that have a page."""
    out: Dict[str, List[Tuple[str, dict]]] = {}
    for n, a in G.nodes(data=True):
        if a.get("type") in ("figure", "table") and a.get("page"):
            doc = doc_of_node(n) or ("jemh102" if "::seed::" in n else None)
            if doc:
                out.setdefault(doc, []).append((n, a))
    return out


# ---------------------------------------------------------------------------
# Stage: crops (local)
# ---------------------------------------------------------------------------
def candidate_boxes(page: fitz.Page) -> List[fitz.Rect]:
    page_area = abs(page.rect) or 1.0
    boxes: List[fitz.Rect] = []
    try:
        clusters = page.cluster_drawings()
    except Exception:
        clusters = []
    for c in clusters:
        pct = 100.0 * abs(c) / page_area
        if MIN_AREA_PCT <= pct <= MAX_AREA_PCT:
            boxes.append(fitz.Rect(c) + (-PAD, -PAD, PAD, PAD))
    for img in page.get_images():
        for r in page.get_image_rects(img[0]):
            pct = 100.0 * abs(r) / page_area
            if MIN_AREA_PCT <= pct <= MAX_AREA_PCT:
                boxes.append(fitz.Rect(r) + (-PAD, -PAD, PAD, PAD))
    # merge overlaps
    merged: List[fitz.Rect] = []
    for b in sorted(boxes, key=lambda r: (r.y0, r.x0)):
        for m in merged:
            if m.intersects(b):
                m.include_rect(b)
                break
        else:
            merged.append(fitz.Rect(b))
    return [r & page.rect for r in merged]


def caption_spans(page: fitz.Page) -> List[Dict[str, Any]]:
    """Word-level caption anchors: 'Fig.'/'Table' + 'X.Y' (+ optional '(i)')."""
    words = page.get_text("words")  # x0,y0,x1,y1,word,block,line,word_no
    spans = []
    by_line: Dict[Tuple[int, int], List[tuple]] = {}
    for w in words:
        by_line.setdefault((w[5], w[6]), []).append(w)
    for line in by_line.values():
        line.sort(key=lambda w: w[7])
        i = 0
        while i < len(line):
            w = line[i]
            if CAPTION_RE.match(w[4]) and i + 1 < len(line) and NUM_RE.match(line[i + 1][4]):
                take = [w, line[i + 1]]
                j = i + 2
                if j < len(line) and re.match(r"^\(", line[j][4]):
                    take.append(line[j])
                    j += 1
                rect = fitz.Rect(take[0][:4])
                for t in take[1:]:
                    rect.include_rect(fitz.Rect(t[:4]))
                label = " ".join(t[4] for t in take)
                spans.append({"label": label, "rect": rect})
                i = j
            else:
                i += 1
    return spans


def assign_regions(page: fitz.Page, boxes: List[fitz.Rect], captions: List[dict]) -> Dict[int, fitz.Rect]:
    """caption index -> crop rect. Captions claim the box above/around them; a box
    claimed by several captions is split between them."""
    claims: Dict[int, List[int]] = {}
    for ci, cap in enumerate(captions):
        cr: fitz.Rect = cap["rect"]
        cx = (cr.x0 + cr.x1) / 2
        best, best_d = None, 1e9
        for bi, b in enumerate(boxes):
            if b.y1 > cr.y1 + 40 and not b.contains(cr):     # box clearly below caption
                continue
            if not (b.x0 - 30 <= cx <= b.x1 + 30):           # no horizontal overlap
                continue
            d = abs(cr.y0 - b.y1) if not b.contains(cr) else 0.0
            if d < best_d:
                best, best_d = bi, d
        if best is not None and best_d < 150:
            claims.setdefault(best, []).append(ci)

    regions: Dict[int, fitz.Rect] = {}
    for bi, cis in claims.items():
        b = boxes[bi]
        if len(cis) == 1:
            ci = cis[0]
            r = fitz.Rect(b)
            cr = captions[ci]["rect"]
            if b.contains(cr):                               # composite: figure sits above its caption
                r.y1 = cr.y0 - 2
            regions[ci] = r
            continue
        caps = sorted(cis, key=lambda ci: (captions[ci]["rect"].y0, captions[ci]["rect"].x0))
        ys = [captions[ci]["rect"].y0 for ci in caps]
        if max(ys) - min(ys) < 30:                           # side-by-side: split on x midpoints
            caps.sort(key=lambda ci: captions[ci]["rect"].x0)
            edges = [b.x0]
            for a, c in zip(caps, caps[1:]):
                edges.append((captions[a]["rect"].x1 + captions[c]["rect"].x0) / 2)
            edges.append(b.x1)
            for k, ci in enumerate(caps):
                regions[ci] = fitz.Rect(edges[k], b.y0, edges[k + 1], captions[ci]["rect"].y0 - 2)
        else:                                                # stacked: horizontal bands
            top = b.y0
            for ci in caps:
                cr = captions[ci]["rect"]
                regions[ci] = fitz.Rect(b.x0, top, b.x1, cr.y0 - 2)
                top = cr.y1 + 2
    return regions


def render_crop(page: fitz.Page, rect: fitz.Rect, out_path: Path) -> bool:
    rect = rect & page.rect
    if rect.is_empty or rect.width < 20 or rect.height < 15:
        return False
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), clip=rect, alpha=False)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(out_path))
    return True


def run_crops(store: Path, docs_root: Path, G: nx.DiGraph, manifest: dict, issues: IssueLog,
              cache: Optional[Cache] = None):
    """Local caption/cluster cropping. Nodes whose local crop was previously judged
    bad (badlocal:: markers) are skipped so only the Gemini fallback can re-crop them."""
    skip = {k.split("::", 1)[1] for k in (cache.mem if cache else {}) if k.startswith("badlocal::")}
    nodes_by_doc = {d: [(n, a) for n, a in nodes if n not in skip]
                    for d, nodes in visual_nodes(G).items()}
    crop_root = store / "figure_crops"
    total, matched = 0, 0
    for doc_id, nodes in tqdm(sorted(nodes_by_doc.items()), desc="cropping docs"):
        pdf = docs_root / f"{doc_id}.pdf"
        if not pdf.exists():
            issues.log("crops", f"{doc_id}: pdf not found at {pdf}")
            continue
        doc = fitz.open(str(pdf))
        by_page: Dict[int, List[Tuple[str, dict]]] = {}
        for n, a in nodes:
            by_page.setdefault(int(a["page"]), []).append((n, a))
        for pno, pnodes in sorted(by_page.items()):
            if pno < 1 or pno > len(doc):
                continue
            page = doc[pno - 1]
            boxes = candidate_boxes(page)
            captions = caption_spans(page)
            regions = assign_regions(page, boxes, captions)
            cap_by_norm = {norm_label(captions[ci]["label"]): (ci, r) for ci, r in regions.items()}
            used_caps = set()
            unmatched_nodes = []
            for n, a in pnodes:
                total += 1
                key = norm_label(a.get("label", ""))
                hit = None
                if key in cap_by_norm:
                    hit = cap_by_norm[key]
                else:  # tolerate '(i)' and trailing-dot mismatches
                    base = re.sub(r"\s*\(.*\)$", "", key).strip()
                    cands = [(ck, v) for ck, v in cap_by_norm.items()
                             if re.sub(r"\s*\(.*\)$", "", ck).strip() == base and v[0] not in used_caps]
                    if len(cands) == 1:
                        hit = cands[0][1]
                if hit:
                    ci, rect = hit
                    out = crop_root / doc_id / f"{safe_name(n)}.png"
                    if render_crop(page, rect, out):
                        used_caps.add(ci)
                        matched += 1
                        manifest[n] = {"image_path": str(out.relative_to(store)).replace("\\", "/"),
                                       "bbox": [round(v, 1) for v in tuple(rect)],
                                       "crop_source": "caption", "page": pno, "doc_id": doc_id}
                        continue
                unmatched_nodes.append((n, a))
            # single leftover node + single unclaimed box -> pair them
            free_boxes = [b for bi, b in enumerate(boxes)
                          if not any(b.intersects(fitz.Rect(m["bbox"])) for m in manifest.values()
                                     if m["doc_id"] == doc_id and m["page"] == pno)]
            if len(unmatched_nodes) == 1 and len(free_boxes) == 1:
                n, a = unmatched_nodes[0]
                out = crop_root / doc_id / f"{safe_name(n)}.png"
                if render_crop(page, free_boxes[0], out):
                    matched += 1
                    manifest[n] = {"image_path": str(out.relative_to(store)).replace("\\", "/"),
                                   "bbox": [round(v, 1) for v in tuple(free_boxes[0])],
                                   "crop_source": "cluster", "page": pno, "doc_id": doc_id}
        doc.close()
    print(f"[crops] matched {matched}/{total} figure/table nodes locally")


# ---------------------------------------------------------------------------
# Stage: formulas (local text-span crops)
# ---------------------------------------------------------------------------
def _norm_tokens(s: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", str(s or "").lower())


def find_formula_span(page_words: List[tuple], formula: str) -> Optional[fitz.Rect]:
    """Fuzzy sliding-window match of the formula against the page's word stream.

    The NCERT text layer renders math symbols as private-use glyphs, so exact
    search_for misses most formulas; matching only the alphanumeric tokens with
    rapidfuzz survives the glyph noise.
    """
    from rapidfuzz import fuzz
    target = _norm_tokens(formula)
    if len(target) < 2:
        return None
    target_str = " ".join(target)
    toks = [( " ".join(_norm_tokens(w[4])), w) for w in page_words]
    toks = [(t, w) for t, w in toks if t]
    if not toks:
        return None
    n = len(target)
    best_score, best_span = 0.0, None
    for k in range(max(2, n - 2), n + 4):
        for i in range(0, len(toks) - k + 1):
            window = " ".join(t for t, _ in toks[i:i + k])
            score = fuzz.ratio(target_str, window)
            if score > best_score:
                best_score, best_span = score, toks[i:i + k]
    if best_score < 80 or not best_span:
        return None
    rect = fitz.Rect(best_span[0][1][:4])
    for _, w in best_span[1:]:
        rect.include_rect(fitz.Rect(w[:4]))
    if rect.height > 60:  # matched words scattered over many lines: not a display formula span
        return None
    return rect + (-6, -4, 6, 4)


def run_formulas(store: Path, docs_root: Path, G: nx.DiGraph, manifest: dict):
    crop_root = store / "figure_crops"
    nodes_by_doc: Dict[str, List[Tuple[str, dict]]] = {}
    for n, a in G.nodes(data=True):
        if a.get("type") == "formula" and a.get("page") and a.get("formula") and n not in manifest:
            doc = doc_of_node(n)
            if doc:
                nodes_by_doc.setdefault(doc, []).append((n, a))
    found, total = 0, 0
    for doc_id, nodes in tqdm(sorted(nodes_by_doc.items()), desc="formula crops"):
        pdf = docs_root / f"{doc_id}.pdf"
        if not pdf.exists():
            continue
        doc = fitz.open(str(pdf))
        words_cache: Dict[int, List[tuple]] = {}
        for n, a in nodes:
            total += 1
            pno = int(a["page"])
            if pno < 1 or pno > len(doc):
                continue
            page = doc[pno - 1]
            if pno not in words_cache:
                words_cache[pno] = page.get_text("words")
            rect = find_formula_span(words_cache[pno], a["formula"])
            if rect is None:
                continue
            out = crop_root / doc_id / f"{safe_name(n)}.png"
            if render_crop(page, rect, out):
                found += 1
                manifest[n] = {"image_path": str(out.relative_to(store)).replace("\\", "/"),
                               "bbox": [round(v, 1) for v in tuple(rect)],
                               "crop_source": "text_span", "page": pno, "doc_id": doc_id}
        doc.close()
    print(f"[formulas] cropped {found}/{total} formula nodes (misses skipped by design)")


# ---------------------------------------------------------------------------
# Stage: fallback (Gemini bbox per page with unmatched figure/table nodes)
# ---------------------------------------------------------------------------
def run_fallback(store: Path, docs_root: Path, G: nx.DiGraph, manifest: dict, cache: Cache,
                 issues: IssueLog, client, limit=None):
    crop_root = store / "figure_crops"
    pending: Dict[Tuple[str, int], List[Tuple[str, dict]]] = {}
    for doc_id, nodes in visual_nodes(G).items():
        for n, a in nodes:
            if n not in manifest:
                pending.setdefault((doc_id, int(a["page"])), []).append((n, a))
    pages = sorted(pending.items())
    if limit:
        pages = pages[:limit]
    print(f"[fallback] {len(pages)} pages still have unmatched figure/table nodes")
    recovered = 0
    for (doc_id, pno), nodes in tqdm(pages, desc="gemini bbox fallback"):
        img_path = store / "page_images" / doc_id / f"page_{pno:03d}.png"
        if not img_path.exists():
            issues.log("fallback", f"{doc_id} p{pno}: no page render")
            continue
        import hashlib
        node_sig = hashlib.md5("|".join(sorted(n for n, _ in nodes)).encode()).hexdigest()[:8]
        key = f"fb::{doc_id}::p{pno}::{node_sig}"
        data = cache.get(key)
        if data is None:
            wanted = [{"node_id": n, "label": a.get("label", ""), "description": (a.get("description") or "")[:200]}
                      for n, a in nodes]
            prompt = f"""This is one page of an NCERT Class 10 Maths textbook. Locate each requested visual.
Return STRICT JSON: {{"items": [{{"node_id": "<copy exactly>", "found": true|false,
"box": [y0, x0, y1, x1]}}]}} where the box uses 0-1000 normalized coordinates of this image
(y0<y1, x0<x1), tightly enclosing the figure/table INCLUDING its axes/grid but EXCLUDING
surrounding paragraphs. Set found=false if the visual is not on this page.

Requested visuals:
{json.dumps(wanted, ensure_ascii=False)}
"""
            try:
                data = call_json(client, [types.Part.from_bytes(data=img_path.read_bytes(),
                                                                mime_type="image/png"), prompt])
            except RuntimeError as e:
                issues.log("fallback", f"{doc_id} p{pno}: {e}")
                data = {"items": []}
            cache.put(key, data)
        raw_items = data if isinstance(data, list) else (data.get("items") or []) if isinstance(data, dict) else []
        by_id = {i.get("node_id"): i for i in raw_items if isinstance(i, dict)}
        pdf = docs_root / f"{doc_id}.pdf"
        if not pdf.exists():
            issues.log("fallback", f"{doc_id}: pdf not found at {pdf}")
            continue
        doc = fitz.open(str(pdf))
        if pno < 1 or pno > len(doc):
            doc.close()
            continue
        page = doc[pno - 1]
        for n, a in nodes:
            item = by_id.get(n)
            box = (item or {}).get("box")
            if not item or not item.get("found") or not (isinstance(box, list) and len(box) == 4):
                issues.log("fallback", f"{n}: not located on {doc_id} p{pno}")
                continue
            y0, x0, y1, x1 = [max(0.0, min(1000.0, float(v))) for v in box]
            if y1 - y0 < 15 or x1 - x0 < 15:
                continue
            rect = fitz.Rect(x0 / 1000 * page.rect.width, y0 / 1000 * page.rect.height,
                             x1 / 1000 * page.rect.width, y1 / 1000 * page.rect.height)
            out = crop_root / doc_id / f"{safe_name(n)}.png"
            if render_crop(page, rect, out):
                recovered += 1
                manifest[n] = {"image_path": str(out.relative_to(store)).replace("\\", "/"),
                               "bbox": [round(v, 1) for v in tuple(rect)],
                               "crop_source": "gemini", "page": pno, "doc_id": doc_id}
        doc.close()
    print(f"[fallback] recovered {recovered} crops via Gemini bboxes")


# ---------------------------------------------------------------------------
# Stage: semantics (A2.5) — batched vision on the crops
# ---------------------------------------------------------------------------
def misconception_candidates(G: nx.DiGraph, node_id: str) -> List[str]:
    """Misconception ids of the concepts this visual illustrates (fallback: its chapter's)."""
    concepts = [u for u, _, d in G.in_edges(node_id, data=True) if d.get("relation") == "illustrated_by"]
    if not concepts:
        doc = doc_of_node(node_id)
        concepts = [n for n, a in G.nodes(data=True)
                    if a.get("type") == "concept" and a.get("chapter_doc") == doc]
    out = []
    for c in concepts:
        if c in G:
            out += [v for v in G.successors(c) if G.nodes[v].get("type") == "misconception"]
    return sorted(set(out))[:20]


def run_semantics(store: Path, G: nx.DiGraph, manifest: dict, cache: Cache, issues: IssueLog,
                  client, batch_size=5, limit=None):
    todo = [n for n, m in manifest.items()
            if G.nodes.get(n, {}).get("type") in ("figure", "table") and cache.get(f"sem::{n}") is None]
    if limit:
        todo = todo[:limit]
    print(f"[semantics] {len(todo)} cropped figures/tables need semantic enrichment")
    for start in tqdm(range(0, len(todo), batch_size), desc="crop semantics"):
        batch = todo[start:start + batch_size]
        parts: List[Any] = []
        items = []
        for k, n in enumerate(batch, 1):
            a = G.nodes[n]
            img = store / manifest[n]["image_path"]
            if not img.exists():
                continue
            parts.append(types.Part.from_bytes(data=img.read_bytes(), mime_type="image/png"))
            items.append({"image_number": k, "node_id": n, "label": a.get("label", ""),
                          "book_description": (a.get("description") or "")[:200],
                          "allowed_misconception_ids": misconception_candidates(G, n)})
        if not items:
            continue
        prompt = f"""You see {len(items)} cropped visuals from an NCERT Class 10 Maths textbook, in order.
For EACH, return pedagogical semantics. Return STRICT JSON:
{{"items": [{{
  "node_id": "<copy exactly>",
  "crop_quality": "good"|"bad"  (bad = ANY running body-text sentences or paragraph lines appear
      in the crop next to the figure, OR the figure is truncated/cut off, OR the crop shows
      multiple unrelated figures instead of the one named by its label. A clean crop contains
      ONLY the figure, its internal labels, and at most its 'Fig. X.Y' caption line),
  "alt_text": "<2-3 sentences: what it shows AND what a learner should notice in it>",
  "supports_representation": ["<subset of {REPRESENTATIONS}: which representation(s) this visual teaches>"],
  "disambiguates_misconceptions": ["<ids ONLY from that item's allowed_misconception_ids that this visual directly refutes; usually 0-2>"],
  "good_for_questions": ["<1-2 interpretive question stems answerable FROM this visual alone>"]
}}]}}
Item metadata (image k of the attached images corresponds to image_number k):
{json.dumps(items, ensure_ascii=False, indent=1)}
"""
        try:
            payload = call_json(client, parts + [prompt])
        except RuntimeError as e:
            issues.log("semantics", f"batch at {start}: {e}")
            continue
        raw = payload if isinstance(payload, list) else (payload.get("items") or []) if isinstance(payload, dict) else []
        got = {o.get("node_id"): o for o in raw if isinstance(o, dict)}
        for it in items:
            n = it["node_id"]
            o = got.get(n)
            if not o or not o.get("alt_text"):
                issues.log("semantics", f"{n}: missing/invalid semantics")
                continue
            reps = [r for r in (o.get("supports_representation") or []) if r in REPRESENTATIONS]
            mids = [m for m in (o.get("disambiguates_misconceptions") or [])
                    if m in it["allowed_misconception_ids"]]
            cache.put(f"sem::{n}", {
                "crop_quality": "bad" if o.get("crop_quality") == "bad" else "good",
                "alt_text": str(o["alt_text"]),
                "supports_representation": reps or ["graphical"],
                "disambiguates_misconceptions": mids,
                "good_for_questions": [str(q) for q in (o.get("good_for_questions") or [])][:2],
            })


def evict_bad_crops(store: Path, manifest: dict, cache: Cache, issues: IssueLog) -> int:
    """Drop crops the semantics judge flagged bad so the Gemini bbox fallback re-crops
    them (quality loop; keeps the contact-sheet bad-crop rate under the 5% gate)."""
    evicted = 0
    for key in list(cache.mem):
        if not key.startswith("sem::"):
            continue
        if cache.mem[key].get("crop_quality") != "bad":
            continue
        n = key.split("::", 1)[1]
        m = manifest.get(n)
        if not m or m.get("crop_source") == "gemini":   # already re-cropped once: keep, human reviews
            continue
        issues.log("quality", f"{n}: crop flagged bad ({m['crop_source']}), re-cropping via fallback")
        png = store / m["image_path"]
        if png.exists():
            png.unlink()
        del manifest[n]
        del cache.mem[key]                               # semantics re-runs on the new crop
        cache.put(f"badlocal::{n}", {"prior_source": m["crop_source"]})  # stop run_crops re-adding it
        evicted += 1
    if evicted:  # rewrite the cache file without the evicted sem:: rows
        with open(cache.path, "w", encoding="utf-8") as f:
            for k, v in cache.mem.items():
                f.write(json.dumps({"key": k, "data": v}, ensure_ascii=False) + "\n")
    print(f"[quality] evicted {evicted} bad crops for re-cropping")
    return evicted


# ---------------------------------------------------------------------------
# Stage: contact sheet
# ---------------------------------------------------------------------------
def run_sheet(store: Path, G: nx.DiGraph, manifest: dict):
    by_doc: Dict[str, List[str]] = {}
    for n, m in manifest.items():
        if G.nodes.get(n, {}).get("type") in ("figure", "table"):
            by_doc.setdefault(m["doc_id"], []).append(n)
    rows = ["<html><head><meta charset='utf-8'><style>body{font-family:sans-serif}"
            ".c{display:inline-block;margin:8px;border:1px solid #999;padding:6px;vertical-align:top;max-width:340px}"
            "img{max-width:320px;max-height:260px;display:block}small{color:#555}</style></head><body>"]
    for doc_id in sorted(by_doc):
        rows.append(f"<h2>{doc_id} ({len(by_doc[doc_id])} crops)</h2>")
        for n in sorted(by_doc[doc_id]):
            m = manifest[n]
            a = G.nodes[n]
            rel = m["image_path"].replace("figure_crops/", "", 1)
            rows.append(f"<div class='c'><img src='{rel}'>"
                        f"<b>{a.get('label','')}</b> <small>p.{m['page']} | {m['crop_source']} | {n}</small></div>")
    rows.append("</body></html>")
    out = store / "figure_crops" / "contact_sheet.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(rows), encoding="utf-8")
    print(f"[sheet] {out}")


# ---------------------------------------------------------------------------
# Stage: write — graph patch + caption chunks + FAISS append
# ---------------------------------------------------------------------------
def apply_crops(G: nx.DiGraph, manifest: dict, cache_mem: Dict[str, Any]) -> Tuple[int, int]:
    """Patch image_path/bbox/crop_source + crop semantics onto graph nodes, in place.

    Pure mutation, no file IO — used here and by build_index.py --with-crops so a
    full rebuild reproduces Phase 2 from the manifest + cache without LLM calls.
    """
    patched = 0
    for n, m in manifest.items():
        if n not in G:
            continue
        G.nodes[n].update(image_path=m["image_path"], bbox=m["bbox"], crop_source=m["crop_source"])
        patched += 1
    sem_count = 0
    for key, data in cache_mem.items():
        if key.startswith("sem::"):
            n = key.split("::", 1)[1]
            if n in G:
                G.nodes[n].update(data)
                G.nodes[n]["addresses_gap"] = (
                    [{"representation_missing": r} for r in data["supports_representation"]]
                    + [{"misconception_active": m} for m in data["disambiguates_misconceptions"]])
                sem_count += 1
    return patched, sem_count


def caption_chunk_rows(G: nx.DiGraph, manifest: dict, cache_mem: Dict[str, Any],
                       base_rows: List[dict]) -> List[dict]:
    """Build the retrievable figure_caption mini-chunk rows from cached semantics.

    Figures without illustrated_by edges inherit the concepts / median difficulty of
    their own page's text chunks so the store's 100% concept-link/difficulty guard
    holds. Shared by run_write and build_index.py's consolidated rebuild.
    """
    page_concepts: Dict[tuple, list] = {}
    page_diffs: Dict[tuple, list] = {}
    for r in base_rows:
        if r.get("kind") in ("page_text", "page_summary"):
            k = (r["doc_id"], r.get("page"))
            for c in r.get("concept_ids") or []:
                page_concepts.setdefault(k, []).append(c)
            if r.get("difficulty") is not None:
                page_diffs.setdefault(k, []).append(r["difficulty"])

    def fields(n: str) -> Tuple[list, int]:
        k = (manifest[n]["doc_id"], manifest[n]["page"])
        concepts = [u for u, _, d in G.in_edges(n, data=True) if d.get("relation") == "illustrated_by"]
        if not concepts:
            concepts = sorted(set(page_concepts.get(k, [])))[:3]
        diffs = page_diffs.get(k, [])
        difficulty = int(np.median(diffs)) if diffs else 4
        return concepts, difficulty

    rows = []
    for key, data in cache_mem.items():
        if not key.startswith("sem::"):
            continue
        n = key.split("::", 1)[1]
        if n not in G or n not in manifest:
            continue
        a = G.nodes[n]
        concepts, difficulty = fields(n)
        rows.append({
            "chunk_id": f"figcap::{n}", "doc_id": manifest[n]["doc_id"], "source_path": "",
            "page": manifest[n]["page"],
            "text": f"{a.get('label', '')}: {data['alt_text']}",
            "kind": "figure_caption", "figure_id": n,
            "image_path": manifest[n]["image_path"],
            "concept_ids": concepts,
            "pedagogical_role": "explanation",
            "difficulty": difficulty,
            "representations": data["supports_representation"],
        })
    return rows


def run_write(store: Path, G: nx.DiGraph, manifest: dict, cache: Cache, client):
    import faiss
    for fname in ("graph.json", "chunks.jsonl", "vector.faiss", "meta.json"):
        bak = store / f"{fname}.phase2.bak"
        if not bak.exists():
            shutil.copyfile(store / fname, bak)

    patched, sem_count = apply_crops(G, manifest, cache.mem)

    # 2. caption mini-chunks (kind figure_caption) -> chunks.jsonl + FAISS
    chunks_path = store / "chunks.jsonl"
    all_rows = [json.loads(l) for l in chunks_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    existing = {r["chunk_id"] for r in all_rows}

    candidate_rows = caption_chunk_rows(G, manifest, cache.mem, all_rows)
    by_id = {r["chunk_id"]: r for r in candidate_rows}

    # retro-patch caption rows written before concept/difficulty inheritance existed
    patched_rows = 0
    for r in all_rows:
        if r.get("kind") == "figure_caption" and (not r.get("concept_ids") or r.get("difficulty") is None):
            fresh = by_id.get(r["chunk_id"])
            if fresh:
                r["concept_ids"], r["difficulty"] = fresh["concept_ids"], fresh["difficulty"]
                patched_rows += 1

    new_rows = [r for r in candidate_rows if r["chunk_id"] not in existing]
    if new_rows:
        vecs = embed_texts(client, [r["text"] for r in new_rows], "RETRIEVAL_DOCUMENT")
        index = faiss.read_index(str(store / "vector.faiss"))
        index.add(np.ascontiguousarray(vecs.astype(np.float32)))
        faiss.write_index(index, str(store / "vector.faiss"))
    if new_rows or patched_rows:
        # order must stay identical to FAISS insertion order: update in place, append new
        out_rows = all_rows + new_rows
        chunks_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out_rows),
                               encoding="utf-8")

    (store / "graph.json").write_text(json.dumps(nx.node_link_data(G), ensure_ascii=False, indent=2),
                                      encoding="utf-8")

    meta_path = store / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["num_chunks"] = meta.get("num_chunks", 0) + len(new_rows)
    meta["phase2_visual_assets"] = {
        "date": date.today().isoformat(), "cropped_nodes": patched,
        "semantic_enriched": sem_count, "caption_chunks_added": len(new_rows),
        "crop_sources": {src: sum(1 for m in manifest.values() if m["crop_source"] == src)
                         for src in ("caption", "cluster", "text_span", "gemini")},
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[write] patched {patched} nodes ({sem_count} with semantics), added {len(new_rows)} caption chunks")


# ---------------------------------------------------------------------------
def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="rag_store")
    ap.add_argument("--docs", default=None, help="PDF root (default: meta.json docs_root)")
    ap.add_argument("--only", choices=["crops", "formulas", "fallback", "semantics", "sheet", "write"],
                    default=None)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    store = Path(args.store)
    meta = json.loads((store / "meta.json").read_text(encoding="utf-8"))
    docs_root = Path(args.docs or meta["docs_root"])
    G = load_graph(store)
    cache = Cache(store / "fig_crop_cache.jsonl")
    issues = IssueLog(store / "fig_crop_issues.log")

    manifest_path = store / "figure_crops" / "crops_manifest.json"
    manifest: Dict[str, Any] = (json.loads(manifest_path.read_text(encoding="utf-8"))
                                if manifest_path.exists() else {})

    stages = [args.only] if args.only else ["crops", "formulas", "fallback", "semantics", "sheet", "write"]
    client = make_client() if any(s in stages for s in ("fallback", "semantics", "write")) else None

    if "crops" in stages:
        run_crops(store, docs_root, G, manifest, issues, cache=cache)
    if "formulas" in stages:
        run_formulas(store, docs_root, G, manifest)
    if "fallback" in stages:
        run_fallback(store, docs_root, G, manifest, cache, issues, client, limit=args.limit)
    if "semantics" in stages:
        run_semantics(store, G, manifest, cache, issues, client, limit=args.limit)
        # quality loop: bad local crops are evicted and re-cropped via Gemini bboxes
        if not args.limit and evict_bad_crops(store, manifest, cache, issues):
            run_fallback(store, docs_root, G, manifest, cache, issues, client)
            run_semantics(store, G, manifest, cache, issues, client)
    if "sheet" in stages:
        run_sheet(store, G, manifest)
    if "write" in stages:
        run_write(store, G, manifest, cache, client)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
