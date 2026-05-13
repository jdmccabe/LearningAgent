from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Document:
    path: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    id: str
    document_path: str
    text: str
    start_line: int
    end_line: int
    metadata: dict[str, Any] = field(default_factory=dict)


def load_document(path: str | Path) -> Document:
    """Load simple local document formats without optional dependencies."""

    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in {".txt", ".md"}:
        return Document(str(p), p.read_text(encoding="utf-8"), {"format": suffix[1:]})
    if suffix == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        return Document(str(p), json.dumps(data, indent=2), {"format": "json", "data": data})
    if suffix == ".csv":
        rows = load_csv_rows(p)
        text = "\n".join(", ".join(f"{k}: {v}" for k, v in row.items()) for row in rows)
        return Document(str(p), text, {"format": "csv", "rows": rows})
    raise ValueError(
        f"Unsupported file type '{suffix}'. Convert to txt/md/csv/json first."
    )


def load_csv_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]


def write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def chunk_document(document: Document, max_lines: int = 40, overlap: int = 5) -> list[Chunk]:
    lines = document.text.splitlines()
    chunks: list[Chunk] = []
    if not lines:
        return chunks
    step = max(1, max_lines - overlap)
    for start in range(0, len(lines), step):
        end = min(len(lines), start + max_lines)
        chunk_lines = lines[start:end]
        chunks.append(
            Chunk(
                id=f"{Path(document.path).stem}:{start + 1}-{end}",
                document_path=document.path,
                text="\n".join(chunk_lines),
                start_line=start + 1,
                end_line=end,
            )
        )
        if end == len(lines):
            break
    return chunks

