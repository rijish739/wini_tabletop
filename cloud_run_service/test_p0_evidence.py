"""P0 evidence/correctness invariant tests (stdlib runner; no pytest required)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace


def _stub_tutor_imports() -> None:
    numpy = types.ModuleType("numpy")
    numpy.ndarray = object
    sys.modules.setdefault("numpy", numpy)
    sys.modules.setdefault("requests", types.ModuleType("requests"))

    cognitive = types.ModuleType("cognitive_analyzer")
    cognitive.CognitiveAnalyzer = object
    sys.modules.setdefault("cognitive_analyzer", cognitive)
    hope = types.ModuleType("hope_detector")
    hope.HopeDetector = object
    sys.modules.setdefault("hope_detector", hope)
    shadow = types.ModuleType("policy_shadow")
    shadow.PolicyShadow = object
    sys.modules.setdefault("policy_shadow", shadow)

    query = types.ModuleType("query")
    for name in ("Snapshot", "bridge_evidence", "cohesion_filter", "ev", "load_store",
                 "misconception_evidence", "need_evidence", "resolve_band",
                 "snapshot_rerank"):
        setattr(query, name, object)
    sys.modules.setdefault("query", query)

    perception = types.ModuleType("perception")
    perception.__path__ = []
    perception.gate = lambda text: None
    sys.modules.setdefault("perception", perception)
    perception_config = types.ModuleType("perception.config")
    perception_config.PERCEPTION_BACKEND = "test"
    sys.modules.setdefault("perception.config", perception_config)

    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *args, **kwargs: None
    sys.modules.setdefault("dotenv", dotenv)


_stub_tutor_imports()

import tutor_loop as tl  # noqa: E402
from learner_state import BRIDGE_MASTERY_DELTA, LearnerState  # noqa: E402
from response_layer.contracts import (  # noqa: E402
    AssessmentHook,
    AssessmentHookType,
    Beat,
    OutcomeEvent,
)
from response_layer.validator import ScriptValidator  # noqa: E402
import state_backend  # noqa: E402
import wini_server  # noqa: E402


def _candidate(**overrides):
    value = {
        "kind": "practice", "id": "item-1", "item_id": "item-1",
        "concept_id": "concept-1", "question": "What is 2 plus 3?",
        "expected_answer": "5", "rubric": "exact sum",
        "assessment_purpose": "practice", "response_type": "number",
        "reveal_policy": "after_attempt", "item_verified": True,
        "verification_provenance": "authored_store",
        "verification_version": "store-v1", "hint_chain": [],
    }
    value.update(overrides)
    return value


def test_hook_roundtrip_and_one_arm() -> None:
    hints = [{"text": "Think about making five."}, {"text": "Start from two."}]
    script = tl.assessment_script(
        _candidate(hint_chain=hints), "ISOMORPHIC_PRACTICE", "concept-1")
    session = {}
    pending = tl.arm_from_script(script, session)
    assert pending is session["pending_check"]
    assert pending["item_verified"] is True
    assert pending["item_id"] == "item-1"
    assert pending["question"] == "What is 2 plus 3?"
    assert pending["hint_chain"] == hints
    assert pending["idempotency_key"].endswith(":b0:1")
    restored = AssessmentHook.from_dict(script.beats[0].assessment_hook.to_dict())
    assert restored.expected_answer == "5"
    assert restored.assessment_purpose == "practice"


def test_unverified_or_multiple_hooks_never_arm() -> None:
    unverified = tl.assessment_script(
        _candidate(item_verified=False), "ISOMORPHIC_PRACTICE", "concept-1")
    assert tl.arm_from_script(unverified, {}) is None
    script = tl.assessment_script(_candidate(), "ISOMORPHIC_PRACTICE", "concept-1")
    script.beats.append(Beat(
        beat_id="b1", pedagogical_step="test_question",
        assessment_hook=AssessmentHook.from_dict(
            script.beats[0].assessment_hook.to_dict())))
    assert tl.arm_from_script(script, {}) is None


def test_delivery_requires_exact_item_and_voids_key_leak() -> None:
    hook = tl._assessment_hook(_candidate(), "s", "b0")
    clean = "Try this now. What is 2 plus 3?"
    leaked = "The answer is 5. What is 2 plus 3?"
    assert tl.assessment_delivery_issue(clean, hook) is None
    assert tl.assessment_delivery_issue(leaked, hook) == "answer_key_leak"
    assert tl.assessment_delivery_issue("Try this now.", hook) == "verified_question_not_delivered"


def test_streaming_preserves_prefix_and_delivers_verified_question() -> None:
    old_vertex = sys.modules.get("llm_vertex")
    fake = types.ModuleType("llm_vertex")
    fake.generate_reply_stream = lambda *args, **kwargs: iter(
        ["Here is one step. ", "Now try it."])
    sys.modules["llm_vertex"] = fake
    chunks = []
    try:
        final = tl._stream_answer(
            "prompt", 100, None, chunks.append, "What is 2 plus 3?")
        assert final == "Here is one step. Now try it. What is 2 plus 3?"
        assert chunks[0] == "Here is one step."
        assert chunks[-1].endswith("What is 2 plus 3?")
    finally:
        if old_vertex is None:
            sys.modules.pop("llm_vertex", None)
        else:
            sys.modules["llm_vertex"] = old_vertex


def test_generated_item_needs_independent_agreement_and_caches_only_verified() -> None:
    old_chat, old_path, old_cache = tl.qwen_chat, tl._VERIFIED_ITEM_CACHE_PATH, tl._VERIFIED_ITEM_CACHE
    calls = []
    try:
        with tempfile.TemporaryDirectory() as td:
            tl._VERIFIED_ITEM_CACHE_PATH = Path(td) / "verified.json"
            tl._VERIFIED_ITEM_CACHE = {}
            replies = iter([
                '{"question":"What is 6 times 7?","expected_answer":"42"}',
                '{"derived_answer":"42","confidence":0.99}',
            ])

            def chat(_prompt, **kwargs):
                calls.append(kwargs.get("temperature"))
                return next(replies)

            tl.qwen_chat = chat
            item = tl.generate_quiz_item(
                {"schema_id": "s1", "method_steps": ["multiply"]}, "multiplication")
            assert item and item["item_verified"] is True
            assert calls == [0.0, 0.0]
            assert json.loads(tl._VERIFIED_ITEM_CACHE_PATH.read_text())[next(
                iter(json.loads(tl._VERIFIED_ITEM_CACHE_PATH.read_text()))
            )]["item_verified"] is True

            tl._VERIFIED_ITEM_CACHE = {}
            tl._VERIFIED_ITEM_CACHE_PATH = Path(td) / "disagree.json"
            replies = iter([
                '{"question":"What is 6 times 7?","expected_answer":"41"}',
                '{"derived_answer":"42","confidence":0.99}',
            ])
            assert tl.generate_quiz_item(
                {"schema_id": "s2", "method_steps": ["multiply"]}, "multiplication") is None
            assert tl._VERIFIED_ITEM_CACHE == {}
    finally:
        tl.qwen_chat, tl._VERIFIED_ITEM_CACHE_PATH, tl._VERIFIED_ITEM_CACHE = \
            old_chat, old_path, old_cache


def test_grader_contract_has_path_confidence_and_consistency() -> None:
    result = tl.judge_answer("What is 2 plus 3?", "5", "5", stt_confidence=0.94,
                             idempotency_key="s:b:1")
    assert result == {
        "outcome": "correct", "confidence": 1.0, "path": "deterministic",
        "misconception_consistent": False, "stt_confidence": 0.94,
        "idempotency_key": "s:b:1",
    }


def test_concurrent_grader_propagates_rubric_confidence_and_idempotency() -> None:
    old_judge = tl.judge_answer
    captured = {}
    try:
        def judge(question, expected, reply, rubric, **kwargs):
            captured.update({"question": question, "expected": expected, "reply": reply,
                             "rubric": rubric, **kwargs})
            return {"outcome": "correct", "confidence": 0.91,
                    "path": "rubric_model", **kwargs}

        tl.judge_answer = judge
        brain = wini_server.Brain.__new__(wini_server.Brain)
        brain.tutor = SimpleNamespace(state=SimpleNamespace(data={"session": {
            "pending_check": {"question": "Why?", "expected_answer": "because",
                              "rubric": "must name the reason",
                              "idempotency_key": "s:b:1"}}}))
        result = brain._maybe_speculate_grade("because", 0.87).result(timeout=2)
        assert result["confidence"] == 0.91
        assert captured["rubric"] == "must name the reason"
        assert captured["stt_confidence"] == 0.87
        assert captured["idempotency_key"] == "s:b:1"
    finally:
        tl.judge_answer = old_judge


def _event(**overrides) -> OutcomeEvent:
    args = {
        "script_id": "s1", "beat_id": "b1", "attempt": 1,
        "assessment_hook_id": "h1", "outcome": "correct",
        "learner_id": "learner-a", "concept_id": "concept-1", "kc_id": "concept-1",
        "item_id": "item-1", "item_source": "authored_store",
        "assessment_purpose": "practice", "grader_path": "deterministic",
        "grader_confidence": 1.0, "stt_confidence": 0.95,
        "payload": {"mutation_kind": "practice", "target_concept": "concept-1"},
    }
    args.update(overrides)
    return OutcomeEvent(**args)


def test_one_idempotent_event_per_mutation_and_replay() -> None:
    state = LearnerState(None, {"learner_id": "learner-a", "concept_states": {}})
    first = state.apply_outcome_event(_event())
    mastery = state.mastery("concept-1")
    duplicate = state.apply_outcome_event(_event())
    assert first["status"] == "applied"
    assert duplicate["status"] == "duplicate"
    assert len(state.evidence_ledger) == 1
    assert round(state.mastery("concept-1"), 4) == round(mastery, 4) == 0.45
    assert round(state.replay_mastery("concept-1"), 4) == round(mastery, 4)

    low = _event(script_id="s2", stt_confidence=0.2)
    assert state.apply_outcome_event(low)["status"] == "suppressed"
    assert len(state.evidence_ledger) == 1
    assert state.mastery("concept-1") == mastery


def test_misconception_requires_converging_consistent_evidence() -> None:
    state = LearnerState(None, {"concept_states": {}})
    correct = state.apply_probe_result("m1", "correct", "c1")
    assert correct["misconception_status"] == "untracked"
    assert "m1" not in state.misconception_states

    inconsistent = state.apply_probe_result("m2", "wrong", "c1", evidence_consistent=False)
    assert inconsistent["misconception_status"] == "untracked"
    assert "m2" not in state.misconception_states

    one = state.apply_probe_result("m1", "wrong", "c1", evidence_consistent=True)
    two = state.apply_probe_result("m1", "wrong", "c1", evidence_consistent=True)
    assert one["misconception_status"] == "candidate"
    assert two["misconception_status"] == "supported"


def test_bridge_partial_is_distinct_from_wrong() -> None:
    assert BRIDGE_MASTERY_DELTA["partial"] > BRIDGE_MASTERY_DELTA["wrong"]
    state = LearnerState(None, {"concept_states": {}})
    result = state.apply_bridge_result("bridge-1", "partial")
    assert result["mastery"] == 0.35


def test_policy_fallback_and_transfer_readiness_gate() -> None:
    update = {"cognitive_load": 0.0, "frustration_risk": 0.0,
              "curiosity": 0.0, "confusion": 0.0}
    assert tl.rules_decide(update, [], [], False)[0] == "EXPLAIN"
    assert tl.rules_decide(update, [], ["transfer_ready_evidence"], False,
                           transfer_ready=False)[0] != "TRANSFER_PROBLEM"
    assert tl.rules_decide(update, [], ["transfer_ready_evidence"], False,
                           transfer_ready=True)[0] == "TRANSFER_PROBLEM"


def test_response_layer_flag_is_shared() -> None:
    assert tl.RESPONSE_LAYER is wini_server.RESPONSE_LAYER


def test_validator_strips_placeholder_assessment() -> None:
    script = tl.assessment_script(_candidate(), "TEST_QUESTION", "concept-1")
    script.beats[0].assessment_hook.item_verified = False
    ScriptValidator().validate(script, evidence_text={}, profile={})
    assert script.beats[0].assessment_hook is None
    assert script.validation["assessment_hooks_ok"] is False


def test_identity_is_distinct_and_never_defaults() -> None:
    names = ("WINI_LEARNER_ID", "WINI_AUTHENTICATED_DEVICE_ID",
             "WINI_AUTHENTICATED_SESSION_ID")
    old = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ.pop(name, None)
        os.environ["WINI_AUTHENTICATED_DEVICE_ID"] = "device-a"
        a = state_backend.resolve_learner_id()
        os.environ["WINI_AUTHENTICATED_DEVICE_ID"] = "device-b"
        b = state_backend.resolve_learner_id()
        assert a != b and a.startswith("learner_") and b.startswith("learner_")
        os.environ.pop("WINI_AUTHENTICATED_DEVICE_ID")
        try:
            state_backend.resolve_learner_id()
        except RuntimeError:
            pass
        else:
            raise AssertionError("missing authenticated identity did not fail closed")
    finally:
        for name, value in old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def test_safety_general_log_is_redacted() -> None:
    old_store = tl.STORE
    try:
        with tempfile.TemporaryDirectory() as td:
            tl.STORE = Path(td)
            loop = tl.TutorLoop.__new__(tl.TutorLoop)
            route = SimpleNamespace(
                primary="SAFETY", reason="deterministic safety", source="gate",
                safety_alert=True, concept_id=None, concept_confidence=0.0)
            loop._log_nonlearning("private crisis text", route, "safe scripted reply")
            row = json.loads((tl.STORE / "learning_log.jsonl").read_text().strip())
            assert row["question"] == "[REDACTED_SAFETY_UTTERANCE]"
            assert row["log_tier"] == "general_redacted"
    finally:
        tl.STORE = old_store


def test_batch_stt_carries_recognition_confidence() -> None:
    google = types.ModuleType("google")
    google.__path__ = []
    cloud = types.ModuleType("google.cloud")
    cloud.__path__ = []

    class RecognitionConfig:
        class AudioEncoding:
            LINEAR16 = "LINEAR16"

        def __init__(self, **kwargs):
            self.kwargs = kwargs

    speech = types.SimpleNamespace(
        SpeechClient=object,
        SpeechContext=lambda **kwargs: kwargs,
        RecognitionConfig=RecognitionConfig,
        RecognitionAudio=lambda **kwargs: kwargs,
    )
    cloud.speech = speech
    sys.modules["google"] = google
    sys.modules["google.cloud"] = cloud
    sys.modules["google.cloud.speech"] = speech

    import importlib
    cloud_stt = importlib.import_module("voice.cloud_stt")
    cloud_stt._dbg = None
    adapter = cloud_stt.CloudStt.__new__(cloud_stt.CloudStt)
    adapter.language = "en-US"
    adapter.model = "latest_short"
    adapter.context = object()
    alternatives = [
        SimpleNamespace(transcript="forty", confidence=0.8),
        SimpleNamespace(transcript="two", confidence=0.6),
    ]
    adapter.client = SimpleNamespace(recognize=lambda **kwargs: SimpleNamespace(results=[
        SimpleNamespace(alternatives=[alternatives[0]]),
        SimpleNamespace(alternatives=[alternatives[1]]),
    ]))
    result = adapter.recognize_pcm_evidence(b"pcm", 16000)
    assert result.transcript == "forty two"
    assert result.confidence == 0.7


def test_low_stt_confidence_preserves_state_and_pending_hook() -> None:
    old_store, old_gate = tl.STORE, tl._front_gate
    try:
        with tempfile.TemporaryDirectory() as td:
            tl.STORE = Path(td)
            tl._front_gate = lambda _text: None
            original = {
                "session": {"pending_check": {"id": "item-1", "question": "What is 2 plus 3?"},
                            "current_concept": "concept-1"},
                "concept_states": {"concept-1": {"mastery": 0.5}},
            }
            data = json.loads(json.dumps(original))
            loop = tl.TutorLoop.__new__(tl.TutorLoop)
            loop.state = SimpleNamespace(data=data)
            result = loop.turn("maybe five", stt_confidence=0.2)
            assert result["action"] == "CONFIRM_LOW_CONFIDENCE"
            assert data == original
    finally:
        tl.STORE, tl._front_gate = old_store, old_gate


def _run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {test.__name__}: {exc!r}")
    print(f"\n{len(tests) - failed} passed, {failed} failed ({len(tests)} total)")
    return failed


if __name__ == "__main__":
    raise SystemExit(_run())
