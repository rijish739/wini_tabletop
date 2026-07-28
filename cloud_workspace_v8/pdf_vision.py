from __future__ import annotations
import io, json, os
from pathlib import Path
from typing import Any, Dict, List
import fitz
from google import genai
from google.genai import types

VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash")

def render_pdf_pages(pdf_path: Path, out_dir: Path, max_pages: int | None = None) -> List[Dict[str, Any]]:
    doc = fitz.open(str(pdf_path))
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    for i in range(len(doc)):
        if max_pages is not None and i >= max_pages:
            break
        page = doc[i]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        img_path = out_dir / f"page_{i+1:03d}.png"
        pix.save(str(img_path))
        text = page.get_text("text")
        pages.append({"page": i + 1, "image_path": str(img_path), "text": text})
    return pages

def summarize_page_with_vision(
    client: genai.Client,
    page_image_path: str,
    page_text: str,
    page_num: int,
    known_concept_ids: List[str] | None = None,
) -> Dict[str, Any]:
    image_bytes = Path(page_image_path).read_bytes()
    concept_hint = ""
    if known_concept_ids:
        concept_hint = (
            "Whenever you fill a `likely_concept_ids` field, you MUST choose ids ONLY from "
            "this allowed list (use [] if none apply):\n" + ", ".join(known_concept_ids) + "\n"
        )
    prompt = f"""
You are extracting pedagogical structure from one page of a Class 10 Mathematics NCERT textbook.
Use BOTH the page image and the page text. Return STRICT JSON only.

{concept_hint}
Return an object with these keys (every list may be empty, but every key must be present):

- page: integer
- concise_summary: string (2-4 sentences capturing the teaching content of the page)
- concept_candidates: list of {{ "concept_id": string, "label": string, "confidence": 0..1 }}
- equations: list of {{ "name": string, "formula": string, "likely_concept_ids": [string],
    "difficulty": 1..10 }}
- figures: list of {{ "label": string, "what_it_shows": string,
    "representation": "graphical|diagrammatic|tabular|other", "likely_concept_ids": [string] }}
- tables: list of {{ "label": string, "what_it_shows": string, "likely_concept_ids": [string] }}
- examples: list of {{ "label": string, "content": string, "likely_concept_ids": [string],
    "difficulty": 1..10, "pedagogical_role": "worked_example",
    "bloom_level": "remember|understand|apply|analyze|evaluate|create" }}
- exercises: list of {{ "label": string, "content": string, "likely_concept_ids": [string],
    "difficulty": 1..10, "pedagogical_role": "practice|challenge",
    "bloom_level": "remember|understand|apply|analyze|evaluate|create" }}
- misconceptions: list of {{ "text": string, "likely_concept_ids": [string], "correction": string }}
- applications: list of {{ "text": string, "source_concept_ids": [string],
    "target_domain": string, "transfer_type": "near|far" }}
- retrieval_tags: list of string

Rules:
- difficulty is an estimate of cognitive load for a Class 10 student (1 = trivial recall, 10 = hard multi-step reasoning).
- For any graph/table/figure, describe its MATHEMATICAL meaning, not just its appearance.
- `applications` = places where this page connects a polynomial idea to another concept/domain
  (geometry, physics, word problems, another chapter). Use it only when a genuine cross-concept bridge exists.
- `misconceptions` = errors a student is likely to make on this content, with a one-line correction.
- Do NOT invent concept ids that are not in the allowed list above.

Page number: {page_num}

Page text:
{page_text[:6000]}
"""
    resp = client.models.generate_content(
        model=VISION_MODEL,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            prompt,
        ],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    data = json.loads(resp.text or "{}")
    data["page"] = page_num
    # Guarantee every expected key exists so downstream graph building never KeyErrors.
    for key in ("concise_summary",):
        data.setdefault(key, "")
    for key in ("concept_candidates", "equations", "figures", "tables", "examples",
                "exercises", "misconceptions", "applications", "retrieval_tags"):
        if not isinstance(data.get(key), list):
            data[key] = []
    return data
