from __future__ import annotations

import copy
import unittest
from dataclasses import dataclass

from interaction_control import (
    InteractionControl,
    InteractionControlDependencies,
    InteractionControlRequest,
    InteractionDisposition,
)
from runtime.contracts import (
    DeviceCapabilities,
    FailureSeverity,
    StateOperation,
    StateScope,
    TurnBudgets,
    TurnInput,
)


@dataclass
class _Route:
    primary: str
    reason: str = "fixture route"
    source: str = "fixture"
    concept_id: str | None = None
    concept_confidence: float = 0.0
    safety_alert: bool = False
    safety_tier: int | None = None
    safety_category: str | None = None
    uncertain: bool = False


def _turn(text: str = "help") -> TurnInput:
    return TurnInput(
        turn_id="turn-15",
        learner_id="learner-15",
        interaction={"text": text, "answer_budget": {"max_words": 20}},
        device=DeviceCapabilities(),
        budgets=TurnBudgets(total_ms=10_000),
        trusted_observations={"stt_confidence": 1.0},
    )


def _dependencies(**overrides) -> InteractionControlDependencies:
    values = {
        "deterministic_route": lambda text: None,
        "perception_route": lambda text, session: _Route("LEARNING"),
        "analyze": lambda text, current: {
            "normalized_text": text.lower(),
            "concept": {
                "concept_id": current,
                "concept_confidence": 1.0 if current else 0.0,
                "abstained": current is None,
            },
            "signals": [],
            "state_deltas": {},
        },
        "persona": {"identity": "Wini", "style": "Warm", "intents": {}},
        "want_answer": False,
        "generation_backend": "fixture-model",
        "generate_persona": lambda prompt: "generated",
        "concept_name": lambda concept_id: "Quadratic equations",
        "topic_candidates": lambda text, limit: [],
        "chapter_for_concept": lambda concept_id: None,
        "extract_topic_request": lambda text: None,
        "is_bare_topic": lambda text: False,
        "wants_different_topic": lambda text: False,
        "concept_relates_to_topic": lambda new, old: False,
        "mode_cue": lambda text: None,
        "current_mode": lambda session: session.get("mode", "EXPLAIN"),
        "set_mode": lambda session, mode: session.update({"mode": mode}),
        "consume_mode_offer": lambda session, text: None,
        "consume_test_resume": lambda session, text: None,
        "check_frozen_test": lambda session: None,
        "log_event": lambda event: None,
        "notify_safety": lambda record: None,
        "now": lambda: "2026-08-14T12:00:00",
    }
    values.update(overrides)
    return InteractionControlDependencies(**values)


