"""Phase 5 outcome emission and single-writer turn-close application."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Iterable

from .contracts import OutcomeEvent


def _normalise(outcome: str | None) -> str | None:
    value = str(outcome or "").lower()
    return {"incorrect": "wrong", "nonresponse": "not_an_answer",
            "correct": "correct", "partial": "partial", "wrong": "wrong"}.get(value)


@dataclass
class OutcomeEmitter:
    """Collect idempotent delivery/assessment events; never writes LearnerState."""
    _seen: set[str] = field(default_factory=set)
    _pending: list[OutcomeEvent] = field(default_factory=list)

    def record(self, runner_event: dict[str, Any], attempt: int = 1) -> OutcomeEvent | None:
        if runner_event.get("event") != "assessment_scored":
            return None
        interaction = dict(runner_event.get("interaction") or {})
        hook_id = interaction.get("hook_id")
        if not hook_id:
            return None
        event = OutcomeEvent(
            script_id=str(runner_event.get("script_id") or ""),
            beat_id=str(runner_event.get("beat_id") or ""),
            attempt=int(attempt),
            assessment_hook_id=str(hook_id),
            outcome=_normalise(runner_event.get("outcome")),
            concept_id=interaction.get("target_concept"),
            kc_id=interaction.get("target_concept"),
            item_id=interaction.get("item_id") or str(hook_id),
            assessment_purpose=interaction.get("assessment_purpose"),
            grader_path="device_local",
            grader_confidence=1.0,
            stt_confidence=1.0,
            payload={
                "hook_type": interaction.get("hook_type"),
                "target_concept": interaction.get("target_concept"),
                "target_misconception": interaction.get("target_misconception"),
                "state_update_intent": interaction.get("state_update_intent"),
                "mutation_kind": interaction.get("state_update_intent") or "practice",
                "response": runner_event.get("response") or {},
            },
        )
        if not event.script_id or not event.beat_id or event.idempotency_key in self._seen:
            return None
        self._seen.add(event.idempotency_key)
        self._pending.append(event)
        return event

    def drain(self) -> list[OutcomeEvent]:
        pending, self._pending = self._pending, []
        return pending


def apply_at_turn_close(state, events: Iterable[OutcomeEvent],
                        applied_keys: set[str] | None = None) -> tuple[list[dict], set[str]]:
    """The only Phase-5 function permitted to call LearnerState writeback APIs.

    Device telemetry remains observational until the existing learner loop calls this
    at a turn boundary. Duplicate/replayed events are skipped by idempotency key.
    """
    applied = applied_keys if applied_keys is not None else set()
    results: list[dict] = []
    for event in events:
        key = event.idempotency_key
        if key in applied:
            continue
        outcome = _normalise(event.outcome)
        payload = event.payload or {}
        hook_type = payload.get("hook_type")
        concept = payload.get("target_concept")
        misconception = payload.get("target_misconception")
        try:
            from evidence import record_outcome
            result = record_outcome(state, event)
        except Exception as exc:  # bad telemetry must not corrupt learner state
            result = {"status": "rejected", "reason": str(exc)}
        applied.add(key)
        results.append({"idempotency_key": key, "outcome": outcome, "result": result})
    return results, applied
