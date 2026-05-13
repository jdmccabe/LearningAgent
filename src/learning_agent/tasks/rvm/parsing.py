from __future__ import annotations

import re
from pathlib import Path

from learning_agent.core.documents import Document, load_table_rows, load_document
from learning_agent.tasks.rvm.schema import Requirement, RvmDecision


ID_KEYS = ("id", "requirement_id", "req_id", "identifier", "object_identifier", "absolute_number")
TEXT_KEYS = ("text", "requirement", "shall", "description", "object_text", "primary_text", "statement")
PARENT_KEYS = ("parent_id", "parent", "parent_requirement", "parent_identifier")
STANDARD_KEYS = ("standard", "source_standard", "source", "module")
ASSURANCE_KEYS = ("assurance_standard", "standard_basis", "certification_basis")
DAL_KEYS = ("dal", "design_assurance_level", "software_level", "hardware_level")
OBJECTIVE_KEYS = ("lifecycle_objectives", "objectives", "do_objectives")


def parse_requirements(path: str | Path) -> list[Requirement]:
    p = Path(path)
    if p.suffix.lower() in {".csv", ".tsv", ".xlsx", ".reqif", ".reqifz", ".xml"}:
        return _parse_requirements_table(p)
    return _parse_requirements_text(load_document(p))


def parse_good_rvm(path: str | Path) -> list[RvmDecision]:
    rows = load_table_rows(path)
    decisions: list[RvmDecision] = []
    for row in rows:
        normalized = {_clean_key(k): (v or "").strip() for k, v in row.items()}
        req_id = _first(normalized, ID_KEYS)
        if not req_id:
            continue
        decisions.append(
            RvmDecision(
                requirement_id=req_id,
                applicability=normalized.get("applicability", "unknown") or "unknown",
                verification_method=normalized.get("verification_method", "unknown") or "unknown",
                rationale=normalized.get("rationale", ""),
                confidence=1.0,
                trace_links=_split_links(normalized.get("trace_links", "")),
            )
        )
    return decisions


def _parse_requirements_table(path: Path) -> list[Requirement]:
    rows = load_table_rows(path)
    requirements: list[Requirement] = []
    for index, row in enumerate(rows, start=1):
        normalized = {_clean_key(k): (v or "").strip() for k, v in row.items()}
        req_id = _first(normalized, ID_KEYS) or f"REQ-{index:04d}"
        text = _first(normalized, TEXT_KEYS)
        if not text:
            continue
        requirements.append(
            Requirement(
                id=req_id,
                text=text,
                source_document=str(path),
                parent_id=_first(normalized, PARENT_KEYS) or None,
                standard=_first(normalized, STANDARD_KEYS) or None,
                assurance_standard=_first(normalized, ASSURANCE_KEYS),
                dal=_first(normalized, DAL_KEYS),
                lifecycle_objectives=_split_links(_first(normalized, OBJECTIVE_KEYS)),
                metadata={k: v for k, v in normalized.items() if k not in set(ID_KEYS + TEXT_KEYS)},
            )
        )
    return requirements


def _parse_requirements_text(document: Document) -> list[Requirement]:
    requirements: list[Requirement] = []
    pattern = re.compile(
        r"^\s*(?P<id>[A-Za-z]{1,8}[-_ ]?\d+(?:[.\-_]\d+)*)\s*[:\-]\s*(?P<text>.+)$"
    )
    for index, line in enumerate(document.text.splitlines(), start=1):
        match = pattern.match(line)
        if not match:
            continue
        req_id = match.group("id").replace(" ", "-")
        text = match.group("text").strip()
        parent = _infer_parent(req_id)
        requirements.append(
            Requirement(
                id=req_id,
                text=text,
                source_document=document.path,
                parent_id=parent,
                metadata={"line": index},
            )
        )
    return requirements


def _infer_parent(req_id: str) -> str | None:
    for separator in (".", "-", "_"):
        if separator in req_id:
            parts = req_id.split(separator)
            if len(parts) > 2:
                return separator.join(parts[:-1])
    return None


def _clean_key(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _first(row: dict[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        if row.get(key):
            return row[key]
    return ""


def _split_links(value: str) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[;,]", value) if item.strip()]