class InteractionControlTests(unittest.TestCase):
    def test_internal_routing_failure_is_returned_as_typed_failure_signal(self) -> None:
        def fail_route(text):
            raise TimeoutError("gate unavailable")

        outcome = InteractionControl(
            _dependencies(deterministic_route=fail_route)
        ).control(InteractionControlRequest(turn_input=_turn(), session={}))

        self.assertFalse(outcome.valid)
        self.assertIsNone(outcome.value)
        self.assertEqual(outcome.failures[0].capability, "interaction_control")
        self.assertEqual(outcome.failures[0].severity, FailureSeverity.ERROR)
        self.assertFalse(outcome.failures[0].valid_outcome)
        self.assertIn("TimeoutError: gate unavailable", outcome.failures[0].cause)

    def test_learning_reuses_trusted_precomputed_analysis(self) -> None:
        analyze_calls = []
        trusted_analysis = {
            "normalized_text": "teach me fractions",
            "concept": {
                "concept_id": "fractions",
                "concept_confidence": 0.99,
                "abstained": False,
            },
            "signals": ["steady"],
            "state_deltas": {},
        }
        turn_input = TurnInput(
            turn_id="turn-precomputed",
            learner_id="learner-15",
            interaction={"text": "teach me fractions"},
            device=DeviceCapabilities(),
            budgets=TurnBudgets(total_ms=10_000),
            trusted_observations={"precomputed_analysis": trusted_analysis},
        )
        dependencies = _dependencies(
            analyze=lambda text, current: analyze_calls.append(text),
        )

        outcome = InteractionControl(dependencies).control(
            InteractionControlRequest(turn_input=turn_input, session={})
        )

        self.assertEqual(outcome.value.analysis["concept"]["concept_id"], "fractions")
        self.assertEqual(analyze_calls, [])

    def test_persona_generation_fallback_reports_typed_degradation(self) -> None:
        def generation_fails(prompt):
            raise TimeoutError("persona model timed out")

        dependencies = _dependencies(
            perception_route=lambda text, session: _Route("SOCIAL"),
            want_answer=True,
            generate_persona=generation_fails,
            persona={
                "identity": "Wini",
                "style": "Warm",
                "intents": {"SOCIAL": {"canned": ["Hello!"]}},
            },
        )

        outcome = InteractionControl(dependencies).control(
            InteractionControlRequest(turn_input=_turn("hello"), session={})
        )

        self.assertTrue(outcome.valid)
        self.assertEqual(outcome.value.compatibility["answer"], "Hello!")
        self.assertEqual(len(outcome.failures), 1)
        self.assertEqual(outcome.failures[0].capability, "interaction_control")
        self.assertEqual(outcome.failures[0].severity, FailureSeverity.DEGRADED)
        self.assertTrue(outcome.failures[0].valid_outcome)

    def test_low_confidence_input_is_observational_and_skips_perception(self) -> None:
        perception_calls = []
        dependencies = _dependencies(
            perception_route=lambda text, session: perception_calls.append(text),
        )
        turn_input = TurnInput(
            turn_id="turn-low-confidence",
            learner_id="learner-15",
            interaction={"text": "forty too", "answer_budget": None},
            device=DeviceCapabilities(),
            budgets=TurnBudgets(total_ms=10_000),
            trusted_observations={"stt_confidence": 0.31},
        )
        session = {
            "current_concept": "quadratics",
            "pending_check": {"id": "check-1", "question": "What is 6 × 7?"},
        }

        outcome = InteractionControl(dependencies).control(
            InteractionControlRequest(turn_input=turn_input, session=session)
        )

        self.assertEqual(outcome.value.disposition, InteractionDisposition.COMPLETE)
        self.assertEqual(
            outcome.value.compatibility["action"], "CONFIRM_LOW_CONFIDENCE"
        )
        self.assertIn("What is 6 × 7?", outcome.value.compatibility["answer"])
        self.assertEqual(outcome.state_changes, ())
        self.assertEqual(perception_calls, [])

    def test_identity_mismatch_fails_admission_with_typed_signal(self) -> None:
        outcome = InteractionControl(_dependencies()).control(
            InteractionControlRequest(
                turn_input=_turn("teach me triangles"),
                session={},
                bound_learner_id="different-learner",
            )
        )

        self.assertFalse(outcome.valid)
        self.assertIsNone(outcome.value)
        self.assertEqual(outcome.state_changes, ())
        self.assertEqual(len(outcome.failures), 1)
        self.assertEqual(outcome.failures[0].capability, "identity")
        self.assertEqual(outcome.failures[0].phase, "admission_and_routing")
        self.assertEqual(outcome.failures[0].severity, FailureSeverity.FATAL)
        self.assertFalse(outcome.failures[0].valid_outcome)

    def test_safety_route_returns_typed_outcome_without_mutating_snapshot(self) -> None:
        notifications = []
        logs = []
        route = _Route(
            "SAFETY",
            reason="deterministic safety gate",
            safety_alert=True,
            safety_tier=3,
            safety_category="self_harm",
        )
        dependencies = _dependencies(
            deterministic_route=lambda text: route,
            persona={
                "identity": "Wini",
                "style": "Warm",
                "intents": {"SAFETY": {"scripted": "Please get a trusted adult now."}},
            },
            notify_safety=notifications.append,
            log_event=logs.append,
        )
        session = {
            "current_concept": "quadratics",
            "pending_check": {"id": "check-1"},
            "context": [],
        }
        before = copy.deepcopy(session)

        outcome = InteractionControl(dependencies).control(
            InteractionControlRequest(turn_input=_turn("I want to end my life"), session=session)
        )

        self.assertTrue(outcome.valid)
        self.assertEqual(outcome.value.disposition, InteractionDisposition.COMPLETE)
        self.assertEqual(outcome.value.compatibility["action"], "SAFETY")
        self.assertEqual(
            outcome.value.compatibility["answer"], "Please get a trusted adult now."
        )
        self.assertEqual(outcome.value.compatibility["pending_check"], "check-1")
        self.assertEqual(session, before)
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["safety_category"], "self_harm")
        self.assertEqual(logs[-1]["action"], "SAFETY")
        self.assertTrue(any(
            change.owner == "interaction_control"
            and change.scope is StateScope.SESSION
            and change.path == ("context",)
            and change.operation is StateOperation.SET
            for change in outcome.state_changes
        ))
        self.assertTrue(any(
            change.owner == "interaction_control"
            and change.scope is StateScope.LEARNER
            and change.path == ("safety_alerts",)
            and change.operation is StateOperation.APPEND
            for change in outcome.state_changes
        ))

    def test_explicit_goodbye_ends_session_and_preserves_pending_assessment(self) -> None:
        route = _Route("SESSION_CONTROL", reason="leave request")
        dependencies = _dependencies(
            deterministic_route=lambda text: route,
            persona={
                "identity": "Wini",
                "style": "Warm",
                "intents": {
                    "SESSION_CONTROL": {
                        "canned": ["Okay, take a break."],
                        "farewell": "Goodbye! I'll be here next time.",
                    }
                },
            },
        )
        session = {
            "status": "active",
            "pending_check": {"id": "check-1", "question": "What is 2 + 2?"},
            "context": [],
        }

        outcome = InteractionControl(dependencies).control(
            InteractionControlRequest(turn_input=_turn("Goodbye"), session=session)
        )

        self.assertEqual(outcome.value.compatibility["answer_source"], "farewell")
        self.assertEqual(
            outcome.value.compatibility["answer"], "Goodbye! I'll be here next time."
        )
        self.assertTrue(outcome.value.compatibility["session_ended"])
        self.assertEqual(outcome.value.compatibility["pending_check"], "check-1")
        changed = {
            change.path: change.value
            for change in outcome.state_changes
            if change.scope is StateScope.SESSION
        }
        self.assertEqual(changed[("status",)], "ended")
        self.assertEqual(changed[("leave_requests",)], 1)
        self.assertTrue(changed[("break_requested",)])

    def test_confirmed_pending_shift_continues_learning_on_new_topic(self) -> None:
        analyzed = []
        dependencies = _dependencies(
            analyze=lambda text, current: analyzed.append((text, current)) or {
                "normalized_text": text.lower(),
                "concept": {
                    "concept_id": current,
                    "concept_confidence": 1.0,
                    "abstained": False,
                },
                "signals": [],
                "state_deltas": {},
            },
        )
        session = {
            "current_concept": "quadratics",
            "pending_shift": {"concept_id": "triangles", "name": "Triangles"},
            "pending_check": {"id": "old-check"},
            "pending_hope": {"signal": "KT"},
            "context": [],
        }

        outcome = InteractionControl(dependencies).control(
            InteractionControlRequest(turn_input=_turn("yes"), session=session)
        )

        self.assertEqual(
            outcome.value.disposition, InteractionDisposition.CONTINUE_LEARNING
        )
        self.assertEqual(outcome.value.text, "I want to learn about Triangles")
        self.assertEqual(analyzed, [("I want to learn about Triangles", "triangles")])
        changed = {
            change.path: (change.operation, change.value, change.owner)
            for change in outcome.state_changes
        }
        self.assertEqual(
            changed[("current_concept",)],
            (StateOperation.SET, "triangles", "interaction_control"),
        )
        self.assertEqual(
            changed[("pending_shift",)][0], StateOperation.DELETE
        )
        self.assertEqual(changed[("pending_check",)][2], "assessment_evidence")
        self.assertEqual(changed[("pending_hope",)][2], "assessment_evidence")

    def test_mode_stop_outranks_session_control_without_ending_session(self) -> None:
        def set_mode(session, mode):
            session["mode"] = mode
            session.pop("test_state", None)
            session.pop("practice_plan", None)

        dependencies = _dependencies(
            perception_route=lambda text, session: _Route("SESSION_CONTROL"),
            mode_cue=lambda text: "STOP",
            current_mode=lambda session: session.get("mode", "EXPLAIN"),
            set_mode=set_mode,
        )
        session = {
            "status": "active",
            "mode": "TEST",
            "test_state": {"phase": "active"},
            "pending_check": {"id": "test-question"},
            "pending_hope": {"signal": "KT"},
            "context": [],
        }

        outcome = InteractionControl(dependencies).control(
            InteractionControlRequest(turn_input=_turn("stop the test"), session=session)
        )

        self.assertEqual(outcome.value.disposition, InteractionDisposition.COMPLETE)
        self.assertEqual(outcome.value.compatibility["action"], "MODE_STOP")
        self.assertFalse(outcome.value.compatibility["session_ended"])
        changed = {
            change.path: (change.operation, change.value, change.owner)
            for change in outcome.state_changes
        }
        self.assertEqual(
            changed[("mode",)], (StateOperation.SET, "EXPLAIN", "pedagogy")
        )
        self.assertEqual(changed[("test_state",)][2], "pedagogy")
        self.assertEqual(changed[("pending_check",)][2], "assessment_evidence")

    def test_explicit_grounded_topic_shift_retargets_learning_continuation(self) -> None:
        analyzed = []

        def analyze(text, current):
            analyzed.append((text, current))
            concept_id = "triangles" if "Triangles" in text else current
            return {
                "normalized_text": text.lower(),
                "concept": {
                    "concept_id": concept_id,
                    "concept_confidence": 0.3 if concept_id == current else 0.95,
                    "abstained": concept_id == current,
                },
                "signals": [],
                "state_deltas": {},
            }

        dependencies = _dependencies(
            analyze=analyze,
            extract_topic_request=lambda text: "triangles",
            topic_candidates=lambda text, limit: [("triangles", "Triangles", 0.55)],
        )
        session = {
            "current_concept": "quadratics",
            "pending_check": {"id": "old-check"},
            "context": [],
        }

        outcome = InteractionControl(dependencies).control(
            InteractionControlRequest(
                turn_input=_turn("I asked about triangles"), session=session
            )
        )

        self.assertEqual(outcome.value.text, "I want to learn about Triangles")
        self.assertEqual(outcome.value.analysis["concept"]["concept_id"], "triangles")
        self.assertEqual(len(analyzed), 2)
        changed = {change.path: change for change in outcome.state_changes}
        self.assertEqual(changed[("current_concept",)].value, "triangles")
        self.assertEqual(changed[("pending_check",)].operation, StateOperation.DELETE)

    def test_anaphoric_followup_preserves_unrelated_current_topic(self) -> None:
        dependencies = _dependencies(
            analyze=lambda text, current: {
                "normalized_text": text.lower(),
                "concept": {
                    "concept_id": "linear_graphs",
                    "concept_confidence": 0.91,
                    "abstained": False,
                },
                "signals": [],
                "state_deltas": {},
            },
            concept_relates_to_topic=lambda new, old: False,
        )

        outcome = InteractionControl(dependencies).control(
            InteractionControlRequest(
                turn_input=_turn("solve this with graph"),
                session={"current_concept": "quadratics"},
            )
        )

        self.assertEqual(
            outcome.value.analysis["concept"]["concept_id"], "quadratics"
        )
        self.assertFalse(any(
            change.path == ("current_concept",) for change in outcome.state_changes
        ))

    def test_declining_current_topic_offers_alternatives_and_clears_stale_prompt(self) -> None:
        dependencies = _dependencies(
            perception_route=lambda text, session: _Route("SOCIAL"),
            wants_different_topic=lambda text: True,
            chapter_for_concept=lambda concept_id: "jemh104",
        )
        session = {
            "current_concept": "quadratics",
            "pending_check": {"id": "old-check"},
            "pending_hope": {"signal": "KT"},
            "steer_streak": 2,
            "context": [],
        }

        outcome = InteractionControl(dependencies).control(
            InteractionControlRequest(
                turn_input=_turn("I don't want to learn this"), session=session
            )
        )

        self.assertEqual(outcome.value.compatibility["action"], "TOPIC_MENU")
        self.assertIn("Real Numbers", outcome.value.compatibility["answer"])
        self.assertNotIn("Quadratic Equations,", outcome.value.compatibility["answer"])
        changed = {change.path: change for change in outcome.state_changes}
        self.assertEqual(changed[("pending_check",)].owner, "assessment_evidence")
        self.assertEqual(changed[("pending_hope",)].owner, "assessment_evidence")
        self.assertEqual(changed[("steer_streak",)].value, 0)

    def test_pending_mode_offer_decline_completes_before_perception(self) -> None:
        perception_calls = []

        def consume_offer(session, text):
            session.pop("pending_mode_offer", None)
            return ("declined", "EXPLAIN")

        dependencies = _dependencies(
            perception_route=lambda text, session: perception_calls.append(text),
            consume_mode_offer=consume_offer,
        )
        outcome = InteractionControl(dependencies).control(
            InteractionControlRequest(
                turn_input=_turn("no"),
                session={"pending_mode_offer": {"mode": "PRACTICE"}, "context": []},
            )
        )

        self.assertEqual(outcome.value.compatibility["action"], "MODE_OFFER_DECLINED")
        self.assertEqual(perception_calls, [])
        changed = {change.path: change for change in outcome.state_changes}
        self.assertEqual(changed[("pending_mode_offer",)].owner, "pedagogy")

    def test_learning_resumes_paused_session_through_continuity_changes(self) -> None:
        outcome = InteractionControl(_dependencies()).control(
            InteractionControlRequest(
                turn_input=_turn("continue fractions"),
                session={
                    "status": "paused",
                    "break_requested": True,
                    "leave_requests": 1,
                    "current_concept": "fractions",
                },
            )
        )

        changed = {change.path: change for change in outcome.state_changes}
        self.assertEqual(changed[("status",)].value, "active")
        self.assertEqual(changed[("break_requested",)].operation, StateOperation.DELETE)
        self.assertEqual(changed[("leave_requests",)].operation, StateOperation.DELETE)


if __name__ == "__main__":
    unittest.main()
