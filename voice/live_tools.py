"""Local tutor-turn handler exposed to the Gemini Live API as a function tool.

The Live model is forbidden from teaching. On every student turn it calls
``get_tutor_turn(transcript)``; this module runs the EXISTING local pedagogy
(pacing triage -> TutorLoop -> Qwen, with the short-answer budget) and returns
the exact text for the model to speak verbatim.

Nothing here is cloud: the brain is local. Only the returned text crosses back
to the Live session (same boundary the old TTS path already had).
"""

from __future__ import annotations

from typing import Any

from google.genai import types

from pacing import PacingController
from .audio_io import now_ms
from .sanitize import sanitize_for_speech


# The single tool the Live model may call. Keep the description blunt so the
# model routes every turn here instead of answering on its own.
TUTOR_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="get_tutor_turn",
            description=(
                "Get the tutor's exact spoken reply for what the student just "
                "said. You MUST call this for every student turn and never answer "
                "on your own. Speak back the returned `say` text word for word."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "transcript": types.Schema(
                        type=types.Type.STRING,
                        description="The student's words, exactly as spoken.",
                    ),
                },
                required=["transcript"],
            ),
        )
    ]
)


class TutorTurnHandler:
    """Wraps a (already-constructed, already-warm) TutorLoop + PacingController.

    `handle()` is blocking (Qwen generation); the Live session runs it in an
    executor so audio streaming is never stalled.
    """

    def __init__(self, loop) -> None:
        self.loop = loop
        self.pacing = PacingController()

    def analyze(self, transcript: str, stt_uncertain: bool = False):
        """Fast cognitive triage (MiniLM, ~50 ms). Returns a PacingDecision so the
        caller can pick a state-appropriate filler BEFORE the slow generation."""
        return self.pacing.before_turn((transcript or "").strip(), self.loop, stt_uncertain=stt_uncertain)

    def respond(self, transcript: str, decision) -> dict[str, Any]:
        """Generate the answer for an already-analyzed turn and apply state."""
        transcript = (transcript or "").strip()
        lat: dict[str, int] = {}
        result: dict[str, Any] | None = None
        answer = decision.direct_answer
        if decision.direct_answer is None:
            t0 = now_ms()
            try:
                result = self.loop.turn(
                    transcript,
                    answer_budget=decision.answer_budget.as_dict(),
                    precomputed_analysis=decision.analysis,
                )
                answer = result.get("answer")
            except Exception as exc:  # noqa: BLE001
                answer = "Let us try that step once more."
                result = {"error": str(exc), "answer": answer, "action": "ERROR"}
            lat["qwen_ms"] = now_ms() - t0
        else:
            lat["qwen_ms"] = 0

        self.pacing.after_turn(transcript, answer, result, self.loop, decision, latency=lat)
        return {
            "say": sanitize_for_speech(answer or ""),
            "raw_answer": answer or "",
            "action": (result or {}).get("action"),
            "triage": decision.triage.as_dict(),
            "budget": decision.answer_budget.as_dict(),
            "latency_ms": lat,
            # which LLM (qwen|gemini) generated the answer; None for scripted/canned
            "gen_backend": (result or {}).get("gen_backend"),
            "answer_source": (result or {}).get("answer_source"),
            # the student ended the session (SESSION_CONTROL hard stop): the runner
            # speaks this farewell and then stops taking turns
            "session_ended": bool((result or {}).get("session_ended")),
        }

    def handle(self, transcript: str, stt_uncertain: bool = False) -> dict[str, Any]:
        decision = self.analyze(transcript, stt_uncertain=stt_uncertain)
        return self.respond(transcript, decision)
