# dataset/archive — NOT used by the build pipeline

Canonical dataset of record: `../exemplar_dataset_10000_fixed.json` (10000 base rows + 800 T2/T3 supplementary rows with `split:"train"`).

`../exemplar_dataset_10000_curated.json` is its gold-rule projection (built by `cognitive_classifier/curate_dataset.py`) and is the input to build_bank / build_policy / concept_resolver.

Files here are kept for provenance only:
- `exemplar_dataset_10000.json|.csv` — the original raw generation output (was the curate source before re-pointing to _fixed.json).
- `exemplar_dataset_100.json|.csv` — pre-scale 100-row sample.
- `*.backup_*.json` — superseded dataset snapshots.
