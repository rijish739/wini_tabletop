"""Offline tests for the Part 11 perception front door.

Fast (no torch, no network):  python -m perception.test_perception
With the full tutor loop:      python -m perception.test_perception --integration

The Gemini call is injected (call_fn), so the adapter, validation belt, and the
classify/resolve/route interfaces are exercised without any Vertex call.
"""

from __future__ import annotations

import sys

from .gates import gate, is_nonsense, is_safety
from .gemini_perception import GeminiPerception
from .route import INHERIT


# --------------------------------------------------------------------------- #
# Gates (pure, model-free)
# --------------------------------------------------------------------------- #
def test_gates():
    for t in ["i want to kill myself", "my dad hits me at home", "i want to die",
              "someone touched me in a bad way", "i wish i was dead"]:
        assert is_safety(t), f"SAFETY missed: {t!r}"
        assert gate(t).primary == "SAFETY"
        assert gate(t).safety_alert is True
    # SAFETY beats NONSENSE priority
    assert gate("kill myself !!!").primary == "SAFETY"

    for t in ["", "   ", "!!!", "?????", "aaaaaa", "sdfghjk", "...."]:
        assert is_nonsense(t), f"NONSENSE missed: {t!r}"
        assert gate(t).primary == "NONSENSE"

    # real (terse) maths answers must PASS THROUGH (no gate) — never gated
    for t in ["5", "yes", "x=2", "is it 0", "42", "no", "cos", "why",
              "i think it is 12", "the answer is 7", "what is a factor"]:
        assert not is_nonsense(t), f"NONSENSE false-positive: {t!r}"
        assert not is_safety(t), f"SAFETY false-positive: {t!r}"
        assert gate(t) is None, f"gate should pass through: {t!r}"


# --------------------------------------------------------------------------- #
# Validation belt (§5.5a) — no torch, mocked call
# --------------------------------------------------------------------------- #
def _gp(response):
    """A GeminiPerception whose one Gemini call returns `response` (dict|None|callable)."""
    def call_fn(prompt, system):
        return response(prompt) if callable(response) else response
    return GeminiPerception(call_fn=call_fn)


def test_validation_belt():
    gp = _gp(None)  # total failure -> graceful fallback
    p = gp._perceive("anything")
    assert p["_source"] == "fallback"
    assert p["intent"] == "LEARNING" and p["concept_id"] == INHERIT and p["signal_scores"] == {}

    # invalid intent -> fallback
    assert _gp({"intent": "BOGUS"})._perceive("x")["_source"] == "fallback"

    # OOV concept coerced to INHERIT; OOV signal dropped; values clamped; valid kept
    gp = _gp({
        "intent": "LEARNING",
        "concept_id": "not_a_real_concept",
        "concept_confidence": 5.0,
        "secondary_concepts": ["jemh104__quadratic_formula", "also_bogus"],
        "signal_scores": {"confusion": 1.7, "made_up_signal": 0.9, "curiosity": 0.6},
        "answer_attempt": "yes", "safety": 0,
    })
    p = gp._perceive("x")
    assert p["_source"] == "gemini"
    assert p["concept_id"] == INHERIT                     # OOV -> inherit
    assert p["concept_confidence"] == 1.0                 # clamped
    assert p["secondary_concepts"] == ["jemh104__quadratic_formula"]  # bogus dropped
    assert "made_up_signal" not in p["signal_scores"]     # OOV signal dropped
    assert p["signal_scores"]["confusion"] == 1.0         # clamped
    assert p["answer_attempt"] is True and p["safety"] is False


