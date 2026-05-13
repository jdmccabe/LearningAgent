from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from learning_agent.tasks.rvm.schema import ComplianceFinding, ComplianceReport, Requirement, RvmDecision


ALLOWED_PRIMARY_METHODS = {"test", "analysis", "inspection", "demonstration"}
SUBJECTIVE_TERMS = {
    "acceptable",
    "adequate",
    "easy",
    "efficient",
    "fast",
    "intuitive",
    "optimal",
    "quick",
    "quickly",
    "rapid",
    "reasonable",
    "robust",
    "sufficient",
    "timely",
    "user-friendly",
}
METHOD_COMBO_PATTERN = re.compile(r"\b(test|analysis|inspection|demonstration)\s*[/,+&]\s*(test|analysis|inspection|demonstration)\b", re.I)
DOC_ANCHOR_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_-]{2,}\b.*\b(sec|section|para|paragraph|table|fig|figure)\b", re.I)
EXECUTION_ARTIFACT_PATTERN = re.compile(r"(\bsha256:[a-f0-9]{16,}\b|\b[a-f0-9]{32,64}\b|\.log\b|\.pdf\b|\.xml\b|\.json\b|\.csv\b|\.xlsx\b|ATR-|TR-|REPORT)", re.I)
BOUNDED_CRITERIA_PATTERN = re.compile(r"(<=|>=|<|>|=|\bbetween\b|\bwithin\b|\bfrom\b.+\bto\b|\bpass\b|\bfail\b|\btrue\b|\bfalse\b|\b0x[0-9a-f]+\b|\d+(\.\d+)?)", re.I)


def audit_compliance_from_file(path: str | Path) -> ComplianceReport:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    decisions = [_decision_from_dict(item) for item in data.get("decisions", [])]
    graph_nodes = data.get("graph", {}).get("nodes", [])
    requirements = [
        Requirement(
            id=node["id"],
            text=node.get("properties", {}).get("text", ""),
            parent_id=node.get("properties", {}).get("parent_id"),
        )
        for node in graph_nodes
        if node.get("kind") == "requirement"
    ]
    return audit_compliance(decisions, requirements)


