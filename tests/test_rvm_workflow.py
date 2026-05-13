from __future__ import annotations

import json
from pathlib import Path

from learning_agent.tasks.rvm.evaluation import evaluate_rvm
from learning_agent.tasks.rvm.workflow import review_rvm


ROOT = Path(__file__).resolve().parents[1]


def test_review_rvm_runs_offline() -> None:
    result = review_rvm(
        [ROOT / "examples" / "standards.csv"],
        [ROOT / "examples" / "project.txt"],
        ["STD-001"],
    )
    decisions = {
        item["requirement_id"]: item
        for item in result["result"]["decisions"]
    }
    assert decisions["STD-002"]["applicability"] == "not_applicable"
    assert decisions["STD-004"]["verification_method"] == "test"
    assert result["result"]["impacts"][0]["changed_requirement_id"] == "STD-001"
    assert "STD-001.1" in result["result"]["impacts"][0]["impacted_requirement_ids"]


def test_rvm_evaluation_scores_predictions() -> None:
    result = review_rvm(
        [ROOT / "examples" / "standards.csv"],
        [ROOT / "examples" / "project.txt"],
    )
    pred = ROOT / "out" / "test_pred.json"
    pred.parent.mkdir(exist_ok=True)
    pred.write_text(json.dumps(result["result"]), encoding="utf-8")

    report = evaluate_rvm(ROOT / "examples" / "gold_rvm.csv", pred)

    assert "applicability" in report.metrics
    assert report.metrics["applicability"]["count"] == 5
    pred.unlink()
