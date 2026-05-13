from __future__ import annotations

from learning_agent.tasks.rvm.compliance import audit_compliance
from learning_agent.tasks.rvm.schema import Evidence, Requirement, RvmDecision


def test_compliance_audit_flags_low_quality_entry() -> None:
    requirements = [
        Requirement(id="LLR-1", text="The system shall boot quickly.", parent_id=None),
    ]
    decisions = [
        RvmDecision(
            requirement_id="LLR-1",
            applicability="applicable",
            verification_method="test/analysis",  # type: ignore[arg-type]
            rationale="Will be checked during integration.",
            success_criteria="The system shall boot quickly.",
        )
    ]

    report = audit_compliance(decisions, requirements)
    rule_ids = {finding.rule_id for finding in report.findings}

    assert not report.passed
    assert "TRACE_PARENT" in rule_ids
    assert "TRACE_CHILD" in rule_ids
    assert "METHOD_PRIMARY" in rule_ids
    assert "EVIDENCE_PROCEDURE" in rule_ids
    assert "EVIDENCE_EXECUTION" in rule_ids
    assert "CRITERIA_SUBJECTIVE" in rule_ids


def test_compliance_audit_accepts_traceable_objective_entry() -> None:
    requirements = [
        Requirement(id="HL-SYS-REQ-402", text="Top level", parent_id=None),
        Requirement(
            id="LLR-402-1",
            text="The system shall transition to Ready-State in <= 1500 milliseconds.",
            parent_id="HL-SYS-REQ-402",
            assurance_standard="DO-178C",
            dal="A",
            lifecycle_objectives=["A-7.1", "A-7.2"],
        ),
        Requirement(id="CODE-BOOT-READY", text="Implementation block", parent_id="LLR-402-1"),
    ]
    decisions = [
        RvmDecision(
            requirement_id="LLR-402-1",
            applicability="applicable",
            verification_method="test",
            rationale="Verified by boot timing test.",
            parent_ids=["HL-SYS-REQ-402"],
            child_ids=["CODE-BOOT-READY"],
            procedure_reference="SW-ITP-04 Rev B Sec 5.1",
            execution_artifacts=["ATR-102_Run4.log", "sha256:0123456789abcdef0123456789abcdef"],
            success_criteria="Power-On to Ready-State shall be <= 1500 milliseconds and status register 0x00 shall return 0x01.",
            assurance_standard="DO-178C",
            dal="A",
            lifecycle_objectives=["A-7.1", "A-7.2"],
        )
    ]

    report = audit_compliance(decisions, requirements)

    assert report.passed
    assert report.finding_count == 0


def test_not_applicable_requires_architecture_evidence_and_change_rationale() -> None:
    requirements = [
        Requirement(id="REQ-WIRELESS", text="The system shall encrypt wireless links.", parent_id="HL-1"),
    ]
    decisions = [
        RvmDecision(
            requirement_id="REQ-WIRELESS",
            applicability="not_applicable",
            verification_method="other",
            rationale="Not applicable because this is a hardware project.",
            parent_ids=["HL-1"],
            child_ids=["WAIVER-WIRELESS-001"],
            procedure_reference="SYS-ARCH-01 Rev A Sec 2.1",
            evidence=[
                Evidence(
                    source="SYS-ARCH-01 Rev A Sec 2.1",
                    quote="Subsystem contains no wireless telemetry hardware.",
                    reason="System boundary exclusion.",
                )
            ],
        )
    ]

    report = audit_compliance(decisions, requirements)
    rule_ids = {finding.rule_id for finding in report.findings}

    assert "CHANGE_RATIONALE" in rule_ids
