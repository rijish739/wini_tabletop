"""Build the exemplar classifier artifacts from the CURATED dataset.

Pipeline:
  1. load dataset/exemplar_dataset_10000_curated.json (run curate_dataset.py
     first — it is the gold-rule projection of the canonical _fixed.json);
     canonicalize labels, drop labels below MIN_SUPPORT
  2. splits: REUSE the row_ids from models/exemplar_classifier/splits.json when
     present (the shared evaluation contract for every model trained on this
     dataset); otherwise create a seeded stratified 80/10/10 split over the
     10000 base rows. The 800 supplementary rows (split=="train") and
     dataset/augmented_rare_labels.json rows are appended to the TRAIN bank only.
  3. embed with all-MiniLM-L6-v2 (normalized); the logistic head additionally
     sees the 9 binary cue features (cues.py) that pooling dilutes
  4. tune k/m on validation; calibrate per-label thresholds on OUT-OF-FOLD
     train predictions (5-fold), clamped to [0.10, 0.90] — rare labels get
     hundreds of calibration positives instead of ~10 validation ones
  5. select the scorer family (knn / evidence / logreg / ensembles) by
     validation macro-F1; report held-out test metrics for all candidates
  6. write artifacts to models/exemplar_classifier/ + eval_report.md

Usage:
  python -m cognitive_classifier.curate_dataset   (once, after label-rule changes)
  python -m cognitive_classifier.augment_rare_labels   (optional, needs Vertex)
  python -m cognitive_classifier.build_bank
"""

from __future__ import annotations

import json
import random
import time
from collections import Counter
from pathlib import Path

import numpy as np

from .classifier import (
    DEFAULT_MODEL_DIR,
    MODEL_NAME,
    score_labels_evidence,
    score_labels_knn,
    score_labels_logreg,
)
from .cues import cue_matrix
from .label_space import MIN_SUPPORT, canonicalize_labels

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "dataset" / "exemplar_dataset_10000_curated.json"
AUGMENTED = ROOT / "dataset" / "augmented_rare_labels.json"
SEED = 42
K_GRID = (8, 16, 32, 64)
THRESHOLD_GRID = np.arange(0.05, 0.96, 0.01)
THRESHOLD_CLAMP = (0.10, 0.90)
OOF_FOLDS = 5


def load_rows() -> tuple[list[dict], list[str], int]:
    """Returns (rows, kept_labels, n_original).

    The curated dataset is the gold-rule projection of `_fixed.json`: 10000
    audit-corrected base rows followed by 800 T2/T3 supplementary rows that
    declare split=="train". Supplementary rows — like augmented_rare_labels.json
    rows (source='augmented') — are TRAIN-ONLY and never enter val/test, so only
    the base rows count toward n_original (the splittable pool)."""
    if not DATASET.exists():
        raise SystemExit(f"{DATASET.name} missing — run: python -m cognitive_classifier.curate_dataset")
    curated = json.loads(DATASET.read_text(encoding="utf-8"))
    base = [r for r in curated if r.get("split") != "train"]
    supp = [r for r in curated if r.get("split") == "train"]
    for r in supp:
        r["source"] = "supplementary"  # train-only; excluded from threshold calibration
    n_original = len(base)
    raw = base + supp
    if supp:
        print(f"{n_original} base rows + {len(supp)} supplementary rows (train bank only)")
    if AUGMENTED.exists():
        aug = json.loads(AUGMENTED.read_text(encoding="utf-8"))
        print(f"appending {len(aug)} augmented rows (train bank only)")
        raw = raw + aug
    rows = []
    for i, r in enumerate(raw):
        rows.append(
            {
                "row_id": i,
                "utterance": r["student_utterance"],
                "labels": canonicalize_labels(r["miniLM_labels"]),
                "concept_id": r["concept_id"],
                "category": r["category"],
                "source": r.get("source", "original"),
            }
        )
    support = Counter(l for r in rows for l in r["labels"])
    kept = sorted(l for l, c in support.items() if c >= MIN_SUPPORT)
    dropped = {l: c for l, c in support.items() if c < MIN_SUPPORT}
    if dropped:
        print(f"dropped below MIN_SUPPORT={MIN_SUPPORT}: {dropped}")
    kept_set = set(kept)
    for r in rows:
        r["labels"] = [l for l in r["labels"] if l in kept_set]
    rows = [r for r in rows if r["labels"] or r["source"] == "original"]
    return rows, kept, n_original


