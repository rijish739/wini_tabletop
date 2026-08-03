"""Phase 4 deterministic Device Script Runner.

The runner executes compiled beats as a small state machine. It owns delivery state,
but never grades content or mutates learner state. Callers perform actual rendering,
audio, touch, and robot operations from returned commands, then acknowledge them.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable

TERMINAL = frozenset(("completed", "failed", "cancelled"))
WAITING = frozenset(("waiting_touch", "waiting_spoken_checkpoint", "interrupted"))


@dataclass
class RunnerEvent:
    name: str
    script_id: str
    beat_id: str | None
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"event": self.name, "script_id": self.script_id,
                "beat_id": self.beat_id, **self.payload}


class DeviceScriptRunner:
    """Beat-synchronised executor for a compiled response bundle.

    The minimum coherent unit is one fully packaged beat. A runner never starts a beat
    until its local record exists; later beats cannot be revealed before the current
    one completes, branches, suspends, or fails safely.
    """
    def __init__(self, emit: Callable[[dict], None] | None = None):
        self._emit_cb = emit
        self.events: list[dict] = []
        self.bundle: dict | None = None
        self.by_id: dict[str, dict] = {}
        self.state = "idle"
        self.current_id: str | None = None
        self.acknowledged: set[str] = set()
        self._interrupted_from: str | None = None
        # Board Buddy lifecycle (§10.3): LVGL (the parent) opens the child once and closes
        # it once, around the beat(s) that use it. The runner emits board_open/board on
        # prepare and board_close when leaving Board Buddy (next beat has no board / script
        # ends / interrupt-end), never letting a later beat reveal before the child closes.
        self._board_open = False

    def _event(self, name: str, beat_id: str | None = None, **payload) -> dict:
        assert self.bundle is not None
        event = RunnerEvent(name, self.bundle["script_id"], beat_id, payload).to_dict()
        self.events.append(event)
        if self._emit_cb is not None:
            self._emit_cb(event)
        return event

    def arm(self, bundle: dict) -> list[dict]:
        """Validate a complete first coherent unit and prepare it for execution."""
        beats = list(bundle.get("beats") or [])
        ids = [str(beat.get("beat_id") or "") for beat in beats]
        if not bundle.get("script_id") or not beats or "" in ids or len(set(ids)) != len(ids):
            raise ValueError("invalid response bundle")
        entry = bundle.get("entry_beat_id") or ids[0]
        if entry not in ids:
            raise ValueError("bundle entry beat is missing")
        profile = bundle.get("device_profile") or {}
        limit = int(profile.get("max_beats_per_package") or 0)
        if limit and len(beats) > limit:
            # A transport package may be small, but it must contain a complete beat.
            raise ValueError("bundle exceeds device beat limit; split before arming")

        self.bundle = bundle
        self.by_id = {beat["beat_id"]: beat for beat in beats}
        self.current_id = entry
        self.state = "armed"
        self.acknowledged.clear()
        self._event("script_validated", entry, bundle_id=bundle.get("bundle_id"))
        return self._prepare_current()

    @staticmethod
    def _board_visual(beat: dict) -> dict | None:
        v = beat.get("visual")
        return v if isinstance(v, dict) and v.get("kind") == "board_buddy_payload" else None

    def _prepare_current(self) -> list[dict]:
        assert self.current_id is not None
        beat = self.by_id[self.current_id]
        commands: list[dict] = []
        board = self._board_visual(beat)
        if board is not None:
            # Parent lifecycle verbs: open the child once, then hand it the payload.
            if not self._board_open:
                commands.append({"cmd": "board_open", "beat_id": self.current_id})
                self._board_open = True
            commands.append({"cmd": "board", "beat_id": self.current_id,
                             "payload": board.get("payload") or [],
                             "tmax": board.get("tmax", 0.0),
                             "animated": bool(board.get("animated"))})
        elif beat.get("visual") is not None:
            commands.append({"cmd": "prepare_visual", "beat_id": self.current_id,
                             "visual": beat["visual"]})
        if beat.get("lvgl_text") is not None:
            commands.append({"cmd": "prepare_text", "beat_id": self.current_id,
                             "text": beat["lvgl_text"]})
        if beat.get("robot"):
            commands.append({"cmd": "prepare_robot", "beat_id": self.current_id,
                             "primitives": beat["robot"]})
        self._event("beat_armed", self.current_id, commands=len(commands))
        return commands

    def start(self) -> list[dict]:
        if self.state != "armed" or self.current_id is None:
            raise RuntimeError("runner is not armed")
        self.state = "running"
        beat = self.by_id[self.current_id]
        self._event("beat_started", self.current_id)
        commands = [{"cmd": "show_prepared", "beat_id": self.current_id}]
        speech = beat.get("speech")
        if speech and speech.get("text"):
            commands.append({"cmd": "start_speech", "beat_id": self.current_id,
                             "speech": speech})
        else:
            commands.append({"cmd": "speech_complete", "beat_id": self.current_id})
        return commands

    def acknowledge(self, modality: str, ok: bool = True, detail: str | None = None) -> list[dict]:
        """Record actual modality delivery. A failure reduces modality count safely."""
        if self.current_id is None or self.state in TERMINAL:
            return []
        key = f"{self.current_id}:{modality}"
        if key in self.acknowledged:
            return []
        self.acknowledged.add(key)
        if ok:
            self._event(f"{modality}_ack", self.current_id, detail=detail)
            return []
        self._event("fallback_triggered", self.current_id, modality=modality, detail=detail)
        if modality == "speech":
            self.state = "waiting_touch"
            return [{"cmd": "show_text_pause", "beat_id": self.current_id}]
        return [{"cmd": "suppress_modality", "beat_id": self.current_id, "modality": modality}]

    def speech_completed(self) -> list[dict]:
        if self.state != "running" or self.current_id is None:
            return []
        self._event("speech_completed", self.current_id)
        interaction = self.by_id[self.current_id].get("interaction")
        if interaction and interaction.get("kind") == "touch_prompt":
            self.state = "waiting_touch"
            self._event("touch_prompt_shown", self.current_id, hook_id=interaction.get("hook_id"))
            return [{"cmd": "await_touch", "beat_id": self.current_id, "interaction": interaction}]
        if interaction and interaction.get("kind") == "spoken_checkpoint":
            self.state = "waiting_spoken_checkpoint"
            self._event("spoken_checkpoint_started", self.current_id,
                        hook_id=interaction.get("hook_id"))
            return [{"cmd": "suspend_for_spoken_checkpoint", "beat_id": self.current_id,
                     "interaction": interaction}]
        return self._advance("complete")

    def touch_response(self, outcome: str, payload: dict | None = None) -> list[dict]:
        if self.state != "waiting_touch" or self.current_id is None:
            return []
        interaction = self.by_id[self.current_id].get("interaction") or {}
        self._event("touch_response_received", self.current_id, outcome=outcome,
                    hook_id=interaction.get("hook_id"), response=payload or {})
        return self._resolve_assessment(outcome, payload)

    def spoken_checkpoint_resolved(self, outcome: str, payload: dict | None = None) -> list[dict]:
        if self.state != "waiting_spoken_checkpoint" or self.current_id is None:
            return []
        interaction = self.by_id[self.current_id].get("interaction") or {}
        self._event("spoken_checkpoint_resolved", self.current_id, outcome=outcome,
                    hook_id=interaction.get("hook_id"), response=payload or {})
        return self._resolve_assessment(outcome, payload)

    def _resolve_assessment(self, outcome: str, payload: dict | None) -> list[dict]:
        assert self.current_id is not None
        interaction = self.by_id[self.current_id].get("interaction") or {}
        self._event("assessment_scored", self.current_id, outcome=outcome,
                    interaction=interaction, response=payload or {})
        return self._advance(outcome)

    def interrupt(self, audio_ref: str | None = None) -> list[dict]:
        if self.state != "running" or self.current_id is None:
            return []
        beat = self.by_id[self.current_id]
        self._interrupted_from = self.current_id
        self.state = "interrupted"
        self._event("interrupt_detected", self.current_id, audio_ref=audio_ref,
                    resumable=bool(beat.get("resumable", True)))
        return [{"cmd": "duck_or_pause_speech", "beat_id": self.current_id},
                {"cmd": "capture_interrupt", "beat_id": self.current_id, "audio_ref": audio_ref}]

    def resume_decision(self, decision: str) -> list[dict]:
        if self.state != "interrupted" or self.current_id is None:
            return []
        if decision == "resume" and self.by_id[self.current_id].get("resumable", True):
            self.state = "running"
            self._event("resume_decision_received", self.current_id, decision=decision)
            return [{"cmd": "resume_speech", "beat_id": self.current_id}]
        if decision in ("end", "answer_interjection"):
            self.state = "cancelled"
            self._event("script_completed", self.current_id, status="interrupted", decision=decision)
            close = self._close_board(None)     # tear the child down before ending
            return close + [{"cmd": "end_script", "beat_id": self.current_id}]
        raise ValueError("decision must be resume, answer_interjection, or end")

    def _close_board(self, next_id: str | None) -> list[dict]:
        """Emit board_close when the child is open and the next beat does not use it (or the
        script/branch is ending). LVGL then tears Board Buddy down and restores its card."""
        if not self._board_open:
            return []
        next_beat = self.by_id.get(next_id) if next_id else None
        if next_beat is not None and self._board_visual(next_beat) is not None:
            return []                       # next beat keeps the board open — don't close
        self._board_open = False
        return [{"cmd": "board_close", "beat_id": self.current_id}]

    def _advance(self, outcome: str) -> list[dict]:
        assert self.current_id is not None
        beat = self.by_id[self.current_id]
        target = {
            "correct": beat.get("on_correct"),
            "incorrect": beat.get("on_incorrect"),
            "wrong": beat.get("on_incorrect"),
            "nonresponse": beat.get("on_nonresponse"),
        }.get(outcome) or beat.get("on_complete")
        self._event("beat_completed", self.current_id, outcome=outcome, next_beat_id=target)
        close = self._close_board(target)
        if target is None:
            self.state = "completed"
            self._event("script_completed", self.current_id, status="completed")
            return close + [{"cmd": "complete_script", "beat_id": self.current_id}]
        if target not in self.by_id:
            self.state = "failed"
            self._event("fallback_triggered", self.current_id, modality="navigation",
                        detail="branch target missing")
            return close + [{"cmd": "safe_pause", "beat_id": self.current_id}]
        self.current_id = target
        self.state = "armed"
        return close + self._prepare_current()

