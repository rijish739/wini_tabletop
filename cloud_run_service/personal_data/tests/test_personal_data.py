"""Unit tests for the personal-data detector, the redactor, and the sink types.

Every test here is **offline and free**: the detector is driven through its ``call_fn``
seam, so nothing in this file holds a credential or makes a call. The money is only
ever in ``eval/``.

What these tests are for, stated once. This package has two failure modes, and they
pull in opposite directions:

1. **A broken call reading as "no personal data."** An empty response, a malformed
   response, a timeout, a crash and a thinking-token overrun must each produce a
   non-answer that withholds the transcript — never an empty finding list. Several
   tests below look pedantic in isolation and are all this one test.

2. **Redacting the maths.** The contract has no threshold and no shape rule precisely
   so this cannot happen by accident, and the tests that assert an untouched
   arithmetic string are guarding an *absence* — the easiest kind of protection to
   delete during a refactor because nothing appears to depend on it.

The two structural assertions the ticket names are ``RedactedTextIsUnforgeableTests``
and ``NoIdentifierEverEscapesTests`` at the bottom.
"""

from __future__ import annotations

import ast
import json
import time
import unittest
from pathlib import Path

from personal_data import (
    GenerationText,
    IdentifierClass,
    IdentifierFinding,
    PersonalDataContext,
    PersonalDataDetector,
    PersonalDataGateway,
    PersonalDataVerdict,
    RedactedText,
    STAMP_INCOMPLETE,
    STAMP_UNAVAILABLE,
    VerdictStatus,
    for_generation,
    placeholder,
    prompt_hash,
    redact,
    turn_redaction,
)
from personal_data import config
from personal_data.prompt import (
    IDENTIFIER_CLASS_NAMES,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    STATIC_BLOCK,
    dynamic_prompt,
)
from personal_data.schema import FINDING_FIELDS, FORBIDDEN_FIELDS, REQUIRED_FIELDS

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

    return PersonalDataDetector(call_fn=call_fn)


def _payload(*pairs):
    return {"findings": [
        {"identifier_class": cls, "value": value} for cls, value in pairs
    ]}


def _landed(*pairs, utterance_id="u1"):
    return PersonalDataVerdict(
        utterance_id=utterance_id,
        status=VerdictStatus.LANDED,
        findings=frozenset(
            IdentifierFinding(identifier_class=cls, value=value)
            for cls, value in pairs
        ),
    )


# ---------------------------------------------------------------------------
class ContractTests(unittest.TestCase):
    """The types refuse to represent the states the contract forbids."""

    def test_an_unavailable_verdict_cannot_carry_findings(self) -> None:
        with self.assertRaises(ValueError):
            PersonalDataVerdict(
                utterance_id="u1",
                status=VerdictStatus.UNAVAILABLE,
                findings=frozenset({IdentifierFinding(
                    identifier_class=IdentifierClass.PHONE, value="98765")}),
            )

    def test_unavailable_is_the_only_way_to_build_a_non_answer(self) -> None:
        verdict = PersonalDataVerdict.unavailable(utterance_id="u1")
        self.assertIs(verdict.status, VerdictStatus.UNAVAILABLE)
        self.assertFalse(verdict.landed)
        self.assertEqual(verdict.findings, frozenset())

    def test_a_finding_names_a_non_empty_substring(self) -> None:
        with self.assertRaises(ValueError):
            IdentifierFinding(identifier_class=IdentifierClass.NAME, value="")

    def test_classes_are_sorted_and_deduplicated(self) -> None:
        verdict = _landed(
            (IdentifierClass.NAME, "Aarav"),
            (IdentifierClass.NAME, "Priya"),
            (IdentifierClass.ADDRESS, "14 MG Road"),
        )
        self.assertEqual(
            verdict.classes, (IdentifierClass.ADDRESS, IdentifierClass.NAME)
        )

    def test_the_context_window_is_one_preceding_exchange(self) -> None:
        PersonalDataContext(recent_context=({"role": "wini", "text": "hi"},))
        with self.assertRaises(ValueError):
            PersonalDataContext(recent_context=({}, {}, {}))

    def test_the_verdict_carries_no_severity_or_safety_type(self) -> None:
        # §1: personal data is off the safety axis entirely. The absence is the point.
        verdict = _landed((IdentifierClass.PHONE, "98765"))
        for forbidden in ("severity", "safety_class", "safety_alert", "tripped"):
            self.assertFalse(hasattr(verdict, forbidden), forbidden)


