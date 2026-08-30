"""The personal-data turn topology and its two deadlines (slice 13).

These live in ``runtime/tests/`` for the same reason the safety topology tests do: the
ordering is a **coordinator** property, not a package one. They are offline and free —
the detector is always driven through its ``call_fn`` seam.

The topology under test (PERSONAL_DATA_CONTRACT.md §2, §7, §8):

    Utterance Intake produces normalized_text
    personal-data call dispatched IMMEDIATELY after it
    ...perception runs...
    the verdict is resolved before Interaction Control writes its analytics row
    persisting sinks fail CLOSED; generation fails OPEN

The two properties that are worth more than the rest, and the reason this file exists:

* a stubbed **timeout** produces a row with **no transcript** — never a row that reads
  as "this child disclosed nothing";
* a stubbed **landed verdict** produces a row with placeholders and class labels, and
  the maths in the same utterance is untouched.
"""

from __future__ import annotations

import time
import unittest

from interaction_control import (
    InteractionControlRequest,
    InteractionDecision,
    InteractionDisposition,
)
from perception import Perception, PerceptionRequest
from perception.route import RouteResult
from personal_data import (
    PersonalDataDetector,
    PersonalDataGateway,
    VerdictStatus,
)
from personal_data import config as pd_config
from runtime.contracts import (
    DeviceCapabilities,
    ModuleOutcome,
    TurnBudgets,
    TurnInput,
    Utterance,
    UtteranceProvenance,
    UtteranceSource,
)
from runtime.coordinator import TurnCoordinator
from runtime.supervisor import RuntimeSupervisor
from utterance_intake import UtteranceIntake

from .test_coordinator import _SuccessfulLegacyAdapter


_ANALYSIS = {
    "normalized_text": "", "signals": [], "signal_scores": {},
    "concept": {"concept_id": None, "concept_confidence": 0.0,
                "secondary_concepts": [], "abstained": True},
    "cognitive_update": {},
    "state_deltas": {"global": {}, "concept_id": None,
                     "concept_flags": [], "signals": []},
}


class _Adapter(_SuccessfulLegacyAdapter):
    """Supplies a perception request, a writable session, and records what the legacy
    turn was handed — which is where the OTHER two converted sinks live."""

    def __init__(self, session: dict | None = None) -> None:
        self.session = session if session is not None else {"context": []}
        self.executed: list[dict] = []

    def interaction_request(self, turn_input: TurnInput) -> InteractionControlRequest:
        return InteractionControlRequest(turn_input=turn_input, session=self.session)

    def perception_request(self, turn_input: TurnInput):
        return PerceptionRequest(turn_input=turn_input, session={})

    def execute(self, turn_input, interaction=None, **kwargs):
        self.executed.append(kwargs)
        return super().execute(turn_input, interaction=interaction)


class _RecordingGateway:
    def __init__(self, ledger: list[tuple[str, float]]) -> None:
        self._ledger = ledger

    def observe(self, text, session, current_concept):
        self._ledger.append(("perception_produced", time.monotonic()))
        return RouteResult(primary="LEARNING"), dict(_ANALYSIS, normalized_text=text)


class _RecordingControl:
    """Stands in for Interaction Control and records the request it was handed."""

    def __init__(self, ledger: list[tuple[str, float]] | None = None) -> None:
        self._ledger = ledger if ledger is not None else []
        self.requests: list[InteractionControlRequest] = []

    def control(self, request: InteractionControlRequest):
        self._ledger.append(("control_ran", time.monotonic()))
        self.requests.append(request)
        return ModuleOutcome(value=InteractionDecision(
            disposition=InteractionDisposition.COMPLETE,
            text="hello",
            compatibility={"action": "SOCIAL", "answer": "ok", "display": [],
                           "session_ended": False},
        ))


def _detector(payload=None, *, delay: float = 0.0, ledger=None, boom=False,
              calls=None):
    def call_fn(prompt, static_block):
        if ledger is not None:
            ledger.append(("personal_data_called", time.monotonic()))
        if calls is not None:
            calls.append(prompt)
        if delay:
            time.sleep(delay)
        if boom:
            raise RuntimeError("transport exploded")
        return payload

    return PersonalDataDetector(call_fn=call_fn)


