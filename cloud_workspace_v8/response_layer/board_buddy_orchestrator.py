"""LLM-orchestrated segment loop for a Board Buddy visual teaching turn (§0a, §10.2).

The resolved control model: **the LLM (brain) is the master clock, not the audio.** A visual
teaching turn is a budget-bounded loop of *segments*. Each segment the LLM independently
emits a Board Buddy ``board_call`` (draw), a ``speech`` utterance, both, or neither; the
device executes and acks completion; the LLM drives the next segment or ends. Board Buddy is
a **pure executor** of the payload the brain hands it.

This module is the brain-side driver. It is deliberately transport-agnostic and dependency-
free so it runs headless in tests (BOARD_BUDDY_INTEGRATION_PLAN.md Phase 2 exit: "a stub
device ack lets this be tested without hardware"):

  * ``decide(state) -> segment``   — the LLM segment decision. The default is a Vertex-backed
    decider (:func:`vertex_segment_decider`); tests inject a scripted list.
  * ``emit(verb) -> None``          — send one wire verb to the device (``board_open`` /
    ``board`` / ``speak`` / ``board_close``). wini_server wires these to the mode channel.
  * ``wait_ack(expect) -> ack``    — block until the device reports the segment complete
    (``{"speech":True,"animation":True}``) or an interrupt (``{"interrupt":True}``). The
    default returns "done immediately"; the live server blocks on the device round-trip.

Invariants preserved (§6.3, §6.4):
  * **Grounding still holds.** The same LLM speaks and draws in a segment, so the picture
    matches the words by construction — but every ``board_call`` is still run through the
    deterministic belt (:func:`board_buddy_author.validate_board_call`), grounded against the
    accumulated spoken text, so a hallucinated count/coefficient never reaches the wire.
  * **Board Buddy is opened once, closed once**, around the whole visual turn; the parent
    (LVGL) owns that lifecycle via the verbs this loop emits.
  * **Budget-bounded** (§8 Q3): a small cap on segments and board calls per turn guards
    latency/cost; the default is conservative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from . import board_buddy_caps as caps
from .board_buddy_author import payload_has_animation, tmax_hint, validate_board_call

# Back-compat alias (the hint helper now lives in board_buddy_author with the other payload
# helpers); kept so existing references and tests importing it from here still resolve.
_tmax_hint = tmax_hint

DEFAULT_MAX_SEGMENTS = 6         # hard stop on LLM turns per teaching turn
DEFAULT_BOARD_BUDGET = 4         # §8 Q3 recommendation: <= 4 board calls / turn

# Segment = the LLM's per-step decision.
#   {"board_call": {"elements":[...]} | [...] | None,
#    "speech": str | None,
#    "done": bool}
Segment = dict[str, Any]


@dataclass
class SegmentResult:
    """What one executed segment did (for telemetry + tests)."""
    index: int
    spoke: str | None = None
    board_payload: list[dict] | None = None
    board_tmax: float = 0.0
    dropped: list[str] = field(default_factory=list)
    ack: dict = field(default_factory=dict)


@dataclass
class TurnResult:
    """The whole orchestrated turn's trace."""
    verbs: list[dict] = field(default_factory=list)       # every wire verb emitted, in order
    segments: list[SegmentResult] = field(default_factory=list)
    spoken_text: str = ""                                  # concatenated speech
    board_opened: bool = False
    interrupted: bool = False
    stop_reason: str = ""                                  # done | budget | empty | error

    def to_dict(self) -> dict:
        return {
            "verbs": self.verbs,
            "spoken_text": self.spoken_text,
            "board_opened": self.board_opened,
            "interrupted": self.interrupted,
            "stop_reason": self.stop_reason,
            "n_segments": len(self.segments),
            "n_board_calls": sum(1 for s in self.segments if s.board_payload),
            "dropped": [d for s in self.segments for d in s.dropped],
        }