# ---------------------------------------------------------------------------
class RedactionTests(unittest.TestCase):
    def test_the_named_substring_is_replaced_by_a_typed_placeholder(self) -> None:
        out = redact("my number is 98765", _landed((IdentifierClass.PHONE, "98765")))
        self.assertEqual(out.text, "my number is <PHONE>")
        self.assertEqual(out.class_values, ["PHONE"])

    def test_placeholders_are_un_indexed(self) -> None:
        # §6.1: two names in one utterance both become <NAME>. An index is exactly the
        # field someone later makes stable across turns — a persistent pseudo-identifier.
        out = redact(
            "Aarav and Priya are here",
            _landed((IdentifierClass.NAME, "Aarav"), (IdentifierClass.NAME, "Priya")),
        )
        self.assertEqual(out.text, "<NAME> and <NAME> are here")

    def test_no_placeholder_contains_a_digit(self) -> None:
        # §6.1: math_grade.normalize must never be able to parse one as a number.
        # Asserted over the whole enum, not just today's classes.
        for identifier_class in IdentifierClass:
            token = placeholder(identifier_class)
            self.assertFalse(any(ch.isdigit() for ch in token), token)
            self.assertEqual(token, token.upper())

    def test_the_longest_finding_is_replaced_first(self) -> None:
        # A short finding nested inside a long one would otherwise corrupt it.
        out = redact(
            "call 9876543210 now",
            _landed(
                (IdentifierClass.PHONE, "9876543210"),
                (IdentifierClass.PHONE, "543210"),
            ),
        )
        self.assertEqual(out.text, "call <PHONE> now")

    def test_an_unavailable_verdict_yields_no_redacted_text(self) -> None:
        self.assertIsNone(
            redact("anything", PersonalDataVerdict.unavailable(utterance_id="u1"))
        )

    def test_a_substring_miss_fails_closed(self) -> None:
        # §4: redaction has failed and cannot be verified, so the sink gets nothing.
        # A partially-cleaned transcript is one we cannot claim to have cleaned.
        self.assertIsNone(
            redact("my number is 98765", _landed((IdentifierClass.PHONE, "12345")))
        )

    def test_a_substring_miss_still_records_the_class_and_stamps_the_turn(self) -> None:
        outcome = turn_redaction(
            "my number is 98765", _landed((IdentifierClass.PHONE, "12345"))
        )
        self.assertIsNone(outcome.redacted)
        self.assertEqual(outcome.class_values, ["PHONE"])
        self.assertEqual(outcome.stamp, STAMP_INCOMPLETE)
        self.assertEqual(outcome.missed, (IdentifierClass.PHONE,))

    def test_no_detector_is_stamped_unavailable(self) -> None:
        outcome = turn_redaction("what is 2+2", None)
        self.assertIsNone(outcome.redacted)
        self.assertEqual(outcome.stamp, STAMP_UNAVAILABLE)
        self.assertEqual(outcome.class_values, [])
        self.assertFalse(outcome.found)

    def test_a_clean_turn_produces_an_untouched_redacted_text(self) -> None:
        outcome = turn_redaction("9 x 25 x 17 = 3825", _landed())
        self.assertEqual(outcome.redacted.text, "9 x 25 x 17 = 3825")
        self.assertEqual(outcome.class_values, [])
        self.assertEqual(outcome.stamp, "")
        self.assertFalse(outcome.found)

    def test_the_analytics_row_carries_class_labels_and_nothing_else(self) -> None:
        # §9: `privacy_classes: [ADDRESS]` — labels only. No value, no count, no span.
        outcome = turn_redaction(
            "I live at 14 MG Road", _landed((IdentifierClass.ADDRESS, "14 MG Road"))
        )
        self.assertEqual(outcome.analytics(), {"privacy_classes": ["ADDRESS"]})
        self.assertNotIn("14 MG Road", json.dumps(outcome.analytics()))