def stratified_split(rows: list[dict], n_original: int) -> dict[str, list[int]]:
    """Frozen-contract split: reuse saved row_ids when available, else create a
    seeded 80/10/10 stratified by primary label. Augmented rows always train."""
    saved = DEFAULT_MODEL_DIR / "splits.json"
    pos_by_row_id = {r["row_id"]: i for i, r in enumerate(rows)}
    if saved.exists():
        frozen = json.loads(saved.read_text(encoding="utf-8"))["row_ids"]
        splits = {
            part: sorted(pos_by_row_id[rid] for rid in frozen[part] if rid in pos_by_row_id)
            for part in ("train", "val", "test")
        }
        print("reusing frozen splits.json row_ids")
    else:
        original = [i for i, r in enumerate(rows) if r["row_id"] < n_original]
        primary_support = Counter(rows[i]["labels"][0] for i in original if rows[i]["labels"])
        rng = random.Random(SEED)
        buckets: dict[str, list[int]] = {}
        for idx in original:
            r = rows[idx]
            if not r["labels"]:
                continue
            key = r["labels"][0] if primary_support[r["labels"][0]] >= 30 else "__rare__"
            buckets.setdefault(key, []).append(idx)
        splits = {"train": [], "val": [], "test": []}
        for key in sorted(buckets):
            idxs = buckets[key]
            rng.shuffle(idxs)
            n = len(idxs)
            n_val, n_test = max(1, round(n * 0.10)), max(1, round(n * 0.10))
            splits["val"] += idxs[:n_val]
            splits["test"] += idxs[n_val : n_val + n_test]
            splits["train"] += idxs[n_val + n_test :]
        for part in splits.values():
            part.sort()
    # augmented rows (row_id >= n_original) join the train bank only
    aug_pos = {i for i, r in enumerate(rows) if r["row_id"] >= n_original and r["labels"]}
    splits["train"] = sorted(set(splits["train"]) | aug_pos)
    return splits


def label_matrix(rows: list[dict], idxs: list[int], labels: list[str]) -> np.ndarray:
    index = {l: i for i, l in enumerate(labels)}
    mat = np.zeros((len(idxs), len(labels)), dtype=np.float32)
    for row, idx in enumerate(idxs):
        for l in rows[idx]["labels"]:
            mat[row, index[l]] = 1.0
    return mat


def calibrate_thresholds(scores: np.ndarray, truth: np.ndarray) -> np.ndarray:
    """Per-label max-F1 threshold, clamped. Calibrate on OUT-OF-FOLD train
    predictions, not the small validation split — a 2%-prevalence label then
    has ~160 calibration positives instead of ~10."""
    n_labels = truth.shape[1]
    thresholds = np.full(n_labels, 0.5, dtype=np.float32)
    for j in range(n_labels):
        pos = truth[:, j].sum()
        if pos == 0:
            continue
        best_f1, best_t = -1.0, 0.5
        for t in THRESHOLD_GRID:
            pred = scores[:, j] >= t
            tp = float((pred & (truth[:, j] == 1)).sum())
            if tp == 0:
                continue
            precision = tp / pred.sum()
            recall = tp / pos
            f1 = 2 * precision * recall / (precision + recall)
            if f1 > best_f1:
                best_f1, best_t = f1, t
        thresholds[j] = best_t
    return np.clip(thresholds, *THRESHOLD_CLAMP)


def f1_summary(pred: np.ndarray, truth: np.ndarray) -> dict:
    tp = (pred & (truth == 1)).sum()
    micro_p = tp / max(pred.sum(), 1)
    micro_r = tp / max(truth.sum(), 1)
    micro_f1 = 2 * micro_p * micro_r / max(micro_p + micro_r, 1e-9)
    per_label = []
    for j in range(truth.shape[1]):
        tp_j = float((pred[:, j] & (truth[:, j] == 1)).sum())
        p = tp_j / max(pred[:, j].sum(), 1)
        r = tp_j / max(truth[:, j].sum(), 1)
        f1 = 2 * p * r / max(p + r, 1e-9)
        per_label.append({"precision": p, "recall": r, "f1": f1, "support": int(truth[:, j].sum())})
    macro_f1 = float(np.mean([m["f1"] for m in per_label if m["support"] > 0]))
    return {"micro_f1": float(micro_f1), "macro_f1": macro_f1, "per_label": per_label}


