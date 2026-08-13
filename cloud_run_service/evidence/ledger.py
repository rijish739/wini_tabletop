"""Authoritative outcome ledger, idempotent projection, migration, and replay."""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Iterable

from response_layer.contracts import OutcomeEvent
from runtime_flags import GRADER_WRITE_CONFIDENCE_MIN, STT_WRITE_CONFIDENCE_MIN

LEDGER_SCHEMA_VERSION = 1
STATE_SCHEMA_VERSION = 2


def make_idempotency_key(learner_id: str, turn_id: str, item_id: str,
                         normalized_reply: str) -> str:
    material = "\x1f".join((learner_id, turn_id, item_id,
                             " ".join(str(normalized_reply or "").casefold().split())))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _ledger(state) -> list:
    return state.data.setdefault("evidence_ledger", [])


def _index(state) -> dict[str, int]:
    index = state.data.setdefault("evidence_index", {})
    ledger = _ledger(state)
    if len(index) < len(ledger):
        for offset, row in enumerate(ledger):
            key = row.get("idempotency_key")
            if key:
                index.setdefault(key, offset)
    return index


def _projection_base(state) -> dict:
    return {
        "learner_id": state.data.get("learner_id"),
        "concept_states": copy.deepcopy(state.data.get("concept_states") or {}),
        "misconception_states": copy.deepcopy(state.data.get("misconception_states") or {}),
        "session": {"bridges_served": copy.deepcopy(
            (state.data.get("session") or {}).get("bridges_served") or [])},
        "global": copy.deepcopy(state.data.get("global") or {}),
    }


def _projection_undo(state, event: OutcomeEvent):
    """Capture only keys one projection may touch; ledger size never affects cost."""
    payload = dict(event.payload or {})
    kind = payload.get("mutation_kind") or payload.get("kind") or "practice"
    concept = event.concept_id or payload.get("target_concept")
    item_id = event.item_id or event.assessment_hook_id or event.beat_id
    concept_targets = {item_id if kind == "bridge" else concept}
    concept_targets.discard(None)
    concept_map = state.data.setdefault("concept_states", {})
    concept_snapshots = {}
    for cid in concept_targets:
        existed = cid in concept_map
        row = concept_map.get(cid) or {}
        history = row.get("item_history")
        history_existed = isinstance(history, dict)
        item_existed = bool(history_existed and item_id in history)
        item_snapshot = copy.deepcopy(history.get(item_id)) if item_existed else None
        concept_snapshots[cid] = (
            existed, {k: copy.deepcopy(v) for k, v in row.items()
                      if k != "item_history"}, history, history_existed,
            item_existed, item_snapshot)

    misconception_map = state.data.setdefault("misconception_states", {})
    misconception_targets = set()
    if kind == "misconception":
        misconception_targets.add(item_id)
    if payload.get("revealed_misconception_id"):
        misconception_targets.add(payload["revealed_misconception_id"])
    misconception_snapshots = {
        mid: (mid in misconception_map, copy.deepcopy(misconception_map.get(mid)))
        for mid in misconception_targets}

    session_existed = "session" in state.data
    session = state.data.setdefault("session", {})
    bridges_existed = "bridges_served" in session
    bridges_snapshot = copy.deepcopy(session.get("bridges_served"))
    hints_existed = "hint_progress" in session
    hints_snapshot = copy.deepcopy(session.get("hint_progress"))

    def undo() -> None:
        for cid, snapshot in concept_snapshots.items():
            existed, base, history, history_existed, item_existed, item_before = snapshot
            if not existed:
                concept_map.pop(cid, None)
                continue
            row = concept_map.setdefault(cid, {})
            row.clear()
            row.update(base)
            if history_existed:
                if item_existed:
                    history[item_id] = item_before
                else:
                    history.pop(item_id, None)
                row["item_history"] = history
        for mid, (existed, before) in misconception_snapshots.items():
            if existed:
                misconception_map[mid] = before
            else:
                misconception_map.pop(mid, None)
        if bridges_existed:
            session["bridges_served"] = bridges_snapshot
        else:
            session.pop("bridges_served", None)
        if hints_existed:
            session["hint_progress"] = hints_snapshot
        else:
            session.pop("hint_progress", None)
        if not session_existed and not session:
            state.data.pop("session", None)

    return undo


def _apply_projection(state, event: OutcomeEvent) -> dict:
    payload = dict(event.payload or {})
    outcome = str(event.outcome or "").lower()
    concept = event.concept_id or payload.get("target_concept")
    item_id = event.item_id or event.assessment_hook_id or event.beat_id
    kind = payload.get("mutation_kind") or payload.get("kind") or "practice"
    target = item_id if kind == "bridge" else concept
    before = state.mastery(target) if target else None
    if kind == "bridge":
        result = state._project_bridge_result(
            item_id, outcome, payload.get("revealed_misconception_id"),
            evidence_ref=event.event_id,
            evidence_consistent=event.consistent_with_misconception,
            observed_at=event.ts)
    elif kind == "misconception":
        result = state._project_probe_result(
            item_id, outcome, concept_id=concept,
            hints_used=int(event.assistance_consumed or payload.get("hints_used") or 0),
            evidence_consistent=event.consistent_with_misconception,
            evidence_ref=event.event_id,
            binary_item=bool(payload.get("binary_item", False)),
            observed_at=event.ts)
    else:
        if not concept:
            raise ValueError("missing_target_concept")
        result = state._project_item_result(
            item_id, outcome, concept, kind=kind,
            difficulty=payload.get("difficulty"),
            hints_used=int(event.assistance_consumed or payload.get("hints_used") or 0),
            observed_at=event.ts)
    representations = [str(r) for r in (payload.get("representations") or []) if r]
    if outcome == "correct" and concept and representations:
        cs = state.concept_states.setdefault(concept, {})
        known = cs.setdefault("representations_known", [])
        for representation in representations:
            if representation not in known:
                known.append(representation)
    after = state.mastery(target) if target else before
    application = dict(result)
    application.update({
        "status": "applied", "idempotency_key": event.idempotency_key,
        "event_id": event.event_id, "mastery_before": before,
        "mastery_after": after,
        "mastery_delta_applied": (None if before is None or after is None
                                  else round(after - before, 4)),
    })
    return application


