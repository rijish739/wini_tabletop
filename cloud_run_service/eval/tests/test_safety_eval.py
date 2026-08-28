"""The safety eval harness, and the frozen outage net's CI guard.

Everything here is **offline and free**. The harness's billed half (`--collect`)
is exercised only through a stubbed cache; the money is in the `billed-safety` CI
job, behind the `billed-eval` approval environment.

Two jobs:

* keep the **degraded net frozen** — `degraded_net.jsonl` records what the lexicon
  does today, and any drift in either direction is a failure here rather than a
  surprise in production;
* keep the harness honest — no aggregate number, no cache mixed across prompt
  hashes, and a failed call never cached as a negative verdict.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from eval import safety_eval
from child_safety.prompt import prompt_hash


class DegradedNetFreezeTests(unittest.TestCase):
    """§8: the net is FROZEN — never edited toward the model, never edited by
    reading a missed-corpus row. This test is what makes "frozen" enforceable
    rather than merely asserted in a docstring."""

    def test_the_outage_net_has_not_drifted(self) -> None:
        result = safety_eval.net_floor()
        self.assertTrue(
            result["frozen"],
            "the frozen outage lexicon changed behaviour on: "
            f"{result['freeze_drift']}. The net is frozen; if this is deliberate, "
            "the corpus row records what the net DOES and must be re-observed, not "
            "argued with.",
        )

    def test_the_net_meets_its_own_axis_floor(self) -> None:
        """Published under its own label (§10.2) and never a gate on the model."""
        result = safety_eval.net_floor()
        self.assertIsNotNone(result["axis_recall"])
        self.assertGreaterEqual(result["axis_recall"], safety_eval.NET_AXIS_FLOOR)

    def test_the_freeze_corpus_records_known_false_positives_rather_than_hiding_them(
        self,
    ) -> None:
        """A net FP is a recorded fact, not a defect report. §10.2 places no
        precision gate on the axis, ever — a future recall broadening must never be
        blockable by precision. But it must stay VISIBLE as a false positive."""
        result = safety_eval.net_floor()
        self.assertTrue(
            result["false_positives"],
            "the frozen net is known to over-trigger; a run reporting zero FPs "
            "means gold was edited toward the regex",
        )
        rows = {row["id"]: row for row in safety_eval._read(safety_eval.NET_CORPUS)}
        for row_id in result["false_positives"]:
            self.assertTrue(
                rows[row_id].get("note"),
                f"{row_id} is a net FP and must carry a note saying so",
            )

    def test_blind_gold_and_observed_net_behaviour_are_kept_apart(self) -> None:
        """§10.1: a corpus written by reading the patterns measures the patterns.
        `label` is authored blind; `net_observed` is what the regex does. They
        disagree on at least one row, and that disagreement is the FP above — if
        they can never disagree, gold has been collapsed into the regex."""
        rows = safety_eval._read(safety_eval.NET_CORPUS)
        for row in rows:
            self.assertIn("net_observed", row, row["id"])
        disagreements = [
            row["id"] for row in rows
            if row["net_observed"]["tripped"] != row["label"]["tripped"]
        ]
        self.assertTrue(disagreements)


class CorpusWiringTests(unittest.TestCase):
    def test_every_enum_class_has_a_blind_corpus(self) -> None:
        from child_safety.prompt import SAFETY_CLASS_NAMES

        self.assertEqual(
            set(SAFETY_CLASS_NAMES), set(safety_eval.POSITIVE_CORPORA),
            "a class in the response enum with no corpus is a class measured by "
            "nothing",
        )

    def test_every_corpus_file_exists_and_is_non_trivial(self) -> None:
        for label, filename in safety_eval.POSITIVE_CORPORA.items():
            with self.subTest(label=label):
                self.assertGreaterEqual(len(safety_eval._read(filename)), 50)

    def test_the_positive_corpora_carry_their_own_gold_class(self) -> None:
        for label, filename in safety_eval.POSITIVE_CORPORA.items():
            for row in safety_eval._read(filename):
                self.assertEqual(row["label"], label, row["id"])

    def test_row_ids_are_unique_across_every_corpus(self) -> None:
        """The cache is keyed by row id; a collision would silently reuse one
        row's verdict for another."""
        ids = [row["id"] for row in safety_eval._all_rows()]
        self.assertEqual(len(ids), len(set(ids)))


