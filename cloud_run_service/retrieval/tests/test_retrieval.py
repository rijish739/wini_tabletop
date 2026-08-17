from __future__ import annotations

import unittest

import networkx as nx
import numpy as np

from pedagogy import PedagogicalDecision, PedagogicalPacing
from retrieval import (
    Retrieval,
    RetrievalDependencies,
    RetrievalRequest,
    RetrievalStateView,
    RetrievalStoreView,
)
from runtime.contracts import DeviceCapabilities, TurnBudgets, TurnInput


def turn(text: str = "explain fractions") -> TurnInput:
    return TurnInput(
        turn_id="turn-19",
        learner_id="learner-1",
        interaction={"text": text},
        device=DeviceCapabilities(),
        budgets=TurnBudgets(total_ms=1000),
    )


def decision(action="EXPLAIN", need="explain") -> PedagogicalDecision:
    return PedagogicalDecision(
        mode="EXPLAIN", action=action, need=need, reason="test",
        pacing=PedagogicalPacing(max_words=60, max_sentences=3),
    )


def store() -> RetrievalStoreView:
    graph = nx.DiGraph()
    graph.add_node("fractions", type="concept")
    graph.add_node(
        "grade9::division", type="bridge", name="division",
        diagnostic_question="What is 6 divided by 3?", expected_answer="2",
    )
    graph.add_edge("grade9::division", "fractions", relation="bridges_to")
    graph.add_node(
        "misc::add-denominators", type="misconception",
        diagnostic_question="Do denominators always add?", why_wrong="They do not.",
        correct_idea="Use a common denominator.", expected_answer="no",
    )
    graph.add_edge("fractions", "misc::add-denominators", relation="has_misconception")
    graph.add_node("schema::fractions", type="problem_schema", name="fraction addition",
                   method_steps=["find a common denominator", "add numerators"])
    graph.add_edge("fractions", "schema::fractions", relation="has_schema")
    graph.add_node("transfer::recipe", type="concept")
    graph.add_edge("fractions", "transfer::recipe", relation="transfers_to", transfer_type="near")
    chunks = (
        {"chunk_id": "bridge-recap", "kind": "bridge_recap", "grade9_id": "grade9::division",
         "text": "Division recap", "concept_ids": ["fractions"], "pedagogical_role": "summary",
         "difficulty": 2},
        {"chunk_id": "fraction-explain", "text": "Fractions name equal parts.",
         "concept_ids": ["fractions"], "pedagogical_role": "explanation", "difficulty": 3},
        {"chunk_id": "fraction-example", "text": "One half plus one half is one.",
         "concept_ids": ["fractions"], "pedagogical_role": "worked_example", "difficulty": 3},
    )
    return RetrievalStoreView(
        concepts=({"concept_id": "fractions", "representations": ["symbolic", "visual"]},),
        chunks=chunks,
        graph=graph,
        chunk_embeddings=np.asarray([[0.9, 0.1], [1.0, 0.0], [0.8, 0.2]]),
    )


def state(**overrides) -> RetrievalStateView:
    values = dict(
        mastery={"fractions": 0.2, "grade9::division": 0.1},
        measured_concepts=frozenset({"fractions"}),
        misconceptions={"misc::add-denominators": {"status": "supported", "consecutive_failures": 0}},
        representations_known={"fractions": ("symbolic",)},
        served_items=(), bridges_served=(), hint_progress={},
        hope_rolling={"KI": 0.5, "KT": 0.5, "CT": 0.5},
    )
    values.update(overrides)
    return RetrievalStateView(**values)


