"""Offline handoff gates.

The command is deliberately conservative: unavailable dependencies, incomplete
oracle captures, and missing live-cloud credentials are reported as blocked rather
than silently treated as passes. It is standard-library-only so it can run in a
clean checkout.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "cloud_run_service"

MODULES = {
    "interaction_control": "interaction_control/tests",
    "perception": "perception/tests",
    "pedagogy": "pedagogy/tests",
    "assessment_evidence": "assessment_evidence/tests",
    "retrieval": "retrieval/tests",
    "response_planning": "response_planning/tests",
    "response_generation": "response_generation/tests",
    "presentation": "presentation/tests",
    "state_and_persistence": "state_and_persistence/tests",
    "runtime": "runtime/tests",
}

FEATURE_PACKAGES = set(MODULES) - {"runtime"}


@dataclass
class Gate:
    name: str
    status: str
    detail: str


def _command(name: str, args: list[str]) -> Gate:
    completed = subprocess.run(
        [sys.executable, *args], cwd=SERVICE, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    output = completed.stdout.strip().splitlines()
    detail = "\n".join(output[-12:])
    status = "pass" if completed.returncode == 0 else "blocked"
    return Gate(name, status, detail or f"exit code {completed.returncode}")


def _architecture_gate() -> Gate:
    violations: list[str] = []
    for package in sorted(FEATURE_PACKAGES):
        package_dir = SERVICE / package
        for path in package_dir.rglob("*.py"):
            # Tests intentionally compose public seams from several Modules. The
            # rule is about production implementation coupling, not test fixtures.
            if "tests" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError) as exc:
                violations.append(f"{path.relative_to(ROOT)}: {exc}")
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports = [(alias.name, alias.name.split(".")[0]) for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imports = ([(node.module, node.module.split(".")[0])]
                               if node.module else [])
                else:
                    continue
                # A package root and its public ``interface`` are the approved
                # cross-Module seam. Private implementation imports are not.
                forbidden = sorted({root for full, root in imports
                                    if root in FEATURE_PACKAGES and root != package
                                    and full != root and ".interface" not in full})
                violations.extend(
                    f"{path.relative_to(ROOT)}:{node.lineno}: imports {name}"
                    for name in forbidden
                )
    if violations:
        return Gate("architecture", "blocked", "\n".join(violations))
    return Gate("architecture", "pass", "No Feature Module imports another Feature Module.")


def _duplicate_gate() -> Gate:
    duplicate = ROOT / "cloud_workspace_v8"
    if duplicate.exists():
        return Gate("duplicate-runtime", "blocked", f"duplicate tree retained: {duplicate}")
    return Gate("duplicate-runtime", "pass", "cloud_workspace_v8 is absent.")


def _compatibility_gate() -> Gate:
    required = [
        ROOT / "tutor_loop.py", ROOT / "wini_server.py",
        SERVICE / "tutor_loop.py", SERVICE / "wini_server.py",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        return Gate("compatibility-entrypoints", "blocked", "missing: " + ", ".join(missing))
    return Gate("compatibility-entrypoints", "pass", "TutorLoop and server entrypoints are retained.")


def run_verification() -> dict:
    gates = [
        _command("oracle-validate", ["-m", "baseline_oracle", "validate"]),
        _command("oracle-equivalence", ["-m", "baseline_oracle", "verify"]),
        _architecture_gate(),
        _duplicate_gate(),
        _compatibility_gate(),
    ]
    for name, suite in MODULES.items():
        gates.append(_command(f"module:{name}", ["-m", "unittest", "discover", "-s", suite, "-q"]))
    return {
        "status": "pass" if all(g.status == "pass" for g in gates) else "blocked",
        "gates": [asdict(g) for g in gates],
        "limitations": [
            "Live-cloud smoke is an explicitly separate, credentialed operation and was not run by this offline command.",
            "Performance comparison is blocked until artifact-complete baseline and candidate captures exist.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="write the machine-readable report")
    args = parser.parse_args(argv)
    report = run_verification()
    rendered = json.dumps(report, indent=2) + "\n"
    print(rendered, end="")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(rendered, encoding="utf-8")
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