class CacheDisciplineTests(unittest.TestCase):
    def test_the_cache_filename_carries_the_prompt_hash(self) -> None:
        self.assertIn(prompt_hash(), safety_eval.cache_path().name)

    def test_mixing_caches_across_prompt_hashes_is_a_hard_failure(self) -> None:
        """Not a warning. A row cached under a different prompt hash was produced
        by a different detector, and scoring it would publish a number for a system
        that does not exist."""
        path = safety_eval.cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        original = path.read_text(encoding="utf-8") if existed else None
        try:
            path.write_text(
                json.dumps({"id": "x", "prompt_hash": "deadbeefdeadbeef"}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as caught:
                safety_eval.load_cache()
            self.assertIn("never mixed", str(caught.exception))
        finally:
            if original is not None:
                path.write_text(original, encoding="utf-8")
            elif path.exists():
                path.unlink()


class ReportingDisciplineTests(unittest.TestCase):
    """§10.2: no aggregate safety number is permitted anywhere."""

    def _results(self, per_class_recall: float) -> dict:
        return {
            "measured_at": "2026-08-28", "prompt_hash": "h", "prompt_version": "p",
            "schema_version": "s", "model_ids": ["gemini-2.5-flash"],
            "model_pinned": False, "n_scored": 10,
            "per_class": {
                label: {
                    "n": 10, "model_axis_recall": 1.0,
                    "model_class_recall": per_class_recall,
                    "incremental_recall": 1.0, "incremental_n": 5,
                    "union_recall": 1.0, "review_scope": "unreviewed",
                }
                for label in safety_eval.POSITIVE_CORPORA
            },
            "false_positive_observation": {"n": 10, "tripped": 1, "rate": 0.1},
            "legacy_20_union": {"n": 20, "tripped": 20},
        }

    def test_the_report_publishes_three_separate_numbers_per_class(self) -> None:
        report = safety_eval.render(self._results(0.9))
        self.assertIn("model class", report)
        self.assertIn("incremental", report)
        self.assertIn("union", report)

    def test_the_report_contains_no_mean_or_total(self) -> None:
        report = safety_eval.render(self._results(0.9)).lower()
        for banned in ("macro", "average", "overall recall", "aggregate recall"):
            self.assertNotIn(banned, report)

    def test_a_class_below_floor_is_named_in_the_not_covered_statement(self) -> None:
        """Naming it is the deliverable. A class silently below floor is exactly
        what a single aggregate number hid."""
        report = safety_eval.render(self._results(0.5))
        self.assertIn("## Not covered", report)
        self.assertIn("do not enter the enum", report)
        for label in safety_eval.POSITIVE_CORPORA:
            self.assertIn(f"- `{label}`", report)

    def test_an_unmeasured_number_prints_as_unmeasured_not_as_zero(self) -> None:
        self.assertIsNone(safety_eval._fraction(0, 0))
        self.assertEqual(safety_eval._fraction(0, 4), 0.0)


class ScoringRoundTripTests(unittest.TestCase):
    """Score a stubbed cache end to end — offline, no call, no credential."""

    def setUp(self) -> None:
        self.path = safety_eval.cache_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.existed = self.path.exists()
        self.original = (
            self.path.read_text(encoding="utf-8") if self.existed else None
        )
        self.pointer_original = (
            safety_eval.POINTER.read_text(encoding="utf-8")
            if safety_eval.POINTER.exists() else None
        )

    def tearDown(self) -> None:
        if self.original is not None:
            self.path.write_text(self.original, encoding="utf-8")
        elif self.path.exists():
            self.path.unlink()
        if self.pointer_original is not None:
            safety_eval.POINTER.write_text(self.pointer_original, encoding="utf-8")
        elif safety_eval.POINTER.exists():
            safety_eval.POINTER.unlink()

    def _write_cache(self, *, perfect: bool) -> None:
        lines = []
        for row in safety_eval._all_rows():
            classes = (
                [row["gold_class"]] if perfect and row["gold_class"] else []
            )
            lines.append(json.dumps({
                "id": row["id"], "corpus": row["corpus"],
                "gold_class": row["gold_class"],
                "gold_tripped": row["gold_tripped"],
                "prompt_hash": prompt_hash(),
                "prompt_version": "p", "schema_version": "s",
                "model_id": "gemini-2.5-flash@stub", "model_pinned": True,
                "verdict": {
                    "tripped": bool(classes), "classes": classes,
                    "imminence_cue": False, "named_means": False,
                    "weapon": False, "arranged_meeting": False,
                    "status": "ok", "model_id": "gemini-2.5-flash@stub",
                    "model_pinned": True, "prompt_version": "p",
                    "schema_version": "s", "latency_ms": 10, "attempts": 1,
                    "failure_reason": "",
                },
            }))
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_a_perfect_cache_scores_every_class_at_full_recall(self) -> None:
        self._write_cache(perfect=True)
        results = safety_eval.score()
        for label, row in results["per_class"].items():
            with self.subTest(label=label):
                self.assertEqual(row["model_class_recall"], 1.0)
                self.assertEqual(row["model_axis_recall"], 1.0)

    def test_incremental_recall_is_measured_only_where_the_net_misses(self) -> None:
        """The entire justification for paying for the call, so it is measured
        rather than assumed."""
        self._write_cache(perfect=True)
        results = safety_eval.score()
        for label, row in results["per_class"].items():
            with self.subTest(label=label):
                self.assertLessEqual(row["incremental_n"], row["n"])
                self.assertEqual(row["incremental_recall"], 1.0)

    def test_a_silent_model_regresses_the_union_and_the_gate_catches_it(self) -> None:
        """The real risk of the inversion: on a healthy turn the degraded net does
        not contribute, so a row the lexicon caught and the model misses trips
        nothing at all."""
        self._write_cache(perfect=False)
        regressions = safety_eval.union_regressions()
        self.assertTrue(
            regressions,
            "a model that names nothing must fail the union gate on every row "
            "today's lexicon trips on",
        )

    def test_scoring_writes_the_pointer_every_case_record_embeds(self) -> None:
        self._write_cache(perfect=True)
        payload = safety_eval.write_pointer(safety_eval.score())
        self.assertEqual(payload["status"], "measured")
        self.assertTrue(safety_eval.POINTER.exists())
        # Per-class only — a fused number in the permanent audit trail would
        # reintroduce exactly what §10.2 forbids in the report.
        self.assertEqual(
            set(payload["per_class_model_recall"]), set(safety_eval.POSITIVE_CORPORA)
        )

    def test_the_case_record_reads_the_pointer_the_eval_wrote(self) -> None:
        from interaction_control.control import _eval_numbers_in_force

        self._write_cache(perfect=True)
        safety_eval.write_pointer(safety_eval.score())
        self.assertEqual(_eval_numbers_in_force()["status"], "measured")

    def test_an_absent_pointer_reads_as_unmeasured_never_as_a_number(self) -> None:
        """A fabricated number here would be worse than none (§12)."""
        from interaction_control.control import _eval_numbers_in_force

        if safety_eval.POINTER.exists():
            safety_eval.POINTER.unlink()
        self.assertEqual(_eval_numbers_in_force()["status"], "unmeasured")


class CutoverGateTests(unittest.TestCase):
    def test_an_unpinned_model_is_a_hard_block(self) -> None:
        """A floating alias means a Google-side rollout can change child-safety
        behaviour between two deploys of identical code."""
        results = ReportingDisciplineTests()._results(1.0)
        results["model_pinned"] = False
        passed, blockers = safety_eval.cutover(results)
        self.assertFalse(passed)
        self.assertTrue(any("pin" in b.lower() for b in blockers))

    def test_unreviewed_corpora_block_the_cutover(self) -> None:
        results = ReportingDisciplineTests()._results(1.0)
        results["model_pinned"] = True
        passed, blockers = safety_eval.cutover(results)
        self.assertFalse(passed)
        self.assertTrue(any("unreviewed" in b for b in blockers))

    def test_a_class_below_its_own_floor_blocks_while_it_is_still_in_the_enum(
        self,
    ) -> None:
        """§10.2: stop-ship *for that class*. The gate cannot edit the enum itself,
        so it blocks and names the class."""
        results = ReportingDisciplineTests()._results(0.5)
        results["model_pinned"] = True
        for row in results["per_class"].values():
            row["review_scope"] = "reviewed"
        passed, blockers = safety_eval.cutover(results)
        self.assertFalse(passed)
        self.assertTrue(any("per-class floor" in b for b in blockers))

    def test_axis_recall_below_floor_blocks(self) -> None:
        results = ReportingDisciplineTests()._results(1.0)
        results["model_pinned"] = True
        for row in results["per_class"].values():
            row["review_scope"] = "reviewed"
            row["model_axis_recall"] = 0.5
        passed, blockers = safety_eval.cutover(results)
        self.assertFalse(passed)
        self.assertTrue(any("axis recall" in b for b in blockers))


if __name__ == "__main__":
    unittest.main()
