"""Response Layer — the teaching-transaction compiler (response_layer_architecture_plan.md).

Phase 1+2 slice: the canonical **Teaching Script** contracts (Phase 1) plus a
template-first planner, a Visual Benefit Gate, and a script validator (Phase 2).

The layer starts AFTER retrieval and turns the frozen upstream outputs (learner
snapshot, pedagogical action, evidence manifest, concept, misconceptions,
representation gaps) into ONE synchronized plan — the Teaching Script — before any
modality output exists. Speech, visuals, touch, robot behaviour, and assessment are
all rendered from that single script; no modality invents instructional content.

This package is BRAIN-side (it runs inside the Pi's `wini_server` brain process). It
is inert until `WINI_RESPONSE_LAYER=1` flips the flagged block in `tutor_loop.turn()`
— see the module docstrings for the exact seam. Nothing here touches learner state:
the single-writer rule (§3.10) is preserved; this layer is planning + validation only.

Public surface:
    from response_layer import (
        ResponseContext, TeachingScript, Beat, AssessmentHook, OutcomeEvent,
        DeviceCapabilityProfile, WINIPI5_PROFILE,
        ResponseKind, VisualType, ExecutionMode,
        build_response_context, TeachingScriptPlanner, ScriptValidator,
    )
"""

from __future__ import annotations

from .contracts import (
    AssessmentHook,
    AssessmentHookType,
    Beat,
    ExecutionMode,
    OutcomeEvent,
    ResponseContext,
    ResponseKind,
    RobotPrimitive,
    TeachingScript,
    VisualType,
)
from .device_profile import (
    DeviceCapabilityProfile,
    ESP32_P4_PROFILE,
    WINIPI5_PROFILE,
    profile_from_report,
)

__all__ = [
    "AssessmentHook",
    "AssessmentHookType",
    "Beat",
    "ExecutionMode",
    "OutcomeEvent",
    "ResponseContext",
    "ResponseKind",
    "RobotPrimitive",
    "TeachingScript",
    "VisualType",
    "DeviceCapabilityProfile",
    "WINIPI5_PROFILE",
    "ESP32_P4_PROFILE",
    "profile_from_report",
    # Planner / validator / adapter are imported lazily by callers to keep this
    # package importable (for the pure-data contracts + unit tests) without pulling
    # in the tutor_loop / rag_store dependencies until a real turn needs them.
    "build_response_context",
    "TeachingScriptPlanner",
    "ScriptValidator",
]


def __getattr__(name: str):  # PEP 562 lazy re-export
    # planner/validator/adapter reach into templates + formula_links; importing them
    # eagerly would make `import response_layer` drag the store in. Contracts stay free.
    if name in ("TeachingScriptPlanner",):
        from .planner import TeachingScriptPlanner

        return TeachingScriptPlanner
    if name in ("build_response_context",):
        from .adapter import build_response_context

        return build_response_context
    if name in ("ScriptValidator",):
        from .validator import ScriptValidator

        return ScriptValidator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