class _RecordingGatewayWrapper(PersonalDataGateway):
    """Records the moment ``dispatch`` is called.

    The *dispatch* is the orderable event, not the worker thread's first instruction:
    the call runs in parallel by design, so asserting the thread wins a race against
    perception would be asserting on the scheduler.
    """

    def __init__(self, detector, ledger) -> None:
        super().__init__(detector)
        self._ledger = ledger

    def dispatch(self, **kwargs):
        self._ledger.append(("personal_data_dispatched", time.monotonic()))
        self.last_kwargs = kwargs
        return super().dispatch(**kwargs)


def _turn(text: str = "hello", turn_id: str = "turn-pd") -> TurnInput:
    return TurnInput(
        turn_id=turn_id, learner_id="learner-1",
        interaction={"text": text},
        device=DeviceCapabilities(), budgets=TurnBudgets(total_ms=10_000),
        utterance=Utterance(
            text=text, source=UtteranceSource.TYPED,
            provenance=UtteranceProvenance(
                utterance_id=f"utt-{turn_id}", captured_at="2026-08-28T00:00:00Z"),
        ),
    )


def _coordinator(control, detector, *, adapter=None, perception=None, intake=None,
                 ledger=None):
    supervisor = RuntimeSupervisor()
    supervisor.ready()
    gateway = (
        _RecordingGatewayWrapper(detector, ledger) if ledger is not None
        else PersonalDataGateway(detector)
    )
    coordinator = TurnCoordinator(
        adapter=adapter or _Adapter(),
        interaction_control=control,
        utterance_intake=intake,
        perception=perception,
        personal_data=gateway,
        supervisor=supervisor,
    )
    return coordinator, gateway


def _payload(*pairs):
    return {"findings": [
        {"identifier_class": cls, "value": value} for cls, value in pairs
    ]}


# --------------------------------------------------------------------------
class DispatchOrderingTests(unittest.TestCase):
    def test_the_call_is_dispatched_before_perception_is_asked_for_anything(self) -> None:
        ledger: list[tuple[str, float]] = []
        control = _RecordingControl(ledger)
        coordinator, _ = _coordinator(
            control, _detector(_payload(), ledger=ledger),
            perception=Perception(_RecordingGateway(ledger)), ledger=ledger,
        )

        coordinator.run(_turn("teach fractions"))

        order = [name for name, _ in ledger]
        self.assertLess(
            order.index("personal_data_dispatched"),
            order.index("perception_produced"),
        )
        # ...and the verdict is resolved before the analytics row is written.
        self.assertLess(
            order.index("personal_data_called"), order.index("control_ran")
        )

    def test_the_call_sees_the_normalized_text_intake_published(self) -> None:
        # §4: redaction is exact-match on this exact string. Handing the detector one
        # form and the redactor another would fail every turn closed.
        ledger: list[tuple[str, float]] = []
        control = _RecordingControl()
        coordinator, gateway = _coordinator(
            control, _detector(_payload()), intake=UtteranceIntake(), ledger=ledger,
        )

        coordinator.run(_turn("  my  number   is 98765  "))

        self.assertEqual(gateway.last_kwargs["text"], "my number is 98765")

    def test_the_call_is_memoized_on_the_utterance_id_not_the_turn_id(self) -> None:
        control = _RecordingControl()
        coordinator, gateway = _coordinator(
            control, _detector(_payload()), intake=UtteranceIntake(), ledger=[],
        )
        coordinator.run(_turn("hello"))
        self.assertEqual(gateway.last_kwargs["utterance_id"], "utt-turn-pd")

    def test_the_prompt_context_is_one_preceding_exchange(self) -> None:
        # §14, driven through a REAL frozen session, which is where the safety-side
        # equivalent broke: slicing a frozen tuple of mappingproxies before thawing it
        # raises "cannot pickle 'mappingproxy'".
        session = {"context": [
            {"role": "student", "text": "one"},
            {"role": "wini", "text": "two"},
            {"role": "student", "text": "three"},
            {"role": "wini", "text": "what is your number?"},
        ]}
        control = _RecordingControl()
        coordinator, gateway = _coordinator(
            control, _detector(_payload()), adapter=_Adapter(session),
            intake=UtteranceIntake(), ledger=[],
        )

        coordinator.run(_turn("it's 98765"))

        context = gateway.last_kwargs["context"]
        self.assertEqual(len(context.recent_context), 2)
        self.assertEqual(context.recent_context[-1]["text"], "what is your number?")


