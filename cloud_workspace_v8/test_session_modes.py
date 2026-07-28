"""Part 12 §7.1 — unit/integration tests for the mode substrate (Stage 1).

Pure tests over ModeController + the deterministic cues — no TutorLoop, no models,
no cloud. Run: python test_session_modes.py  (exit 0 = all green).

Covers: cue mapping + precedence (§5.1), explicit-request transitions (§4.1 table),
offer consume/decline semantics (bare yes/no like pending_shift), offer gating
(off by default; conditions when enabled), and set_mode plan-struct hygiene.
"""

from __future__ import annotations

import sys

from cognitive_classifier.cues import (
    is_practice_request, is_test_request, is_explain_request, is_stop_test_request,
)
from session_modes import ModeController, mode_cues, normalize_mode

_failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _failures.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


# ── cue detection + precedence (§5.1) ──────────────────────────────────────────
def test_cues():
    print("[cues]")
    for t in ["let's practice", "can we practice", "give me a problem to solve",
              "give me some sums", "more problems", "let me try a question",
              "i want to practice"]:
        check(is_practice_request(t), f"practice cue: {t!r}")
    for t in ["test me", "quiz me", "can we do a test", "give me a quiz",
              "i want a test", "test my knowledge"]:
        check(is_test_request(t), f"test cue: {t!r}")
    for t in ["explain it again", "back to learning", "just explain",
              "go back to explaining"]:
        check(is_explain_request(t), f"explain cue: {t!r}")
    for t in ["stop the test", "stop the quiz", "no more tests",
              "i don't want to be tested", "stop practicing"]:
        check(is_stop_test_request(t), f"stop cue: {t!r}")
    # precedence: "stop the test" must NOT read as a test request at the cue router
    check(mode_cues("stop the test") == "STOP", "mode_cues precedence: stop before test")
    check(mode_cues("test me please") == "TEST", "mode_cues: test")
    check(mode_cues("let's practice now") == "PRACTICE", "mode_cues: practice")
    check(mode_cues("back to learning") == "EXPLAIN", "mode_cues: explain")
    check(mode_cues("what is a polynomial?") is None, "mode_cues: plain question -> None")


# ── explicit-request transitions (§4.1) ────────────────────────────────────────
def test_resolve():
    print("[resolve_mode]")
    mc = ModeController()
    s = {}
    check(mc.current_mode(s) == "EXPLAIN", "default mode is EXPLAIN")
    m, r = mc.resolve_mode(s, "test me")
    check(m == "TEST" and r, "EXPLAIN -> TEST on 'test me'")
    m, r = mc.resolve_mode(s, "let's practice")
    check(m == "PRACTICE" and r, "TEST -> PRACTICE on 'let's practice'")
    m, r = mc.resolve_mode(s, "stop the test")
    check(m == "EXPLAIN" and r, "PRACTICE -> EXPLAIN on stop-request")
    m, r = mc.resolve_mode(s, "hello")   # no cue
    check(m == "EXPLAIN" and r is None, "no cue -> unchanged, no reason")
    m, r = mc.resolve_mode(s, "just explain")  # already EXPLAIN
    check(m == "EXPLAIN" and r is None, "same-mode request is a no-op")


def test_set_mode_hygiene():
    print("[set_mode hygiene]")
    mc = ModeController()
    s = {"mode": "PRACTICE", "practice_plan": {"x": 1}, "test_state": {"y": 2}}
    mc.set_mode(s, "TEST")
    check("practice_plan" not in s, "leaving PRACTICE drops practice_plan")
    check(s["mode"] == "TEST", "mode set to TEST")
    mc.set_mode(s, "EXPLAIN")
    check("test_state" not in s, "leaving TEST drops test_state")
    check(normalize_mode("garbage") == "EXPLAIN", "normalize_mode falls back to EXPLAIN")


