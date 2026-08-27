"""The one shared safety-verdict composition entry point.

Both Interaction Control sites that branch on ``safety_alert`` compose the
verdict here, so two call sites can never compose it differently. The invariant,
retargeted and stated as one sentence: **nothing may ever remove a finding,
whatever made it.** Composition is union-only and monotone — it can only add.

Frozen from day one (ticket 01). Its body today is the LEXICON reading union
perception's ``safety`` bit. Slice 12 (``child_safety/`` cutover) changes the
**body** of this function to union in the model verdict; **the legacy-20
regression test that calls it is never edited at cutover.** See
``docs/architecture/SAFETY_ROUTE_TAXONOMY.md`` §6 (normative).
"""

from __future__ import annotations

from typing import Any


def compose_safety_alert(
    *,
    lexicon: Any = None,
    perception_safety_alert: bool = False,
) -> bool:
    """Union the safety sources into one alert boolean. Add-only.

    * ``lexicon`` — the ``SafetySignals`` LEXICON reading from Utterance Intake
      (or ``None`` when no observation is available yet).
    * ``perception_safety_alert`` — perception's existing ``safety`` bit.

    Slice 12 adds the ``child_safety`` model verdict as a third union term here.
    """
    lexicon_tripped = bool(lexicon is not None and getattr(lexicon, "tripped", False))
    return bool(perception_safety_alert) or lexicon_tripped