class FailClosedTests(unittest.TestCase):
    """§8: persisting sinks fail closed. The transcript is withheld, never faked."""

    def _row(self, detector, text="my number is 98765", *, timeout=None):
        control = _RecordingControl()
        adapter = _Adapter()
        coordinator, _ = _coordinator(
            control, detector, adapter=adapter, intake=UtteranceIntake(), ledger=[],
        )
        original = pd_config.PERSONAL_DATA_TIMEOUT_S
        if timeout is not None:
            pd_config.PERSONAL_DATA_TIMEOUT_S = timeout
        try:
            coordinator.run(_turn(text))
        finally:
            pd_config.PERSONAL_DATA_TIMEOUT_S = original
        return control.requests[0].personal_data, adapter.executed[0]

    def test_a_stubbed_timeout_withholds_the_transcript(self) -> None:
        redaction, executed = self._row(
            _detector(_payload(), delay=0.4), timeout=0.05
        )
        self.assertIs(redaction.status, VerdictStatus.UNAVAILABLE)
        self.assertIsNone(redaction.redacted)
        self.assertEqual(redaction.stamp, "privacy_unavailable")
        # ...and the same redaction reaches the legacy turn's sinks.
        self.assertIs(executed["personal_data"], redaction)

    def test_a_detector_crash_withholds_the_transcript(self) -> None:
        redaction, _ = self._row(_detector(boom=True))
        self.assertIs(redaction.status, VerdictStatus.UNAVAILABLE)
        self.assertIsNone(redaction.redacted)

    def test_an_empty_response_is_not_a_clean_turn(self) -> None:
        # The thinking-token overrun. This is the single failure mode the whole
        # package exists to prevent: it must not read as "no personal data".
        redaction, _ = self._row(_detector(None))
        self.assertIs(redaction.status, VerdictStatus.UNAVAILABLE)
        self.assertIsNone(redaction.redacted)

    def test_no_detector_wired_is_stamped_and_withholds(self) -> None:
        control = _RecordingControl()
        supervisor = RuntimeSupervisor()
        supervisor.ready()
        adapter = _Adapter()
        TurnCoordinator(
            adapter=adapter, interaction_control=control,
            utterance_intake=UtteranceIntake(), supervisor=supervisor,
        ).run(_turn("my number is 98765"))
        # `None` rather than an UNAVAILABLE redaction: nothing ran, and the sinks
        # already treat None as fail-closed. The difference is visible to a reader of
        # the code, not to a sink.
        self.assertIsNone(control.requests[0].personal_data)
        self.assertIsNone(adapter.executed[0]["personal_data"])


class LandedVerdictTests(unittest.TestCase):
    """The happy path, and the property that guards the lesson."""

    def _redaction(self, text, *pairs):
        control = _RecordingControl()
        coordinator, _ = _coordinator(
            control, _detector(_payload(*pairs)), intake=UtteranceIntake(), ledger=[],
        )
        coordinator.run(_turn(text))
        return control.requests[0].personal_data

    def test_the_named_identifier_is_replaced_and_the_maths_is_not(self) -> None:
        redaction = self._redaction(
            "my number is 9876543210 and 9 x 25 x 17 = 3825",
            ("PHONE", "9876543210"),
        )
        self.assertEqual(
            redaction.redacted.text,
            "my number is <PHONE> and 9 x 25 x 17 = 3825",
        )
        self.assertEqual(redaction.class_values, ["PHONE"])

    def test_a_maths_only_turn_is_untouched_and_carries_no_classes(self) -> None:
        redaction = self._redaction("9 x 25 x 17 = 3825")
        self.assertEqual(redaction.redacted.text, "9 x 25 x 17 = 3825")
        self.assertEqual(redaction.class_values, [])
        self.assertFalse(redaction.found)

    def test_an_unmatchable_substring_stamps_and_withholds(self) -> None:
        # §4: the class is still recorded, the transcript is not written.
        redaction = self._redaction("my number is 98765", ("PHONE", "not-in-text"))
        self.assertIs(redaction.status, VerdictStatus.LANDED)
        self.assertIsNone(redaction.redacted)
        self.assertEqual(redaction.stamp, "redaction_incomplete")
        self.assertEqual(redaction.class_values, ["PHONE"])

    def test_the_verdict_never_crosses_the_seam(self) -> None:
        # §4: the identifier-bearing verdict is consumed by the redactor and dropped.
        # What Interaction Control holds is placeholder text and labels.
        redaction = self._redaction("my number is 98765", ("PHONE", "98765"))
        self.assertFalse(hasattr(redaction, "findings"))
        self.assertNotIn("98765", repr(redaction))
        self.assertNotIn("98765", redaction.redacted.text)


