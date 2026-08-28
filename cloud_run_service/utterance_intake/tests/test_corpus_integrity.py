"""Corpus-integrity validator — a gate, not a document.

Runs in the free lane. It fails on a malformed fixture row, an empty grid cell,
or a generator family violation so the coverage corpora cannot silently rot.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

FIXTURES = Path(__file__).with_name("fixtures")
SERVICE_ROOT = Path(__file__).parents[2]
CORPORA_DIR = SERVICE_ROOT / "eval" / "corpora"

_INTAKE_REQUIRED = {
    "normalized_text", "authorization", "safety_tripped", "illegible",
    "problem_is_problem", "parse_outcome", "has_anaphora",
}
_DIFF_REQUIRED = {"id", "function", "input_id", "before", "after", "reason", "ticket"}

_MANIFEST_REQUIRED = {
    "name", "authoring_rule", "size_floor", "schema", "gate", "owner",
    "path", "reviewed_by", "reviewed_at", "review_scope", "record_path",
}

_SUPERSET_REQUIRED = {"id", "text", "label", "source", "grid_cell"}

SAFETY_CLASSES = {
    "SELF_HARM", "HARM_BY_OTHER", "THREAT_TO_CHILD", "THREAT_BY_CHILD",
    "PEER_AT_RISK", "UNSAFE_CONTACT", "UNSPECIFIED_CONCERN",
}

PII_CLASSES = {
    "NAME", "SCHOOL", "ADDRESS", "LIVE_LOCATION", "PHONE",
    "EMAIL", "CREDENTIAL", "GOVERNMENT_ID", "OTHER_IDENTIFIER",
}


def _rows(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for n, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:  # pragma: no cover - failure path
                raise AssertionError(f"{path.name}:{n} is not valid JSON: {exc}")
    return rows


class IntakeCorpusIntegrity(unittest.TestCase):
    def test_intake_observations_rows_are_well_formed(self) -> None:
        rows = _rows(FIXTURES / "intake_observations.jsonl")
        self.assertGreater(len(rows), 0)
        seen_ids: set[str] = set()
        for row in rows:
            self.assertIn("id", row)
            self.assertNotIn(row["id"], seen_ids, f"duplicate id {row['id']}")
            seen_ids.add(row["id"])
            self.assertIn("utterance", row)
            self.assertIn("text", row["utterance"])
            expected = row.get("expected") or {}
            missing = _INTAKE_REQUIRED - expected.keys()
            self.assertEqual(missing, set(), f"{row['id']} missing {missing}")


class ExpectedDiffManifestIsLive(unittest.TestCase):
    def test_manifest_parses_and_rows_are_closed_shape(self) -> None:
        path = FIXTURES / "expected_diffs.jsonl"
        self.assertTrue(path.exists(), "the expected-diff manifest file must exist")
        for row in _rows(path):
            missing = _DIFF_REQUIRED - row.keys()
            self.assertEqual(missing, set(), f"diff row missing {missing}")


class CorpusManifestIntegrity(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest_path = CORPORA_DIR / "corpus_manifest.jsonl"
        self.assertTrue(self.manifest_path.exists(), "corpus_manifest.jsonl must exist")
        self.manifest_rows = _rows(self.manifest_path)

    def test_manifest_has_all_22_required_corpora(self) -> None:
        self.assertGreaterEqual(len(self.manifest_rows), 22)
        names = {r["name"] for r in self.manifest_rows}
        # Safety per-class + FP + degraded + legacy
        for sc in SAFETY_CLASSES:
            self.assertIn(f"safety_{sc.lower()}", names)
        self.assertIn("safety_false_positives", names)
        self.assertIn("safety_degraded_net", names)
        self.assertIn("safety_legacy_20", names)
        # PII per-class + math precision
        for pc in PII_CLASSES:
            self.assertIn(f"pii_{pc.lower()}", names)
        self.assertIn("pii_maths_dense_precision", names)
        # STT & Intake
        self.assertIn("stt_captured_fixtures", names)
        self.assertIn("intake_frozen_inputs", names)

    def test_manifest_rows_have_closed_schema_and_files_exist(self) -> None:
        for row in self.manifest_rows:
            missing = _MANIFEST_REQUIRED - row.keys()
            self.assertEqual(missing, set(), f"manifest entry {row.get('name')} missing fields {missing}")
            corpus_file = SERVICE_ROOT / row["path"]
            self.assertTrue(corpus_file.exists(), f"Corpus file not found: {corpus_file}")
            corpus_rows = _rows(corpus_file)
            self.assertGreaterEqual(
                len(corpus_rows),
                row["size_floor"],
                f"Corpus {row['name']} size {len(corpus_rows)} below floor {row['size_floor']}",
            )


class SupersetRowAndSourceIntegrity(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest_rows = _rows(CORPORA_DIR / "corpus_manifest.jsonl")

    def test_all_corpus_rows_have_required_fields_and_unique_ids(self) -> None:
        for m_row in self.manifest_rows:
            corpus_file = SERVICE_ROOT / m_row["path"]
            rows = _rows(corpus_file)
            seen_ids: set[str] = set()
            for r in rows:
                missing = _SUPERSET_REQUIRED - r.keys()
                self.assertEqual(missing, set(), f"{corpus_file.name}:{r.get('id')} missing {missing}")
                self.assertNotIn(r["id"], seen_ids, f"duplicate id {r['id']} in {corpus_file.name}")
                seen_ids.add(r["id"])
                # Source format
                source = r["source"]
                valid_source = source in {"authored", "captured"} or source.startswith("generated:")
                self.assertTrue(valid_source, f"Invalid source '{source}' in {r['id']}")

    def test_different_generator_family_for_safety_and_pii(self) -> None:
        """The integrity test asserts no safety or PII row was generated by VERTEX_SAFETY_MODEL."""
        vertex_model = os.environ.get("VERTEX_SAFETY_MODEL", "gemini-2.5-flash").lower()
        for m_row in self.manifest_rows:
            name = m_row["name"]
            if not (name.startswith("safety_") or name.startswith("pii_")):
                continue
            if name in {"safety_legacy_20", "safety_degraded_net"}:
                continue  # Authored legacy/net
            corpus_file = SERVICE_ROOT / m_row["path"]
            rows = _rows(corpus_file)
            for r in rows:
                source = r["source"]
                if source.startswith("generated:"):
                    gen_model = source.split(":", 1)[1].lower()
                    self.assertFalse(
                        gen_model.startswith("gemini") or gen_model == vertex_model,
                        f"Safety/PII row {r['id']} generated by forbidden model family '{gen_model}' (matches {vertex_model})",
                    )


class GridIntegrityValidator(unittest.TestCase):
    def test_safety_grids_have_no_empty_cell_and_meet_indirect_floor(self) -> None:
        safety_classes = list(SAFETY_CLASSES) + ["SAFETY_FP"]
        for class_name in safety_classes:
            grid_file = CORPORA_DIR / "safety_grids" / f"{class_name}.json"
            self.assertTrue(grid_file.exists(), f"Grid file missing: {grid_file}")
            with open(grid_file, "r", encoding="utf-8") as f:
                grid_data = json.load(f)

            cells = grid_data.get("cells", {})
            self.assertEqual(len(cells), 16, f"Safety grid {class_name} does not have 16 cells")
            total_examples = 0
            indirect_or_euphemistic_examples = 0
            for cell_key, row_ids in cells.items():
                self.assertGreater(len(row_ids), 0, f"Empty grid cell '{cell_key}' in safety grid {class_name}")
                total_examples += len(row_ids)
                parts = cell_key.split("|")
                directness, register, codesw, euphemism = parts[0], parts[1], parts[2], parts[3]
                if directness == "indirect" or euphemism == "euphemistic":
                    indirect_or_euphemistic_examples += len(row_ids)

            if class_name != "SAFETY_FP":
                indirect_ratio = indirect_or_euphemistic_examples / total_examples
                self.assertGreaterEqual(
                    indirect_ratio,
                    0.40,
                    f"Safety class {class_name} has indirect ratio {indirect_ratio:.2f} < 0.40 floor",
                )

    def test_pii_grids_have_no_empty_cell(self) -> None:
        for class_name in PII_CLASSES:
            grid_file = CORPORA_DIR / "pii_grids" / f"{class_name}.json"
            self.assertTrue(grid_file.exists(), f"Grid file missing: {grid_file}")
            with open(grid_file, "r", encoding="utf-8") as f:
                grid_data = json.load(f)

            cells = grid_data.get("cells", {})
            self.assertEqual(len(cells), 16, f"PII grid {class_name} does not have 16 cells")
            for cell_key, row_ids in cells.items():
                self.assertGreater(len(row_ids), 0, f"Empty grid cell '{cell_key}' in PII grid {class_name}")


class SpecializedCorporaIntegrity(unittest.TestCase):
    def test_maths_dense_precision_corpus(self) -> None:
        path = CORPORA_DIR / "pii" / "maths_dense_precision.jsonl"
        self.assertTrue(path.exists())
        rows = _rows(path)
        self.assertGreaterEqual(len(rows), 500)
        for r in rows:
            self.assertEqual(r["label"], "NONE", f"Non-zero label {r['label']} in precision corpus {r['id']}")

    def test_degraded_net_freeze_corpus(self) -> None:
        path = CORPORA_DIR / "safety" / "degraded_net.jsonl"
        self.assertTrue(path.exists())
        rows = _rows(path)
        self.assertGreaterEqual(len(rows), 50)
        for r in rows:
            self.assertIn("tripped", r["label"])

    def test_legacy_20_suite_exact_20_rows(self) -> None:
        path = CORPORA_DIR / "safety" / "legacy_20.jsonl"
        self.assertTrue(path.exists())
        rows = _rows(path)
        self.assertEqual(len(rows), 20)

    def test_captured_stt_fixtures_have_stt_payload(self) -> None:
        path = CORPORA_DIR / "stt" / "captured_stt_fixtures.jsonl"
        self.assertTrue(path.exists())
        rows = _rows(path)
        self.assertGreaterEqual(len(rows), 10)
        for r in rows:
            self.assertIn("stt", r)
            self.assertIn("recognizer", r["stt"])
            self.assertIn("confidence", r["stt"])
            self.assertIn("alternates", r["stt"])

    def test_frozen_intake_inputs_set_covers_required_categories(self) -> None:
        path = FIXTURES / "frozen_intake_inputs.jsonl"
        self.assertTrue(path.exists())
        rows = _rows(path)
        self.assertGreaterEqual(len(rows), 150)
        labels = {r["label"] for r in rows}
        self.assertIn("baseline_oracle_seed", labels)
        self.assertIn("nfkc_typography", labels)
        self.assertIn("confident_false_negative", labels)
        self.assertIn("terse_real_answer", labels)
        self.assertIn("nonsense_probe", labels)
        # Check homophone table coverage (at least 40 homophone entries)
        homophone_rows = [r for r in rows if r["label"].startswith("homophone_table_")]
        self.assertGreaterEqual(len(homophone_rows), 40)
        # Check problem cue coverage
        problem_rows = [r for r in rows if r["label"].startswith("problem_cue_")]
        self.assertGreaterEqual(len(problem_rows), 3)

    def test_no_production_data_leakage_from_learning_log(self) -> None:
        learning_log_path = SERVICE_ROOT / "rag_store" / "learning_log.jsonl"
        if not learning_log_path.exists():
            return
        prod_utterances: set[str] = set()
        with open(learning_log_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    text = obj.get("utterance") or obj.get("text") or obj.get("student_utterance")
                    if text:
                        prod_utterances.add(text.strip().lower())
                except Exception:
                    pass

        # Check safety and PII rows
        manifest_rows = _rows(CORPORA_DIR / "corpus_manifest.jsonl")
        for m_row in manifest_rows:
            if not (m_row["name"].startswith("safety_") or m_row["name"].startswith("pii_")):
                continue
            if m_row["name"] == "pii_maths_dense_precision":
                continue  # Sourced from fixed exemplar dataset
            corpus_file = SERVICE_ROOT / m_row["path"]
            for r in _rows(corpus_file):
                t = r["text"].strip().lower()
                self.assertNotIn(
                    t,
                    prod_utterances,
                    f"Production utterance leak in {m_row['name']}:{r['id']} ('{r['text']}')",
                )


if __name__ == "__main__":
    unittest.main()