class MathsIsProtectedByConstructionTests(unittest.TestCase):
    """§5: the collision has no tie-break because the system has no threshold.

    These tests assert an ABSENCE — that nothing in the redactor reacts to the shape of
    a string. An absence is the easiest protection to delete by accident, which is why
    it is asserted rather than trusted.
    """

    MATHS = (
        "9 x 25 x 17 = 3825",
        "the roots are 2 and -5",
        "x = 42",
        "chapter 4 exercise 3 question 7",
        "the answer is 98765",
        "2345 6789 0123",          # Aadhaar-shaped, and still just maths here
        "+91 9845012345",          # phone-shaped, and still just maths here
    )

    def test_a_landed_verdict_with_no_findings_touches_nothing(self) -> None:
        for text in self.MATHS:
            with self.subTest(text=text):
                self.assertEqual(redact(text, _landed()).text, text)

    def test_only_what_the_model_named_is_removed(self) -> None:
        text = "my number is 9876543210 and 9 x 25 x 17 = 3825"
        out = redact(text, _landed((IdentifierClass.PHONE, "9876543210")))
        self.assertEqual(out.text, "my number is <PHONE> and 9 x 25 x 17 = 3825")
        self.assertIn("3825", out.text)


# ---------------------------------------------------------------------------
class DetectorReliabilityTests(unittest.TestCase):
    """One test, said five ways: a broken call is never an empty finding list."""

    def _assert_unavailable(self, verdict) -> None:
        self.assertIs(verdict.status, VerdictStatus.UNAVAILABLE)
        self.assertEqual(verdict.findings, frozenset())
        self.assertIsNone(redact("anything", verdict))

    def test_an_empty_response_is_a_failure(self) -> None:
        # The thinking-token overrun: empty text with finish_reason=MAX_TOKENS.
        self._assert_unavailable(
            _detector(None).detect(utterance_id="u1", text="hi")
        )

    def test_a_malformed_response_is_a_failure(self) -> None:
        self._assert_unavailable(
            _detector("not a dict").detect(utterance_id="u1", text="hi")
        )

    def test_a_crash_is_a_failure(self) -> None:
        self._assert_unavailable(
            _detector(boom=RuntimeError("transport")).detect(
                utterance_id="u1", text="hi")
        )

    def test_an_expired_envelope_is_a_failure(self) -> None:
        detector = _detector(_payload())
        verdict = detector.detect(
            utterance_id="u1", text="hi", deadline=time.monotonic() - 1
        )
        self._assert_unavailable(verdict)

    def test_a_dispatch_timeout_is_a_failure_not_a_clean_turn(self) -> None:
        gateway = PersonalDataGateway(_detector(_payload(), delay=0.4))
        original = config.PERSONAL_DATA_TIMEOUT_S
        config.PERSONAL_DATA_TIMEOUT_S = 0.05
        try:
            dispatch = gateway.dispatch(utterance_id="u1", text="hi")
            self._assert_unavailable(dispatch.await_verdict())
        finally:
            config.PERSONAL_DATA_TIMEOUT_S = original

    def test_the_retry_shares_the_envelope_and_does_not_extend_it(self) -> None:
        calls: list[str] = []
        detector = _detector(None, calls=calls)
        detector.detect(utterance_id="u1", text="hi")
        self.assertEqual(len(calls), 2, "one immediate retry, and only one")

    def test_no_retry_is_started_that_cannot_finish(self) -> None:
        calls: list[str] = []
        detector = _detector(None, calls=calls)
        detector.detect(
            utterance_id="u1", text="hi",
            deadline=time.monotonic() + config.PERSONAL_DATA_RETRY_MIN_S / 2,
        )
        self.assertEqual(len(calls), 1, "a retry with no envelope left is not started")

    def test_the_call_is_memoized_on_utterance_id_never_on_text(self) -> None:
        calls: list[str] = []
        detector = _detector(_payload(), calls=calls)
        detector.detect(utterance_id="u1", text="same words")
        detector.detect(utterance_id="u1", text="same words")
        self.assertEqual(len(calls), 1, "a replayed turn must not re-bill")
        detector.detect(utterance_id="u2", text="same words")
        self.assertEqual(
            len(calls), 2,
            "two children saying the same words must not share a verdict",
        )

    def test_an_utterance_id_is_required(self) -> None:
        with self.assertRaises(ValueError):
            _detector(_payload()).detect(utterance_id="", text="hi")