def test_interface_shapes():
    labels_probe = _gp({"intent": "LEARNING", "concept_id": INHERIT,
                        "signal_scores": {}, "answer_attempt": False, "safety": False})
    clf = labels_probe.classify("hello", top_evidence=0)
    assert set(clf) == {"signals", "scores", "evidence"}
    assert len(clf["scores"]) == 38 and clf["signals"] == []

    # classify: a high signal crosses the threshold and is returned
    gp = _gp({"intent": "LEARNING", "concept_id": "jemh104__quadratic_formula",
              "concept_confidence": 0.8,
              "signal_scores": {"confusion": 0.9, "curiosity": 0.1},
              "answer_attempt": False, "safety": False})
    clf = gp.classify("i am confused")
    assert "confusion" in clf["signals"] and "curiosity" not in clf["signals"]

    # resolve: concrete concept
    r = gp.resolve("i am confused", current_concept="jemh101__x")
    assert r["concept_id"] == "jemh104__quadratic_formula" and r["abstained"] is False

    # resolve: INHERIT -> abstain to session concept (resolver contract §6)
    gpi = _gp({"intent": "LEARNING", "concept_id": INHERIT, "signal_scores": {},
               "answer_attempt": False, "safety": False})
    r = gpi.resolve("hmm", current_concept="jemh105__nth_term_formula")
    assert r["abstained"] is True and r["concept_id"] == "jemh105__nth_term_formula"

    # route: intents + safety escalation net
    assert _gp({"intent": "SOCIAL", "concept_id": INHERIT, "signal_scores": {},
                "answer_attempt": False, "safety": False}).route("hi").primary == "SOCIAL"
    rr = _gp({"intent": "LEARNING", "concept_id": INHERIT, "signal_scores": {},
              "answer_attempt": True, "safety": True}).route("i want to hurt myself")
    assert rr.safety_alert is True and rr.answer_attempt is True

    # one Gemini call per utterance: route + classify + resolve share the memo
    calls = {"n": 0}

    def counting(prompt, system):
        calls["n"] += 1
        return {"intent": "LEARNING", "concept_id": INHERIT, "signal_scores": {},
                "answer_attempt": False, "safety": False}
    gp = GeminiPerception(call_fn=counting)
    gp.route("same text"); gp.classify("same text"); gp.resolve("same text")
    assert calls["n"] == 1, f"expected 1 memoized call, got {calls['n']}"


# --------------------------------------------------------------------------- #
# Front-door reply policies (offline; no store, no model, no LLM call).
# Regressions from gemini_tutor_issues.md: retention after "bye", and
# visualization pleas answered with re-definitions.
# --------------------------------------------------------------------------- #
def test_session_policy():
    import json as _json
    from pathlib import Path

    from tutor_loop import TutorLoop
    from .route import RouteResult

    # bare loop: only the attributes the non-learning reply path touches
    loop = TutorLoop.__new__(TutorLoop)
    loop.persona = _json.loads(
        (Path(__file__).resolve().parents[1] / "persona.json").read_text(encoding="utf-8"))
    loop.want_answer = True  # LLM would normally run — the END path must not reach it
    route = RouteResult(primary="SESSION_CONTROL", source="gemini")

    # explicit goodbye -> ended immediately, scripted farewell, no question asked
    session: dict = {}
    loop._apply_session_control(session, "No, I want to go. Bye.")
    assert session["status"] == "ended", session
    reply = loop._nonlearning_reply(route, "No, I want to go. Bye.", session)
    assert reply and "?" not in reply, f"farewell must not ask anything: {reply!r}"

    # soft pause then a SECOND leave request -> hard stop (two-strikes rule)
    session = {}
    loop._apply_session_control(session, "can we stop, i am tired")
    assert session["status"] == "paused" and session["leave_requests"] == 1
    loop._apply_session_control(session, "no, i do not want to do the same right now")
    assert session["status"] == "ended" and session["leave_requests"] == 2
    reply = loop._nonlearning_reply(route, "no, i do not want to do the same right now", session)
    assert reply and "?" not in reply, f"second leave must end cleanly: {reply!r}"

    # SESSION_CONTROL persona prompt (pause path) must forbid steering back
    session = {"status": "paused", "context": []}
    prompt = loop._persona_prompt(route, "i'm tired", session,
                                  loop.persona["intents"]["SESSION_CONTROL"])
    assert "Do NOT ask any question" in prompt
    assert "current topic is" not in prompt

    # SOCIAL prompt carries the recent conversation so "I was right" is answerable
    session = {"context": [
        {"role": "student", "text": "the height is the opposite side?"},
        {"role": "wini", "text": "Yes — the height is opposite to the angle of elevation."},
    ]}
    prompt = loop._persona_prompt(RouteResult(primary="SOCIAL", source="gemini"),
                                  "Wini, I was right!", session,
                                  loop.persona["intents"]["SOCIAL"])
    assert "RECENT CONVERSATION" in prompt and "opposite" in prompt


