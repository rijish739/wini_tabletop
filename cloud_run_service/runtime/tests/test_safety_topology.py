"""Invariant 6 and the turn-level safety properties (slice 12).

These live in ``runtime/tests/`` because the turn topology is a **coordinator**
property, not an Utterance Intake one — putting them under ``utterance_intake/``
would make a module test depend on the coordinator, which the layering rule
forbids. They are offline and free: the detector is always driven through its
``call_fn`` seam, so no test here holds a credential or makes a call.

The topology under test (SAFETY_ROUTE_TAXONOMY.md §7.1):

    safety dispatched FIRST
    perception dispatched immediately after
    perception's output HELD until the safety verdict is analyzed  <- invariant 6
    ...bounded by the 5s envelope, then released degraded with the
       `safety_model_unavailable` stamp

Invariant 6 is **bounded** on purpose. Unbounded was rejected: a hung safety call
would freeze every turn, which trades one child's disclosure for every child's
lesson.
"""

from __future__ import annotations

import time
import unittest

from child_safety import ChildSafetyDetector, ChildSafetyGateway
from utterance_intake import UtteranceIntake
from interaction_control import (
    InteractionControl,
    InteractionControlDependencies,
    InteractionControlRequest,
    InteractionDecision,
    InteractionDisposition,
    SafetySeverity,
)
from perception import Perception, PerceptionRequest
from perception.route import RouteResult
from runtime.contracts import (
    DeviceCapabilities,
    ModuleOutcome,
    TurnBudgets,
    TurnInput,
)
from runtime.coordinator import LOGICAL_TURN_PHASES, LegacyExecution, TurnCoordinator
from runtime.supervisor import RuntimeSupervisor

from .test_coordinator import _SuccessfulLegacyAdapter


# --------------------------------------------------------------------------
# Stubs
# --------------------------------------------------------------------------
_ANALYSIS = {
    "normalized_text": "", "signals": [], "signal_scores": {},
    "concept": {"concept_id": None, "concept_confidence": 0.0,
                "secondary_concepts": [], "abstained": True},
    "cognitive_update": {},
    "state_deltas": {"global": {}, "concept_id": None,
                     "concept_flags": [], "signals": []},
}


class _Adapter(_SuccessfulLegacyAdapter):
    """Supplies a perception request and a session Interaction Control can write."""

    def __init__(self, session: dict | None = None) -> None:
        self.session = session if session is not None else {"context": []}

    def interaction_request(self, turn_input: TurnInput) -> InteractionControlRequest:
        return InteractionControlRequest(turn_input=turn_input, session=self.session)

    def perception_request(self, turn_input: TurnInput):
        return PerceptionRequest(turn_input=turn_input, session={})


class _RecordingGateway:
    """Perception, with the moment it produced its output recorded."""

    def __init__(self, ledger: list[tuple[str, float]]) -> None:
        self._ledger = ledger

    def observe(self, text, session, current_concept):
        self._ledger.append(("perception_produced", time.monotonic()))
        return RouteResult(primary="LEARNING"), dict(_ANALYSIS, normalized_text=text)


class _RecordingControl:
    """Stands in for Interaction Control and records what it was handed, when.

    Interaction Control is where perception's output is *released* to the rest of
    the turn. Recording the arrival here is what makes invariant 6 observable.
    """

    def __init__(self, ledger: list[tuple[str, float]]) -> None:
        self._ledger = ledger
        self.requests: list[InteractionControlRequest] = []

    def control(self, request: InteractionControlRequest):
        self._ledger.append(("perception_released", time.monotonic()))
        self.requests.append(request)
        return ModuleOutcome(value=InteractionDecision(
            disposition=InteractionDisposition.COMPLETE,
            text=str(request.turn_input.interaction.get("text") or ""),
            compatibility={"action": "SOCIAL", "answer": "ok", "display": [],
                           "session_ended": False},
        ))


def _detector(payload=None, *, delay: float = 0.0, ledger=None, boom=False):
    """A ``ChildSafetyDetector`` wired to a stub call, never to Vertex."""

    def call_fn(prompt, static_block):
        if ledger is not None:
            ledger.append(("safety_called", time.monotonic()))
        if delay:
            time.sleep(delay)
        if boom:
            raise RuntimeError("transport exploded")
        return payload

    return ChildSafetyDetector(call_fn=call_fn)


