"""Train + evaluate the HOPE detectors (build plan Part 4, report section 5).

Data: cleaned rag_store/hope_gold_set.jsonl (run clean_bank.py first). Features
come from features.py: MiniLM embedding of the ANSWER ALONE + standardized
alignment/length scalars (answer↔rubric, answer↔prompt, word count, reasoning
markers, math tokens). All local, GPU if available.

Per-signal ordinal head (multinomial logistic, KI / KT / CT); bridge answers
fold into the KT head (rubric: bridge is scored on the KT scale).

Split: by PROMPT (a prompt's four answers never straddle the split) into
70/15/15 train/val/test; C selected on val by QWK.

Metrics on held-out prompts:
  - QWK (quadratic weighted kappa) vs final_label
  - adjacent accuracy (|pred - true| <= 1)
  - DISCRIMINATION GATE: mean score(strong) - mean score(memorized) >= 1 ordinal

Usage:  python -m hope_detector.build_detector
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from cognitive_classifier.classifier import MODEL_NAME
from .detector import DEFAULT_MODEL_DIR
from .features import N_SCALARS, assemble, scalar_feats

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "rag_store" / "hope_gold_set.jsonl"
SEED = 42
SIGNAL_MAP = {"bridge": "KT"}
HEAD_SIGNALS = ["KI", "KT", "CT"]
C_GRID = (0.3, 1.0, 3.0, 10.0)


def quadratic_weighted_kappa(y_true, y_pred, n_classes=4) -> float:
    o = np.zeros((n_classes, n_classes))
    for t, p in zip(y_true, y_pred):
        o[int(t), int(p)] += 1
    w = np.array([[(i - j) ** 2 / (n_classes - 1) ** 2 for j in range(n_classes)] for i in range(n_classes)])
    e = np.outer(o.sum(1), o.sum(0)) / max(o.sum(), 1)
    denom = (w * e).sum()
    return float(1 - (w * o).sum() / denom) if denom > 0 else 0.0


def main() -> None:
    t0 = time.time()
    gold = [json.loads(l) for l in GOLD.read_text(encoding="utf-8").splitlines() if l.strip()]
    for g in gold:
        g["head"] = SIGNAL_MAP.get(g["signal"], g["signal"])

    prompts = sorted({g["prompt_id"] for g in gold})
    rng = np.random.RandomState(SEED)
    rng.shuffle(prompts)
    n = len(prompts)
    test_p = set(prompts[: round(n * 0.15)])
    val_p = set(prompts[round(n * 0.15): round(n * 0.30)])

    def split_of(g):
        return "test" if g["prompt_id"] in test_p else ("val" if g["prompt_id"] in val_p else "train")

    print(f"{len(gold)} answers / {n} prompts; split by prompt 70/15/15")

    from sentence_transformers import SentenceTransformer

    embedder = SentenceTransformer(MODEL_NAME)
    ans_emb = np.asarray(embedder.encode([g["answer_text"] for g in gold], batch_size=128,
                                         normalize_embeddings=True, show_progress_bar=True), dtype=np.float32)
    rub_emb = np.asarray(embedder.encode([g.get("rubric_anchor", "") for g in gold], batch_size=128,
                                         normalize_embeddings=True), dtype=np.float32)
    pr_emb = np.asarray(embedder.encode([g["prompt"] for g in gold], batch_size=128,
                                        normalize_embeddings=True), dtype=np.float32)
    raw_scalars = np.vstack([
        scalar_feats(g["answer_text"], g["prompt"], ans_emb[i], rub_emb[i], pr_emb[i])
        for i, g in enumerate(gold)
    ])

    from sklearn.linear_model import LogisticRegression

    heads_npz: dict = {}
    report_rows = []
    for sig in HEAD_SIGNALS:
        idx = np.array([i for i, g in enumerate(gold) if g["head"] == sig])
        tr = np.array([i for i in idx if split_of(gold[i]) == "train"])
        va = np.array([i for i in idx if split_of(gold[i]) == "val"])
        te = np.array([i for i in idx if split_of(gold[i]) == "test"])
        # standardize scalars on train only
        mean = raw_scalars[tr].mean(0)
        std = raw_scalars[tr].std(0)
        std[std == 0] = 1.0

        def feats(ii):
            return np.vstack([assemble(ans_emb[i], raw_scalars[i], mean, std) for i in ii])

        Xtr, Xva, Xte = feats(tr), feats(va), feats(te)
        ytr = np.array([gold[i]["final_label"] for i in tr])
        yva = np.array([gold[i]["final_label"] for i in va])
        yte = np.array([gold[i]["final_label"] for i in te])

        best = None
        for C in C_GRID:
            mdl = LogisticRegression(max_iter=3000, C=C, class_weight="balanced")
            mdl.fit(Xtr, ytr)
            qwk_va = quadratic_weighted_kappa(yva, mdl.classes_[mdl.predict_proba(Xva).argmax(1)])
            if best is None or qwk_va > best[1]:
                best = (mdl, qwk_va, C)
        model, qwk_va, C = best

        proba = model.predict_proba(Xte)
        classes = model.classes_
        pred = classes[proba.argmax(1)]
        exp_score = proba @ classes
        qwk = quadratic_weighted_kappa(yte, pred)
        adjacent = float((np.abs(pred - yte) <= 1).mean())
        mem = np.array([exp_score[k] for k, i in enumerate(te) if gold[i]["answer_level"] == "memorized"])
        strong = np.array([exp_score[k] for k, i in enumerate(te) if gold[i]["answer_level"] == "strong"])
        sep = float(strong.mean() - mem.mean()) if len(mem) and len(strong) else float("nan")

        heads_npz[f"{sig}_coef"] = model.coef_.astype(np.float32)
        heads_npz[f"{sig}_intercept"] = model.intercept_.astype(np.float32)
        heads_npz[f"{sig}_classes"] = classes.astype(np.int64)
        heads_npz[f"{sig}_mean"] = mean.astype(np.float32)
        heads_npz[f"{sig}_std"] = std.astype(np.float32)
        report_rows.append((sig, len(tr), len(te), C, qwk, adjacent, sep))
        print(f"{sig}: train={len(tr)} test={len(te)} C={C} QWK={qwk:.3f} adj={adjacent:.3f} "
              f"strong-mem sep={sep:.2f}")

    out = DEFAULT_MODEL_DIR
    out.mkdir(parents=True, exist_ok=True)
    np.savez(out / "signal_heads.npz", **heads_npz)
    (out / "config.json").write_text(
        json.dumps({"signals": HEAD_SIGNALS, "signal_map": SIGNAL_MAP, "model": MODEL_NAME,
                    "seed": SEED, "n_scalars": N_SCALARS, "feature": "answer_emb + standardized scalars"},
                   indent=2),
        encoding="utf-8",
    )

    lines = [
        "# HOPE Detector — Evaluation Report",
        "",
        f"Gold (cleaned): {len(gold)} answers / {n} prompts · embedder `{MODEL_NAME}`",
        "Features: answer-only MiniLM embedding + standardized alignment/length scalars (features.py).",
        "Split by prompt 70/15/15; C selected on val by QWK. bridge folds into KT.",
        "",
        "| signal | train | test | C | QWK | adjacent acc | strong−memorized sep |",
        "|---|---|---|---|---|---|---|",
    ]
    for sig, ntr, nte, C, qwk, adj, sep in report_rows:
        gate = "PASS" if sep >= 1.0 else "WEAK"
        lines.append(f"| {sig} | {ntr} | {nte} | {C} | {qwk:.3f} | {adj:.3f} | {sep:.2f} ({gate}) |")
    lines += [
        "",
        "QWK gate (report section 5): >= 0.6 desired. Discrimination gate: strong answer "
        "out-scores memorized by >= 1 ordinal.",
        "",
        "**Label caveat:** `final_label` = round((rater_a + rater_b)/2), both LLM "
        "(gemini-flash + gemini-pro stand-in; raters agreed 84% exact / 98.6% within 1). "
        "The human round was a 30-prompt quality audit + the drop decision, not a full "
        "re-label. Replace with teacher labels before production scale.",
        "",
        f"Build time: {time.time() - t0:.0f}s",
    ]
    (out / "eval_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"artifacts -> {out}")


if __name__ == "__main__":
    main()
