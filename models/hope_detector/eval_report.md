# HOPE Detector — Evaluation Report

Gold (cleaned): 888 answers / 222 prompts · embedder `sentence-transformers/all-MiniLM-L6-v2`
Features: answer-only MiniLM embedding + standardized alignment/length scalars (features.py).
Split by prompt 70/15/15; C selected on val by QWK. bridge folds into KT.

| signal | train | test | C | QWK | adjacent acc | strong−memorized sep |
|---|---|---|---|---|---|---|
| KI | 244 | 28 | 1.0 | 0.527 | 0.679 | 1.65 (PASS) |
| KT | 212 | 52 | 3.0 | 0.448 | 0.827 | 1.29 (PASS) |
| CT | 164 | 52 | 3.0 | 0.651 | 0.865 | 1.81 (PASS) |

QWK gate (report section 5): >= 0.6 desired. Discrimination gate: strong answer out-scores memorized by >= 1 ordinal.

**Label caveat:** `final_label` = round((rater_a + rater_b)/2), both LLM (gemini-flash + gemini-pro stand-in; raters agreed 84% exact / 98.6% within 1). The human round was a 30-prompt quality audit + the drop decision, not a full re-label. Replace with teacher labels before production scale.

Build time: 64s