def record_outcome(state, event: OutcomeEvent | dict) -> dict:
    """The ONLY function that creates durable learning evidence.

    Projection and ledger append are one in-memory transaction and are persisted
    together by the existing atomic LearnerState.save()/Firestore document write.
    """
    event = event if isinstance(event, OutcomeEvent) else OutcomeEvent.from_dict(event)
    bound_learner = str(state.data.get("learner_id") or "").strip()
    if not event.learner_id and bound_learner:
        event.learner_id = bound_learner
    if bound_learner and event.learner_id != bound_learner:
        raise ValueError("outcome learner_id does not match bound learner state")
    if not event.learner_id:
        raise ValueError("OutcomeEvent requires learner_id")
    key = event.idempotency_key
    if not key or not event.event_id or not event.turn_id:
        raise ValueError("OutcomeEvent requires event_id, turn_id, and idempotency_key")
    index = _index(state)
    if key in index:
        row = _ledger(state)[int(index[key])]
        result = dict(row.get("application") or {})
        result.update({"status": "duplicate", "idempotency_key": key})
        return result
    if event.outcome not in {"correct", "partial", "wrong"}:
        return {"status": "rejected", "reason": "insufficient_evidence",
                "idempotency_key": key}
    if event.stt_confidence is not None and event.stt_confidence < STT_WRITE_CONFIDENCE_MIN:
        return {"status": "suppressed", "reason": "low_stt_confidence",
                "idempotency_key": key}
    if event.grader_confidence is None or event.grader_confidence < GRADER_WRITE_CONFIDENCE_MIN:
        return {"status": "suppressed", "reason": "low_grader_confidence",
                "idempotency_key": key}

    identity_created = not bound_learner
    if identity_created:
        state.data["learner_id"] = event.learner_id
    undo_projection = _projection_undo(state, event)
    ledger = _ledger(state)
    ledger_len = len(ledger)
    base_created = "evidence_projection_base" not in state.data
    try:
        if not ledger:
            state.data.setdefault("evidence_projection_base", _projection_base(state))
        application = _apply_projection(state, event)
        row = event.to_dict()
        row["schema_version"] = LEDGER_SCHEMA_VERSION
        row["application"] = application
        ledger.append(row)
        _index(state)[key] = len(ledger) - 1
        state.data["state_schema_version"] = STATE_SCHEMA_VERSION
        return dict(application)
    except Exception:
        undo_projection()
        del ledger[ledger_len:]
        _index(state).pop(key, None)
        if base_created:
            state.data.pop("evidence_projection_base", None)
        if identity_created:
            state.data.pop("learner_id", None)
        raise


def replay(events: Iterable[OutcomeEvent | dict], *, base_state: dict | None = None):
    """Replay without appending a second ledger; used by migration and tests only."""
    from learner_state import LearnerState

    state = LearnerState(None, copy.deepcopy(base_state or {
        "concept_states": {}, "misconception_states": {}, "global": {},
        "session": {"bridges_served": []}}))
    for raw in events:
        event = raw if isinstance(raw, OutcomeEvent) else OutcomeEvent.from_dict(raw)
        if event.outcome in {"correct", "partial", "wrong"}:
            _apply_projection(state, event)
    return state


def migrate_state_data(data: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible additive migration; persisted rows are never rewritten."""
    data.setdefault("concept_states", {})
    data.setdefault("global", {})
    data.setdefault("misconception_states", {})
    if "evidence_log" in data and "evidence_ledger" not in data:
        data["evidence_ledger"] = list(data.get("evidence_log") or [])
    ledger = data.setdefault("evidence_ledger", [])
    for row in ledger:
        row.setdefault("schema_version", 0)
        if not row.get("event_id"):
            row["event_id"] = "legacy_" + hashlib.sha256(json.dumps(
                row, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]
    data["evidence_index"] = {
        row.get("idempotency_key"): offset for offset, row in enumerate(ledger)
        if row.get("idempotency_key")}
    for mid, record in list(data["misconception_states"].items()):
        if not isinstance(record, dict):
            data["misconception_states"].pop(mid, None)
            continue
        status = record.get("status")
        if status in {"active", "suspected", "recurring"}:
            failures = int(record.get("consistent_failures")
                           or record.get("consecutive_failures") or 0)
            record["status"] = "supported" if failures >= 2 else "candidate"
        record.setdefault("evidence_refs", [])
        record.setdefault("transitions", [])
    pending = (data.get("session") or {}).get("pending_check")
    if isinstance(pending, dict) and not pending.get("item_verified"):
        pending.setdefault("verification_status", "legacy_unverified")
    data["state_schema_version"] = STATE_SCHEMA_VERSION
    return data


def ledger_size_bytes(state) -> int:
    return len(json.dumps(_ledger(state), ensure_ascii=False).encode("utf-8"))
