"""Unit tests for the primary safety detector.

Every test here is **offline and free**: the detector is driven through its
``call_fn`` seam, so nothing in this file holds a credential or makes a call. The
money is only ever in ``eval/``.

What these tests are for, stated once: the single failure mode this whole package
exists to prevent is **a broken safety call reading as "no concern."** Several
tests below look pedantic in isolation and are all the same test — an empty
response, a malformed response, a timeout, a crash and a thinking-token overrun
must each produce a non-answer that puts the turn in degraded mode, never a
negative verdict.
"""

from __future__ import annotations

import ast
import time
import unittest
from pathlib import Path

from child_safety import (
    ChildSafetyDetector,
    ChildSafetyGateway,
    ModelSafetyVerdict,
    SafetyModelStatus,
    SafetySessionSummary,
    divergence,
    prompt_hash,
)
from child_safety import config
from child_safety.prompt import PROMPT_VERSION, SCHEMA_VERSION, dynamic_prompt
from child_safety.schema import FORBIDDEN_FIELDS, REQUIRED_FIELDS
from utterance_intake.observation import SafetyClass, SafetySource

_PACKAGE = Path(__file__).resolve().parent.parent


def _detector(payload=None, *, delay=0.0, boom=None, calls=None):
    def call_fn(prompt, static_block):
        if calls is not None:
            calls.append(prompt)
        if delay:
            time.sleep(delay)
        if boom is not None:
            raise boom
        return payload

    return ChildSafetyDetector(call_fn=call_fn)


def _verdict(**overrides):
    base = dict(
        tripped=True, classes=frozenset({SafetyClass.SELF_HARM}),
        imminence_cue=False, status=SafetyModelStatus.OK,
        model_id="gemini-2.5-flash", model_pinned=False,
        prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION,
    )
    base.update(overrides)
    return ModelSafetyVerdict(**base)


# --------------------------------------------------------------------------
class ContractTests(unittest.TestCase):
    def test_a_failed_call_cannot_carry_a_positive_verdict(self) -> None:
        with self.assertRaises(ValueError):
            ModelSafetyVerdict(
                tripped=True, classes=frozenset({SafetyClass.SELF_HARM}),
                imminence_cue=False, status=SafetyModelStatus.TIMEOUT,
                model_id="m", model_pinned=False,
                prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION,
            )

    def test_unavailable_is_the_only_way_to_build_a_non_answer(self) -> None:
        with self.assertRaises(ValueError):
            ModelSafetyVerdict.unavailable(
                status=SafetyModelStatus.OK, model_id="m", model_pinned=False,
                prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION,
            )

    def test_a_non_answer_is_not_a_negative_verdict(self) -> None:
        """No classes and `available is False` — the composition step reads the
        second, which is what stops "the call failed" becoming "the child is fine"."""
        verdict = ModelSafetyVerdict.unavailable(
            status=SafetyModelStatus.ERROR, model_id="m", model_pinned=False,
            prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION,
        )
        self.assertFalse(verdict.tripped)
        self.assertFalse(verdict.available)

    def test_tripped_must_equal_bool_classes(self) -> None:
        with self.assertRaises(ValueError):
            _verdict(tripped=True, classes=frozenset())

    def test_evidence_flags_require_a_tripped_axis(self) -> None:
        with self.assertRaises(ValueError):
            _verdict(tripped=False, classes=frozenset(), imminence_cue=True)

    def test_the_verdict_cannot_name_a_severity(self) -> None:
        """Structural, not conventional: `SafetySeverity` lives in the consumer and
        a detector that cannot name the type cannot write it (§5)."""
        with self.assertRaises(TypeError):
            _verdict(severity="CRITICAL")
        with self.assertRaises(TypeError):
            _verdict(caregiver_implicated=True)

    def test_findings_carry_the_version_as_evidence_never_the_text(self) -> None:
        findings = _verdict().findings()
        self.assertEqual(len(findings), 1)
        finding = next(iter(findings))
        self.assertIs(finding.source, SafetySource.MODEL)
        self.assertEqual(finding.evidence_id, f"{PROMPT_VERSION}/{SCHEMA_VERSION}")

    def test_the_case_record_payload_is_structured_and_carries_no_text(self) -> None:
        record = _verdict().as_record()
        self.assertEqual(record["classes"], ["SELF_HARM"])
        for forbidden in FORBIDDEN_FIELDS:
            self.assertNotIn(forbidden, record)

    def test_session_summary_admits_a_count_and_a_max_severity_only(self) -> None:
        summary = SafetySessionSummary(
            prior_safety_findings=2, prior_max_severity="ELEVATED"
        )
        self.assertEqual(summary.prior_safety_findings, 2)
        with self.assertRaises(ValueError):
            SafetySessionSummary(prior_max_severity="TIER_3")
        with self.assertRaises(ValueError):
            SafetySessionSummary(recent_context=({}, {}, {}))


