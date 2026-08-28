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
    try:
        import numpy
    except ImportError:
        numpy = types.ModuleType("numpy")
        numpy.ndarray = object
        sys.modules.setdefault("numpy", numpy)
    try:
        import requests
    except ImportError:
        sys.modules.setdefault("requests", types.ModuleType("requests"))

    try:
        import cognitive_analyzer
    except ImportError:
        cognitive = types.ModuleType("cognitive_analyzer")
        cognitive.CognitiveAnalyzer = object
        sys.modules.setdefault("cognitive_analyzer", cognitive)
    try:
        import hope_detector
    except ImportError:
        hope = types.ModuleType("hope_detector")
        hope.HopeDetector = object
        sys.modules.setdefault("hope_detector", hope)
    try:
        import policy_shadow
    except ImportError:
        shadow = types.ModuleType("policy_shadow")
        shadow.PolicyShadow = object
        sys.modules.setdefault("policy_shadow", shadow)

    try:
        import query
    except ImportError:
        query = types.ModuleType("query")
        for name in ("Snapshot", "bridge_evidence", "cohesion_filter", "ev", "load_store",
                     "misconception_evidence", "need_evidence", "resolve_band",
                     "snapshot_rerank"):
            setattr(query, name, object)
        sys.modules.setdefault("query", query)

    perception = types.ModuleType("perception")
    perception.__path__ = []
    perception.gate = lambda text: None
    from perception.interface import LegacyPerceptionEngine, Perception
    perception.LegacyPerceptionEngine = LegacyPerceptionEngine
    perception.Perception = Perception
    sys.modules.setdefault("perception", perception)
    sys.modules["perception.interface"] = sys.modules.get("perception.interface") or perception
    perception_config = types.ModuleType("perception.config")
    perception_config.PERCEPTION_BACKEND = "test"
    sys.modules.setdefault("perception.config", perception_config)

    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *args, **kwargs: None
    sys.modules.setdefault("dotenv", dotenv)


_stub_tutor_imports()

import tutor_loop as tl  # noqa: E402
from learner_state import BRIDGE_MASTERY_DELTA, LearnerState  # noqa: E402
from evidence import record_outcome, replay  # noqa: E402
from items import CandidateItem, VerifiedItemBank, verify  # noqa: E402
from response_layer.contracts import (  # noqa: E402
    AssessmentHook,
    AssessmentHookType,
    Beat,
    OutcomeEvent,
)
from response_layer.validator import ScriptValidator  # noqa: E402
from response_layer.arming import pending_is_assessable, void_pending_assessment  # noqa: E402
from response_layer.realization import check_realization  # noqa: E402
from evidence.grading import obvious_non_attempt  # noqa: E402
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
        "verification_version": "store-v1", "verification_status": "authored_verified",
        "verification_token": "authored-test-token", "hint_chain": [],
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
    assert pending["idempotency_key"] is None  # filled from learner+turn+reply at grading
    restored = AssessmentHook.from_dict(script.beats[0].assessment_hook.to_dict())
    assert restored.expected_answer == "5"
    assert restored.assessment_purpose == "practice"


def test_unverified_or_multiple_hooks_never_arm() -> None:
    unverified = tl.assessment_script(
        _candidate(item_verified=False, verification_status="unverified",
                   verification_token=None), "ISOMORPHIC_PRACTICE", "concept-1")
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
    with tempfile.TemporaryDirectory() as td:
        bank = VerifiedItemBank(Path(td) / "verified.jsonl")
        candidate = CandidateItem(
            concept_id="multiplication", question="What is 6 times 7?",
            expected_answer="42")
        item = verify(candidate, independent_answer="42", bank=bank)
        assert item and item.item_verified
        assert bank.select("multiplication", "check_independent").item_id == item.item_id
        disagree = CandidateItem(
            concept_id="multiplication", question="What is 6 times 7?",
            expected_answer="41")
        assert verify(disagree, independent_answer="42", bank=bank) is None
        assert len(bank.load()) == 1


def test_item_verifier_rejects_malformed_uncertain_unsupported_and_adapter_bypass() -> None:
    from items import from_authored
    malformed = CandidateItem(
        concept_id="c1", question="not a question", expected_answer="5")
    uncertain = CandidateItem(
        concept_id="c1", question="What is 2 plus 3?", expected_answer="5")
    unsupported = CandidateItem(
        concept_id="c1", question="What is 2 plus 3?", expected_answer="5",
        response_type="video")
    assert verify(malformed, independent_answer="5", cache=False) is None
    assert verify(uncertain, independent_answer="5", verifier_confidence=0.89,
                  cache=False) is None
    assert verify(unsupported, independent_answer="5", cache=False) is None
    assert from_authored({
        "id": "generated-bypass", "concept_id": "c1",
        "question": "What is 2 plus 3?", "expected_answer": "5",
        "item_source": "generated",
    }) is None


