from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from interaction_control import (
    CapabilityTransition,
    InteractionControl,
    InteractionControlDependencies,
    InteractionDecision,
    InteractionDisposition,
)
from runtime.contracts import ModuleOutcome
from runtime.compatibility import TutorLoopCompatibilityFacade
from runtime.supervisor import RuntimeHealth
from perception import Perception, PerceptionTransportError
from perception.route import RouteResult
from assessment_evidence import AssessmentEvidence
from evidence.ledger import make_idempotency_key
from pedagogy import Pedagogy, PedagogyDependencies


class CompatibilityFacadeTests(unittest.TestCase):
    def test_pedagogy_decision_crosses_the_compatibility_facade(self) -> None:
        class Engine:
            def observe(self, text, session, current_concept):
                flags = []
                signals = []
                cognitive = {
                    "confusion": 0.0, "curiosity": 0.0,
                    "cognitive_load": 0.0, "frustration_risk": 0.0,
                }
                problem_cue = {}
                if text == "hint please":
                    flags, signals = ["hint_requested"], ["request_hint"]
                elif text == "denominators always add":
                    flags = ["misconception_suspected"]
                elif text == "give me a harder one":
                    signals = ["ready_for_next"]
                elif text == "I don't understand":
                    cognitive["confusion"] = 0.8
                elif text == "solve 2x + 3 = 7":
                    problem_cue = {"is_problem": True, "directive": True}
                return RouteResult(primary="LEARNING", concept_id="fractions"), {
                    "normalized_text": text,
                    "signals": signals,
                    "signal_scores": {},
                    "concept": {
                        "concept_id": "fractions", "concept_confidence": 1.0,
                        "secondary_concepts": [], "abstained": False,
                    },
                    "cognitive_update": cognitive,
                    "state_deltas": {
                        "global": {}, "concept_id": "fractions",
                        "concept_flags": flags,
                        "signals": signals,
                    },
                    "problem_cue": problem_cue,
                }

        class Control:
            def control(self, request):
                if request.turn_input.interaction["text"] == "change topic":
                    return ModuleOutcome(value=InteractionDecision(
                        disposition=InteractionDisposition.COMPLETE,
                        text="change topic",
                        compatibility={
                            "action": "TOPIC_SHIFT", "answer": "Which topic?",
                            "display": [], "session_ended": False,
                        },
                    ))
                return ModuleOutcome(value=InteractionDecision(
                    disposition=InteractionDisposition.CONTINUE_LEARNING,
                    text=request.turn_input.interaction["text"],
                    analysis=request.perception.analysis,
                ))

        received = {}
        state = SimpleNamespace(data={
            "learner_id": "learner-1",
            "concept_states": {"fractions": {
                "mastery": 0.4, "transfer_readiness": 0.9,
            }},
            "session": {"mode": "EXPLAIN", "current_concept": "fractions"},
        })
        facade = TutorLoopCompatibilityFacade(
            legacy_turn=lambda text, **kwargs: received.update(kwargs) or {
                "action": kwargs["_pedagogy_decision"].action,
                "answer": "Try a similar example.", "display": [],
            },
            commit_state=lambda: None,
            state=state,
            interaction_control=Control(),
            perception=Perception(Engine()),
            pedagogy=Pedagogy(dependencies=PedagogyDependencies(
                schema_ids=lambda concept_id: ["schema-1"],
            )),
        )

        cases = (
            ("explain fractions", "EXPLAIN"),
            ("hint please", "ANALOGOUS_EXAMPLE"),
            ("denominators always add", "MISCONCEPTION_PROBE"),
            ("give me a harder one", "TRANSFER_PROBLEM"),
            ("I don't understand", "EXPLAIN"),
            ("okay", "METACOGNITIVE_REFLECT"),
            ("solve 2x + 3 = 7", "SOLVE_STUDENT_PROBLEM"),
            ("let's practice", "WORKED_EXAMPLE"),
            ("test me", "TEST_QUESTION"),
            ("stop the test", "EXPLAIN"),
        )
        for index, (text, expected) in enumerate(cases):
            with self.subTest(text=text):
                result = facade.turn(
                    text, turn_id=f"turn-{index + 2}", learner_id="learner-1"
                )
                self.assertEqual(result["action"], expected)

        self.assertEqual(received["_pedagogy_decision"].need, "explain")
        topic_change = facade.turn(
            "change topic", turn_id="turn-topic", learner_id="learner-1"
        )
        self.assertEqual(topic_change["action"], "TOPIC_SHIFT")

    def test_prior_assessment_is_graded_and_projected_through_the_facade(self) -> None:
        class AttemptControl:
            def control(self, request):
                return ModuleOutcome(value=InteractionDecision(
                    disposition=InteractionDisposition.CONTINUE_LEARNING,
                    text=request.turn_input.interaction["text"],
                    analysis={},
                    answer_attempt=True,
                ))

        pending = {
            "id": "item-1", "item_id": "item-1", "script_id": "script-1",
            "beat_id": "beat-1", "hook_id": "hook-1",
            "question": "What is 2 plus 3?", "expected_answer": "5",
            "concept_id": "addition", "kind": "practice",
            "item_verified": True, "verification_status": "verified",
            "verification_token": "token", "realized_turn_id": "turn-1",
        }
        state = SimpleNamespace(data={
            "learner_id": "learner-1", "concept_states": {},
            "session": {"pending_check": pending},
        })
        received = {}

        def legacy_turn(text, **kwargs):
            received.update(kwargs)
            self.assertNotIn("pending_check", state.data["session"])
            return {"action": "EXPLAIN", "answer": "Good work.", "display": []}

        facade = TutorLoopCompatibilityFacade(
            legacy_turn=legacy_turn,
            commit_state=lambda: None,
            state=state,
            interaction_control=AttemptControl(),
            assessment_evidence=AssessmentEvidence(),
        )

        result = facade.turn("5", turn_id="turn-2", learner_id="learner-1")

        self.assertEqual(result["action"], "EXPLAIN")
        self.assertEqual(received["_prior_assessment"].grade.outcome, "correct")
        self.assertEqual(len(state.data["evidence_ledger"]), 1)
        self.assertGreater(state.data["concept_states"]["addition"]["mastery"], 0.0)

    def test_prior_assessment_edge_cases_cross_the_facade(self) -> None:
        class Control:
            def control(self, request):
                text = request.turn_input.interaction["text"]
                return ModuleOutcome(value=InteractionDecision(
                    disposition=InteractionDisposition.CONTINUE_LEARNING,
                    text=text,
                    analysis={},
                    answer_attempt=text not in {"okay", "I don't understand"},
                ))

        def pending(**changes):
            value = {
                "id": "item-1", "item_id": "item-1", "script_id": "script-1",
                "beat_id": "beat-1", "hook_id": "hook-1",
                "question": "What is 2 plus 3?", "expected_answer": "5",
                "concept_id": "addition", "kind": "practice",
                "item_verified": True, "verification_status": "verified",
                "verification_token": "token", "realized_turn_id": "turn-1",
            }
            value.update(changes)
            return value

        def run(text, *, pending_value=None, grade=None, evidence_index=None):
            state = SimpleNamespace(data={
                "learner_id": "learner-1", "concept_states": {},
                "evidence_index": evidence_index or {},
                "session": {"pending_check": pending_value or pending()},
            })
            received = {}
            facade = TutorLoopCompatibilityFacade(
                legacy_turn=lambda _text, **kwargs: received.update(kwargs) or {
                    "action": "EXPLAIN", "answer": "continue", "display": []
                },
                commit_state=lambda: None,
                state=state,
                interaction_control=Control(),
                assessment_evidence=AssessmentEvidence(),
            )
            result = facade.turn(
                text, turn_id="turn-2", learner_id="learner-1",
                precomputed_grade=grade,
            )
            return state, received, result

        wrong_state, wrong_received, _ = run("4")
        self.assertEqual(wrong_received["_prior_assessment"].grade.outcome, "wrong")
        self.assertEqual(len(wrong_state.data["evidence_ledger"]), 1)

        partial_state, partial_received, _ = run("partly five", grade={
            "outcome": "partial", "grader_path": "rubric_model", "confidence": 0.9,
        })
        self.assertEqual(partial_received["_prior_assessment"].grade.outcome, "partial")
        self.assertNotIn("pending_check", partial_state.data["session"])

        low_state, low_received, _ = run("maybe five", grade={
            "outcome": "partial", "grader_path": "rubric_model", "confidence": 0.2,
        })
        self.assertEqual(
            low_received["_prior_assessment"].writeback_status, "low_confidence"
        )
        self.assertIn("pending_check", low_state.data["session"])

        non_state, non_received, _ = run("I don't understand")
        self.assertFalse(non_received["_prior_assessment"].attempted)
        self.assertIn("pending_check", non_state.data["session"])

        duplicate_key = make_idempotency_key(
            "learner-1", "turn-2", "item-1", "5"
        )
        duplicate_state, duplicate_received, _ = run(
            "5", evidence_index={duplicate_key: 0}
        )
        self.assertEqual(
            duplicate_received["_prior_assessment"].writeback_status, "duplicate"
        )
        self.assertNotIn("pending_check", duplicate_state.data["session"])

        for invalid, cause in (
            (pending(realized_turn_id="turn-2"), "stale_pending_assessment"),
            (pending(item_verified=False, verification_status="legacy_unverified"),
             "legacy_unverified_pending_assessment"),
        ):
            with self.subTest(cause=cause):
                with self.assertRaisesRegex(RuntimeError, cause):
                    run("5", pending_value=invalid)

    def test_perception_scenarios_cross_the_compatibility_facade(self) -> None:
        class Engine:
            def observe(self, text, session, current_concept):
                if text == "backend down":
                    raise PerceptionTransportError("backend_unavailable")
                return RouteResult(primary="LEARNING"), {
                    "normalized_text": text, "signals": [], "signal_scores": {},
                    "concept": {
                        "concept_id": current_concept, "concept_confidence": 0.0,
                        "secondary_concepts": [], "abstained": True,
                    },
                    "cognitive_update": {},
                    "state_deltas": {"global": {}, "concept_id": current_concept,
                                     "concept_flags": [], "signals": []},
                }

        class Control:
            def control(self, request):
                observation = request.perception
                if observation.intent != "LEARNING":
                    return ModuleOutcome(value=InteractionDecision(
                        disposition=InteractionDisposition.COMPLETE,
                        text=request.turn_input.interaction["text"],
                        compatibility={"action": observation.intent, "answer": "safe",
                                       "display": [], "session_ended": False},
                    ))
                return ModuleOutcome(value=InteractionDecision(
                    disposition=InteractionDisposition.CONTINUE_LEARNING,
                    text=request.turn_input.interaction["text"],
                    analysis=observation.analysis,
                    perception_uncertain=observation.uncertain,
                ))

        received = []
        state = SimpleNamespace(
            data={"learner_id": "learner-1", "session": {"current_concept": "fractions"}}
        )
        facade = TutorLoopCompatibilityFacade(
            legacy_turn=lambda text, **kwargs: received.append(kwargs) or {
                "action": "EXPLAIN", "answer": "learning", "display": []
            },
            commit_state=lambda: None,
            state=state,
            interaction_control=Control(),
            perception=Perception(Engine()),
        )

        self.assertEqual(facade.turn("I want to kill myself")["action"], "SAFETY")
        self.assertEqual(facade.turn("!!!!!!")["action"], "NONSENSE")
        self.assertEqual(facade.turn("explain that")["action"], "EXPLAIN")
        self.assertEqual(received[-1]["precomputed_analysis"]["concept"]["concept_id"], "fractions")
        self.assertEqual(facade.turn("backend down")["action"], "EXPLAIN")
        self.assertTrue(received[-1]["_perception_uncertain"])
        self.assertEqual(received[-1]["precomputed_analysis"]["signals"], [])

    def test_learning_and_nonlearning_routes_cross_the_same_compatibility_facade(self) -> None:
        def route(text, session):
            return SimpleNamespace(
                primary="SOCIAL" if text == "hello" else "LEARNING",
                reason="fixture route",
                source="fixture",
                concept_id=None,
                concept_confidence=0.0,
                safety_alert=False,
                uncertain=False,
                answer_attempt=False,
            )

        no_transition = lambda *args: CapabilityTransition()
        control = InteractionControl(InteractionControlDependencies(
            deterministic_route=lambda text: None,
            perception_route=route,
            analyze=lambda text, current: {
                "normalized_text": text,
                "concept": {
                    "concept_id": "fractions",
                    "concept_confidence": 1.0,
                    "abstained": False,
                },
                "signals": [],
                "state_deltas": {},
            },
            persona={
                "identity": "Wini",
                "style": "Warm",
                "intents": {"SOCIAL": {"canned": ["Hello!"]}},
            },
            want_answer=False,
            generation_backend="fixture",
            generate_persona=lambda prompt: "",
            concept_name=lambda concept_id: "Fractions",
            topic_candidates=lambda text, limit: [],
            chapter_for_concept=lambda concept_id: None,
            extract_topic_request=lambda text: None,
            is_bare_topic=lambda text: False,
            wants_different_topic=lambda text: False,
            concept_relates_to_topic=lambda new, old: False,
            mode_cue=lambda text: None,
            current_mode=lambda session: "EXPLAIN",
            set_mode=no_transition,
            consume_mode_offer=no_transition,
            consume_test_resume=no_transition,
            check_frozen_test=no_transition,
            clear_pending_assessment=no_transition,
            log_event=lambda event: None,
            notify_safety=lambda record: None,
            now=lambda: "2026-08-14T12:00:00",
        ))

        learning_calls = []

        def legacy_learning(text, **kwargs):
            learning_calls.append((text, kwargs))
            return {
                "action": "EXPLAIN",
                "answer": "One half.",
                "display": [],
                "session_ended": False,
            }

        state = SimpleNamespace(data={"learner_id": "learner-1", "session": {}})
        facade = TutorLoopCompatibilityFacade(
            legacy_turn=legacy_learning,
            commit_state=lambda: None,
            state=state,
            interaction_control=control,
        )

        social = facade.turn("hello", turn_id="turn-social", learner_id="learner-1")
        learning = facade.turn(
            "teach me fractions", turn_id="turn-learning", learner_id="learner-1"
        )

        self.assertEqual(social["action"], "SOCIAL")
        self.assertEqual(learning["action"], "EXPLAIN")
        self.assertEqual(len(learning_calls), 1)
        self.assertEqual(learning_calls[0][0], "teach me fractions")
        self.assertTrue(learning_calls[0][1]["_interaction_controlled"])
        self.assertEqual(
            state.data["session"]["context"],
            [
                {"role": "student", "text": "hello"},
                {"role": "wini", "text": "Hello!"},
                {"role": "student", "text": "teach me fractions"},
                {"role": "wini", "text": "One half."},
            ],
        )

    def test_tutor_loop_turn_routes_through_coordinator_and_preserves_dictionary(self) -> None:
        state = SimpleNamespace(
            data={"learner_id": "learner-1", "session": {"mode": "EXPLAIN"}}
        )
        expected = {
            "answer": "One half.",
            "display": [{"kind": "text", "lines": ["1/2"]}],
            "signals": ["steady"],
        }
        received = {}

        def legacy_turn(text, **kwargs):
            received["text"] = text
            received.update(kwargs)
            return expected

        commits = []
        class LearningControl:
            def control(self, request):
                return ModuleOutcome(value=InteractionDecision(
                    disposition=InteractionDisposition.CONTINUE_LEARNING,
                    text=request.turn_input.interaction["text"],
                    analysis=request.turn_input.trusted_observations[
                        "precomputed_analysis"
                    ],
                ))

        facade = TutorLoopCompatibilityFacade(
            legacy_turn=legacy_turn,
            commit_state=lambda: commits.append("committed"),
            state=state,
            interaction_control=LearningControl(),
        )

        actual = facade.turn(
            "What is one half?",
            answer_budget={"max_words": 20},
            precomputed_analysis={"signals": ["steady"]},
            precomputed_grade="correct",
            stt_confidence=0.98,
            turn_id="turn-1",
            learner_id="learner-1",
        )

        self.assertEqual(actual, expected)
        self.assertIsInstance(actual["display"], list)
        self.assertIsInstance(actual["display"][0]["lines"], list)
        self.assertEqual(received["text"], "What is one half?")
        self.assertEqual(received["answer_budget"], {"max_words": 20})
        self.assertEqual(received["precomputed_analysis"], {"signals": ["steady"]})
        self.assertEqual(received["precomputed_grade"], "correct")
        self.assertEqual(commits, ["committed"])
        self.assertEqual(facade.runtime_health.health, RuntimeHealth.READY)

    def test_canonical_tutor_loop_entrypoint_is_only_a_compatibility_facade(self) -> None:
        source = (Path(__file__).parents[2] / "tutor_loop.py").read_text(encoding="utf-8")
        facade_start = source.index("    def turn(")
        legacy_start = source.index("    def _legacy_turn(")
        facade_body = source[facade_start:legacy_start]
        legacy_body = source[legacy_start:source.index("    @staticmethod\n    def _test_echo")]
        adapter_source = (
            Path(__file__).parents[1] / "legacy_adapter.py"
        ).read_text(encoding="utf-8")

        self.assertIn("_turn_compatibility_facade().turn(", facade_body)
        self.assertNotIn("_front_gate(text)", facade_body)
        self.assertIn("_interaction_controlled", legacy_body)
        self.assertNotIn("_handle_nonlearning", adapter_source)
        self.assertNotIn("_maybe_topic_shift", adapter_source)
        self.assertNotIn("_maybe_stop_mode", adapter_source)


if __name__ == "__main__":
    unittest.main()
