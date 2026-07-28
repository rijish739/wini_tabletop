"""Finalize the HOPE bank + gold set after human review (build plan Part 4).

Actions (idempotent; backups written once):
  1. DROP the prompts flagged `status: rewrite_or_drop` in hope_prompt_bank.jsonl
     (37 prompts the LLM calibration found could not separate a memorized answer
     from a strong one — confirmed for removal by the human reviewer).
  2. DROP the gold answers tied to those dropped prompts (they are exactly the
     non-discriminating training signal we want gone).
  3. ATTACH the human prompt-quality ratings (rag_store/hope_bank_review_human.txt,
     30 prompts) onto their bank rows as `human_hope_rating`, joined by position
     against the ordered review sample with a signal-consistency assertion.

Backups: rag_store/hope_prompt_bank.jsonl.prehope.bak / hope_gold_set.jsonl.prehope.bak
Writes the cleaned files back in place + rag_store/hope_clean_report.md.

Usage:  python -m hope_detector.clean_bank
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "rag_store"
BANK = STORE / "hope_prompt_bank.jsonl"
GOLD = STORE / "hope_gold_set.jsonl"
SAMPLE = STORE / "hope_bank_review_sample.md"
HUMAN = STORE / "hope_bank_review_human.txt"
REPORT = STORE / "hope_clean_report.md"


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def human_ratings() -> dict[str, int]:
    """prompt_id -> human HOPE rating, joined by position (sample order ==
    human-table order; signals asserted to match)."""
    ordered_ids = re.findall(r"^## (hope::\S+)", SAMPLE.read_text(encoding="utf-8"), re.M)
    rows = re.findall(r"^\|\s*\d+\s*\|[^|]+\|\s*(KI|KT|CT)\s*\|\s*\*\*(\d)\*\*",
                      HUMAN.read_text(encoding="utf-8"), re.M)
    if len(ordered_ids) != len(rows):
        raise SystemExit(f"sample has {len(ordered_ids)} prompts but human table has {len(rows)}")
    out = {}
    for pid, (sig, rating) in zip(ordered_ids, rows):
        if pid.split("::")[2] != sig:
            raise SystemExit(f"signal mismatch at {pid}: human says {sig}")
        out[pid] = int(rating)
    return out


def main() -> None:
    bank = _read_jsonl(BANK)
    gold = _read_jsonl(GOLD)

    if not (STORE / "hope_prompt_bank.jsonl.prehope.bak").exists():
        (STORE / "hope_prompt_bank.jsonl.prehope.bak").write_text(BANK.read_text(encoding="utf-8"), encoding="utf-8")
        (STORE / "hope_gold_set.jsonl.prehope.bak").write_text(GOLD.read_text(encoding="utf-8"), encoding="utf-8")

    drop_ids = {b["prompt_id"] for b in bank if b.get("status") == "rewrite_or_drop"}
    ratings = human_ratings()

    kept_bank = []
    for b in bank:
        if b["prompt_id"] in drop_ids:
            continue
        b.pop("status", None)
        if b["prompt_id"] in ratings:
            b["human_hope_rating"] = ratings[b["prompt_id"]]
        kept_bank.append(b)

    kept_gold = [g for g in gold if g["prompt_id"] not in drop_ids]

    _write_jsonl(BANK, kept_bank)
    _write_jsonl(GOLD, kept_gold)

    import collections
    sig_bank = collections.Counter(b["signal"] for b in kept_bank)
    lines = [
        "# HOPE Bank Cleanup Report",
        "",
        f"Dropped {len(drop_ids)} `rewrite_or_drop` prompts and {len(gold) - len(kept_gold)} "
        f"gold answers tied to them.",
        f"Bank: {len(bank)} -> {len(kept_bank)} prompts.  Gold: {len(gold)} -> {len(kept_gold)} answers.",
        f"Human prompt ratings attached: {sum(1 for b in kept_bank if 'human_hope_rating' in b)}.",
        "",
        "## Kept bank by signal",
        "",
        "| signal | prompts |",
        "|---|---|",
    ] + [f"| {s} | {n} |" for s, n in sorted(sig_bank.items())]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"bank {len(bank)}->{len(kept_bank)}  gold {len(gold)}->{len(kept_gold)}  "
          f"human ratings attached: {sum(1 for b in kept_bank if 'human_hope_rating' in b)}")
    print(f"by signal: {dict(sig_bank)}")
    print(f"wrote backups (*.prehope.bak), cleaned files, {REPORT.name}")


if __name__ == "__main__":
    main()
