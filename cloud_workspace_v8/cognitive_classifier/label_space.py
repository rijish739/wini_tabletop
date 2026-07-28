"""Canonical label space for the exemplar cognitive classifier.

The raw dataset (now archived at dataset/archive/exemplar_dataset_10000.json)
carries 48 distinct labels in `miniLM_labels`, with a long tail of
near-duplicates and one-off variants produced during generation. This module
folds the tail into the nearest canonical label and drops anything that still
lacks the minimum support needed for a usable exemplar bank + threshold
calibration. (The canonical dataset of record is now
dataset/exemplar_dataset_10000_fixed.json; curate_dataset.py projects it to
_curated.json.)

Merge rationale (raw count in parentheses):
  recurring_misconception (4)      -> recurring_error        same phenomenon, two spellings
  prerequisite_weakness_clue (2)   -> prerequisite_weakness  same phenomenon
  self_deprecation (10)            -> low_confidence         "i feel so dumb" = confidence signal
  visual_analogy (3)               -> request_representation student asks for a visual form
  surface_engagement (2)           -> disengagement          shallow engagement, same policy response
  application_difficulty (2)       -> physical               "real-life use" axis of the dataset
  application_oriented (1)         -> physical
  application_request (1)          -> physical
  logical (1)                      -> abstraction_attempt
  strategic_learning (1)           -> self_monitoring
  productive_struggle (1)          -> self_monitoring
  active_engagement (1)            -> curiosity

Added canonical labels (T2 — acknowledgment, IMPLEMENTATION_TASKS.md):
  acknowledgment                                              positive-confirmation utterances
    ("yes got it", "makes sense now", "understood"). Authored as supplementary
    augmented rows (≥300) because the original 10k bank had almost no
    positive-confirmation examples; MiniLM otherwise embeds "makes sense now"
    next to "not making sense now" and the classifier mislabels acks as
    `confusion`. Gold rule: see cues.is_pure_ack + curate_dataset.curate_row —
    is_pure_ack(utt) ⇒ ensure `acknowledgment` ∧ remove `confusion`/`low_confidence`.
    DO NOT add to LABEL_MERGE_MAP — it is its own canonical label.
"""

from __future__ import annotations

from typing import Iterable, List

MIN_SUPPORT = 40

LABEL_MERGE_MAP = {
    "recurring_misconception": "recurring_error",
    "prerequisite_weakness_clue": "prerequisite_weakness",
    "self_deprecation": "low_confidence",
    "visual_analogy": "request_representation",
    "surface_engagement": "disengagement",
    "application_difficulty": "physical",
    "application_oriented": "physical",
    "application_request": "physical",
    "logical": "abstraction_attempt",
    "strategic_learning": "self_monitoring",
    "productive_struggle": "self_monitoring",
    "active_engagement": "curiosity",
}


def canonicalize_labels(raw: str | Iterable[str]) -> List[str]:
    """Normalize a raw `miniLM_labels` value into canonical label list.

    Accepts either the comma-separated string from the dataset or an
    iterable of labels. Lowercases, strips, applies the merge map, and
    de-duplicates while preserving order.
    """
    if isinstance(raw, str):
        parts = raw.split(",")
    else:
        parts = list(raw)
    out: List[str] = []
    for part in parts:
        label = part.strip().lower().replace(" ", "_")
        if not label:
            continue
        label = LABEL_MERGE_MAP.get(label, label)
        if label not in out:
            out.append(label)
    return out