# --------------------------------------------------------------------------
class DetectorTests(unittest.TestCase):
    def test_a_clear_utterance_produces_an_answered_negative(self) -> None:
        verdict = _detector({"axis_tripped": False, "classes": []}).detect(
            utterance_id="u1", text="what is 2+2"
        )
        self.assertTrue(verdict.available)
        self.assertFalse(verdict.tripped)
        self.assertIs(verdict.status, SafetyModelStatus.OK)

    def test_the_call_is_memoized_on_utterance_id_never_on_text(self) -> None:
        calls: list[str] = []
        detector = _detector({"axis_tripped": False, "classes": []}, calls=calls)
        detector.detect(utterance_id="u1", text="hello")
        detector.detect(utterance_id="u1", text="hello")
        self.assertEqual(len(calls), 1, "a replayed turn must not re-bill")
        # The same words from a different utterance are a different call.
        detector.detect(utterance_id="u2", text="hello")
        self.assertEqual(len(calls), 2)

    def test_an_utterance_id_is_required(self) -> None:
        with self.assertRaises(ValueError):
            _detector({}).detect(utterance_id="", text="hello")

    def test_an_empty_response_is_a_failure_never_a_negative_verdict(self) -> None:
        """The thinking-token overrun (CLAUDE.md gotcha): Gemini 2.5 Flash can burn
        the whole output budget on hidden thinking and return empty text with
        finish_reason=MAX_TOKENS. On this path that would look exactly like "no
        safety concern," so it must be unrepresentable as one."""
        verdict = _detector(None).detect(utterance_id="u1", text="i want to die")
        self.assertFalse(verdict.available)
        self.assertIs(verdict.status, SafetyModelStatus.ERROR)

    def test_a_malformed_response_is_a_failure(self) -> None:
        verdict = _detector("not a dict").detect(utterance_id="u1", text="x")
        self.assertFalse(verdict.available)

    def test_a_transport_crash_is_a_failure_not_a_clear_turn(self) -> None:
        verdict = _detector(boom=RuntimeError("boom")).detect(
            utterance_id="u1", text="x"
        )
        self.assertFalse(verdict.available)
        self.assertIn("RuntimeError", verdict.failure_reason)

    def test_the_retry_shares_the_envelope_and_never_extends_it(self) -> None:
        calls: list[str] = []
        detector = _detector(None, calls=calls)
        detector.detect(utterance_id="u1", text="x")
        self.assertEqual(len(calls), 2, "exactly one retry, in the same envelope")

    def test_an_exhausted_envelope_skips_the_retry_rather_than_paying_for_it(self) -> None:
        calls: list[str] = []
        detector = _detector(None, calls=calls)
        detector.detect(
            utterance_id="u1", text="x", deadline=time.monotonic() + 0.01
        )
        self.assertEqual(len(calls), 1)

    def test_a_deadline_already_past_makes_no_call_at_all(self) -> None:
        calls: list[str] = []
        detector = _detector(None, calls=calls)
        verdict = detector.detect(
            utterance_id="u1", text="x", deadline=time.monotonic() - 1
        )
        self.assertEqual(calls, [])
        self.assertFalse(verdict.available)


class WarmingTests(unittest.TestCase):
    def test_warming_never_raises_when_vertex_is_unreachable(self) -> None:
        """A cold start is a latency problem, never a correctness one — so a failed
        warm reports False and the next real call retries. Offline, this is exactly
        the unreachable case."""
        self.assertIn(ChildSafetyDetector().warm(), (True, False))

    def test_a_warmed_detector_does_not_rebuild_inside_the_envelope(self) -> None:
        """CLAUDE.md (measured 2026-07-01): client construction is 4-9s, which is
        larger than the whole 5s envelope. Whatever `warm()` built must be reused,
        not rebuilt on the first call."""
        detector = ChildSafetyDetector()
        detector._gateway = object()
        detector._schema = object()
        gateway, schema = detector._gateway, detector._schema
        detector.warm()
        self.assertIs(detector._gateway, gateway)
        self.assertIs(detector._schema, schema)