# ── offer consume/decline (bare yes/no) ────────────────────────────────────────
def test_offer_consume():
    print("[consume_offer]")
    mc = ModeController(offers_enabled=True)
    # accept
    s = {"mode": "EXPLAIN", "pending_mode_offer": {"mode": "PRACTICE"}}
    res = mc.consume_offer(s, "yes")
    check(res == ("accepted", "PRACTICE"), "bare yes accepts offer -> PRACTICE")
    check("pending_mode_offer" not in s, "offer cleared after accept")
    # decline
    s = {"mode": "EXPLAIN", "pending_mode_offer": {"mode": "PRACTICE"}}
    res = mc.consume_offer(s, "no thanks")
    check(res == ("declined", "EXPLAIN"), "bare no declines, stays EXPLAIN")
    check(s["mode"] == "EXPLAIN" and "pending_mode_offer" not in s, "declined: mode unchanged, offer cleared")
    # ambiguous -> None, offer cancelled
    s = {"mode": "EXPLAIN", "pending_mode_offer": {"mode": "PRACTICE"}}
    res = mc.consume_offer(s, "what does practice mean?")
    check(res is None and "pending_mode_offer" not in s, "ambiguous reply cancels offer, returns None")
    # no offer
    check(mc.consume_offer({"mode": "EXPLAIN"}, "yes") is None, "no offer -> None")


def test_offer_emit():
    print("[maybe_offer_practice]")
    off = ModeController(offers_enabled=False)
    s = {"mode": "EXPLAIN", "current_concept": "c1", "last_action": "EXPLAIN"}
    an = {"cognitive_update": {"frustration_risk": 0.1, "cognitive_load": 0.2}}
    check(off.maybe_offer_practice(s, acknowledged=True, analysis=an,
                                   has_active_misconception=False) is None,
          "offers OFF by default -> no offer (Stage 1 regression-neutral)")

    on = ModeController(offers_enabled=True)
    s = {"mode": "EXPLAIN", "current_concept": "c1", "last_action": "EXPLAIN"}
    line = on.maybe_offer_practice(s, acknowledged=True, analysis=an,
                                   has_active_misconception=False)
    check(bool(line) and s.get("pending_mode_offer", {}).get("mode") == "PRACTICE",
          "enabled + ack + taught + calm -> offers PRACTICE")
    # blockers
    for name, kw in [
        ("no ack", dict(acknowledged=False, analysis=an, has_active_misconception=False)),
        ("active misconception", dict(acknowledged=True, analysis=an, has_active_misconception=True)),
        ("high frustration", dict(acknowledged=True, has_active_misconception=False,
                                  analysis={"cognitive_update": {"frustration_risk": 0.8}})),
    ]:
        s2 = {"mode": "EXPLAIN", "current_concept": "c1", "last_action": "EXPLAIN"}
        check(on.maybe_offer_practice(s2, **kw) is None, f"no offer when {name}")


# ── PRACTICE ladder (§4.3) ─────────────────────────────────────────────────────
def test_ladder_entry():
    print("[ladder entry level]")
    mc = ModeController()
    cases = [(0.30, 0), (0.44, 0), (0.45, 1), (0.59, 1), (0.60, 2), (0.74, 2),
             (0.75, 3), (0.90, 3)]
    for mastery, want in cases:
        s = {"current_concept": "c1"}
        item = mc.next_practice_item(s, mastery=mastery)
        check(item["level"] == want, f"mastery {mastery} -> entry level {want} (got {item['level']})")
        check(item["action"] == mc.LADDER[want][0], f"  level {want} action = {mc.LADDER[want][0]}")


