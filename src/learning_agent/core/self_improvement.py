from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ImprovementSuggestion:
    kind: str
    target: str
    suggestion: str
    evidence: str
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImprovementPlan:
    summary: str
    suggestions: list[ImprovementSuggestion] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "suggestions": [item.to_dict() for item in self.suggestions],
        }