class ValidationBeltTests(unittest.TestCase):
    """The belt behind the schema. Controlled generation stops *invented* class
    names, not *wrong* ones, and cannot stop an internally inconsistent answer.
    Every coercion here is add-only."""

    def _detect(self, payload):
        return _detector(payload).detect(utterance_id="u1", text="x")

    def test_an_out_of_catalog_class_is_dropped(self) -> None:
        verdict = self._detect(
            {"axis_tripped": True, "classes": ["SELF_HARM", "NOT_A_CLASS"]}
        )
        self.assertEqual(verdict.classes, frozenset({SafetyClass.SELF_HARM}))

    def test_naming_a_class_trips_the_axis_even_if_the_model_said_otherwise(self) -> None:
        """A model may not clear the axis (§7.4)."""
        verdict = self._detect({"axis_tripped": False, "classes": ["SELF_HARM"]})
        self.assertTrue(verdict.tripped)

    def test_a_tripped_axis_with_no_surviving_class_becomes_unspecified(self) -> None:
        verdict = self._detect({"axis_tripped": True, "classes": ["NOT_A_CLASS"]})
        self.assertEqual(
            verdict.classes, frozenset({SafetyClass.UNSPECIFIED_CONCERN})
        )

    def test_a_severity_in_the_payload_is_ignored_not_honoured(self) -> None:
        """If the model somehow emits one, it must go nowhere. Severity is derived
        at exactly one site and written by no detector."""
        verdict = self._detect(
            {"axis_tripped": True, "classes": ["SELF_HARM"],
             "severity": "CRITICAL", "caregiver_implicated": True, "tier": 3}
        )
        self.assertNotIn("severity", verdict.as_record())
        self.assertNotIn("caregiver_implicated", verdict.as_record())

    def test_evidence_flags_are_carried_through(self) -> None:
        verdict = self._detect({
            "axis_tripped": True, "classes": ["UNSAFE_CONTACT"],
            "imminence_cue": True, "arranged_meeting": True,
        })
        self.assertTrue(verdict.imminence_cue)
        self.assertTrue(verdict.arranged_meeting)


class DispatchTests(unittest.TestCase):
    def test_the_hold_expires_into_a_timeout_verdict(self) -> None:
        original = config.SAFETY_TIMEOUT_S
        config.SAFETY_TIMEOUT_S = 0.15
        try:
            gateway = ChildSafetyGateway(
                _detector({"axis_tripped": False, "classes": []}, delay=2.0)
            )
            dispatch = gateway.dispatch(utterance_id="u1", text="x")
            verdict = dispatch.await_verdict()
        finally:
            config.SAFETY_TIMEOUT_S = original
        self.assertIs(verdict.status, SafetyModelStatus.TIMEOUT)
        self.assertFalse(verdict.available)

    def test_a_late_verdict_still_counts_and_is_stamped_late(self) -> None:
        """§6.4: the call is deliberately not cancelled at the deadline. A verdict
        that lands afterwards unions into the record the net opened."""
        original = config.SAFETY_TIMEOUT_S
        config.SAFETY_TIMEOUT_S = 0.05
        try:
            gateway = ChildSafetyGateway(_detector(
                {"axis_tripped": True, "classes": ["SELF_HARM"]}, delay=0.3
            ))
            dispatch = gateway.dispatch(utterance_id="u1", text="x")
            self.assertFalse(dispatch.await_verdict().available)
            self.assertIsNone(dispatch.late_verdict())   # still outstanding
            time.sleep(0.5)
            late = dispatch.late_verdict()
        finally:
            config.SAFETY_TIMEOUT_S = original
        self.assertIsNotNone(late)
        self.assertIs(late.status, SafetyModelStatus.LATE)
        self.assertEqual(late.classes, frozenset({SafetyClass.SELF_HARM}))

    def test_a_verdict_counted_at_await_time_is_not_counted_twice(self) -> None:
        gateway = ChildSafetyGateway(
            _detector({"axis_tripped": True, "classes": ["SELF_HARM"]})
        )
        dispatch = gateway.dispatch(utterance_id="u1", text="x")
        self.assertTrue(dispatch.await_verdict().available)
        self.assertIsNone(dispatch.late_verdict())


