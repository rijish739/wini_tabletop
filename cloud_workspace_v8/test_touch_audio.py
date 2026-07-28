import time
import pytest
import numpy as np
from unittest.mock import MagicMock, patch

from wini_platform.touch_gestures import TouchGestureRecognizer
from wini_client.sound_bank import SoundBank, _adsr, _sine
from wini_client.audio_manager import AudioManager
from wini_platform.emotion_engine import EmotionEngine, State

# ── 1. SoundBank Tests ────────────────────────────────────────────────────────

def test_adsr_envelope():
    # Length 100, ADSR parameters in seconds
    rate = 1000
    n = 100
    # a=10ms (10 samples), d=10ms (10 samples), s=0.5, r=10ms (10 samples)
    env = _adsr(n, 0.01, 0.01, 0.5, 0.01, rate=rate)
    assert len(env) == n
    assert env[0] == 0.0
    assert np.all(env >= 0.0)
    assert np.all(env <= 1.0)

def test_sine_generation():
    rate = 1000
    dur = 0.5
    s = _sine(10, dur, rate=rate)
    assert len(s) == int(rate * dur)

def test_sound_bank_retrieval():
    bank = SoundBank(rate=16000, base_amplitude=0.15)
    assert "curious" in bank.families
    pcm, rate = bank.get_sound("curious", mood=50)
    assert len(pcm) > 0
    assert rate == 16000

    # Test repetition avoidance (multiple retrievals should shift weights)
    # We retrieve curious 10 times and verify it doesn't break
    for _ in range(10):
        pcm, _ = bank.get_sound("curious", mood=80)
        assert len(pcm) > 0

# ── 2. AudioManager Tests ──────────────────────────────────────────────────────

def test_audio_manager_tts_exclusivity():
    play_fn = MagicMock()
    bank = SoundBank(rate=16000)
    am = AudioManager(play_fn=play_fn, sound_bank=bank)

    # When speaking is active, play_emotion should return False (suppressed)
    am.set_speaking(True)
    assert am.is_speaking() is True
    res = am.play_emotion("curious")
    assert res is False
    play_fn.assert_not_called()

    # When speaking finishes, it should allow playing
    am.set_speaking(False)
    assert am.is_speaking() is False
    res = am.play_emotion("curious")
    assert res is True
    # Playback is dispatched to a worker thread — wait briefly for it to land.
    deadline = time.time() + 1.0
    while not play_fn.called and time.time() < deadline:
        time.sleep(0.01)
    play_fn.assert_called_once()

def test_audio_manager_cooldowns():
    play_fn = MagicMock()
    bank = SoundBank(rate=16000)
    am = AudioManager(play_fn=play_fn, sound_bank=bank)

    # First play should succeed
    assert am.play_emotion("curious") is True
    # Immediate second play should fail (cooldown < 800ms)
    assert am.play_emotion("curious") is False

# ── 3. TouchGestureRecognizer Tests ───────────────────────────────────────────

def test_gesture_single_tap():
    taps = []
    def on_single_tap():
        taps.append("single")

    rec = TouchGestureRecognizer(on_single_tap=on_single_tap)

    # Down, then Up within 100ms (is a tap)
    rec.on_level(True)
    time.sleep(0.05)
    rec.on_level(False)

    # Wait for double tap window to expire (400ms)
    time.sleep(0.5)
    assert "single" in taps

def test_gesture_double_tap():
    double_taps = []
    def on_double_tap():
        double_taps.append("double")

    rec = TouchGestureRecognizer(on_double_tap=on_double_tap)

    # First tap
    rec.on_level(True)
    time.sleep(0.05)
    rec.on_level(False)

    # Gap of 100ms
    time.sleep(0.1)

    # Second tap
    rec.on_level(True)
    time.sleep(0.05)
    rec.on_level(False)

    time.sleep(0.1)
    assert "double" in double_taps

def test_gesture_hold():
    holds = []
    releases = []
    rec = TouchGestureRecognizer(
        on_hold_start=lambda: holds.append("start"),
        on_hold_end=lambda dur: releases.append(dur)
    )

    # Hold down for 800ms (threshold is 700ms)
    rec.on_level(True)
    time.sleep(0.4)
    rec.on_level(True) # Keep feeding level
    time.sleep(0.4)
    rec.on_level(True)
    
    assert "start" in holds
    
    # Release
    rec.on_level(False)
    assert len(releases) == 1
    assert releases[0] >= 0.7

# ── 4. EmotionEngine Tests ─────────────────────────────────────────────────────

def test_emotion_engine_transitions():
    am = MagicMock()
    am.play_emotion.return_value = True
    
    current_time = [100.0]
    def mock_monotonic():
        return current_time[0]
        
    with patch("time.monotonic", side_effect=mock_monotonic):
        engine = EmotionEngine(audio_manager=am)
        assert engine.state == State.IDLE
        assert engine.mood == 50.0

        # Tap once -> Curious
        engine.on_single_tap()
        assert engine.state == State.CURIOUS
        assert engine.mood == 52.0
        am.play_emotion.assert_called_with("curious")

        # Double tap -> Happy
        engine.on_double_tap()
        assert engine.state == State.HAPPY
        assert engine.mood == 57.0
        am.play_emotion.assert_called_with("happy")

        # Repeated patting (3 times) -> Excited
        engine.on_pat_sequence(3)
        assert engine.state == State.EXCITED
        assert engine.mood == 60.0
        am.play_emotion.assert_called_with("happy")

        # Tick decay excited -> happy in 30s
        current_time[0] += 31.0
        engine.tick(31.0)
        assert engine.state == State.HAPPY

        # Tick decay happy -> content in 60s
        current_time[0] += 61.0
        engine.tick(61.0)
        assert engine.state == State.CONTENT

def test_overstimulation():
    am = MagicMock()
    engine = EmotionEngine(audio_manager=am)

    # Send 9 touches rapidly
    for _ in range(9):
        engine.on_single_tap()

    assert engine.state == State.OVERSTIMULATED
    am.play_emotion.assert_any_call("overstimulated")
