"""Public Interface for the Interaction Control Feature Module."""

from .control import (
    CapabilityTransition,
    InteractionControl,
    InteractionControlDependencies,
    InteractionControlInterface,
    InteractionContinuity,
    InteractionControlRequest,
    InteractionDecision,
    InteractionDisposition,
)
from .safety_composition import (
    SafetySeverity,
    SafetyVerdict,
    compose_safety_alert,
    compose_safety_verdict,
    derive_severity,
    union_late,
)

__all__ = [
    "SafetySeverity",
    "SafetyVerdict",
    "compose_safety_alert",
    "compose_safety_verdict",
    "derive_severity",
    "union_late",
    "CapabilityTransition",
    "InteractionControl",
    "InteractionControlDependencies",
    "InteractionControlInterface",
    "InteractionContinuity",
    "InteractionControlRequest",
    "InteractionDecision",
    "InteractionDisposition",
]
