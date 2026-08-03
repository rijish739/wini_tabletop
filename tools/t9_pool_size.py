"""How many crops tier 3 scores per turn, and how many miss the cached matrix.

`_visual_relevance` falls back to a per-row MiniLM encode for any candidate not
in the precomputed matrix (the formula pseudo-rows reached through a concept's
own pool). Each fallback is a separate encode inside the turn, so this counts
them before they become a latency surprise.

    .venv/bin/python tools/t9_pool_size.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
STORE = ROOT / "rag_store"


def main() -> int:
    rows = [json.loads(l) for l in (STORE / "chunks.jsonl").open(encoding="utf-8")]
    caption_ids = {r["chunk_id"] for r in rows
                   if r.get("kind") == "figure_caption" and r.get("image_path")}

    # concept -> formula crops, exactly as tutor_loop merges them
    links = json.loads((STORE / "formula_links.json").read_text(encoding="utf-8"))
    per_concept = Counter()
    for l in links["links"]:
        if l.get("has_image"):
            per_concept[l["concept_id"]] += 1

    by_chapter = Counter(r.get("doc_id") for r in rows
                         if r.get("kind") == "figure_caption" and r.get("image_path"))

    print(f"caption crops in matrix : {len(caption_ids)}")
    print(f"chapter pool size       : min={min(by_chapter.values())} "
          f"max={max(by_chapter.values())} median~{sorted(by_chapter.values())[len(by_chapter)//2]}")
    print(f"concepts with formula crops: {len(per_concept)}")
    top = per_concept.most_common(8)
    print("worst-case per-turn ENCODE fallbacks (formula crops on one concept):")
    for cid, n in top:
        print(f"   {n:4d}  {cid}")
    print(f"\n=> a turn on {top[0][0]} would do {top[0][1]} extra MiniLM encodes "
          f"unless they are batched or capped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