class RetrievalInterfaceTests(unittest.TestCase):
    def module(self, *, cohesion_check=None, practice_candidate=None) -> Retrieval:
        return Retrieval(RetrievalDependencies(
            embed=lambda texts: np.asarray([[1.0, 0.0] for _ in texts]),
            cohesion_check=cohesion_check,
            practice_candidate=practice_candidate,
        ))

    def request(self, *, pedagogical=None, learner_state=None, retrieval_store=None):
        return RetrievalRequest(
            turn_input=turn(), concept_id="fractions", concept_confidence=1.0,
            secondary_concepts=(), pedagogical=pedagogical or decision(),
            state=learner_state or state(), store=retrieval_store or store(),
        )

    def test_bridge_precedes_misconception_and_chunks_and_proposes_served_changes(self):
        outcome = self.module().retrieve(self.request())

        self.assertTrue(outcome.valid)
        evidence = outcome.value.manifest.evidence
        self.assertEqual("bridge_recap", evidence[0].type)
        self.assertEqual("bridge_diagnostic", evidence[1].type)
        self.assertEqual("misconception", evidence[2].type)
        self.assertNotIn("correct_idea", evidence[2].content)
        self.assertEqual("manifest_only", outcome.value.manifest.grounding)
        self.assertEqual("retrieval", outcome.state_changes[0].owner)
        self.assertEqual(("served_items",), outcome.state_changes[0].path)

    def test_need_modes_select_schema_transfer_and_representation_evidence(self):
        schema = self.module().retrieve(self.request(pedagogical=decision("WORKED_EXAMPLE", "schema")))
        transfer = self.module().retrieve(self.request(pedagogical=decision("TRANSFER_PROBLEM", "transfer")))
        representation = self.module().retrieve(self.request(
            pedagogical=decision("REPRESENTATION_TRANSLATION", "integrate")))

        self.assertIn("problem_schema", {e.type for e in schema.value.manifest.evidence})
        self.assertIn("transfer_target", {e.type for e in transfer.value.manifest.evidence})
        self.assertEqual("integrate", representation.value.manifest.need)

    def test_example_and_practice_are_selected_through_the_interface(self):
        example = self.module().retrieve(self.request(
            pedagogical=decision("WORKED_EXAMPLE", "example")))
        practice = self.module(practice_candidate=lambda concept_id: {
            "id": "practice-1", "item_id": "practice-1", "question": "1/2 + 1/2?",
            "concept_id": concept_id, "item_verified": True,
        }).retrieve(self.request(pedagogical=PedagogicalDecision(
            mode="PRACTICE", action="ISOMORPHIC_PRACTICE", need="practice",
            reason="test", pacing=PedagogicalPacing(60, 3),
        ), learner_state=state(
            bridges_served=("grade9::division",), misconceptions={},
        )))

        chunk_ids = [item.id for item in example.value.manifest.evidence
                     if item.type == "chunk"]
        self.assertEqual("fraction-example", chunk_ids[0])
        self.assertEqual("practice-1", practice.value.assessment_candidate["id"])
        self.assertTrue(practice.value.assessment_allowed)

    def test_served_history_demotes_without_excluding_and_manifest_is_immutable(self):
        outcome = self.module().retrieve(self.request(learner_state=state(
            served_items=("fraction-explain",))))

        chunks = [e.id for e in outcome.value.manifest.evidence if e.type == "chunk"]
        self.assertIn("fraction-explain", chunks)
        with self.assertRaises(TypeError):
            outcome.value.manifest.ranking_trace["changed"] = True

    def test_unavailable_embeddings_returns_safe_empty_non_assessing_outcome(self):
        outcome = Retrieval().retrieve(self.request(
            pedagogical=decision("TRANSFER_PROBLEM", "transfer")))

        self.assertTrue(outcome.valid)
        self.assertFalse(outcome.value.assessment_candidate)
        self.assertFalse(outcome.value.assessment_allowed)
        self.assertEqual((), outcome.value.manifest.evidence)
        self.assertEqual("embeddings_unavailable", outcome.failures[0].cause)
        self.assertTrue(outcome.failures[0].valid_outcome)

    def test_missing_store_invalid_evidence_and_cohesion_failure_are_typed(self):
        missing = self.module().retrieve(self.request(retrieval_store=RetrievalStoreView()))
        invalid_store = store()
        invalid_store = RetrievalStoreView(
            concepts=invalid_store.concepts,
            chunks=({"chunk_id": "", "text": "bad"},),
            graph=invalid_store.graph,
            chunk_embeddings=np.asarray([[1.0, 0.0]]),
        )
        invalid = self.module().retrieve(self.request(retrieval_store=invalid_store))
        cohesion = self.module(cohesion_check=lambda evidence: (_ for _ in ()).throw(
            RuntimeError("judge down"))).retrieve(self.request())

        self.assertEqual("missing_store", missing.failures[0].cause)
        self.assertEqual("invalid_evidence", invalid.failures[0].cause)
        self.assertEqual("cohesion_failure", cohesion.failures[0].cause)
        self.assertFalse(cohesion.value.assessment_allowed)


if __name__ == "__main__":
    unittest.main()
