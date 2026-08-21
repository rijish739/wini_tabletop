"""Validated in-memory working projection for one Turn."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Mapping

from evidence import migrate_state_data, record_outcome
from learner_state import LearnerState
from runtime.contracts import (
    StateChange,
    StateOperation,
    StateScope,
    deep_freeze,
)
from state_backend import bind_state_identity


StatePath = tuple[str, ...]
_EVIDENCE_DERIVED_ROOTS = frozenset({
    "concept_states",
    "misconception_states",
    "evidence_ledger",
    "evidence_index",
    "evidence_projection_base",
})
_INTEGRITY_ROOTS = frozenset({"learner_id", "state_schema_version", "state_change_index"})


class StateChangeRejected(ValueError):
    """A change violates capability ownership or a state invariant."""


class StateChangeConflict(ValueError):
    """Two changes in one Turn target the same state path."""


@dataclass(frozen=True)
class CapabilityStateAccess:
    learner_read: tuple[StatePath, ...] = ()
    session_read: tuple[StatePath, ...] = ()
    learner_write: tuple[StatePath, ...] = ()
    session_write: tuple[StatePath, ...] = ()

    def __post_init__(self) -> None:
        for name in ("learner_read", "session_read", "learner_write", "session_write"):
            normalized = tuple(tuple(str(part) for part in path) for path in getattr(self, name))
            if any(not path or any(not part for part in path) for path in normalized):
                raise ValueError(f"{name} contains an empty state path")
            object.__setattr__(self, name, normalized)


@dataclass(frozen=True)
class LearnerStateView(Mapping[str, Any]):
    """Immutable, capability-selected Learner State fields."""

    data: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", deep_freeze(self.data))

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)


@dataclass(frozen=True)
class SessionStateView(Mapping[str, Any]):
    """Immutable, capability-selected Session State fields."""

    data: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", deep_freeze(self.data))

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)


@dataclass(frozen=True)
class StateView:
    learner: LearnerStateView
    session: SessionStateView


@dataclass(frozen=True)
class PreparedStateCommit:
    learner_id: str
    persistence_version: str
    state: dict[str, Any]
    change_ids: tuple[str, ...]


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return {_thaw(item) for item in value}
    return copy.deepcopy(value)


def _contains(grants: tuple[StatePath, ...], path: StatePath) -> bool:
    return any(path[:len(grant)] == grant for grant in grants)


def _overlap(left: StatePath, right: StatePath) -> bool:
    shortest = min(len(left), len(right))
    return left[:shortest] == right[:shortest]


def _validate_exclusive_writes(access: Mapping[str, CapabilityStateAccess]) -> None:
    for scope_name in ("learner_write", "session_write"):
        claims: list[tuple[str, StatePath]] = []
        for owner, grant in access.items():
            for path in getattr(grant, scope_name):
                for claimed_owner, claimed_path in claims:
                    if owner != claimed_owner and _overlap(path, claimed_path):
                        raise StateChangeRejected(
                            f"overlapping {scope_name} ownership: {claimed_owner} and {owner}"
                        )
                claims.append((owner, path))


def _read_path(root: Mapping[str, Any], path: StatePath) -> tuple[bool, Any]:
    current: Any = root
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _write_path(root: dict[str, Any], path: StatePath, value: Any) -> None:
    current = root
    for part in path[:-1]:
        child = current.setdefault(part, {})
        if not isinstance(child, dict):
            raise StateChangeRejected(f"state path is not a mapping: {'.'.join(path)}")
        current = child
    current[path[-1]] = _thaw(value)


def _select(root: Mapping[str, Any], paths: tuple[StatePath, ...]) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for path in paths:
        exists, value = _read_path(root, path)
        if exists:
            _write_path(selected, path, value)
    return selected


class WorkingStateProjection:
    """One-Turn state transaction before durability is attempted."""

    def __init__(
        self,
        *,
        learner_id: str,
        state: Mapping[str, Any],
        access: Mapping[str, CapabilityStateAccess],
        persistence_version: str | None = None,
        transaction_token: object | None = None,
    ) -> None:
        working = migrate_state_data(copy.deepcopy(dict(state)))
        bind_state_identity(working, learner_id)
        self.learner_id = learner_id
        self._starting = copy.deepcopy(working)
        self._working = working
        self._access = dict(access)
        _validate_exclusive_writes(self._access)
        self._changes: list[StateChange] = []
        self._changed_paths: dict[
            tuple[StateScope, StatePath], tuple[str, StateOperation]
        ] = {}
        self._change_ids: dict[str, StateChange] = {}
        self._idempotency_keys = set(working.get("evidence_index") or {}) | set(
            working.get("state_change_index") or {}
        )
        self._persistence_version = persistence_version
        self._transaction_token = transaction_token
        self._finalized = False
        self._committing = False

    @property
    def changes(self) -> tuple[StateChange, ...]:
        return tuple(self._changes)

    def view(self, capability: str) -> StateView:
        try:
            grant = self._access[capability]
        except KeyError as exc:
            raise StateChangeRejected(f"unknown state capability: {capability}") from exc
        learner = {key: value for key, value in self._working.items() if key != "session"}
        session = self._working.get("session") or {}
        return StateView(
            learner=LearnerStateView(_select(learner, grant.learner_read)),
            session=SessionStateView(_select(session, grant.session_read)),
        )

    def apply(self, change: StateChange) -> bool:
        """Validate and apply one change; return False for an idempotent duplicate."""
        if self._finalized or self._committing:
            raise StateChangeRejected("a committing or committed working projection is closed")
        grant = self._access.get(change.owner)
        if grant is None:
            raise StateChangeRejected(f"unknown State Change owner: {change.owner}")
        writable = (
            grant.learner_write if change.scope is StateScope.LEARNER else grant.session_write
        )
        if not _contains(writable, change.path):
            raise StateChangeRejected(
                f"{change.owner} does not own {change.scope.value}:{'.'.join(change.path)}"
            )

        previous_change = self._change_ids.get(change.change_id)
        if previous_change is not None:
            if previous_change == change:
                return False
            raise StateChangeConflict(
                f"change id already used by {previous_change.owner}"
            )

        if change.idempotency_key and change.idempotency_key in self._idempotency_keys:
            return False

        if change.operation is StateOperation.APPEND and not change.idempotency_key:
            raise StateChangeRejected("append State Changes require an idempotency key")

        is_evidence = (
            change.scope is StateScope.LEARNER and change.path[0] in _EVIDENCE_DERIVED_ROOTS
        )
        if is_evidence and not (
            change.owner == "assessment_evidence"
            and change.path == ("evidence_ledger",)
            and change.operation is StateOperation.APPEND
            and change.idempotency_key
        ):
            raise StateChangeRejected(
                "evidence is single-writer, append-only, and requires an idempotency key"
            )
        if is_evidence:
            event_key = str((_thaw(change.value) or {}).get("idempotency_key") or "")
            if event_key != change.idempotency_key:
                raise StateChangeRejected(
                "State Change and evidence event idempotency keys must match"
                )
        if (
            change.scope is StateScope.LEARNER
            and change.path[0] in (_EVIDENCE_DERIVED_ROOTS | _INTEGRITY_ROOTS)
            and not is_evidence
        ):
            raise StateChangeRejected(
                f"direct changes to integrity-controlled state are forbidden: {change.path[0]}"
            )

        target_key = (change.scope, change.path)
        for (changed_scope, changed_path), (changed_id, changed_operation) in (
            self._changed_paths.items()
        ):
            repeated_append = (
                changed_scope is change.scope
                and changed_path == change.path
                and changed_operation is StateOperation.APPEND
                and change.operation is StateOperation.APPEND
            )
            if changed_scope is change.scope and _overlap(changed_path, change.path) and not repeated_append:
                raise StateChangeConflict(f"state path already changed by {changed_id}")
        root = self._working if change.scope is StateScope.LEARNER else self._working.setdefault(
            "session", {}
        )
        if is_evidence:
            result = record_outcome(LearnerState(None, self._working), _thaw(change.value))
            if result.get("status") not in {"applied", "duplicate"}:
                raise StateChangeRejected(
                    f"evidence change was not applicable: {result.get('reason', result.get('status'))}"
                )
        else:
            self._apply_operation(root, change)
        self._validate_invariants()
        self._changed_paths[target_key] = (change.change_id, change.operation)
        self._change_ids[change.change_id] = change
        self._changes.append(change)
        if change.idempotency_key:
            self._idempotency_keys.add(change.idempotency_key)
        if change.idempotency_key and not is_evidence:
            self._working.setdefault("state_change_index", {})[
                change.idempotency_key
            ] = change.change_id
        return True

    def _validate_invariants(self) -> None:
        """Validate cross-state structure after every accepted change."""
        if self._working.get("learner_id") != self.learner_id:
            raise StateChangeRejected("state identity changed inside a Turn")
        session = self._working.get("session")
        if session is not None and not isinstance(session, dict):
            raise StateChangeRejected("session state must remain a mapping")
        pending = (session or {}).get("pending_check")
        if pending is not None and not isinstance(pending, dict):
            raise StateChangeRejected("pending_check must be a mapping or null")

    def _apply_operation(self, root: dict[str, Any], change: StateChange) -> None:
        if change.operation is StateOperation.SET:
            _write_path(root, change.path, change.value)
            return
        parent = root
        for part in change.path[:-1]:
            child = parent.get(part)
            if not isinstance(child, dict):
                raise StateChangeRejected(f"state path does not exist: {'.'.join(change.path)}")
            parent = child
        key = change.path[-1]
        if change.operation is StateOperation.DELETE:
            parent.pop(key, None)
            return
        target = parent.setdefault(key, [])
        if not isinstance(target, list):
            raise StateChangeRejected(f"append target is not a list: {'.'.join(change.path)}")
        target.append(_thaw(change.value))

    def projected_state(self) -> dict[str, Any]:
        return copy.deepcopy(self._working)

    def starting_state(self) -> dict[str, Any]:
        return copy.deepcopy(self._starting)

    def prepare_commit(self, transaction_token: object) -> PreparedStateCommit:
        if transaction_token is not self._transaction_token or transaction_token is None:
            raise StateChangeRejected("working projection belongs to another transaction")
        if self._persistence_version is None:
            raise StateChangeRejected("working projection has no persistence version")
        if self._finalized or self._committing:
            raise StateChangeRejected("working projection is already committing or committed")
        self._committing = True
        return PreparedStateCommit(
            learner_id=self.learner_id,
            persistence_version=self._persistence_version,
            state=self.projected_state(),
            change_ids=tuple(change.change_id for change in self._changes),
        )

    def abort_commit(self, transaction_token: object) -> None:
        if transaction_token is self._transaction_token and not self._finalized:
            self._committing = False

    def complete_commit(self, transaction_token: object) -> None:
        if transaction_token is not self._transaction_token or not self._committing:
            raise StateChangeRejected("working projection has no matching prepared commit")
        self._committing = False
        self._finalized = True
