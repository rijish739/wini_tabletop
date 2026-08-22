"""Deep Perception Module Interface and its validated observation policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from runtime.contracts import (
    FailureSeverity,
    FailureSignal,
    ModuleOutcome,
    StateChange,
    StateOperation,
    StateScope,
    TurnInput,
    deep_freeze,
    deep_thaw,
)

from .gates import gate
from .route import INTENT_SET, RouteResult


class PerceptionTransportError(RuntimeError):
    """A classified transport failure reported by the shared Model Gateway."""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(detail or kind)
        self.kind = kind


class PerceptionEngine(Protocol):
    """Internal policy engine retained while the cognitive analyzer is folded in."""

    def observe(
        self, text: str, session: Mapping[str, Any], current_concept: str | None
    ) -> tuple[RouteResult, Mapping[str, Any]]: ...


@dataclass(frozen=True)
class PerceptionRequest:
    turn_input: TurnInput
    session: Mapping[str, Any]
    learner_state: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "session", deep_freeze(self.session))
        object.__setattr__(
            self, "learner_state", deep_freeze(self.learner_state or {})
        )


@dataclass(frozen=True)
class PerceptionObservation:
    intent: str
    concept_id: str | None
    concept_confidence: float
    secondary_concepts: tuple[str, ...]
    signals: tuple[str, ...]
    signal_scores: Mapping[str, float]
    cognitive_update: Mapping[str, float]
    safety_alert: bool
    answer_attempt: bool
    uncertain: bool
    source: str
    route: RouteResult
    analysis: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "secondary_concepts", tuple(self.secondary_concepts))
        object.__setattr__(self, "signals", tuple(self.signals))
        object.__setattr__(self, "signal_scores", deep_freeze(self.signal_scores))
        object.__setattr__(self, "cognitive_update", deep_freeze(self.cognitive_update))
        object.__setattr__(self, "analysis", deep_freeze(self.analysis))


class PerceptionInterface(Protocol):
    """The single seam used by the Turn Coordinator and Interface tests."""

    def perceive(
        self, request: PerceptionRequest
    ) -> ModuleOutcome[PerceptionObservation]: ...


class Perception:
    """Derive validated intent, cognitive, concept, and safety observations."""

    _REQUIRED_ANALYSIS = frozenset({
        "normalized_text", "signals", "signal_scores", "concept",
        "cognitive_update", "state_deltas",
    })

    def __init__(self, engine: PerceptionEngine) -> None:
        self._engine = engine

    def perceive(
        self, request: PerceptionRequest
    ) -> ModuleOutcome[PerceptionObservation]:
        interaction = deep_thaw(request.turn_input.interaction)
        text = str(interaction.get("text") or "")
        deterministic = gate(text)
        if deterministic is not None:
            return ModuleOutcome(value=self._from_route(deterministic, {}))

        session = deep_thaw(request.session)
        try:
            route, analysis = self._engine.observe(
                text, session, session.get("current_concept")
            )
            trusted = deep_thaw(request.turn_input.trusted_observations)
            if trusted.get("precomputed_analysis") is not None:
                analysis = trusted["precomputed_analysis"]
            if bool(getattr(route, "uncertain", False)):
                return self._degraded(
                    session, "degraded_fallback", text=text, analysis=analysis
                )
            observation = self._validate(route, analysis, session)
            return ModuleOutcome(
                value=observation,
                state_changes=self._soft_state_changes(request, observation),
            )
        except PerceptionTransportError as exc:
            cause = exc.kind if exc.kind in {"timeout", "backend_unavailable"} else "backend_unavailable"
            return self._degraded(session, cause, text=text)
        except (TypeError, ValueError, KeyError, AttributeError):
            return self._degraded(session, "invalid_schema", text=text)
        except Exception:
            return self._degraded(session, "backend_unavailable", text=text)

    def _validate(
        self,
        route: RouteResult,
        analysis: Mapping[str, Any],
        session: Mapping[str, Any],
    ) -> PerceptionObservation:
        if not isinstance(route, RouteResult) or route.primary not in INTENT_SET:
            raise ValueError("invalid route")
        if route.primary != "LEARNING":
            return self._from_route(route, {})
        if not isinstance(analysis, Mapping) or not self._REQUIRED_ANALYSIS <= analysis.keys():
            raise ValueError("invalid analysis")
        mutable = deep_thaw(analysis)
        concept = mutable.get("concept")
        if not isinstance(concept, dict):
            raise ValueError("invalid concept")
        concept_id = concept.get("concept_id")
        if concept.get("abstained") and not concept_id:
            concept_id = session.get("current_concept")
            concept["concept_id"] = concept_id
        confidence = float(concept.get("concept_confidence", 0.0))
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("invalid confidence")
        signals = mutable.get("signals")
        scores = mutable.get("signal_scores")
        cognitive = mutable.get("cognitive_update")
        if not isinstance(signals, list) or not isinstance(scores, dict) or not isinstance(cognitive, dict):
            raise ValueError("invalid cognitive observation")
        return PerceptionObservation(
            intent=route.primary,
            concept_id=concept_id,
            concept_confidence=confidence,
            secondary_concepts=tuple(concept.get("secondary_concepts") or ()),
            signals=tuple(str(signal) for signal in signals),
            signal_scores={str(key): float(value) for key, value in scores.items()},
            cognitive_update={str(key): float(value) for key, value in cognitive.items()},
            safety_alert=bool(route.safety_alert),
            answer_attempt=bool(route.answer_attempt),
            uncertain=bool(route.uncertain),
            source=route.source,
            route=route,
            analysis=mutable,
        )

    def _from_route(
        self, route: RouteResult, analysis: Mapping[str, Any]
    ) -> PerceptionObservation:
        return PerceptionObservation(
            intent=route.primary,
            concept_id=route.concept_id,
            concept_confidence=float(route.concept_confidence),
            secondary_concepts=tuple(route.secondary_concepts),
            signals=(),
            signal_scores=dict(route.signal_scores),
            cognitive_update={},
            safety_alert=bool(route.safety_alert),
            answer_attempt=bool(route.answer_attempt),
            uncertain=bool(route.uncertain),
            source=route.source,
            route=route,
            analysis=analysis,
        )

    @staticmethod
    def _soft_state_changes(
        request: PerceptionRequest, observation: PerceptionObservation
    ) -> tuple[StateChange, ...]:
        """Translate validated weak evidence into typed, coordinator-visible changes."""
        deltas = deep_thaw(observation.analysis).get("state_deltas") or {}
        state = deep_thaw(request.learner_state)
        changes: list[StateChange] = []
        global_defaults = {
            "confidence": 0.5, "curiosity": 0.5,
            "cognitive_load": 0.5, "engagement": 0.5,
        }
        global_state = state.get("global") or {}
        counts = state.get("global_observations") or {}
        for field, observed in (deltas.get("global") or {}).items():
            if field not in global_defaults:
                continue
            old = float(global_state.get(field, global_defaults[field]))
            value = round(0.7 * old + 0.3 * float(observed), 4)
            changes.extend((
                StateChange(
                    change_id=f"{request.turn_input.turn_id}:perception:global:{field}",
                    owner="perception", scope=StateScope.LEARNER,
                    path=("global", field), operation=StateOperation.SET, value=value,
                ),
                StateChange(
                    change_id=f"{request.turn_input.turn_id}:perception:observations:{field}",
                    owner="perception", scope=StateScope.LEARNER,
                    path=("global_observations", field), operation=StateOperation.SET,
                    value=int(counts.get(field, 0)) + 1,
                ),
            ))
        return tuple(changes)

    def _degraded(
        self,
        session: Mapping[str, Any],
        cause: str,
        *,
        text: str,
        analysis: Mapping[str, Any] | None = None,
    ) -> ModuleOutcome[PerceptionObservation]:
        current = session.get("current_concept")
        route = RouteResult(
            primary="LEARNING", concept_id=current, concept_confidence=0.0,
            source="fallback", uncertain=True,
            reason="perception fallback (LEARNING/inherit)",
        )
        neutral_analysis = {
            "raw_text": text, "normalized_text": text.strip(), "problem_cue": {},
            "signals": [], "signal_scores": {},
            "concept": {
                "concept_id": current, "concept_confidence": 0.0,
                "secondary_concepts": [], "abstained": True,
                "resolution_reason": "degraded fallback inherited session concept",
            },
            "cognitive_update": {
                "confusion": 0.0, "curiosity": 0.0, "confidence": 0.5,
                "misconception_probability": 0.0, "transfer_attempt": 0.0,
                "abstraction_attempt": 0.0, "self_correction": 0.0,
                "cognitive_load": 0.0, "engagement": 0.5,
                "frustration_risk": 0.0,
            },
            "state_deltas": {
                "global": {}, "concept_id": current,
                "concept_flags": [], "signals": [],
            },
        }
        failure = FailureSignal(
            capability="perception",
            phase="perception_and_prior_grading",
            severity=FailureSeverity.DEGRADED,
            recoverable=True,
            cause=cause,
            valid_outcome=True,
            context={"fallback": "neutral_inherited_concept"},
        )
        if analysis is not None:
            try:
                neutral_analysis = deep_thaw(analysis)
                concept = neutral_analysis["concept"]
                concept["concept_id"] = current
                concept["concept_confidence"] = 0.0
                concept["secondary_concepts"] = []
                concept["abstained"] = True
                neutral_analysis["signals"] = []
                neutral_analysis["signal_scores"] = {}
                neutral_analysis["cognitive_update"] = {
                    "confusion": 0.0, "curiosity": 0.0, "confidence": 0.5,
                    "misconception_probability": 0.0, "transfer_attempt": 0.0,
                    "abstraction_attempt": 0.0, "self_correction": 0.0,
                    "cognitive_load": 0.0, "engagement": 0.5,
                    "frustration_risk": 0.0,
                }
                neutral_analysis["state_deltas"] = {
                    "global": {}, "concept_id": current,
                    "concept_flags": [], "signals": [],
                }
            except (TypeError, KeyError):
                pass
        return ModuleOutcome(
            value=self._from_route(route, neutral_analysis), failures=(failure,)
        )


class LegacyPerceptionEngine:
    """Temporary internal adapter around the existing cognitive analyzer."""

    def __init__(self, *, route, analyze) -> None:
        self._route = route
        self._analyze = analyze

    def observe(self, text, session, current_concept):
        route = self._route(text, session)
        analysis = self._analyze(text, current_concept)
        return route, analysis
