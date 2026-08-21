"""Shared model transport with bounded calls, streaming, and statistics."""
from __future__ import annotations
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Iterable, Protocol

@dataclass(frozen=True)
class ModelCall:
    prompt: str
    max_output_tokens: int = 400
    temperature: float = 0.3
    timeout_s: float = 30.0
    model: str | None = None
    location: str | None = None
    retries: int = 1

@dataclass(frozen=True)
class ModelStatistics:
    calls: int = 0
    retries: int = 0
    failures: int = 0
    elapsed_ms: int = 0
    client_constructions: int = 0

class ModelGateway(Protocol):
    def generate(self, call: ModelCall) -> str: ...
    def stream(self, call: ModelCall) -> Iterable[str]: ...
    def statistics(self) -> ModelStatistics: ...
    def generate_json(self, prompt: str, *, response_schema: Any, system: str | None,
                      cached_content: str | None, model: str, location: str,
                      timeout_s: float, temperature: float) -> Any: ...

class VertexModelGateway:
    """Production adapter; llm_vertex owns the memoized SDK client."""
    def __init__(self) -> None:
        self._lock = Lock()
        self._stats = ModelStatistics(client_constructions=1)

    def _record(self, elapsed=0, *, retry=False, failure=False):
        with self._lock:
            old = self._stats
            self._stats = ModelStatistics(old.calls + (0 if retry else 1),
                old.retries + int(retry), old.failures + int(failure),
                old.elapsed_ms + elapsed, old.client_constructions)

    def generate(self, call: ModelCall) -> str:
        import llm_vertex
        started = time.perf_counter()
        for attempt in range(max(0, call.retries) + 1):
            try:
                reply = llm_vertex.generate_reply(
                    call.prompt, temperature=call.temperature,
                    max_output_tokens=max(64, call.max_output_tokens),
                    model=call.model or llm_vertex.DEFAULT_MODEL,
                    location=call.location or llm_vertex.DEFAULT_REGION,
                    timeout_s=call.timeout_s)
                self._record(int((time.perf_counter() - started) * 1000))
                return str(reply.text or "").strip()
            except (TimeoutError, ConnectionError):
                if attempt >= call.retries:
                    self._record(int((time.perf_counter() - started) * 1000), failure=True)
                    raise
                self._record(retry=True)
        raise AssertionError("unreachable")

    def stream(self, call: ModelCall) -> Iterable[str]:
        import llm_vertex
        started = time.perf_counter()
        try:
            yield from llm_vertex.generate_reply_stream(
                call.prompt, temperature=call.temperature,
                max_output_tokens=max(64, call.max_output_tokens),
                model=call.model or llm_vertex.DEFAULT_MODEL,
                location=call.location or llm_vertex.DEFAULT_REGION,
                timeout_s=call.timeout_s)
        except Exception:
            self._record(int((time.perf_counter() - started) * 1000), failure=True)
            raise
        else:
            self._record(int((time.perf_counter() - started) * 1000))

    def generate_json(self, prompt: str, **kwargs):
        import llm_vertex
        started = time.perf_counter()
        try:
            value = llm_vertex.generate_json(prompt, **kwargs)
        except Exception:
            self._record(int((time.perf_counter() - started) * 1000), failure=True)
            raise
        self._record(int((time.perf_counter() - started) * 1000))
        return value

    def statistics(self) -> ModelStatistics:
        return self._stats

class ReplayModelGateway:
    """Deterministic adapter using text, chunk sequences, or exceptions."""
    def __init__(self, responses: Iterable[Any]) -> None:
        self._responses = iter(responses)
        self.calls: list[ModelCall] = []
        self._failures = 0

    def _next(self, call):
        self.calls.append(call)
        value = next(self._responses)
        if isinstance(value, BaseException):
            self._failures += 1
            raise value
        return value

    def generate(self, call: ModelCall) -> str:
        value = self._next(call)
        return (value if isinstance(value, str) else "".join(value)).strip()

    def stream(self, call: ModelCall) -> Iterable[str]:
        value = self._next(call)
        yield from ((value,) if isinstance(value, str) else value)

    def generate_json(self, prompt: str, **kwargs):
        return self.generate(ModelCall(prompt, timeout_s=kwargs.get("timeout_s", 30)))

    def statistics(self) -> ModelStatistics:
        return ModelStatistics(calls=len(self.calls), failures=self._failures,
                               client_constructions=1)
