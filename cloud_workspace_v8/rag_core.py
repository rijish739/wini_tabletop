from __future__ import annotations
import dataclasses, json, math, os, re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import networkx as nx
import faiss
from rapidfuzz import fuzz
from rank_bm25 import BM25Okapi
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
GEN_MODEL = os.getenv("GEMINI_GEN_MODEL", "gemini-2.5-flash")
VECTOR_DIM = int(os.getenv("VECTOR_DIM", "3072"))

class RetrievalHit(BaseModel):
    score: float
    doc_id: str
    source_path: str
    chunk_id: str
    text: str
    concept_ids: List[str] = Field(default_factory=list)
    page: int | None = None
    figure_labels: List[str] = Field(default_factory=list)
    kind: str = "chunk"

def make_client() -> genai.Client:
    return genai.Client()

def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def simple_tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())

def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 180) -> List[str]:
    text = normalize_text(text)
    if not text:
        return []
    paras = re.split(r"\n\s*\n", text)
    chunks, current = [], ""
    def flush():
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""
    for para in paras:
        if not para.strip():
            continue
        para = para.strip()
        if len(para) > chunk_size:
            flush()
            start = 0
            while start < len(para):
                end = min(len(para), start + chunk_size)
                piece = para[start:end].strip()
                if piece:
                    chunks.append(piece)
                if end >= len(para):
                    break
                start = max(end - overlap, start + 1)
            continue
        if len(current) + len(para) + 2 <= chunk_size:
            current = f"{current}\n\n{para}".strip() if current else para
        else:
            flush()
            current = para
    flush()
    return chunks

EMBED_BATCH = int(os.getenv("GEMINI_EMBED_BATCH", "100"))

def embed_texts(client: genai.Client, texts: List[str], task_type: str) -> np.ndarray:
    if not texts:
        return np.zeros((0, VECTOR_DIM), dtype=np.float32)
    # The Vertex embedding endpoint accepts at most 250 instances per request, so
    # split large corpora into batches and concatenate the results.
    vectors: List[np.ndarray] = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start:start + EMBED_BATCH]
        resp = client.models.embed_content(
            model=EMBED_MODEL,
            contents=batch,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=VECTOR_DIM,
            ),
        )
        vectors.extend(np.array(e.values, dtype=np.float32) for e in resp.embeddings)
    mat = np.vstack(vectors).astype(np.float32)
    faiss.normalize_L2(mat)
    return mat

def embed_query(client: genai.Client, text: str) -> np.ndarray:
    return embed_texts(client, [text], task_type="RETRIEVAL_QUERY")[0]


class EmbedCache:
    """Disk-backed embedding cache keyed by sha1(text).

    The upgrade plan's scope rule is "no re-embedding of existing content", while
    Phase 4 demands a full rebuild — this cache is what makes both true at once.
    Storage: <dir>/embed_cache_keys.json (ordered sha1 list) + embed_cache_vecs.npy.
    """

    def __init__(self, cache_dir: Path):
        import hashlib
        self._sha1 = lambda t: hashlib.sha1(t.encode("utf-8")).hexdigest()
        self.keys_path = Path(cache_dir) / "embed_cache_keys.json"
        self.vecs_path = Path(cache_dir) / "embed_cache_vecs.npy"
        if self.keys_path.exists() and self.vecs_path.exists():
            keys = json.loads(self.keys_path.read_text(encoding="utf-8"))
            vecs = np.load(self.vecs_path)
            self.index = {k: i for i, k in enumerate(keys)}
            self.keys = keys
            self.vecs = vecs
        else:
            self.index, self.keys = {}, []
            self.vecs = np.zeros((0, VECTOR_DIM), dtype=np.float32)

    def add(self, texts: List[str], vectors: np.ndarray) -> None:
        new_keys, new_rows = [], []
        for t, v in zip(texts, vectors):
            k = self._sha1(t)
            if k not in self.index:
                self.index[k] = len(self.keys) + len(new_keys)
                new_keys.append(k)
                new_rows.append(v)
        if new_keys:
            self.keys.extend(new_keys)
            self.vecs = np.vstack([self.vecs, np.array(new_rows, dtype=np.float32)])

    def save(self) -> None:
        self.keys_path.write_text(json.dumps(self.keys), encoding="utf-8")
        np.save(self.vecs_path, self.vecs)

    def embed(self, client: genai.Client, texts: List[str], task_type: str) -> np.ndarray:
        """embed_texts with cache: only texts not seen before hit the API."""
        missing = [t for t in texts if self._sha1(t) not in self.index]
        # dedupe while preserving order
        missing = list(dict.fromkeys(missing))
        if missing:
            print(f"EmbedCache: {len(texts) - len(missing)} cached, embedding {len(missing)} new texts")
            fresh = embed_texts(client, missing, task_type)
            self.add(missing, fresh)
            self.save()
        else:
            print(f"EmbedCache: all {len(texts)} texts cached")
        return np.array([self.vecs[self.index[self._sha1(t)]] for t in texts], dtype=np.float32)

