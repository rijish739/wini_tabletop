"""Cognitive-state fillers — the short thing Wini says while the brain generates.

Instead of always saying "Let me see", the filler is chosen from the MiniLM
cognitive analysis of the student's turn (confusion / curiosity / frustration /
hint request / topic shift / acknowledgement), and a different phrase is picked
each time within that bucket. All phrases are pre-synthesised once with Cloud TTS
so playback is instant.
"""

from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor

from .cloud_tts import CloudTts

FILLERS: dict[str, list[str]] = {
    "hint": ["Sure, here's a small hint.", "Okay, let me give you a clue.",
             "Alright, here's a little nudge.", "Let me point you in the right direction."],
    "curious": ["Ooh, good question!", "Nice, let's explore that.",
                "I like where you're going.", "Great curiosity, let's dig in."],
    "frustrated": ["No worries, let's take it slowly.", "That's okay, we'll get it together.",
                   "Don't worry, let's try once more.", "It's alright, let's break it down."],
    "confused": ["Okay, let me explain.", "Let's clear that up.",
                 "Alright, let's untangle this.", "Good, let's look again."],
    "shift": ["Sure, let's switch.", "Okay, new topic.",
              "Alright, let's go there.", "Happy to change track."],
    "ack": ["Great!", "Awesome.", "Well done!", "Nice work.", "Lovely."],
    "default": ["Let me think.", "Okay.", "Right.", "Let's see.",
                "Hmm, one moment.", "Good, let's see."],
}


def pick_bucket(decision) -> str:
    """Map a PacingDecision (triage + MiniLM cognitive_update) to a filler bucket."""
    tri = decision.triage.as_dict().get("primary_intent")
    cu = (decision.analysis or {}).get("cognitive_update", {})
    if tri == "hint_request":
        return "hint"
    if tri == "topic_shift":
        return "shift"
    if tri == "ack":
        return "ack"
    if float(cu.get("frustration_risk", 0)) >= 0.6:
        return "frustrated"
    if float(cu.get("curiosity", 0)) >= 0.6 and float(cu.get("confusion", 0)) < 0.4:
        return "curious"
    if float(cu.get("confusion", 0)) >= 0.4:
        return "confused"
    return "default"


class FillerBank:
    def __init__(self, tts: CloudTts) -> None:
        self.tts = tts
        self.cache: dict[str, bytes] = {}
        self._last: dict[str, str] = {}   # last phrase used per bucket (avoid repeats)

    def presynth(self) -> None:
        phrases = [p for v in FILLERS.values() for p in v]
        with ThreadPoolExecutor(max_workers=8) as ex:
            for phrase, pcm in zip(phrases, ex.map(self.tts.synth, phrases)):
                self.cache[phrase] = pcm

    def pick(self, decision) -> tuple[str, bytes]:
        bucket = pick_bucket(decision)
        opts = FILLERS[bucket]
        last = self._last.get(bucket)
        choices = [p for p in opts if p != last] or opts
        phrase = random.choice(choices)
        self._last[bucket] = phrase
        pcm = self.cache.get(phrase) or self.tts.synth(phrase)  # lazy fallback
        return phrase, pcm
