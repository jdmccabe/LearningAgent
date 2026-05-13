from __future__ import annotations

import json
import re
from pathlib import Path

from learning_agent.core.documents import load_document
from learning_agent.core.self_improvement import ImprovementPlan, ImprovementSuggestion
from learning_agent.tasks.rvm.parsing import parse_good_rvm, parse_requirements
from learning_agent.tasks.rvm.workflow import _tokens


def suggest_rvm_improvements(
    gold_path: str | Path,
    prediction_path: str | Path,
    standard_paths: list[str | Path],
    project_paths: list[str | Path],
) -> ImprovementPlan:
    """Generate deterministic policy-tuning suggestions from benchmark failures."""

    gold = {item.requirement_id: item for item in parse_good_rvm(gold_path)}
    prediction_data = json.loads(Path(prediction_path).read_text(encoding="utf-8"))
    predictions = {
        item["requirement_id"]: item
        for item in prediction_data.get("decisions", prediction_data.get("result", {}).get("decisions", []))
    }
    requirements = {
        req.id: req
        for path in standard_paths
        for req in parse_requirements(path)
    }
    project_lines = [
        line.strip()
        for path in project_paths
        for line in load_document(path).text.splitlines()
        if line.strip()
    ]

    suggestions: list[ImprovementSuggestion] = []
    for req_id, expected in gold.items():
        actual = predictions.get(req_id, {})
        req = requirements.get(req_id)
        if not req:
            continue
        actual_app = actual.get("applicability", "missing")
        if expected.applicability != actual_app:
            suggestions.extend(_suggest_applicability(req_id, req.text, expected.applicability, actual_app, project_lines))
        actual_ver = actual.get("verification_method", "missing")
        if expected.verification_method != actual_ver:
            suggestions.append(
                ImprovementSuggestion(
                    kind="verification_keyword",
                    target=expected.verification_method,
                    suggestion=(
                        "Review whether distinctive requirement terms should be added "
                        f"to the '{expected.verification_method}' verification keyword policy."
                    ),
                    evidence=req.text,
                    confidence=0.45,
                )
            )
    return ImprovementPlan(
        summary=f"Generated {len(suggestions)} candidate improvement(s) from benchmark failures.",
        suggestions=suggestions,
    )


def _suggest_applicability(
    req_id: str,
    requirement_text: str,
    expected: str,
    actual: str,
    project_lines: list[str],
) -> list[ImprovementSuggestion]:
    suggestions: list[ImprovementSuggestion] = []
    best_line = _best_project_line(requirement_text, project_lines)
    if expected == "not_applicable":
        exclusion = _candidate_exclusion_phrase(best_line)
        suggestions.append(
            ImprovementSuggestion(
                kind="not_applicable_policy",
                target=req_id,
                suggestion=(
                    f"Consider adding '{exclusion}' as a scoped not-applicable phrase "
                    "or adding a domain synonym that links this project exclusion to the requirement."
                ),
                evidence=f"expected={expected}, actual={actual}; project line: {best_line}",
                confidence=0.55 if exclusion else 0.3,
            )
        )
    elif expected == "applicable":
        suggestions.append(
            ImprovementSuggestion(
                kind="applicability_overlap",
                target=req_id,
                suggestion=(
                    "Consider adding domain synonyms/normalizers or lowering the positive "
                    "overlap threshold for this requirement family."
                ),
                evidence=f"expected={expected}, actual={actual}; best project line: {best_line}",
                confidence=0.4,
            )
        )
    else:
        suggestions.append(
            ImprovementSuggestion(
                kind="applicability_policy",
                target=req_id,
                suggestion=f"Add or refine a policy rule for expected applicability '{expected}'.",
                evidence=f"actual={actual}; best project line: {best_line}",
                confidence=0.35,
            )
        )
    return suggestions


def _best_project_line(requirement_text: str, project_lines: list[str]) -> str:
    req_tokens = _tokens(requirement_text)
    if not project_lines:
        return ""
    return max(project_lines, key=lambda line: _jaccard(req_tokens, _tokens(line)))


def _candidate_exclusion_phrase(line: str) -> str:
    match = re.search(r"\b(no|not|without)\s+([a-z0-9 ]{3,50})", line.lower())
    return match.group(0).strip(" .;,") if match else ""


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left or right else 0.0

