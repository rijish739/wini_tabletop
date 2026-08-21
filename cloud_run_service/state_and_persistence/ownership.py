"""Canonical semantic ownership for durable and session-continuity state.

This is intentionally data, rather than policy hidden in a coordinator or an
adapter.  The projection uses this registry to build the capability grants
used by every Turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .projection import CapabilityStateAccess, StatePath, _overlap


@dataclass(frozen=True)
class OwnedStateField:
    scope: str
    path: StatePath
    owner: str
    readers: tuple[str, ...] = ()


# A root claim is deliberate: nested fields are part of the owning module's
# schema and cannot be silently claimed by another module.
STATE_OWNERSHIP_MATRIX: tuple[OwnedStateField, ...] = (
    OwnedStateField("learner", ("learner_id",), "state_and_persistence"),
    OwnedStateField("learner", ("state_schema_version",), "state_and_persistence"),
    OwnedStateField("learner", ("state_change_index",), "state_and_persistence"),
    OwnedStateField("learner", ("concept_states",), "assessment_evidence", ("pedagogy", "retrieval", "response_planning")),
    OwnedStateField("learner", ("misconception_states",), "assessment_evidence", ("pedagogy", "retrieval", "response_planning")),
    OwnedStateField("learner", ("evidence_ledger",), "assessment_evidence", ("retrieval",)),
    OwnedStateField("learner", ("evidence_index",), "assessment_evidence", ("assessment_evidence",)),
    OwnedStateField("learner", ("evidence_projection_base",), "assessment_evidence"),
    OwnedStateField("learner", ("global",), "perception", ("pedagogy", "response_planning")),
    OwnedStateField("learner", ("global_observations",), "perception"),
    OwnedStateField("learner", ("hope_rolling",), "assessment_evidence", ("retrieval",)),
    OwnedStateField("learner", ("safety_alerts",), "interaction_control"),
    OwnedStateField("session", ("current_concept",), "interaction_control", ("pedagogy", "retrieval", "response_planning")),
    OwnedStateField("session", ("pending_shift",), "interaction_control"),
    OwnedStateField("session", ("context",), "interaction_control", ("response_generation",)),
    OwnedStateField("session", ("status",), "interaction_control"),
    OwnedStateField("session", ("leave_requests",), "interaction_control"),
    OwnedStateField("session", ("break_requested",), "interaction_control"),
    OwnedStateField("session", ("steer_streak",), "interaction_control"),
    OwnedStateField("session", ("safety_alert",), "interaction_control"),
    OwnedStateField("session", ("mode",), "pedagogy", ("assessment_evidence",)),
    OwnedStateField("session", ("test_state",), "pedagogy"),
    OwnedStateField("session", ("practice_plan",), "pedagogy"),
    OwnedStateField("session", ("practice_state",), "pedagogy"),
    OwnedStateField("session", ("pending_mode_offer",), "pedagogy"),
    OwnedStateField("session", ("pending_test_resume",), "pedagogy"),
    OwnedStateField("session", ("pending_check",), "assessment_evidence"),
    OwnedStateField("session", ("pending_hope",), "assessment_evidence"),
    OwnedStateField("session", ("hint_progress",), "assessment_evidence", ("retrieval",)),
    OwnedStateField("session", ("served_items",), "retrieval"),
    OwnedStateField("session", ("bridges_served",), "retrieval"),
    OwnedStateField("session", ("pace",), "interaction_control"),
    OwnedStateField("session", ("last_action",), "interaction_control"),
    OwnedStateField("session", ("last_repr_targets",), "interaction_control"),
    OwnedStateField("session", ("realization_validation",), "interaction_control"),
    OwnedStateField("session", ("voided_check",), "assessment_evidence"),
    OwnedStateField("session", ("response_outcome_keys",), "interaction_control"),
    OwnedStateField("session", ("barrier",), "interaction_control"),
    OwnedStateField("session", ("session_started_at",), "interaction_control"),
)


def validate_ownership_matrix(matrix: tuple[OwnedStateField, ...] = STATE_OWNERSHIP_MATRIX) -> None:
    """Reject duplicate or overlapping semantic writers at import/test time."""
    claims: dict[str, list[tuple[StatePath, str]]] = {"learner": [], "session": []}
    for field in matrix:
        if field.scope not in claims or not field.path or not field.owner:
            raise ValueError(f"invalid ownership entry: {field!r}")
        for path, owner in claims[field.scope]:
            if owner != field.owner and _overlap(path, field.path):
                raise ValueError(f"overlapping ownership: {owner} and {field.owner}")
        claims[field.scope].append((field.path, field.owner))


def canonical_capability_access() -> Mapping[str, CapabilityStateAccess]:
    """Build immutable capability grants from the one ownership matrix."""
    validate_ownership_matrix()
    grants: dict[str, dict[str, list[StatePath]]] = {}
    for field in STATE_OWNERSHIP_MATRIX:
        for capability in (field.owner, *field.readers):
            grant = grants.setdefault(capability, {"learner_read": [], "session_read": [], "learner_write": [], "session_write": []})
            grant[f"{field.scope}_read"].append(field.path)
        grants[field.owner][f"{field.scope}_write"].append(field.path)
    return {name: CapabilityStateAccess(**values) for name, values in grants.items()}


validate_ownership_matrix()
