"""Phase 4 runner and Phase 5 outcome tests."""
from __future__ import annotations

from learner_state import load_learner_state
from .device_runner import DeviceScriptRunner
from .outcomes import OutcomeEmitter, apply_at_turn_close


def _bundle(kind: str = "touch_prompt") -> dict:
    return {
        "bundle_id": "bundle1", "script_id": "script1", "turn_id": "turn1",
        "entry_beat_id": "b0",
        "device_profile": {"touch_present": True, "max_beats_per_package": 0},
        "beats": [
            {"beat_id": "b0", "speech": {"text": "First."}, "visual": None,
             "lvgl_text": None, "robot": [], "resumable": True,
             "interaction": {"kind": kind, "hook_id": "h1", "hook_type": "micro_check",
                             "target_concept": "c1", "target_misconception": None,
                             "state_update_intent": None, "evidence_refs": []},
             "on_complete": "b1", "on_correct": "b1",
             "on_incorrect": "b1", "on_nonresponse": "b1"},
            {"beat_id": "b1", "speech": {"text": "Second."}, "visual": None,
             "lvgl_text": None, "robot": [], "resumable": True,
             "interaction": None, "on_complete": None,
             "on_correct": None, "on_incorrect": None, "on_nonresponse": None},
        ],
    }


def test_touch_checkpoint_advances_only_after_speech() -> None:
    runner = DeviceScriptRunner()
    runner.arm(_bundle())
    start = runner.start()
    assert start[-1]["cmd"] == "start_speech"
    wait = runner.speech_completed()
    assert runner.state == "waiting_touch"
    assert wait[0]["cmd"] == "await_touch"
    prepare = runner.touch_response("correct", {"tap": [20, 40]})
    assert runner.state == "armed"
    assert prepare == []
    assert runner.current_id == "b1"
    runner.start()
    done = runner.speech_completed()
    assert runner.state == "completed"
    assert done[0]["cmd"] == "complete_script"


def test_spoken_checkpoint_and_barge_in_contract() -> None:
    runner = DeviceScriptRunner()
    runner.arm(_bundle("spoken_checkpoint"))
    runner.start()
    suspend = runner.speech_completed()
    assert runner.state == "waiting_spoken_checkpoint"
    assert suspend[0]["cmd"] == "suspend_for_spoken_checkpoint"
    runner.spoken_checkpoint_resolved("incorrect", {"text": "I do not know"})
    assert runner.current_id == "b1"

    runner = DeviceScriptRunner()
    runner.arm(_bundle())
    runner.start()
    commands = runner.interrupt("audio://clip")
    assert runner.state == "interrupted"
    assert commands[0]["cmd"] == "duck_or_pause_speech"
    assert runner.resume_decision("resume")[0]["cmd"] == "resume_speech"


def test_outcomes_are_idempotent_and_single_writer_applied() -> None:
    runner = DeviceScriptRunner()
    runner.arm(_bundle())
    runner.start()
    runner.speech_completed()
    runner.touch_response("correct")
    scored = next(event for event in runner.events if event["event"] == "assessment_scored")

    emitter = OutcomeEmitter()
    first = emitter.record(scored)
    assert first is not None
    assert emitter.record(scored) is None
    state = load_learner_state(None)
    before = state.mastery("c1")
    applied, keys = apply_at_turn_close(state, emitter.drain())
    assert len(applied) == 1
    assert state.mastery("c1") > before
    replay, _ = apply_at_turn_close(state, [first], keys)
    assert replay == []


def _run() -> int:
    tests = [test_touch_checkpoint_advances_only_after_speech,
             test_spoken_checkpoint_and_barge_in_contract,
             test_outcomes_are_idempotent_and_single_writer_applied]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed} passed, {failed} failed ({len(tests)} total)")
    return 1 if failed else 0

if __name__ == "__main__":
    raise SystemExit(_run())

