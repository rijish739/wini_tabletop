"""Atomic persistence adapters and the State and Persistence module interface."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from typing import Any, Mapping, Protocol

from learner_state import LearnerState
from runtime.contracts import TurnCommit

from .projection import CapabilityStateAccess, StateChangeRejected, WorkingStateProjection


class StateCommitFailed(RuntimeError):
    """A Turn Commit did not become durable."""


class StaleState(StateCommitFailed):
    """The durable state changed after this working projection began."""


def state_version(state: Mapping[str, Any]) -> str:
    payload = json.dumps(
        state, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PersistenceAdapter(Protocol):
    """Genuine whole-state persistence seam used exactly once per Turn Commit."""

    def load(self) -> dict[str, Any]: ...

    def persist(self, *, expected_version: str, state: Mapping[str, Any]) -> None: ...


class LearnerStatePersistenceAdapter:
    """Production adapter over LearnerState and the configured durable state store.

    When a durable store is supplied it is the single persistence target. Otherwise
    the existing atomic JSON-file save is used. The in-process LearnerState is only
    published after that whole-state write succeeds.
    """

    def __init__(self, learner_state: LearnerState, durable_store: Any | None = None) -> None:
        self._learner_state = learner_state
        self._durable_store = durable_store
        self._lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._learner_state.data)

    def persist(self, *, expected_version: str, state: Mapping[str, Any]) -> None:
        next_state = copy.deepcopy(dict(state))
        with self._lock:
            if state_version(self._learner_state.data) != expected_version:
                raise StaleState("learner state changed before Turn Commit")
            previous = self._learner_state.data
            try:
                if self._durable_store is not None:
                    self._durable_store.save(next_state)
                else:
                    LearnerState(self._learner_state.path, next_state).save()
            except Exception as exc:
                self._learner_state.data = previous
                raise StateCommitFailed(str(exc)) from exc
            self._learner_state.data = next_state


class DeterministicPersistenceAdapter:
    """Offline adapter with atomic success/failure behavior and no external I/O."""

    def __init__(self, state: Mapping[str, Any]) -> None:
        self._state = copy.deepcopy(dict(state))
        self._next_failure: str | None = None
        self.commit_count = 0

    @property
    def committed_state(self) -> dict[str, Any]:
        return copy.deepcopy(self._state)

    def fail_next_commit(self, reason: str = "deterministic commit failure") -> None:
        self._next_failure = reason

    def load(self) -> dict[str, Any]:
        return self.committed_state

    def persist(self, *, expected_version: str, state: Mapping[str, Any]) -> None:
        if state_version(self._state) != expected_version:
            raise StaleState("durable state changed before Turn Commit")
        if self._next_failure is not None:
            reason = self._next_failure
            self._next_failure = None
            raise StateCommitFailed(reason)
        next_state = copy.deepcopy(dict(state))
        self._state = next_state
        self.commit_count += 1


class StateAndPersistence:
    """Small public interface for beginning and atomically committing Turn state."""

    def __init__(
        self,
        *,
        adapter: PersistenceAdapter,
        access: Mapping[str, CapabilityStateAccess],
    ) -> None:
        self._adapter = adapter
        self._access = dict(access)
        self._transaction_token = object()

    def begin(self, *, learner_id: str) -> WorkingStateProjection:
        source = self._adapter.load()
        return WorkingStateProjection(
            learner_id=learner_id,
            state=source,
            access=self._access,
            persistence_version=state_version(source),
            transaction_token=self._transaction_token,
        )

    def commit(self, *, turn_id: str, projection: WorkingStateProjection) -> TurnCommit:
        if not turn_id:
            raise StateCommitFailed("Turn Commit requires a turn identity")
        try:
            prepared = projection.prepare_commit(self._transaction_token)
        except StateChangeRejected as exc:
            raise StateCommitFailed(str(exc)) from exc
        version = state_version(prepared.state)
        material = "\x1f".join((turn_id, prepared.learner_id, version, *prepared.change_ids))
        commit_id = "commit_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
        receipt = TurnCommit(
            commit_id=commit_id,
            turn_id=turn_id,
            learner_id=prepared.learner_id,
            applied_change_ids=prepared.change_ids,
            state_version=version,
        )
        try:
            self._adapter.persist(
                expected_version=prepared.persistence_version,
                state=prepared.state,
            )
        except (StaleState, StateCommitFailed):
            projection.abort_commit(self._transaction_token)
            raise
        except Exception as exc:
            projection.abort_commit(self._transaction_token)
            raise StateCommitFailed(str(exc)) from exc
        projection.complete_commit(self._transaction_token)
        return receipt
