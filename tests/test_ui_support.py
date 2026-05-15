from __future__ import annotations

import json
from pathlib import Path

from learning_agent.core.documents import write_json
from learning_agent.tasks.rvm.workflow import review_rvm
from learning_agent.core.memory import default_memory_paths
from learning_agent.ui_support import (
    append_learning_candidate,
    artifact_inventory,
    create_learning_candidate,
    format_memory_inventory,
    format_score,
    learning_queue_path,
    load_learning_candidates,
    memory_inventory,
    required_human_actions,
    summarize_review,
    update_learning_candidate_status,
)
from learning_agent.ui import HELP_SECTIONS


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "out" / "test_ui_support"


def test_summarize_review_surfaces_required_human_actions() -> None:
    _clean_scratch()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    result = review_rvm(
        [ROOT / "examples" / "standards.csv"],
        [ROOT / "examples" / "project.txt"],
        ["STD-001"],
    )
    review_path = SCRATCH / "review.json"
    write_json(review_path, result["result"])

    summary = summarize_review(review_path)

    assert summary["decision_count"] == 5
    assert summary["compliance_failure_count"] > 0
    assert any(item["action"] == "Resolve compliance failures" for item in summary["required_human_actions"])
    assert any(item["action"] == "Complete traceability links" for item in summary["required_human_actions"])
    _clean_scratch()


def test_required_human_actions_handles_empty_review() -> None:
    actions = required_human_actions({"decisions": []})

    assert actions == [
        {
            "priority": "required",
            "action": "Run workflow",
            "context": "No RVM decisions are present. Add inputs and run the workflow before review or approval.",
        }
    ]


def test_artifact_inventory_is_recursive_and_score_formatting_is_stable() -> None:
    _clean_scratch()
    nested = SCRATCH / "nested"
    nested.mkdir(parents=True, exist_ok=True)
    artifact = nested / "artifact.json"
    artifact.write_text(json.dumps({"ok": True}), encoding="utf-8")

    inventory = artifact_inventory(SCRATCH)

    assert [item.name for item in inventory] == ["artifact.json"]
    assert format_score(0.456) == "0.46"
    assert format_score("bad") == "0.00"
    _clean_scratch()


def test_memory_inventory_formats_as_readable_list() -> None:
    _clean_scratch()
    paths = default_memory_paths(workspace=SCRATCH / "workspace", root=SCRATCH / "memory")
    inventory = memory_inventory(paths)

    text = format_memory_inventory(inventory)

    assert "Memory root:" in text
    assert "Stores:" in text
    assert "- Shared Canonical Store" in text
    assert "- Learning Queue" in text
    assert "{" not in text
    _clean_scratch()


def test_learning_queue_lifecycle_is_file_backed() -> None:
    _clean_scratch()
    paths = default_memory_paths(workspace=SCRATCH / "workspace", root=SCRATCH / "memory")
    queue = learning_queue_path(paths)
    candidate = create_learning_candidate(
        task="review_rejected",
        input_text="REQ-1 draft decision",
        bad_output="applicable",
        corrected_output="not_applicable",
        rationale="Architecture boundary excludes this function.",
        tags=["ui_feedback"],
        source="approval_workflow",
    )

    candidate_id = append_learning_candidate(queue, candidate)
    loaded = load_learning_candidates(queue)
    changed = update_learning_candidate_status(queue, {candidate_id}, "approved", ["vec-1"])
    reloaded = load_learning_candidates(queue)

    assert loaded[0]["status"] == "pending"
    assert loaded[0]["source"] == "approval_workflow"
    assert changed == 1
    assert reloaded[0]["status"] == "approved"
    assert reloaded[0]["applied_ids"] == ["vec-1"]
    _clean_scratch()


def test_ui_help_sections_cover_required_explanation_parts() -> None:
    required_sections = {
        "Standard / requirement documents",
        "Project context / DOORS exports / design documents",
        "Evidence artifacts to hash",
        "Workflow and memory policy",
        "Initial optimization from known-good RVMs",
        "Resolved persistent memory locations",
        "Reference and project memory",
        "Learning queue",
        "Search persistent memory",
        "Run actions",
        "Current review artifact",
        "Run log",
        "Compliance",
        "Failures",
        "Decisions",
        "Avg Confidence",
        "Low Confidence",
        "Not Applicable",
        "Required human actions",
        "Compliance findings",
        "RVM decisions",
        "Artifact output directory",
        "Generated artifacts",
        "Artifact preview",
        "Approval context",
        "Record approval state",
        "Guide",
    }

    assert required_sections <= set(HELP_SECTIONS)
    for section in required_sections:
        content = HELP_SECTIONS[section]
        assert content["summary"]
        assert content["details"]
        assert content["sources"]
        assert content["usage"]


def _clean_scratch() -> None:
    if not SCRATCH.exists():
        return
    for path in sorted(SCRATCH.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    SCRATCH.rmdir()
