import unittest

from presentation import Presentation, PresentationRequest
from response_generation import GeneratedResponse
from response_layer.contracts import Beat, TeachingScript, VisualIntent, VisualType
from response_planning import ResponsePlan
from runtime.contracts import DeviceCapabilities, TurnBudgets, TurnInput, RealizationStatus


def request(*, display=False, visual=None, speech=None, interrupted=None, items=()):
    beat = Beat(beat_id="b1", pedagogical_step="explain", visual_intent=visual)
    plan = ResponsePlan(
        script=TeachingScript(script_id="s1", turn_id="t1", concept_id="c1",
                              pedagogical_action="EXPLAIN", response_kind="instructional",
                              device_profile={}, beats=[beat], validation={"ok": True}),
        intended_modalities=("speech", "display") if visual or items else ("speech",),
        approved_modalities=("speech", "display") if visual or items else ("speech",),
    )
    return PresentationRequest(
        turn_input=TurnInput(turn_id="t1", learner_id="l1", interaction={},
                             device=DeviceCapabilities(display=display),
                             budgets=TurnBudgets(total_ms=1000)),
        response_plan=plan,
        generated_response=GeneratedResponse(speech or r"Use \frac{1}{2}.", False, "replay"),
        speech=(lambda text: None), display=(lambda item: None) if display else None,
        interrupted=interrupted, display_items=items,
    )


class PresentationTests(unittest.TestCase):
    def test_sanitizes_speech_and_marks_it_delivered(self):
        spoken = []
        req = request(speech=r"Use \frac{1}{2}.")
        req = PresentationRequest(**{**req.__dict__, "speech": spoken.append})
        outcome = Presentation().realize(req)
        self.assertEqual(outcome.value.status, RealizationStatus.COMPLETE)
        self.assertEqual(outcome.value.delivered, ("speech",))
        self.assertNotIn("\\frac", spoken[0])

    def test_retrieved_crop_and_device_metadata_are_sent_to_display(self):
        shown, events = [], []
        visual = VisualIntent(VisualType.RETRIEVED_CROP, True, asset_ref="crop-7")
        req = request(display=True, visual=visual)
        req = PresentationRequest(**{**req.__dict__, "display": shown.append, "emit": events.append})
        outcome = Presentation().realize(req)
        self.assertEqual(outcome.value.status, RealizationStatus.COMPLETE)
        self.assertEqual(outcome.value.delivered, ("speech", "display"))
        self.assertEqual(shown[0]["asset_ref"], "crop-7")
        self.assertEqual([event.kind for event in events], ["speech", "display"])

    def test_optional_display_failure_degrades_to_speech_only(self):
        visual = VisualIntent(VisualType.RETRIEVED_CROP, True, asset_ref="crop-7")
        outcome = Presentation().realize(request(display=False, visual=visual))
        self.assertEqual(outcome.value.status, RealizationStatus.DEGRADED)
        self.assertEqual(outcome.value.delivered, ("speech",))
        self.assertEqual(outcome.failures[0].cause, "display_unavailable")

    def test_interruption_is_reported(self):
        outcome = Presentation().realize(request(interrupted=lambda: True))
        self.assertEqual(outcome.value.status, RealizationStatus.INTERRUPTED)
        self.assertEqual(outcome.failures[0].cause, "stream_interrupted")


if __name__ == "__main__":
    unittest.main()
