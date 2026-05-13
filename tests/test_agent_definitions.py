from __future__ import annotations

from pathlib import Path

from learning_agent.tasks.rvm.agents import AGENT_DEFINITIONS, AGENT_SET_ID, agent_versions
from learning_agent.tasks.rvm.workflow import review_rvm


ROOT = Path(__file__).resolve().parents[1]


def test_agent_definitions_are_explicit_and_versioned() -> None:
    required = {
        "document_ingestion",
        "traceability_builder",
        "applicability_analyst",
        "verification_planner",
        "impact_analyzer",
        "compliance_auditor",
    }
    definitions = {definition.id: definition for definition in AGENT_DEFINITIONS}

    assert AGENT_SET_ID == "rvm-aerospace-v1"
    assert required <= set(definitions)
    for definition in definitions.values():
        assert definition.version
        assert definition.role
        assert len(definition.system_definition) > 80
        assert definition.inputs
        assert definition.outputs
        assert definition.hard_rules
        assert definition.failure_modes


def test_review_artifact_records_agent_versions() -> None:
    result = review_rvm(
        [ROOT / "examples" / "standards.csv"],
        [ROOT / "examples" / "project.txt"],
    )
    artifact = result["result"]["verification_artifact"]

    assert artifact["agent_set_id"] == AGENT_SET_ID
    assert artifact["agent_versions"] == agent_versions()

