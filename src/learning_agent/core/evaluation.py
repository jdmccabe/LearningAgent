from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class ClassificationMetrics:
    label: str
    true_positive: int
    false_positive: int
    false_negative: int

    @property
    def precision(self) -> float:
        denominator = self.true_positive + self.false_positive
        return self.true_positive / denominator if denominator else 0.0

    @property
    def recall(self) -> float:
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else 0.0

    @property
    def f1(self) -> float:
        denominator = self.precision + self.recall
        return 2 * self.precision * self.recall / denominator if denominator else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "false_negative": self.false_negative,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


@dataclass(frozen=True)
class EvaluationReport:
    metrics: dict[str, Any]
    failures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"metrics": self.metrics, "failures": self.failures}


def classification_metrics(
    expected: dict[str, str], predicted: dict[str, str], labels: Iterable[str]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label in labels:
        tp = sum(
            1
            for key, expected_label in expected.items()
            if expected_label == label and predicted.get(key) == label
        )
        fp = sum(
            1
            for key, predicted_label in predicted.items()
            if predicted_label == label and expected.get(key) != label
        )
        fn = sum(
            1
            for key, expected_label in expected.items()
            if expected_label == label and predicted.get(key) != label
        )
        result[label] = ClassificationMetrics(label, tp, fp, fn).to_dict()
    total = len(expected)
    exact = sum(1 for key, value in expected.items() if predicted.get(key) == value)
    result["accuracy"] = round(exact / total, 4) if total else 0.0
    result["count"] = total
    return result


def link_metrics(
    expected_links: Iterable[tuple[str, str]], predicted_links: Iterable[tuple[str, str]]
) -> dict[str, Any]:
    expected = set(expected_links)
    predicted = set(predicted_links)
    tp = len(expected & predicted)
    fp = len(predicted - expected)
    fn = len(expected - predicted)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }

