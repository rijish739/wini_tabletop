"""Personal-data recall and precision, measured against the blind corpora (§12).

Its own harness, deliberately not a mode of ``perception_eval.py`` or
``safety_eval.py``: it has its own prompt-of-record, its own model flag and its own
re-measurement triggers, and fusing them would make a change on one path silently
invalidate a number on another.

Read §12 before adding a print statement to this file:

    **Publish no aggregate number anywhere. Per-class only.** An aggregate is how the
    safety side came to report a meaningless 1.0.

So there is no mean, no macro-average and no total over the nine classes. Two
measurements are published, under their own labels, and they are never combined:

* **per-class recall** — of the rows that disclose class C, how many did the model
  name as class C. Floor **0.80 per class**;
* **maths-dense false-positive rate** — over ≥500 rows containing zero identifiers,
  how many produced any finding at all. Hard gate **≤ 1%**.

The recall floor is 0.80 because that is what the state of the art achieves:
MathEd-PII's domain-aware ceiling is 0.80–0.82, and a floor above the published
ceiling is a gate that never goes green, which in practice means a gate that gets
waived. The precision gate is hard, not advisory — over-redaction is the failure that
breaks the product, and the maths corpus is where §5's residual risk is measured.

A third number is reported and is **not** a gate: **redaction integrity**, the fraction
of findings whose ``value`` was actually a substring of the utterance. It is not a
model-quality measurement, it is an operational one — every miss is a turn whose
transcript §4 withholds, so this is the number that predicts how much of the analytics
log survives.

Cost shape, mirroring ``safety_eval.py``: ``--collect`` is BILLED and makes one call
per uncached row, appending as it goes, so an interrupted pass never re-bills.
``--score`` is OFFLINE and reads that cache.

**The cache is keyed by the prompt hash and caches are never mixed.** A row cached
under a different hash was produced by a different detector; scoring it as if it were
this one would report a number for a system that does not exist. That is a hard
failure here, and an assertion in the test suite.

    python -m eval.personal_data_eval --collect [--limit N]   # BILLED, resumable
    python -m eval.personal_data_eval --score                 # offline, from the cache
    python -m eval.personal_data_eval --gate                  # the release gate
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from personal_data import config as pd_config                  # noqa: E402
from personal_data.detector import PersonalDataDetector         # noqa: E402
from personal_data.prompt import (                              # noqa: E402
    IDENTIFIER_CLASS_NAMES,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    prompt_hash,
)

EVAL_DIR = Path(__file__).resolve().parent
CORPORA = EVAL_DIR / "corpora" / "pii"
RECORDS = EVAL_DIR / "records"
CACHE_DIR = RECORDS / "personal_data_eval_cache"

#: §12. Two floors, on two different measurements, never combined into one.
RECALL_FLOOR = 0.80
MAX_FALSE_POSITIVE_RATE = 0.01

#: The per-class disclosure corpora. One file per §3 class.
POSITIVE_CORPORA = {name: f"{name.lower()}.jsonl" for name in IDENTIFIER_CLASS_NAMES}

#: ≥500 rows from the maths dataset containing **zero** identifiers. Any finding here
#: is a false positive.
PRECISION_CORPUS = "maths_dense_precision.jsonl"


# --------------------------------------------------------------------------
# Corpora
# --------------------------------------------------------------------------
def _read(name: str) -> list[dict]:
    path = CORPORA / name
    if not path.exists():
        raise SystemExit(f"missing corpus: {path}")
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _corpus_review_state() -> dict[str, str]:
    """Sign-off per corpus, from the manifest. An unreviewed corpus may still be
    scored — under an "unreviewed" label — but no release happens on its numbers."""
    manifest = EVAL_DIR / "corpora" / "corpus_manifest.jsonl"
    state: dict[str, str] = {}
    if not manifest.exists():
        return state
    with manifest.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                row = json.loads(line)
                state[row["name"]] = row.get("review_scope") or "unreviewed"
    return state


def _all_rows(limit: int | None = None) -> list[dict]:
    """Every row the model is asked about, tagged with its corpus and gold label."""
    rows: list[dict] = []
    for label, filename in POSITIVE_CORPORA.items():
        for row in _read(filename):
            rows.append({**row, "gold_class": label, "corpus": filename})
    for row in _read(PRECISION_CORPUS):
        rows.append({**row, "gold_class": None, "corpus": PRECISION_CORPUS})
    if limit:
        rows = rows[:limit]
    return rows


# --------------------------------------------------------------------------
# The cache — keyed by prompt hash, never mixed
# --------------------------------------------------------------------------
def cache_path() -> Path:
    """One file per prompt-of-record. The hash is in the *filename* so a prompt change
    cannot silently append to the previous run's evidence."""
    return CACHE_DIR / f"personal_data_raw_{prompt_hash()}.jsonl"