def test_visual_routing():
    from cognitive_classifier.cues import is_visualization_request
    from tutor_loop import rules_decide

    for t in ["I cannot imagine this", "i can't picture it", "I am not able to visualise that",
              "how does it look?", "hard to imagine this in my head"]:
        assert is_visualization_request(t), f"visual cue missed: {t!r}"
    for t in ["i cannot understand this", "what is the discriminant?", "the answer is 7",
              "picture", "i drew the diagram already"]:
        assert not is_visualization_request(t) or t == "picture", f"false visual cue: {t!r}"

    neutral = {"cognitive_load": 0.2, "frustration_risk": 0.1, "curiosity": 0.3, "confusion": 0.5}
    # a visualization plea outranks the generic re-explain (rule 1b)
    action, need, _ = rules_decide(neutral, [], [], False, clarification=True, visual=True)
    assert action == "REPRESENTATION_TRANSLATION" and need == "integrate"
    # without the visual cue the clarification path is unchanged
    action, _, _ = rules_decide(neutral, [], [], False, clarification=True)
    assert action == "EXPLAIN"


def test_purpose_routing():
    """2026-07-03 transcript: purpose/connection questions must be ANSWERED, not
    met with a transfer problem / definition / encouragement."""
    from cognitive_classifier.cues import is_purpose_question, is_learning_request
    from tutor_loop import rules_decide

    for t in ["why do i have to learn quadratic equations",
              "but how this is related to quadratic equation,",
              "No, you didn't answer my question. Like how the previous example was related to quadratic equation,",
              "why the previous example is connected to quadratic?",
              "what is the use of trigonometry",
              "when will i ever use this",
              "what does this have to do with circles"]:
        assert is_purpose_question(t), f"purpose cue missed: {t!r}"
    for t in ["what is the discriminant?", "give me an example", "i am confused",
              "the answer is 7", "i want to learn about triangles"]:
        assert not is_purpose_question(t), f"false purpose cue: {t!r}"

    neutral = {"cognitive_load": 0.2, "frustration_risk": 0.1, "curiosity": 0.7, "confusion": 0.2}
    # rule 1w beats the curiosity->SOCRATIC and transfer paths
    action, need, _ = rules_decide(neutral, ["question", "transfer_attempt"], [], False, purpose=True)
    assert action == "WHY_IT_MATTERS" and need == "explain", action
    # and beats the frustration/encourage path (turn-5 regression)
    frustrated = {"cognitive_load": 0.5, "frustration_risk": 0.7, "curiosity": 0.2, "confusion": 0.6}
    action, _, _ = rules_decide(frustrated, ["frustration"], [], False, purpose=True)
    assert action == "WHY_IT_MATTERS", action

    # explicit learning requests (turn-1 regression: "I want to learn about the
    # quadratic equation" -> QUIZ)
    for t in ["I want to learn about the quadratic equation.", "teach me trigonometry",
              "can you explain circles"]:
        assert is_learning_request(t), f"learning request missed: {t!r}"
    assert not is_learning_request("the answer is 7")


