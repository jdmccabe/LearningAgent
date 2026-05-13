from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from learning_agent.core.documents import chunk_document, load_document
from learning_agent.core.embeddings import Embedder, HashingEmbedder
from learning_agent.core.vector_store import JsonlVectorStore, SearchResult


@dataclass(frozen=True)
class CorrectionPair:
    task: str
    input_text: str
    bad_output: str
    corrected_output: str
    rationale: str = ""
    tags: list[str] = field(default_factory=list)
    metrics_delta: dict[str, float] = field(default_factory=dict)

    def to_text(self) -> str:
        return "\n".join(
            [
                f"Task: {self.task}",
                f"Input: {self.input_text}",
                f"Bad output: {self.bad_output}",
                f"Corrected output: {self.corrected_output}",
                f"Rationale: {self.rationale}",
            ]
        )

    def to_metadata(self) -> dict[str, Any]:
        return asdict(self)


class ReferenceMemory:
    def __init__(self, path: str | Path, embedder: Embedder | None = None) -> None:
        self.store = JsonlVectorStore(path, embedder or HashingEmbedder())

    def index_files(self, paths: list[str | Path], max_lines: int = 40, overlap: int = 5) -> list[str]:
        texts: list[str] = []
        metadatas: list[dict[str, Any]] = []
        for path in paths:
            document = load_document(path)
            for chunk in chunk_document(document, max_lines=max_lines, overlap=overlap):
                texts.append(chunk.text)
                metadatas.append(
                    {
                        "id": chunk.id,
                        "kind": "reference",
                        "source": chunk.document_path,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                    }
                )
        return self.store.add_texts(texts, metadatas)

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        return self.store.search(query, top_k=top_k, filters={"kind": "reference"})


class CorrectionMemory:
    def __init__(self, path: str | Path, embedder: Embedder | None = None) -> None:
        self.store = JsonlVectorStore(path, embedder or HashingEmbedder())

    def add_pairs(self, pairs: list[CorrectionPair]) -> list[str]:
        return self.store.add_texts(
            [pair.to_text() for pair in pairs],
            [{**pair.to_metadata(), "kind": "correction"} for pair in pairs],
        )

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        return self.store.search(query, top_k=top_k, filters={"kind": "correction"})


@dataclass(frozen=True)
class MemoryPaths:
    root: Path
    reference_store: Path
    crystallized_store: Path
    workspace_root: Path
    working_store: Path
    workspace_manifest: Path


def default_memory_paths(
    workspace: str | Path | None = None, root: str | Path | None = None
) -> MemoryPaths:
    """Return persistent memory paths.

    Reference and crystallized memories are shared inside this repo. Working
    memory is isolated per workspace path to avoid project cross-contamination.
    """

    workspace_path = Path(workspace or Path.cwd()).resolve()
    memory_root = Path(root or ".learning_agent").resolve()
    workspace_id = _workspace_id(workspace_path)
    workspace_root = memory_root / "workspaces" / workspace_id
    return MemoryPaths(
        root=memory_root,
        reference_store=memory_root / "reference" / "reference_memory.jsonl",
        crystallized_store=memory_root / "crystallized" / "learned_corrections.jsonl",
        workspace_root=workspace_root,
        working_store=workspace_root / "working_memory.jsonl",
        workspace_manifest=workspace_root / "manifest.json",
    )


class WorkspaceMemory:
    """Project-level working memory isolated to a single workspace."""

    def __init__(
        self,
        workspace: str | Path | None = None,
        root: str | Path | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self.paths = default_memory_paths(workspace=workspace, root=root)
        self.embedder = embedder or HashingEmbedder()
        self.store = JsonlVectorStore(self.paths.working_store, self.embedder)
        self.paths.workspace_root.mkdir(parents=True, exist_ok=True)
        if not self.paths.workspace_manifest.exists():
            self.paths.workspace_manifest.write_text(
                json.dumps(
                    {
                        "workspace": str(Path(workspace or Path.cwd()).resolve()),
                        "workspace_id": self.paths.workspace_root.name,
                        "purpose": "Project-scoped working memory. Do not share across workspaces.",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

    def index_project_files(self, paths: list[str | Path], max_lines: int = 40, overlap: int = 5) -> list[str]:
        texts: list[str] = []
        metadatas: list[dict[str, Any]] = []
        for path in paths:
            document = load_document(path)
            for chunk in chunk_document(document, max_lines=max_lines, overlap=overlap):
                texts.append(chunk.text)
                metadatas.append(
                    {
                        "id": chunk.id,
                        "kind": "working",
                        "source": chunk.document_path,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "workspace_id": self.paths.workspace_root.name,
                    }
                )
        return self.store.add_texts(texts, metadatas)

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        return self.store.search(
            query,
            top_k=top_k,
            filters={"kind": "working", "workspace_id": self.paths.workspace_root.name},
        )


def _workspace_id(path: Path) -> str:
    digest = hashlib.sha256(str(path).lower().encode("utf-8")).hexdigest()[:16]
    return f"{path.name}-{digest}"
