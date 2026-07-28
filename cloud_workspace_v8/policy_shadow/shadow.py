"""Runtime policy shadow: features -> softmax over the 15 tutor actions.

Features (fixed order, defined once here and reused by build_policy.py):
    [ MiniLM utterance embedding (384)
    | Part-1 label scores in label_space.json order
    | section 6.2 cognitive-update aggregates in UPDATE_KEYS order ]

The action vocabulary is the dataset's 15 clean tutor actions. Raw dataset
values are canonicalized by `canonicalize_action`:
  - multi-action strings ("ENCOURAGE + REVIEW") -> first listed action
  - VERBAL_ANALOGY -> VISUAL_ANALOGY (same analogy family)
  - RESUME_STATE / REQUEST_HINT -> None (session mechanics / student-side
    label, not tutor pedagogy) — rows dropped from training
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import numpy as np

DEFAULT_MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "policy_shadow"

UPDATE_KEYS = [
    "confusion", "curiosity", "confidence", "misconception_probability",
    "transfer_attempt", "abstraction_attempt", "self_correction",
    "cognitive_load", "engagement", "frustration_risk",
]

ACTION_MERGE = {"VERBAL_ANALOGY": "VISUAL_ANALOGY"}
ACTION_DROP = {"RESUME_STATE", "REQUEST_HINT", ""}


def canonicalize_action(raw: str) -> Optional[str]:
    first = re.split(r"[,+]", raw.strip())[0].strip().upper()
    if first in ACTION_DROP:
        return None
    return ACTION_MERGE.get(first, first)


def feature_vector(emb: np.ndarray, label_scores: np.ndarray, update: dict) -> np.ndarray:
    upd = np.array([float(update.get(k, 0.0)) for k in UPDATE_KEYS], dtype=np.float32)
    return np.concatenate([emb.astype(np.float32), label_scores.astype(np.float32), upd])


class PolicyShadow:
    def __init__(self, actions: list[str], coef: np.ndarray, intercept: np.ndarray, classes: np.ndarray) -> None:
        self.actions = actions
        self.coef = coef
        self.intercept = intercept
        self.classes = classes

    @classmethod
    def load(cls, model_dir: Path | str = DEFAULT_MODEL_DIR) -> "PolicyShadow":
        model_dir = Path(model_dir)
        meta = json.loads((model_dir / "actions.json").read_text(encoding="utf-8"))
        w = np.load(model_dir / "policy_logreg.npz")
        return cls(meta["actions"], w["coef"], w["intercept"], w["classes"])

    def suggest_from_features(self, features: np.ndarray, top_k: int = 3) -> dict:
        z = features @ self.coef.T + self.intercept
        z -= z.max()
        p = np.exp(z)
        p /= p.sum()
        order = np.argsort(-p)
        ranked = [
            {"action": self.actions[int(self.classes[j])], "p": round(float(p[j]), 4)}
            for j in order[:top_k]
        ]
        return {"action": ranked[0]["action"], "confidence": ranked[0]["p"], "ranked": ranked}

    def suggest(self, analysis: dict, classifier) -> dict:
        """Suggest from a CognitiveAnalyzer.analyze() result. Recomputes the
        embedding + full label-score vector via the Part-1 classifier (the
        analysis dict only keeps scores >= 0.05)."""
        from cognitive_classifier.cues import cue_matrix

        text = analysis["normalized_text"]
        emb = classifier.embed([text])
        scores = classifier.score_matrix(emb, cue_matrix([text]))[0]
        return self.suggest_from_features(
            feature_vector(emb[0], scores, analysis["cognitive_update"])
        )


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Suggest a tutor action for an utterance.")
    parser.add_argument("text")
    args = parser.parse_args()
    from cognitive_analyzer import CognitiveAnalyzer

    analyzer = CognitiveAnalyzer()
    analysis = analyzer.analyze(args.text)
    suggestion = PolicyShadow.load().suggest(analysis, analyzer.classifier)
    print(json.dumps({"concept": analysis["concept"]["concept_id"],
                      "signals": analysis["signals"], "suggestion": suggestion}, indent=2))


if __name__ == "__main__":
    _main()
