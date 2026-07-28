"""Targeted augmentation for rare cognitive labels (FIX 2, data half).

Rare labels fail because they almost never appear as the PRIMARY signal of an
utterance (self_correction co-occurs with confusion on 87/96 train rows), so
their evidence drowns in the dominant co-label's embedding cloud. This script
generates utterances where the rare label is the main point.

Guard rails:
  - generated rows go to the TRAIN bank only (build_bank appends them outside
    the frozen splits); val/test stay 100% original distribution
  - seed examples are drawn from TRAIN rows only (no paraphrase leakage)
  - every generated row passes through curate_dataset.curate_row, so the
    rule-governed labels (question / request_hint / simplification_request)
    stay deterministic on augmented data too
  - dedup against the full original dataset and within the generated set

Writes dataset/augmented_rare_labels.json. Resumable via dataset/augment_cache.jsonl.
Env: GOOGLE_GENAI_USE_VERTEXAI=True, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

from dotenv import load_dotenv

from .curate_dataset import curate_row
from .label_space import canonicalize_labels

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dataset" / "exemplar_dataset_10000_curated.json"
SPLITS = ROOT / "models" / "exemplar_classifier" / "splits.json"
DST = ROOT / "dataset" / "augmented_rare_labels.json"
CACHE = ROOT / "dataset" / "augment_cache.jsonl"

BATCH = 20
SEED = 7

# label -> (target new rows, definition shown to the generator)
TARGETS = {
    "self_correction": (200, "the student catches and revises their OWN earlier statement or step mid-message (wait / actually / oh I did it wrong / I was wrong)"),
    "answer_attempt": (220, "the student states a candidate answer or result they computed and (often) asks if it is right"),
    "request_hint": (160, "the student explicitly asks for a hint, a nudge, the first step, the steps, or the answer because they cannot start or are stuck"),
    "high_confidence": (180, "the student expresses confidence or that the material is easy / already known"),
    "hint_dependency": (150, "the student wants ready-made steps or answers to memorize instead of working it out — reliance on being told"),
    "misconception_clue": (180, "the student states a plausible-sounding but WRONG belief about the maths as if it were fact"),
    "representation_shift": (150, "the student wants the SAME content shown in a different representation (graph instead of equation, table instead of words)"),
    "example_request": (120, "the student asks for a worked example / a sum with actual numbers"),
}

CO_LABEL_MENU = (
    "confusion, low_confidence, question, procedural_focus, curiosity, frustration, "
    "anxiety, shortcut_seeking, skepticism, cognitive_overload, graphical, diagrammatic, "
    "algebraic, tabular, self_monitoring, transfer_attempt"
)

PROMPT = """You generate synthetic Class 10 Maths student-chat utterances for training a
multi-label cognitive-signal classifier. Indian-English student tone (casual, "na", "pls",
fragments allowed), topics across NCERT Class 10 Maths (real numbers, polynomials, linear
equations, quadratics, AP, triangles, coordinate geometry, trigonometry, circles, surface
area/volume, statistics, probability).

TARGET LABEL: {label}
DEFINITION: {definition}

Requirements:
- {n} utterances, 6 to 25 words each, varied topics and phrasings.
- The target label must be the PRIMARY, unmistakable signal of every utterance.
- Optionally add 0-2 secondary labels per row, only from: {menu}
- Do NOT reuse the seed phrasings below; vary structure, not just nouns.

Seed examples of the target label (style reference only):
{seeds}

Return a JSON array of objects: {{"student_utterance": "...", "miniLM_labels": "label1, label2"}}
Every row's miniLM_labels must include "{label}"."""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def main() -> None:
    load_dotenv()
    from google import genai  # lazy: only needed when generating

    from build_hope_bank import Cache, call_json  # hard-timeout call pattern

    rows = json.loads(SRC.read_text(encoding="utf-8"))
    train_ids = set(json.loads(SPLITS.read_text(encoding="utf-8"))["row_ids"]["train"])
    seen = {_norm(r["student_utterance"]) for r in rows}
    rng = random.Random(SEED)
    client = genai.Client()
    cache = Cache(CACHE)

    out: list[dict] = []
    for label, (target, definition) in TARGETS.items():
        seed_pool = [
            r["student_utterance"] for i, r in enumerate(rows)
            if i in train_ids and label in canonicalize_labels(r["miniLM_labels"])
        ]
        kept = 0
        n_batches = (target + BATCH - 1) // BATCH
        for b in range(n_batches + 2):  # +2 spare batches to cover rejects
            if kept >= target:
                break
            key = f"{label}::batch{b}"
            data = cache.get(key)
            if data is None:
                seeds = "\n".join(f"- {s}" for s in rng.sample(seed_pool, min(6, len(seed_pool))))
                prompt = PROMPT.format(label=label, definition=definition, n=BATCH,
                                       menu=CO_LABEL_MENU, seeds=seeds)
                try:
                    data = call_json(client, prompt)
                except RuntimeError as exc:
                    print(f"  {key}: {exc} — skipped")
                    continue
                cache.put(key, data)
            if not isinstance(data, list):
                continue
            for item in data:
                if kept >= target:
                    break
                utt = str(item.get("student_utterance", "")).strip()
                if not (4 <= len(utt.split()) <= 30) or _norm(utt) in seen:
                    continue
                labels, _ = curate_row(utt, str(item.get("miniLM_labels", "")))
                if label not in labels:
                    continue  # curation rules vetoed the target label (e.g. no hint phrasing)
                seen.add(_norm(utt))
                out.append({
                    "student_utterance": utt,
                    "concept_id": "INHERIT_CURRENT_CONCEPT",
                    "miniLM_labels": ", ".join(labels),
                    "hope_signals": "",
                    "target_policy_action": "",
                    "category": 0,
                    "source": "augmented",
                })
                kept += 1
        print(f"{label}: kept {kept}/{target}")

    DST.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(out)} augmented rows -> {DST.name}")


if __name__ == "__main__":
    main()
