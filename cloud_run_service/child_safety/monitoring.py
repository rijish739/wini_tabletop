"""Net-vs-model divergence — MONITORING ONLY (SAFETY_ROUTE_TAXONOMY.md §10.4).

The lexicon reading is computed every turn anyway (microseconds, no network). On a
healthy turn it is **not the verdict** and is consumed by nothing except this: a
free continuous health check on the outage net, published as a divergence metric.

Read the last three words of §10.4 before wiring anything to this. It never gates a
release, never alters a verdict, and **can never be a reason to edit the lexicon
toward the model.** The lexicon is frozen; a divergence row is a fact about the net,
not a defect report against it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import ModelSafetyVerdict


@dataclass(frozen=True)
class Divergence:
    """One turn's agreement between the outage net and the model, axis only.

    Classes are not compared: the net emits only ``UNSPECIFIED_CONCERN`` by design
    (§8), so a class comparison would measure that design decision rather than the
    net's health.
    """

    net_tripped: bool
    model_tripped: bool
    model_available: bool

    @property
    def comparable(self) -> bool:
        """False when the model did not answer — a non-answer is not a disagreement."""
        return self.model_available

    @property
    def agrees(self) -> bool | None:
        if not self.comparable:
            return None
        return self.net_tripped == self.model_tripped

    @property
    def label(self) -> str:
        if not self.comparable:
            return "model_unavailable"
        if self.net_tripped and self.model_tripped:
            return "both"
        if self.net_tripped:
            return "net_only"
        if self.model_tripped:
            return "model_only"
        return "neither"

    def as_metric(self) -> dict:
        """Analytics-safe by construction: booleans and a label, no classes, no text.
        §14 gives routine analytics ``tripped`` + ``severity`` and nothing else; this
        carries less than that."""
        return {
            "net_tripped": self.net_tripped,
            "model_tripped": self.model_tripped,
            "model_available": self.model_available,
            "divergence": self.label,
        }


def divergence(lexicon, model: ModelSafetyVerdict | None) -> Divergence:
    """Compare the always-computed lexicon reading against the model verdict."""
    return Divergence(
        net_tripped=bool(lexicon is not None and getattr(lexicon, "tripped", False)),
        model_tripped=bool(model is not None and model.tripped),
        model_available=bool(model is not None and model.available),
    )
