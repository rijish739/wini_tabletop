"""Batch scene author for a WHOLE chapter — the driver SCENE_VISUALS_GUIDE §3.3
calls for. Loops a chapter's concepts through the single-concept authoring path
(`build_concept_scene.author`) with the guards each lesson already paid for:

  1. Dry-run the whole chapter first (no --run) to eyeball every prompt, then bill.
  2. Skip already-authored + validated specs (idempotent; only re-author failures).
     --force re-authors even a present spec.
  3. Author SEQUENTIALLY — one Vertex client, built once (client construction is the
     ~4-9 s cold-start, not the call). `author` reuses `generate_json`'s memoized client.
  4. Auto-repair + validate each (author already does); on invalid, LOG and CONTINUE —
     one bad concept never aborts the chapter.
  5. Render a preview GIF per concept (review gallery you scan in one pass).
  6. Write a per-run report (concept_id, status, latency_ms, #beats) so a re-run
     targets only the failures.

Finally it (re)builds `rag_store/concept_figures.json` — the concept -> scene index the
store never had (§3.4), regenerated from whatever `figure_specs/*.scene.json` exist so
it stays in sync — which is what the live mic path (§4) looks up.

Usage:
    py -3 -m figures.build_chapter_scenes jemh104                 # dry-run (nothing billed)
    py -3 -m figures.build_chapter_scenes jemh104 --run --render  # author for real + GIFs
    py -3 -m figures.build_chapter_scenes jemh104 --run --force   # re-author even present specs
    py -3 -m figures.build_chapter_scenes --index-only            # just rebuild the index
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import time
from pathlib import Path

from figures import build_concept_scene as bcs

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "rag_store"
SPECS = STORE / "figure_specs"
INDEX = STORE / "concept_figures.json"


def chapter_ids(chapter: str) -> list[str]:
    data = json.load(io.open(STORE / "concepts.json", encoding="utf-8"))
    return [c["concept_id"] for c in data if c.get("chapter_doc") == chapter]


def _scene_ok(path: Path) -> bool:
    """True if an existing spec still passes the offline structural gate."""
    try:
        scene = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — corrupt file counts as not-ok (re-author it)
        return False
    return not bcs.validate_scene(scene)


def rebuild_index() -> dict:
    """Regenerate rag_store/concept_figures.json from the specs on disk (§3.4).
    Only scenes that pass the structural gate go in — the live path trusts this."""
    idx: dict[str, dict] = {}
    for p in sorted(glob.glob(str(SPECS / "*.scene.json"))):
        path = Path(p)
        try:
            s = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"[index] skip unreadable {path.name}: {e}")
            continue
        errs = bcs.validate_scene(s)
        if errs:
            print(f"[index] skip invalid {path.name}: {errs[0]}")
            continue
        cid = s.get("concept_id") or path.name.split(".scene.json")[0]
        idx[cid] = {
            "scene": str(path.relative_to(ROOT)).replace("\\", "/"),
            "beats": len(s.get("beats", [])),
            "title": s.get("title", ""),
            "shape": "derivation" if not any(
                e.get("t") == "axes"
                for e in list(s.get("base", []))
                + [x for b in s.get("beats", []) for x in b.get("in", [])]
            ) else "graph",
        }
    INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[index] wrote {INDEX.relative_to(ROOT)} — {len(idx)} concept(s)")
    return idx


def run_chapter(chapter: str, *, run: bool, render: bool, force: bool) -> list[tuple]:
    ids = chapter_ids(chapter)
    if not ids:
        raise SystemExit(f"no concepts for chapter {chapter!r} in concepts.json")
    print(f"[chapter] {chapter}: {len(ids)} concept(s)  "
          f"(run={run}, render={render}, force={force})\n")
    report: list[tuple] = []
    for cid in ids:
        out = SPECS / f"{cid}.scene.json"
        if out.exists() and not force and _scene_ok(out):
            print(f"[skip] {cid} (already authored + valid)")
            report.append((cid, "skip", 0, _beats(out)))
            continue
        if not run:
            # dry-run: show the exact prompt/schema for offline review, don't bill.
            print(f"\n===== DRY RUN {cid} =====")
            bcs.author(cid, run=False, render=False)
            report.append((cid, "dry", 0, 0))
            continue
        t0 = time.monotonic()
        try:
            rc = bcs.author(cid, run=True, render=render)
        except Exception as e:  # noqa: BLE001 — one concept never aborts the chapter
            print(f"[error] {cid}: {e}")
            rc = 1
        ms = round((time.monotonic() - t0) * 1000)
        status = "ok" if rc == 0 else "FAIL"
        report.append((cid, status, ms, _beats(out) if rc == 0 else 0))

    print("\n===== chapter report =====")
    for cid, status, ms, beats in report:
        print(f"  {status:5} {ms:>6} ms  beats={beats:<2}  {cid}")
    ok = sum(1 for _, s, _, _ in report if s in ("ok", "skip"))
    print(f"  {ok}/{len(report)} usable")
    return report


def _beats(path: Path) -> int:
    try:
        return len(json.loads(path.read_text(encoding="utf-8")).get("beats", []))
    except Exception:  # noqa: BLE001
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("chapter", nargs="?", help="chapter_doc, e.g. jemh104")
    ap.add_argument("--run", action="store_true", help="actually call Gemini (billed)")
    ap.add_argument("--render", action="store_true", help="also render a preview GIF each")
    ap.add_argument("--force", action="store_true", help="re-author even present valid specs")
    ap.add_argument("--index-only", action="store_true",
                    help="skip authoring; just rebuild concept_figures.json and exit")
    args = ap.parse_args()

    if args.index_only:
        rebuild_index()
        return 0
    if not args.chapter:
        ap.error("chapter is required (or use --index-only)")

    run_chapter(args.chapter, run=args.run, render=args.render, force=args.force)
    # Always refresh the index after a real run so the live path sees new scenes.
    if args.run:
        rebuild_index()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
