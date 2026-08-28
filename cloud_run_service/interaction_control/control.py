"""Session admission, routing, continuity, redirection, and termination policy."""

from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Mapping, Protocol

if TYPE_CHECKING:
    from perception import PerceptionObservation, RouteResult
    from utterance_intake import UtteranceObservation

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

from .safety_composition import compose_safety_alert


class InteractionDisposition(str, Enum):
    COMPLETE = "complete"
    CONTINUE_LEARNING = "continue_learning"


@dataclass(frozen=True)
class InteractionControlRequest:
    turn_input: TurnInput
    session: Mapping[str, Any]
    bound_learner_id: str | None = None
    perception: "PerceptionObservation | None" = None
    # Utterance Intake observation — always non-None in production (Intake is
    # total by design); None only in legacy test stubs that predate the field.
    # No consumer may getattr-fallback to a private regex when this is present.
    observation: "UtteranceObservation | None" = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "session", deep_freeze(self.session))


@dataclass(frozen=True)
class InteractionDecision:
    disposition: InteractionDisposition
    text: str
    compatibility: Mapping[str, Any] | None = None
    analysis: Mapping[str, Any] | None = None
    perception_degraded: bool = False
    answer_attempt: bool = False
    continuity: "InteractionContinuity | None" = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "disposition", InteractionDisposition(self.disposition))
        if not self.text:
            raise ValueError("Interaction Decision requires text")
        if self.disposition is InteractionDisposition.COMPLETE and self.compatibility is None:
            raise ValueError("a completed interaction requires compatibility output")
        object.__setattr__(
            self,
            "compatibility",
            None if self.compatibility is None else deep_freeze(self.compatibility),
        )
        object.__setattr__(
            self,
            "analysis",
            None if self.analysis is None else deep_freeze(self.analysis),
        )

    def response_state_changes(self, answer: str) -> tuple[StateChange, ...]:
        """Let Interaction Control author post-learning continuity changes."""
        if self.continuity is None:
            return ()
        return self.continuity.response_state_changes(answer)


@dataclass(frozen=True)
class InteractionContinuity:
    turn_id: str
    learner_text: str
    prior_context: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "prior_context",
            tuple(deep_freeze(item) for item in self.prior_context),
        )

    def response_state_changes(self, answer: str) -> tuple[StateChange, ...]:
        context = [deep_thaw(item) for item in self.prior_context]
        context.append({"role": "student", "text": self.learner_text[:250]})
        if answer:
            context.append({"role": "wini", "text": answer[:250]})
        return (StateChange(
            change_id=f"{self.turn_id}:interaction:session:context:response",
            owner="interaction_control",
            scope=StateScope.SESSION,
            path=("context",),
            operation=StateOperation.SET,
            value=context[-8:],
        ),)


@dataclass(frozen=True)
class CapabilityTransition:
    """State changes authored by the capability that owns their semantics."""

    result: Any = None
    state_changes: tuple[StateChange, ...] = ()


class InteractionControlInterface(Protocol):
    """The single seam used by the Turn Coordinator and module tests."""

    def control(
        self, request: InteractionControlRequest
    ) -> ModuleOutcome[InteractionDecision]: ...


@dataclass(frozen=True)
class InteractionControlDependencies:
    """Internal legacy ports used while adjacent Feature Modules are unextracted."""

    deterministic_route: Callable[[str], Any | None]
    perception_route: Callable[[str, Mapping[str, Any]], Any | None]
    analyze: Callable[[str, str | None], Mapping[str, Any]]
    persona: Mapping[str, Any]
    want_answer: bool
    generation_backend: str
    generate_persona: Callable[[str], str]
    concept_name: Callable[[str | None], str]
    topic_candidates: Callable[[str, int], list[Any]]
    chapter_for_concept: Callable[[str | None], str | None]
    wants_different_topic: Callable[[str], bool]
    # concept_relates_to_topic removed (ticket 11): the drift guard that called it was
    # deleted in slice 04; the rule survives as prose in the handover doc only.
    # Slice 07 (2026-08-28): mode_cue signature changed from Callable[[str], str|None]
    # to Callable[[RouteResult], str|None] where the argument is now a RouteResult (observation).
    # The function reads ``route.session_control_mode`` instead of running cue regexes on text.
    mode_cue: Callable[[RouteResult], str | None]
    current_mode: Callable[[dict[str, Any]], str]
    set_mode: Callable[[Mapping[str, Any], str, str], CapabilityTransition]
    consume_mode_offer: Callable[[Mapping[str, Any], str, str], CapabilityTransition]
    consume_test_resume: Callable[[Mapping[str, Any], str, str], CapabilityTransition]
    check_frozen_test: Callable[[Mapping[str, Any], str], CapabilityTransition]
    clear_pending_assessment: Callable[[Mapping[str, Any], str], CapabilityTransition]
    log_event: Callable[[Mapping[str, Any]], None]
    notify_safety: Callable[[Mapping[str, Any]], None]
    now: Callable[[], str]
    stt_write_confidence_min: float = 0.60
    pedagogy_owns_modes: bool = False