def main() -> None:
    t0 = time.time()
    rows, labels, n_original = load_rows()
    print(f"rows={len(rows)}  canonical labels={len(labels)}")

    splits = stratified_split(rows, n_original)
    print({part: len(idxs) for part, idxs in splits.items()})

    from sentence_transformers import SentenceTransformer

    embedder = SentenceTransformer(MODEL_NAME)
    texts = [r["utterance"] for r in rows]
    embeddings = np.asarray(
        embedder.encode(texts, batch_size=256, normalize_embeddings=True, show_progress_bar=True),
        dtype=np.float32,
    )
    cues = cue_matrix(texts)  # 9 binary surface cues, logreg head only

    train_idx, val_idx, test_idx = splits["train"], splits["val"], splits["test"]
    bank_emb = embeddings[train_idx]
    bank_truth = label_matrix(rows, train_idx, labels)
    bank_aug = np.hstack([bank_emb, cues[train_idx]])
    val_emb, val_truth = embeddings[val_idx], label_matrix(rows, val_idx, labels)
    val_aug = np.hstack([val_emb, cues[val_idx]])
    test_emb, test_truth = embeddings[test_idx], label_matrix(rows, test_idx, labels)
    test_aug = np.hstack([test_emb, cues[test_idx]])
    # calibration uses original-distribution rows only (augmented rows may
    # legitimately skew score distributions toward their target labels)
    orig_mask = np.array([rows[i]["source"] == "original" for i in train_idx])

    # --- candidate scorers ------------------------------------------------------
    # Hyperparameters (k, m) tuned on validation inside their families, then the
    # scorer family itself selected by validation macro-F1.
    from sklearn.linear_model import LogisticRegression
    from sklearn.multiclass import OneVsRestClassifier

    # n_jobs left sequential: joblib's loky backend breaks on Windows here
    def fit_logreg(features: np.ndarray, truth: np.ndarray):
        model = OneVsRestClassifier(LogisticRegression(max_iter=1000, C=4.0))
        model.fit(features, truth)
        c = np.vstack([est.coef_[0] for est in model.estimators_]).astype(np.float32)
        b = np.array([est.intercept_[0] for est in model.estimators_], dtype=np.float32)
        return c, b

    coef, intercept = fit_logreg(bank_aug, bank_truth)

    def best_in_family(scorer_fn, grid, name):
        winner = None
        for p in grid:
            scores = scorer_fn(val_emb, p)
            thr = calibrate_thresholds(scores, val_truth)
            macro = f1_summary(scores >= thr, val_truth)["macro_f1"]
            print(f"  {name} param={p:>3}  val macro_f1={macro:.4f}")
            if winner is None or macro > winner[1]:
                winner = (p, macro)
        return winner[0]

    print("tuning knn k:")
    k = best_in_family(lambda e, p: score_labels_knn(e, bank_emb, bank_truth, p), K_GRID, "knn")
    print("tuning evidence m:")
    m = best_in_family(lambda e, p: score_labels_evidence(e, bank_emb, bank_truth, p), (1, 3, 5, 10), "evidence")

    # --- out-of-fold train scores for threshold calibration (FIX 3) ------------
    print(f"computing {OOF_FOLDS}-fold OOF scores for calibration…")
    n_train = len(train_idx)
    rng = np.random.RandomState(SEED)
    fold_of = rng.permutation(n_train) % OOF_FOLDS
    oof = {c: np.zeros((n_train, len(labels)), dtype=np.float32) for c in ("knn", "evidence", "logreg")}
    for f in range(OOF_FOLDS):
        infold = np.flatnonzero(fold_of == f)
        outfold = np.flatnonzero(fold_of != f)
        oof["knn"][infold] = score_labels_knn(bank_emb[infold], bank_emb[outfold], bank_truth[outfold], k)
        oof["evidence"][infold] = score_labels_evidence(bank_emb[infold], bank_emb[outfold], bank_truth[outfold], m)
        cf, bf = fit_logreg(bank_aug[outfold], bank_truth[outfold])
        oof["logreg"][infold] = score_labels_logreg(bank_aug[infold], cf, bf)

    def scores_for(scorer: str, emb: np.ndarray, aug: np.ndarray) -> np.ndarray:
        parts = []
        for component in scorer.split("+"):
            if component == "knn":
                parts.append(score_labels_knn(emb, bank_emb, bank_truth, k))
            elif component == "evidence":
                parts.append(score_labels_evidence(emb, bank_emb, bank_truth, m))
            elif component == "logreg":
                parts.append(score_labels_logreg(aug, coef, intercept))
        return np.mean(parts, axis=0)

    candidates = ["knn", "evidence", "logreg", "knn+logreg", "evidence+logreg"]
    results = {}
    best_scorer = None
    for scorer in candidates:
        oof_scores = np.mean([oof[c] for c in scorer.split("+")], axis=0)
        thr = calibrate_thresholds(oof_scores[orig_mask], bank_truth[orig_mask])
        val_sum = f1_summary(scores_for(scorer, val_emb, val_aug) >= thr, val_truth)
        test_sum = f1_summary(scores_for(scorer, test_emb, test_aug) >= thr, test_truth)
        results[scorer] = {"thresholds": thr, "val": val_sum, "test": test_sum}
        print(
            f"{scorer:<16} val micro/macro {val_sum['micro_f1']:.4f}/{val_sum['macro_f1']:.4f}"
            f"   test micro/macro {test_sum['micro_f1']:.4f}/{test_sum['macro_f1']:.4f}"
        )
        if best_scorer is None or val_sum["macro_f1"] > results[best_scorer]["val"]["macro_f1"]:
            best_scorer = scorer
    print(f"selected scorer={best_scorer} (k={k}, m={m})")
    thresholds = results[best_scorer]["thresholds"]
    exemplar_eval = results[best_scorer]["test"]

    # --- save artifacts ---------------------------------------------------------
    out = DEFAULT_MODEL_DIR
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / "bank_embeddings.npy", bank_emb)
    with (out / "bank_meta.jsonl").open("w", encoding="utf-8") as f:
        for idx in train_idx:
            r = rows[idx]
            f.write(json.dumps({k2: r[k2] for k2 in ("row_id", "utterance", "labels", "concept_id", "category", "source")}, ensure_ascii=False) + "\n")
    (out / "label_space.json").write_text(json.dumps({"labels": labels, "min_support": MIN_SUPPORT}, indent=2), encoding="utf-8")
    np.savez(out / "logreg.npz", coef=coef, intercept=intercept)
    (out / "thresholds.json").write_text(
        json.dumps(
            {"scorer": best_scorer, "k": k, "m": m, "logreg_cues": True,
             "calibration": f"{OOF_FOLDS}-fold OOF, clamp {THRESHOLD_CLAMP}",
             "thresholds": {l: round(float(t), 2) for l, t in zip(labels, thresholds)}},
            indent=2,
        ),
        encoding="utf-8",
    )
    # frozen split contract: original-row ids only (augmented rows are a train-
    # time overlay and may be regenerated without invalidating the contract)
    (out / "splits.json").write_text(
        json.dumps({"seed": SEED, "dataset": DATASET.name,
                    "row_ids": {p: [rows[i]["row_id"] for i in idxs if rows[i]["row_id"] < n_original]
                                for p, idxs in splits.items()}}),
        encoding="utf-8",
    )

    # --- report -----------------------------------------------------------------
    lines = [
        "# Exemplar Cognitive Classifier — Evaluation Report",
        "",
        f"Dataset: `{DATASET.name}` · rows used: {len(rows)} "
        f"({int(orig_mask.sum())} original + {int((~orig_mask).sum())} augmented in train) · canonical labels: {len(labels)}",
        f"Split: train {len(train_idx)} / val {len(val_idx)} / test {len(test_idx)} (seed {SEED}; test/val 100% original rows)",
        f"Embedder: `{MODEL_NAME}` (frozen, normalized) · selected scorer = **{best_scorer}** (k={k}, m={m}) "
        f"· logreg uses 9 cue features · thresholds: {OOF_FOLDS}-fold OOF, clamp {THRESHOLD_CLAMP}",
        "",
        "## Scorer comparison (thresholds from OOF train; selection by val macro-F1)",
        "",
        "| scorer | val micro-F1 | val macro-F1 | test micro-F1 | test macro-F1 |",
        "|---|---|---|---|---|",
    ]
    for scorer in candidates:
        r = results[scorer]
        marker = " **(shipped)**" if scorer == best_scorer else ""
        lines.append(
            f"| {scorer}{marker} | {r['val']['micro_f1']:.4f} | {r['val']['macro_f1']:.4f} "
            f"| {r['test']['micro_f1']:.4f} | {r['test']['macro_f1']:.4f} |"
        )
    lines += [
        "",
        "## Per-label test metrics (shipped scorer)",
        "",
        "| label | support | precision | recall | F1 | threshold |",
        "|---|---|---|---|---|---|",
    ]
    order = np.argsort([-m["support"] for m in exemplar_eval["per_label"]])
    for j in order:
        m = exemplar_eval["per_label"][j]
        lines.append(
            f"| {labels[j]} | {m['support']} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} | {thresholds[j]:.2f} |"
        )
    lines += [
        "",
        f"Build time: {time.time() - t0:.0f}s",
    ]
    (out / "eval_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nshipped scorer={best_scorer}  test micro_f1={exemplar_eval['micro_f1']:.4f} macro_f1={exemplar_eval['macro_f1']:.4f}")
    print(f"artifacts -> {out}")


if __name__ == "__main__":
    main()
