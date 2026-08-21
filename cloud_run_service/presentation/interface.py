"""Device realization for the approved response surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, TYPE_CHECKING

from runtime.contracts import (
    FailureSeverity, FailureSignal, ModuleOutcome, ProvisionalOutput,
    RealizationReceipt, RealizationStatus, TurnInput,
)
from voice.sanitize import sanitize_for_speech

if TYPE_CHECKING:
    from response_generation import GeneratedResponse
    from response_planning import ResponsePlan

CAPABILITY = "presentation"


@dataclass(frozen=True)
class PresentationRequest:
    turn_input: TurnInput
    response_plan: "ResponsePlan"
    generated_response: "GeneratedResponse"
    speech: Callable[[str], Any] | None = None
    display: Callable[[Mapping[str, Any]], Any] | None = None
    emit: Callable[[ProvisionalOutput], Any] | None = None
    interrupted: Callable[[], bool] | None = None
    display_items: tuple[Mapping[str, Any], ...] = ()


class PresentationInterface(Protocol):
    def realize(self, request: PresentationRequest) -> ModuleOutcome[RealizationReceipt]: ...


class Presentation:
    """Realize speech, cards, formulas, and retrieved crops."""

    def realize(self, request: PresentationRequest) -> ModuleOutcome[RealizationReceipt]:
        turn_id = request.turn_input.turn_id
        plan = request.response_plan
        intended = tuple(plan.intended_modalities)
        failures: list[FailureSignal] = []
        delivered: list[str] = []
        details: dict[str, Any] = {"events": [], "display": []}

        if "speech" in intended:
            if not request.turn_input.device.speech:
                failures.append(self._failure("unavailable_speech", "capability", False))
            else:
                spoken = sanitize_for_speech(str(request.generated_response.answer or ""))
                if request.interrupted and request.interrupted():
                    failures.append(self._failure("stream_interrupted", "streaming", True))
                elif spoken:
                    try:
                        if request.speech is not None:
                            request.speech(spoken)
                            delivered.append("speech")
                        self._emit(request, turn_id, len(details["events"]), "speech", {"text": spoken}, details)
                    except Exception as exc:
                        failures.append(self._failure("stream_interrupted", "streaming", True, str(exc)))

        if "display" in intended or "display" in plan.approved_modalities:
            artifacts = self._artifacts(request)
            if not request.turn_input.device.display:
                if artifacts:
                    failures.append(self._failure("display_unavailable", "capability", True))
            elif not artifacts and "display" in intended:
                failures.append(self._failure("invalid_asset", "asset_validation", True))
            else:
                for artifact in artifacts:
                    if request.interrupted and request.interrupted():
                        failures.append(self._failure("stream_interrupted", "streaming", True))
                        break
                    if not self._valid_artifact(artifact):
                        failures.append(self._failure("invalid_asset", "asset_validation", True, str(artifact.get("kind") or "display")))
                        continue
                    try:
                        if request.display is not None:
                            request.display(artifact)
                            if "display" not in delivered:
                                delivered.append("display")
                        details["display"].append(dict(artifact))
                        self._emit(request, turn_id, len(details["events"]), "display", artifact, details)
                    except Exception as exc:
                        failures.append(self._failure("partial_realization", "realization", True, str(exc)))

        if failures and any(f.cause == "stream_interrupted" for f in failures):
            status = RealizationStatus.INTERRUPTED
        elif failures and delivered:
            status = RealizationStatus.DEGRADED
        elif failures:
            status = RealizationStatus.FAILED if any(not f.valid_outcome for f in failures) else RealizationStatus.DEGRADED
        elif delivered == list(intended):
            status = RealizationStatus.COMPLETE
        else:
            status = RealizationStatus.PARTIAL
        receipt = RealizationReceipt(turn_id=turn_id, status=status, intended=intended,
                                     delivered=tuple(delivered), failures=tuple(failures), details=details)
        return ModuleOutcome(value=receipt, failures=tuple(failures))

    @staticmethod
    def _artifacts(request: PresentationRequest) -> list[dict[str, Any]]:
        artifacts = [dict(item) for item in request.display_items]
        for beat in request.response_plan.script.beats:
            intent = beat.visual_intent
            if intent is None or not intent.allowed or intent.visual_type.value == "none":
                continue
            artifacts.append({"kind": intent.visual_type.value, "asset_ref": intent.asset_ref,
                              "representation_target": intent.representation_target, "beat_id": beat.beat_id})
        return artifacts

    @staticmethod
    def _valid_artifact(artifact: Mapping[str, Any]) -> bool:
        kind = str(artifact.get("kind") or "")
        if kind in {"question-card", "score-card", "formula", "static_text_formula"}:
            return bool(artifact.get("text") or artifact.get("question") or artifact.get("formula") or artifact.get("payload"))
        return bool(artifact.get("asset_ref") or artifact.get("image_path") or artifact.get("payload") or artifact.get("text"))

    @staticmethod
    def _emit(request, turn_id, sequence, kind, payload, details) -> None:
        event = ProvisionalOutput(turn_id=turn_id, sequence=sequence, kind=kind, payload=payload)
        details["events"].append(event.kind)
        if request.emit is not None:
            request.emit(event)

    @staticmethod
    def _failure(cause, phase, recoverable, detail="") -> FailureSignal:
        return FailureSignal(capability=CAPABILITY, phase=phase,
                             severity=FailureSeverity.DEGRADED if recoverable else FailureSeverity.ERROR,
                             recoverable=recoverable, cause=cause, valid_outcome=recoverable,
                             context={"detail": detail} if detail else {})