def audit_compliance(decisions: list[RvmDecision], requirements: list[Requirement]) -> ComplianceReport:
    requirements_by_id = {req.id: req for req in requirements}
    children_by_parent: dict[str, list[str]] = {}
    for req in requirements:
        if req.parent_id:
            children_by_parent.setdefault(req.parent_id, []).append(req.id)

    findings: list[ComplianceFinding] = []
    for decision in decisions:
        req = requirements_by_id.get(decision.requirement_id)
        expected_parent = req.parent_id if req else None
        expected_children = children_by_parent.get(decision.requirement_id, [])

        if expected_parent and expected_parent not in decision.parent_ids:
            findings.append(_finding(decision.requirement_id, "TRACE_PARENT", f"Missing explicit parent ID '{expected_parent}'.", "Populate parent_ids with the exact high-level requirement identifier."))
        if not expected_parent and not decision.parent_ids:
            findings.append(_finding(decision.requirement_id, "TRACE_PARENT", "No parent requirement is recorded.", "Use a strict source high-level requirement ID or mark the record as top-level with an approved waiver field."))
        if expected_children:
            missing_children = sorted(set(expected_children) - set(decision.child_ids))
            if missing_children:
                findings.append(_finding(decision.requirement_id, "TRACE_CHILD", f"Missing child trace IDs: {', '.join(missing_children)}.", "Populate child_ids with exact low-level requirement or implementation identifiers."))
        elif not decision.child_ids:
            findings.append(_finding(decision.requirement_id, "TRACE_CHILD", "No child requirement or implementation block is recorded.", "Add exact child requirement, design element, code unit, or test/implementation block identifier."))

        method = decision.verification_method.lower()
        if decision.applicability != "not_applicable":
            if method not in ALLOWED_PRIMARY_METHODS:
                findings.append(_finding(decision.requirement_id, "METHOD_PRIMARY", f"Primary verification method '{decision.verification_method}' is not one of Test, Demonstration, Inspection, Analysis.", "Choose exactly one primary method, or split work into separate verification records."))
            if METHOD_COMBO_PATTERN.search(method):
                findings.append(_finding(decision.requirement_id, "METHOD_COMBO", "Verification method combines multiple methods.", "Split combined methods into separate verification records."))

        if not decision.procedure_reference or not DOC_ANCHOR_PATTERN.search(decision.procedure_reference):
            findings.append(_finding(decision.requirement_id, "EVIDENCE_PROCEDURE", "Procedure reference does not identify an exact document anchor.", "Use a concrete reference such as ATP-102 Rev B Sec 4.2."))
        if decision.applicability != "not_applicable" and not any(EXECUTION_ARTIFACT_PATTERN.search(item) for item in decision.execution_artifacts):
            findings.append(_finding(decision.requirement_id, "EVIDENCE_EXECUTION", "No concrete execution artifact, file hash, log, or signed report is recorded.", "Add artifact identifiers such as ATR-102_Run4.log or sha256:<digest>."))

        criteria_text = decision.success_criteria or req.text if req else decision.success_criteria
        subjective = sorted(term for term in SUBJECTIVE_TERMS if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", criteria_text.lower()))
        if subjective:
            findings.append(_finding(decision.requirement_id, "CRITERIA_SUBJECTIVE", f"Subjective success criteria term(s): {', '.join(subjective)}.", "Replace qualitative wording with bounded, measurable pass/fail criteria."))
        if decision.applicability != "not_applicable" and not BOUNDED_CRITERIA_PATTERN.search(criteria_text):
            findings.append(_finding(decision.requirement_id, "CRITERIA_OBJECTIVE", "Success criteria are not objectively bounded or directly pass/fail.", "Add measurable limits, enumerated states, exact expected values, or explicit pass/fail condition."))

        if decision.change_log:
            for index, change in enumerate(decision.change_log, start=1):
                missing = [key for key in ("timestamp", "author_id", "technical_justification") if not change.get(key)]
                if missing:
                    findings.append(_finding(decision.requirement_id, "CHANGE_LOG", f"Change log entry {index} missing: {', '.join(missing)}.", "Each change must include timestamp, author ID, and technical justification."))
        elif decision.applicability in {"not_applicable", "conditional"} or decision.assumptions:
            findings.append(_finding(decision.requirement_id, "CHANGE_RATIONALE", "Applicability/method assumptions lack a formal change rationale block.", "Add timestamp, author ID, and technical justification tied to the master architecture."))

        if decision.applicability == "not_applicable" and not decision.evidence:
            findings.append(_finding(decision.requirement_id, "APPLICABILITY_EVIDENCE", "Not-applicable decision lacks cited architecture or boundary evidence.", "Cite the exact architecture document and section that removes the requirement from project scope."))

    failures = [finding for finding in findings if finding.severity == "failure"]
    warnings = [finding for finding in findings if finding.severity == "warning"]
    return ComplianceReport(
        passed=not failures,
        finding_count=len(findings),
        failure_count=len(failures),
        warning_count=len(warnings),
        findings=findings,
    )


def _decision_from_dict(data: dict[str, Any]) -> RvmDecision:
    return RvmDecision(
        requirement_id=data.get("requirement_id", ""),
        applicability=data.get("applicability", "unknown"),
        verification_method=data.get("verification_method", "unknown"),
        rationale=data.get("rationale", ""),
        parent_ids=list(data.get("parent_ids", [])),
        child_ids=list(data.get("child_ids", [])),
        procedure_reference=data.get("procedure_reference", ""),
        execution_artifacts=list(data.get("execution_artifacts", [])),
        success_criteria=data.get("success_criteria", ""),
        change_log=list(data.get("change_log", [])),
        evidence=[],
        confidence=float(data.get("confidence", 0.0)),
        trace_links=list(data.get("trace_links", [])),
        assumptions=list(data.get("assumptions", [])),
    )


def _finding(requirement_id: str, rule_id: str, message: str, fix: str) -> ComplianceFinding:
    return ComplianceFinding(
        requirement_id=requirement_id,
        rule_id=rule_id,
        severity="failure",
        message=message,
        fix=fix,
    )

