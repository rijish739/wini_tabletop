"""Child Safety — the PRIMARY safety detector.

A sibling of ``perception/``, not a part of it: independent prompt-of-record,
schema, version string, context cache and eval. ``docs/architecture/
SAFETY_ROUTE_TAXONOMY.md`` is normative; this package implements §7.

What this package does NOT contain, on purpose:

* **severity** — derived at exactly one site, the composition step in
  ``interaction_control.safety_composition`` (§5). ``SafetySeverity`` is not
  importable from here.
* **caregiver_implicated** — lexicon-only (§4.1); a precision-seeking model would
  quietly undo an over-trigger that exists to stop a child being directed toward
  the person harming them.
* **the lexicon** — that stayed in ``perception/gates.py`` and is read by Utterance
  Intake as the degraded-mode outage net (§8).
"""

from .contracts import (
    ModelSafetyVerdict,
    SafetyModelStatus,
    SafetySessionSummary,
)
from .detector import ChildSafetyDetector
from .dispatch import ChildSafetyGateway, SafetyDispatch
from .monitoring import Divergence, divergence
from .prompt import PROMPT_VERSION, SAFETY_CLASS_NAMES, SCHEMA_VERSION, prompt_hash

__all__ = [
    "ChildSafetyDetector",
    "ChildSafetyGateway",
    "Divergence",
    "ModelSafetyVerdict",
    "PROMPT_VERSION",
    "SAFETY_CLASS_NAMES",
    "SCHEMA_VERSION",
    "SafetyDispatch",
    "SafetyModelStatus",
    "SafetySessionSummary",
    "divergence",
    "prompt_hash",
]
