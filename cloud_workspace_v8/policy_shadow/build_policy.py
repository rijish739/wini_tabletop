"""Train + evaluate the policy shadow model (plan Part 5).

Data: curated dataset's `target_policy_action` (canonicalized 27 -> 15
actions; 9 RESUME_STATE/REQUEST_HINT rows dropped). Frozen Part 1 splits.
Features are exactly what the runtime can compute per turn (shadow.py
feature_vector): MiniLM embedding + Part-1 label scores + section 6.2
cognitive-update aggregates. Model: multinomial logistic regression.

Baselines: majority class; embedding-only logreg (shows what the cognitive
features add).

Usage:  python -m policy_shadow.build_policy
"""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

import numpy as np

from cognitive_analyzer.analyzer import derive_cognitive_update
from cognitive_classifier import ExemplarCognitiveClassifier
from cognitive_classifier.cues import cue_matrix
from .shadow import DEFAULT_MODEL_DIR, UPDATE_KEYS, canonicalize_action

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "dataset" / "exemplar_dataset_10000_curated.json"
SPLITS = ROOT / "models" / "exemplar_classifier" / "splits.json"


def main() -> None:
    t0 = time.time()
    rows = json.loads(DATASET.read_text(encoding="utf-8"))
    splits = json.loads(SPLITS.read_text(encoding="utf-8"))["row_ids"]

    action_of = [canonicalize_action(r["target_policy_action"]) for r in rows]
    actions = sorted({a for a in action_of if a})
    aindex = {a: i for i, a in enumerate(actions)}
    dropped = sum(1 for a in action_of if a is None)
    print(f"{len(actions)} actions, {dropped} rows dropped (non-pedagogy labels)")

    print("loading Part-1 classifier + embedding 10k utterances…")
    clf = ExemplarCognitiveClassifier.load()
    texts = [r["student_utterance"] for r in rows]
    emb = clf.embed(texts)
    cues = cue_matrix(texts)

    print("scoring labels in batches…")
    scores = np.zeros((len(rows), len(clf.labels)), dtype=np.float32)
    for start in range(0, len(rows), 512):
        end = min(start + 512, len(rows))
        scores[start:end] = clf.score_matrix(emb[start:end], cues[start:end])

    updates = np.array(
        [[derive_cognitive_update(dict(zip(clf.labels, s)))[k] for k in UPDATE_KEYS] for s in scores],
        dtype=np.float32,
    )
    features = np.hstack([emb, scores, updates])

    # Supplementary rows (T2/T3, split=="train") live after the 10000 base rows
    # in the curated file and are NOT referenced by splits.json (which indexes
    # base rows only). Fold them into the TRAIN set so the policy also learns
    # from the new acknowledgment / weak-label data; they never enter val/test.
    supp_idx = [i for i, r in enumerate(rows)
                if r.get("split") == "train" and action_of[i] is not None]

    def part(name):
        idx = [i for i in splits[name] if action_of[i] is not None]
        if name == "train":
            idx = idx + supp_idx
        return np.array(idx), np.array([aindex[action_of[i]] for i in idx])

    tr_idx, tr_y = part("train")
    va_idx, va_y = part("val")
    te_idx, te_y = part("test")
    print({"train": len(tr_idx), "val": len(va_idx), "test": len(te_idx),
           "supplementary_in_train": len(supp_idx)})

    from sklearn.linear_model import LogisticRegression

    def fit_eval(X_cols, tag):
        best = None
        for C in (0.5, 1.0, 4.0):
            model = LogisticRegression(max_iter=2000, C=C)
            model.fit(features[tr_idx][:, X_cols], tr_y)
            acc = (model.predict(features[va_idx][:, X_cols]) == va_y).mean()
            if best is None or acc > best[1]:
                best = (model, acc, C)
        model, va_acc, C = best
        proba = model.predict_proba(features[te_idx][:, X_cols])
        pred = proba.argmax(axis=1)
        classes = model.classes_
        top1 = (classes[pred] == te_y).mean()
        order2 = np.argsort(-proba, axis=1)[:, :2]
        top2 = np.any(classes[order2] == te_y[:, None], axis=1).mean()
        print(f"{tag}: C={C} val_acc={va_acc:.4f} test top1={top1:.4f} top2={top2:.4f}")
        return model, {"val_acc": float(va_acc), "top1": float(top1), "top2": float(top2), "C": C}

    n_emb = emb.shape[1]
    all_cols = np.arange(features.shape[1])
    emb_cols = np.arange(n_emb)

    majority = Counter(tr_y).most_common(1)[0][0]
    maj_acc = float((te_y == majority).mean())
    print(f"majority baseline ({actions[majority]}): test acc={maj_acc:.4f}")
    _, emb_only = fit_eval(emb_cols, "emb-only")
    model, full = fit_eval(all_cols, "full-features")

    # per-action test metrics for the shipped (full) model
    proba = model.predict_proba(features[te_idx])
    pred = model.classes_[proba.argmax(axis=1)]
    per_action = []
    for a, j in aindex.items():
        tp = float(((pred == j) & (te_y == j)).sum())
        p = tp / max((pred == j).sum(), 1)
        r = tp / max((te_y == j).sum(), 1)
        f1 = 2 * p * r / max(p + r, 1e-9)
        per_action.append((a, int((te_y == j).sum()), p, r, f1))

    out = DEFAULT_MODEL_DIR
    out.mkdir(parents=True, exist_ok=True)
    np.savez(out / "policy_logreg.npz",
             coef=model.coef_.astype(np.float32),
             intercept=model.intercept_.astype(np.float32),
             classes=model.classes_.astype(np.int64))
    (out / "actions.json").write_text(
        json.dumps({"actions": actions, "update_keys": UPDATE_KEYS,
                    "n_label_scores": len(clf.labels)}, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Policy Shadow Model — Evaluation Report",
        "",
        f"Actions: {len(actions)} (canonicalized from 27 raw values; {dropped} rows dropped)",
        f"Features: emb({n_emb}) + label_scores({len(clf.labels)}) + update({len(UPDATE_KEYS)})",
        "",
        "| model | test top-1 | test top-2 |",
        "|---|---|---|",
        f"| majority class | {maj_acc:.4f} | - |",
        f"| embedding only | {emb_only['top1']:.4f} | {emb_only['top2']:.4f} |",
        f"| full features **(shipped)** | {full['top1']:.4f} | {full['top2']:.4f} |",
        "",
        "## Per-action test metrics (shipped)",
        "",
        "| action | support | precision | recall | F1 |",
        "|---|---|---|---|---|",
    ]
    for a, sup, p, r, f1 in sorted(per_action, key=lambda x: -x[1]):
        lines.append(f"| {a} | {sup} | {p:.3f} | {r:.3f} | {f1:.3f} |")
    lines += ["", f"Build time: {time.time() - t0:.0f}s",
              "", "SHADOW MODE: rules decide; suggestions are logged for comparison (plan Part 5)."]
    (out / "eval_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"artifacts -> {out}")


if __name__ == "__main__":
    main()
