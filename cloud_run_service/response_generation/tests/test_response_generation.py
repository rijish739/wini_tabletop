import unittest

from pedagogy import PedagogicalDecision
from response_generation import (
    ResponseGeneration,
    ResponseGenerationRequest,
    ResponseGenerationStateView,
)
from response_layer.contracts import Beat, ResponseKind, TeachingScript
from response_planning import ResponsePlan
from retrieval import GroundedEvidence, GroundedManifest, RetrievalResult
from runtime.contracts import DeviceCapabilities, TurnBudgets, TurnInput
from runtime.model_gateway import ModelCall, ReplayModelGateway


def request(*, spoken=None, stream=None, budget=None, figure=False, clarification=False):
    beat = Beat(beat_id="beat-1", pedagogical_step="explain")
    plan = ResponsePlan(
        script=TeachingScript(
            script_id="script-1", turn_id="turn-1", concept_id="fractions",
            pedagogical_action="EXPLAIN", response_kind=ResponseKind.INSTRUCTIONAL,
            device_profile={}, beats=[beat], validation={"ok": True},
        ),
        intended_modalities=("speech",), approved_modalities=("speech",),
    )
    manifest = GroundedManifest(
        evidence=(GroundedEvidence(
            id="chunk-1", type="chunk", why="textbook",
            content={"text": "Equivalent fractions have the same value."},
        ),), bridge_ids=(), schema_ids=(), ranking_trace={}, cohesion_log=(),
        snapshot={}, band_reason="fixture", grounding="manifest_only", need="explain",
    )
    return ResponseGenerationRequest(
        turn_input=TurnInput(
            turn_id="turn-1", learner_id="learner-1",
            interaction={"text": "Explain that again", "answer_budget": budget or {"max_words": 12, "max_sentences": 2}},
            device=DeviceCapabilities(speech=True, display=figure),
            budgets=TurnBudgets(total_ms=30_000),
        ),
        pedagogical=PedagogicalDecision(
            action="EXPLAIN", need="explain", reason="fixture", mode="EXPLAIN"
        ),
        retrieval=RetrievalResult(manifest=manifest), response_plan=plan,
        state=ResponseGenerationStateView(
            history=({"role": "student", "text": "What are fractions?"},),
            clarification=clarification, figure_on_screen=figure,
        ),
        deterministic_spoken=spoken, stream=stream,
    )


class ResponseGenerationTests(unittest.TestCase):
    def test_grounded_prompt_keeps_action_context_budget_and_screen_policy(self):
        gateway = ReplayModelGateway(["Fractions name equal parts. They can look different."])
        outcome = ResponseGeneration(gateway).generate(
            request(figure=True, clarification=True)
        )

        self.assertTrue(outcome.valid)
        prompt = gateway.calls[0].prompt
        self.assertIn("Pedagogical action for this turn: EXPLAIN", prompt)
        self.assertIn("Equivalent fractions have the same value.", prompt)
        self.assertIn("RECENT CONVERSATION", prompt)
        self.assertIn("at most 12 words and 2 sentence", prompt)
        self.assertIn("figure on the screen", prompt)
        self.assertIn("different, simpler way", prompt)

    def test_deterministic_assessment_line_never_calls_model(self):
        gateway = ReplayModelGateway([])
        outcome = ResponseGeneration(gateway).generate(
            request(spoken="What is one half plus one half?")
        )
        self.assertEqual(outcome.value.answer, "What is one half plus one half?")
        self.assertEqual(gateway.statistics().calls, 0)

    def test_streams_only_final_budgeted_answer_and_backends_have_parity(self):
        chunks = []
        batch = ReplayModelGateway(["Fractions are equal parts. One half means one of two equal parts."])
        streamed = ReplayModelGateway([["Fractions are equal ", "parts. ",
                                        "One half means one of two equal parts."]])
        left = ResponseGeneration(batch).generate(request())
        right = ResponseGeneration(streamed).generate(request(stream=chunks.append))
        self.assertEqual(left.value.answer, right.value.answer)
        self.assertEqual("".join(chunks), right.value.answer)
        self.assertLessEqual(len(right.value.answer.split()), 12)

    def test_timeout_and_empty_output_emit_typed_safe_non_assessing_fallback(self):
        for response, cause in ((TimeoutError("late"), "model_timeout"), ("", "empty_output")):
            with self.subTest(cause=cause):
                outcome = ResponseGeneration(ReplayModelGateway([response])).generate(request())
                self.assertTrue(outcome.valid)
                self.assertFalse(outcome.value.assessing)
                self.assertEqual(outcome.value.answer,
                                 "I couldn't prepare a grounded explanation just now. Let's try again.")
                self.assertEqual(outcome.failures[0].cause, cause)
                self.assertEqual(outcome.failures[0].capability, "response_generation")


class ModelGatewayTests(unittest.TestCase):
    def test_replay_gateway_records_calls_and_constructs_once(self):
        gateway = ReplayModelGateway(["one", "two"])
        gateway.generate(ModelCall(prompt="a", max_output_tokens=10))
        gateway.generate(ModelCall(prompt="b", max_output_tokens=10))
        stats = gateway.statistics()
        self.assertEqual(stats.calls, 2)
        self.assertEqual(stats.client_constructions, 1)


if __name__ == "__main__":
    unittest.main()
