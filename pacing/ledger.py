"""Small persisted pace ledger.

The ledger lives inside learner_state.json under session.pace. It is deliberately
separate from tutor_loop's session.pending_check: pending_check is a graded
diagnostic/bridge closure, while pending_micro_check is only conversational pacing.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


DEFAULT_PACE: dict[str, Any] = {
    "mode": "idle",
    "current_micro_goal": "",
    "expected_response_type": "free",
    "pending_micro_check": None,
    "explanation_step": 0,
    "max_words": 60,
    "last_explanation_summary": "",
    "last_spoken_answer": "",
    "last_voice_latency_ms": {},
}


@dataclass
class PaceLedger:
    data: dict[str, Any] = field(default_factory=lambda: deepcopy(DEFAULT_PACE))

    @classmethod
    def from_state(cls, state) -> "PaceLedger":
        session = state.data.setdefault("session", {})
        pace = session.setdefault("pace", deepcopy(DEFAULT_PACE))
        merged = deepcopy(DEFAULT_PACE)
        merged.update(pace if isinstance(pace, dict) else {})
        session["pace"] = merged
        return cls(merged)

    def save_to_state(self, state) -> None:
        state.data.setdefault("session", {})["pace"] = self.data

    def set_micro_check(self, question: str, kind: str = "pace_check") -> None:
        self.data["pending_micro_check"] = {
            "question": question[:220],
            "kind": kind,
        }

    def clear_micro_check(self) -> None:
        self.data["pending_micro_check"] = None

    @property
    def pending_micro_check(self) -> dict[str, Any] | None:
        pending = self.data.get("pending_micro_check")
        return pending if isinstance(pending, dict) else None


def get_session(state) -> dict[str, Any]:
    return state.data.setdefault("session", {})
