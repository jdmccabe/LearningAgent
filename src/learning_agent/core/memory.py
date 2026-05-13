from __future__ import annotations

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