class ValidationBeltTests(unittest.TestCase):
    def test_an_out_of_catalog_class_is_dropped(self) -> None:
        verdict = _detector(_payload(("BLOOD_TYPE", "O+"))).detect(
            utterance_id="u1", text="my blood type is O+")
        self.assertEqual(verdict.findings, frozenset())
        self.assertIs(verdict.status, VerdictStatus.LANDED)

    def test_an_empty_value_is_dropped(self) -> None:
        verdict = _detector(_payload(("NAME", ""))).detect(
            utterance_id="u1", text="hello")
        self.assertEqual(verdict.findings, frozenset())

    def test_duplicate_findings_collapse(self) -> None:
        verdict = _detector(
            _payload(("NAME", "Aarav"), ("NAME", "Aarav"))
        ).detect(utterance_id="u1", text="Aarav")
        self.assertEqual(len(verdict.findings), 1)

    def test_an_unmatchable_value_survives_validation_and_fails_the_redaction(self) -> None:
        # §4: dropping it here would convert an unverifiable redaction into an
        # apparently clean one, which is the one thing that section exists to prevent.
        verdict = _detector(_payload(("PHONE", "12345"))).detect(
            utterance_id="u1", text="my number is 98765")
        self.assertEqual(len(verdict.findings), 1)
        self.assertIsNone(redact("my number is 98765", verdict))


# ---------------------------------------------------------------------------
class TwoDeadlinesTests(unittest.TestCase):
    """§7: generation is opportunistic, persisting sinks get the full envelope."""

    def test_the_opportunistic_read_does_not_block(self) -> None:
        gateway = PersonalDataGateway(_detector(_payload(), delay=0.3))
        dispatch = gateway.dispatch(utterance_id="u1", text="hi")
        started = time.monotonic()
        landed = dispatch.landed_verdict()
        self.assertLess(time.monotonic() - started, 0.1, "landed_verdict blocked")
        self.assertIsNone(landed, "a call still in flight has landed nothing")

    def test_the_persisting_read_waits_for_the_verdict(self) -> None:
        gateway = PersonalDataGateway(_detector(_payload(("PHONE", "98765")),
                                                delay=0.2))
        dispatch = gateway.dispatch(utterance_id="u1", text="my number is 98765")
        verdict = dispatch.await_verdict()
        self.assertIs(verdict.status, VerdictStatus.LANDED)
        self.assertEqual(verdict.classes, (IdentifierClass.PHONE,))

    def test_generation_fails_open_when_nothing_landed(self) -> None:
        # §8: generation cannot fail closed — it cannot run without the text.
        gen = for_generation("my number is 98765", None)
        self.assertEqual(gen.text, "my number is 98765")
        self.assertFalse(gen.redaction_confirmed)
        self.assertTrue(gen.anti_echo_required)

    def test_generation_uses_the_redacted_form_when_one_landed(self) -> None:
        outcome = turn_redaction(
            "my number is 98765", _landed((IdentifierClass.PHONE, "98765"))
        )
        gen = for_generation("my number is 98765", outcome)
        self.assertEqual(gen.text, "my number is <PHONE>")
        self.assertTrue(gen.redaction_confirmed)
        self.assertFalse(gen.anti_echo_required)

    def test_a_failed_redaction_makes_generation_fall_open(self) -> None:
        outcome = turn_redaction(
            "my number is 98765", _landed((IdentifierClass.PHONE, "12345"))
        )
        gen = for_generation("my number is 98765", outcome)
        self.assertTrue(gen.anti_echo_required)