def _turn(text: str = "hello", turn_id: str = "turn-safety") -> TurnInput:
    return TurnInput(
        turn_id=turn_id, learner_id="learner-1",
        interaction={"text": text},
        device=DeviceCapabilities(), budgets=TurnBudgets(total_ms=10_000),
    )


class _RecordingGatewayWrapper(ChildSafetyGateway):
    """Records the moment ``dispatch`` is called.

    The *dispatch* is the orderable event, not the worker thread's first
    instruction: the call runs in parallel by design, so asserting that the thread
    wins the race against perception would be asserting on the scheduler. What the
    topology actually promises is that the call is **started** before perception
    is asked for anything.
    """

    def __init__(self, detector, ledger) -> None:
        super().__init__(detector)
        self._ledger = ledger

    def dispatch(self, **kwargs):
        self._ledger.append(("safety_dispatched", time.monotonic()))
        return super().dispatch(**kwargs)


def _coordinator(control, detector, *, adapter=None, perception=None, intake=None,
                 ledger=None):
    supervisor = RuntimeSupervisor()
    supervisor.ready()
    gateway = (
        _RecordingGatewayWrapper(detector, ledger) if ledger is not None
        else ChildSafetyGateway(detector)
    )
    return TurnCoordinator(
        adapter=adapter or _Adapter(),
        interaction_control=control,
        utterance_intake=intake,
        perception=perception,
        child_safety=gateway,
        supervisor=supervisor,
    )


# --------------------------------------------------------------------------
# Invariant 6
# --------------------------------------------------------------------------
class Invariant6Tests(unittest.TestCase):
    def test_perception_output_is_not_released_before_the_verdict_is_analyzed(self) -> None:
        """The hold. Perception finishes first; its output still waits."""
        ledger: list[tuple[str, float]] = []
        control = _RecordingControl(ledger)
        detector = _detector(
            {"axis_tripped": False, "classes": []}, delay=0.15, ledger=ledger
        )
        coordinator = _coordinator(
            control, detector, perception=Perception(_RecordingGateway(ledger)),
            ledger=ledger,
        )

        coordinator.run(_turn("teach fractions"))

        order = [name for name, _ in ledger]
        # Safety is dispatched FIRST — before perception is asked for anything.
        self.assertLess(
            order.index("safety_dispatched"), order.index("perception_produced")
        )
        # ...and perception's output is released only after the verdict landed.
        self.assertLess(
            order.index("perception_produced"), order.index("perception_released")
        )
        # The hold is real, not incidental: perception finished ~immediately and
        # still waited on the detector's 0.15s.
        stamps = {name: when for name, when in ledger}
        self.assertGreaterEqual(
            stamps["perception_released"] - stamps["perception_produced"], 0.10
        )
        self.assertIsNotNone(control.requests[0].safety)

    def test_the_hold_is_bounded_by_the_envelope_and_releases_degraded(self) -> None:
        """A hung safety call must not freeze the turn — the bound is the point."""
        import child_safety.config as cfg

        original = cfg.SAFETY_TIMEOUT_S
        cfg.SAFETY_TIMEOUT_S = 0.2
        try:
            control = _RecordingControl([])
            detector = _detector({"axis_tripped": False, "classes": []}, delay=3.0)
            coordinator = _coordinator(control, detector)

            started = time.monotonic()
            coordinator.run(_turn())
            elapsed = time.monotonic() - started
        finally:
            cfg.SAFETY_TIMEOUT_S = original

        self.assertLess(elapsed, 2.0, "the hold must be bounded, not unbounded")
        verdict = control.requests[0].safety
        self.assertFalse(verdict.available)
        self.assertEqual(verdict.status.value, "timeout")

    def test_safety_is_dispatched_even_when_perception_is_skipped(self) -> None:
        """Invariant 1: the safety path reads neither authorization nor the
        transcript reading, so an UNAUTHORIZED turn — where perception does not
        run at all — still gets its safety call."""
        from utterance_intake import UtteranceIntake, UtteranceIntakeRequest  # noqa: F401
        from utterance_intake.observation import Authorization

        ledger: list[tuple[str, float]] = []
        control = _RecordingControl(ledger)
        detector = _detector({"axis_tripped": False, "classes": []}, ledger=ledger)

        class _UnauthorizedIntake:
            def observe(self, request):
                from utterance_intake import UtteranceIntake as _UI
                outcome = _UI().observe(request)
                observation = outcome.value
                object.__setattr__(
                    observation, "authorization", Authorization.UNAUTHORIZED
                )
                return outcome

        supervisor = RuntimeSupervisor()
        supervisor.ready()
        turn_input = _turn("mumble")
        coordinator = TurnCoordinator(
            adapter=_Adapter(), interaction_control=control,
            utterance_intake=_UnauthorizedIntake(),
            perception=Perception(_RecordingGateway(ledger)),
            child_safety=_RecordingGatewayWrapper(detector, ledger),
            supervisor=supervisor,
        )
        coordinator.run(_replace_utterance(turn_input))

        order = [name for name, _ in ledger]
        self.assertIn("safety_dispatched", order)
        self.assertNotIn("perception_produced", order)
        self.assertIsNotNone(control.requests[0].safety)