def test_grader_contract_has_path_confidence_and_consistency() -> None:
    result = tl.judge_answer("What is 2 plus 3?", "5", "5", stt_confidence=0.94,
                             idempotency_key="s:b:1")
    assert result.outcome == "correct"
    assert result.grader_path == "deterministic"
    assert result.confidence == 1.0 and result.stt_confidence == 0.94
    assert result.idempotency_key == "s:b:1"


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
                              "rubric": "must name the reason", "kind": "practice",
                              "item_id": "item-1"}}}))
        result = brain._maybe_speculate_grade(
            "because", 0.87, turn_id="turn-1", learner_id="learner-a").result(timeout=2)
        assert result["confidence"] == 0.91
        assert captured["rubric"] == "must name the reason"
        assert captured["stt_confidence"] == 0.87
        assert captured["idempotency_key"]
    finally:
        tl.judge_answer = old_judge


def test_serial_and_concurrent_grading_share_grade_result_contract() -> None:
    brain = wini_server.Brain.__new__(wini_server.Brain)
    brain.tutor = SimpleNamespace(state=SimpleNamespace(data={"session": {
        "pending_check": {"question": "What is 2 plus 3?", "expected_answer": "5",
                          "rubric": "exact sum", "kind": "practice",
                          "item_id": "item-1"}}}))
    serial = tl.judge_answer(
        "What is 2 plus 3?", "5", "5", "exact sum",
        stt_confidence=0.9, idempotency_key="shared-key")
    concurrent = brain._maybe_speculate_grade(
        "5", 0.9, turn_id="turn-1", learner_id="learner-a").result(timeout=2)
    assert isinstance(serial, type(concurrent))
    assert serial.outcome == concurrent.outcome == "correct"
    assert serial.grader_path == concurrent.grader_path == "deterministic"


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

    # Ticket 05: stt_confidence is no longer a gate inside record_outcome.
    # Authorization is the gate — an UNAUTHORIZED transcript is rejected upstream
    # in assessment_evidence/interface.py before record_outcome is ever called.
    # A call that reaches record_outcome with stt_confidence=0.2 but
    # grader_confidence=1.0 is now APPLIED (the grader confidence gate still
    # holds; the stt_confidence float check was deliberately deleted).
    low = _event(script_id="s2", stt_confidence=0.2)
    assert state.apply_outcome_event(low)["status"] == "applied"
    assert len(state.evidence_ledger) == 2
    assert state.mastery("concept-1") > mastery


def test_misconception_requires_converging_consistent_evidence() -> None:
    state = LearnerState(None, {"concept_states": {}})
    correct = record_outcome(state, _event(
        script_id="mis-correct", turn_id="mis-correct", item_id="m1",
        concept_id="c1", outcome="correct",
        consistent_with_misconception=False,
        payload={"mutation_kind": "misconception", "target_concept": "c1"}))
    assert correct["misconception_status"] == "untracked"
    assert "m1" not in state.misconception_states

    inconsistent = record_outcome(state, _event(
        script_id="mis-no", turn_id="mis-no", item_id="m2", concept_id="c1",
        outcome="wrong", consistent_with_misconception=False,
        payload={"mutation_kind": "misconception", "target_concept": "c1"}))
    assert inconsistent["misconception_status"] == "untracked"
    assert "m2" not in state.misconception_states

    one = record_outcome(state, _event(
        script_id="mis-one", turn_id="mis-one", item_id="m1", concept_id="c1",
        outcome="wrong", consistent_with_misconception=True,
        payload={"mutation_kind": "misconception", "target_concept": "c1"}))
    two = record_outcome(state, _event(
        script_id="mis-two", turn_id="mis-two", item_id="m1", concept_id="c1",
        outcome="wrong", consistent_with_misconception=True,
        payload={"mutation_kind": "misconception", "target_concept": "c1"}))
    assert one["misconception_status"] == "candidate"
    assert two["misconception_status"] == "supported"


