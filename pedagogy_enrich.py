"""Pedagogical enrichment for retrieved text chunks.

The base RAG store tethers each text chunk to a concept using cosine similarity
only. The learner-state architecture additionally needs to know, for every piece
of evidence:

  * what pedagogical *role* it plays (definition / explanation / worked example /
    practice / challenge / application / summary / historical note), and
  * an estimate of its *difficulty* (1-10) so the Pedagogical Decision Engine can
    target the learner's Zone of Proximal Development (ZPD), and
  * which *representation* it uses (symbolic / verbal / graphical / ...), so the
    engine can do representation translation, and
  * a coarse *Bloom level* for cognitive-demand routing.

This module classifies chunks in batches with the generation model and caches the
result on disk so re-runs are cheap. It is deliberately separate from build_index
so the enrichment policy can evolve without touching the indexing pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from google import genai
from google.genai import types

from rag_core import GEN_MODEL

ROLES = [
    "definition", "explanation", "worked_example", "practice",
    "challenge", "application", "summary", "historical_note",
    # Chunks that recall prior-grade (Class IX) knowledge before new instruction;
    # tagged by build_bridges.py and assignable on future rebuilds (plan Phase 3 step 1).
    "bridge_recall",
]
REPRESENTATIONS = ["symbolic", "verbal", "graphical", "diagrammatic", "tabular", "algebraic"]
BLOOM = ["remember", "understand", "apply", "analyze", "evaluate", "create"]

_DEFAULT = {
    "pedagogical_role": "explanation",
    "difficulty": 5,
    "representations": ["verbal"],
    "bloom_level": "understand",
}


def _prompt(batch: List[Dict[str, Any]]) -> str:
    items = []
    for i, row in enumerate(batch):
        text = (row.get("text") or "")[:900]
        items.append(f"[{i}] {text}")
    listing = "\n\n".join(items)
    return f"""
You are tagging fragments of a Class 10 Mathematics textbook for a tutoring system.
For EACH numbered fragment, return one JSON object describing it.

Return STRICT JSON: an object with a single key "items" whose value is a list, where
the element at position k corresponds to fragment [k]. Each element must be:
{{
  "pedagogical_role": one of {ROLES},
  "difficulty": integer 1..10 (cognitive load for a Class 10 student; 1=trivial recall, 10=hard multi-step),
  "representations": subset of {REPRESENTATIONS},
  "bloom_level": one of {BLOOM}
}}

Guidance:
- "definition": states what something is. "explanation": develops reasoning/why.
- "worked_example": a solved problem. "practice": routine exercise. "challenge": hard/extension exercise.
- "application": connects the idea to another domain or real-world use. "summary": recap. "historical_note": history/aside.
- Judge difficulty from the reasoning depth a student needs, not the length of the text.

Return exactly {len(batch)} items, in order.

Fragments:
{listing}
"""


def _coerce(obj: Any) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        return dict(_DEFAULT)
    role = obj.get("pedagogical_role")
    if role not in ROLES:
        role = _DEFAULT["pedagogical_role"]
    try:
        diff = int(obj.get("difficulty", _DEFAULT["difficulty"]))
    except (TypeError, ValueError):
        diff = _DEFAULT["difficulty"]
    diff = max(1, min(10, diff))
    reps = obj.get("representations")
    if not isinstance(reps, list) or not reps:
        reps = list(_DEFAULT["representations"])
    reps = [r for r in reps if r in REPRESENTATIONS] or list(_DEFAULT["representations"])
    bloom = obj.get("bloom_level")
    if bloom not in BLOOM:
        bloom = _DEFAULT["bloom_level"]
    return {
        "pedagogical_role": role,
        "difficulty": diff,
        "representations": reps,
        "bloom_level": bloom,
    }


def enrich_chunks(
    client: genai.Client,
    chunk_rows: List[Dict[str, Any]],
    cache_path: Path,
    batch_size: int = 16,
) -> None:
    """Add pedagogical_role / difficulty / representations / bloom_level to each row in place.

    Results are cached by chunk_id so a crashed or repeated run is cheap.
    """
    cache: Dict[str, Dict[str, Any]] = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                cache[rec["chunk_id"]] = rec["tags"]

    pending = [r for r in chunk_rows if r["chunk_id"] not in cache]
    print(f"Pedagogy enrichment: {len(chunk_rows)} chunks, {len(pending)} need tagging "
          f"({len(cache)} cached).")

    with open(cache_path, "a", encoding="utf-8") as cf:
        for start in range(0, len(pending), batch_size):
            batch = pending[start:start + batch_size]
            try:
                resp = client.models.generate_content(
                    model=GEN_MODEL,
                    contents=_prompt(batch),
                    config=types.GenerateContentConfig(response_mime_type="application/json"),
                )
                payload = json.loads(resp.text or "{}")
                items = payload.get("items", []) if isinstance(payload, dict) else []
            except Exception as e:  # noqa: BLE001 - enrichment must never break indexing
                print(f"  batch {start // batch_size} failed ({e}); using defaults.")
                items = []
            for i, row in enumerate(batch):
                tags = _coerce(items[i]) if i < len(items) else dict(_DEFAULT)
                cache[row["chunk_id"]] = tags
                cf.write(json.dumps({"chunk_id": row["chunk_id"], "tags": tags},
                                    ensure_ascii=False) + "\n")

    for row in chunk_rows:
        row.update(cache.get(row["chunk_id"], dict(_DEFAULT)))