class BoardSegmentOrchestrator:
    """Drive one visual teaching turn as an LLM-orchestrated segment loop.

    Only used on **earned-visual turns** (§6.3 Q4): plain Q&A keeps the Part-13 single-call
    streamed path untouched. Construct with the teaching ``brief`` (goal + grounding material)
    and the injected ``decide`` / ``emit`` / ``wait_ack`` seams, then call :meth:`run`.
    """

    def __init__(self, brief: str, *, profile: dict | None = None,
                 decide: Callable[[dict], Segment] | None = None,
                 emit: Callable[[dict], None] | None = None,
                 wait_ack: Callable[[dict], dict] | None = None,
                 max_segments: int = DEFAULT_MAX_SEGMENTS,
                 board_budget: int = DEFAULT_BOARD_BUDGET):
        self.brief = brief
        self.profile = profile or {}
        self._decide = decide or vertex_segment_decider(brief, profile)
        self._emit_cb = emit
        self._wait_ack = wait_ack or (lambda expect: {"speech": True, "animation": True})
        self.max_segments = max(1, int(max_segments))
        self.board_budget = max(0, int(board_budget))
        self.result = TurnResult()

    def _emit(self, verb: dict) -> None:
        self.result.verbs.append(verb)
        if self._emit_cb is not None:
            self._emit_cb(verb)

    def _decider_state(self) -> dict:
        """The read-only state handed to the LLM before each segment decision."""
        return {
            "brief": self.brief,
            "spoken_so_far": self.result.spoken_text,
            "segments_done": len(self.result.segments),
            "segments_left": self.max_segments - len(self.result.segments),
            "board_calls_left": self.board_budget
                                - sum(1 for s in self.result.segments if s.board_payload),
            "board_open": self.result.board_opened,
        }

    def run(self) -> TurnResult:
        """Execute the loop to completion (done / budget / interrupt) and return the trace."""
        try:
            self._loop()
        except Exception as e:  # noqa: BLE001 — orchestration never crashes the turn
            self.result.stop_reason = f"error:{type(e).__name__}"
        finally:
            if self.result.board_opened:
                self._emit({"cmd": "board_close"})
        return self.result

    def _loop(self) -> None:
        while len(self.result.segments) < self.max_segments:
            seg = self._decide(self._decider_state()) or {}
            speech = (seg.get("speech") or "").strip() or None
            board_call = seg.get("board_call")
            board_calls_used = sum(1 for s in self.result.segments if s.board_payload)

            if seg.get("done") or (not speech and not board_call):
                self.result.stop_reason = "done" if seg.get("done") else "empty"
                return

            sr = SegmentResult(index=len(self.result.segments))

            # 1) draw — belt-grounded against everything spoken so far PLUS this segment's
            #    speech (the words the picture must match), then emitted.
            if board_call and board_calls_used < self.board_budget:
                ground_text = f"{self.result.spoken_text} {speech or ''}"
                kept, dropped = validate_board_call(board_call, ground_text,
                                                    profile=self.profile)
                sr.dropped = dropped
                if kept:
                    if not self.result.board_opened:
                        self._emit({"cmd": "board_open"})
                        self.result.board_opened = True
                    tmax = _tmax_hint(kept)
                    sr.board_payload = kept
                    sr.board_tmax = tmax
                    self._emit({"cmd": "board", "payload": kept, "tmax": tmax,
                                "animated": payload_has_animation(kept)})

            # 2) speak — a verb the caller maps to Cloud TTS; speech stays dynamic-length
            #    (never clamped to the board's T_max, memory answer-length-stays-dynamic).
            if speech:
                sr.spoke = speech
                self.result.spoken_text = f"{self.result.spoken_text} {speech}".strip()
                self._emit({"cmd": "speak", "text": speech})

            # 3) wait for the device to finish BOTH modalities this segment used, so the
            #    next LLM decision sees a completed segment (§10.2 completion round-trip).
            expect = {"speech": bool(speech), "animation": bool(sr.board_payload)}
            ack = self._wait_ack(expect) or {}
            sr.ack = ack
            self.result.segments.append(sr)
            if ack.get("interrupt"):
                self.result.interrupted = True
                self.result.stop_reason = "interrupt"
                return

        self.result.stop_reason = "budget"


# ---------------------------------------------------------------------------
# The real LLM decider (Vertex) — one structured call per segment
# ---------------------------------------------------------------------------
def _segment_schema():
    from google.genai import types
    from .board_buddy_author import _board_element_schema
    S, T = types.Schema, types.Type
    return S(
        type=T.OBJECT,
        properties={
            "speech": S(type=T.STRING),
            "board_call": _board_element_schema(),
            "done": S(type=T.BOOLEAN),
        },
    )


def _segment_prompt(brief: str, state: dict, profile: dict | None) -> str:
    tools = caps.allowed_tools_for_profile(profile)
    stickers = caps.allowed_stickers_for_profile(profile)
    return (
        "You are Wini, a warm maths tutor teaching ONE idea to a child, using a shared "
        "drawing board (Board Buddy). You decide the next teaching SEGMENT: what to SAY and "
        "what to DRAW right now. You may speak, draw, both, or (when finished) set done.\n\n"
        "TEACHING BRIEF (what this turn is about — stay grounded in it):\n"
        f"{brief}\n\n"
        "DRAWING TOOLS (Board Buddy — use ONLY these, with ONLY these params):\n"
        + caps.tool_help_block(tools) + "\n"
        f"Sticker names: {', '.join(stickers)}.\n"
        "Pick the tool that FITS the idea:\n" + caps.routing_lines() + "\n\n"
        "RULES:\n"
        "- The board must match your words: put NO number/count/hop/fraction on the board "
        "that your speech (now or earlier) did not say. Ungrounded values are dropped.\n"
        "- One clear step per segment. Keep speech natural and child-friendly; it is NOT "
        "clamped to the animation length.\n"
        "- Reuse the open board across segments; don't re-draw what's already shown.\n"
        f"- You have {state.get('segments_left')} segment(s) and "
        f"{state.get('board_calls_left')} board draw(s) left. When the idea is taught, set "
        "done=true (no more speech/board).\n\n"
        f"SPOKEN SO FAR:\n{state.get('spoken_so_far') or '(nothing yet)'}\n\n"
        "Return the next segment."
    )


def vertex_segment_decider(brief: str, profile: dict | None = None
                           ) -> Callable[[dict], Segment]:
    """Build the real segment decider: one structured Vertex Gemini call per segment.

    Returns a closure ``decide(state) -> segment``. A failed/empty call yields ``{done:True}``
    so the loop ends cleanly rather than hanging (the caller degrades to the crop/text path)."""
    def decide(state: dict) -> Segment:
        try:
            from llm_vertex import generate_json
            res = generate_json(_segment_prompt(brief, state, profile),
                                response_schema=_segment_schema(),
                                temperature=0.3, max_output_tokens=800)
        except Exception:  # noqa: BLE001 — a decision failure ends the turn, never crashes it
            return {"done": True}
        if not res.ok or not isinstance(res.data, dict):
            return {"done": True}
        return res.data
    return decide