def test_bridge_partial_is_distinct_from_wrong() -> None:
    assert BRIDGE_MASTERY_DELTA["partial"] > BRIDGE_MASTERY_DELTA["wrong"]
    state = LearnerState(None, {"concept_states": {}})
    result = record_outcome(state, _event(
        script_id="bridge", turn_id="bridge", item_id="bridge-1",
        concept_id="c1", outcome="partial",
        payload={"mutation_kind": "bridge"}))
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
    script.beats[0].assessment_hook.verification_status = "unverified"
    script.beats[0].assessment_hook.verification_token = None
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


def test_safety_alert_store_is_tiered_and_contains_no_raw_child_text() -> None:
    old_store = tl.STORE
    try:
        with tempfile.TemporaryDirectory() as td:
            tl.STORE = Path(td)
            loop = tl.TutorLoop.__new__(tl.TutorLoop)
            loop.state = SimpleNamespace(data={"learner_id": "learner-a"})
            loop._notify_supervisor = lambda _record: None
            route = SimpleNamespace(source="gate", safety_tier=3,
                                    safety_category="urgent_danger")
            raw = "private child safety disclosure"
            loop._log_safety(raw, route)
            row = json.loads((tl.STORE / "safety_alerts.jsonl").read_text().strip())
            assert row["safety_tier"] == 3 and row["safety_category"] == "urgent_danger"
            assert "utterance" not in row and raw not in json.dumps(row)
            assert len(row["utterance_sha256"]) == 64
    finally:
        tl.STORE = old_store