def _replace_utterance(turn_input: TurnInput) -> TurnInput:
    """Attach a typed Utterance so Utterance Intake runs at all."""
    from dataclasses import replace

    from runtime.contracts import Utterance, UtteranceProvenance, UtteranceSource

    return replace(turn_input, utterance=Utterance(
        text=str(turn_input.interaction.get("text") or ""),
        source=UtteranceSource.TYPED,
        provenance=UtteranceProvenance(
            utterance_id="utt-1", captured_at="2026-08-28T00:00:00"
        ),
    ))


# --------------------------------------------------------------------------
# The two stop-ship turn-level properties (ticket 12, final bullet)
# --------------------------------------------------------------------------
def _real_control_dependencies(notifications, logs):
    return InteractionControlDependencies(
        deterministic_route=lambda text: None,
        perception_route=lambda text, session: RouteResult(primary="SOCIAL"),
        analyze=lambda text, current: {
            "normalized_text": text, "concept": {
                "concept_id": None, "concept_confidence": 0.0, "abstained": True},
            "signals": [], "state_deltas": {},
        },
        persona={"identity": "Wini", "style": "Warm",
                 "intents": {"SAFETY": {"scripted": "Please find a trusted adult."},
                             "SOCIAL": {"scripted": "Hi!"}}},
        want_answer=False,
        generation_backend="stub",
        generate_persona=lambda prompt: "generated",
        concept_name=lambda cid: cid or "",
        topic_candidates=lambda text, k: [],
        chapter_for_concept=lambda cid: None,
        wants_different_topic=lambda text: False,
        mode_cue=lambda route: None,
        current_mode=lambda session: "tutor",
        set_mode=lambda session, mode, reason: None,
        consume_mode_offer=lambda session, mode, reason: None,
        consume_test_resume=lambda session, mode, reason: None,
        check_frozen_test=lambda session, mode: None,
        clear_pending_assessment=lambda session, reason: None,
        log_event=logs.append,
        notify_safety=notifications.append,
        now=lambda: "2026-08-28T00:00:00",
    )


