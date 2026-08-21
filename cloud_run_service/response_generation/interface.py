"""Grounded learner-facing speech behind one Response Generation Interface."""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol, TYPE_CHECKING
from runtime.contracts import FailureSeverity, FailureSignal, ModuleOutcome
from runtime.model_gateway import ModelCall, ModelGateway

if TYPE_CHECKING:
    from pedagogy import PedagogicalDecision
    from response_planning import ResponsePlan
    from retrieval import RetrievalResult
    from runtime.contracts import TurnInput

CAPABILITY = "response_generation"
SAFE_FALLBACK = "I couldn't prepare a grounded explanation just now. Let's try again."

@dataclass(frozen=True)
class ResponseGenerationStateView:
    history: tuple[Mapping[str, str], ...] = ()
    clarification: bool = False
    figure_on_screen: bool = False
    board_pending: bool = False
    same_problem: bool = False
    chapter_hint: str = "Class 10 Mathematics"
    writeback_note: str = ""

@dataclass(frozen=True)
class ResponseGenerationRequest:
    turn_input: "TurnInput"
    pedagogical: "PedagogicalDecision"
    retrieval: "RetrievalResult"
    response_plan: "ResponsePlan"
    state: ResponseGenerationStateView = ResponseGenerationStateView()
    deterministic_spoken: str | None = None
    stream: Callable[[str], None] | None = None

@dataclass(frozen=True)
class GeneratedResponse:
    answer: str
    assessing: bool
    backend: str
    model_calls: int = 0
    client_constructions: int = 0

class ResponseGenerationInterface(Protocol):
    def generate(self, request: ResponseGenerationRequest) -> ModuleOutcome[GeneratedResponse]: ...

class ResponseGeneration:
    def __init__(self, gateway: ModelGateway, *, backend: str = "model") -> None:
        self._gateway, self._backend = gateway, backend

    def generate(self, request: ResponseGenerationRequest) -> ModuleOutcome[GeneratedResponse]:
        if request.deterministic_spoken is not None:
            return ModuleOutcome(value=GeneratedResponse(
                request.deterministic_spoken, True, "deterministic"))
        before = self._gateway.statistics()
        prompt, tokens = self._prompt(request)
        call = ModelCall(prompt=prompt, max_output_tokens=tokens)
        try:
            answer = (self._gateway.generate(call) if request.stream is None else
                      "".join(self._gateway.stream(call)).strip())
            answer = self._budget(answer, request.turn_input.interaction.get("answer_budget") or {}) if answer else ""
            if not answer:
                return self._fallback("empty_output", before=before)
            proposal = request.response_plan.assessment_proposal
            if proposal is not None and proposal.hook.question:
                question = proposal.hook.question.strip()
                if question and question not in answer:
                    answer = f"{answer} {question}".strip()
            if request.stream is not None:
                request.stream(answer)
            after = self._gateway.statistics()
            return ModuleOutcome(value=GeneratedResponse(
                answer, request.response_plan.assessment_proposal is not None,
                self._backend, after.calls - before.calls,
                after.client_constructions))
        except TimeoutError as exc:
            return self._fallback("model_timeout", str(exc), before=before)
        except Exception as exc:
            return self._fallback("model_transport_failure", str(exc), before=before)

    def _prompt(self, request):
        state = request.state
        budget = dict(request.turn_input.interaction.get("answer_budget") or {})
        max_words, max_sentences = int(budget.get("max_words", 35)), int(budget.get("max_sentences", 2))
        action = str(request.pedagogical.action)
        evidence = "\n\n".join(
            f"EVIDENCE {i}:\n{str(item.content.get('text') or item.content.get('question') or item.content.get('why_wrong') or '')[:700]}"
            for i, item in enumerate(request.retrieval.manifest.evidence, 1))[:6000]
        history = ""
        if state.history:
            history = "RECENT CONVERSATION (build on it; do not repeat it):\n" + "\n".join(
                f"{row.get('role', '').upper()}: {row.get('text', '')}" for row in state.history[-6:]) + "\n\n"
        clarification = "Explain the same idea a different, simpler way using plainer words.\n" if state.clarification else ""
        continuity = "SAME PROBLEM: reuse the exact numbers and quantities from recent conversation.\n" if state.same_problem else ""
        screen = ("Refer directly to the figure on the screen and ground the explanation in it.\n"
                  if state.figure_on_screen else
                  "A board may be drawn later. Do not refer to a picture that may not appear.\n"
                  if state.board_pending else "")
        grounding = ("Use the evidence for the method and the learner's own numbers for their problem."
                     if request.retrieval.manifest.grounding == "method_only" else
                     "Use only the grounded evidence below; if it does not support a claim, say less.")
        proposal, assessment = request.response_plan.assessment_proposal, ""
        if proposal is not None and proposal.hook.question:
            assessment = "End with this verified question verbatim; never solve or paraphrase it:\n" + proposal.hook.question + "\n"
        prompt = (f"You are Wini, a friendly {state.chapter_hint} tutor.\n"
            f"Pedagogical action for this turn: {action}. {self._action_policy(action)}\n"
            f"PACING: speak at most {max_words} words and {max_sentences} sentence(s). Deliver one complete idea without greetings, apologies, preamble, LaTeX, or internal IDs.\n"
            f"{continuity}{assessment}{clarification}{screen}{grounding}\n"
            f"{history}{evidence}\n\nSTUDENT: {request.turn_input.interaction.get('text', '')}\n\nWINI:")
        return prompt, max(90, min(480, round(max_words * 3.5)))

    @staticmethod
    def _action_policy(action):
        return {"MISCONCEPTION_PROBE": "Ask the grounded diagnostic first and do not reveal the correction.",
            "SOCRATIC_Q": "Use one guiding question instead of a lecture.",
            "SOLVE_STUDENT_PROBLEM": "Solve the learner's exact problem, show compact steps, and state the final answer.",
            "REPRESENTATION_TRANSLATION": "Translate the idea into a representation the learner can picture.",
            "VISUAL_ANALOGY": "Use one concrete visual analogy grounded in the evidence.",
            "COMPLETION_STEP": "Show every step except the final one, then ask the learner to finish it.",
            "TRANSFER_PROBLEM": "Pose one fresh grounded transfer problem without solving it.",
            "METACOGNITIVE_REFLECT": "Ask for one short reflection or offer the next step; do not re-explain."}.get(
                action, "Teach clearly and briefly at Class 10 level.")

    @staticmethod
    def _budget(text, budget):
        max_words, max_sentences = int(budget.get("max_words", 35)), int(budget.get("max_sentences", 2))
        sentences = [x.strip() for x in re.findall(r"[^.!?]+[.!?]?", text) if x.strip()]
        kept, words = [], 0
        for sentence in sentences[:max_sentences]:
            count = len(sentence.split())
            if kept and words + count > max_words: break
            if not kept and count > max_words:
                sentence, count = " ".join(sentence.split()[:max_words]), max_words
            kept.append(sentence); words += count
        return " ".join(kept).strip()

    def _fallback(self, cause, detail="", before=None):
        after = self._gateway.statistics()
        calls = 0 if before is None else after.calls - before.calls
        return ModuleOutcome(value=GeneratedResponse(
                SAFE_FALLBACK, False, "fallback", calls,
                after.client_constructions),
            failures=(FailureSignal(capability=CAPABILITY, phase="generation",
                severity=FailureSeverity.DEGRADED, recoverable=True, cause=cause,
                valid_outcome=True, context={"detail": detail} if detail else {}),))