def load_cache() -> dict[str, dict]:
    path = cache_path()
    if not path.exists():
        return {}
    cached: dict[str, dict] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("prompt_hash") != prompt_hash():
                # Belt as well as braces: a hand-edited or concatenated cache is a hard
                # failure, never a warning. Scoring a mixed cache would report a number
                # for a detector that does not exist.
                raise SystemExit(
                    f"cache {path.name} contains prompt_hash={row.get('prompt_hash')!r} "
                    f"but the prompt-of-record is {prompt_hash()!r}. Caches are never "
                    "mixed across prompt hashes — re-run --collect."
                )
            cached[row["id"]] = row
    return cached


def _cache_entry(row: dict, verdict) -> dict:
    """What one row's result looks like on disk.

    **The identifier values are not written.** ``predicted_classes`` and a per-finding
    ``matched`` boolean are all that survive the verdict (§4, §9): this file is a sink
    like any other, and an eval cache full of children's phone numbers would be the
    single worst place for the contract to leak — it is committed, uploaded as a CI
    artifact, and read by humans.

    The corpora themselves contain synthetic identifiers, so the *inputs* are safe. It
    is the model's echo of them that must not be persisted, because on a real
    production replay it would not be synthetic.
    """
    return {
        "id": row["id"],
        "corpus": row["corpus"],
        "gold_class": row["gold_class"],
        "prompt_hash": prompt_hash(),
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "model_id": verdict.model_id,
        "model_pinned": verdict.model_pinned,
        "status": verdict.status.value,
        "predicted_classes": sorted(c.value for c in verdict.classes),
        "n_findings": len(verdict.findings),
        # §4's operational number: did every named substring actually appear? A False
        # here is a turn whose transcript would have been withheld in production.
        "all_values_matched": all(
            finding.value in row["text"] for finding in verdict.findings
        ),
        "latency_ms": verdict.latency_ms,
        "attempts": verdict.attempts,
    }


