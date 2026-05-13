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

PrimaryVerificationMethod = Literal["test", "analysis", "inspection", "demonstration"]


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
    parent_ids: list[str] = field(default_factory=list)
    child_ids: list[str] = field(default_factory=list)
    procedure_reference: str = ""
    execution_artifacts: list[str] = field(default_factory=list)
    success_criteria: str = ""
    change_log: list[dict[str, str]] = field(default_factory=list)
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


@dataclass
class ComplianceFinding:
    requirement_id: str
    rule_id: str
    severity: Literal["failure", "warning"]
    message: str
    fix: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ComplianceReport:
    passed: bool
    finding_count: int
    failure_count: int
    warning_count: int
    findings: list[ComplianceFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "finding_count": self.finding_count,
            "failure_count": self.failure_count,
            "warning_count": self.warning_count,
            "findings": [finding.to_dict() for finding in self.findings],
        }
