"""Structural comparison across every recorded Turn observation surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .normalization import normalize_at_path


@dataclass(frozen=True)
class Difference:
    path: str
    reference: Any
    candidate: Any
    reason: str = "value_mismatch"


@dataclass(frozen=True)
class ComparisonReport:
    differences: tuple[Difference, ...]

    @property
    def equivalent(self) -> bool:
        return not self.differences


def compare_observations(
    reference: Mapping[str, Any], candidate: Mapping[str, Any]
) -> ComparisonReport:
    differences: list[Difference] = []
    _compare("", reference, candidate, differences)
    return ComparisonReport(tuple(differences))


def _compare(path: str, reference: Any, candidate: Any, out: list[Difference]) -> None:
    if isinstance(reference, Mapping) and isinstance(candidate, Mapping):
        keys = sorted(set(reference) | set(candidate))
        for key in keys:
            child = f"{path}.{key}" if path else str(key)
            if key not in reference:
                out.append(Difference(child, None, candidate[key], "unexpected_field"))
            elif key not in candidate:
                out.append(Difference(child, reference[key], None, "missing_field"))
            else:
                _compare(child, reference[key], candidate[key], out)
        return

    if _is_sequence(reference) and _is_sequence(candidate):
        if len(reference) != len(candidate):
            out.append(Difference(path, len(reference), len(candidate), "length_mismatch"))
        for index, (left, right) in enumerate(zip(reference, candidate)):
            _compare(f"{path}[{index}]", left, right, out)
        return

    left = normalize_at_path(path, reference)
    right = normalize_at_path(path, candidate)
    if type(left) is not type(right) or left != right:
        out.append(Difference(path, reference, candidate))


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
