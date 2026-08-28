"""Composition with the model verdict — the sources unioned, severity derived once.

A **separate file** from `test_safety_composition.py` on purpose. That file is the
legacy-20 regression, frozen from ticket 01 and explicitly not edited at the
`child_safety` cutover; the thing under it changed instead. These are the new
rules the cutover introduced, so they belong beside it, not inside it.

`docs/architecture/SAFETY_ROUTE_TAXONOMY.md` §5 and §6 are normative. The one
sentence everything here tests: **nothing may ever remove a finding, whatever made
it.**
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from child_safety import ModelSafetyVerdict, SafetyModelStatus
from interaction_control import (
    InteractionDisposition,
    SafetySeverity,
    compose_safety_verdict,
    derive_severity,
    union_late,
)
from utterance_intake.intake import _lexicon_safety, normalize_text
from utterance_intake.observation import SafetyClass, SafetySource

_PROMPT, _SCHEMA = "p-v1", "s-v1"


def _model(classes=("SELF_HARM",), *, status=SafetyModelStatus.OK, **flags):
    if not status.answered:
        return ModelSafetyVerdict.unavailable(
            status=status, model_id="m", model_pinned=False,
            prompt_version=_PROMPT, schema_version=_SCHEMA,
        )
    classes = frozenset(SafetyClass(c) for c in classes)
    return ModelSafetyVerdict(
        tripped=bool(classes), classes=classes,
        imminence_cue=flags.pop("imminence_cue", False),
        status=status, model_id="m", model_pinned=False,
        prompt_version=_PROMPT, schema_version=_SCHEMA, **flags,
    )


class SeverityDerivationTests(unittest.TestCase):
    """§5, and the only site that may implement it."""

    def test_no_class_means_no_severity(self) -> None:
        self.assertIsNone(derive_severity(classes=frozenset()))

    def test_imminence_with_any_class_is_critical(self) -> None:
        self.assertIs(
            derive_severity(
                classes=frozenset({SafetyClass.UNSPECIFIED_CONCERN}),
                imminence_cue=True,
            ),
            SafetySeverity.CRITICAL,
        )

    def test_bare_ideation_is_elevated_not_critical(self) -> None:
        """Enumerated in the taxonomy's exception list *before* implementation, so
        it is not discovered at test time: "i want to die" with no means and no
        imminence reads an emergency number at a child who did not need one."""
        self.assertIs(
            derive_severity(classes=frozenset({SafetyClass.SELF_HARM})),
            SafetySeverity.ELEVATED,
        )

    def test_a_named_means_makes_self_harm_critical(self) -> None:
        self.assertIs(
            derive_severity(
                classes=frozenset({SafetyClass.SELF_HARM}), named_means=True
            ),
            SafetySeverity.CRITICAL,
        )

    def test_evidence_flags_are_matched_to_their_own_class(self) -> None:
        """A weapon does not make *self-harm* critical; it makes a threat critical."""
        self.assertIs(
            derive_severity(classes=frozenset({SafetyClass.SELF_HARM}), weapon=True),
            SafetySeverity.ELEVATED,
        )
        self.assertIs(
            derive_severity(
                classes=frozenset({SafetyClass.THREAT_BY_CHILD}), weapon=True
            ),
            SafetySeverity.CRITICAL,
        )


class CompositionTests(unittest.TestCase):
    def test_on_a_healthy_turn_the_model_verdict_is_the_verdict(self) -> None:
        verdict = compose_safety_verdict(model=_model(["HARM_BY_OTHER"]))
        self.assertTrue(verdict.tripped)
        self.assertEqual(verdict.classes, frozenset({SafetyClass.HARM_BY_OTHER}))
        self.assertFalse(verdict.degraded)
        self.assertIs(verdict.severity, SafetySeverity.ELEVATED)

    def test_the_outage_net_does_not_contribute_on_a_healthy_turn(self) -> None:
        """§8: on a healthy turn the net is not the verdict. It is still computed
        every turn — the divergence monitor reads it — but it adds nothing here."""
        lexicon = _lexicon_safety(normalize_text("i want to kill myself"))
        self.assertTrue(lexicon.tripped)
        verdict = compose_safety_verdict(
            lexicon=lexicon, model=_model(["PEER_AT_RISK"])
        )
        self.assertEqual(verdict.classes, frozenset({SafetyClass.PEER_AT_RISK}))
        self.assertNotIn(SafetySource.LEXICON, verdict.sources)

    def test_the_outage_net_contributes_only_when_the_model_did_not_answer(self) -> None:
        lexicon = _lexicon_safety(normalize_text("i want to kill myself"))
        verdict = compose_safety_verdict(
            lexicon=lexicon, model=_model(status=SafetyModelStatus.TIMEOUT)
        )
        self.assertTrue(verdict.tripped)
        self.assertTrue(verdict.degraded)
        self.assertTrue(verdict.model_unavailable)
        self.assertEqual(
            verdict.classes, frozenset({SafetyClass.UNSPECIFIED_CONCERN})
        )

    def test_the_net_can_never_produce_critical(self) -> None:
        """The whole point of the demotion: no emergency-resource script fires off
        a regex, whatever the words were."""
        lexicon = _lexicon_safety(normalize_text("i am going to kill myself tonight"))
        verdict = compose_safety_verdict(
            lexicon=lexicon, model=_model(status=SafetyModelStatus.ERROR)
        )
        self.assertIs(verdict.severity, SafetySeverity.ELEVATED)

    def test_history_may_raise_severity_but_never_lower_it(self) -> None:
        raised = compose_safety_verdict(
            model=_model(["SELF_HARM"]), prior_max_severity="CRITICAL"
        )
        self.assertIs(raised.severity, SafetySeverity.CRITICAL)
        kept = compose_safety_verdict(
            model=_model(["SELF_HARM"], imminence_cue=True),
            prior_max_severity="ELEVATED",
        )
        self.assertIs(kept.severity, SafetySeverity.CRITICAL)

    def test_history_cannot_lift_the_degraded_ceiling(self) -> None:
        """Inheriting an earlier turn's CRITICAL in degraded mode would fire the
        emergency script on evidence the net is not allowed to produce. The earlier
        record keeps its own CRITICAL; this is a refusal to upgrade, not a
        downgrade."""
        lexicon = _lexicon_safety(normalize_text("i want to kill myself"))
        verdict = compose_safety_verdict(
            lexicon=lexicon, model=_model(status=SafetyModelStatus.TIMEOUT),
            prior_max_severity="CRITICAL",
        )
        self.assertIs(verdict.severity, SafetySeverity.ELEVATED)

    def test_perception_bit_is_axis_only_and_never_a_class(self) -> None:
        verdict = compose_safety_verdict(perception_safety_alert=True)
        self.assertEqual(
            verdict.classes, frozenset({SafetyClass.UNSPECIFIED_CONCERN})
        )
        self.assertIn(SafetySource.PERCEPTION_BIT, verdict.sources)

    def test_perception_unions_with_the_model_and_never_replaces_it(self) -> None:
        verdict = compose_safety_verdict(
            perception_safety_alert=True, model=_model(["UNSAFE_CONTACT"])
        )
        self.assertEqual(
            verdict.classes,
            frozenset({SafetyClass.UNSAFE_CONTACT, SafetyClass.UNSPECIFIED_CONCERN}),
        )

    def test_a_negative_model_verdict_does_not_clear_perceptions_bit(self) -> None:
        """Union-only, stated as the case that would break it."""
        verdict = compose_safety_verdict(
            perception_safety_alert=True, model=_model([])
        )
        self.assertTrue(verdict.tripped)

    def test_caregiver_implicated_is_lexicon_only_and_survives_a_healthy_turn(self) -> None:
        """§4.1: the flag deliberately over-triggers and only ever makes the
        response language safer, so it contributes in both modes."""
        lexicon = SimpleNamespace(
            tripped=True, caregiver_implicated=True, findings=frozenset()
        )
        verdict = compose_safety_verdict(lexicon=lexicon, model=_model(["HARM_BY_OTHER"]))
        self.assertTrue(verdict.caregiver_implicated)

    def test_analytics_carry_tripped_and_severity_and_nothing_else(self) -> None:
        """§14's write boundary. The class set is redacted of phrases but is still
        a disclosure category — it goes to the case record only."""
        analytics = compose_safety_verdict(model=_model(["HARM_BY_OTHER"])).analytics()
        self.assertEqual(set(analytics), {"safety_alert", "safety_severity"})


class TranscriptStampTests(unittest.TestCase):
    """§9: the stamps ride on the verdict and never gate it."""

    def test_an_unconfirmed_transcript_still_trips_at_full_severity(self) -> None:
        verdict = compose_safety_verdict(
            model=_model(["SELF_HARM"], imminence_cue=True),
            transcript_unconfirmed=True,
        )
        self.assertTrue(verdict.tripped)
        self.assertTrue(verdict.transcript_unconfirmed)
        self.assertIs(verdict.severity, SafetySeverity.CRITICAL)

    def test_a_discarded_transcript_still_produces_a_finding(self) -> None:
        verdict = compose_safety_verdict(
            model=_model(["SELF_HARM"]), transcript_discarded=True
        )
        self.assertTrue(verdict.tripped)
        self.assertTrue(verdict.transcript_discarded)


class GateDemotionTests(unittest.TestCase):
    """The demotion, at the routing seam.

    `gates.gate()` still returns `primary="SAFETY", safety_alert=True` when the
    lexicon matches — that is the outage net doing its job. But §6.3 says the net
    **does not contribute on a healthy turn**, so when the model answers and finds
    no concern, that gate route must not survive as a safety turn.

    The failure this prevents: the child is told to find a trusted adult, analytics
    record `safety_alert: true`, and **nobody is notified** — a safety turn the
    child experiences with no case record behind it.
    """

    def _run(self, model):
        import interaction_control.tests.test_interaction_control as harness
        from interaction_control import InteractionControl, InteractionControlRequest
        from perception.gates import gate

        route = gate("i want to kill myself")
        self.assertEqual(route.primary, "SAFETY")   # the net still trips
        notifications, logs = [], []
        dependencies = harness._dependencies(
            deterministic_route=lambda text: route,
            perception_route=lambda text, session: None,
            persona={"identity": "Wini", "style": "Warm", "intents": {
                "SAFETY": {"scripted": "Please find a trusted adult."}}},
            notify_safety=notifications.append,
            log_event=logs.append,
        )
        outcome = InteractionControl(dependencies).control(
            InteractionControlRequest(
                turn_input=harness._turn("i want to kill myself"),
                session={"context": []}, safety=model,
            )
        )
        return outcome, notifications, logs

    @staticmethod
    def _delivered_as_safety(outcome) -> bool:
        """Did the CHILD experience a safety turn? A released route continues to
        learning and carries no compatibility payload at all."""
        compatibility = outcome.value.compatibility
        return bool(compatibility) and compatibility.get("action") == "SAFETY"

    def test_a_healthy_model_finding_nothing_releases_the_gate_route(self) -> None:
        outcome, notifications, logs = self._run(_model([]))
        self.assertFalse(
            self._delivered_as_safety(outcome),
            "the net alone must not route a turn to SAFETY once the model is "
            "healthy — that is the arrangement the taxonomy inverted",
        )
        self.assertEqual(notifications, [])
        self.assertIs(
            outcome.value.disposition, InteractionDisposition.CONTINUE_LEARNING
        )

    def test_a_safety_turn_is_never_delivered_without_a_case_record(self) -> None:
        """The coherence property, stated directly: if the child is handled as a
        safety turn, a case record exists and someone was notified."""
        for model in (_model([]), _model(["SELF_HARM"]),
                      _model(status=SafetyModelStatus.TIMEOUT)):
            with self.subTest(status=model.status.value, tripped=model.tripped):
                outcome, notifications, _ = self._run(model)
                self.assertEqual(
                    self._delivered_as_safety(outcome), bool(notifications)
                )

    def test_an_unavailable_model_lets_the_outage_net_route_the_turn(self) -> None:
        """The other half: when the model did not answer, the net IS the verdict."""
        outcome, notifications, _ = self._run(_model(status=SafetyModelStatus.TIMEOUT))
        self.assertEqual(outcome.value.compatibility["action"], "SAFETY")
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["severity"], "ELEVATED")

    def test_no_detector_wired_keeps_the_legacy_behaviour(self) -> None:
        """A turn with no detector is degraded, so the net still routes it. This is
        what keeps the legacy path working while generation is still staged."""
        outcome, notifications, _ = self._run(None)
        self.assertEqual(outcome.value.compatibility["action"], "SAFETY")
        self.assertEqual(len(notifications), 1)


class LateVerdictTests(unittest.TestCase):
    def test_a_late_verdict_adds_classes_and_raises_severity(self) -> None:
        opened = compose_safety_verdict(
            lexicon=_lexicon_safety(normalize_text("i want to kill myself")),
            model=_model(status=SafetyModelStatus.TIMEOUT),
        )
        self.assertIs(opened.severity, SafetySeverity.ELEVATED)

        late = _model(["SELF_HARM"], status=SafetyModelStatus.LATE, named_means=True)
        updated = union_late(opened, late)

        self.assertIn(SafetyClass.SELF_HARM, updated.classes)
        self.assertIn(SafetyClass.UNSPECIFIED_CONCERN, updated.classes)
        self.assertIs(updated.severity, SafetySeverity.CRITICAL)

    def test_the_degraded_stamp_survives_a_late_verdict(self) -> None:
        """The turn *was* released degraded. Rewriting that would make the record
        claim something the child did not experience."""
        opened = compose_safety_verdict(
            lexicon=_lexicon_safety(normalize_text("i want to kill myself")),
            model=_model(status=SafetyModelStatus.TIMEOUT),
        )
        updated = union_late(opened, _model(["SELF_HARM"], status=SafetyModelStatus.LATE))
        self.assertTrue(updated.degraded)
        self.assertEqual(updated.model_status, "late")

    def test_a_late_non_answer_changes_nothing(self) -> None:
        opened = compose_safety_verdict(model=_model(["SELF_HARM"]))
        self.assertIs(union_late(opened, None), opened)
        self.assertIs(
            union_late(opened, _model(status=SafetyModelStatus.ERROR)), opened
        )

    def test_a_late_verdict_can_never_clear_an_open_finding(self) -> None:
        opened = compose_safety_verdict(
            lexicon=_lexicon_safety(normalize_text("i want to kill myself")),
            model=_model(status=SafetyModelStatus.TIMEOUT),
        )
        # The model eventually answers "nothing here". The record still stands.
        updated = union_late(opened, _model([], status=SafetyModelStatus.LATE))
        self.assertTrue(updated.tripped)
        self.assertIn(SafetyClass.UNSPECIFIED_CONCERN, updated.classes)


if __name__ == "__main__":
    unittest.main()
