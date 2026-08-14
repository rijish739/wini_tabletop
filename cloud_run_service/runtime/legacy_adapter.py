"""Temporary bridge around the unextracted TutorLoop Turn implementation."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Callable, Mapping

from .contracts import (
    FailureSeverity,
    FailureSignal,
    RealizationReceipt,
    RealizationStatus,
    TurnCommit,
    TurnInput,
    TurnResult,
    deep_thaw,
)


class LegacyAdapterFailure(RuntimeError):
    def __init__(self, *, original: Exception, signal: FailureSignal) -> None:
        super().__init__(signal.cause)
        self.original = original
        self.signal = signal


def _state_version(state: Mapping[str, Any]) -> str:
    payload = json.dumps(
        state, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LegacyTurnAdapter:
    """Explicit, measurable compatibility bridge; this is not a Feature Module."""

    name = "temporary_legacy_turn_adapter"

    def __init__(
        self,
        *,
        legacy_turn: Callable[..., Mapping[str, Any]],
        commit_state: Callable[[], None],
        state: Any,
    ) -> None:
        self._legacy_turn = legacy_turn
        self._commit_state = commit_state
        self._state = state

    def execute(self, turn_input: TurnInput):
        # Imported lazily to keep the adapter/coordinator modules acyclic.
        from .coordinator import LOGICAL_TURN_PHASES, LegacyExecution

        interaction = deep_thaw(turn_input.interaction)
        trusted = deep_thaw(turn_input.trusted_observations)
        starting_state = copy.deepcopy(self._state.data)
        try:
            compatibility = dict(self._legacy_turn(
                str(interaction["text"]),
                answer_budget=interaction.get("answer_budget"),
                precomputed_analysis=trusted.get("precomputed_analysis"),
                precomputed_grade=trusted.get("precomputed_grade"),
                stt_confidence=trusted.get("stt_confidence"),
                turn_id=turn_input.turn_id,
                learner_id=turn_input.learner_id,
                _allow_shift=bool(interaction.get("allow_topic_shift", True)),
            ))
        except Exception as exc:
            self._restore(starting_state)
            signal = FailureSignal(
                capability="legacy_runtime",
                phase="legacy_execution",
                severity=FailureSeverity.FATAL,
                recoverable=False,
                cause=f"{type(exc).__name__}: {exc}",
                valid_outcome=False,
                context={"adapter": self.name},
            )
            raise LegacyAdapterFailure(original=exc, signal=signal) from exc

        try:
            self._commit_state()
        except Exception as exc:
            rollback_persisted = self._restore(starting_state)
            signal = FailureSignal(
                capability="state_and_persistence",
                phase="commit",
                severity=FailureSeverity.FATAL,
                recoverable=False,
                cause=f"{type(exc).__name__}: {exc}",
                valid_outcome=False,
                context={
                    "adapter": self.name,
                    "rollback_persisted": rollback_persisted,
                },
            )
            raise LegacyAdapterFailure(original=exc, signal=signal) from exc

        state_version = _state_version(self._state.data)
        material = f"{turn_input.turn_id}\x1f{turn_input.learner_id}\x1f{state_version}"
        commit = TurnCommit(
            commit_id="legacy_commit_" + hashlib.sha256(
                material.encode("utf-8")
            ).hexdigest()[:24],
            turn_id=turn_input.turn_id,
            learner_id=turn_input.learner_id,
            applied_change_ids=(),
            state_version=state_version,
        )
        delivered = []
        if compatibility.get("answer"):
            delivered.append("speech")
        if compatibility.get("display") or compatibility.get("visual"):
            delivered.append("display")
        result = TurnResult(
            turn_id=turn_input.turn_id,
            learner_id=turn_input.learner_id,
            outcome=compatibility,
            compatibility=compatibility,
            realization=RealizationReceipt(
                turn_id=turn_input.turn_id,
                status=RealizationStatus.PARTIAL,
                intended=tuple(delivered),
                delivered=(),
                details={
                    "source": self.name,
                    "observation": "presentation_occurs_after_tutor_loop_facade",
                },
            ),
            commit=commit,
        )
        return LegacyExecution(
            result=result,
            completed_phases=LOGICAL_TURN_PHASES,
            measurements={
                "legacy_adapter_turns": 1,
                "legacy_adapter_unextracted_phases": len(LOGICAL_TURN_PHASES),
            },
        )

    def _restore(self, starting_state: Mapping[str, Any]) -> bool:
        self._state.data = copy.deepcopy(dict(starting_state))
        save = getattr(self._state, "save", None)
        if not callable(save):
            return False
        try:
            save()
        except Exception:
            return False
        return True