def test_ladder_movement():
    print("[ladder movement]")
    mc = ModeController()
    # start mid-ladder; correct-no-hints climbs
    s = {"current_concept": "c1", "practice_plan": {"concept_id": "c1", "ladder_level": 1,
                                                    "consecutive_wrong": 0}}
    item = mc.next_practice_item(s, mastery=0.5, last_outcome="correct", last_hints=0)
    check(item["level"] == 2, "correct-no-hints -> ladder up (1->2)")
    # a 3-hint struggle drops it
    item = mc.next_practice_item(s, mastery=0.5, last_outcome="correct", last_hints=3)
    check(item["level"] == 1, "correct-with-3-hints -> ladder down (2->1)")
    # wrong drops it
    item = mc.next_practice_item(s, mastery=0.5, last_outcome="wrong", last_hints=0)
    check(item["level"] == 0, "wrong -> ladder down (1->0)")
    # second consecutive wrong at level 0 -> exit to corrective EXPLAIN
    item = mc.next_practice_item(s, mastery=0.5, last_outcome="wrong", last_hints=0)
    check(item.get("exit_to_explain") is True, "2nd consecutive wrong at L0 -> exit to EXPLAIN")
    # partial holds the level and resets the wrong streak
    s2 = {"current_concept": "c1", "practice_plan": {"concept_id": "c1", "ladder_level": 2,
                                                     "consecutive_wrong": 1}}
    item = mc.next_practice_item(s2, mastery=0.6, last_outcome="partial", last_hints=0)
    check(item["level"] == 2 and s2["practice_plan"]["consecutive_wrong"] == 0,
          "partial holds level + resets wrong streak")
    # a NEW concept resets the plan to its entry level
    s3 = {"current_concept": "c2", "practice_plan": {"concept_id": "c1", "ladder_level": 3}}
    item = mc.next_practice_item(s3, mastery=0.30)
    check(item["level"] == 0 and s3["practice_plan"]["concept_id"] == "c2",
          "concept change re-enters ladder at mastery-based level")


def test_apply_item_result():
    print("[apply_item_result]")
    from learner_state import LearnerState
    st = LearnerState(path=None, data={"concept_states": {}})
    st.update_mastery("c1", 0.5)
    r = st.apply_item_result("itemA", "correct", "c1", kind="practice", hints_used=0)
    check(r["mastery"] > 0.5, "correct practice item raises mastery")
    check(st.concept_states["c1"]["item_history"]["itemA"]["outcomes"] == ["correct"],
          "item_history records the outcome")
    # hint discount: a hinted correct gains less than a clean correct
    st.update_mastery("c2", 0.5)
    clean = st.apply_item_result("i2", "correct", "c2", kind="practice", hints_used=0)["mastery_delta"]
    st.update_mastery("c3", 0.5)
    hinted = st.apply_item_result("i3", "correct", "c3", kind="practice", hints_used=3)["mastery_delta"]
    check(hinted < clean, f"hinted gain ({hinted}) < clean gain ({clean})")
    # test items are full-weight (no discount)
    st.update_mastery("c4", 0.5)
    tst = st.apply_item_result("i4", "correct", "c4", kind="test", hints_used=3)["mastery_delta"]
    check(tst == clean, "test items carry full weight (no hint discount)")
    # mastery gate + test_history
    st.record_test_result("c1", score=0.8, n=5, gate="pass", item_results=[])
    check(st.mastery_gate("c1") == "passed", "record_test_result pass -> gate passed")
    check("c1" in st.concepts_due_for_review(exclude="cX"), "passed concept is review-due")


# ── TEST quiz set (§4.4) ───────────────────────────────────────────────────────
def test_quiz_set_build():
    print("[build_quiz_set]")
    mc = ModeController()
    s = {"mode": "EXPLAIN"}
    ts = mc.build_quiz_set(s, "c1", ["schemaA", "schemaB"], n=5)
    check(ts is not None and len(ts["schema_cycle"]) == 5, "cycles 2 schemas up to N=5")
    check(ts["schema_cycle"] == ["schemaA", "schemaB", "schemaA", "schemaB", "schemaA"],
          "interleaves/cycles in order")
    check(s["mode"] == "TEST" and s["test_state"] is ts, "build sets mode TEST + test_state")
    check(mc.build_quiz_set({}, "c1", [], n=5) is None, "no schemas -> None (degrade)")


