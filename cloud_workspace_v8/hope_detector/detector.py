"""Runtime HOPE detector: (prompt, answer, rubric) -> ordinal 0-3 per signal.

Artifacts (built by build_detector.py) in models/hope_detector/:
  signal_heads.npz   per-signal logistic coef/intercept/classes (KI, KT, CT)
  config.json        signal list, text template, model name

bridge answers are scored by the KT head (rubric: bridge uses the KT scale).
Two outputs per call:
  label    argmax class (the discrete 0-3 rating)
  score    expected value sum_k k * p(k) -> smooth 0-3 for rolling HOPE averages
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np

from cognitive_classifier.classifier import MODEL_NAME
from .features import assemble, scalar_feats

DEFAULT_MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "hope_detector"


class HopeDetector:
    def __init__(self, embedder, heads: dict, signal_map: dict) -> None:
        self.embedder = embedder
        self.heads = heads          # signal -> {coef, intercept, classes, mean, std}
        self.signal_map = signal_map  # e.g. {"bridge": "KT"}

    @classmethod
    def load(cls, model_dir: Path | str = DEFAULT_MODEL_DIR, device: Optional[str] = None,
             embedder=None) -> "HopeDetector":
        """Load the signal heads. Pass `embedder` to REUSE an existing MiniLM.

        Constructing a SentenceTransformer costs ~6.7 s on the Pi and does not get
        cheaper the second time, so building one here only for the caller to
        overwrite it is 6.7 s of pure boot latency — which is exactly what
        tutor_loop used to do. Callers that already have (or lazily provide) an
        embedder pass it in; only a standalone user pays for a fresh one.
        """
        model_dir = Path(model_dir)
        if embedder is None:
            from sentence_transformers import SentenceTransformer

            embedder = SentenceTransformer(MODEL_NAME, device=device)
        w = np.load(model_dir / "signal_heads.npz")
        config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
        heads = {
            sig: {"coef": w[f"{sig}_coef"], "intercept": w[f"{sig}_intercept"],
                  "classes": w[f"{sig}_classes"], "mean": w[f"{sig}_mean"], "std": w[f"{sig}_std"]}
            for sig in config["signals"]
        }
        return cls(embedder, heads, config.get("signal_map", {}))

    def _probs(self, head: dict, feat: np.ndarray) -> np.ndarray:
        z = feat @ head["coef"].T + head["intercept"]
        z -= z.max(axis=1, keepdims=True)
        p = np.exp(z)
        return p / p.sum(axis=1, keepdims=True)

    def score(self, signal: str, prompt: str, answer: str, rubric_anchor: str = "") -> dict:
        sig = self.signal_map.get(signal, signal)
        if sig not in self.heads:
            raise ValueError(f"no head for signal {signal!r} (have {sorted(self.heads)})")
        ans_e, rub_e, pr_e = self.embedder.encode(
            [answer, rubric_anchor, prompt], normalize_embeddings=True)
        scalars = scalar_feats(answer, prompt, np.asarray(ans_e), np.asarray(rub_e), np.asarray(pr_e))
        head = self.heads[sig]
        feat = assemble(np.asarray(ans_e), scalars, head["mean"], head["std"])[None, :]
        p = self._probs(head, feat)[0]
        classes = head["classes"]
        return {
            "signal": sig,
            "label": int(classes[int(p.argmax())]),
            "score": round(float((classes * p).sum()), 3),  # expected value, smooth 0-3
            "probs": {int(c): round(float(pi), 3) for c, pi in zip(classes, p)},
        }


def _main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Score one HOPE answer.")
    ap.add_argument("signal", choices=["KI", "KT", "CT", "bridge"])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--answer", required=True)
    ap.add_argument("--rubric", default="")
    args = ap.parse_args()
    det = HopeDetector.load()
    print(json.dumps(det.score(args.signal, args.prompt, args.answer, args.rubric), indent=2))


if __name__ == "__main__":
    _main()
