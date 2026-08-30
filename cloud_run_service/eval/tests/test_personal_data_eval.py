"""Discipline tests for the personal-data eval harness (§12).

Offline and free. Nothing here calls Vertex; the point is to catch the ways an eval
lies **before** anyone pays for a collection — which is why the CI job runs this file
as a step *above* ``--collect``.

Three things are asserted, and each corresponds to a way a published number has
already gone wrong somewhere in this tree:

1. **No aggregate.** A mean over the nine classes is how PEER_AT_RISK and
   UNSAFE_CONTACT hid at zero behind a shipped "SAFETY recall 1.0".
2. **Caches are never mixed.** A row cached under a different prompt hash was produced
   by a different detector; scoring it reports a number for a system that does not
   exist.
3. **The cache holds no identifier values.** The eval cache is committed, uploaded as a
   CI artifact and read by humans — the worst possible place for §4 to leak.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from eval import personal_data_eval as pde
from personal_data.prompt import IDENTIFIER_CLASS_NAMES, prompt_hash

_EVAL = Path(__file__).resolve().parent.parent


class CorpusIntegrityTests(unittest.TestCase):
    def test_every_class_has_a_corpus_and_meets_its_size_floor(self) -> None:
        for label, filename in pde.POSITIVE_CORPORA.items():
            with self.subTest(label=label):
                rows = pde._read(filename)
                self.assertGreaterEqual(len(rows), 50, f"{label}: §12 floor is 50")

    def test_the_precision_corpus_meets_its_own_floor(self) -> None:
        rows = pde._read(pde.PRECISION_CORPUS)
        self.assertGreaterEqual(len(rows), 500, "§12 floor is 500 rows")

    def test_the_precision_corpus_declares_zero_identifiers(self) -> None:
        # Any finding on these rows is a false positive by definition, which only
        # holds if the corpus really does contain none.
        for row in pde._read(pde.PRECISION_CORPUS):
            self.assertEqual(row.get("label"), "NONE", row["id"])

    def test_the_corpora_cover_the_enum_exactly(self) -> None:
        self.assertEqual(
            tuple(pde.POSITIVE_CORPORA), IDENTIFIER_CLASS_NAMES,
            "a class with no corpus is a class measured by nothing",
        )

    def test_every_corpus_is_registered_in_the_manifest(self) -> None:
        review = pde._corpus_review_state()
        for filename in list(pde.POSITIVE_CORPORA.values()) + [pde.PRECISION_CORPUS]:
            name = f"pii_{filename.replace('.jsonl', '')}"
            self.assertIn(name, review, name)


class ReportingDisciplineTests(unittest.TestCase):
    """§12: publish no aggregate number anywhere."""

    def _results(self, class_recall: dict, fp_rate: float = 0.0) -> dict:
        return {
            "measured_at": "2026-08-28",
            "prompt_hash": "deadbeef", "prompt_version": "v1", "schema_version": "v1",
            "model_ids": ["gemini-2.5-flash"], "model_pinned": True, "n_scored": 100,
            "per_class": {
                label: {
                    "n": 64, "class_recall": class_recall.get(label, 0.9),
                    "any_finding_recall": 0.95, "redaction_integrity": 0.99,
                    "review_scope": "reviewed",
                }
                for label in IDENTIFIER_CLASS_NAMES
            },
            "maths_dense_precision": {
                "n": 550, "false_positives": int(550 * fp_rate), "rate": fp_rate,
                "max_rate": pde.MAX_FALSE_POSITIVE_RATE, "examples": [],
                "review_scope": "reviewed",
            },
        }

    def test_the_report_prints_no_mean_over_the_classes(self) -> None:
        # A class at 0.0 must be visible. If any aggregate existed, this report would
        # read as "mostly fine".
        results = self._results({"PEER_AT_RISK": 0.0, "CREDENTIAL": 0.0})
        report = pde.render(results)
        self.assertIn("BELOW", report)
        for banned in ("average", "mean", "overall", "macro"):
            self.assertNotIn(banned, report.lower(), banned)

    def test_a_below_floor_class_is_named_in_the_not_covered_section(self) -> None:
        results = self._results({"CREDENTIAL": 0.4})
        report = pde.render(results)
        self.assertIn("## Not covered", report)
        self.assertIn("`CREDENTIAL`", report.split("## Not covered")[1])

    def test_no_aggregate_is_computed_anywhere_in_the_harness(self) -> None:
        # A source guard, because the report is the easy half: the temptation is to
        # add `statistics.mean(...)` to `score()` "just for the summary line".
        tree = ast.parse((_EVAL / "personal_data_eval.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
                self.assertNotIn(
                    name, ("mean", "fmean", "median", "average"),
                    "§12 forbids an aggregate over the per-class numbers",
                )

    def test_an_unmeasured_class_prints_as_a_dash_not_as_zero(self) -> None:
        results = self._results({})
        results["per_class"]["EMAIL"]["class_recall"] = None
        report = pde.render(results)
        row = [line for line in report.splitlines() if "`EMAIL`" in line][0]
        self.assertIn("—", row)
        self.assertNotIn("0.000", row)


class GateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.results = ReportingDisciplineTests()._results({})

    def test_a_clean_run_passes(self) -> None:
        passed, blockers = pde.gate(self.results)
        self.assertTrue(passed, blockers)

    def test_an_unpinned_model_blocks(self) -> None:
        self.results["model_pinned"] = False
        passed, blockers = pde.gate(self.results)
        self.assertFalse(passed)
        self.assertIn("floating alias", " ".join(blockers))

    def test_an_unreviewed_corpus_blocks(self) -> None:
        self.results["per_class"]["PHONE"]["review_scope"] = "unreviewed"
        passed, blockers = pde.gate(self.results)
        self.assertFalse(passed)
        self.assertIn("unreviewed", " ".join(blockers))

    def test_a_below_floor_class_blocks_and_names_itself(self) -> None:
        self.results["per_class"]["CREDENTIAL"]["class_recall"] = 0.5
        passed, blockers = pde.gate(self.results)
        self.assertFalse(passed)
        self.assertIn("CREDENTIAL", " ".join(blockers))

    def test_the_precision_gate_is_hard(self) -> None:
        # §12: "The precision gate is hard, not advisory." Over-redaction is the
        # failure that breaks the product.
        self.results["maths_dense_precision"]["rate"] = 0.02
        self.results["maths_dense_precision"]["false_positives"] = 11
        passed, blockers = pde.gate(self.results)
        self.assertFalse(passed)
        self.assertIn("false-positive rate", " ".join(blockers))

    def test_precision_exactly_at_the_limit_passes(self) -> None:
        self.results["maths_dense_precision"]["rate"] = pde.MAX_FALSE_POSITIVE_RATE
        passed, blockers = pde.gate(self.results)
        self.assertTrue(passed, blockers)

    def test_the_recall_floor_is_the_published_state_of_the_art(self) -> None:
        # §12: the floor is 0.80 because MathEd-PII's domain-aware ceiling is
        # 0.80-0.82. A floor above the published ceiling is a gate that never goes
        # green, which in practice means a gate that gets waived.
        self.assertEqual(pde.RECALL_FLOOR, 0.80)
        self.assertEqual(pde.MAX_FALSE_POSITIVE_RATE, 0.01)


class CacheDisciplineTests(unittest.TestCase):
    def test_the_cache_filename_carries_the_prompt_hash(self) -> None:
        self.assertIn(prompt_hash(), pde.cache_path().name)

    def test_a_mixed_cache_is_a_hard_failure(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            original = pde.CACHE_DIR
            pde.CACHE_DIR = Path(td)
            try:
                pde.cache_path().write_text(
                    json.dumps({"id": "x", "prompt_hash": "some-other-hash"}) + "\n",
                    encoding="utf-8",
                )
                with self.assertRaises(SystemExit):
                    pde.load_cache()
            finally:
                pde.CACHE_DIR = original

    def test_the_cache_entry_holds_no_identifier_value(self) -> None:
        # §4: the verdict is identifier-bearing and is never serialized. This cache is
        # committed AND uploaded as a CI artifact.
        from personal_data import (
            IdentifierClass, IdentifierFinding, PersonalDataVerdict, VerdictStatus,
        )

        secret = "9876543210"
        verdict = PersonalDataVerdict(
            utterance_id="row-1", status=VerdictStatus.LANDED,
            findings=frozenset({IdentifierFinding(
                identifier_class=IdentifierClass.PHONE, value=secret)}),
        )
        entry = pde._cache_entry(
            {"id": "row-1", "corpus": "phone.jsonl", "gold_class": "PHONE",
             "text": f"my number is {secret}"},
            verdict,
        )
        self.assertNotIn(secret, json.dumps(entry))
        self.assertEqual(entry["predicted_classes"], ["PHONE"])
        self.assertTrue(entry["all_values_matched"])

    def test_an_unmatched_value_is_recorded_as_such(self) -> None:
        from personal_data import (
            IdentifierClass, IdentifierFinding, PersonalDataVerdict, VerdictStatus,
        )

        verdict = PersonalDataVerdict(
            utterance_id="row-1", status=VerdictStatus.LANDED,
            findings=frozenset({IdentifierFinding(
                identifier_class=IdentifierClass.PHONE, value="not-in-text")}),
        )
        entry = pde._cache_entry(
            {"id": "row-1", "corpus": "phone.jsonl", "gold_class": "PHONE",
             "text": "my number is 98765"},
            verdict,
        )
        self.assertFalse(entry["all_values_matched"])

    def test_score_refuses_to_run_without_a_cache(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            original = pde.CACHE_DIR
            pde.CACHE_DIR = Path(td)
            try:
                with self.assertRaises(SystemExit):
                    pde.score()
            finally:
                pde.CACHE_DIR = original


class ScoringRoundTripTests(unittest.TestCase):
    """Scoring reads what collection writes. Offline, with a synthetic cache."""

    def test_recall_and_precision_are_computed_from_the_cache(self) -> None:
        import tempfile

        rows = pde._all_rows()
        phone_rows = [r for r in rows if r["gold_class"] == "PHONE"]
        maths_rows = [r for r in rows if r["gold_class"] is None]
        with tempfile.TemporaryDirectory() as td:
            original = pde.CACHE_DIR
            pde.CACHE_DIR = Path(td)
            try:
                with pde.cache_path().open("w", encoding="utf-8") as handle:
                    # Every PHONE row correct except one.
                    for index, row in enumerate(phone_rows):
                        handle.write(json.dumps({
                            "id": row["id"], "corpus": row["corpus"],
                            "gold_class": "PHONE", "prompt_hash": prompt_hash(),
                            "model_id": "m", "model_pinned": True, "status": "LANDED",
                            "predicted_classes": [] if index == 0 else ["PHONE"],
                            "n_findings": 0 if index == 0 else 1,
                            "all_values_matched": True,
                        }) + "\n")
                    # One maths row is a false positive.
                    for index, row in enumerate(maths_rows):
                        handle.write(json.dumps({
                            "id": row["id"], "corpus": row["corpus"],
                            "gold_class": None, "prompt_hash": prompt_hash(),
                            "model_id": "m", "model_pinned": True, "status": "LANDED",
                            "predicted_classes": ["PHONE"] if index == 0 else [],
                            "n_findings": 1 if index == 0 else 0,
                            "all_values_matched": True,
                        }) + "\n")
                results = pde.score()
            finally:
                pde.CACHE_DIR = original

        phone = results["per_class"]["PHONE"]
        self.assertEqual(phone["n"], len(phone_rows))
        self.assertAlmostEqual(
            phone["class_recall"], (len(phone_rows) - 1) / len(phone_rows)
        )
        precision = results["maths_dense_precision"]
        self.assertEqual(precision["false_positives"], 1)
        self.assertAlmostEqual(precision["rate"], 1 / len(maths_rows))
        # A class with no cached rows reports None, not 0.0.
        self.assertIsNone(results["per_class"]["EMAIL"]["class_recall"])


if __name__ == "__main__":
    unittest.main()
