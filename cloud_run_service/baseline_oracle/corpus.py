"""Frozen input corpus and its coverage/sanitization invariants."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


REQUIRED_BEHAVIOR_TAGS = frozenset({
    "learning",
    "non_learning",
    "safety",
    "topic_control",
    "clarification",
    "hint",
    "practice",
    "test",
    "assessment_attempt",
    "assessment_non_attempt",
    "retrieval",
    "visual",
    "failure",
})
REQUIRED_STATE_KINDS = frozenset({
    "cold_start",
    "active_session",
    "mode",
    "pending_assessment",
    "misconception",
    "mastery",
    "migration",
    "termination",
})


class CorpusValidationError(ValueError):
    pass


@dataclass(frozen=True)
class FrozenCorpus:
    states: Mapping[str, Mapping[str, Any]]
    cases: tuple[Mapping[str, Any], ...]
    recordings: tuple[Mapping[str, Any], ...]
    state_kinds: frozenset[str] = frozenset()

    @classmethod
    def from_data(
        cls,
        *,
        states: Mapping[str, Mapping[str, Any]],
        cases: Sequence[Mapping[str, Any]],
        recordings: Sequence[Mapping[str, Any]],
        state_kinds: Sequence[str] = (),
    ) -> "FrozenCorpus":
        return cls(
            states=dict(states),
            cases=tuple(cases),
            recordings=tuple(recordings),
            state_kinds=frozenset(state_kinds),
        )

    def validate(self) -> None:
        covered = {str(tag) for case in self.cases for tag in case.get("tags", [])}
        missing = sorted(REQUIRED_BEHAVIOR_TAGS - covered)
        if missing:
            raise CorpusValidationError(
                "missing behavior coverage: " + ", ".join(missing)
            )

        if self.state_kinds:
            missing_states = sorted(REQUIRED_STATE_KINDS - self.state_kinds)
            if missing_states:
                raise CorpusValidationError(
                    "missing starting-state coverage: " + ", ".join(missing_states)
                )

        seen: set[str] = set()
        for case in self.cases:
            case_id = str(case.get("id") or "")
            if not case_id or case_id in seen:
                raise CorpusValidationError(f"invalid or duplicate case id: {case_id!r}")
            seen.add(case_id)
            state_name = str(case.get("state") or "")
            if state_name not in self.states:
                raise CorpusValidationError(
                    f"case {case_id!r} references unknown state {state_name!r}"
                )

        serialized = json.dumps(self.states, sort_keys=True).lower()
        forbidden = ("@", "api_key", "access_token", "authorization", "private_key")
        leaked = [token for token in forbidden if token in serialized]
        if leaked:
            raise CorpusValidationError(
                "starting-state fixture contains forbidden sensitive marker(s): "
                + ", ".join(leaked)
            )

        recording_keys: set[tuple[str, str, int]] = set()
        required = {
            "case_id", "boundary", "call_index", "request_sha256", "response",
            "finish_state", "schema", "redactions",
        }
        for row in self.recordings:
            missing_fields = sorted(required - set(row))
            raw = json.dumps(row, sort_keys=True).lower()
            if (
                missing_fields
                or "request" in row
                or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("request_sha256") or ""))
                or row.get("finish_state") not in {"STOP", "MAX_TOKENS", "TIMEOUT", "ERROR"}
                or any(token in raw for token in ("authorization", "api_key", "access_token", "private_key"))
            ):
                detail = ", ".join(missing_fields) if missing_fields else "unsafe or invalid fields"
                raise CorpusValidationError(f"invalid model recording: {detail}")
            key = (str(row["case_id"]), str(row["boundary"]), int(row["call_index"]))
            if key in recording_keys or key[0] not in seen:
                raise CorpusValidationError(f"invalid model recording key: {key!r}")
            recording_keys.add(key)


def load_default_corpus() -> FrozenCorpus:
    fixture_root = Path(__file__).with_name("fixtures")
    states: dict[str, Mapping[str, Any]] = {}
    state_kinds: set[str] = set()
    for path in sorted((fixture_root / "states").glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        name, kind = str(row["name"]), str(row["kind"])
        if name in states:
            raise CorpusValidationError(f"duplicate starting-state fixture: {name}")
        states[name] = row["state"]
        state_kinds.add(kind)
    corpus = json.loads((fixture_root / "corpus.json").read_text(encoding="utf-8"))
    recordings = json.loads(
        (fixture_root / "model_replays.json").read_text(encoding="utf-8")
    )
    return FrozenCorpus.from_data(
        states=states,
        cases=corpus,
        recordings=recordings,
        state_kinds=state_kinds,
    )
