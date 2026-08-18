from __future__ import annotations

import unittest
from types import SimpleNamespace

from pedagogy import PedagogicalDecision, PedagogicalPacing
from response_planning import (
    ResponsePlanning,
    ResponsePlanningRequest,
    ResponsePlanningStateView,
)
from runtime.contracts import DeviceCapabilities, TurnBudgets, TurnInput


class Evidence:
    def __init__(self, id, type, why, content):
        self.id, self.type, self.why, self.content = id, type, why, content

    def to_dict(self):
        return {"id": self.id, "type": self.type, "why": self.why, **self.content}


def request(*, action="EXPLAIN", display=True, assessment=None, evidence=True):
    turn = TurnInput(
        turn_id="turn-1", learner_id="learner-1",
        interaction={"text": "show me fractions"},
        device=DeviceCapabilities(speech=True, display=display, authored_visuals=display),
        budgets=TurnBudgets(total_ms=1000),
    )
    decision = PedagogicalDecision(
        action=action, mode="TEST" if action == "TEST_QUESTION" else "EXPLAIN",
        need="practice" if "PRACTICE" in action else "explain", reason="fixture",
        pacing=PedagogicalPacing(max_sentences=3, max_words=80),
    )
    items = ((Evidence(id="e1", type="chunk", why="fixture",
                       content={"text": "Fractions are equal parts."}),)
             if evidence else ())
    manifest = SimpleNamespace(evidence=items, grounding="manifest_only")
    retrieval = SimpleNamespace(manifest=manifest, assessment_candidate=assessment,
                                assessment_allowed=True)
    return ResponsePlanningRequest(
        turn_input=turn, pedagogical=decision, retrieval=retrieval,
        concept_id="fractions",
        state=ResponsePlanningStateView(
            concept_type="representation", representation_targets=("visual",),
        ),
    )


class ResponsePlanningTests(unittest.TestCase):
    def test_explanation_produces_approved_typed_plan(self):
        outcome = ResponsePlanning().plan(request())
        self.assertTrue(outcome.valid)
        self.assertEqual(outcome.value.script.pedagogical_action, "EXPLAIN")
        self.assertEqual(outcome.value.intended_modalities, ("speech", "display"))
        self.assertEqual(outcome.value.approved_modalities, ("speech", "display"))
        self.assertIsNone(outcome.value.assessment_proposal)

    def test_unsupported_optional_visual_falls_back_to_speech(self):
        outcome = ResponsePlanning().plan(request(display=False))
        self.assertTrue(outcome.valid)
        self.assertEqual(outcome.value.intended_modalities, ("speech", "display"))
        self.assertEqual(outcome.value.approved_modalities, ("speech",))
        self.assertEqual(outcome.failures[0].cause, "unsupported_capability")

    def test_verified_candidate_is_only_proposed_not_armed(self):
        candidate = {
            "id": "item-1", "item_id": "item-1", "kind": "practice",
            "question": "What is one half plus one half?", "expected_answer": "1",
            "concept_id": "fractions", "assessment_purpose": "check_independent",
            "state_update_intent": "practice", "item_verified": True,
            "verification_status": "verified", "verification_token": "token",
        }
        outcome = ResponsePlanning().plan(request(action="ISOMORPHIC_PRACTICE",
                                                  assessment=candidate))
        self.assertTrue(outcome.valid)
        proposal = outcome.value.assessment_proposal
        self.assertEqual(proposal.item_id, "item-1")
        self.assertFalse(proposal.armed)
        self.assertEqual(outcome.state_changes, ())

    def test_ungrounded_instructional_plan_emits_failure(self):
        outcome = ResponsePlanning().plan(request(evidence=False))
        self.assertFalse(outcome.valid)
        self.assertEqual(outcome.failures[0].cause, "grounding_violation")

    def test_action_scenarios_preserve_the_selected_teaching_script(self):
        cases = {
            "EXPLAIN": "explain",
            "ISOMORPHIC_PRACTICE": "pose_problem",
            "TEST_QUESTION": "test_question",
            "REPRESENTATION_TRANSLATION": "representation_translation",
            "VISUAL_ANALOGY": "representation_translation",
        }
        for action, first_step in cases.items():
            with self.subTest(action=action):
                outcome = ResponsePlanning().plan(request(action=action))
                self.assertTrue(outcome.valid)
                self.assertEqual(outcome.value.script.beats[0].pedagogical_step,
                                 first_step)

    def test_social_scenario_is_speech_only_and_needs_no_grounding(self):
        req = request(evidence=False)
        req = ResponsePlanningRequest(
            turn_input=req.turn_input, pedagogical=req.pedagogical,
            retrieval=req.retrieval, concept_id=None, state=req.state,
            response_kind="social",
        )
        outcome = ResponsePlanning().plan(req)
        self.assertTrue(outcome.valid)
        self.assertEqual(outcome.value.intended_modalities, ("speech",))

    def test_illegal_teaching_step_emits_typed_failure(self):
        planner = ResponsePlanning()
        real_plan = planner._planner.plan

        def illegal(ctx):
            script = real_plan(ctx)
            script.beats[0].pedagogical_step = "test_summary"
            return script

        planner._planner.plan = illegal
        outcome = planner.plan(request())
        self.assertFalse(outcome.valid)
        self.assertEqual(outcome.failures[0].cause, "illegal_teaching_step")


if __name__ == "__main__":
    unittest.main()