class PromptAndSchemaTests(unittest.TestCase):
    def test_the_schema_cannot_represent_a_severity_or_a_caregiver_flag(self) -> None:
        from child_safety import prompt as prompt_module

        for forbidden in FORBIDDEN_FIELDS:
            self.assertNotIn(forbidden, REQUIRED_FIELDS)
            self.assertNotIn(
                f'"{forbidden}"', prompt_module.STATIC_BLOCK,
                f"the prompt must not teach the model to emit {forbidden}",
            )

    def test_the_prompt_hash_covers_the_version_stamps(self) -> None:
        from child_safety import prompt as prompt_module

        before = prompt_hash()
        original = prompt_module.SCHEMA_VERSION
        prompt_module.SCHEMA_VERSION = "child-safety-schema-v2"
        try:
            self.assertNotEqual(prompt_hash(), before)
        finally:
            prompt_module.SCHEMA_VERSION = original
        self.assertEqual(prompt_hash(), before)

    def test_the_dynamic_prompt_carries_a_count_and_a_severity_never_classes(self) -> None:
        rendered = dynamic_prompt(
            text="hello", prior_safety_findings=3, prior_max_severity="ELEVATED",
            recent_context=({"role": "student", "text": "prior"},),
        )
        self.assertIn("prior_safety_findings: 3", rendered)
        self.assertIn("prior_max_severity: ELEVATED", rendered)
        self.assertNotIn("SELF_HARM", rendered)

    def test_the_prompt_teaches_the_seven_classes(self) -> None:
        from child_safety.prompt import SAFETY_CLASS_NAMES, STATIC_BLOCK

        self.assertEqual(len(SAFETY_CLASS_NAMES), 7)
        for name in SAFETY_CLASS_NAMES:
            self.assertIn(name, STATIC_BLOCK)
        # The enum and the intake catalog are the same seven.
        self.assertEqual(
            set(SAFETY_CLASS_NAMES), {cls.value for cls in SafetyClass}
        )


class MonitoringTests(unittest.TestCase):
    def test_a_non_answer_is_not_a_disagreement(self) -> None:
        from types import SimpleNamespace

        model = ModelSafetyVerdict.unavailable(
            status=SafetyModelStatus.TIMEOUT, model_id="m", model_pinned=False,
            prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION,
        )
        result = divergence(SimpleNamespace(tripped=True), model)
        self.assertFalse(result.comparable)
        self.assertIsNone(result.agrees)
        self.assertEqual(result.label, "model_unavailable")

    def test_the_metric_carries_no_classes_and_no_text(self) -> None:
        from types import SimpleNamespace

        metric = divergence(SimpleNamespace(tripped=True), _verdict()).as_metric()
        self.assertEqual(metric["divergence"], "both")
        self.assertEqual(
            set(metric), {"net_tripped", "model_tripped", "model_available",
                          "divergence"}
        )


class SourceGuardTests(unittest.TestCase):
    """Invariant 1, as a statement about the codebase rather than about one turn."""

    def _imports(self) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        for path in _PACKAGE.rglob("*.py"):
            if "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for alias in node.names:
                        found.append((node.module, alias.name))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        found.append((alias.name, ""))
        return found

    def test_the_safety_path_reads_neither_authorization_nor_the_transcript(self) -> None:
        """A safety trip at any confidence always produces the safety response
        path, so there is nothing here for those readings to gate. Reading them
        would create the option of withholding a disclosure because the microphone
        was poor — the exact failure this axis exists to prevent."""
        for module, name in self._imports():
            self.assertNotIn(
                name, {"Authorization", "TranscriptReading"},
                f"{module}.{name} must not be reachable from child_safety/",
            )

    def test_severity_is_unreachable_from_the_detector_package(self) -> None:
        for module, name in self._imports():
            self.assertNotEqual(name, "SafetySeverity")
            self.assertFalse(
                module.startswith("interaction_control"),
                f"child_safety/ must not import its own consumer ({module})",
            )


if __name__ == "__main__":
    unittest.main()
