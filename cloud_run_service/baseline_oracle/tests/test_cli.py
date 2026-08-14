from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from baseline_oracle.cli import main
from baseline_oracle.reference import load_frozen_reference


class OracleCliTests(unittest.TestCase):
    def test_verify_command_passes_the_frozen_reference(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["verify"])

        report = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["self_check_status"], "pass")
        self.assertEqual(report["cases"], 27)

    def test_candidate_capture_is_blocked_while_reference_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "candidate.json"
            capture.write_text(json.dumps({
                "startup": {"startup_ms": 123.0, "model_client_constructions": 2},
                "observations": list(load_frozen_reference()),
            }), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["verify", "--candidate", str(capture)])

        report = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["candidate_startup"]["startup_ms"], 123.0)


if __name__ == "__main__":
    unittest.main()
