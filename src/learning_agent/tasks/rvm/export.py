from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


RVM_EXPORT_COLUMNS = [
    "requirement_id",
    "parent_ids",
    "child_ids",
    "applicability",
    "verification_method",
    "procedure_reference",
    "execution_artifacts",
    "success_criteria",
    "assurance_standard",
    "dal",
    "lifecycle_objectives",
    "rationale",
    "change_log",
]


def export_rvm_csv(rvm_path: str | Path, out: str | Path) -> None:
    data = json.loads(Path(rvm_path).read_text(encoding="utf-8"))
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RVM_EXPORT_COLUMNS)
        writer.writeheader()
        for decision in data.get("decisions", []):
            writer.writerow(_export_row(decision))


def _export_row(decision: dict[str, Any]) -> dict[str, str]:
    return {
        "requirement_id": str(decision.get("requirement_id", "")),
        "parent_ids": _join(decision.get("parent_ids", [])),
        "child_ids": _join(decision.get("child_ids", [])),
        "applicability": str(decision.get("applicability", "")),
        "verification_method": str(decision.get("verification_method", "")),
        "procedure_reference": str(decision.get("procedure_reference", "")),
        "execution_artifacts": _join(decision.get("execution_artifacts", [])),
        "success_criteria": str(decision.get("success_criteria", "")),
        "assurance_standard": str(decision.get("assurance_standard", "")),
        "dal": str(decision.get("dal", "")),
        "lifecycle_objectives": _join(decision.get("lifecycle_objectives", [])),
        "rationale": str(decision.get("rationale", "")),
        "change_log": json.dumps(decision.get("change_log", []), sort_keys=True),
    }


def _join(values: Any) -> str:
    if isinstance(values, list):
        return ";".join(str(item) for item in values)
    return str(values or "")