class InteractionControl:
    """Govern how an interaction enters, redirects, continues, or ends a session."""

    _CHAPTER_TITLES = {
        "jemh101": "Real Numbers",
        "jemh102": "Polynomials",
        "jemh103": "Linear Equations",
        "jemh104": "Quadratic Equations",
        "jemh105": "Arithmetic Progressions",
        "jemh106": "Triangles",
        "jemh107": "Coordinate Geometry",
        "jemh108": "Trigonometry",
        "jemh109": "Applications of Trigonometry",
        "jemh110": "Circles",
        "jemh111": "Areas Related to Circles",
        "jemh112": "Surface Areas and Volumes",
        "jemh113": "Statistics",
        "jemh114": "Probability",
    }

    def __init__(self, dependencies: InteractionControlDependencies) -> None:
        self._dependencies = dependencies

    def control(
        self, request: InteractionControlRequest
    ) -> ModuleOutcome[InteractionDecision]:
        try:
            return self._control(request)
        except Exception as exc:
            return ModuleOutcome(
                value=None,
                failures=(FailureSignal(
                    capability="interaction_control",
                    phase="admission_and_routing",
                    severity=FailureSeverity.ERROR,
                    recoverable=False,
                    cause=f"{type(exc).__name__}: {exc}",
                    valid_outcome=False,
                    context={"turn_id": request.turn_input.turn_id},
                ),),
            )

    def _control(
        self, request: InteractionControlRequest
    ) -> ModuleOutcome[InteractionDecision]:
        bound_learner = str(request.bound_learner_id or "").strip()
        if bound_learner.lower() == "default":
            bound_learner = ""
        if bound_learner and bound_learner != request.turn_input.learner_id:
            return ModuleOutcome(
                value=None,
                failures=(FailureSignal(
                    capability="identity",
                    phase="admission_and_routing",
                    severity=FailureSeverity.FATAL,
                    recoverable=False,
                    cause="turn learner identity does not match bound state",
                    valid_outcome=False,
                    context={
                        "turn_id": request.turn_input.turn_id,
                        "requested_learner_id": request.turn_input.learner_id,
                    },
                ),),
            )
        interaction = deep_thaw(request.turn_input.interaction)
        # Ticket 11: interaction["text"] channel deleted — text now comes from the typed
        # observation (always non-None after the walking skeleton wired UtteranceIntake).
        # Fallback to interaction.get("text") removed; all producers were migrated.
        text = (
            request.observation.normalized_text
            if request.observation is not None
            else str(interaction.get("text") or "")  # legacy test stubs only
        )
        session = deep_thaw(request.session)
        starting_session = copy.deepcopy(session)
        perception = request.perception
        route = (
            perception.route
            if perception is not None and perception.source == "gate"
            else self._dependencies.deterministic_route(text)
        )
        if route is not None:
            if compose_safety_alert(
                perception_safety_alert=bool(getattr(route, "safety_alert", False))
            ):
                route.primary = "SAFETY"
                self._record_safety(request.turn_input, text, route, session)
            compatibility, failures = self._complete_nonlearning(
                request.turn_input, route, text, session
            )
            return ModuleOutcome(
                value=InteractionDecision(
                    disposition=InteractionDisposition.COMPLETE,
                    text=text,
                    compatibility=compatibility,
                ),
                state_changes=self._state_changes(
                    request.turn_input, starting_session, session
                ),
                failures=failures,
            )

        # Ticket 05: the LEARNING path gates on authorization, not the raw
        # stt_confidence float.  An UNAUTHORIZED turn produces the repair
        # screen; perception is NOT run (the gate fires first).
        from utterance_intake.observation import Authorization as _Authorization
        if (request.observation is not None
                and request.observation.authorization is _Authorization.UNAUTHORIZED):
            compatibility = self._unauthorized_repair_result(
                request.turn_input, session, request.observation,
            )
            return ModuleOutcome(value=InteractionDecision(
                disposition=InteractionDisposition.COMPLETE,
                text=text,
                compatibility=compatibility,
            ))
        # Ticket 11: trusted_observations["stt_confidence"] channel deleted.
        # _low_confidence_result is now dead code (its only caller above was removed).
        # Authorization.UNAUTHORIZED (ticket 05) covers what stt_confidence used to gate.

        pending = self._consume_pending_shift(
            text, session, request.turn_input.turn_id
        )
        if pending is not None:
            text, completed = pending
            if completed is not None:
                return ModuleOutcome(
                    value=InteractionDecision(
                        disposition=InteractionDisposition.COMPLETE,
                        text=text,
                        compatibility=self._shift_result(
                            request.turn_input, text, session, **completed
                        ),
                    ),
                    state_changes=self._state_changes(
                        request.turn_input, starting_session, session
                    ),
                )

        pending_mode = None
        if not self._dependencies.pedagogy_owns_modes:
            pending_mode = self._consume_pending_mode_control(
                text, session, request.turn_input.turn_id
            )
        if pending_mode is not None:
            return ModuleOutcome(
                value=InteractionDecision(
                    disposition=InteractionDisposition.COMPLETE,
                    text=text,
                    compatibility=self._shift_result(
                        request.turn_input, text, session, **pending_mode
                    ),
                ),
                state_changes=self._state_changes(
                    request.turn_input, starting_session, session
                ),
            )

        route = (
            perception.route
            if perception is not None
            else self._dependencies.perception_route(text, session)
        )
        perception_degraded = bool(
            perception.perception_degraded
            if perception is not None
            else getattr(route, "perception_degraded", False)
        )
        if route is not None and compose_safety_alert(
            perception_safety_alert=bool(getattr(route, "safety_alert", False))
        ):
            route.primary = "SAFETY"
            self._record_safety(request.turn_input, text, route, session)
        if (
            not self._dependencies.pedagogy_owns_modes
            and
            route is not None
            and str(route.primary) == "SESSION_CONTROL"
            and not bool(getattr(route, "safety_alert", False))
        ):
            stopped = self._maybe_stop_mode(
                text, session, request.turn_input.turn_id, route=route
            )
            if stopped is not None:
                return ModuleOutcome(
                    value=InteractionDecision(
                        disposition=InteractionDisposition.COMPLETE,
                        text=text,
                        compatibility=self._shift_result(
                            request.turn_input, text, session, **stopped
                        ),
                    ),
                    state_changes=self._state_changes(
                        request.turn_input, starting_session, session
                    ),
                )
        declined = self._maybe_decline_topic(
            text, session, request.turn_input.turn_id, route=route
        )
        if declined is not None:
            return ModuleOutcome(
                value=InteractionDecision(
                    disposition=InteractionDisposition.COMPLETE,
                    text=text,
                    compatibility=self._shift_result(
                        request.turn_input, text, session, **declined
                    ),
                ),
                state_changes=self._state_changes(
                    request.turn_input, starting_session, session
                ),
            )
        pedagogical_mode_control = (
            self._dependencies.pedagogy_owns_modes
            and self._dependencies.mode_cue(route) is not None
        )
        is_also_learning = bool(
            getattr(perception, "also_learning", False)
            or getattr(route, "also_learning", False)
        )
        if (route is not None and str(route.primary) != "LEARNING"
                and not pedagogical_mode_control
                and not (is_also_learning and str(route.primary) in {"SOCIAL", "EMOTIONAL"})):
            compatibility, failures = self._complete_nonlearning(
                request.turn_input, route, text, session
            )
            return ModuleOutcome(
                value=InteractionDecision(
                    disposition=InteractionDisposition.COMPLETE,
                    text=text,
                    compatibility=compatibility,
                ),
                state_changes=self._state_changes(
                    request.turn_input, starting_session, session
                ),
                failures=failures,
            )
        resumed = self._resume_session(session, request.turn_input.turn_id)
        if resumed is not None:
            return ModuleOutcome(
                value=InteractionDecision(
                    disposition=InteractionDisposition.COMPLETE,
                    text=text,
                    compatibility=self._shift_result(
                        request.turn_input, text, session, **resumed
                    ),
                ),
                state_changes=self._state_changes(
                    request.turn_input, starting_session, session
                ),
            )
        if route is not None:
            session["steer_streak"] = 0
        # Ticket 11: trusted_observations["stt_confidence"] deleted.
        # precomputed_analysis (coordinator cache) still lives in trusted_observations.
        precomputed_analysis = deep_thaw(
            request.turn_input.trusted_observations
        ).get("precomputed_analysis")
        analysis = (
            precomputed_analysis
            if precomputed_analysis is not None
            else (
                deep_thaw(perception.analysis)
                if perception is not None
                else self._dependencies.analyze(text, session.get("current_concept"))
            )
        )
        allow_shift = bool(interaction.get("allow_topic_shift", True))
        if allow_shift:
            shifted = self._maybe_topic_shift(
                text, analysis, session, request.turn_input.turn_id, route=route
            )
            if shifted is not None:
                text, analysis, completed = shifted
                if completed is not None:
                    return ModuleOutcome(
                        value=InteractionDecision(
                            disposition=InteractionDisposition.COMPLETE,
                            text=text,
                            compatibility=self._shift_result(
                                request.turn_input, text, session, **completed
                            ),
                        ),
                        state_changes=self._state_changes(
                            request.turn_input, starting_session, session
                        ),
                    )
        analysis = deep_thaw(analysis)
        concept = dict(analysis.get("concept") or {})
        primary = concept.get("concept_id")
        # Drift guard deleted (ticket 04 / issue 12): a confident resolution to an
        # unrelated concept is now accepted and session["current_concept"] follows
        # it. This is a deliberate behaviour change recorded in issue 15; the
        # concept resolver (handover doc) is the future owner of topic-continuity
        # decisions. ReferenceReading on observation is supplied and unread here
        # until that layer exists.
        test_state = session.get("test_state")
        test_locked = test_state is not None and test_state.get("phase") not in (None, "done")
        if primary and not test_locked:
            session["current_concept"] = primary
        return ModuleOutcome(
            value=InteractionDecision(
                disposition=InteractionDisposition.CONTINUE_LEARNING,
                text=text,
                analysis=analysis,
                perception_degraded=perception_degraded,
                answer_attempt=bool(
                    perception.answer_attempt
                    if perception is not None
                    else getattr(route, "answer_attempt", False)
                ),
                continuity=InteractionContinuity(
                    turn_id=request.turn_input.turn_id,
                    learner_text=text,
                    prior_context=tuple(session.get("context") or ()),
                ),
            ),
            state_changes=self._state_changes(
                request.turn_input, starting_session, session
            ),
        )

    def _resume_session(
        self, session: dict[str, Any], turn_id: str
    ) -> dict[str, str] | None:
        if session.get("status") not in {"paused", "ended"} and not session.get(
            "break_requested"
        ):
            return None
        session["status"] = "active"
        session.pop("break_requested", None)
        session.pop("leave_requests", None)
        if self._dependencies.pedagogy_owns_modes:
            return None
        resume = self._apply_capability_transition(
            session, self._dependencies.check_frozen_test(session, turn_id)
        )
        if not resume:
            return None
        return {
            "reply": (
                "Welcome back! You were in the middle of a test — "
                f"question {resume['graded'] + 1} of {resume['n']}. "
                "Want to continue it?"
            ),
            "action": "TEST_RESUME_OFFER",
            "reason": (
                f"frozen test found ({resume['graded']}/{resume['n']} graded); "
                "offering resume"
            ),
        }

    def _consume_pending_mode_control(
        self, text: str, session: dict[str, Any], turn_id: str
    ) -> dict[str, str] | None:
        if session.get("pending_mode_offer"):
            decision = self._apply_capability_transition(
                session,
                self._dependencies.consume_mode_offer(session, text, turn_id),
            )
            if decision is not None and decision[0] == "declined":
                return {
                    "reply": "No problem — let's keep learning.",
                    "action": "MODE_OFFER_DECLINED",
                    "reason": "practice offer declined; staying in EXPLAIN",
                }
        if session.get("pending_test_resume"):
            decision = self._apply_capability_transition(
                session,
                self._dependencies.consume_test_resume(session, text, turn_id),
            )
            if decision is not None and decision[0] == "resume":
                test_state = session.get("test_state") or {}
                graded = len(test_state.get("results", []))
                count = int(test_state.get("n", 5))
                reply = (
                    f"Let's pick up where we left off — question {graded + 1} of {count}."
                )
                pending_question = (session.get("pending_check") or {}).get("question")
                if pending_question:
                    reply += f" Here it is again: {pending_question}"
                return {
                    "reply": reply,
                    "action": "TEST_RESUME",
                    "reason": (
                        f"frozen test resumed by student ({graded}/{count} graded)"
                    ),
                }
            if decision is not None and decision[0] == "abandon":
                return {
                    "reply": "No problem — let's keep learning.",
                    "action": "TEST_RESUME_DECLINED",
                    "reason": "frozen test abandoned by student",
                }
        return None

    def _maybe_decline_topic(
        self, text: str, session: dict[str, Any], turn_id: str, route: Any = None
    ) -> dict[str, str] | None:
        if not self._dependencies.wants_different_topic(text):
            return None
        # Slice 07: mode_cue now reads from the route observation (not text).
        if self._dependencies.mode_cue(route) in {"STOP", "TEST", "PRACTICE"}:
            return None
        test_state = session.get("test_state")
        if test_state is not None and test_state.get("phase") not in (None, "done"):
            return None
        # Slice 07: topic_phrasing from the route is the sole source; regex arm deleted.
        span = getattr(route, "topic_phrasing", None)
        if span:
            candidates = self._dependencies.topic_candidates(span, 3)
            if candidates:
                concept_id, _name, similarity = candidates[0]
                if concept_id != session.get("current_concept") and similarity >= 0.45:
                    return None
        current_chapter = self._dependencies.chapter_for_concept(
            session.get("current_concept")
        )
        titles = [
            title
            for chapter, title in self._CHAPTER_TITLES.items()
            if chapter != current_chapter
        ]
        if not titles:
            return None
        count = min(4, len(titles))
        step = max(1, len(titles) // count)
        menu = [titles[index] for index in range(0, len(titles), step)][:count]
        listed = (
            ", ".join(menu[:-1]) + ", or " + menu[-1]
            if len(menu) > 1
            else menu[0]
        )
        reply = (
            f"Sure — we don't have to stay on {self._friendly_concept(session)}. "
            f"We could do {listed}. Which one would you like?"
        )
        self._apply_capability_transition(
            session,
            self._dependencies.clear_pending_assessment(session, turn_id),
        )
        session["steer_streak"] = 0
        return {
            "reply": reply,
            "action": "TOPIC_MENU",
            "reason": "decline-of-topic, no alternative named; offered chapter menu",
        }

    def _maybe_topic_shift(
        self,
        text: str,
        analysis: Mapping[str, Any],
        session: dict[str, Any],
        turn_id: str,
        route: Any = None,
    ) -> tuple[str, Mapping[str, Any], dict[str, str] | None] | None:
        test_state = session.get("test_state")
        if test_state is not None and test_state.get("phase") != "done":
            return None
        # Slice 07: mode_cue now reads from the route observation (not text).
        if self._dependencies.mode_cue(route) is not None:
            return None
        concept = analysis.get("concept") or {}
        primary = concept.get("concept_id")
        current = session.get("current_concept")
        # Slice 07: topic_phrasing from the route is the sole source; regex arms deleted.
        span = getattr(route, "topic_phrasing", None)
        graded_pending = bool(session.get("pending_check") or session.get("pending_hope"))
        bare = (span is not None) and not graded_pending
        if not span and not bare:
            return None
        if (
            primary
            and not concept.get("abstained")
            and primary != current
            and float(concept.get("concept_confidence") or 0.0) >= 0.6
        ):
            return None
        target_text = span or str(analysis.get("normalized_text") or "")
        candidates = self._dependencies.topic_candidates(target_text, 3)
        if not candidates:
            return None
        concept_id, name, similarity = candidates[0]
        if concept_id == current and similarity >= 0.25:
            return None
        if span and similarity >= 0.45:
            session["current_concept"] = concept_id
            self._apply_capability_transition(
                session,
                self._dependencies.clear_pending_assessment(session, turn_id),
            )
            self._dependencies.log_event({
                "ts": self._dependencies.now(),
                "loop": "tutor_loop_v4",
                "question": text,
                "action": "TOPIC_SHIFT",
                "action_reason": (
                    f"explicit request grounded to {concept_id} (sim {similarity:.2f})"
                ),
                "need": "none",
                "signals": [],
                "answer": None,
            })
            rewritten = f"I want to learn about {name}"
            return (
                rewritten,
                self._dependencies.analyze(rewritten, concept_id),
                None,
            )
        current_name = self._friendly_concept(session)
        if similarity >= 0.25:
            reply = (
                f"We're doing {current_name} right now. Do you want to switch to "
                f"{name}? Say yes or no."
            )
        else:
            asked = span or target_text
            reply = (
                f"Hmm, '{asked}' isn't one of our Class 10 topics. The closest I "
                f"have is {name} — want to try that? Or say no to continue {current_name}."
            )
        session["pending_shift"] = {"concept_id": concept_id, "name": name}
        return text, analysis, {
            "reply": reply,
            "action": "TOPIC_SHIFT_CONFIRM",
            "reason": (
                f"shift request; top match {concept_id} (sim {similarity:.2f})"
            ),
        }

    def _unauthorized_repair_result(
        self,
        turn_input: TurnInput,
        session: Mapping[str, Any],
        observation: "UtteranceObservation",
    ) -> dict[str, Any]:
        """Ticket 05: produce the repair screen from the observation's
        ``repair_choices`` — the one sanctioned export.  The response layer
        reads ``repair_choices``; nothing reads ``utterance.alternates``.
        The learner always chooses; nothing auto-selects an alternate.
        Ticket 11: text now comes from observation.normalized_text (interaction["text"] deleted)."""
        interaction = deep_thaw(turn_input.interaction)
        text = observation.normalized_text
        pending = session.get("pending_check") or {}
        choices = list(observation.transcript.repair_choices)
        causes = [c.value for c in observation.transcript.causes]

        if choices:
            options = " / ".join(f'"{c}"' for c in choices[:3])
            reply = f"I'm not sure I heard that right. Did you say {options}? Pick one, or say something else."
        else:
            reply = "I'm not sure I heard that right. Please say that again"
            if pending.get("question"):
                reply += f" for this question: {pending['question']}"
            reply += "."

        self._dependencies.log_event({
            "ts": self._dependencies.now(),
            "loop": "tutor_loop_v4",
            "question": text,
            "action": "REPAIR_SCREEN",
            "action_reason": (
                f"unauthorized transcript (causes: {', '.join(causes)}); "
                "repair screen presented"
            ),
            "need": "none",
            "signals": [],
            "answer": reply,
        })
        return {
            "action": "REPAIR_SCREEN",
            "action_reason": f"unauthorized transcript; causes: {', '.join(causes)}",
            "need": "none",
            "shadow": None,
            "concept": {
                "concept_id": session.get("current_concept"),
                "concept_confidence": 0.0,
                "abstained": True,
            },
            "signals": [],
            "cognitive_update": {},
            "n_evidence": 0,
            "bridge_ids": [],
            "writeback": None,
            "hope_update": None,
            "pending_check": pending.get("id"),
            "pending_hope": None,
            "answer_budget": interaction.get("answer_budget"),
            "pace": copy.deepcopy(session.get("pace", {})),
            "display": [],
            "session_ended": False,
            "answer": reply,
            "answer_source": "scripted",
            "gen_backend": None,
            "repair_choices": choices,
        }

    def _maybe_stop_mode(
        self, text: str, session: dict[str, Any], turn_id: str, route: Any = None
    ) -> dict[str, str] | None:
        # Slice 07: mode_cue now reads from the route observation (not text).
        if self._dependencies.mode_cue(route) != "STOP":
            return None
        previous = self._dependencies.current_mode(session)
        if previous == "EXPLAIN" and not session.get("test_state"):
            return None
        self._apply_capability_transition(
            session,
            self._dependencies.set_mode(session, "EXPLAIN", turn_id),
        )
        self._apply_capability_transition(
            session,
            self._dependencies.clear_pending_assessment(session, turn_id),
        )
        return {
            "reply": (
                "Okay, we'll stop the questions for now. Let's keep learning — "
                "ask me anything about maths."
            ),
            "action": "MODE_STOP",
            "reason": f"stop cue: {previous} -> EXPLAIN (keep learning)",
        }

    def _consume_pending_shift(
        self, text: str, session: dict[str, Any], turn_id: str
    ) -> tuple[str, dict[str, str] | None] | None:
        if not session.get("pending_shift"):
            return None
        target = session.pop("pending_shift") or {}
        if not target.get("concept_id"):
            return None
        normalized = (text or "").strip().lower()
        words = normalized.split()
        if re.match(r"^(yes|yeah|ya|yep|ok(ay)?|sure|haan|ha)\b", normalized) and len(words) <= 3:
            session["current_concept"] = target["concept_id"]
            self._apply_capability_transition(
                session,
                self._dependencies.clear_pending_assessment(session, turn_id),
            )
            self._dependencies.log_event({
                "ts": self._dependencies.now(),
                "loop": "tutor_loop_v4",
                "question": text,
                "action": "TOPIC_SHIFT",
                "action_reason": f"confirmed switch to {target['concept_id']}",
                "need": "none",
                "signals": [],
                "answer": None,
            })
            return f"I want to learn about {target['name']}", None
        if re.match(r"^(no|nope|nah|not now)\b", normalized) and len(words) <= 3:
            reply = f"No problem — let's continue with {self._friendly_concept(session)}."
            return text, {
                "reply": reply,
                "action": "TOPIC_SHIFT_DECLINED",
                "reason": "shift offer declined; continuing current topic",
            }
        return None

    def _shift_result(
        self,
        turn_input: TurnInput,
        text: str,
        session: dict[str, Any],
        *,
        reply: str,
        action: str,
        reason: str,
    ) -> dict[str, Any]:
        context = list(session.get("context") or [])
        context.extend((
            {"role": "student", "text": text[:250]},
            {"role": "wini", "text": reply[:250]},
        ))
        session["context"] = context[-8:]
        self._dependencies.log_event({
            "ts": self._dependencies.now(),
            "loop": "tutor_loop_v4",
            "question": text,
            "action": action,
            "action_reason": reason,
            "need": "none",
            "signals": [],
            "answer": reply,
        })
        pending_check = session.get("pending_check") or {}
        return {
            "action": action,
            "action_reason": reason,
            "need": "none",
            "shadow": None,
            "concept": {
                "concept_id": session.get("current_concept"),
                "concept_confidence": 0.0,
                "abstained": True,
            },
            "signals": [],
            "cognitive_update": {},
            "n_evidence": 0,
            "bridge_ids": [],
            "writeback": None,
            "hope_update": None,
            "pending_check": pending_check.get("id"),
            "pending_hope": None,
            "answer_budget": deep_thaw(turn_input.interaction).get("answer_budget"),
            "pace": copy.deepcopy(session.get("pace", {})),
            "display": [],
            "session_ended": False,
            "answer": reply,
            "answer_source": "scripted",
            "gen_backend": None,
        }

    def _record_safety(
        self,
        turn_input: TurnInput,
        text: str,
        route: Any,
        session: dict[str, Any],
    ) -> None:
        record = {
            "ts": self._dependencies.now(),
            "learner_id": turn_input.learner_id,
            "utterance_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "utterance_length": len(text),
            "safety_tier": int(getattr(route, "safety_tier", None) or 2),
            "safety_category": getattr(route, "safety_category", None)
            or "safety_concern",
            "source": getattr(route, "source", "unknown"),
            "handled": "scripted_reply+persisted_alert+supervisor_notify",
        }
        session["safety_alert"] = record
        session.setdefault("__learner_safety_alerts__", []).append(record)
        self._dependencies.notify_safety(copy.deepcopy(record))

    def _complete_nonlearning(
        self,
        turn_input: TurnInput,
        route: Any,
        text: str,
        session: dict[str, Any],
    ) -> tuple[dict[str, Any], tuple[FailureSignal, ...]]:
        intent = str(route.primary)
        if intent == "SESSION_CONTROL":
            self._apply_session_control(session, text)
        reply, reply_source, failures = self._nonlearning_reply(route, text, session)
        context = list(session.get("context") or [])
        context.append({"role": "student", "text": text[:250]})
        if reply:
            context.append({"role": "wini", "text": reply[:250]})
        session["context"] = context[-8:]
        pending_check = session.get("pending_check") or {}
        pending_hope = session.get("pending_hope") or {}
        result = {
            "action": intent,
            "action_reason": getattr(route, "reason", ""),
            "need": "none",
            "shadow": None,
            "concept": {
                "concept_id": getattr(route, "concept_id", None),
                "concept_confidence": getattr(route, "concept_confidence", 0.0),
                "abstained": getattr(route, "concept_id", None) is None,
            },
            "signals": [],
            "cognitive_update": {},
            "n_evidence": 0,
            "bridge_ids": [],
            "writeback": None,
            "hope_update": None,
            "pending_check": pending_check.get("id"),
            "pending_hope": pending_hope.get("signal"),
            "answer_budget": deep_thaw(turn_input.interaction).get("answer_budget"),
            "pace": copy.deepcopy(session.get("pace", {})),
            "display": [],
            "answer": reply,
            "intent": intent,
            "route_source": getattr(route, "source", ""),
            "answer_source": reply_source,
            "gen_backend": (
                self._dependencies.generation_backend
                if reply_source not in {"scripted", "farewell", "canned"}
                else None
            ),
            "session_ended": session.get("status") == "ended",
        }
        self._dependencies.log_event({
            "ts": self._dependencies.now(),
            "loop": "tutor_loop_v4",
            "question": "[REDACTED_SAFETY_UTTERANCE]"
            if bool(getattr(route, "safety_alert", False))
            else text,
            "log_tier": "general_redacted"
            if bool(getattr(route, "safety_alert", False))
            else "general",
            "action": intent,
            "action_reason": getattr(route, "reason", ""),
            "need": "none",
            "intent": intent,
            "route_source": getattr(route, "source", ""),
            "safety_alert": bool(getattr(route, "safety_alert", False)),
            "concept": result["concept"],
            "signals": [],
            "answer": reply,
            "answer_source": reply_source,
        })
        return result, failures

    def _nonlearning_reply(
        self, route: Any, text: str, session: dict[str, Any]
    ) -> tuple[str, str, tuple[FailureSignal, ...]]:
        spec = (
            self._dependencies.persona.get("intents", {}).get(str(route.primary), {})
        )
        if "scripted" in spec:
            return str(spec["scripted"]), "scripted", ()
        canned_values = spec.get("canned") or []
        canned = ""
        if canned_values:
            canned = str(canned_values[0]).replace(
                "{concept}", self._friendly_concept(session)
            )
        if str(route.primary) == "SESSION_CONTROL" and session.get("status") == "ended":
            return str(spec.get("farewell") or canned), "farewell", ()
        if not self._dependencies.want_answer:
            return canned, "canned", ()
        try:
            generated = self._dependencies.generate_persona(
                self._persona_prompt(route, text, session, spec)
            )
        except Exception as exc:
            return canned, "canned", (FailureSignal(
                capability="interaction_control",
                phase="non_learning_routing",
                severity=FailureSeverity.DEGRADED,
                recoverable=True,
                cause=f"{type(exc).__name__}: {exc}",
                valid_outcome=True,
                context={"intent": str(route.primary)},
            ),)
        if generated:
            return generated, self._dependencies.generation_backend, ()
        return canned, "canned", (FailureSignal(
            capability="interaction_control",
            phase="non_learning_routing",
            severity=FailureSeverity.DEGRADED,
            recoverable=True,
            cause="empty persona generation",
            valid_outcome=True,
            context={"intent": str(route.primary)},
        ),)

    @staticmethod
    def _apply_session_control(session: dict[str, Any], text: str) -> None:
        explicit_end = re.search(
            r"\b(bye|goodbye|good ?night|see you|that'?s all|i'?m done|we'?re done|"
            r"stop for (today|now)|end (the )?(session|lesson)|finish for|"
            r"i (want|have|need) to go(?! (over|through|back|on))|let me go|going now)\b",
            (text or "").lower(),
        )
        leave_requests = int(session.get("leave_requests", 0)) + 1
        session["leave_requests"] = leave_requests
        session["status"] = "ended" if explicit_end or leave_requests >= 2 else "paused"
        session["break_requested"] = True

    def _persona_prompt(
        self, route: Any, text: str, session: dict[str, Any], spec: Mapping[str, Any]
    ) -> str:
        persona = self._dependencies.persona
        instruction = spec.get(
            "instruction", "Reply warmly and gently steer back to maths."
        )
        intent = str(route.primary)
        if intent == "SESSION_CONTROL":
            steer = (
                "Do NOT ask any question and do NOT mention a sum or problem to try. "
                "Accept the pause warmly in one sentence."
            )
        elif intent in {"SOCIAL", "EMOTIONAL"}:
            streak = int(session.get("steer_streak", 0))
            if streak >= 2:
                steer = (
                    "Do NOT mention maths, a topic, a sum, or a problem to try. Just "
                    "respond warmly to what the child said, in one short sentence."
                )
                session["steer_streak"] = 0
            else:
                session["steer_streak"] = streak + 1
                steer = (
                    "If you steer back to maths, the current topic is: "
                    f"{self._friendly_concept(session)}."
                )
        else:
            steer = (
                "If you steer back to maths, the current topic is: "
                f"{self._friendly_concept(session)}."
            )
        history = list(session.get("context") or [])[-6:]
        recent = ""
        if history:
            recent = (
                "RECENT CONVERSATION (use it; never ask about something it already tells you):\n"
                + "\n".join(
                    f"{item['role'].upper()}: {item['text']}" for item in history
                )
                + "\n\n"
            )
        return (
            f"{persona.get('identity', '')}\n{persona.get('style', '')}\n"
            f"Situation: {instruction}\n"
            f"{steer}\n\n"
            f"{recent}CHILD SAID: {text}\n\nWINI (one or two short spoken sentences):"
        )

    def _friendly_concept(self, session: Mapping[str, Any]) -> str:
        concept_id = session.get("current_concept")
        return (
            self._dependencies.concept_name(str(concept_id))
            if concept_id
            else "our maths"
        )

    @staticmethod
    def _apply_capability_transition(
        session: dict[str, Any], transition: CapabilityTransition
    ) -> Any:
        authored = session.setdefault("__capability_state_changes__", [])
        for change in transition.state_changes:
            if change.scope is not StateScope.SESSION or len(change.path) != 1:
                raise ValueError("capability transition must target one session field")
            if change.owner == "interaction_control":
                raise ValueError("adjacent capability cannot author Interaction Control state")
            key = change.path[0]
            if change.operation is StateOperation.SET:
                session[key] = deep_thaw(change.value)
            elif change.operation is StateOperation.DELETE:
                session.pop(key, None)
            else:
                raise ValueError("capability transition must SET or DELETE session state")
            authored.append(change)
        return transition.result

    def _state_changes(
        self,
        turn_input: TurnInput,
        starting_session: Mapping[str, Any],
        session: dict[str, Any],
    ) -> tuple[StateChange, ...]:
        learner_alerts = session.pop("__learner_safety_alerts__", [])
        capability_changes = tuple(session.pop("__capability_state_changes__", []))
        capability_paths = {change.path for change in capability_changes}
        changes: list[StateChange] = []
        for index, alert in enumerate(learner_alerts):
            changes.append(StateChange(
                change_id=f"{turn_input.turn_id}:interaction:safety:{index}",
                owner="interaction_control",
                scope=StateScope.LEARNER,
                path=("safety_alerts",),
                operation=StateOperation.APPEND,
                value=alert,
                idempotency_key=f"{turn_input.turn_id}:safety:{index}",
            ))
        keys = set(starting_session) | set(session)
        for key in sorted(keys):
            if (key,) in capability_paths:
                continue
            before = starting_session.get(key, _MISSING)
            after = session.get(key, _MISSING)
            if before == after:
                continue
            operation = StateOperation.DELETE if after is _MISSING else StateOperation.SET
            changes.append(StateChange(
                change_id=f"{turn_input.turn_id}:interaction:session:{key}",
                owner=self._owner_for_session_path(key),
                scope=StateScope.SESSION,
                path=(key,),
                operation=operation,
                value=None if after is _MISSING else after,
            ))
        changes.extend(capability_changes)
        return tuple(changes)

    @staticmethod
    def _owner_for_session_path(key: str) -> str:
        if key in {
            "pending_check",
            "pending_hope",
            "mode",
            "test_state",
            "practice_plan",
            "practice_state",
            "pending_mode_offer",
            "pending_test_resume",
        }:
            raise ValueError(f"{key} must be authored by its owning capability port")
        return "interaction_control"


_MISSING = object()
