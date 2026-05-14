from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import uuid4

from learning_agent.core.memory import MemoryPaths


@dataclass(frozen=True)
class ArtifactInfo:
    path: str
    name: str
    suffix: str
    size_bytes: int
    modified_iso: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def artifact_inventory(directory: str | Path) -> list[ArtifactInfo]:
    root = Path(directory)
    if not root.exists():
        return []
    artifacts: list[ArtifactInfo] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        stat = path.stat()
        artifacts.append(
            ArtifactInfo(
                path=str(path),
                name=path.name,
                suffix=path.suffix.lower(),
                size_bytes=stat.st_size,
                modified_iso=_format_mtime(stat.st_mtime),
            )
        )
    return artifacts


def load_review(review_path: str | Path) -> dict[str, Any]:
    return json.loads(Path(review_path).read_text(encoding="utf-8"))


def summarize_review(review_path: str | Path) -> dict[str, Any]:
    data = load_review(review_path)
    decisions = data.get("decisions", [])
    compliance = data.get("compliance_report", {})
    audit_findings = data.get("audit_findings", [])
    confidences = [
        value
        for value in (_numeric_value(item.get("confidence", 0.0)) for item in decisions)
        if value is not None
    ]
    missing_procedure = sum(1 for item in decisions if not item.get("procedure_reference"))
    missing_execution = sum(1 for item in decisions if not item.get("execution_artifacts"))
    missing_assurance = sum(1 for item in decisions if not item.get("assurance_standard") or not item.get("dal"))
    not_applicable = sum(1 for item in decisions if item.get("applicability") == "not_applicable")

    return {
        "review_path": str(review_path),
        "decision_count": len(decisions),
        "average_confidence": round(mean(confidences), 4) if confidences else 0.0,
        "low_confidence_count": sum(1 for value in confidences if value < 0.45),
        "not_applicable_count": not_applicable,
        "missing_procedure_count": missing_procedure,
        "missing_execution_artifact_count": missing_execution,
        "missing_assurance_count": missing_assurance,
        "audit_finding_count": len(audit_findings),
        "compliance_passed": bool(compliance.get("passed", False)),
        "compliance_failure_count": int(compliance.get("failure_count", 0)),
        "compliance_warning_count": int(compliance.get("warning_count", 0)),
        "agent_set_id": data.get("verification_artifact", {}).get("agent_set_id", ""),
        "impact_count": len(data.get("impacts", [])),
        "required_human_actions": required_human_actions(data),
    }


def required_human_actions(review_data: dict[str, Any]) -> list[dict[str, str]]:
    decisions = review_data.get("decisions", [])
    compliance = review_data.get("compliance_report", {})
    audit_findings = review_data.get("audit_findings", [])
    actions: list[dict[str, str]] = []

    if not decisions:
        return [
            {
                "priority": "required",
                "action": "Run workflow",
                "context": "No RVM decisions are present. Add inputs and run the workflow before review or approval.",
            }
        ]

    failure_count = int(compliance.get("failure_count", 0))
    if failure_count:
        actions.append(
            {
                "priority": "required",
                "action": "Resolve compliance failures",
                "context": f"{failure_count} deterministic compliance failure(s) must be closed before approval.",
            }
        )

    na_count = sum(1 for item in decisions if item.get("applicability") == "not_applicable")
    if na_count:
        actions.append(
            {
                "priority": "required",
                "action": "Approve not-applicable decisions",
                "context": f"{na_count} not-applicable decision(s) require architecture or boundary evidence review.",
            }
        )

    for action in _actions_from_rule_ids(compliance.get("findings", [])):
        actions.append(action)

    missing_evidence = sum(
        1
        for item in decisions
        if not item.get("procedure_reference")
        or (item.get("applicability") != "not_applicable" and not item.get("execution_artifacts"))
    )
    if missing_evidence:
        actions.append(
            {
                "priority": "required",
                "action": "Attach procedure and execution evidence",
                "context": f"{missing_evidence} decision(s) are missing procedure references or execution artifacts.",
            }
        )

    missing_assurance = sum(1 for item in decisions if not item.get("assurance_standard") or not item.get("dal"))
    if missing_assurance:
        actions.append(
            {
                "priority": "required",
                "action": "Complete assurance metadata",
                "context": f"{missing_assurance} decision(s) are missing assurance standard or DAL.",
            }
        )

    if audit_findings:
        actions.append(
            {
                "priority": "review",
                "action": "Review workflow audit findings",
                "context": f"{len(audit_findings)} low-confidence or policy finding(s) require reviewer disposition.",
            }
        )

    low_confidence = sum(
        1
        for item in decisions
        if (_numeric_value(item.get("confidence", 0.0)) or 0.0) < 0.45
    )
    if low_confidence:
        actions.append(
            {
                "priority": "review",
                "action": "Resolve low-confidence decisions",
                "context": f"{low_confidence} decision(s) have confidence below the review threshold.",
            }
        )

    if not actions:
        actions.append(
            {
                "priority": "ready",
                "action": "Record approval decision",
                "context": "No deterministic blocking findings were found. Record reviewed, approved, or baselined state.",
            }
        )
    return actions


