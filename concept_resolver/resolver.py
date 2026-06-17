"""Runtime concept resolver: anchor similarity + labeled-exemplar k-NN blend.

Scoring (selected and calibrated by build_resolver.py on the frozen splits):

    cards(c)  = cosine(query, anchor text of concept card c)      [zero-shot,
                covers concepts with no labeled utterances]
    knn(c)    = similarity-weighted fraction of the query's top-K labeled
                train utterances that carry concept c              [learned]
    score(c)  = alpha * knn(c) + (1 - alpha) * cards(c)
    abstain   if max_c score(c) < tau  ->  inherit session concept

An optional multinomial logistic head (98 seen concepts + ABSTAIN class) is
evaluated as a comparison candidate at build time; the shipped method is
whichever wins the combined validation metric.

Output schema follows architecture section 6.3: primary concept + confidence,
secondary concepts, resolution reason, plus an explicit `abstained` flag and
the inherited concept when session context is provided.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from cognitive_classifier.classifier import MODEL_NAME, score_labels_knn

DEFAULT_MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "concept_resolver"


def blend_scores(
    query_emb: np.ndarray,
    anchor_emb: np.ndarray,
    bank_emb: np.ndarray,
    bank_concept_matrix: np.ndarray,
    alpha: float,
    k: int,
) -> np.ndarray:
    """[n_q, n_concepts] blended concept scores in [0, 1]."""
    cards = np.clip(query_emb @ anchor_emb.T, 0.0, None)
    knn = score_labels_knn(query_emb, bank_emb, bank_concept_matrix, k)
    return alpha * knn + (1.0 - alpha) * cards


class ConceptResolver:
    def __init__(
        self,
        embedder,
        concept_ids: list[str],
        concept_names: list[str],
        anchor_emb: np.ndarray,
        bank_emb: np.ndarray,
        bank_concept_matrix: np.ndarray,
        alpha: float,
        k: int,
        tau: float,
        method: str = "blend",
        logreg: Optional[dict] = None,
    ) -> None:
        self.embedder = embedder
        self.concept_ids = concept_ids
        self.concept_names = concept_names
        self.anchor_emb = anchor_emb.astype(np.float32)
        self.bank_emb = bank_emb.astype(np.float32)
        self.bank_concept_matrix = bank_concept_matrix.astype(np.float32)
        self.alpha = alpha
        self.k = k
        self.tau = tau
        self.method = method
        self.logreg = logreg  # {"coef", "intercept", "classes"}; class n_concepts = ABSTAIN

    @classmethod
    def load(cls, model_dir: Path | str = DEFAULT_MODEL_DIR, device: Optional[str] = None) -> "ConceptResolver":
        model_dir = Path(model_dir)
        from sentence_transformers import SentenceTransformer

        embedder = SentenceTransformer(MODEL_NAME, device=device)
        meta = json.loads((model_dir / "concepts_meta.json").read_text(encoding="utf-8"))
        config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
        bank = np.load(model_dir / "train_bank.npz")
        logreg = None
        lr_path = model_dir / "logreg_resolver.npz"
        if lr_path.exists():
            w = np.load(lr_path)
            logreg = {"coef": w["coef"], "intercept": w["intercept"], "classes": w["classes"]}
        return cls(
            embedder,
            concept_ids=meta["concept_ids"],
            concept_names=meta["concept_names"],
            anchor_emb=np.load(model_dir / "anchor_embeddings.npy"),
            bank_emb=bank["emb"],
            bank_concept_matrix=bank["concept_matrix"],
            alpha=config["alpha"],
            k=config["k"],
            tau=config["tau"],
            method=config.get("method", "blend"),
            logreg=logreg,
        )

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        return np.asarray(
            self.embedder.encode(list(texts), normalize_embeddings=True, show_progress_bar=False),
            dtype=np.float32,
        )

    def _logreg_scores(self, query_emb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Softmax concept scores [n_q, n_concepts] + abstain-class probability."""
        z = query_emb @ self.logreg["coef"].T + self.logreg["intercept"]
        z -= z.max(axis=1, keepdims=True)
        proba = np.exp(z)
        proba /= proba.sum(axis=1, keepdims=True)
        n_concepts = len(self.concept_ids)
        out = np.zeros((query_emb.shape[0], n_concepts), dtype=np.float32)
        abstain_p = np.zeros(query_emb.shape[0], dtype=np.float32)
        for col, cls in enumerate(self.logreg["classes"]):
            if cls == n_concepts:
                abstain_p = proba[:, col]
            else:
                out[:, cls] = proba[:, col]
        return out, abstain_p

    def score_texts(self, texts: Sequence[str]) -> np.ndarray:
        emb = self.embed(texts)
        if self.method == "logreg" and self.logreg is not None:
            return self._logreg_scores(emb)[0]
        return blend_scores(emb, self.anchor_emb, self.bank_emb,
                            self.bank_concept_matrix, self.alpha, self.k)

    def resolve(self, text: str, current_concept: Optional[str] = None, top_k: int = 3) -> dict:
        """Resolve one utterance per architecture section 6.3."""
        query = self.embed([text])
        if self.method == "logreg" and self.logreg is not None:
            scores_mat, abstain_p = self._logreg_scores(query)
            scores = scores_mat[0]
            should_abstain = float(abstain_p[0]) > float(scores.max()) or float(scores.max()) < self.tau
        else:
            scores = blend_scores(query, self.anchor_emb, self.bank_emb,
                                  self.bank_concept_matrix, self.alpha, self.k)[0]
            should_abstain = float(scores.max()) < self.tau
        order = np.argsort(-scores)
        best = int(order[0])
        confidence = float(scores[best])
        secondary = [
            self.concept_ids[int(j)] for j in order[1:top_k]
            if scores[int(j)] >= 0.5 * confidence and scores[int(j)] > 0.0
        ]
        # component breakdown for the reason string (always from the
        # interpretable signals, whichever method scored)
        card_sim = float(np.clip(query @ self.anchor_emb[best], 0.0, None)[0])
        knn_part = float(score_labels_knn(query, self.bank_emb, self.bank_concept_matrix, max(self.k, 8))[0][best])

        if should_abstain:
            return {
                "concept_id": current_concept,
                "concept_confidence": round(confidence, 4),
                "secondary_concepts": [],
                "abstained": True,
                "resolution_reason": (
                    f"utterance names no concept confidently (best: "
                    f"'{self.concept_names[best]}' at {confidence:.2f}) — "
                    + ("inherited session concept" if current_concept else "no session concept to inherit")
                ),
            }
        return {
            "concept_id": self.concept_ids[best],
            "concept_confidence": round(confidence, 4),
            "secondary_concepts": secondary,
            "abstained": False,
            "resolution_reason": (
                f"matched '{self.concept_names[best]}' (classifier {confidence:.2f}, "
                f"card similarity {card_sim:.2f}, labeled-exemplar agreement {knn_part:.2f})"
            ),
        }


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Resolve a student utterance to a concept.")
    parser.add_argument("text")
    parser.add_argument("--current-concept", default=None)
    parser.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    args = parser.parse_args()
    resolver = ConceptResolver.load(args.model_dir)
    print(json.dumps(resolver.resolve(args.text, args.current_concept), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _main()