def test_quiz_score():
    print("[score_quiz]")
    mc = ModeController()
    p = mc.score_quiz(["correct"] * 4 + ["wrong"], 5, 0.8)
    check(abs(p["score"] - 0.8) < 1e-9 and p["gate"] == "pass", "4/5 = 0.80 -> pass at 0.8 gate")
    f = mc.score_quiz(["correct"] * 3 + ["wrong", "wrong"], 5, 0.8)
    check(abs(f["score"] - 0.6) < 1e-9 and f["gate"] == "fail", "3/5 = 0.60 -> fail")
    h = mc.score_quiz(["correct", "correct", "partial", "wrong", "wrong"], 5, 0.8)
    check(abs(h["score"] - 0.5) < 1e-9, "partial counts as half a mark (2 + 0.5)/5 = 0.5")


def test_quiz_advance():
    print("[advance_test]")
    mc = ModeController()
    s = {}
    mc.build_quiz_set(s, "c1", ["A", "B"], n=3)
    step = mc.advance_test(s, last_outcome=None)   # first serve, nothing graded
    check(step["phase"] == "serving" and step["i"] == 1 and step["schema_id"] == "A",
          "first serve = item 1 (schema A)")
    step = mc.advance_test(s, last_outcome="correct")
    check(step["i"] == 2 and step["schema_id"] == "B" and s["test_state"]["results"] == ["correct"],
          "grade folds in; serve item 2 (schema B)")
    # a non-attempt does NOT consume the slot — the SAME item index is re-served
    step = mc.advance_test(s, last_outcome=None)
    check(step["i"] == 2 and s["test_state"]["results"] == ["correct"],
          "non-attempt (None) re-serves the same index, no slot consumed")
    step = mc.advance_test(s, last_outcome="wrong")   # 2nd grade
    check(step["i"] == 3, "item 3 after 2 graded of n=3")
    step = mc.advance_test(s, last_outcome="correct")  # 3rd grade -> summary
    check(step["phase"] == "summary" and step["n"] == 3, "all N graded -> summary")
    check(step["gate"] == "fail" and step["correct"] == 2, "2/3 correct -> fail gate")
    check(s["test_state"]["phase"] == "done", "test_state marked done")


# ── active-test protection (production review fix 3) ──────────────────────────
def test_mode_blocked_during_test():
    print("[test protection]")
    mc = ModeController()
    s = {}
    mc.build_quiz_set(s, "c1", ["A", "B"], n=5)
    check(s["mode"] == "TEST", "quiz set arms TEST mode")
    m, r = mc.resolve_mode(s, "let's practice")
    check(m == "TEST" and "blocked" in (r or ""), "spoken practice request blocked mid-test")
    check(s.get("test_state") is not None, "test_state survives the blocked switch")
    m, r = mc.resolve_mode(s, "back to learning")
    check(m == "TEST" and "blocked" in (r or ""), "explain request blocked mid-test")
    m, r = mc.resolve_mode(s, "stop the test")
    check(m == "EXPLAIN" and "test_state" not in s, "explicit stop still abandons the test")
    # a DONE test no longer blocks
    s2 = {"mode": "TEST", "test_state": {"phase": "done"}}
    m, r = mc.resolve_mode(s2, "let's practice")
    check(m == "PRACTICE", "finished test does not block mode changes")


# ── frozen-test resume (production review fix 4) ───────────────────────────────
def test_frozen_test_resume():
    print("[frozen test resume]")
    mc = ModeController()
    s = {"mode": "TEST", "test_state": {
        "concept_id": "c1", "n": 5, "idx": 2,
        "schema_cycle": ["A", "B", "A", "B", "A"],
        "items": [{"id": "q1"}, {"id": "q2"}, {"id": "q3"}],
        "results": ["correct", "wrong"], "phase": "serving"}}
    offer = mc.check_frozen_test(s)
    check(offer is not None and offer["graded"] == 2 and offer["n"] == 5,
          "frozen test detected (2/5 graded)")
    check(mc.check_frozen_test(s) is None, "already-offered -> no duplicate offer")
    res = mc.consume_test_resume(s, "yes")
    check(res == ("resume", "TEST"), "bare yes resumes")
    check(s.get("test_state") is not None and s["mode"] == "TEST",
          "resume keeps test_state + TEST mode")
    check("pending_test_resume" not in s, "offer is one-shot")
    # no frozen test -> no offer
    check(mc.check_frozen_test({"mode": "EXPLAIN"}) is None, "no test_state -> no offer")
    check(mc.check_frozen_test({"test_state": {"phase": "done"}}) is None,
          "done test -> no offer")