class TurnLevelSafetyPropertyTests(unittest.TestCase):
    def test_a_stubbed_critical_reaches_the_case_record(self) -> None:
        """A CRITICAL model verdict must survive the whole turn intact: through the
        hold, through composition, into the case record, out to the notification."""
        notifications: list[dict] = []
        session = {"context": []}
        control = InteractionControl(_real_control_dependencies(notifications, []))
        detector = _detector({
            "axis_tripped": True,
            "classes": ["SELF_HARM"],
            "imminence_cue": True,
            "named_means": True,
            "weapon": False,
            "arranged_meeting": False,
        })
        coordinator = _coordinator(
            control, detector, adapter=_Adapter(session)
        )

        coordinator.run(_turn("i am going to do it tonight"))

        self.assertEqual(len(notifications), 1)
        record = notifications[0]
        self.assertEqual(record["severity"], SafetySeverity.CRITICAL.value)
        self.assertEqual(record["classes"], ["SELF_HARM"])
        self.assertTrue(record["imminence_cue"])
        self.assertEqual(record["model_status"], "ok")
        self.assertNotIn("safety_model_unavailable", record["stamps"])
        # §14.1: self-contained. A reviewer never reproduces the call.
        self.assertEqual(record["model_verdict"]["classes"], ["SELF_HARM"])
        self.assertIn("prompt_version", record["model_verdict"])
        self.assertEqual(
            [f["source"] for f in record["findings"]], ["MODEL"]
        )
        # ...and no raw child text anywhere in it.
        import json
        self.assertNotIn("tonight", json.dumps(record))

    def test_a_stubbed_timeout_releases_degraded_with_the_stamp(self) -> None:
        """The net opens a record the model could not. Axis only, ELEVATED,
        never CRITICAL (§8) — and the degradation is stamped, never silent."""
        import child_safety.config as cfg

        notifications: list[dict] = []
        session = {"context": []}
        control = InteractionControl(_real_control_dependencies(notifications, []))
        original = cfg.SAFETY_TIMEOUT_S
        cfg.SAFETY_TIMEOUT_S = 0.2
        try:
            detector = _detector({"axis_tripped": True, "classes": ["SELF_HARM"]},
                                 delay=3.0)
            coordinator = _coordinator(
                control, detector, adapter=_Adapter(session),
                intake=UtteranceIntake(),
            )
            coordinator.run(_replace_utterance(_turn("i want to kill myself")))
        finally:
            cfg.SAFETY_TIMEOUT_S = original

        self.assertEqual(len(notifications), 1)
        record = notifications[0]
        self.assertEqual(record["severity"], SafetySeverity.ELEVATED.value)
        self.assertEqual(record["classes"], ["UNSPECIFIED_CONCERN"])
        self.assertIn("safety_model_unavailable", record["stamps"])
        self.assertIn("degraded", record["stamps"])
        self.assertEqual(record["model_status"], "timeout")

    def test_the_prompt_sees_a_count_a_severity_and_the_last_exchange_only(self) -> None:
        """§7.5, driven through a REAL frozen session — which is where this broke:
        a frozen session holds `context` as a tuple of mappingproxies, and slicing
        before thawing hands `deep_thaw` a plain list that `copy.deepcopy` cannot
        pickle. Every other test here used an empty context and missed it."""
        prompts: list[str] = []
        session = {
            "context": [
                {"role": "student", "text": "first"},
                {"role": "wini", "text": "second"},
                {"role": "student", "text": "third"},
            ],
            "safety_accumulator": {"count": 4, "max_severity": "CRITICAL"},
        }

        def call_fn(prompt, static_block):
            prompts.append(prompt)
            return {"axis_tripped": False, "classes": []}

        coordinator = _coordinator(
            _RecordingControl([]), ChildSafetyDetector(call_fn=call_fn),
            adapter=_Adapter(session),
        )
        coordinator.run(_turn("what is 2+2"))

        self.assertEqual(len(prompts), 1)
        prompt = prompts[0]
        self.assertIn("prior_safety_findings: 4", prompt)
        self.assertIn("prior_max_severity: CRITICAL", prompt)
        # session["context"][-2:] — the one preceding exchange, and no more.
        self.assertIn("second", prompt)
        self.assertIn("third", prompt)
        self.assertNotIn("first", prompt)

    def test_the_divergence_metric_is_published_and_carries_no_classes(self) -> None:
        """§10.4: monitoring only. It never gates a release and never alters a
        verdict — this asserts it is emitted and that it says nothing it may not."""
        import debug_logger

        emitted: list[tuple] = []
        original = debug_logger.emit
        debug_logger.emit = lambda level, event, **kw: emitted.append((event, kw))
        try:
            control = InteractionControl(_real_control_dependencies([], []))
            coordinator = _coordinator(
                control,
                _detector({"axis_tripped": True, "classes": ["SELF_HARM"]}),
                adapter=_Adapter({"context": []}), intake=UtteranceIntake(),
            )
            coordinator.run(_replace_utterance(_turn("i want to kill myself")))
        finally:
            debug_logger.emit = original

        rows = [kw for event, kw in emitted if event == "safety_divergence"]
        self.assertTrue(rows)
        self.assertEqual(rows[0]["divergence"], "both")
        self.assertEqual(
            set(rows[0]),
            {"net_tripped", "model_tripped", "model_available", "divergence"},
        )

    def test_a_detector_crash_is_a_non_answer_not_a_clear_turn(self) -> None:
        """The failure mode that motivates the whole arrangement: a broken safety
        call must never read as 'no concern'."""
        notifications: list[dict] = []
        control = InteractionControl(_real_control_dependencies(notifications, []))
        coordinator = _coordinator(
            control, _detector(boom=True), adapter=_Adapter({"context": []}),
            intake=UtteranceIntake(),
        )

        coordinator.run(_replace_utterance(_turn("i want to kill myself")))

        self.assertEqual(len(notifications), 1)
        self.assertIn("safety_model_unavailable", notifications[0]["stamps"])
        self.assertEqual(notifications[0]["model_status"], "error")


if __name__ == "__main__":
    unittest.main()