def cosine_faiss_index(vectors: np.ndarray) -> faiss.IndexFlatIP:
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors.astype(np.float32))
    return index

def build_bm25(corpus: List[str]) -> BM25Okapi:
    return BM25Okapi([simple_tokenize(x) for x in corpus])

def retrieve_semantic(index: faiss.IndexFlatIP, query_vec: np.ndarray, k: int = 10):
    q = query_vec.astype(np.float32).reshape(1, -1)
    faiss.normalize_L2(q)
    scores, ids = index.search(q, k)
    return scores[0].tolist(), ids[0].tolist()

def graph_expand(G: nx.DiGraph, concept_ids: List[str], depth: int = 1) -> List[str]:
    seen = set(concept_ids)
    frontier = list(concept_ids)
    for _ in range(depth):
        nxt = []
        for cid in frontier:
            if cid not in G:
                continue
            for nbr in G.successors(cid):
                if nbr not in seen:
                    seen.add(nbr)
                    nxt.append(nbr)
            for nbr in G.predecessors(cid):
                if nbr not in seen:
                    seen.add(nbr)
                    nxt.append(nbr)
        frontier = nxt
    return list(seen)

def resolve_top_concepts(query: str, concept_cards: List[Dict[str, Any]], client: genai.Client, k: int = 5):
    texts = [f"{c['name']}\n{c.get('summary','')}\nAliases: {', '.join(c.get('aliases', []))}" for c in concept_cards]
    idx = cosine_faiss_index(embed_texts(client, texts, "RETRIEVAL_DOCUMENT"))
    qv = embed_query(client, query)
    scores, ids = retrieve_semantic(idx, qv, k=min(k, len(concept_cards)))
    out = []
    for s, i in zip(scores, ids):
        if i < 0:
            continue
        c = concept_cards[i]
        out.append({"concept_id": c["concept_id"], "name": c["name"], "score": float(s)})
    return out

def rank_hits(query: str, candidate_rows: List[Dict[str, Any]], client: genai.Client, k: int = 8):
    if not candidate_rows:
        return []
    corpus = [r["text"] for r in candidate_rows]
    bm25 = build_bm25(corpus)
    qtok = simple_tokenize(query)
    bm = bm25.get_scores(qtok)
    qv = embed_query(client, query)
    cvecs = embed_texts(client, corpus, "RETRIEVAL_DOCUMENT")
    sims = (cvecs @ qv).tolist()
    ranked = []
    for i, row in enumerate(candidate_rows):
        lexical = float(bm[i])
        semantic = float(sims[i])
        title_boost = 0.0
        if row.get("title"):
            title_boost = fuzz.partial_ratio(query.lower(), row["title"].lower()) / 100.0
        score = 0.62 * semantic + 0.25 * (lexical / (1 + abs(lexical))) + 0.13 * title_boost
        item = dict(row)
        item["score"] = float(score)
        ranked.append(item)
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:k]

def answer_with_gemini(client: genai.Client, question: str, context_blocks: List[Dict[str, Any]], chapter_hint: str = "") -> str:
    context_text = []
    for i, b in enumerate(context_blocks, 1):
        context_text.append(
            f"[{i}] source={b.get('source_path','')}\n"
            f"page={b.get('page','')}\n"
            f"concept_ids={b.get('concept_ids', [])}\n"
            f"figure_labels={b.get('figure_labels', [])}\n"
            f"text:\n{b.get('text','')}\n"
        )
    prompt = f"""
You are a pedagogy-first tutor for Class 10 Mathematics.

Use the context to answer the user's question.
Prefer concept explanation over generic summaries.
If the question is vague, mention the likely concepts and ask one focused follow-up.
If images/figures are relevant, explicitly mention them.
Keep the explanation simple but mathematically correct.

Chapter hint:
{chapter_hint}

Question:
{question}

Context:
{chr(10).join(context_text)}
"""
    resp = client.models.generate_content(model=GEN_MODEL, contents=prompt)
    return (resp.text or "").strip()
