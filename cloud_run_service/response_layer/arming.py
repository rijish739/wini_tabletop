"""Single choke point between a TeachingScript and a gradeable session check."""
from __future__ import annotations

from .contracts import TeachingScript

_VERIFIED_STATUSES = {"verified", "authored_verified"}


def _is_armable(hook) -> bool:
    status = str(getattr(hook, "verification_status", "") or "")
    if not status and getattr(hook, "item_verified", False):
        # Compatibility for a currently persisted authored hook. Generated items
        # never receive this fallback; they require the verify() token below.
        provenance = str(getattr(hook, "verification_provenance", "") or "")
        status = "authored_verified" if provenance == "authored_store" else ""
    token = str(getattr(hook, "verification_token", "") or "")
    source = str(getattr(hook, "item_source", "") or "")
    if source.startswith("generated") and not token:
        return False
    return bool(
        status in _VERIFIED_STATUSES and token
        and hook.item_id and hook.question
        and (hook.expected_answer or hook.rubric)
        and hook.assessment_purpose and hook.state_update_intent
        and hook.reveal_policy
    )


def pending_is_assessable(pending: dict | None) -> bool:
    value = dict(pending or {})
    status = value.get("verification_status")
    token = value.get("verification_token")
    return bool(
        status in _VERIFIED_STATUSES and token and value.get("item_id")
        and value.get("question") and (value.get("expected_answer") or value.get("rubric"))
        and value.get("assessment_purpose") and value.get("kind")
        and value.get("reveal_policy"))


def _downgrade(script: TeachingScript, beat, reason: str) -> None:
    beat.assessment_hook = None
    if beat.completion_condition in {"await_spoken_answer", "await_local_response"}:
        beat.completion_condition = "speech_complete"
    script.validation.setdefault("assessment_downgrades", []).append({
        "beat_id": beat.beat_id, "reason": reason})
    script.validation["assessment_hooks_ok"] = False


def arm_from_script(script: TeachingScript, session: dict) -> dict | None:
    """The ONLY function allowed to create an assessable pending_check."""
    hooks = [(beat, beat.assessment_hook) for beat in (script.beats or [])
             if beat.assessment_hook is not None]
    if len(hooks) != 1:
        for beat, _hook in hooks:
            _downgrade(script, beat, "exactly_one_assessing_hook_required")
        return None
    beat, hook = hooks[0]
    if not _is_armable(hook):
        _downgrade(script, beat, "unverified_or_incomplete_item")
        return None
    pending = hook.to_dict()
    pending.update({
        "kind": hook.state_update_intent,
        "id": hook.item_id,
        "concept_id": hook.target_concept,
        "script_id": script.script_id,
        "beat_id": beat.beat_id,
        "attempt": 1,
        "action": script.pedagogical_action or "unknown",
        "mode": session.get("mode", "EXPLAIN"),
        "barrier": session.get("barrier", "unknown"),
    })
    # Single-writer guarantee: no other function may assign an assessable check.
    session["pending_check"] = pending
    return pending


def void_pending_assessment(session: dict, *, reason: str,
                            item_id: str | None = None) -> dict | None:
    pending = session.get("pending_check")
    if pending and (item_id is None or pending.get("item_id") == item_id):
        session.pop("pending_check", None)
    session["voided_check"] = {"item_id": item_id, "reason": reason}
    return pending