# ---------------------------------------------------------------------------
class PromptAndSchemaTests(unittest.TestCase):
    def test_the_prompt_hash_moves_with_the_versions(self) -> None:
        import personal_data.prompt as prompt_module

        before = prompt_hash()
        original = prompt_module.SCHEMA_VERSION
        prompt_module.SCHEMA_VERSION = "changed"
        try:
            self.assertNotEqual(prompt_hash(), before)
        finally:
            prompt_module.SCHEMA_VERSION = original
        self.assertEqual(prompt_hash(), before)

    def test_every_enum_member_is_defined_in_the_static_block(self) -> None:
        for name in IDENTIFIER_CLASS_NAMES:
            self.assertIn(f"### {name}", STATIC_BLOCK, name)

    def test_the_enum_and_the_contract_type_agree(self) -> None:
        self.assertEqual(
            tuple(c.value for c in IdentifierClass), IDENTIFIER_CLASS_NAMES
        )

    def test_the_schema_field_names_match_what_the_belt_reads(self) -> None:
        self.assertEqual(REQUIRED_FIELDS, ("findings",))
        self.assertEqual(FINDING_FIELDS, ("identifier_class", "value"))

    def test_the_forbidden_fields_appear_in_neither_schema_nor_verdict(self) -> None:
        source = (_PACKAGE / "schema.py").read_text(encoding="utf-8")
        properties = source.split("properties=")[1]
        for field in FORBIDDEN_FIELDS:
            self.assertNotIn(f'"{field}"', properties, field)
        verdict = _landed((IdentifierClass.PHONE, "98765"))
        for field in FORBIDDEN_FIELDS:
            self.assertFalse(hasattr(verdict, field), field)

    def test_the_prompt_sees_one_preceding_exchange_and_no_session_summary(self) -> None:
        rendered = dynamic_prompt(
            text="it's 98765",
            recent_context=(
                {"role": "wini", "text": "what is your number?"},
                {"role": "student", "text": "wait"},
            ),
        )
        self.assertIn("what is your number?", rendered)
        self.assertIn("it's 98765", rendered)
        # §9 forbids the standing behavioural record a prior-disclosure count needs.
        self.assertNotIn("prior", rendered.lower())

    def test_the_maths_rule_precedes_the_class_definitions(self) -> None:
        # Ordering is load-bearing: the collision class (§5) is read against it.
        self.assertLess(
            STATIC_BLOCK.index("this is a MATHS tutor"),
            STATIC_BLOCK.index("### NAME"),
        )

    def test_the_prompt_was_not_written_from_the_corpora(self) -> None:
        # The blindness rule runs in both directions (§12). A prompt that quotes corpus
        # rows measures the corpus. Spot-check: no corpus row text appears verbatim.
        corpus = _PACKAGE.parent / "eval" / "corpora" / "pii"
        if not corpus.exists():          # corpora are a separate ticket's artifact
            self.skipTest("pii corpora not present")
        leaked = []
        for path in sorted(corpus.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                text = json.loads(line).get("text") or ""
                if len(text) > 20 and text in STATIC_BLOCK:
                    leaked.append(text)
        self.assertEqual(leaked, [], f"prompt quotes corpus rows: {leaked[:3]}")


# ---------------------------------------------------------------------------
class RedactedTextIsUnforgeableTests(unittest.TestCase):
    """Structural assertion 1: ``RedactedText`` is unconstructable without a landed
    verdict (§6.2, §13). This is the whole of the sink conversion — if it can be
    forged, the type is back to being discipline."""

    def test_a_bare_string_cannot_become_a_redacted_text(self) -> None:
        with self.assertRaises(TypeError):
            RedactedText(text="my number is 9876543210")

    def test_a_generation_text_cannot_be_forged_either(self) -> None:
        with self.assertRaises(TypeError):
            GenerationText(text="my number is 9876543210")

    def test_an_unavailable_verdict_cannot_produce_one(self) -> None:
        self.assertIsNone(
            redact("hi", PersonalDataVerdict.unavailable(utterance_id="u1"))
        )

    def test_a_turn_redaction_cannot_hold_one_without_a_landed_verdict(self) -> None:
        from personal_data.redaction import TurnRedaction

        landed = redact("hi", _landed())
        with self.assertRaises(ValueError):
            TurnRedaction(status=VerdictStatus.UNAVAILABLE, redacted=landed)

    def test_redact_is_the_only_construction_site_in_the_package(self) -> None:
        # An AST guard rather than a naming convention: the token is module-private, so
        # a second constructor would have to live in redaction.py to reach it. Anything
        # new in this file that passes `_token` is a second way to make one.
        source = (_PACKAGE / "redaction.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        builders = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", "")
            if name not in ("RedactedText", "GenerationText"):
                continue
            enclosing = [
                fn.name for fn in ast.walk(tree)
                if isinstance(fn, ast.FunctionDef)
                and fn.lineno <= node.lineno <= (fn.end_lineno or fn.lineno)
            ]
            builders.update(enclosing)
        self.assertEqual(
            builders, {"redact", "for_generation"},
            "a new constructor of the sink types appeared; §6.2 allows exactly two",
        )


class NoIdentifierEverEscapesTests(unittest.TestCase):
    """Structural assertion 2: no raw identifier value appears in any ``__str__`` /
    ``__repr__`` (§4, invariant 5).

    A traceback, a ``print``, a debugger frame dump and an f-string are all sinks, and
    none of them consulted the contract first. The default dataclass ``__repr__`` would
    print every value verbatim, so this is a real hazard rather than a theoretical one.
    """

    SECRET = "9876543210"

    def _assert_absent(self, rendered: str) -> None:
        self.assertNotIn(self.SECRET, rendered, rendered)

    def test_the_finding_masks_its_value(self) -> None:
        finding = IdentifierFinding(
            identifier_class=IdentifierClass.PHONE, value=self.SECRET)
        self._assert_absent(repr(finding))
        self._assert_absent(str(finding))
        self._assert_absent(f"{finding}")
        self._assert_absent(f"{finding!r}")

    def test_the_verdict_masks_its_findings(self) -> None:
        verdict = _landed((IdentifierClass.PHONE, self.SECRET))
        self._assert_absent(repr(verdict))
        self._assert_absent(str(verdict))
        self._assert_absent(f"{verdict}")

    def test_the_verdict_has_no_serialization_path(self) -> None:
        # §4: there is no `asdict` path and no `json.dumps` path. `child_safety` has
        # `as_record()` and is safe because a safety verdict carries only labels;
        # copying that method here is the most likely way this contract gets broken.
        verdict = _landed((IdentifierClass.PHONE, self.SECRET))
        self.assertFalse(hasattr(verdict, "as_record"))
        self.assertFalse(hasattr(verdict, "as_dict"))
        with self.assertRaises(TypeError):
            json.dumps(verdict)

    def test_a_traceback_carrying_a_finding_does_not_leak_it(self) -> None:
        import traceback

        finding = IdentifierFinding(
            identifier_class=IdentifierClass.PHONE, value=self.SECRET)
        try:
            raise ValueError(f"bad finding: {finding}")
        except ValueError:
            self._assert_absent("".join(traceback.format_exc()))

    def test_the_turn_redaction_that_crosses_seams_is_identifier_free(self) -> None:
        outcome = turn_redaction(
            f"my number is {self.SECRET}",
            _landed((IdentifierClass.PHONE, self.SECRET)),
        )
        self._assert_absent(repr(outcome))
        self._assert_absent(json.dumps(outcome.analytics()))
        self._assert_absent(outcome.redacted.text)
        self._assert_absent(repr(outcome.redacted))

    def test_the_debug_line_carries_a_count_and_never_a_class_or_value(self) -> None:
        import debug_logger

        before = len(debug_logger.tail(10_000))
        _detector(_payload(("PHONE", self.SECRET))).detect(
            utterance_id="u1", text=f"my number is {self.SECRET}")
        emitted = debug_logger.tail(10_000)[before:]
        self.assertTrue(emitted, "the detector emits a debug line")
        rendered = json.dumps(emitted, default=str)
        self._assert_absent(rendered)
        self.assertNotIn("PHONE", rendered)
        self.assertIn("n_findings", rendered)


class DebugSinkTests(unittest.TestCase):
    """``debug_logger`` is a converted sink: SSE **and** disk (§6.3)."""

    def test_a_bare_transcript_string_is_withheld(self) -> None:
        import debug_logger

        before = len(debug_logger.tail(10_000))
        debug_logger.emit(debug_logger.L1, "stt_done", transcript="my number is 98765")
        entry = debug_logger.tail(10_000)[before:][0]
        self.assertEqual(entry["transcript"], debug_logger.WITHHELD)

    def test_a_redacted_text_is_emitted_with_its_class_labels(self) -> None:
        import debug_logger

        redacted = redact(
            "my number is 98765", _landed((IdentifierClass.PHONE, "98765"))
        )
        before = len(debug_logger.tail(10_000))
        debug_logger.emit(debug_logger.L2, "turn_text", text=redacted)
        entry = debug_logger.tail(10_000)[before:][0]
        self.assertEqual(entry["text"], "my number is <PHONE>")
        self.assertEqual(entry["text_privacy_classes"], ["PHONE"])

    def test_non_transcript_fields_pass_through_untouched(self) -> None:
        import debug_logger

        before = len(debug_logger.tail(10_000))
        debug_logger.emit(debug_logger.L6, "gen_start", backend="gemini", ms=1240)
        entry = debug_logger.tail(10_000)[before:][0]
        self.assertEqual(entry["backend"], "gemini")
        self.assertEqual(entry["ms"], 1240)

    def test_a_generation_text_is_not_accepted_as_redacted(self) -> None:
        # GenerationText may hold unredacted text; debug is a persisting sink.
        import debug_logger

        gen = for_generation("my number is 98765", None)
        before = len(debug_logger.tail(10_000))
        debug_logger.emit(debug_logger.L6, "gen_start", text=gen)
        entry = debug_logger.tail(10_000)[before:][0]
        self.assertNotIn("98765", json.dumps(entry, default=str))


class DetectorSourceGuardTests(unittest.TestCase):
    """§2: model-only. No regex, no lexicon, no shape rule, no threshold — asserted
    against the source, because every one of them is a thing a well-meaning fix would
    add, and every one of them re-opens the F1 = 0.379 failure that eats the maths."""

    FILES = ("detector.py", "redaction.py", "contracts.py", "dispatch.py")

    def test_no_module_imports_re(self) -> None:
        for name in self.FILES:
            tree = ast.parse((_PACKAGE / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotEqual(alias.name, "re", name)
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(node.module, "re", name)

    def test_no_threshold_constant_exists(self) -> None:
        # Names, not prose: the docstrings say "no threshold" repeatedly and must be
        # allowed to. What is banned is a *binding* — an assignment target or an
        # attribute — because that is what a future tie-break would actually need.
        banned = ("threshold", "min_confidence", "cutoff", "score", "floor")
        for name in self.FILES + ("config.py",):
            tree = ast.parse((_PACKAGE / name).read_text(encoding="utf-8"))
            bound: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    bound.add(node.id.lower())
                elif isinstance(node, ast.Attribute):
                    bound.add(node.attr.lower())
                elif isinstance(node, ast.arg):
                    bound.add(node.arg.lower())
            for word in banned:
                offenders = [n for n in bound if word in n]
                self.assertEqual(offenders, [], f"{name}: {offenders}")

    def test_the_package_cannot_reach_the_safety_axis(self) -> None:
        # §1: off the safety axis entirely. A module that cannot name the types cannot
        # drift onto them.
        for name in self.FILES:
            source = (_PACKAGE / name).read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                module = getattr(node, "module", None)
                if isinstance(node, (ast.Import, ast.ImportFrom)) and module:
                    self.assertNotIn("child_safety", module, name)
                    self.assertNotIn("safety_composition", module, name)


if __name__ == "__main__":
    unittest.main()
