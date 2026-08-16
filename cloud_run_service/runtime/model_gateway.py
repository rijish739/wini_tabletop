"""Shared transport-only port for structured model calls."""

from __future__ import annotations

from typing import Any, Protocol


class ModelGateway(Protocol):
    def generate_json(
        self,
        prompt: str,
        *,
        response_schema: Any,
        system: str | None,
        cached_content: str | None,
        model: str,
        location: str,
        timeout_s: float,
        temperature: float,
    ) -> Any: ...


class VertexModelGateway:
    """Thin adapter: transport configuration in, transport result out."""

    def generate_json(self, prompt: str, **kwargs):
        import llm_vertex

        return llm_vertex.generate_json(prompt, **kwargs)