def test_frozen_test_abandon():
    print("[frozen test abandon]")
    mc = ModeController()
    base = {"mode": "TEST", "test_state": {
        "concept_id": "c1", "n": 5, "idx": 2, "schema_cycle": ["A"] * 5,
        "items": [], "results": ["correct", "wrong"], "phase": "serving"}}
    s = dict(base, test_state=dict(base["test_state"]),
             pending_test_resume={"concept_id": "c1", "graded": 2, "n": 5})
    res = mc.consume_test_resume(s, "no")
    check(res == ("abandon", "EXPLAIN"), "bare no abandons -> EXPLAIN")
    check("test_state" not in s and s["mode"] == "EXPLAIN",
          "abandon drops test_state + leaves TEST mode")
    # ambiguous reply cancels the offer AND drops the set (else the stale TEST
    # mode would rebuild a quiz on the next unrelated question)
    s = dict(base, test_state=dict(base["test_state"]),
             pending_test_resume={"concept_id": "c1", "graded": 2, "n": 5})
    res = mc.consume_test_resume(s, "what is a polynomial?")
    check(res is None and "test_state" not in s and s["mode"] == "EXPLAIN",
          "ambiguous reply cancels offer, drops set, back to EXPLAIN")
    check(mc.consume_test_resume({"mode": "EXPLAIN"}, "yes") is None, "no offer -> None")


# ── atomic learner-state save + recovery (production review fix 1) ─────────────
def test_atomic_save():
    print("[atomic save]")
    import tempfile
    from pathlib import Path
    from learner_state import LearnerState, load_learner_state
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "state.json"
        st = LearnerState(path=p, data={"concept_states": {}, "global": {}})
        st.update_mastery("c1", 0.5)
        st.save()
        check(p.exists(), "save() writes the primary file")
        check(not p.with_suffix(".tmp").exists(), "tmp file cleaned up (renamed)")
        st.update_mastery("c1", 0.7)
        st.save()
        check(p.with_suffix(".bak").exists(), "second save keeps a .bak generation")
        bak = load_learner_state(p.with_suffix(".bak"))
        check(abs(bak.mastery("c1") - 0.5) < 0.01, "backup holds the prior state")
        cur = load_learner_state(p)
        check(abs(cur.mastery("c1") - 0.7) < 0.01, "primary holds the latest state")


def test_corrupt_recovery():
    print("[corrupt recovery]")
    import tempfile
    from pathlib import Path
    from learner_state import load_learner_state
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "state.json"
        p.with_suffix(".bak").write_text(
            '{"concept_states": {"c1": {"mastery": 0.6}}, "global": {}}', encoding="utf-8")
        p.write_text('{"truncat', encoding="utf-8")
        st = load_learner_state(p)
        check(abs(st.mastery("c1") - 0.6) < 0.01, "corrupt primary -> recovered from .bak")
        check(p.with_suffix(".corrupt").exists(), "corrupt file preserved for post-mortem")
        st.save()
        check(abs(load_learner_state(p).mastery("c1") - 0.6) < 0.01,
              "save() after recovery writes a valid primary")
        # no primary, no backup -> cold start
        p2 = Path(d) / "fresh.json"
        st2 = load_learner_state(p2)
        check(st2.mastery("cX") == 0.30, "nothing on disk -> cold start")


def main() -> int:
    for fn in (test_cues, test_resolve, test_set_mode_hygiene,
               test_offer_consume, test_offer_emit,
               test_ladder_entry, test_ladder_movement, test_apply_item_result,
               test_quiz_set_build, test_quiz_score, test_quiz_advance,
               test_mode_blocked_during_test, test_frozen_test_resume,
               test_frozen_test_abandon, test_atomic_save, test_corrupt_recovery):
        fn()
    print()
    if _failures:
        print(f"FAILED: {len(_failures)} check(s)")
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
