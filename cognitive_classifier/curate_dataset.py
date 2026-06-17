"""Dataset curation: fix the label-ontology problems found in evaluation.

Reads  dataset/exemplar_dataset_10000.json  (never modified)
Writes dataset/exemplar_dataset_10000_curated.json + dataset/curation_report.md

Fixes applied (see complete_architecture_build_plan.md section 2.5):

FIX 1 — request_hint ontology. In the raw data, `request_hint` mostly marks
"re-explain / simplify / switch modality" utterances, while genuine hint and
answer requests sit under shortcut_seeking / hint_dependency. New contract:
`request_hint` = the utterance explicitly asks for a hint, a starting step,
the steps, or the answer (HINT_RE) — applied as a deterministic gold rule in
both directions (added where it matches, removed where it does not). Rows
that lose it are rerouted: EXAMPLE_RE -> example_request, MODALITY_RE ->
request_representation, otherwise -> simplification_request (new label).

FIX 4 — question consistency. `question` is set if and only if the utterance
is interrogative (is_question rule). The raw data applied it haphazardly,
capping precision at ~0.5 no matter the model.

Also rule-governed: simplification_request := SIMPLIFY_RE (a label introduced
here must be consistent from birth). example_request is add-only (added where
EXAMPLE_RE matches; existing positives kept).

`curate_row` is exported so LLM-augmented rows (augment_rare_labels.py) pass
through the exact same rules before entering the bank.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .cues import EXAMPLE_RE, HINT_RE, MODALITY_RE, SIMPLIFY_RE, is_question
from .label_space import canonicalize_labels

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dataset" / "exemplar_dataset_10000.json"
DST = ROOT / "dataset" / "exemplar_dataset_10000_curated.json"
REPORT = ROOT / "dataset" / "curation_report.md"


def curate_row(utterance: str, raw_labels) -> tuple[list[str], list[str]]:
    """Apply the gold rules to one row. Returns (labels, change_log)."""
    labels = canonicalize_labels(raw_labels)
    changes: list[str] = []

    # FIX 4 — question is deterministic
    if is_question(utterance):
        if "question" not in labels:
            labels.append("question")
            changes.append("+question")
    elif "question" in labels:
        labels.remove("question")
        changes.append("-question")

    # FIX 1 — request_hint is deterministic; evicted rows are rerouted
    asks_hint = bool(HINT_RE.search(utterance))
    if asks_hint and "request_hint" not in labels:
        labels.append("request_hint")
        changes.append("+request_hint")
    elif not asks_hint and "request_hint" in labels:
        labels.remove("request_hint")
        changes.append("-request_hint")
        if EXAMPLE_RE.search(utterance):
            reroute = "example_request"
        elif MODALITY_RE.search(utterance):
            reroute = "request_representation"
        else:
            reroute = "simplification_request"
        if reroute not in labels:
            labels.append(reroute)
            changes.append(f"+{reroute} (reroute)")

    # simplification_request is rule-governed from birth
    if SIMPLIFY_RE.search(utterance):
        if "simplification_request" not in labels:
            labels.append("simplification_request")
            changes.append("+simplification_request")
    elif "simplification_request" in labels:
        labels.remove("simplification_request")
        changes.append("-simplification_request")

    # example_request: add-only consistency pass
    if EXAMPLE_RE.search(utterance) and "example_request" not in labels:
        labels.append("example_request")
        changes.append("+example_request")

    return labels, changes


def main() -> None:
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    ops = Counter()
    out = []
    for r in rows:
        labels, changes = curate_row(r["student_utterance"], r["miniLM_labels"])
        for c in changes:
            ops[c.split(" ")[0]] += 1
        curated = dict(r)
        curated["miniLM_labels"] = ", ".join(labels)
        out.append(curated)
    DST.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    support = Counter(l for r in out for l in canonicalize_labels(r["miniLM_labels"]))
    changed = sum(1 for a, b in zip(rows, out) if a["miniLM_labels"] != b["miniLM_labels"])
    lines = [
        "# Dataset Curation Report",
        "",
        f"Source: `{SRC.name}` (untouched) -> `{DST.name}`",
        f"Rows changed: {changed} / {len(rows)}",
        "",
        "## Operations",
        "",
        "| op | rows |",
        "|---|---|",
    ]
    for op, n in ops.most_common():
        lines.append(f"| {op} | {n} |")
    lines += ["", "## Post-curation label support", "", "| label | rows |", "|---|---|"]
    for label, n in support.most_common():
        lines.append(f"| {label} | {n} |")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"changed {changed}/{len(rows)} rows; ops: {dict(ops)}")
    print(f"wrote {DST.name}, {REPORT.name}")


if __name__ == "__main__":
    main()
