from __future__ import annotations

from dataclasses import dataclass, field


DEFAULT_NOT_APPLICABLE_TERMS = {
    "not applicable",
    "n/a",
    "out of scope",
    "not used",
    "no external interface",
    "no human operator",
    "no wireless",
    "no battery",
    "software only",
    "hardware only",
    "not in scope",
}

DEFAULT_CONDITIONAL_TERMS = {
    "if",
    "when",
    "where",
    "unless",
    "as applicable",
    "where applicable",
    "for projects with",
}

VERIFICATION_KEYWORDS = {
    "test": {
        "test",
        "measure",
        "execute",
        "validate by running",
        "performance",
        "latency",
        "throughput",
        "load",
        "stress",
    },
    "analysis": {
        "analysis",
        "calculate",
        "model",
        "simulation",
        "derive",
        "prove",
        "formal",
        "coverage",
        "risk",
    },
    "inspection": {
        "inspect",
        "review",
        "document",
        "drawing",
        "code review",
        "configuration",
        "presence",
        "verify exists",
    },
    "demonstration": {
        "demonstrate",
        "demo",
        "show",
        "operator",
        "user",
        "workflow",
        "manual operation",
    },
    "certification": {
        "certified",
        "certificate",
        "compliance report",
        "third party",
        "supplier declaration",
    },
    "similarity": {
        "similarity",
        "heritage",
        "previously qualified",
        "equivalent",
        "unchanged design",
    },
}


@dataclass(frozen=True)
class RvmPolicy:
    not_applicable_terms: set[str] = field(default_factory=lambda: DEFAULT_NOT_APPLICABLE_TERMS)
    conditional_terms: set[str] = field(default_factory=lambda: DEFAULT_CONDITIONAL_TERMS)
    verification_keywords: dict[str, set[str]] = field(default_factory=lambda: VERIFICATION_KEYWORDS)
    low_confidence_threshold: float = 0.45

