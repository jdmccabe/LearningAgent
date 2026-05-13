from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Applicability = Literal["applicable", "not_applicable", "conditional", "unknown"]
VerificationMethod = Literal[
    "test",
    "analysis",
    "inspection",
    "demonstration",
    "similarity",
    "certification",
    "other",
    "unknown",
]


@dataclass
class Evidence:
    source: str
    quote: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Requirement:
    id: str
    text: str
    source_document: str = ""
    parent_id: str | None = None
    standard: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RvmDecision:
    requirement_id: str
    applicability: Applicability
    verification_method: VerificationMethod
    rationale: str
    evidence: list[Evidence] = field(default_factory=list)
    confidence: float = 0.0
    trace_links: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = [e.to_dict() for e in self.evidence]
        return data


@dataclass
class ImpactReport:
    changed_requirement_id: str
    impacted_requirement_ids: list[str]
    impacted_verification_ids: list[str]
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