def collect(limit: int | None = None) -> dict:
    """BILLED. One Gemini call per uncached row, appended as it goes."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    rows = _all_rows(limit)
    cached = load_cache()
    pending = [row for row in rows if row["id"] not in cached]
    print(f"collect: {len(pending)} rows to call ({len(cached)} already cached), "
          f"prompt_hash={prompt_hash()}")

    detector = PersonalDataDetector(memo_size=1)
    errors = 0
    with cache_path().open("a", encoding="utf-8") as handle:
        for index, row in enumerate(pending, 1):
            verdict = detector.detect(utterance_id=row["id"], text=row["text"])
            if not verdict.landed:
                # Not cached, so a later --collect retries it. A failed call is never
                # written as an empty finding list — that is the failure mode this
                # whole package exists to prevent, and it would be just as wrong in an
                # eval as in a turn.
                errors += 1
                print(f"  [{index}/{len(pending)}] FAILED {row['id']}: "
                      f"{verdict.failure_reason}")
                continue
            handle.write(
                json.dumps(_cache_entry(row, verdict), ensure_ascii=False) + "\n"
            )
            handle.flush()
            if index % 50 == 0:
                print(f"  [{index}/{len(pending)}] cached")
    return {"new_calls": len(pending) - errors, "errors": errors,
            "cached_before": len(cached)}


# --------------------------------------------------------------------------
# Scoring — offline, per class, no aggregate
# --------------------------------------------------------------------------
def _fraction(hit: int, total: int) -> float | None:
    """None, never 0.0, when nothing was measured. A missing measurement and a
    measured zero are different facts and must not print the same."""
    return (hit / total) if total else None


def score(limit: int | None = None) -> dict:
    cached = load_cache()
    if not cached:
        raise SystemExit(
            f"no cached predictions in {cache_path().name}. Run `--collect` first "
            "(BILLED), then `--score` (offline)."
        )
    rows = [row for row in _all_rows(limit) if row["id"] in cached]
    review = _corpus_review_state()

    per_class: dict[str, dict] = {}
    for label, filename in POSITIVE_CORPORA.items():
        subset = [row for row in rows if row["gold_class"] == label]
        exact = detected = matched = 0
        for row in subset:
            entry = cached[row["id"]]
            predicted = entry["predicted_classes"]
            exact += int(label in predicted)
            detected += int(bool(predicted))
            matched += int(entry["all_values_matched"])
        per_class[label] = {
            "n": len(subset),
            # The gated number: did the model name THIS class.
            "class_recall": _fraction(exact, len(subset)),
            # Reported beside it and never fused with it: the model found *something*
            # personal. A row detected as the wrong class is still redacted, so this is
            # the number that describes what the child is actually protected from —
            # while `class_recall` is what §12 gates on.
            "any_finding_recall": _fraction(detected, len(subset)),
            "redaction_integrity": _fraction(matched, len(subset)),
            "review_scope": review.get(
                f"pii_{filename.replace('.jsonl', '')}", "unreviewed"
            ),
        }

    precision_rows = [row for row in rows if row["corpus"] == PRECISION_CORPUS]
    false_positives = [
        row["id"] for row in precision_rows
        if cached[row["id"]]["predicted_classes"]
    ]
    model_ids = {cached[row["id"]]["model_id"] for row in rows}
    return {
        "measured_at": time.strftime("%Y-%m-%d"),
        "prompt_hash": prompt_hash(),
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "model_ids": sorted(model_ids),
        "model_pinned": all(cached[row["id"]]["model_pinned"] for row in rows),
        "n_scored": len(rows),
        "per_class": per_class,
        "maths_dense_precision": {
            "n": len(precision_rows),
            "false_positives": len(false_positives),
            "rate": _fraction(len(false_positives), len(precision_rows)),
            "max_rate": MAX_FALSE_POSITIVE_RATE,
            "examples": false_positives[:10],
            "review_scope": review.get("pii_maths_dense_precision", "unreviewed"),
        },
    }


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def render(results: dict) -> str:
    def fmt(value):
        return "—" if value is None else f"{value:.3f}"

    precision = results["maths_dense_precision"]
    lines = [
        "# Personal-data eval",
        "",
        f"> Measured **{results['measured_at']}** · prompt `{results['prompt_version']}`"
        f" · schema `{results['schema_version']}` · hash `{results['prompt_hash']}`",
        f"> Model(s): {', '.join(results['model_ids'])} · "
        f"pinned: **{results['model_pinned']}** · {results['n_scored']} rows scored",
        "",
        "**There is no aggregate number in this report, by design.** Per-class recall"
        " and the maths-dense false-positive rate measure different things and are"
        " never combined — a single number is what hid whole classes at zero behind a"
        " shipped \"SAFETY recall 1.0\".",
        "",
        "## Per-class recall (floor 0.80)",
        "",
        "| class | n | class recall | any finding | redaction integrity | floor | review |",
        "|---|---|---|---|---|---|---|",
    ]
    for label in IDENTIFIER_CLASS_NAMES:
        row = results["per_class"].get(label)
        if not row:
            continue
        below = (
            row["class_recall"] is not None and row["class_recall"] < RECALL_FLOOR
        )
        lines.append(
            f"| `{label}` | {row['n']} | {fmt(row['class_recall'])} | "
            f"{fmt(row['any_finding_recall'])} | {fmt(row['redaction_integrity'])} | "
            f"{'**BELOW**' if below else 'ok'} | {row['review_scope']} |"
        )

    lines += [
        "",
        "## Maths-dense precision (hard gate ≤ 1%)",
        "",
        f"{precision['false_positives']}/{precision['n']} rows containing zero "
        f"identifiers produced a finding — rate **{fmt(precision['rate'])}**, "
        f"limit {precision['max_rate']}.",
        "",
        "This is where §5's residual risk is measured. The contract resolves the"
        " numeric collision structurally — redaction is exact-match on a substring a"
        " maths-aware model named, so there is no threshold to tune — which moves the"
        " whole risk onto the model, which is why this gate is hard rather than a"
        " footnote. A tutor that redacts `3825` has broken the lesson.",
        "",
        "## Not covered",
        "",
    ]
    below = [
        label for label, row in results["per_class"].items()
        if row["class_recall"] is not None and row["class_recall"] < RECALL_FLOOR
    ]
    if below:
        lines.append(
            "These classes are **below the 0.80 per-class floor and do not enter the "
            "enum** (§3). Naming them is the deliverable — a class silently below "
            "floor reports zero downstream, which is indistinguishable from "
            "\"this never happens\":"
        )
        lines += [f"- `{label}`" for label in sorted(below)]
    else:
        lines.append("Every measured class meets its floor.")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# The release gate
# --------------------------------------------------------------------------
def gate(results: dict) -> tuple[bool, list[str]]:
    """§12. Stop-ship, and it is allowed to say no."""
    blockers: list[str] = []

    if not results["model_pinned"]:
        blockers.append(
            "VERTEX_PERSONAL_DATA_MODEL_VERSION is unset, so the model is riding a "
            "floating alias: a Google-side rollout could change detection behaviour "
            "between two deploys of identical code, and a model's recall moves "
            "silently in ways a regex's never did. Pin it before release."
        )

    unreviewed = sorted(
        label for label, row in results["per_class"].items()
        if row["review_scope"] == "unreviewed"
    )
    if results["maths_dense_precision"]["review_scope"] == "unreviewed":
        unreviewed.append("maths_dense_precision")
    if unreviewed:
        blockers.append(
            "no release happens on unreviewed corpora; unreviewed: "
            + ", ".join(unreviewed)
        )

    below = sorted(
        label for label, row in results["per_class"].items()
        if row["class_recall"] is not None and row["class_recall"] < RECALL_FLOOR
    )
    still_in_enum = [
        label for label in below if label in IDENTIFIER_CLASS_NAMES
    ]
    if still_in_enum:
        blockers.append(
            f"below the {RECALL_FLOOR} per-class floor but still in the response "
            f"enum: {', '.join(still_in_enum)}. Either remove the class from "
            "personal_data/prompt.py + schema.py, or meet the floor. A class that "
            "ships below floor is measured by nothing the release record admits."
        )

    precision = results["maths_dense_precision"]
    if precision["rate"] is not None and precision["rate"] > MAX_FALSE_POSITIVE_RATE:
        blockers.append(
            f"maths-dense false-positive rate {precision['rate']:.4f} exceeds the hard "
            f"{MAX_FALSE_POSITIVE_RATE} gate ({precision['false_positives']}/"
            f"{precision['n']} rows). Over-redaction is the failure that breaks the "
            f"product; examples: {precision['examples'][:5]}"
        )
    return (not blockers), blockers


# --------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Personal-data eval (PERSONAL_DATA_CONTRACT.md §12)"
    )
    parser.add_argument("--collect", action="store_true",
                        help="BILLED: one Gemini call per uncached row (resumable)")
    parser.add_argument("--score", action="store_true",
                        help="offline: per-class recall + precision from the cache")
    parser.add_argument("--gate", action="store_true",
                        help="the release gate (offline, needs a cache)")
    parser.add_argument("--limit", type=int, default=None, help="cap rows (smoke)")
    parser.add_argument("--report", type=Path, default=None,
                        help="write the rendered report to this path")
    args = parser.parse_args()

    if not any((args.collect, args.score, args.gate)):
        parser.print_help()
        return

    if args.collect:
        print(json.dumps(collect(args.limit), indent=2))
    if args.score or args.gate:
        results = score(args.limit)
        report = render(results)
        print(report)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(report, encoding="utf-8")
    if args.gate:
        passed, blockers = gate(results)
        print("\n## Release gate\n")
        if passed:
            print("PASS — the personal-data gate is clear.")
        else:
            for blocker in blockers:
                print(f"BLOCKED: {blocker}")
            raise SystemExit(1)


if __name__ == "__main__":
    main()