def memory_inventory(paths: MemoryPaths) -> dict[str, Any]:
    files = {
        "shared_canonical_store": paths.reference_store,
        "learning_queue": learning_queue_path(paths),
        "workspace_canonical_store": paths.working_store,
        "workspace_manifest": paths.workspace_manifest,
    }
    return {
        "root": str(paths.root),
        "workspace_root": str(paths.workspace_root),
        "stores": {
            name: {
                "path": str(path),
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
                "record_count": _count_records(path),
            }
            for name, path in files.items()
        },
    }


def format_memory_inventory(inventory: dict[str, Any]) -> str:
    lines = [
        f"Memory root: {inventory.get('root', '')}",
        f"Workspace memory root: {inventory.get('workspace_root', '')}",
        "",
        "Stores:",
    ]
    stores = inventory.get("stores", {})
    for name, details in stores.items():
        label = name.replace("_", " ").title()
        exists = "yes" if details.get("exists") else "no"
        record_count = details.get("record_count")
        record_text = "" if record_count is None else f", records: {record_count}"
        lines.extend(
            [
                f"- {label}",
                f"  Path: {details.get('path', '')}",
                f"  Exists: {exists}, size: {details.get('size_bytes', 0)} bytes{record_text}",
            ]
        )
    return "\n".join(lines)


def format_score(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def learning_queue_path(paths: MemoryPaths) -> Path:
    return paths.root / "crystallized" / "learning_queue.jsonl"


def create_learning_candidate(
    *,
    task: str,
    input_text: str,
    bad_output: str,
    corrected_output: str,
    rationale: str,
    tags: list[str] | None = None,
    source: str = "ui",
) -> dict[str, Any]:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    return {
        "id": f"learn-{uuid4().hex[:12]}",
        "created_utc": now,
        "updated_utc": now,
        "status": "pending",
        "source": source,
        "task": task,
        "input_text": input_text,
        "bad_output": bad_output,
        "corrected_output": corrected_output,
        "rationale": rationale,
        "tags": tags or [],
        "applied_ids": [],
    }


def append_learning_candidate(path: str | Path, candidate: dict[str, Any]) -> str:
    queue_path = Path(path)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with queue_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(candidate) + "\n")
    return str(candidate["id"])


def load_learning_candidates(path: str | Path) -> list[dict[str, Any]]:
    queue_path = Path(path)
    if not queue_path.exists():
        return []
    candidates: list[dict[str, Any]] = []
    for line in queue_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        candidates.append(json.loads(line))
    return candidates


def update_learning_candidate_status(
    path: str | Path,
    candidate_ids: set[str],
    status: str,
    applied_ids: list[str] | None = None,
) -> int:
    queue_path = Path(path)
    candidates = load_learning_candidates(queue_path)
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    changed = 0
    for candidate in candidates:
        if candidate.get("id") not in candidate_ids:
            continue
        candidate["status"] = status
        candidate["updated_utc"] = now
        if applied_ids is not None:
            candidate["applied_ids"] = applied_ids
        changed += 1
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(
        "".join(json.dumps(candidate) + "\n" for candidate in candidates),
        encoding="utf-8",
    )
    return changed


def _numeric_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _actions_from_rule_ids(findings: list[dict[str, Any]]) -> list[dict[str, str]]:
    counts: dict[str, int] = {}
    for finding in findings:
        rule_id = str(finding.get("rule_id", ""))
        if rule_id:
            counts[rule_id] = counts.get(rule_id, 0) + 1

    grouped_actions = [
        (
            {"TRACE_PARENT", "TRACE_CHILD"},
            "Complete traceability links",
            "Supply exact parent and child IDs so the RVM has no orphan records.",
        ),
        (
            {"EVIDENCE_PROCEDURE"},
            "Anchor verification procedures",
            "Enter exact document IDs, revisions, sections, tables, or paragraphs for verification procedures.",
        ),
        (
            {"EVIDENCE_EXECUTION"},
            "Attach execution evidence",
            "Attach logs, signed reports, controlled files, or SHA-256 evidence hashes for executed verification.",
        ),
        (
            {"CRITERIA_OBJECTIVE", "CRITERIA_SUBJECTIVE"},
            "Make success criteria objective",
            "Replace subjective wording with bounded, measurable pass/fail criteria.",
        ),
        (
            {"CHANGE_LOG", "CHANGE_RATIONALE"},
            "Add change rationale",
            "Add timestamped author justification tied to architecture or certification basis.",
        ),
        (
            {"ASSURANCE_STANDARD", "ASSURANCE_LEVEL", "LIFECYCLE_OBJECTIVES"},
            "Complete assurance mapping",
            "Record certification basis, DAL, and lifecycle objectives for each affected requirement.",
        ),
        (
            {"APPLICABILITY_EVIDENCE"},
            "Cite non-applicability evidence",
            "Cite exact architecture or boundary evidence for each not-applicable decision.",
        ),
    ]

    actions: list[dict[str, str]] = []
    for rule_ids, action, context in grouped_actions:
        count = sum(counts.get(rule_id, 0) for rule_id in rule_ids)
        if count:
            actions.append(
                {
                    "priority": "required",
                    "action": action,
                    "context": f"{context} Affected finding count: {count}.",
                }
            )
    return actions


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _count_records(path: Path) -> int | None:
    if not path.exists():
        return 0
    if path.suffix == ".jsonl":
        return _count_jsonl(path)
    if path.suffix not in {".sqlite", ".db"}:
        return None
    try:
        with sqlite3.connect(path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM canonical_records").fetchone()
    except sqlite3.DatabaseError:
        return None
    return int(row[0])


def _format_mtime(timestamp: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")
