"""Response Context Adapter (§5.1) — one normalized input envelope.

``build_response_context`` maps the values ``tutor_loop.turn()`` has ALREADY computed by
the time it reaches generation (action, need, concept, evidence manifest, snapshot signals,
mode, representation/misconception targets, the available scene/crop) into a single
``ResponseContext``. It is pure deterministic schema mapping — it does no upstream work and
makes no model calls (§5.1 "very low runtime cost, negligible latency").

Kept as a free function taking explicit kwargs (not reaching into TutorLoop internals) so
it is unit-testable and the integration seam passes exactly what it has. Absent optional
inputs fall back to safe defaults, so a partially-populated turn never fails to build a
context (§5.1 failure modes → degrade, don't raise).
"""

from __future__ import annotations

import uuid

from .contracts import ResponseContext, ResponseKind, _coerce_enum
from .device_profile import WINIPI5_PROFILE


def _mastery_tier(mastery: float | None) -> str:
    if mastery is None:
        return "medium"
    if mastery < 0.34:
        return "low"
    if mastery < 0.67:
        return "medium"
    return "high"


def build_response_context(
    *,
    turn_id: str | None = None,
    pedagogical_action: str | None = None,
    need: str | None = None,
    teaching_goal: str | None = None,
    concept_id: str | None = None,
    concept_type: str | None = None,
    evidence: list[dict] | None = None,
    evidence_manifest_ref: str | None = None,
    response_kind: str = "instructional",
    mode: str = "EXPLAIN",
    wants_visual: bool = False,
    wants_animation: bool = False,
    wants_real_life: bool = False,
    clarification: bool = False,
    is_intro: bool = False,
    grounding: str = "manifest_only",
    misconception_targets: list[str] | None = None,
    representation_targets: list[str] | None = None,
    active_misconception: bool = False,
    misconception_confirmed: bool = False,
    cognitive_load: float = 0.0,
    frustration_risk: float = 0.0,
    mastery: float | None = None,
    grade_level: str | None = None,
    available_scene_concept_id: str | None = None,
    available_crop: dict | None = None,
    device_profile: dict | None = None,
) -> ResponseContext:
    return ResponseContext(
        response_context_id=f"ctx_{uuid.uuid4().hex[:10]}",
        turn_id=turn_id or f"turn_{uuid.uuid4().hex[:8]}",
        response_kind=_coerce_enum(ResponseKind, response_kind, ResponseKind.INSTRUCTIONAL),
        pedagogical_action=pedagogical_action,
        need=need,
        teaching_goal=teaching_goal,
        concept_id=concept_id,
        concept_type=concept_type,
        misconception_targets=list(misconception_targets or []),
        representation_targets=list(representation_targets or []),
        evidence=list(evidence or []),
        evidence_manifest_ref=evidence_manifest_ref,
        cognitive_load=float(cognitive_load or 0.0),
        frustration_risk=float(frustration_risk or 0.0),
        mastery_tier=_mastery_tier(mastery),
        active_misconception=bool(active_misconception),
        misconception_confirmed=bool(misconception_confirmed),
        grade_level=grade_level,
        mode=mode or "EXPLAIN",
        wants_visual=bool(wants_visual),
        wants_animation=bool(wants_animation),
        wants_real_life=bool(wants_real_life),
        clarification=bool(clarification),
        is_intro=bool(is_intro),
        grounding=grounding or "manifest_only",
        available_scene_concept_id=available_scene_concept_id,
        available_crop=available_crop,
        device_profile=device_profile or WINIPI5_PROFILE.to_dict(),
    )
