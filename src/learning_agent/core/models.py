from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class ModelRequest:
    """A model-agnostic request passed to adapters."""

    task: str
    prompt: str
    context: Mapping[str, Any] = field(default_factory=dict)
    schema: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ModelResponse:
    """A model-agnostic response returned by adapters."""

    text: str
    data: Mapping[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    adapter: str = "unknown"


class ModelAdapter(Protocol):
    """Interface for local heuristics, local LLMs, hosted APIs, or test fakes."""

    name: str

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Return a completion for the request."""


class NoOpModel:
    """Default model that never calls a network or requires credentials."""

    name = "noop"

    def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            text="",
            data={"reason": "No model adapter configured; deterministic workflow used."},
            confidence=0.0,
            adapter=self.name,
        )


class RuleBasedModel:
    """Small offline adapter useful for tests and bootstrapping prompts."""

    name = "rule-based"

    def complete(self, request: ModelRequest) -> ModelResponse:
        text = request.prompt.lower()
        if any(word in text for word in ("not applicable", "n/a", "out of scope")):
            return ModelResponse(
                text="not_applicable",
                data={"label": "not_applicable"},
                confidence=0.55,
                adapter=self.name,
            )
        return ModelResponse(
            text="unknown",
            data={"label": "unknown"},
            confidence=0.25,
            adapter=self.name,
        )

