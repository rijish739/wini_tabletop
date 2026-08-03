"""Explain WHY the T9 teaching visual picked the crop it picked.

A wrong picture is worse than no picture, and the pick is the product of three
inputs that are invisible from the outside: the resolved primary concept, which
crops carry that concept tag, and each candidate's MiniLM similarity to what the
student actually said. This prints all three for one utterance so a bad pick can
be diagnosed instead of guessed at.

    .venv/bin/python tools/t9_probe.py --text "explain the qutub minar problem" \
        --concept jemh108__intro_trigonometry
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STORE = ROOT / "rag_store"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--text", default=None)
    ap.add_argument("--cases", action="store_true",
                    help="run the built-in regression set (one model load) and "
                         "print OLD vs NEW for each")
    ap.add_argument("--concept", default=None,
                    help="resolved primary concept id (tier 3 filters on it)")
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()

    import numpy as np  # noqa: PLC0415
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    from cognitive_classifier.classifier import MODEL_NAME  # noqa: PLC0415

    rows = [json.loads(l) for l in (STORE / "chunks.jsonl").open(encoding="utf-8")]
    crops = [r for r in rows
             if r.get("kind") == "figure_caption" and r.get("image_path")]
    # Mirrors TutorLoop._is_teaching_visual: portraits of mathematicians caption
    # well enough to win on topic and teach nothing.
    import re as _re  # noqa: PLC0415
    drop = _re.compile(r"\bportrait\b|\bphotograph of\b", _re.I)
    crops = [r for r in crops if not drop.search(r.get("text") or "")]
    print(f"[t9] {len(crops)} teaching-visual crops (portraits excluded)")

    # Same embedder and the same alt_text-or-text[:400] key tutor_loop's
    # `_crop_relevance` scores on, so these numbers are the ones the floor sees.
    st = SentenceTransformer(MODEL_NAME)

    def enc(texts):
        return np.asarray(st.encode(list(texts), normalize_embeddings=True,
                                    show_progress_bar=False), dtype=np.float32)

    keys = [(r.get("alt_text") or r.get("text") or "")[:400] for r in crops]
    crop_emb = enc(keys)

    if args.cases:
        rc = 0
        for text, concept in REGRESSION_CASES:
            sims = (enc([text]) @ crop_emb.T)[0]
            rc |= _report(text, concept,
                          sorted(((float(s), r) for s, r in zip(sims, crops)),
                                 key=lambda t: -t[0]), args.top, brief=True)
        return rc

    if not args.text:
        ap.error("--text or --cases is required")
    sims = (enc([args.text]) @ crop_emb.T)[0]
    scored = [(float(s), r) for s, r in zip(sims, crops)]
    scored.sort(key=lambda t: -t[0])

    scored.sort(key=lambda t: -t[0])
    print(f"\n=== TOP {args.top} BY RAW RELEVANCE (no scoping at all) ===")
    for s, r in scored[:args.top]:
        mark = "T" if args.concept and args.concept in (r.get("concept_ids") or []) else " "
        print(f" {mark} {s:.3f}  {r.get('figure_id')}  {(r.get('text') or '')[:66]}")

    if not args.concept:
        return 0
    return _report(args.text, args.concept, scored, args.top)


#: Utterance + the concept resolution is expected to land on. Covers the reported
#: Qutub Minar failure plus one turn per chapter that the OLD hard concept-tag
#: filter handled correctly — those must not change, or the fix has traded one
#: wrong picture for another.
REGRESSION_CASES = [
    ("can you explain the qutub minar example in trigonometry",
     "jemh108__intro_trigonometry"),
    ("what is the angle of elevation", "jemh109__angle_of_elevation"),
    ("solve x^2 - 5x + 6 = 0", "jemh104__quadratic_equation_definition"),
    ("explain the area of a segment of a circle", "jemh111__area_of_segment"),
    ("what is a tangent to a circle", "jemh110__tangent_radius_perpendicularity"),
    ("when are two triangles similar", "jemh106__triangle_similarity_criteria_intro"),
    ("what is the probability of getting a head", "jemh114__probability_range"),
    ("what is an arithmetic progression", "jemh105__arithmetic_mean"),
    ("explain the distance formula", "jemh107__trisection_of_segment"),
    ("what is the fundamental theorem of arithmetic",
     "jemh101__fundamental_theorem_of_arithmetic"),
    ("how do i find the zeroes of a polynomial from its graph",
     "jemh102__quadratic_zero_geometry"),
    ("what is sin cos and tan", "jemh108__fundamental_trig_ratios"),
    ("explain surface area of a cone", "jemh112__surface_area_combination"),
    ("what is the median of grouped data", "jemh113__median_grouped_data"),
    ("solve two linear equations by graph", "jemh103__graphical_solution"),
    ("a tower casts a shadow, find its height", "jemh109__angle_of_elevation"),
    # The reported utterance again, but resolved to the Chapter 9 APPLICATION
    # concept — where the right picture (fig_8_1) lives in Chapter 8. This is the
    # case pure chapter scoping got wrong.
    ("can you explain the qutub minar example in trigonometry",
     "jemh109__application_trig_ratios"),
]


def _report(text, concept, scored, top, brief=False) -> int:
    # Defaults MIRROR TutorLoop's (T9_VISUAL_MIN_RELEVANCE / T9_CONCEPT_BONUS /
    # T9_CROSS_CHAPTER_MIN). Keep them in step — a probe that models a different
    # threshold than the runtime is worse than no probe.
    floor = float(os.getenv("T9_VISUAL_MIN_RELEVANCE", "0.42"))
    bonus = float(os.getenv("T9_CONCEPT_BONUS", "0.12"))
    chapter = _chapter_of_concept(concept)

    # OLD: hard concept-tag filter, then best raw relevance over the floor.
    old_pool = [(s, r) for s, r in scored
                if concept in (r.get("concept_ids") or [])]
    old = max([t for t in old_pool if t[0] >= floor], key=lambda t: t[0],
              default=None)

    # NEW: score everything, then admit by origin — in-chapter, concept-tagged,
    # or clearly better from elsewhere. Concept tag is a tie-break bonus, and the
    # floor applies to the RAW similarity.
    cross = float(os.getenv("T9_CROSS_CHAPTER_MIN", "0.57"))
    new_pool = [(s, r) for s, r in scored
                if s >= floor and (r.get("doc_id") == chapter
                                   or concept in (r.get("concept_ids") or [])
                                   or s >= cross)]
    new = max(new_pool,
              key=lambda t: t[0] + (bonus if concept in
                                    (t[1].get("concept_ids") or []) else 0.0),
              default=None)

    def _f(pick):
        return "(none over floor)" if pick is None else \
            f"{pick[0]:.3f} {pick[1].get('figure_id')}"

    if brief:
        flag = "CHANGED" if (old or new) and (
            (old is None) != (new is None)
            or (old and new and old[1]["figure_id"] != new[1]["figure_id"])) else "same"
        print(f"\n[{flag:7s}] {text}")
        print(f"          old: {_f(old)}")
        print(f"          new: {_f(new)}")
        if new is not None:
            print(f"               {(new[1].get('text') or '')[:96]}")
        return 0

    print(f"\n=== SELECTION (concept={concept}, chapter={chapter}, "
          f"floor={floor}, bonus={bonus}) ===")
    for label, pick in (("OLD (hard concept-tag filter)", old),
                        ("NEW (chapter-scoped + tag bonus)", new)):
        print(f"  {label:34s}: {_f(pick)}")
        if pick is not None:
            print(f"  {'':34s}  {(pick[1].get('text') or '')[:88]}")
    if old and new and old[1].get("figure_id") != new[1].get("figure_id"):
        print("  -> CHANGED: the tag filter was discarding the better crop; "
              f"its tags are {new[1].get('concept_ids')}")
    return 0


def _chapter_of_concept(cid: str) -> str | None:
    """`chapter_doc` off the concept node — the same field tutor_loop reads."""
    g = json.loads((STORE / "graph.json").read_text(encoding="utf-8"))
    for n in g.get("nodes", []):
        if n.get("id") == cid or n.get("concept_id") == cid:
            return n.get("chapter_doc")
    return None


if __name__ == "__main__":
    raise SystemExit(main())
