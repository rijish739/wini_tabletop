"""Session admission, routing, continuity, redirection, and termination policy."""

from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Protocol

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


class InteractionDisposition(str, Enum):
    COMPLETE = "complete"
    CONTINUE_LEARNING = "continue_learning"


@dataclass(frozen=True)
class InteractionControlRequest:
    turn_input: TurnInput
    session: Mapping[str, Any]
    bound_learner_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "session", deep_freeze(self.session))


@dataclass(frozen=True)
class InteractionDecision:
    disposition: InteractionDisposition
    text: str
    compatibility: Mapping[str, Any] | None = None
    analysis: Mapping[str, Any] | None = None
    perception_uncertain: bool = False
    answer_attempt: bool = False

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
    extract_topic_request: Callable[[str], str | None]
    is_bare_topic: Callable[[str], bool]
    wants_different_topic: Callable[[str], bool]
    concept_relates_to_topic: Callable[[str, str], bool]
    mode_cue: Callable[[str], str | None]
    current_mode: Callable[[dict[str, Any]], str]
    set_mode: Callable[[dict[str, Any], str], None]
    consume_mode_offer: Callable[[dict[str, Any], str], Any]
    consume_test_resume: Callable[[dict[str, Any], str], Any]
    log_event: Callable[[Mapping[str, Any]], None]
    notify_safety: Callable[[Mapping[str, Any]], None]
    now: Callable[[], str]
    stt_write_confidence_min: float = 0.60


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
        text = str(interaction.get("text") or "")
        session = deep_thaw(request.session)
        starting_session = copy.deepcopy(session)
        route = self._dependencies.deterministic_route(text)
        if route is not None:
            if bool(getattr(route, "safety_alert", False)):
                route.primary = "SAFETY"
                self._record_safety(request.turn_input, text, route, session)
            compatibility = self._complete_nonlearning(
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
            )

        trusted = deep_thaw(request.turn_input.trusted_observations)
        stt_confidence = trusted.get("stt_confidence")
        stt_confidence = 1.0 if stt_confidence is None else max(
            0.0, min(1.0, float(stt_confidence))
        )
        if stt_confidence < self._dependencies.stt_write_confidence_min:
            compatibility = self._low_confidence_result(
                request.turn_input, session, stt_confidence
            )
            return ModuleOutcome(value=InteractionDecision(
                disposition=InteractionDisposition.COMPLETE,
                text=text,
                compatibility=compatibility,
            ))

        pending = self._consume_pending_shift(text, session)
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

        pending_mode = self._consume_pending_mode_control(text, session)
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

        route = self._dependencies.perception_route(text, session)
        perception_uncertain = bool(getattr(route, "uncertain", False))
        if route is not None and bool(getattr(route, "safety_alert", False)):
            route.primary = "SAFETY"
            self._record_safety(request.turn_input, text, route, session)
        if (
            route is not None
            and str(route.primary) == "SESSION_CONTROL"
            and not bool(getattr(route, "safety_alert", False))
        ):
            stopped = self._maybe_stop_mode(text, session)
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
        declined = self._maybe_decline_topic(text, session)
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
        if route is not None and str(route.primary) != "LEARNING":
            compatibility = self._complete_nonlearning(
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
            )
        if route is not None:
            session["steer_streak"] = 0
        analysis = self._dependencies.analyze(
            text, session.get("current_concept")
        )
        allow_shift = bool(interaction.get("allow_topic_shift", True))
        if allow_shift:
            shifted = self._maybe_topic_shift(text, analysis, session)
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
        current = session.get("current_concept")
        if (
            current
            and primary
            and primary != current
            and self._is_anaphoric_followup(text)
            and not self._dependencies.concept_relates_to_topic(primary, current)
        ):
            concept["concept_id"] = current
            analysis["concept"] = concept
            primary = current
        test_state = session.get("test_state")
        test_locked = test_state is not None and test_state.get("phase") not in (None, "done")
        if primary and not test_locked:
            session["current_concept"] = primary
        return ModuleOutcome(
            value=InteractionDecision(
                disposition=InteractionDisposition.CONTINUE_LEARNING,
                text=text,
                analysis=analysis,
                perception_uncertain=perception_uncertain,
                answer_attempt=bool(getattr(route, "answer_attempt", False)),
            ),
            state_changes=self._state_changes(
                request.turn_input, starting_session, session
            ),
        )

    def _consume_pending_mode_control(
        self, text: str, session: dict[str, Any]
    ) -> dict[str, str] | None:
        if session.get("pending_mode_offer"):
            decision = self._dependencies.consume_mode_offer(session, text)
            if decision is not None and decision[0] == "declined":
                return {
                    "reply": "No problem — let's keep learning.",
                    "action": "MODE_OFFER_DECLINED",
                    "reason": "practice offer declined; staying in EXPLAIN",
                }
        if session.get("pending_test_resume"):
            decision = self._dependencies.consume_test_resume(session, text)
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
        self, text: str, session: dict[str, Any]
    ) -> dict[str, str] | None:
        if not self._dependencies.wants_different_topic(text):
            return None
        if self._dependencies.mode_cue(text) in {"STOP", "TEST", "PRACTICE"}:
            return None
        test_state = session.get("test_state")
        if test_state is not None and test_state.get("phase") not in (None, "done"):
            return None
        span = self._dependencies.extract_topic_request(text)
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
        session.pop("pending_check", None)
        session.pop("pending_hope", None)
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
    ) -> tuple[str, Mapping[str, Any], dict[str, str] | None] | None:
        test_state = session.get("test_state")
        if test_state is not None and test_state.get("phase") != "done":
            return None
        if self._dependencies.mode_cue(text) is not None:
            return None
        concept = analysis.get("concept") or {}
        primary = concept.get("concept_id")
        current = session.get("current_concept")
        span = self._dependencies.extract_topic_request(text)
        graded_pending = bool(session.get("pending_check") or session.get("pending_hope"))
        bare = self._dependencies.is_bare_topic(
            str(analysis.get("normalized_text") or "")
        ) and not graded_pending
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
            session.pop("pending_check", None)
            session.pop("pending_hope", None)
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

    @staticmethod
    def _is_anaphoric_followup(text: str) -> bool:
        value = (text or "").strip()
        if not value or len(value.split()) > 12:
            return False
        return bool(re.search(r"\b(this|that|it|these|those|the same|here)\b", value, re.I))

    def _low_confidence_result(
        self,
        turn_input: TurnInput,
        session: Mapping[str, Any],
        stt_confidence: float,
    ) -> dict[str, Any]:
        interaction = deep_thaw(turn_input.interaction)
        text = str(interaction.get("text") or "")
        pending = session.get("pending_check") or {}
        reply = "I may have heard that wrong. Please say that again"
        if pending.get("question"):
            reply += f" for this question: {pending['question']}"
        else:
            reply += "."
        self._dependencies.log_event({
            "ts": self._dependencies.now(),
            "loop": "tutor_loop_v4",
            "question": text,
            "action": "CONFIRM_LOW_CONFIDENCE",
            "action_reason": (
                f"STT confidence {stt_confidence:.3f} below write floor; "
                "no learning write"
            ),
            "need": "none",
            "signals": [],
            "answer": reply,
        })
        return {
            "action": "CONFIRM_LOW_CONFIDENCE",
            "action_reason": "low STT confidence; no learning write",
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
        }

    def _maybe_stop_mode(
        self, text: str, session: dict[str, Any]
    ) -> dict[str, str] | None:
        if self._dependencies.mode_cue(text) != "STOP":
            return None
        previous = self._dependencies.current_mode(session)
        if previous == "EXPLAIN" and not session.get("test_state"):
            return None
        self._dependencies.set_mode(session, "EXPLAIN")
        session.pop("pending_check", None)
        session.pop("pending_hope", None)
        return {
            "reply": (
                "Okay, we'll stop the questions for now. Let's keep learning — "
                "ask me anything about maths."
            ),
            "action": "MODE_STOP",
            "reason": f"stop cue: {previous} -> EXPLAIN (keep learning)",
        }

    def _consume_pending_shift(
        self, text: str, session: dict[str, Any]
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
            session.pop("pending_check", None)
            session.pop("pending_hope", None)
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
    ) -> dict[str, Any]:
        intent = str(route.primary)
        if intent == "SESSION_CONTROL":
            self._apply_session_control(session, text)
        reply, reply_source = self._nonlearning_reply(route, text, session)
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
        return result

    def _nonlearning_reply(
        self, route: Any, text: str, session: dict[str, Any]
    ) -> tuple[str, str]:
        spec = (
            self._dependencies.persona.get("intents", {}).get(str(route.primary), {})
        )
        if "scripted" in spec:
            return str(spec["scripted"]), "scripted"
        canned_values = spec.get("canned") or []
        canned = ""
        if canned_values:
            canned = str(canned_values[0]).replace(
                "{concept}", self._friendly_concept(session)
            )
        if str(route.primary) == "SESSION_CONTROL" and session.get("status") == "ended":
            return str(spec.get("farewell") or canned), "farewell"
        if not self._dependencies.want_answer:
            return canned, "canned"
        try:
            generated = self._dependencies.generate_persona(
                self._persona_prompt(route, text, session, spec)
            )
        except Exception:
            generated = ""
        return (
            (generated, self._dependencies.generation_backend)
            if generated
            else (canned, "canned")
        )

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

    def _state_changes(
        self,
        turn_input: TurnInput,
        starting_session: Mapping[str, Any],
        session: dict[str, Any],
    ) -> tuple[StateChange, ...]:
        learner_alerts = session.pop("__learner_safety_alerts__", [])
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
        return tuple(changes)

    @staticmethod
    def _owner_for_session_path(key: str) -> str:
        if key in {"pending_check", "pending_hope"}:
            return "assessment_evidence"
        if key in {
            "mode",
            "test_state",
            "practice_plan",
            "practice_state",
            "pending_mode_offer",
            "pending_test_resume",
        }:
            return "pedagogy"
        return "interaction_control"


_MISSING = object()