def test_sparse_global_ema_counts_only_observed_signals() -> None:
    import importlib.util
    analyzer_path = Path(__file__).resolve().parent / "cognitive_analyzer" / "analyzer.py"
    spec = importlib.util.spec_from_file_location("p0_sparse_analyzer", analyzer_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    update = module.derive_cognitive_update({})
    no_evidence = module.derive_state_deltas(
        update, [], {"concept_id": "c1"})
    assert no_evidence["global"] == {}
    state = LearnerState(None, {"concept_states": {}, "global": {"curiosity": 0.8}})
    module.apply_deltas(state, no_evidence)
    assert state.data["global"]["curiosity"] == 0.8
    observed = module.derive_state_deltas(
        module.derive_cognitive_update({"curiosity": 0.9}),
        ["curiosity"], {"concept_id": "c1"})
    module.apply_deltas(state, observed)
    assert state.data["global_observations"]["curiosity"] == 1


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
    """Ticket 05: IC backward-compat gate — stt_confidence < 0.45 with observation=None
    returns CONFIRM_LOW_CONFIDENCE and never mutates session state.

    The coordinator always supplies an intake observation for typed turns, so this
    gate is now only reachable via a direct IC call (observation=None).  The
    production invariant — VOICE below the confidence floor must never mutate learner
    state — is enforced via Authorization.UNAUTHORIZED (tested in test_repair_roundtrip.py).
    """
    from interaction_control import (
        CapabilityTransition,
        InteractionControl,
        InteractionControlDependencies,
        InteractionControlRequest,
    )
    from runtime.contracts import DeviceCapabilities, TurnBudgets, TurnInput

    session = {
        "pending_check": {"id": "item-1", "question": "What is 2 plus 3?"},
        "current_concept": "concept-1",
    }
    original_session = json.loads(json.dumps(session))

    turn_input = TurnInput(
        turn_id="t-low-conf",
        learner_id="l-1",
        interaction={"text": "maybe five"},
        device=DeviceCapabilities(),
        budgets=TurnBudgets(total_ms=10_000),
        trusted_observations={"stt_confidence": 0.2},
    )
    # CONFIRM_LOW_CONFIDENCE fires before any capability port is called,
    # so all ports can be no-op stubs.
    _noop_cap = lambda *_a, **_kw: CapabilityTransition()  # noqa: E731
    deps = InteractionControlDependencies(
        deterministic_route=lambda text: None,
        perception_route=lambda text, session: None,
        analyze=lambda text, current: {},
        persona={"identity": "Wini", "style": "Warm", "intents": {}},
        want_answer=False,
        generation_backend="fixture",
        generate_persona=lambda prompt: "generated",
        concept_name=lambda concept_id: "Math",
        topic_candidates=lambda text, limit: [],
        chapter_for_concept=lambda concept_id: None,
        # Slice 07 (2026-08-28): extract_topic_request / is_bare_topic deleted.
        wants_different_topic=lambda text: False,
        concept_relates_to_topic=lambda new, old: False,
        mode_cue=lambda text: None,
        current_mode=lambda session: "EXPLAIN",
        set_mode=_noop_cap,
        consume_mode_offer=_noop_cap,
        consume_test_resume=_noop_cap,
        check_frozen_test=_noop_cap,
        clear_pending_assessment=_noop_cap,
        log_event=lambda event: None,
        notify_safety=lambda record: None,
        now=lambda: "2026-08-28T00:00:00",
    )
    request = InteractionControlRequest(
        turn_input=turn_input,
        session=dict(session),
        observation=None,  # backward-compat path: no intake observation
    )
    outcome = InteractionControl(deps).control(request)
    assert outcome.value is not None
    assert outcome.value.compatibility["action"] == "CONFIRM_LOW_CONFIDENCE"
    # Session was not mutated (IC returns before any state write)
    assert session == original_session


def test_non_attempts_never_grade_wrong() -> None:
    for reply in ("okay", "I don't understand", "can you explain?", "why?", "next topic"):
        assert obvious_non_attempt(reply)
        result = tl.judge_answer("What is 2 plus 3?", "5", reply)
        assert result.outcome == "not_an_answer"
        assert result.grader_path == "non_attempt_gate"
    from response_layer.outcomes import _normalise
    assert _normalise("nonresponse") == "not_an_answer"


def test_grader_failure_is_insufficient_evidence_when_math_floor_defers() -> None:
    from evidence.grading import grade_answer
    result = grade_answer(
        "What relationship holds between DE and BC?", "DE is parallel to BC",
        "They have a relationship", "must explicitly say parallel",
        model_call=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    assert result.outcome == "not_an_answer"
    assert result.confidence == 0.0 and result.grader_path == "grader_unavailable"


def test_one_binary_result_cannot_support_misconception() -> None:
    state = LearnerState(None, {"learner_id": "learner-a", "concept_states": {}})
    result = record_outcome(state, _event(
        script_id="binary-one", turn_id="binary-one", item_id="m-binary",
        concept_id="c1", outcome="wrong", consistent_with_misconception=True,
        payload={"mutation_kind": "misconception", "target_concept": "c1",
                 "binary_item": True}))
    assert result["misconception_status"] == "candidate"
    assert state.misconception_states["m-binary"]["status"] == "candidate"


def test_hint_request_is_session_only_until_outcome_ledger_projection() -> None:
    state = LearnerState(None, {"learner_id": "learner-a", "concept_states": {}})
    assert state.record_hint_request("c1", "item-hint") == 1
    assert "c1" not in state.concept_states
    record_outcome(state, _event(
        script_id="hint-outcome", turn_id="hint-outcome", item_id="item-hint",
        concept_id="c1", assistance_offered=1, assistance_consumed=1,
        payload={"mutation_kind": "practice", "target_concept": "c1",
                 "hints_used": 1}))
    assert state.concept_states["c1"]["hint_dependency"] > 0
    assert state.hint_chain_position("c1", "item-hint") == 0


def test_full_projection_replay_matches_derived_learning_state() -> None:
    state = LearnerState(None, {
        "learner_id": "learner-a", "concept_states": {},
        "misconception_states": {}, "global": {}, "session": {"bridges_served": []},
    })
    record_outcome(state, _event(
        script_id="r1", turn_id="r1", item_id="practice-1", concept_id="c1",
        outcome="correct", ts="2026-08-01T10:00:00+00:00"))
    record_outcome(state, _event(
        script_id="r2", turn_id="r2", item_id="mis-1", concept_id="c1",
        outcome="wrong", consistent_with_misconception=True,
        ts="2026-08-02T10:00:00+00:00",
        payload={"mutation_kind": "misconception", "target_concept": "c1"}))
    rebuilt = replay(state.evidence_ledger,
                     base_state=state.data["evidence_projection_base"])
    assert rebuilt.concept_states == state.concept_states
    assert rebuilt.misconception_states == state.misconception_states


def test_answer_leak_voids_assessment_and_corrupted_reply_is_unscoreable() -> None:
    hook = tl._assessment_hook(_candidate(), "s", "b")
    result = check_realization(
        "The answer is 5. What is 2 plus 3?", hook=hook,
        grounded_text="What is 2 plus 3?", learner_text="")
    assert result.assessment_corrupted and "answer_key_leak" in result.flags
    session = {"pending_check": tl.arm_from_script(
        tl.assessment_script(_candidate(), "TEST_QUESTION", "concept-1"), {})}
    # Recreate a normally armed session, then void it exactly as post-stream validation does.
    session = {}
    tl.arm_from_script(tl.assessment_script(
        _candidate(), "TEST_QUESTION", "concept-1"), session)
    void_pending_assessment(session, reason="answer_key_leak", item_id="item-1")
    assert not pending_is_assessable(session.get("pending_check"))
    assert session["voided_check"]["reason"] == "answer_key_leak"


def test_realization_belts_flag_unsupported_content_and_budget() -> None:
    hook = tl._assessment_hook(_candidate(), "s", "b")
    result = check_realization(
        "Use 99 first. What is 2 plus 3?", hook=hook,
        grounded_text="2 3", max_words=5,
        correcting_misconception=True, misconception_supported=False)
    assert {"unsupported_number", "response_budget_exceeded",
            "unsupported_misconception_correction"}.issubset(result.flags)


def test_test_question_is_verbatim_and_never_reveals_key_or_instructional_visual() -> None:
    question = "What is 2 plus 3?"
    line = tl.TutorLoop._test_question_line(1, 5, question, None)
    assert line.endswith(question) and "5" not in line
    card = tl.TutorLoop._mode_display({
        "action": "TEST_QUESTION", "question": question, "item_no": 1, "of": 5})
    assert card == [{"kind": "question_card", "text": question, "item_no": 1, "of": 5}]


def test_learner_states_are_isolated_and_cross_identity_event_fails() -> None:
    a = LearnerState(None, {"learner_id": "learner-a", "concept_states": {}})
    b = LearnerState(None, {"learner_id": "learner-b", "concept_states": {}})
    record_outcome(a, _event(script_id="a", turn_id="a"))
    assert a.mastery("concept-1") != b.mastery("concept-1")
    try:
        record_outcome(b, _event(script_id="cross", turn_id="cross",
                                 learner_id="learner-a"))
    except ValueError as exc:
        assert "learner_id" in str(exc)
    else:
        raise AssertionError("cross-learner event was accepted")


def test_backward_migration_is_additive_and_recoverable() -> None:
    from evidence import migrate_state_data
    legacy = {
        "learner_id": "learner-a", "concept_states": {"c1": {"mastery": 0.4}},
        "misconception_states": {"m1": {"status": "active", "consecutive_failures": 1}},
        "session": {"pending_check": {"id": "old", "question": "Old question?"}},
    }
    migrated = migrate_state_data(json.loads(json.dumps(legacy)))
    assert migrated["concept_states"] == legacy["concept_states"]
    assert migrated["misconception_states"]["m1"]["status"] == "candidate"
    assert migrated["session"]["pending_check"]["verification_status"] == "legacy_unverified"
    assert migrated["state_schema_version"] >= 2


def test_three_single_writer_boundaries_and_critical_path_are_static() -> None:
    root = Path(__file__).resolve().parent
    py_files = [p for p in root.rglob("*.py")
                if "__pycache__" not in p.parts and not p.name.startswith("test_")]
    sources = {p: p.read_text(encoding="utf-8") for p in py_files}
    pending_writers = [(p, text.count('session["pending_check"] ='))
                       for p, text in sources.items() if 'session["pending_check"] =' in text]
    assert pending_writers == [(root / "response_layer" / "arming.py", 1)]
    projection_callers = [p for p, text in sources.items()
                          if "state._project_item_result(" in text
                          or "state._project_probe_result(" in text
                          or "state._project_bridge_result(" in text]
    assert projection_callers == [root / "evidence" / "ledger.py"]
    cache_writers = [p for p, text in sources.items() if "._append_verified(" in text]
    assert cache_writers == [root / "items" / "verify.py"]
    tutor_source = sources[root / "tutor_loop.py"]
    practice_body = tutor_source[tutor_source.index("    def _practice_gradeable"):
                                  tutor_source.index("    def _concept_schema_ids")]
    test_body = tutor_source[tutor_source.index("    def _drive_test"):
                              tutor_source.index("    @staticmethod\n    def _test_question_line")]
    assert "generate_quiz_item(" not in practice_body + test_body
    assert "verify_item(" not in practice_body + test_body


def test_retrieval_floor_and_safety_order_remain_in_force() -> None:
    query_source = (Path(__file__).resolve().parent / "query.py").read_text(encoding="utf-8")
    assert 'MIN_ABS_RELEVANCE = float(os.getenv("RETRIEVAL_MIN_RELEVANCE", "0.28"))' in query_source
    assert "if not eligible:" in query_source and '"abstained": True' in query_source
    turn_source = Path(tl.__file__).read_text(encoding="utf-8")
    turn_body = turn_source[turn_source.index("    def turn("):
                            turn_source.index("    @staticmethod\n    def _test_echo")]
    assert turn_body.index("_front_gate(text)") < turn_body.index("record_outcome(self.state, event)")


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