class EndToEndThroughTheFacadeTests(unittest.TestCase):
    """The whole vertical, through the real production construction site.

    ``TutorLoopCompatibilityFacade`` -> ``TurnCoordinator`` -> ``LegacyTurnAdapter`` ->
    ``_legacy_turn(_redaction=...)``. The two converted sinks that live in
    ``tutor_loop`` (``_log_shift`` and the generation prompt) read that kwarg, so this
    is what proves they can be reached at all.
    """

    class _LearningControl:
        """Continues into the legacy turn, which a COMPLETE decision would bypass —
        and bypassing it is exactly what would make this test pass while proving
        nothing."""

        def control(self, request: InteractionControlRequest):
            return ModuleOutcome(value=InteractionDecision(
                disposition=InteractionDisposition.CONTINUE_LEARNING,
                text="hello",
                analysis=_ANALYSIS,
            ))

    def _run(self, detector, text="my number is 98765 and 2+2=4"):
        from types import SimpleNamespace

        from runtime.compatibility import TutorLoopCompatibilityFacade

        received: dict = {}
        state = SimpleNamespace(
            data={"learner_id": "learner-1", "concept_states": {}, "session": {}},
        )
        facade = TutorLoopCompatibilityFacade(
            legacy_turn=lambda _text, **kwargs: received.update(kwargs) or {
                "action": "EXPLAIN", "answer": "continue", "display": [],
            },
            commit_state=lambda: None,
            state=state,
            interaction_control=self._LearningControl(),
            personal_data=PersonalDataGateway(detector),
        )
        facade.turn(text, turn_id="turn-e2e", learner_id="learner-1")
        return received

    def test_the_redaction_reaches_the_legacy_turn(self) -> None:
        received = self._run(_detector(_payload(("PHONE", "98765"))))
        redaction = received["_redaction"]
        self.assertIsNotNone(redaction)
        self.assertEqual(
            redaction.redacted.text, "my number is <PHONE> and 2+2=4"
        )
        self.assertEqual(redaction.class_values, ["PHONE"])

    def test_a_failed_call_reaches_it_as_a_withheld_redaction(self) -> None:
        received = self._run(_detector(None))
        self.assertIs(received["_redaction"].status, VerdictStatus.UNAVAILABLE)
        self.assertIsNone(received["_redaction"].redacted)

    def test_the_facade_wires_no_gateway_when_the_flag_is_off(self) -> None:
        # `PERSONAL_DATA_ENABLED` defaults OFF so the offline suite never bills a call.
        # The consequence is §8's fail-closed everywhere, which is why the flag is
        # asserted rather than assumed.
        from types import SimpleNamespace

        from runtime.compatibility import TutorLoopCompatibilityFacade

        self.assertFalse(
            pd_config.PERSONAL_DATA_ENABLED,
            "a test run must never default to billing a Vertex call per turn",
        )
        received: dict = {}
        state = SimpleNamespace(
            data={"learner_id": "learner-1", "concept_states": {}, "session": {}},
        )
        TutorLoopCompatibilityFacade(
            legacy_turn=lambda _text, **kwargs: received.update(kwargs) or {
                "action": "EXPLAIN", "answer": "continue", "display": [],
            },
            commit_state=lambda: None,
            state=state,
            interaction_control=self._LearningControl(),
        ).turn("hello", turn_id="turn-off", learner_id="learner-1")
        self.assertIsNone(received["_redaction"])


class UnauthorizedTurnTests(unittest.TestCase):
    """An UNAUTHORIZED turn still writes an analytics row, so it still needs a verdict."""

    def test_the_call_is_dispatched_even_when_perception_is_skipped(self) -> None:
        control = _RecordingControl()
        calls: list[str] = []
        coordinator, _ = _coordinator(
            control, _detector(_payload(), calls=calls),
            intake=UtteranceIntake(), ledger=[],
        )
        low_confidence = Utterance(
            text="mumbled", source=UtteranceSource.VOICE,
            provenance=UtteranceProvenance(
                utterance_id="utt-low", captured_at="2026-08-28T00:00:00Z",
                recognizer="stub"),
            confidence=0.1,
        )
        turn = TurnInput(
            turn_id="turn-low", learner_id="learner-1",
            interaction={"text": "mumbled"},
            device=DeviceCapabilities(), budgets=TurnBudgets(total_ms=10_000),
            utterance=low_confidence,
        )

        coordinator.run(turn)

        self.assertEqual(len(calls), 1, "an UNAUTHORIZED turn still gets its call")
        self.assertIsNotNone(control.requests[0].personal_data)


if __name__ == "__main__":
    unittest.main()
