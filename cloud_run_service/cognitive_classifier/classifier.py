"""Runtime exemplar classifier: MiniLM embeddings + weighted k-NN over a bank.

Artifacts (produced by build_bank.py) live in models/exemplar_classifier/:
  bank_embeddings.npy  float32 [n_bank, 384], L2-normalized
  bank_meta.jsonl      one row per exemplar: utterance, labels, concept_id, category
  label_space.json     ordered canonical label list
  thresholds.json      {"k": int, "thresholds": {label: float}}

Scorers (selected on validation macro-F1 by build_bank.py):
  knn       weighted k-NN posterior: p(L) = sim-weighted fraction of the
            global top-k neighbors carrying L
  evidence  per-label evidence (report section 3.2): p(L) = mean cosine of
            the query's top-m most similar exemplars POSITIVE for L — rare
            labels keep their own evidence pool instead of being crowded
            out of a global neighborhood
  logreg    one-vs-rest logistic head on the frozen embeddings
  *+logreg  score-average ensembles of the above

All scores live in [0, 1] and are thresholded per label (calibrated on the
validation split).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

from .cues import cue_matrix

DEFAULT_MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "exemplar_classifier"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def score_labels_knn(
    query_emb: np.ndarray,
    bank_emb: np.ndarray,
    bank_label_matrix: np.ndarray,
    k: int,
) -> np.ndarray:
    """Vectorized weighted k-NN label scores.

    query_emb [n_q, d] and bank_emb [n_b, d] must be L2-normalized.
    bank_label_matrix is a float32 [n_b, n_labels] 0/1 matrix.
    Returns [n_q, n_labels] scores in [0, 1].
    """
    sims = query_emb @ bank_emb.T                       # [n_q, n_b]
    k = min(k, sims.shape[1])
    top_idx = np.argpartition(-sims, k - 1, axis=1)[:, :k]
    top_sims = np.take_along_axis(sims, top_idx, axis=1)
    weights = np.clip(top_sims, 0.0, None)              # [n_q, k]
    denom = weights.sum(axis=1, keepdims=True)
    denom[denom == 0.0] = 1.0
    # [n_q, k, n_labels] would be large; accumulate per query block instead.
    n_q, n_labels = query_emb.shape[0], bank_label_matrix.shape[1]
    out = np.zeros((n_q, n_labels), dtype=np.float32)
    for i in range(n_q):
        out[i] = weights[i] @ bank_label_matrix[top_idx[i]]
    return out / denom


def score_labels_evidence(
    query_emb: np.ndarray,
    bank_emb: np.ndarray,
    bank_label_matrix: np.ndarray,
    m: int,
) -> np.ndarray:
    """Per-label evidence scores: mean cosine of the top-m positives per label."""
    sims = np.clip(query_emb @ bank_emb.T, 0.0, None)   # [n_q, n_b]
    n_q, n_labels = query_emb.shape[0], bank_label_matrix.shape[1]
    out = np.zeros((n_q, n_labels), dtype=np.float32)
    for j in range(n_labels):
        pos = np.flatnonzero(bank_label_matrix[:, j] > 0)
        if pos.size == 0:
            continue
        pos_sims = sims[:, pos]                          # [n_q, n_pos]
        mj = min(m, pos.size)
        top = np.partition(pos_sims, pos_sims.shape[1] - mj, axis=1)[:, -mj:]
        out[:, j] = top.mean(axis=1)
    return out


def score_labels_logreg(query_emb: np.ndarray, coef: np.ndarray, intercept: np.ndarray) -> np.ndarray:
    """One-vs-rest logistic head: sigmoid(emb @ coef.T + intercept)."""
    z = query_emb @ coef.T + intercept
    return (1.0 / (1.0 + np.exp(-z))).astype(np.float32)


class ExemplarCognitiveClassifier:
    """Multi-label cognitive signal classifier over an exemplar bank."""

    def __init__(
        self,
        embedder,
        bank_emb: np.ndarray,
        bank_meta: List[dict],
        labels: List[str],
        thresholds: Dict[str, float],
        scorer: str = "knn",
        k: int = 8,
        m: int = 3,
        logreg_coef: Optional[np.ndarray] = None,
        logreg_intercept: Optional[np.ndarray] = None,
    ) -> None:
        self.embedder = embedder
        self.bank_emb = bank_emb.astype(np.float32)
        self.bank_meta = bank_meta
        self.labels = labels
        self.thresholds = thresholds
        self.scorer = scorer
        self.k = k
        self.m = m
        self.logreg_coef = logreg_coef
        self.logreg_intercept = logreg_intercept
        self._label_index = {label: i for i, label in enumerate(labels)}
        self.bank_label_matrix = np.zeros((len(bank_meta), len(labels)), dtype=np.float32)
        for row, meta in enumerate(bank_meta):
            for label in meta["labels"]:
                col = self._label_index.get(label)
                if col is not None:
                    self.bank_label_matrix[row, col] = 1.0

    # ------------------------------------------------------------------

    @classmethod
    def load(cls, model_dir: Path | str = DEFAULT_MODEL_DIR, device: Optional[str] = None) -> "ExemplarCognitiveClassifier":
        model_dir = Path(model_dir)
        from sentence_transformers import SentenceTransformer

        embedder = SentenceTransformer(MODEL_NAME, device=device)
        bank_emb = np.load(model_dir / "bank_embeddings.npy")
        bank_meta = [json.loads(line) for line in (model_dir / "bank_meta.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        labels = json.loads((model_dir / "label_space.json").read_text(encoding="utf-8"))["labels"]
        cal = json.loads((model_dir / "thresholds.json").read_text(encoding="utf-8"))
        coef = intercept = None
        logreg_path = model_dir / "logreg.npz"
        if logreg_path.exists():
            weights = np.load(logreg_path)
            coef, intercept = weights["coef"], weights["intercept"]
        return cls(
            embedder, bank_emb, bank_meta, labels, cal["thresholds"],
            scorer=cal.get("scorer", "knn"), k=cal.get("k", 8), m=cal.get("m", 3),
            logreg_coef=coef, logreg_intercept=intercept,
        )

    # ------------------------------------------------------------------

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        return np.asarray(
            self.embedder.encode(list(texts), normalize_embeddings=True, show_progress_bar=False),
            dtype=np.float32,
        )

    def score_matrix(self, query_emb: np.ndarray, query_cues: Optional[np.ndarray] = None) -> np.ndarray:
        """Dispatch to the scorer selected at build time. The logreg head was
        trained on [embedding | 9 cue features]; cues are appended when the
        stored coefficient width requires them."""
        parts = []
        for name in self.scorer.split("+"):
            if name == "knn":
                parts.append(score_labels_knn(query_emb, self.bank_emb, self.bank_label_matrix, self.k))
            elif name == "evidence":
                parts.append(score_labels_evidence(query_emb, self.bank_emb, self.bank_label_matrix, self.m))
            elif name == "logreg":
                if self.logreg_coef is None:
                    raise RuntimeError("scorer includes 'logreg' but logreg.npz was not loaded")
                features = query_emb
                if self.logreg_coef.shape[1] > query_emb.shape[1]:
                    if query_cues is None:
                        raise RuntimeError("logreg head expects cue features — pass query_cues")
                    features = np.hstack([query_emb, query_cues])
                parts.append(score_labels_logreg(features, self.logreg_coef, self.logreg_intercept))
            else:
                raise ValueError(f"unknown scorer component: {name}")
        return np.mean(parts, axis=0)

    def score_texts(self, texts: Sequence[str]) -> np.ndarray:
        return self.score_matrix(self.embed(texts), cue_matrix(texts))

    def classify(self, text: str, top_evidence: int = 3) -> dict:
        """Score one utterance; return scores, thresholded signals, evidence."""
        query = self.embed([text])
        scores_vec = self.score_matrix(query, cue_matrix([text]))[0]
        scores = {label: round(float(s), 4) for label, s in zip(self.labels, scores_vec)}
        signals = [
            label for label, s in scores.items()
            if s >= self.thresholds.get(label, 0.5)
        ]
        sims = (query @ self.bank_emb.T)[0]
        nearest = np.argsort(-sims)[:top_evidence]
        evidence = [
            {
                "utterance": self.bank_meta[i]["utterance"],
                "labels": self.bank_meta[i]["labels"],
                "similarity": round(float(sims[i]), 4),
            }
            for i in nearest
        ]
        return {"signals": sorted(signals, key=lambda l: -scores[l]), "scores": scores, "evidence": evidence}


class MiniLMSemanticClassifier:
    """Adapter implementing the InputProcessor SemanticClassifier protocol.

    Labels requested by the processor that are outside the trained label
    space (e.g. ``explanation``) score 0.0, so the processor's max-merge
    keeps its heuristic estimate for those.
    """

    def __init__(self, classifier: Optional[ExemplarCognitiveClassifier] = None) -> None:
        self.classifier = classifier or ExemplarCognitiveClassifier.load()

    def score(self, text: str, labels: Sequence[str]) -> Dict[str, float]:
        result = self.classifier.classify(text, top_evidence=0)
        return {label: float(result["scores"].get(label, 0.0)) for label in labels}


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Classify a student utterance.")
    parser.add_argument("text", help="student utterance")
    parser.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    parser.add_argument("--evidence", type=int, default=3)
    args = parser.parse_args()

    clf = ExemplarCognitiveClassifier.load(args.model_dir)
    result = clf.classify(args.text, top_evidence=args.evidence)
    result["scores"] = {l: s for l, s in sorted(result["scores"].items(), key=lambda kv: -kv[1]) if s > 0.05}
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _main()