def test_topic_shift():
    from cognitive_classifier.cues import extract_topic_request, is_bare_topic
    from tutor_loop import TutorLoop

    # explicit request extraction — the REQUESTED topic, never the negated mention
    span = extract_topic_request(
        "No, I asked about natural. Numbers are explaining me quadratic equation.")
    assert span == "natural", span
    assert extract_topic_request("i asked about natural numbers, not this") == "natural numbers"
    assert extract_topic_request("teach me triangles") == "triangles"
    assert extract_topic_request("can we do probability") == "probability"
    assert extract_topic_request("switch to circles") == "circles"
    assert extract_topic_request("i want to learn about it") is None      # pronoun
    assert extract_topic_request("the answer is 7") is None

    # bare topic labels
    assert is_bare_topic("Natural numbers.")
    assert is_bare_topic("Trigonometry")
    for t in ["yes", "no", "x=2", "the answer is 7", "is it 0?", "okay thanks",
              "what is a factor", "45"]:
        assert not is_bare_topic(t), f"false bare topic: {t!r}"

    # pending_shift consumption on a bare loop (no store, no model)
    loop = TutorLoop.__new__(TutorLoop)
    loop.concepts_by_id = {}
    import networkx as nx
    loop.graph = nx.DiGraph()

    class _S:  # minimal state stub: no path -> no save
        path = None
        data: dict = {}
    loop.state = _S()

    # bare "no" declines: offer cleared, scripted continue-reply, no LLM
    session = {"pending_shift": {"concept_id": "jemh108__intro_trigonometry",
                                 "name": "Introduction to Trigonometry"},
               "current_concept": "jemh104__quadratic_formula"}
    out = loop._consume_pending_shift(session, "no", None)
    assert out is not None and out["action"] == "TOPIC_SHIFT_DECLINED"
    assert "pending_shift" not in session and out["answer_source"] == "scripted"
    assert session["current_concept"] == "jemh104__quadratic_formula"

    # anything longer than yes/no cancels the offer and falls through
    session["pending_shift"] = {"concept_id": "x", "name": "X"}
    assert loop._consume_pending_shift(session, "actually explain the formula again", None) is None
    assert "pending_shift" not in session


# --------------------------------------------------------------------------- #
# Full front-door integration (loads store + MiniLM; qwen_heads default backend)
# --------------------------------------------------------------------------- #
def integration():
    import json
    from pathlib import Path

    from tutor_loop import ROOT, TutorLoop

    # fresh scratch state so we can assert "no cognitive state moved"
    state_path = Path(ROOT) / "_perception_test_state.json"
    if state_path.exists():
        state_path.unlink()
    loop = TutorLoop(state_path=state_path, want_answer=False, use_judge=False)

    # seed a pending_check + a concept so we can prove they survive a non-learning turn
    loop.state.data.setdefault("session", {})["current_concept"] = "jemh104__quadratic_formula"
    loop.state.data["session"]["pending_check"] = {
        "kind": "misconception", "id": "probe::x", "concept_id": "jemh104__quadratic_formula",
        "question": "what is the discriminant?", "expected_answer": "b^2-4ac", "hint_chain": [],
    }
    before = json.dumps(loop.state.data.get("concept_states", {}), sort_keys=True)

    # SAFETY (deterministic gate) — scripted reply, alert persisted, no state move
    out = loop.turn("i want to hurt myself")
    assert out["action"] == "SAFETY", out["action"]
    assert out["display"] == [] and out["answer"] and "trust" in out["answer"].lower()
    assert loop.state.data.get("safety_alerts"), "safety alert not persisted"
    assert out["pending_check"] == "probe::x", "pending_check must be preserved"

    # NONSENSE (deterministic gate) — a vowel-less keyboard mash the gate owns
    # ("asdkfj qptz" has vowels, so it is left to the model, not this gate).
    out = loop.turn("sdfghjkl")
    assert out["action"] == "NONSENSE" and out["answer"]
    assert out["pending_check"] == "probe::x"

    # cognitive state unchanged across both non-learning turns
    after = json.dumps(loop.state.data.get("concept_states", {}), sort_keys=True)
    assert before == after, "non-learning turns must not move cognitive state"

    # LEARNING utterance passes the gates (route None under qwen_heads) -> real pipeline
    out = loop.turn("i don't understand the quadratic formula, can you explain")
    assert out["action"] not in {"SAFETY", "NONSENSE", "SOCIAL", "SESSION_CONTROL",
                                 "META_CAPABILITY", "OFF_DOMAIN_ACADEMIC", "EMOTIONAL"}
    assert "concept" in out and out["need"] != "none"

    if state_path.exists():
        state_path.unlink()
    print("PASS integration (gates + non-learning + LEARNING pass-through)")


if __name__ == "__main__":
    failures = 0
    for fn in (test_gates, test_validation_belt, test_interface_shapes,
               test_session_policy, test_visual_routing, test_purpose_routing,
               test_topic_shift):
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {fn.__name__}: {exc}")
    if "--integration" in sys.argv:
        integration()
    sys.exit(1 if failures else 0)
