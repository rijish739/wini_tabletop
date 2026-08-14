from __future__ import annotations

import contextlib
import io
import json
import unittest

from baseline_oracle.cli import main


class OracleCliTests(unittest.TestCase):
    def test_verify_command_passes_the_frozen_reference(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["verify"])

        report = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["cases"], 27)


if __name__ == "__main__":
    unittest.main()
