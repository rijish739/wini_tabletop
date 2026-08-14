"""Command-line entry point for capture, validation, and comparison."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from typing import Any, Sequence

from .corpus import load_default_corpus
from .reference import verify_frozen_reference
from .runner import OracleRunner
from .verify import verify_candidate


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Frozen Baseline Split equivalence oracle")
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="compare a candidate capture to the reference")
    verify.add_argument("--candidate", type=Path)
    commands.add_parser("validate", help="validate frozen states, corpus, and recordings")
    report = commands.add_parser("report", help="write the preserved baseline report")
    report.add_argument("--json", type=Path, required=True)
    report.add_argument("--markdown", type=Path, required=True)
    capture = commands.add_parser("capture", help="capture a runtime adapter with offline replay")
    capture.add_argument("--adapter", required=True, help="module:zero_argument_factory")
    capture.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "validate":
        corpus = load_default_corpus()
        corpus.validate()
        result = {"status": "pass", "cases": len(corpus.cases),
                  "states": len(corpus.states), "recordings": len(corpus.recordings)}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "verify":
        if args.candidate is None:
            result = verify_frozen_reference()
        else:
            capture = _load_capture(args.candidate)
            result = verify_candidate(
                capture["observations"], candidate_startup=capture["startup"]
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return (0 if result["status"] == "pass"
                else (2 if result["status"] in {"incomplete", "blocked"} else 1))

    if args.command == "report":
        result = verify_frozen_reference()
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.markdown.write_text(_markdown_report(result), encoding="utf-8")
        print(json.dumps({"status": result["status"], "json": str(args.json),
                          "markdown": str(args.markdown)}, indent=2))
        return 0 if result["status"] == "pass" else (2 if result["status"] == "incomplete" else 1)

    adapter = _load_adapter(args.adapter)
    run = OracleRunner(load_default_corpus()).run(adapter)
    payload = {"adapter": run.adapter, "startup": run.startup,
               "observations": list(run.observations)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "captured", "adapter": run.adapter,
                      "cases": len(run.observations), "output": str(args.output)}, indent=2))
    return 0


def _load_capture(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, dict):
        return {"observations": value["observations"], "startup": value.get("startup", {})}
    return {"observations": value, "startup": {}}


def _load_adapter(spec: str):
    module_name, separator, object_name = spec.partition(":")
    if not separator:
        raise ValueError("adapter must use module:zero_argument_factory")
    factory = getattr(importlib.import_module(module_name), object_name)
    return factory()


def _markdown_report(report: dict[str, Any]) -> str:
    performance = report["performance"]
    replay = report["model_replay_coverage"]
    limitations = "\n".join(f"- `{item}`" for item in report["capture_limitations"])
    return f"""# Baseline Split equivalence reference

- Status: **{report['status'].upper()}**
- Fixture self-check: **{report['self_check_status'].upper()}**
- Reference: `{report['reference_name']}`
- Canonical commit: `{report['canonical_commit']}`
- Frozen cases: {report['cases']}
- Behavioral differences in self-check: {report['differences']}
- Performance measurement: `{performance['measurement_status']}`
- Model replay recordings: {replay['recorded_calls']} of {replay['expected_calls']} expected calls

The offline corpus, state fixtures, model-boundary recordings, observation projections,
and normalization rules are internally valid and self-equivalent. The repository copy
cannot execute an unchanged canonical Turn because required runtime artifacts are absent;
model replay is incomplete for {len(replay['incomplete_cases'])} cases; no latency value
has been guessed or copied from unrelated measurements.

## Capture limitations

{limitations}

## Observable surfaces

{', '.join(f'`{field}`' for field in report['observation_fields'])}
"""


if __name__ == "__main__":
    raise SystemExit(main())
