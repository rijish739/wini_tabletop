"""Teaching strategy, learning-mode, progression, and pacing policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from runtime.contracts import (
    ModuleOutcome,
    StateChange,
    StateOperation,
    StateScope,
    TurnInput,
    deep_freeze,
    deep_thaw,
)
from session_modes import ModeController


CAPABILITY = "pedagogy"
ASSESSING_ACTIONS = frozenset({
    "MISCONCEPTION_PROBE", "COMPLETION_STEP", "ISOMORPHIC_PRACTICE",
    "TRANSFER_PROBLEM", "TEST_QUESTION",
})


@dataclass(frozen=True)
class PedagogyObservation:
    """Validated Perception facts relevant to teaching policy."""

    normalized_text: str
    concept_id: str | None
    signals: tuple[str, ...] = ()
    concept_flags: tuple[str, ...] = ()
    cognitive_update: Mapping[str, float] = None
    abstained: bool = False
    answer_attempt: bool = False
    perception_degraded: bool = False
    acknowledged: bool = False
    clarification_requested: bool = False
    visualization_requested: bool = False
    purpose_requested: bool = False
    learning_requested: bool = False
    question: bool = False
    learner_problem: bool = False
    requested_mode: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "signals", tuple(self.signals))
        object.__setattr__(self, "concept_flags", tuple(self.concept_flags))
        object.__setattr__(self, "cognitive_update", deep_freeze(self.cognitive_update or {}))


@dataclass(frozen=True)
class PedagogyStateView:
    """The current working-state projection Pedagogy is permitted to observe."""

    session: Mapping[str, Any]
    mastery: float = 0.2
    transfer_readiness: float = 0.0
    has_active_misconception: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "session", deep_freeze(self.session))


@dataclass(frozen=True)
class PedagogyDependencies:
    schema_ids: Callable[[str | None], list[str]] | None = None
    can_assess: bool = True
    mastery_gate_threshold: float = 0.8


@dataclass(frozen=True)
class PedagogyRequest:
    turn_input: TurnInput
    observation: PedagogyObservation
    state: PedagogyStateView
    prior_outcome: str | None = None
    prior_hints: int = 0


@dataclass(frozen=True)
class PedagogicalPacing:
    max_words: int
    max_sentences: int


@dataclass(frozen=True)
class PedagogicalDecision:
    action: str
    need: str
    reason: str
    mode: str
    introduction: bool = False
    assessment_appropriate: bool = False
    plan: Mapping[str, Any] | None = None
    pacing: PedagogicalPacing = PedagogicalPacing(60, 3)

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan", deep_freeze(self.plan or {}))


class PedagogyInterface(Protocol):
    """The single seam used by the Turn Coordinator and Interface tests."""

    def decide(
        self, request: PedagogyRequest
    ) -> ModuleOutcome[PedagogicalDecision]: ...


class Pedagogy:
    """Select pedagogically appropriate action, mode, progression, and pacing."""

    def __init__(self, *, offers_enabled: bool = False,
                 dependencies: PedagogyDependencies | None = None) -> None:
        self._modes = ModeController(offers_enabled=offers_enabled)
        self._dependencies = dependencies or PedagogyDependencies()

    def decide(self, request: PedagogyRequest) -> ModuleOutcome[PedagogicalDecision]:
        session = deep_thaw(request.state.session)
        before = deep_thaw(request.state.session)
        text = request.observation.normalized_text
        # Pending pedagogical offers are one-shot state owned here. Resolution is
        # intentionally completed before explicit mode cues and progression.
        self._modes.consume_test_resume(session, text)
        self._modes.consume_offer(session, text)
        signals = set(request.observation.signals)
        flags = set(request.observation.concept_flags)
        update = dict(request.observation.cognitive_update)
        acknowledged = request.observation.acknowledged
        clarification = request.observation.clarification_requested or "simplification_request" in signals
        visual = request.observation.visualization_requested or (
            clarification and bool(signals & {"request_representation", "representation_shift"})
        )
        purpose = request.observation.purpose_requested
        student_problem = request.observation.learner_problem
        answer_attempt = bool(request.observation.answer_attempt)
        learning_start = (
            bool(request.observation.concept_id)
            and (request.state.mastery <= 0.2 or request.observation.learning_requested)
            and not answer_attempt and not acknowledged
            and not session.get("pending_check") and not student_problem
            and (request.observation.question or request.observation.learning_requested
                 or bool(signals & {"curiosity", "question", "example_request", "learning_goal"}))
            and float(update.get("frustration_risk", 0.0)) < 0.6
        )

        mode, mode_reason = self._modes.resolve_mode(
            session, text, cue=request.observation.requested_mode
        )
        override = visual or purpose or clarification or "misconception_suspected" in flags
        plan: dict[str, Any] = {}
        if mode == "PRACTICE" and not override:
            plan = self._modes.next_practice_item(
                session,
                mastery=request.state.mastery,
                last_outcome=request.prior_outcome,
                last_hints=request.prior_hints,
            )
            if plan.get("exit_to_explain"):
                mode = self._modes.set_mode(session, "EXPLAIN")
                action, need, reason = "EXPLAIN", "explain", str(plan["why"])
            else:
                action, need, reason = plan["action"], plan["need"], plan["why"]
        elif mode == "TEST" and not override:
            planned = self._drive_test(
                session, request.observation.concept_id, request.prior_outcome
            )
            if planned is None:
                action, need = "EXPLAIN", "explain"
                reason = "test mode: no verified item -> non-assessing explanation"
                plan = {}
            else:
                plan = planned
                action, need, reason = plan["action"], plan["need"], plan["why"]
        else:
            action, need, reason = self._teaching_action(
                update=update,
                signals=signals,
                flags=flags,
                abstained=request.observation.abstained,
                acknowledged=acknowledged,
                clarification=clarification and not answer_attempt,
                learning_start=learning_start,
                visual=visual and not answer_attempt,
                purpose=purpose and not answer_attempt,
                student_problem=student_problem,
                transfer_ready=request.state.transfer_readiness >= 0.75,
            )

        appropriate = action in ASSESSING_ACTIONS and not request.observation.perception_degraded
        if request.observation.perception_degraded and action in ASSESSING_ACTIONS:
            action, need = "EXPLAIN", "explain"
            reason += "; degraded perception -> non-assessing explanation"
            plan = {}
        if mode == "EXPLAIN":
            offer = self._modes.maybe_offer_practice(
                session,
                acknowledged=acknowledged,
                analysis={"cognitive_update": update},
                has_active_misconception=request.state.has_active_misconception,
            )
            if offer:
                plan = dict(plan)
                plan["offer"] = offer
        decision = PedagogicalDecision(
            action=action,
            need=need,
            reason=reason,
            mode=mode,
            introduction=learning_start and action == "EXPLAIN" and request.state.mastery <= 0.2,
            assessment_appropriate=appropriate,
            plan=plan,
            pacing=self._pacing(update, mode, action),
        )
        return ModuleOutcome(
            value=decision,
            state_changes=self._state_changes(request.turn_input.turn_id, before, session),
        )

    def _drive_test(self, session: dict[str, Any], concept_id: str | None,
                    last_outcome: str | None) -> dict[str, Any] | None:
        deps = self._dependencies
        if not deps.can_assess or deps.schema_ids is None:
            return None
        test_state = session.get("test_state")
        if test_state and test_state.get("phase") != "done":
            concept_id = test_state["concept_id"]
        else:
            schemas = deps.schema_ids(concept_id)
            test_state = self._modes.build_quiz_set(session, concept_id, schemas)
            if not test_state:
                return None
            last_outcome = None
        step = self._modes.advance_test(
            session, last_outcome=last_outcome,
            gate_threshold=deps.mastery_gate_threshold,
        )
        if step and step["phase"] == "serving":
            return {
                "action": "TEST_QUESTION", "need": "schema", "why": step["why"],
                "schema_id": step["schema_id"], "item_no": step["i"],
                "of": step["n"], "prior_outcome": last_outcome,
                "concept_id": concept_id,
                "item_history": tuple(test_state.get("items", ())),
                "assessment_appropriate": True,
            }
        session.pop("test_state", None)
        if step["gate"] == "fail":
            self._modes.set_mode(session, "EXPLAIN")
        correct, count = step["correct"], step["n"]
        speak = (f"Great work — you got {correct} out of {count} right. That's a pass!"
                 if step["gate"] == "pass" else
                 f"You got {correct} out of {count} right. Let's work through the tricky parts together.")
        return {
            "action": "TEST_SUMMARY", "need": "none", "why": step["why"],
            "speak": speak, "test_completion": dict(step),
            "concept_id": concept_id,
            "item_history": tuple(test_state.get("items", ())),
            "results": list(step["results"]),
            "correct": correct, "of": count,
        }

    @staticmethod
    def _pacing(update: Mapping[str, Any], mode: str, action: str) -> PedagogicalPacing:
        if mode == "TEST":
            return PedagogicalPacing(35, 1)
        if (float(update.get("cognitive_load", 0.0)) >= 0.7
                or float(update.get("frustration_risk", 0.0)) >= 0.6):
            return PedagogicalPacing(35, 2)
        if action in {"WORKED_EXAMPLE", "SOLVE_STUDENT_PROBLEM"}:
            return PedagogicalPacing(90, 5)
        return PedagogicalPacing(60, 3)

    @staticmethod
    def _state_changes(turn_id: str, before: Mapping[str, Any], after: Mapping[str, Any]):
        missing = object()
        changes = []
        for key in sorted(set(before) | set(after)):
            old, new = before.get(key, missing), after.get(key, missing)
            if old == new:
                continue
            changes.append(StateChange(
                change_id=f"{turn_id}:pedagogy:{key}",
                owner=CAPABILITY,
                scope=StateScope.SESSION,
                path=(key,),
                operation=StateOperation.DELETE if new is missing else StateOperation.SET,
                value=None if new is missing else new,
            ))
        return tuple(changes)

    @staticmethod
    def _teaching_action(*, update, signals, flags, abstained, acknowledged,
                         clarification, learning_start, visual, purpose,
                         student_problem, transfer_ready):
        if visual and not acknowledged:
            return "REPRESENTATION_TRANSLATION", "integrate", "representation gap -> switch representation"
        if purpose and not acknowledged:
            return "WHY_IT_MATTERS", "explain", "purpose question -> answer why directly"
        if clarification and not acknowledged:
            return "EXPLAIN", "explain", "clarification -> re-explain more simply"
        if learning_start and not acknowledged:
            return "EXPLAIN", "explain", "fresh topic -> explain before assessing"
        if "misconception_suspected" in flags:
            return "MISCONCEPTION_PROBE", "explain", "suspected misconception -> probe before correcting"
        if "hint_requested" in flags:
            return "ANALOGOUS_EXAMPLE", "schema", "hint -> analogous example without answer"
        if acknowledged:
            return "METACOGNITIVE_REFLECT", "reflect", "acknowledgement -> consolidate and advance"
        if float(update.get("cognitive_load", 0.0)) >= 0.7 or float(update.get("frustration_risk", 0.0)) >= 0.6:
            return "ENCOURAGE", "explain", "high load -> brief explanation and encouragement"
        if student_problem:
            return "SOLVE_STUDENT_PROBLEM", "schema", "learner problem -> solve that instance"
        if transfer_ready and ("transfer_ready_evidence" in flags or "ready_for_next" in signals):
            return "TRANSFER_PROBLEM", "transfer", "transfer readiness -> near transfer"
        if signals & {"request_representation", "representation_shift", "graphical", "diagrammatic"}:
            return "REPRESENTATION_TRANSLATION", "integrate", "representation signal -> translate"
        if "self_corrected" in flags:
            return "METACOGNITIVE_REFLECT", "reflect", "self-correction -> reflection"
        if "example_request" in signals:
            return "WORKED_EXAMPLE", "example", "example requested"
        if float(update.get("curiosity", 0.0)) >= 0.6 and float(update.get("confusion", 0.0)) < 0.4:
            return "SOCRATIC_Q", "challenge", "curious and not confused -> challenge"
        if float(update.get("confusion", 0.0)) >= 0.4 or abstained:
            return "EXPLAIN", "explain", "confusion or unresolved concept -> explain"
        return "EXPLAIN", "explain", "default grounded explanation"


def rules_decide(update: Mapping[str, Any], signals: Any, flags: Any,
                 abstained: bool, *, acknowledged: bool = False,
                 clarification: bool = False, learning_start: bool = False,
                 visual: bool = False, purpose: bool = False,
                 student_problem: bool = False, transfer_ready: bool = True) -> tuple[str, str, str]:
    """Compatibility helper for rule-based pedagogical decision."""
    sig_set = set(signals) if isinstance(signals, (list, tuple, set)) else set()
    flag_set = set(flags) if isinstance(flags, (list, tuple, set)) else set()
    return Pedagogy._teaching_action(
        update=update or {},
        signals=sig_set,
        flags=flag_set,
        abstained=bool(abstained),
        acknowledged=bool(acknowledged),
        clarification=bool(clarification),
        learning_start=bool(learning_start),
        visual=bool(visual),
        purpose=bool(purpose),
        student_problem=bool(student_problem),
        transfer_ready=bool(transfer_ready),
    )

