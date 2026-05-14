from __future__ import annotations

import json
from pathlib import Path

from learning_agent.core.documents import write_json
from learning_agent.tasks.rvm.workflow import review_rvm
from learning_agent.ui_support import artifact_inventory, format_score, required_human_actions, summarize_review


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


def _clean_scratch() -> None:
    if not SCRATCH.exists():
        return
    for path in sorted(SCRATCH.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    SCRATCH.rmdir()
