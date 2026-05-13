from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from learning_agent.core.evaluation import EvaluationReport, classification_metrics, link_metrics
from learning_agent.tasks.rvm.parsing import parse_good_rvm


def evaluate_rvm(gold_path: str | Path, prediction_path: str | Path) -> EvaluationReport:
    gold = parse_good_rvm(gold_path)
    prediction_data = json.loads(Path(prediction_path).read_text(encoding="utf-8"))
    predictions = prediction_data.get("decisions", prediction_data.get("result", {}).get("decisions", []))

    expected_app = {item.requirement_id: item.applicability for item in gold}
    predicted_app = {
        item["requirement_id"]: item.get("applicability", "unknown") for item in predictions
    }
    expected_ver = {item.requirement_id: item.verification_method for item in gold}
    predicted_ver = {
        item["requirement_id"]: item.get("verification_method", "unknown") for item in predictions
    }
    expected_links = [
        (item.requirement_id, link) for item in gold for link in item.trace_links
    ]
    predicted_links = [
        (item["requirement_id"], link)
        for item in predictions
        for link in item.get("trace_links", [])
    ]

    failures: list[dict[str, Any]] = []
    for req_id, expected in expected_app.items():
        actual = predicted_app.get(req_id, "missing")
        if actual != expected:
            failures.append(
                {
                    "requirement_id": req_id,
                    "field": "applicability",
                    "expected": expected,
                    "actual": actual,
                }
            )
    for req_id, expected in expected_ver.items():
        actual = predicted_ver.get(req_id, "missing")
        if actual != expected:
            failures.append(
                {
                    "requirement_id": req_id,
                    "field": "verification_method",
                    "expected": expected,
                    "actual": actual,
                }
            )

    metrics = {
        "applicability": classification_metrics(
            expected_app,
            predicted_app,
            ["applicable", "not_applicable", "conditional", "unknown"],
        ),
        "verification_method": classification_metrics(
            expected_ver,
            predicted_ver,
            [
                "test",
                "analysis",
                "inspection",
                "demonstration",
                "similarity",
                "certification",
                "other",
                "unknown",
            ],
        ),
        "trace_links": link_metrics(expected_links, predicted_links),
    }
    return EvaluationReport(metrics=metrics, failures=failures)

