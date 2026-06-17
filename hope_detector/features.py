"""Shared HOPE feature construction (used by build_detector.py AND detector.py).

The discrimination that matters — memorized (label ~1) vs strong (label ~3) —
is NOT visible when prompt+answer+rubric are embedded together: the four answer
levels of one prompt then embed almost identically (same prompt, same rubric,
only the answer differs). So we embed the ANSWER alone for content and add
low-variance scalar features that carry answer quality:

  cos(answer, rubric_anchor)  strong answers align with the rubric's target idea
  cos(answer, prompt)         well-developed answers stay on-topic with the prompt
  log word count              strong answers are substantially longer
  reasoning-marker count      because / therefore / since / so that / which means ...
  math-token count            symbols, numbers, formula fragments

Scalars are standardized with train-set mean/std (saved in the artifacts).
"""

from __future__ import annotations

import re

import numpy as np

REASONING_RE = re.compile(
    r"\b(because|since|therefore|hence|thus|so that|which means|in order to|"
    r"as a result|this shows|implies|if\b.*\bthen|due to|leads to)\b",
    re.IGNORECASE,
)
MATH_RE = re.compile(r"[0-9=+\-*/^×÷√²³]|\b[a-z]\s*=|\bsin\b|\bcos\b|\btan\b", re.IGNORECASE)
N_SCALARS = 5


def scalar_feats(answer: str, prompt: str,
                 ans_emb: np.ndarray, rub_emb: np.ndarray, prompt_emb: np.ndarray) -> np.ndarray:
    cos_ar = float(ans_emb @ rub_emb)
    cos_ap = float(ans_emb @ prompt_emb)
    words = len(answer.split())
    reasoning = len(REASONING_RE.findall(answer))
    math = len(MATH_RE.findall(answer))
    return np.array([cos_ar, cos_ap, np.log1p(words), reasoning, np.log1p(math)], dtype=np.float32)


def assemble(ans_emb: np.ndarray, scalars: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    """[ answer embedding | standardized scalar features ]."""
    z = (scalars - mean) / std
    return np.concatenate([ans_emb.astype(np.float32), z.astype(np.float32)])
